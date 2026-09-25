"""Standalone, standard-library-only host helper. Installed as a root-owned copy.

Never import application code here: the service user owns the application checkout.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

MAX_CONFIG = 256_000
UNIT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service")
PROTECTED = {
    "nginx.service",
    "ssh.service",
    "sshd.service",
    "vps-deployer.service",
    "dbus.service",
    "systemd-logind.service",
    "NetworkManager.service",
    "networking.service",
    "ufw.service",
    "firewalld.service",
    "docker.service",
    "containerd.service",
    "reboot.service",
    "poweroff.service",
    "halt.service",
    "rescue.service",
    "emergency.service",
    "kexec.service",
}


class HostError(RuntimeError):
    pass


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostError(f"{argv[0]} is unavailable or timed out") from exc


def revision(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def import_certificate(payload: dict, base=Path("/etc/ssl/vps-deployer"), runner=run) -> dict:
    """Copy validated PEM files to unique, root-private paths; never replace active keys."""
    name = payload.get("project", "")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", name):
        raise HostError("Invalid project name")
    hosts = payload.get("hostnames", [])
    if not 1 <= len(hosts) <= 20 or any(
        not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", h) for h in hosts
    ):
        raise HostError("Provide 1–20 valid certificate hostnames")
    contents = []
    for field in ("certificate", "certificate_key"):
        path = Path(payload.get(field, ""))
        if (
            not path.is_absolute()
            or ".." in path.parts
            or path.suffix not in {".pem", ".crt", ".key"}
        ):
            raise HostError("Use absolute PEM certificate/key source paths")
        # O_NONBLOCK prevents a FIFO/device from hanging the privileged helper.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise HostError("Certificate sources must be regular files")
            data = source.read(1_000_001)
        if not data or len(data) > 1_000_000:
            raise HostError("Certificate source is empty or too large")
        contents.append(data)
    dest = base / name
    for parent in (dest, *dest.parents):
        if not parent.exists() and not parent.is_symlink():
            continue
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid():
            raise HostError(
                "Certificate destination must be owned by the helper user without symlinks"
            )
        if info.st_mode & 0o022:
            raise HostError("Certificate destination must not be group/world writable")
        if parent == base.parent:
            break
    base.mkdir(exist_ok=True, mode=0o700)
    dest.mkdir(exist_ok=True, mode=0o700)
    paths = []
    try:
        for prefix, data in zip(("cert-", "key-"), contents, strict=True):
            fd, filename = tempfile.mkstemp(prefix=prefix, suffix=".pem", dir=dest)
            paths.append(Path(filename))
            with os.fdopen(fd, "wb") as output:
                output.write(data)
        cert, key = map(str, paths)
        checks = [
            ["openssl", "x509", "-in", cert, "-noout", "-checkend", "0"],
            *[
                [
                    "openssl",
                    "verify",
                    "-no-CAfile",
                    "-no-CApath",
                    "-partial_chain",
                    "-trusted",
                    cert,
                    "-verify_hostname",
                    host,
                    cert,
                ]
                for host in hosts
            ],
        ]
        if any(runner(command).returncode for command in checks):
            raise HostError(
                "Certificate is invalid, expired, not yet valid, or does not cover every hostname"
            )
        public = runner(["openssl", "x509", "-in", cert, "-pubkey", "-noout"])
        private = runner(["openssl", "pkey", "-in", key, "-passin", "pass:", "-pubout"])
        if public.returncode or private.returncode or public.stdout != private.stdout:
            raise HostError("Certificate and unencrypted private key must match")
        paths[0].chmod(0o644)
        return {"certificate": cert, "certificate_key": key}
    except Exception:
        for path in paths:
            path.unlink(missing_ok=True)
        raise


def config_metadata(content: str) -> dict:
    def values(directive):
        cleaned = re.sub(r"(?m)^\s*#.*$", "", content)
        return re.findall(r"(?:^|[;{}])\s*(?:" + directive + r")\s+([^;{}]+);", cleaned)

    groups = {}
    for name, body in re.findall(r"\bupstream\s+(\S+)\s*\{([^{}]*)\}", content, re.S):
        groups[name] = re.findall(r"\bserver\s+([^;\s]+)", body)
    return {
        "upstream_groups": groups,
        "domains": [v for group in values("server_name") for v in group.split()],
        "roots": values("root"),
        "upstreams": values("proxy_pass|fastcgi_pass"),
        "certificates": values("ssl_certificate"),
        "keys": values("ssl_certificate_key"),
    }


def handover_content(content: str, project: str, port: int, runtime: str, apps_root: Path) -> str:
    """Change only one unambiguous app destination, preserving all other site settings."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", project) or not 33000 <= port <= 33999:
        raise HostError("Invalid handover project or port")
    metadata = config_metadata(content)
    rows = directives(content)
    if any(
        row[0] in {"fastcgi_pass", "uwsgi_pass", "grpc_pass", "upstream", "alias"} for row in rows
    ):
        raise HostError(
            "Handover supports a single direct HTTP proxy or static root, "
            "not FastCGI, aliases or upstream groups"
        )
    roots = set(metadata["roots"]) - {"/var/www/certbot"}
    if runtime in {"static", "vite"}:
        if metadata["upstreams"] or len(roots) != 1:
            raise HostError("Static handover requires exactly one application root and no proxy")
        old = next(iter(roots))
        target = apps_root / project / "current"
        if runtime == "vite":
            target /= "dist"
        replacement = str(target)
        directive = "root"
    else:
        targets = set(metadata["upstreams"])
        if len(targets) != 1 or roots:
            raise HostError("Proxy handover requires exactly one backend and no application roots")
        old = next(iter(targets))
        match = re.fullmatch(
            r"http://(?:127\.0\.0\.1|localhost|\[::1\]):([0-9]+)(/[^\s;{}]*)?", old
        )
        if not match or int(match[1]) == port:
            raise HostError(
                "Choose a direct loopback HTTP backend and a different new application port"
            )
        replacement = f"http://127.0.0.1:{port}" + (match[2] or "")
        directive = "proxy_pass"
    # Values must be plain, unquoted paths/URLs so replacement is unambiguous.
    if any(c in old for c in "\"'\n\r$"):
        raise HostError("Variable or quoted app destinations need manual migration")
    return re.sub(
        r"(\b" + directive + r"\s+)" + re.escape(old) + r"(?=\s*;)",
        lambda m: m[1] + replacement,
        content,
    )


def directives(content: str) -> list[list[str]]:
    lexer = shlex.shlex(content, posix=True, punctuation_chars=";{}")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    rows, row = [], []
    try:
        for token in lexer:
            if token and all(c in ";{}" for c in token):
                if row:
                    rows.append(row)
                    row = []
            else:
                row.append(token)
    except ValueError as exc:
        raise HostError("Unterminated quote in Nginx configuration") from exc
    if row:
        rows.append(row)
    return rows


def validate_edit(old: str, new: str) -> None:
    if not new.strip() or len(new.encode()) > MAX_CONFIG or "\x00" in new:
        raise HostError("Config must contain 1–256000 bytes and no NUL characters")
    # Only permit routing/tuning directives. Everything else must remain identical
    # to the root-installed original; nginx -t alone is not a privilege boundary.
    editable = set(
        "server location listen server_name client_max_body_size try_files return "
        "proxy_http_version proxy_set_header proxy_read_timeout proxy_send_timeout "
        "proxy_connect_timeout proxy_buffering proxy_buffers proxy_buffer_size "
        "proxy_redirect proxy_cache_bypass proxy_no_cache proxy_pass "
        "fastcgi_pass fastcgi_index fastcgi_param fastcgi_read_timeout "
        "root alias index autoindex ssl_protocols ssl_ciphers ssl_prefer_server_ciphers "
        "add_header expires gzip gzip_types gzip_min_length keepalive_timeout "
        "send_timeout client_body_timeout client_header_timeout".split()
    )
    before, after = directives(old), directives(new)
    if [r for r in before if r[0] not in editable] != [r for r in after if r[0] not in editable]:
        raise HostError(
            "Keep existing include, certificate, log and global directives unchanged. "
            "This editor permits routing and tuning, not privileged module/file changes."
        )
    for row in after:
        if row in before:
            continue
        if row[0] in {"root", "alias"}:
            if len(row) != 2 or "$" in row[1] or ".." in Path(row[1]).parts:
                raise HostError("Invalid document root")
            resolved = Path(row[1]).resolve()
            if not any(resolved.is_relative_to(p) for p in ("/var/www", "/srv")):
                raise HostError("New document roots must be under /var/www or /srv")
        if row[0] in {"proxy_pass", "fastcgi_pass"}:
            if len(row) != 2 or not re.fullmatch(
                r"(?:https?://)?(?:127\.0\.0\.1|localhost|\[::1\]):[0-9]{1,5}(?:/[^\s]*)?", row[1]
            ):
                raise HostError("New upstreams must use a loopback TCP address")
        if row[0] == "listen" and (
            len(row) < 2 or not re.fullmatch(r"(?:[0-9.]+:|\[::\]:)?[0-9]{1,5}", row[1])
        ):
            raise HostError("Only TCP listen addresses can be edited")


class NginxHost:
    def __init__(
        self,
        root: Path = Path("/etc/nginx"),
        runner=run,
        backup_root: Path = Path("/var/backups/vps-deployer/nginx"),
        lock: Path = Path("/run/lock/vps-deployer-nginx.lock"),
    ):
        self.root, self.runner, self.backup_root, self.lock = root, runner, backup_root, lock

    @contextmanager
    def locked(self):
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        with self.lock.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def resolve(self, relative: str) -> Path:
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise HostError("Choose a discovered Nginx config")
        path = self.root / relative
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise HostError("Config is missing or has a broken symlink") from exc
        if not resolved.is_relative_to(self.root.resolve()) or not resolved.is_file():
            raise HostError("Config must be a regular file inside the Nginx directory")
        if resolved.suffix in {".pem", ".key", ".crt"} or resolved.stat().st_size > MAX_CONFIG:
            raise HostError("Not an editable Nginx config")
        return resolved

    def read(self, relative: str) -> dict:
        inventory = self.inventory()
        item = next((r for r in inventory["configs"] if r["id"] == relative), None)
        if item is None or item.get("error"):
            raise HostError("Config is unavailable; refresh the inventory")
        content = self.resolve(relative).read_text()
        return {
            **item,
            "content": content,
            "revision": revision(content),
            "test": inventory["test"],
        }

    def test(self) -> dict:
        try:
            result = self.runner(["nginx", "-T"])
            loaded = re.findall(r"^# configuration file (.+):$", result.stdout, re.M)
            return {"ok": result.returncode == 0, "detail": result.stderr[-8000:], "loaded": loaded}
        except HostError as exc:
            return {"ok": None, "detail": str(exc), "loaded": []}

    def inventory(self) -> dict:
        test = self.test()
        candidates = set(self.root.rglob("*.conf")) if self.root.exists() else set()
        disabled_root = self.root / "disabled-sites"
        if disabled_root.is_dir():
            candidates.update(p for p in disabled_root.rglob("*") if not p.is_dir())
        for directory in ("sites-available", "sites-enabled", "snippets"):
            base = self.root / directory
            if base.is_dir():
                candidates.update(p for p in base.iterdir() if not p.is_dir())
        loaded = set(test["loaded"])
        candidates.update(Path(p) for p in loaded if Path(p).is_relative_to(self.root))
        rows, by_path = [], {}
        for path in sorted(candidates):
            if any(part.startswith(".") for part in path.relative_to(self.root).parts):
                continue
            relative = str(path.relative_to(self.root))
            try:
                target = self.resolve(relative)
                if target in by_path:
                    by_path[target]["aliases"].append(relative)
                    continue
                content = target.read_text()
                row = {
                    "id": str(target.relative_to(self.root.resolve())),
                    "path": str(target),
                    "aliases": [relative],
                    "error": None,
                    **config_metadata(content),
                }
                by_path[target] = row
                rows.append(row)
            except (HostError, OSError, UnicodeError) as exc:
                rows.append(
                    {
                        "id": relative,
                        "path": str(path),
                        "aliases": [relative],
                        "error": str(exc),
                        "domains": [],
                        "roots": [],
                        "upstreams": [],
                        "certificates": [],
                        "keys": [],
                    }
                )
        for row in rows:
            # -T lists included files on success. On failure, enabled means configured
            # for inclusion, NOT proof that an individual config is valid.
            row["enabled"] = (
                row["path"] in loaded
                or any(
                    a.startswith("sites-enabled/")
                    or a.startswith("conf.d/")
                    and a.endswith(".conf")
                    for a in row["aliases"]
                )
                or row["id"] == "nginx.conf"
            )
            implicated = row["path"] + ":" in test["detail"]
            included = row["path"] in loaded or any(
                str(self.root / alias) in loaded for alias in row["aliases"]
            )
            row["included"] = included
            row["status"] = (
                "error"
                if row["error"] or implicated
                else "ok"
                if included and test["ok"] is True
                else "unchecked"
                if not row["enabled"] or test["ok"] is True and not included
                else "unknown"
            )
            row["site"] = bool(row["domains"]) and any(
                row["id"].startswith(p)
                for p in ("sites-available/", "sites-enabled/", "conf.d/", "disabled-sites/")
            )
        groups = {}
        for row in rows:
            groups.update(row.get("upstream_groups", {}))
        for row in rows:
            row["upstream_targets"] = []
            for upstream in row["upstreams"]:
                name = re.sub(r"^https?://", "", upstream).split("/", 1)[0]
                row["upstream_targets"].extend(groups.get(name, [upstream]))
        return {"configs": rows, "test": test}

    def reload(self):
        test = self.runner(["nginx", "-t"])
        if test.returncode:
            raise HostError(test.stderr[-8000:] or "Nginx validation failed")
        result = self.runner(["systemctl", "reload", "nginx"])
        if result.returncode:
            raise HostError(result.stderr[-8000:] or "Nginx reload failed")

    def _backup(self, paths: list[Path]) -> Path:
        self.backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory = Path(tempfile.mkdtemp(prefix="site-", dir=self.backup_root))
        manifest = []
        for index, path in enumerate(paths):
            exists = path.exists() or path.is_symlink()
            manifest.append({"path": str(path), "exists": exists, "slot": str(index)})
            if exists:
                shutil.copy2(path, directory / str(index), follow_symlinks=False)
        (directory / "manifest.json").write_text(json.dumps(manifest))
        return directory

    def restore(self, directory: Path):
        for item in json.loads((directory / "manifest.json").read_text()):
            path = Path(item["path"])
            path.unlink(missing_ok=True)
            if item["exists"]:
                shutil.copy2(directory / item["slot"], path, follow_symlinks=False)

    def action(self, payload: dict) -> dict:
        with self.locked():
            action = payload.get("action")
            if action == "reload":
                self.reload()
                return {"message": "Nginx tested and reloaded"}
            if action == "test":
                return {
                    "test": self.test(),
                    "message": "Checked the complete active Nginx configuration",
                }
            item = self.read(payload.get("id", ""))
            path = self.resolve(item["id"])
            if payload.get("revision") != item["revision"]:
                raise HostError(
                    "Config changed since you opened it. Reload before saving or acting."
                )
            if action not in {"save", "save-reload", "enable", "disable", "delete"}:
                raise HostError("Unknown Nginx action")
            if action not in {"save", "save-reload"} and not item["site"]:
                raise HostError("Only website configs can be enabled, disabled or deleted")
            if path.name == "vps-deployer.conf" and action in {"disable", "delete"}:
                raise HostError("Manage dashboard access in Settings")
            links = [self.root / a for a in item["aliases"] if (self.root / a).is_symlink()]
            paths = list(dict.fromkeys([path, *links]))
            disabled = self.root / "disabled-sites" / path.parent.name / path.name
            target_link = self.root / "sites-enabled" / path.name
            restored = None
            if action == "enable" and item["id"].startswith("disabled-sites/"):
                restored = self.root / path.parent.name / path.name
                if path.parent.name not in {"conf.d", "sites-enabled"}:
                    raise HostError("Unknown original site directory")
                if restored.exists() or restored.is_symlink():
                    raise HostError("A config already exists at the original site path")
                paths.append(restored)
            if action == "enable" and path.parent.name == "sites-available":
                if target_link.exists() or target_link.is_symlink():
                    raise HostError("An enabled file with this name already exists")
                paths.append(target_link)
            if action == "disable" and path.parent.name in {"conf.d", "sites-enabled"}:
                if disabled.exists():
                    raise HostError("A disabled config with this name already exists")
                paths.append(disabled)
            content = payload.get("content", "").replace("\r\n", "\n")
            if action.startswith("save"):
                validate_edit(item["content"], content)
            backup = self._backup(paths)
            try:
                if action.startswith("save"):
                    path.write_text(content)
                elif action == "enable":
                    if restored is not None:
                        path.rename(restored)
                    elif path.parent.name == "sites-available":
                        target_link.symlink_to(path)
                    else:
                        raise HostError("Only sites-available files can be enabled here")
                elif action in {"disable", "delete"}:
                    for link in links:
                        link.unlink()
                    if action == "delete":
                        path.unlink()
                    elif path.parent.name in {"conf.d", "sites-enabled"}:
                        disabled.parent.mkdir(parents=True, exist_ok=True)
                        path.rename(disabled)
                result = self.runner(["nginx", "-t"])
                if result.returncode:
                    raise HostError(result.stderr[-8000:] or "Nginx validation failed")
                if action != "save":
                    self.reload()
            except (HostError, OSError) as exc:
                self.restore(backup)
                raise HostError(f"{exc}\nPrevious files restored. Backup: {backup}") from exc
            return {
                "message": f"{action} completed",
                "backup": str(backup),
                "reloaded": action != "save",
                "validation": "active configuration",
                "id": str(
                    (restored or (disabled if disabled.exists() else path)).relative_to(self.root)
                ),
            }

    def handover(
        self, payload: dict, apps_root=Path("/var/www/apps"), ssl_root=Path("/etc/ssl/vps-deployer")
    ) -> dict:
        with self.locked():
            item = self.read(payload.get("id", ""))
            if (
                not item["site"]
                or not item["enabled"]
                or Path(item["id"]).name.startswith("vps-deployer")
            ):
                raise HostError("Select an enabled, unmanaged website")
            if item["revision"] != payload.get("revision"):
                raise HostError("Source config changed. Review and queue handover again.")
            content = handover_content(
                item["content"],
                payload["project"],
                int(payload["port"]),
                payload["runtime"],
                apps_root,
            )
            units = payload.get("units", [])
            if not isinstance(units, list) or len(units) > 10:
                raise HostError("Select up to 10 old application services")
            active = []
            for unit in units:
                props = unit_details(unit, self.runner)
                if service_protected(props.get("Id", unit)) or props.get("Id", unit).startswith(
                    "vps-deployer-"
                ):
                    raise HostError(
                        "Cannot stop infrastructure or deployed project services during handover"
                    )
                if props.get("ActiveState") == "active":
                    active.append(unit)
            certificates, keys = set(item["certificates"]), set(item["keys"])
            copied = {}
            if certificates or keys:
                if len(certificates) != 1 or len(keys) != 1:
                    raise HostError("Handover requires exactly one certificate/key pair")
                copied = import_certificate(
                    {
                        "project": payload["project"],
                        "hostnames": list(dict.fromkeys(item["domains"])),
                        "certificate": next(iter(certificates)),
                        "certificate_key": next(iter(keys)),
                    },
                    base=ssl_root,
                )
                for directive, value in [
                    ("ssl_certificate", copied["certificate"]),
                    ("ssl_certificate_key", copied["certificate_key"]),
                ]:
                    content = re.sub(
                        r"(\b" + directive + r"\s+)[^;{}]+;",
                        lambda m, v=value: m[1] + v + ";",
                        content,
                    )
            path = self.resolve(item["id"])
            backup = self._backup([path])
            recovery = {"id": item["id"], "revision": revision(content), "units": active}
            (backup / "handover.json").write_text(json.dumps(recovery))
            stopped = False
            try:
                path.write_text(content)
                self.reload()
                stopped = True
                for unit in active:
                    result = service_action({"unit": unit, "action": "stop"}, self.runner)
                    if result["service"].get("ActiveState") not in {"inactive", "failed"}:
                        raise HostError("Old service did not stop: " + unit)
            except (HostError, OSError) as exc:
                recovery_errors = []
                if stopped:
                    for unit in active:
                        try:
                            service_action({"unit": unit, "action": "start"}, self.runner)
                        except HostError as recovery_error:
                            recovery_errors.append(str(recovery_error))
                if recovery_errors:
                    raise HostError(
                        f"{exc}; old services could not be restarted: {recovery_errors}. "
                        f"Replacement routing retained for recovery. Backup: {backup}"
                    ) from exc
                self.restore(backup)
                try:
                    self.reload()
                except HostError as recovery_error:
                    raise HostError(
                        f"{exc}; recovery reload failed: {recovery_error}. Backup: {backup}"
                    ) from exc
                raise HostError(f"{exc}; previous website restored. Backup: {backup}") from exc
            return {
                "id": item["id"],
                "backup": str(backup),
                "content": content,
                "stopped": active,
                **copied,
            }

    def rollback_handover(self, payload: dict) -> dict:
        with self.locked():
            backup = Path(payload.get("backup", ""))
            if (
                backup.parent != self.backup_root
                or not re.fullmatch(r"site-[A-Za-z0-9_-]+", backup.name)
                or backup.is_symlink()
            ):
                raise HostError("Invalid handover backup")
            recovery = json.loads((backup / "handover.json").read_text())
            item = self.read(recovery["id"])
            if item["revision"] != recovery["revision"]:
                raise HostError("Website changed after handover; restore manually from backup")
            for unit in recovery["units"]:
                service_action({"unit": unit, "action": "start"}, self.runner)
            self.restore(backup)
            self.reload()
            return {"message": "Previous website and services restored"}

    def attach_certificate(self, payload: dict, ssl_root=Path("/etc/ssl/vps-deployer")) -> dict:
        with self.locked():
            item = self.read(payload.get("id", ""))
            if item["revision"] != payload.get("revision"):
                raise HostError("Config changed. Reload before importing the certificate.")
            if (
                not item["site"]
                or len(set(item["certificates"])) != 1
                or len(set(item["keys"])) != 1
            ):
                raise HostError(
                    "Transferred sites must already have one explicit TLS certificate/key pair"
                )
            copied = import_certificate(
                {**payload, "hostnames": list(dict.fromkeys(item["domains"]))}, base=ssl_root
            )
            content = item["content"]
            for directive, field in [
                ("ssl_certificate", "certificate"),
                ("ssl_certificate_key", "certificate_key"),
            ]:
                content = re.sub(
                    r"(\b" + directive + r"\s+)[^;{}]+;",
                    lambda m, value=copied[field]: m[1] + value + ";",
                    content,
                )
            path = self.resolve(item["id"])
            backup = self._backup([path])
            try:
                path.write_text(content)
                self.reload()
            except (HostError, OSError) as exc:
                self.restore(backup)
                try:
                    self.reload()
                except HostError as recovery_error:
                    raise HostError(
                        f"{exc}; recovery reload failed: {recovery_error}. Backup: {backup}"
                    ) from exc
                raise HostError(
                    f"{exc}; previous certificate config restored. Backup: {backup}"
                ) from exc
            return {**copied, "backup": str(backup)}


def unit_details(unit: str, runner=run) -> dict:
    if not UNIT_RE.fullmatch(unit) or ".." in unit:
        raise HostError("Invalid service name")
    result = runner(
        [
            "systemctl",
            "show",
            unit,
            "--no-pager",
            "--property=Id,LoadState,ActiveState,SubState,MainPID,FragmentPath,WorkingDirectory,User,UnitFileState",
        ]
    )
    if result.returncode:
        raise HostError("Service is unavailable")
    props = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if props.get("LoadState") == "not-found":
        raise HostError("Service is not installed")
    return props


def service_protected(unit: str) -> bool:
    return unit in PROTECTED or unit.startswith(
        ("systemd-", "dbus", "ssh", "network", "NetworkManager")
    )


def service_action(payload: dict, runner=run) -> dict:
    unit, action = payload.get("unit", ""), payload.get("action")
    props = unit_details(unit, runner)
    if service_protected(props.get("Id", unit)):
        raise HostError(
            "This infrastructure service is protected; use its dedicated settings or SSH"
        )
    if action not in {"start", "stop", "restart"}:
        raise HostError("Unsupported service action")
    result = runner(["systemctl", action, "--", unit])
    if result.returncode:
        raise HostError(result.stderr[-4000:] or "Service action failed")
    return {"message": f"{unit}: {action}", "service": unit_details(unit, runner)}


def service_inventory(runner=run) -> dict:
    errors, services, listeners, processes = [], [], [], []
    try:
        result = runner(
            ["systemctl", "list-units", "--all", "--type=service", "--no-pager", "--output=json"]
        )
        if result.returncode:
            raise HostError(result.stderr[-2000:] or "systemd unavailable")
        rows = json.loads(result.stdout)
        installed = runner(
            ["systemctl", "list-unit-files", "--type=service", "--no-pager", "--output=json"]
        )
        known = {row.get("unit") for row in rows}
        if installed.returncode == 0:
            for item in json.loads(installed.stdout):
                name = item.get("unit_file", "")
                if name not in known and UNIT_RE.fullmatch(name) and "@." not in name:
                    rows.append({"unit": name, "description": ""})
        names = [r["unit"] for r in rows if UNIT_RE.fullmatch(r.get("unit", ""))]
        properties = {}
        # A single batched read avoids a subprocess round trip for every service.
        if names:
            details = runner(
                [
                    "systemctl",
                    "show",
                    *names,
                    "--no-pager",
                    "--property=Id,ActiveState,SubState,MainPID,WorkingDirectory,User",
                ]
            )
            for block in details.stdout.strip().split("\n\n"):
                props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
                if props.get("Id"):
                    properties[props["Id"]] = props
        for row in rows:
            name = row.get("unit", "")
            if not UNIT_RE.fullmatch(name):
                continue
            props = properties.get(name, {})
            services.append(
                {
                    "unit": name,
                    "description": row.get("description", ""),
                    "state": props.get("ActiveState", "unknown"),
                    "sub": props.get("SubState", ""),
                    "pid": int(props.get("MainPID") or 0),
                    "working_directory": props.get("WorkingDirectory", ""),
                    "user": props.get("User") or "root",
                    "protected": service_protected(name),
                }
            )
    except (HostError, ValueError) as exc:
        errors.append(str(exc))
    try:
        result = runner(["ss", "-H", "-ltnp"])
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5:
                listeners.append(
                    {"address": parts[3], "pids": [int(n) for n in re.findall(r"pid=(\d+)", line)]}
                )
        if result.returncode:
            errors.append(result.stderr[-1000:] or "Listener inventory unavailable")
    except HostError as exc:
        errors.append(str(exc))
    try:
        result = runner(["ss", "-H", "-lxnp"])
        for line in result.stdout.splitlines():
            sockets = re.findall(r"(?:^|\s)(/[^\s]+)", line)
            if sockets:
                listeners.append(
                    {
                        "address": "unix:" + sockets[0],
                        "pids": [int(n) for n in re.findall(r"pid=(\d+)", line)],
                    }
                )
    except HostError as exc:
        errors.append(str(exc))
    # comm deliberately omits argv/environment, which can contain credentials.
    try:
        result = runner(["ps", "-eo", "pid=,ppid=,user=,comm="])
        for line in result.stdout.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4:
                pid = int(parts[0])
                try:
                    cgroup = Path(f"/proc/{pid}/cgroup").read_text()
                    units = re.findall(r"([^/\n]+\.service)(?:/|$)", cgroup)
                    unit = units[-1] if units else None
                except OSError:
                    unit = None
                processes.append(
                    {
                        "pid": pid,
                        "ppid": int(parts[1]),
                        "user": parts[2],
                        "command": parts[3],
                        "unit": unit,
                    }
                )
    except (HostError, ValueError) as exc:
        errors.append(str(exc))
    return {"services": services, "listeners": listeners, "processes": processes, "errors": errors}


def main():
    if os.geteuid() != 0:
        raise HostError("Host administration requires the privileged helper")
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    payload = {}
    if action in {
        "host-nginx-read",
        "host-nginx-action",
        "host-service-action",
        "host-ssl-import",
        "host-handover",
        "host-handover-rollback",
        "host-nginx-certificate",
    }:
        raw = sys.stdin.read(MAX_CONFIG * 2 + 1)
        if len(raw) > MAX_CONFIG * 2:
            raise HostError("Request too large")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise HostError("Expected an object")
    host = NginxHost()
    if action == "host-nginx-inventory":
        result = host.inventory()
    elif action == "host-nginx-read":
        result = host.read(payload.get("id", ""))
    elif action == "host-nginx-action":
        result = host.action(payload)
    elif action == "host-service-inventory":
        result = service_inventory()
    elif action == "host-service-action":
        result = service_action(payload)
    elif action == "host-ssl-import":
        result = import_certificate(payload)
    elif action == "host-handover":
        result = host.handover(payload)
    elif action == "host-handover-rollback":
        result = host.rollback_handover(payload)
    elif action == "host-nginx-certificate":
        result = host.attach_certificate(payload)
    else:
        raise HostError("Unknown host action")
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (HostError, OSError, ValueError, TypeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
