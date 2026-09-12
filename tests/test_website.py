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


def test_installer_can_bootstrap_from_website() -> None:
    text = (ROOT / "installer" / "install.sh").read_text(encoding="utf-8")
    assert "${VD_SITE_URL}/installer/lib.sh" in text
    assert "${VD_SITE_URL}/releases/latest.txt" in text
    assert "vps-deployer-${version}.tar.gz" in text
    assert "vd_tar_members_safe" in text
