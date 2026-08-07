import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BLOCK_HOOK = REPO_ROOT / ".codex/hooks/block_sensitive_paths.py"
WARN_HOOK = REPO_ROOT / ".codex/hooks/warn_float_usage.py"


def run_hook(
    script: Path,
    payload: object,
    *,
    cwd: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    hook_input = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(script)],
        input=hook_input,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def patch_command(path: str, added_line: str = "+placeholder = True") -> str:
    return "\n".join(
        [
            "*** Begin Patch",
            f"*** Add File: {path}",
            added_line,
            "*** End Patch",
        ]
    )


def pretool_payload(tool_name: str, command: str) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {"command": command},
    }


def posttool_payload(command: str, cwd: Path) -> dict[str, object]:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "apply_patch",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }


def hook_output(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    return json.loads(result.stdout)["hookSpecificOutput"]


@pytest.mark.parametrize(
    ("tool_name", "command", "category", "expected_path"),
    [
        (
            "apply_patch",
            patch_command(".env"),
            "environment file",
            ".env",
        ),
        (
            "apply_patch",
            patch_command("config/local.env"),
            "environment file",
            "config/local.env",
        ),
        (
            "apply_patch",
            patch_command("var/pgdata/base/1"),
            "PostgreSQL data path",
            "var/pgdata/base/1",
        ),
        (
            "apply_patch",
            patch_command("var/postgres-data/base/1"),
            "PostgreSQL data path",
            "var/postgres-data/base/1",
        ),
        (
            "apply_patch",
            patch_command("var/postgresql/data/base/1"),
            "PostgreSQL data path",
            "var/postgresql/data/base/1",
        ),
        (
            "Bash",
            "printf placeholder > .env",
            "environment file",
            ".env",
        ),
        (
            "Bash",
            "touch config/local.env",
            "environment file",
            "config/local.env",
        ),
        (
            "Bash",
            "mkdir -p var/pgdata/base",
            "PostgreSQL data path",
            "var/pgdata/base",
        ),
        (
            "Bash",
            "cp fixture var/postgres-data/PG_VERSION",
            "PostgreSQL data path",
            "var/postgres-data/PG_VERSION",
        ),
        (
            "Bash",
            "dd if=/dev/null of=var/postgresql/data/PG_VERSION",
            "PostgreSQL data path",
            "var/postgresql/data/PG_VERSION",
        ),
    ],
)
def test_pretooluse_denies_matching_protected_paths(
    tool_name: str,
    command: str,
    category: str,
    expected_path: str,
):
    result = run_hook(BLOCK_HOOK, pretool_payload(tool_name, command))

    assert result.returncode == 0
    assert result.stderr == ""

    output = hook_output(result)
    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == "deny"
    assert category in output["permissionDecisionReason"]
    assert output["permissionDecisionReason"].endswith(f": {expected_path}")


@pytest.mark.parametrize(
    ("tool_name", "command", "expected_path"),
    [
        (
            "apply_patch",
            patch_command(
                "./var/postgresql/base/../data/PG_VERSION"
            ),
            "var/postgresql/data/PG_VERSION",
        ),
        (
            "Bash",
            "touch ./config/../local.env",
            "local.env",
        ),
    ],
)
def test_pretooluse_normalizes_protected_paths_before_denial(
    tool_name: str,
    command: str,
    expected_path: str,
):
    result = run_hook(BLOCK_HOOK, pretool_payload(tool_name, command))

    assert result.returncode == 0
    assert result.stderr == ""

    output = hook_output(result)
    assert output["permissionDecision"] == "deny"
    assert output["permissionDecisionReason"].endswith(f": {expected_path}")


@pytest.mark.parametrize(
    ("tool_name", "command"),
    [
        ("apply_patch", patch_command("pricing/models.py")),
        ("apply_patch", patch_command("docs/.env.example")),
        (
            "apply_patch",
            patch_command("var/postgresql/cluster-data/PG_VERSION"),
        ),
        ("Bash", "cat .env"),
        ("Bash", "touch var/pg-data/value"),
        ("Bash", "printf placeholder > docs/notes.txt"),
    ],
)
def test_pretooluse_allows_non_matching_or_non_writing_paths(
    tool_name: str,
    command: str,
):
    result = run_hook(BLOCK_HOOK, pretool_payload(tool_name, command))

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("payload", "expected_reason"),
    [
        (
            "not JSON SECRET_SENTINEL",
            "invalid JSON",
        ),
        (
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
            },
            "missing tool_input",
        ),
        (
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {},
            },
            "missing command",
        ),
        (
            pretool_payload("Bash", "touch 'SECRET_SENTINEL"),
            "unparseable shell command",
        ),
        (
            pretool_payload("apply_patch", "SECRET_SENTINEL"),
            "apply_patch contains no target declaration",
        ),
    ],
)
def test_matching_pretooluse_malformed_or_missing_input_fails_closed(
    payload: object,
    expected_reason: str,
):
    result = run_hook(BLOCK_HOOK, payload)

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Protected-path hook rejected malformed input" in result.stderr
    assert expected_reason in result.stderr
    assert "Traceback" not in result.stderr
    assert "SECRET_SENTINEL" not in result.stderr


@pytest.fixture
def hook_repository(tmp_path: Path) -> Path:
    # The PostToolUse hook accepts only persisted targets inside a Git root.
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    (tmp_path / "nested").mkdir()
    return tmp_path


def write_target(repository: Path, relative_path: str, contents: str) -> None:
    target = repository / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding="utf-8")


def run_posttool_hook(
    repository: Path,
    command: str,
) -> subprocess.CompletedProcess[str]:
    nested_cwd = repository / "nested"
    return run_hook(
        WARN_HOOK,
        posttool_payload(command, nested_cwd),
        cwd=nested_cwd,
    )


@pytest.mark.parametrize(
    ("target", "added_source"),
    [
        (
            "tests/test_float_hook_target.py",
            'value = float("1")',
        ),
        (
            "pricing/migrations/9999_float_hook_target.py",
            "amount = models.FloatField()",
        ),
    ],
)
def test_posttooluse_advises_for_added_python_float_usage(
    hook_repository: Path,
    target: str,
    added_source: str,
):
    write_target(hook_repository, target, f"{added_source}\n")
    command = patch_command(target, f"+{added_source}")

    result = run_posttool_hook(hook_repository, command)

    assert result.returncode == 0
    assert result.stderr == ""

    output = hook_output(result)
    assert set(output) == {"hookEventName", "additionalContext"}
    assert output["hookEventName"] == "PostToolUse"
    assert "WARNING" in output["additionalContext"]
    assert target in output["additionalContext"]
    assert "Decimal/DecimalField" in output["additionalContext"]


def test_posttooluse_normalizes_target_before_exclusion_checks(
    hook_repository: Path,
):
    raw_target = ".venv/../pricing/models.py"
    added_source = 'value = float("1")'
    write_target(hook_repository, "pricing/models.py", f"{added_source}\n")

    result = run_posttool_hook(
        hook_repository,
        patch_command(raw_target, f"+{added_source}"),
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "WARNING" in hook_output(result)["additionalContext"]


@pytest.mark.parametrize(
    ("target", "added_source"),
    [
        (
            "pricing/calculation.py",
            'value = Decimal("1.00")',
        ),
        (
            "docs/policy.md",
            "Never use float(value) for money.",
        ),
        (
            "__pycache__/cached.py",
            'value = float("1")',
        ),
        (
            ".venv/library.py",
            "amount = models.FloatField()",
        ),
    ],
)
def test_posttooluse_ignores_non_matching_added_lines_and_targets(
    hook_repository: Path,
    target: str,
    added_source: str,
):
    write_target(hook_repository, target, f"{added_source}\n")
    command = patch_command(target, f"+{added_source}")

    result = run_posttool_hook(hook_repository, command)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_posttooluse_does_not_scan_existing_or_unrelated_float_usage(
    hook_repository: Path,
):
    write_target(
        hook_repository,
        "pricing/calculation.py",
        'existing_value = float("1")\n',
    )
    write_target(
        hook_repository,
        "unrelated.py",
        "amount = models.FloatField()\n",
    )
    command = patch_command(
        "pricing/calculation.py",
        '+new_value = Decimal("1.00")',
    )

    result = run_posttool_hook(hook_repository, command)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
