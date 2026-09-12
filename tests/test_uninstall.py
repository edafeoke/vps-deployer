from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vps_deployer.cli.main import app
from vps_deployer.core.uninstall import (
    DASHBOARD_SITE,
    UninstallLayout,
    collect_uninstall_targets,
    run_uninstall,
)

runner = CliRunner()


def _layout(root: Path) -> UninstallLayout:
    nginx = root / "nginx"
    systemd = root / "systemd"
    for path in (
        root / "bin",
        root / "libexec",
        nginx / "sites-available",
        nginx / "sites-enabled",
        nginx / "conf.d",
        systemd,
        root / "opt",
        root / "etc",
        root / "data",
        root / "logs",
        root / "apps" / "my-next-app",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (root / "bin" / "vps-deployer").write_text("cli\n", encoding="utf-8")
    (root / "libexec" / "vps-deployer-helper").write_text("helper\n", encoding="utf-8")
    (root / "etc-sudoers").mkdir(parents=True, exist_ok=True)
    sudoers = root / "etc-sudoers" / "vps-deployer"
    sudoers.write_text("sudoers\n", encoding="utf-8")
    (systemd / "vps-deployer.service").write_text("unit\n", encoding="utf-8")
    (systemd / "vps-deployer-app-my-next-app.service").write_text("app\n", encoding="utf-8")
    (nginx / "sites-available" / DASHBOARD_SITE).write_text("dash\n", encoding="utf-8")
    (nginx / "sites-enabled" / DASHBOARD_SITE).write_text("dash\n", encoding="utf-8")
    (nginx / "conf.d" / DASHBOARD_SITE).write_text("dash\n", encoding="utf-8")
    app_site = "vps-deployer-my-next-app.conf"
    (nginx / "sites-available" / app_site).write_text("app\n", encoding="utf-8")
    (nginx / "sites-enabled" / app_site).write_text("app\n", encoding="utf-8")
    return UninstallLayout(
        bindir=root / "bin",
        libexec=root / "libexec",
        sudoers=sudoers,
        systemd_dir=systemd,
        nginx_available=nginx / "sites-available",
        nginx_enabled=nginx / "sites-enabled",
        nginx_confd=nginx / "conf.d",
        opt=root / "opt",
        etc=root / "etc",
        data=root / "data",
        logs=root / "logs",
        apps=root / "apps",
    )


def test_default_plan_keeps_apps(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    plan = collect_uninstall_targets(purge=False, layout=layout)
    assert layout.apps not in plan.directories
    assert layout.opt in plan.directories
    assert layout.etc in plan.directories
    names = {path.name for path in plan.files}
    assert DASHBOARD_SITE in names
    assert "vps-deployer-my-next-app.conf" not in names
    assert "vps-deployer-app-my-next-app.service" not in plan.units
    assert "vps-deployer.service" in plan.units
    assert plan.remove_user is False


def test_purge_plan_includes_apps(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    plan = collect_uninstall_targets(purge=True, layout=layout)
    assert layout.apps in plan.directories
    names = {path.name for path in plan.files}
    assert DASHBOARD_SITE in names
    assert "vps-deployer-my-next-app.conf" in names
    assert "vps-deployer-app-my-next-app.service" in plan.units
    assert plan.remove_user is True


def test_run_uninstall_default_leaves_apps(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    commands: list[list[str]] = []

    def runner(args: list[str]) -> int:
        commands.append(args)
        return 0

    result = run_uninstall(purge=False, layout=layout, runner=runner, require_root=False)
    assert layout.cli.exists() is False
    assert layout.helper.exists() is False
    assert (layout.nginx_available / DASHBOARD_SITE).exists() is False
    assert (layout.nginx_available / "vps-deployer-my-next-app.conf").exists()
    assert (layout.systemd_dir / "vps-deployer-app-my-next-app.service").exists()
    assert layout.apps.exists()
    assert layout.opt.exists() is False
    assert str(layout.opt) in result.removed
    assert ["systemctl", "disable", "--now", "vps-deployer.service"] in commands
    assert ["systemctl", "daemon-reload"] in commands
    assert ["nginx", "-t"] in commands
    assert ["systemctl", "reload", "nginx"] in commands


def test_uninstall_help() -> None:
    result = runner.invoke(app, ["uninstall", "--help"])
    assert result.exit_code == 0
    assert "--purge" in result.stdout
    assert "--yes" in result.stdout


def test_uninstall_requires_root(monkeypatch) -> None:
    monkeypatch.setattr("vps_deployer.core.uninstall.is_root", lambda: False)
    result = runner.invoke(app, ["uninstall", "--yes"])
    assert result.exit_code == 1
    assert "root" in result.stdout or "root" in result.stderr
