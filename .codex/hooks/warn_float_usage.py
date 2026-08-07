#!/usr/bin/env python3
"""Add model-visible context when an applied Python patch adds float usage."""

from __future__ import annotations

import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path


PATCH_TARGET = re.compile(r"^\*\*\* (?P<action>Add|Update|Delete) File:\s*(?P<path>.+?)\s*$")
PATCH_MOVE_TARGET = re.compile(r"^\*\*\* Move to:\s*(?P<path>.+?)\s*$")
PROHIBITED = re.compile(r"float\s*\(|FloatField")
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox", ".venv", "venv"}


def context(message: str) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        }
    }
    print(json.dumps(output, separators=(",", ":")))


def repository_root(cwd: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(result.stdout.strip()).resolve()


def python_target(path: str) -> bool:
    normalized = Path(posixpath.normpath(path.strip().strip("'\"")))
    return normalized.suffix == ".py" and not EXCLUDED_PARTS.intersection(normalized.parts)


def added_float_targets(command: str) -> set[str]:
    matched: set[str] = set()
    current: str | None = None
    for line in command.splitlines():
        target_match = PATCH_TARGET.match(line)
        if target_match:
            current = None if target_match.group("action") == "Delete" else target_match.group("path")
            continue
        move_match = PATCH_MOVE_TARGET.match(line)
        if move_match:
            current = move_match.group("path")
            continue
        if current and python_target(current) and line.startswith("+") and PROHIBITED.search(line[1:]):
            matched.add(current)
    return matched


def resolved_target(path: str, cwd: Path, root: Path) -> Path | None:
    raw = Path(path.strip().strip("'\""))
    candidates = [raw] if raw.is_absolute() else [cwd / raw, root / raw]
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        context("Decimal advisory could not inspect the completed edit because hook input was malformed.")
        return 0

    if not isinstance(payload, dict):
        context("Decimal advisory could not inspect the completed edit because hook input was malformed.")
        return 0
    if payload.get("tool_name") != "apply_patch":
        return 0
    if payload.get("hook_event_name") != "PostToolUse":
        context("Decimal advisory could not inspect the completed edit because the hook event was unexpected.")
        return 0

    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        context("Decimal advisory could not inspect the completed edit because tool_input.command was missing.")
        return 0

    targets = added_float_targets(command)
    if not targets:
        return 0

    cwd_value = payload.get("cwd")
    cwd = Path(cwd_value).resolve() if isinstance(cwd_value, str) else Path.cwd().resolve()
    root = repository_root(cwd)
    if root is None:
        context("Decimal advisory could not verify the edited Python target because the Git root was unavailable.")
        return 0

    persisted = []
    for target in sorted(targets):
        resolved = resolved_target(target, cwd, root)
        if resolved is None:
            continue
        try:
            contents = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            context(f"Decimal advisory could not read the edited Python target: {target}.")
            continue
        if PROHIBITED.search(contents):
            persisted.append(target)
    if persisted:
        paths = ", ".join(persisted)
        context(
            f"WARNING: Python edit added float( or FloatField usage in {paths}. "
            "PriceWatchPH requires Decimal/DecimalField for money; review the edited code."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
