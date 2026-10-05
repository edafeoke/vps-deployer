"""Identify supported frameworks without executing repository code."""

import base64
import json
from urllib.parse import quote

from vps_deployer.core.github import (
    GitHubAuthError,
    GitHubNotConfiguredError,
    call_github,
    create_installation_token,
)
from vps_deployer.core.validation import ValidationError


def detect_runtime(repository, branch, settings=None):
    try:
        try:
            token = create_installation_token(settings)
        except GitHubNotConfiguredError:
            token = ""
        root = f"/repos/{repository}"
        tree = call_github("GET", f"{root}/git/trees/{quote(branch, safe='')}", token)
        names = {item["path"] for item in tree.get("tree", [])}

        def content(name):
            data = call_github("GET", f"{root}/contents/{name}?ref={quote(branch, safe='')}", token)
            return base64.b64decode(data["content"]).decode("utf-8")

        if "artisan" in names:
            return "laravel"
        if "composer.json" in names:
            deps = json.loads(content("composer.json")).get("require", {})
            return "laravel" if "laravel/framework" in deps else "php"
        if "package.json" in names:
            package = json.loads(content("package.json"))
            deps = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
            if "next" in deps:
                return "nextjs"
            return "vite" if "vite" in deps else "node"
        for name in ("pyproject.toml", "requirements.txt"):
            if name in names:
                text = content(name).lower()
                if "fastapi" in text:
                    return "fastapi"
                if "flask" in text:
                    return "flask"
        if "index.php" in names:
            return "php"
        if "index.html" in names:
            return "static"
    except (GitHubAuthError, ValueError, KeyError, TypeError) as exc:
        raise ValidationError(
            "Unable to detect runtime. Check repository access and branch, or select it manually."
        ) from exc
    raise ValidationError("Runtime could not be detected. Select a runtime manually.")
