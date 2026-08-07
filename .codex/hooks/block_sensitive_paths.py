#!/usr/bin/env python3
"""Deny recognized Codex writes to local secrets and PostgreSQL data."""

from __future__ import annotations

import json
import posixpath
import re
import shlex
import sys
from collections.abc import Iterable


PATCH_TARGET = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File:\s*(?P<path>.+?)\s*$", re.MULTILINE
)
PATCH_MOVE_TARGET = re.compile(r"^\*\*\* Move to:\s*(?P<path>.+?)\s*$", re.MULTILINE)
POSTGRES_MARKERS = ("pgdata", "postgres-data", "postgresql/data")
SHELL_SEPARATORS = {";", "&", "&&", "|", "||"}
REDIRECTIONS = {">", ">>", ">|", "&>", "&>>"}


def reject_malformed(reason: str) -> int:
    print(f"Protected-path hook rejected malformed input: {reason}.", file=sys.stderr)
    return 2


def normalized_path(path: str) -> str:
    cleaned = path.strip().strip("'\"").replace("\\", "/")
    return posixpath.normpath(cleaned)


def protected_category(path: str) -> str | None:
    normalized = normalized_path(path)
    basename = normalized.rsplit("/", 1)[-1]
    if basename == ".env" or basename.endswith(".env"):
        return "environment file"
    if any(marker in normalized for marker in POSTGRES_MARKERS):
        return "PostgreSQL data path"
    return None


def patch_targets(command: str) -> list[str]:
    targets = [match.group("path") for match in PATCH_TARGET.finditer(command)]
    targets.extend(match.group("path") for match in PATCH_MOVE_TARGET.finditer(command))
    return targets


def shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def command_segments(tokens: Iterable[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in SHELL_SEPARATORS:
            if segments[-1]:
                segments.append([])
            continue
        segments[-1].append(token)
    return [segment for segment in segments if segment]


def operands(tokens: list[str]) -> list[str]:
    return [token for token in tokens if token and not token.startswith("-")]


def unwrap_command(segment: list[str]) -> tuple[str, list[str]]:
    index = 0
    while index < len(segment):
        token = segment[index]
        if "=" in token and not token.startswith(("/", "./", "../")):
            index += 1
            continue
        name = posixpath.basename(token)
        if name in {"command", "env", "sudo"}:
            index += 1
            while index < len(segment) and segment[index].startswith("-"):
                index += 1
            continue
        return name, segment[index + 1 :]
    return "", []


def bash_write_targets(command: str) -> list[str]:
    tokens = shell_tokens(command)
    targets: list[str] = []

    for index, token in enumerate(tokens[:-1]):
        if token in REDIRECTIONS or (set(token) <= {">", "&"} and ">" in token):
            targets.append(tokens[index + 1])

    for segment in command_segments(tokens):
        name, arguments = unwrap_command(segment)
        if not name:
            continue

        plain = operands(arguments)
        if name in {"touch", "mkdir", "rm", "rmdir", "truncate", "chmod", "chown"}:
            targets.extend(plain)
        elif name == "tee":
            targets.extend(plain)
        elif name in {"cp", "install", "ln"} and plain:
            targets.append(plain[-1])
        elif name == "mv":
            targets.extend(plain)
        elif name == "dd":
            targets.extend(token.removeprefix("of=") for token in arguments if token.startswith("of="))
        elif name == "sed" and any(token == "-i" or token.startswith("-i") for token in arguments):
            targets.extend(plain[1:] if len(plain) > 1 else plain)
        elif name == "apply_patch":
            targets.extend(patch_targets(command))

    return targets


def denial(path: str, category: str) -> int:
    reason = f"Blocked write to protected {category}: {normalized_path(path)}"
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output, separators=(",", ":")))
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return reject_malformed("invalid JSON")

    if not isinstance(payload, dict):
        return reject_malformed("top-level JSON must be an object")

    tool_name = payload.get("tool_name")
    if tool_name not in {"Bash", "apply_patch"}:
        if not isinstance(tool_name, str):
            return reject_malformed("missing tool_name")
        return 0
    if payload.get("hook_event_name") != "PreToolUse":
        return reject_malformed("unexpected hook event")

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return reject_malformed("missing tool_input")
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return reject_malformed("missing command")

    try:
        targets = patch_targets(command) if tool_name == "apply_patch" else bash_write_targets(command)
    except ValueError:
        return reject_malformed("unparseable shell command")

    if tool_name == "apply_patch" and not targets:
        return reject_malformed("apply_patch contains no target declaration")

    for target in targets:
        category = protected_category(target)
        if category:
            return denial(target, category)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
