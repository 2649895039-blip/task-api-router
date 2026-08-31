"""Validate that a checkout is safe to package and publish."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REQUIRED_FILES = (
    ".claude-plugin/plugin.json",
    "hooks/hooks.json",
    "hooks/action_guard_hook.py",
    "skills/task-router/SKILL.md",
    "openclaw/skills/task-router/SKILL.md",
    "config/models.example.yaml",
    "task_router/config/models.example.yaml",
    "SECURITY.md",
    "NOTICE",
    "TRADEMARKS.md",
)

def _version_from_init(root: Path) -> str:
    text = (root / "task_router" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)', text)
    return match.group(1) if match else ""

def validate_repository(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        version = _version_from_init(root)
        if not version:
            errors.append("task_router.__version__ missing")
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        if f'version = "{version}"' not in pyproject:
            errors.append("pyproject version does not match task_router.__version__")
        manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        if manifest.get("version") != version:
            errors.append("Claude plugin version does not match task_router.__version__")
        readme = (root / "README.md").read_text(encoding="utf-8")
        if f"v{version}" not in readme:
            errors.append("README does not document the current version")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"metadata unreadable: {type(exc).__name__}")
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"missing required release file: {relative}")
    try:
        tracked = subprocess.check_output(
            ["git", "ls-files"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).splitlines()
        forbidden = re.compile(r"(^|/)(models\.yaml|\.env$|data/|promo/)|\.(pem|key)$", re.I)
        errors.extend(f"sensitive file tracked: {path}" for path in tracked if forbidden.search(path))
    except (OSError, subprocess.SubprocessError):
        errors.append("unable to inspect tracked files")
    return errors

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate_repository(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"release validation passed: {_version_from_init(root)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
