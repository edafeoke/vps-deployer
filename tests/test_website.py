from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_DOCS = {
    "getting-started",
    "requirements",
    "installation",
    "first-project",
    "github",
    "projects",
    "deployments",
    "domains",
    "ssl",
    "nginx",
    "environment-variables",
    "rollback",
    "logs",
    "cli",
    "api",
    "configuration",
    "security",
    "troubleshooting",
    "updating",
    "uninstall",
}


def test_website_docs_match_architecture() -> None:
    docs = ROOT / "website" / "content" / "docs"
    slugs = {path.stem for path in docs.glob("*.md")}
    assert slugs == EXPECTED_DOCS


def test_prepare_public_reads_pyproject_version() -> None:
    text = (ROOT / "website" / "scripts" / "prepare-public.mjs").read_text(encoding="utf-8")
    assert "pyproject.toml" in text
    assert "readPackageVersion" in text
    assert 'const version = "0.1.0"' not in text


def test_installer_can_bootstrap_from_website() -> None:
    text = (ROOT / "installer" / "install.sh").read_text(encoding="utf-8")
    assert "${VD_SITE_URL}/installer/lib.sh" in text
    assert "${VD_SITE_URL}/releases/latest.txt" in text
    assert "vps-deployer-${version}.tar.gz" in text
    assert "vd_tar_members_safe" in text


def test_public_pages_use_current_release_history() -> None:
    releases = (ROOT / "website" / "lib" / "releases.ts").read_text(encoding="utf-8")
    for version in (
        "0.1.0",
        "0.2.0",
        "0.3.0",
        "0.3.1",
        "0.3.2",
        "0.3.3",
        "0.3.4",
        "0.3.5",
        "0.3.6",
        "0.4.0",
        "0.5.0",
        "0.6.0",
    ):
        assert f'version: "{version}"' in releases
    changelog = (ROOT / "website" / "app" / "changelog" / "page.tsx").read_text(encoding="utf-8")
    release_page = (ROOT / "website" / "app" / "releases" / "page.tsx").read_text(encoding="utf-8")
    assert "releases.map" in changelog
    assert "currentRelease.version" in release_page
