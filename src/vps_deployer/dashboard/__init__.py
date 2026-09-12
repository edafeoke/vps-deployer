from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

__all__ = ["PACKAGE_DIR", "TEMPLATE_DIR", "STATIC_DIR"]
