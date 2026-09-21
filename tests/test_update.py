from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from vps_deployer.cli.main import app
from vps_deployer.core.update import (
    UpdateError,
    build_installer_argv,
    parse_latest_txt,
    plan_update,
    run_update,
    validate_semver,
)

runner = CliRunner()
SITE = "https://vps-deployer.onebitstack.com"


def _write_installer(_url: str, dest: Path) -> None:
    dest.write_text("#!/bin/bash\n", encoding="utf-8")


def test_parse_latest_txt_strips_whitespace() -> None:
    assert parse_latest_txt("  0.1.0\n") == "0.1.0"
    assert validate_semver("0.1.0")
    assert validate_semver("1.2.3-rc.1")
    assert not validate_semver("v0.1.0")
    with pytest.raises(UpdateError, match="Invalid version"):
        parse_latest_txt("not-a-version")


def test_refuse_http_download_url() -> None:
    with pytest.raises(UpdateError, match="HTTPS"):
        run_update(
            version="0.3.4",
            current_version="0.1.0",
            require_root=False,
            site_url="http://example.com",
        )


def test_same_version_without_force_does_not_invoke_installer() -> None:
    called: list[list[str]] = []
    downloaded: list[str] = []
    result = run_update(
        version="0.1.0",
        current_version="0.1.0",
        require_root=False,
        site_url=SITE,
        download_installer=lambda url, dest: downloaded.append(url),
        runner=lambda args: called.append(args) or 0,
    )
    assert result.skipped
    assert "already current" in result.message
    assert called == []
    assert downloaded == []


def test_force_same_version_builds_installer_argv() -> None:
    called: list[list[str]] = []

    def download(url: str, dest: Path) -> None:
        dest.write_text("#!/bin/bash\n", encoding="utf-8")
        assert url == f"{SITE}/install.sh"

    result = run_update(
        version="0.1.0",
        current_version="0.1.0",
        force=True,
        require_root=False,
        site_url=SITE,
        download_installer=download,
        runner=lambda args: called.append(args) or 0,
    )
    assert result.skipped is False
    assert called[0][0] == "bash"
    assert called[0][1].endswith(".sh")
    assert called[0][2:] == ["--version", "0.1.0"]
    assert result.installer_argv == called[0]


def test_newer_version_from_latest_txt_builds_installer_argv() -> None:
    called: list[list[str]] = []
    fetched: list[str] = []

    def fetch_latest(url: str) -> str:
        fetched.append(url)
        return "  0.3.4\n"

    run_update(
        current_version="0.1.0",
        require_root=False,
        site_url=SITE,
        fetch_latest=fetch_latest,
        download_installer=_write_installer,
        runner=lambda args: called.append(args) or 0,
    )
    assert fetched == [f"{SITE}/releases/latest.txt"]
    assert called[0][2:] == ["--version", "0.3.4"]
    assert build_installer_argv(Path("/tmp/install.sh"), version="0.3.4") == [
        "bash",
        "/tmp/install.sh",
        "--version",
        "0.3.4",
    ]


def test_source_and_version_together_fail(tmp_path: Path) -> None:
    with pytest.raises(UpdateError, match="together"):
        plan_update(version="0.3.4", source=tmp_path)
    with pytest.raises(UpdateError, match="together"):
        run_update(
            version="0.3.4",
            source=tmp_path,
            require_root=False,
            site_url=SITE,
        )


def test_source_builds_installer_argv(tmp_path: Path) -> None:
    called: list[list[str]] = []
    source = tmp_path / "checkout"
    source.mkdir()
    run_update(
        source=source,
        require_root=False,
        site_url=SITE,
        download_installer=_write_installer,
        runner=lambda args: called.append(args) or 0,
    )
    assert called[0][2:] == ["--source", str(source.resolve())]


def test_update_help() -> None:
    result = runner.invoke(app, ["update", "--help"])
    assert result.exit_code == 0
    assert "--version" in result.stdout
    assert "--source" in result.stdout
    assert "--force" in result.stdout
    assert "--yes" in result.stdout


def test_update_requires_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vps_deployer.core.update.is_root", lambda: False)
    result = runner.invoke(app, ["update", "--yes"])
    assert result.exit_code == 1
    assert "root" in result.stdout or "root" in result.stderr


def test_update_cli_rejects_source_and_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("vps_deployer.core.update.is_root", lambda: True)
    result = runner.invoke(
        app,
        ["update", "--yes", "--version", "0.3.4", "--source", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "together" in result.stdout or "together" in result.stderr
