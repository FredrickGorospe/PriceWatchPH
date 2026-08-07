# TASK_012 — Codex MCP repository disposition

## Context

Codex CLI is the primary PriceWatchPH development interface. Native Codex MCP
configuration uses `config.toml`: user configuration lives under the user's
Codex home, while trusted projects may override it with `.codex/config.toml`.

Before this task, the working tree contained two untracked configuration files:

- `.codex/config.toml`, defining duplicate Context7 and Semgrep servers and
  containing an absolute, machine-specific project trust entry.
- `.mcp.json`, duplicating those definitions using a legacy/non-Codex JSON
  configuration format.

The project Semgrep definition uses the deprecated standalone
`uvx semgrep-mcp` package and overrides the user's native `semgrep mcp`
definition while working in PriceWatchPH.

Context7 and Semgrep are host developer tools. Neither is a PriceWatchPH
application runtime dependency, repository acceptance dependency, or Docker
dependency.

OpenAI supports `.codex/config.toml` as the native trusted-project override
mechanism. The current file's contents are inappropriate, but that does not
justify ignoring the path or preventing a future task from adding legitimate,
reviewed project configuration.

TASK_009 already excludes `.codex`, `.mcp.json`, and local tooling from the
Docker build context. That boundary remains unchanged.

## Goal

Remove the current accidental project and legacy MCP configuration while
preserving `.codex/config.toml` as an available native Codex project path and
preventing the legacy root `.mcp.json` from being accidentally committed.

## Scope

Tracked implementation is limited to:

- `.gitignore`
- `.codex/tests/test_task_012_mcp_disposition.py`
- `tasks/TASK_012_CODEX_MCP_DISPOSITION.md`

Local cleanup removes the existing untracked:

- `.codex/config.toml`
- `.mcp.json`

Those files are not tracked, so their removal is not a staged deletion.

User/global Codex configuration, installed MCP packages, credentials, and
machine-local Semgrep environment repair are not repository implementation
artifacts and are not part of the staged TASK_012 snapshot.

TASK_007, TASK_011, application code, migrations, dependency files,
`.dockerignore`, `CLAUDE.md`, `docs/01_PLANNING.md`, hooks, reviewer
configuration, and unrelated user/global MCP servers are out of scope.

## Locked decisions

1. The current untracked `.codex/config.toml` is removed because its contents
   duplicate global tools, select a deprecated Semgrep server, and contain a
   machine-specific trust path.
2. Root `.codex/config.toml` is not ignored. It remains visible to Git so a
   future approved task may add legitimate native Codex project configuration.
3. Root `.mcp.json` is legacy/non-Codex project MCP configuration. It is removed
   and ignored with a root-anchored rule.
4. The `.mcp.json` ignore rule does not hide nested files with that name.
5. Existing and future `.codex` agents, hooks, and tooling tests remain visible
   to Git.
6. Context7 is not configured by the repository. Existing user/global Context7
   configuration is outside TASK_012.
7. Semgrep is not configured by the repository. The deprecated
   `uvx semgrep-mcp` project override is removed.
8. Native Semgrep setup, certificate discovery, executable installation, and
   authentication remain machine-local.
9. No user/global Codex configuration change is staged, committed, or claimed
   as a fresh-clone guarantee.
10. No MCP credential, token, authorization value, absolute user path, or
    machine-specific executable path is added to a tracked TASK_012 artifact.
11. No package is installed, upgraded, or added to a repository dependency
    file.
12. `.dockerignore` remains unchanged. MCP tooling is not added to the Django
    image.
13. Runtime validation results are not committed as proof artifacts.

## Machine-local Semgrep boundary

The TASK_012 hardening investigation confirmed, through a non-persistent Codex
CLI override, that the installed native Semgrep server can complete Codex MCP
initialization and tool discovery when supplied with the host's CA bundle.

That result supports a separate machine-local setup action. It does not add
Semgrep configuration to the repository, does not modify the staged snapshot,
and does not establish that another developer or fresh clone has the same
Semgrep installation or certificate layout.

Persisting any host repair in user configuration requires explicit owner
authorization and separate validation. It is not TASK_012 repository
implementation.

## Persistent tooling test

The dedicated tooling test lives outside the Django test tree:

    .codex/tests/test_task_012_mcp_disposition.py

It runs with Python 3.12 and Git:

    uv run --isolated --no-project --managed-python --python 3.12.13 --with pytest==9.1.1 python -m pytest -c /dev/null -v .codex/tests/test_task_012_mcp_disposition.py

The test protects these repository behaviors:

- root `.mcp.json` is ignored;
- root `.codex/config.toml` is not ignored;
- `.codex` agents, hooks, and tooling tests remain visible to Git;
- a nested `.mcp.json` remains visible to Git;
- neither disputed configuration file is tracked.

The normal Django suite does not collect `.codex/tests`.

## Acceptance criteria

1. Root `.mcp.json` is ignored by a root-anchored Git ignore rule and is not
   tracked.
2. Root `.codex/config.toml` is not ignored and is not tracked.
3. `.codex` agents, hooks, and tooling tests remain visible to Git.
4. A non-root `.mcp.json` remains visible to Git.
5. The two pre-existing untracked configuration files are absent after local
   cleanup.
6. The exact staged snapshot contains no `.codex/config.toml` or `.mcp.json`.
7. The staged snapshot retains the existing tracked Codex reviewer, hooks, and
   tooling tests, including the TASK_012 tooling test.
8. No tracked TASK_012 artifact contains a credential value, authorization
   value, absolute user-specific path, or machine-specific executable path.
9. No user/global Codex configuration or installed package is included in the
   staged snapshot or TASK_012 commit.
10. A scratch image built from the exact staged snapshot contains neither
    `.codex` nor `.mcp.json`; the existing TASK_009 Docker boundary remains
    intact.
11. The complete Django pytest suite passes and
    `makemigrations --check --dry-run` reports no changes.
12. TASK_007, TASK_011, application files, and unrelated working-tree changes
    remain untouched.
13. A final TASK_010 reviewer, invoked from a read-only parent against the
    frozen task and staged diff, reports no blockers.

## Security and portability requirements

- Project trust remains a user-level decision; no trust path is committed.
- Credentials remain in environment variables, OAuth storage, or another
  machine-local credential store.
- A fresh clone does not automatically download, execute, or enable Context7 or
  Semgrep through TASK_012.
- A fresh clone may inherit user/global MCP configuration. That is normal Codex
  behavior and is not controlled or guaranteed by this repository.
- The repository does not claim that machine-local Semgrep configuration,
  executable availability, certificate layout, or authentication is portable.
- The root `.codex/config.toml` path remains available for a future approved
  native project configuration task.

## Validation responsibility

The final static reviewer owns:

- staged `.gitignore` correctness and scope;
- test integrity;
- secret and machine-path leakage across every tracked TASK_012 artifact,
  including this specification;
- task scope;
- weakened, skipped, xfailed, vacuous, bypassed, or test-special-cased
  acceptance coverage;
- contradictions of project constraints.

The runtime validator owns:

- dedicated tooling-test execution;
- Git ignore behavior;
- local cleanup confirmation;
- exact staged-snapshot and Docker inspection;
- Django pytest execution;
- migration-drift validation;
- any separately authorized machine-local MCP startup check.

A static reviewer may state that runtime or machine-local claims cannot be
independently reconstructed from the staged diff. That absence is not a blocker
unless the staged artifacts contradict or invalidate the claimed validation.
No validation log is committed to manufacture static proof.

## Non-goals

- Committing a project `.codex/config.toml`.
- Permanently preventing future project `.codex/config.toml` use.
- Installing, upgrading, pinning, or configuring Context7, Semgrep, Node, uv,
  or Codex.
- Making MCP mandatory for application development or CI.
- Adding MCP tooling to the Django image.
- Creating or preserving Claude/Codex configuration symmetry.
- Changing hooks, reviewer behavior, application code, schema, or migrations.
- Changing unrelated user/global MCP servers.
- Modifying TASK_007 or TASK_011.

## Unresolved unknowns

There are no unresolved repository-disposition decisions in this specification.

Machine-local MCP availability remains environment-dependent by design and is
not a repository acceptance guarantee.
