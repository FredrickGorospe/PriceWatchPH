import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
NATIVE_CODEX_PROJECT_CONFIG = ".codex/config.toml"
LEGACY_ROOT_MCP_CONFIG = ".mcp.json"
DISPUTED_CONFIG_PATHS = (
    NATIVE_CODEX_PROJECT_CONFIG,
    LEGACY_ROOT_MCP_CONFIG,
)


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_legacy_root_mcp_configuration_is_ignored():
    result = run_git(
        "check-ignore",
        "--no-index",
        "--quiet",
        "--",
        LEGACY_ROOT_MCP_CONFIG,
    )

    assert result.returncode == 0, (
        "root .mcp.json must remain machine-local and ignored; "
        f"stderr={result.stderr!r}"
    )
    assert result.stdout == ""
    assert result.stderr == ""


def test_native_codex_project_configuration_remains_visible_to_git():
    result = run_git(
        "check-ignore",
        "--no-index",
        "--quiet",
        "--",
        NATIVE_CODEX_PROJECT_CONFIG,
    )

    assert result.returncode == 1, (
        ".codex/config.toml is the supported native project configuration "
        f"path and must remain visible to Git; stderr={result.stderr!r}"
    )
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize(
    "path",
    (
        ".codex/agents/future_agent.toml",
        ".codex/hooks/future_hook.py",
        ".codex/tests/future_tooling_test.py",
        "fixtures/.mcp.json",
    ),
)
def test_ignore_rule_does_not_hide_portable_project_artifacts(path: str):
    result = run_git(
        "check-ignore",
        "--no-index",
        "--quiet",
        "--",
        path,
    )

    assert result.returncode == 1, (
        f"{path} must remain visible to Git; stderr={result.stderr!r}"
    )
    assert result.stdout == ""
    assert result.stderr == ""


def test_disputed_mcp_configuration_files_are_not_tracked():
    result = run_git(
        "ls-files",
        "--",
        *DISPUTED_CONFIG_PATHS,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
