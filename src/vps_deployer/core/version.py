from importlib.metadata import PackageNotFoundError, version

FALLBACK_VERSION = "0.3.3"


def get_version() -> str:
    try:
        return version("vps-deployer")
    except PackageNotFoundError:
        return FALLBACK_VERSION
