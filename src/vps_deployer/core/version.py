from importlib.metadata import PackageNotFoundError, version

FALLBACK_VERSION = "0.8.1"


def get_version() -> str:
    try:
        return version("vps-deployer")
    except PackageNotFoundError:
        return FALLBACK_VERSION
