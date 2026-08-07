# TASK_011 — Codex hook guardrails

## Goal

Port the existing Claude Code protected-path and float-warning policies to the
native Codex hook protocol without claiming identical runtime coverage.

## Source policy and event mapping

- Claude `PreToolUse` blocks edits when the basename is `.env` or ends in
  `.env`, or when the normalized path contains `pgdata`, `postgres-data`, or
  `postgresql/data`.
- Codex `PreToolUse` matches `Bash` and `apply_patch`, reads
  `tool_input.command`, and returns native `permissionDecision: "deny"` JSON.
- Claude `PostToolUse` warns for `float(` or `FloatField`. Codex
  `PostToolUse` matches `apply_patch`, examines added lines in targeted Python
  files, and returns model-visible `additionalContext` without blocking.

## Runtime and scope

Hooks use the host `python3` available on `PATH` and locate their scripts through
`git rev-parse --show-toplevel`, so sessions may start below the repository root.
The float warning covers added `.py` lines, including tests and migrations, but
excludes prose, caches, virtual environments, and other non-Python targets. It
does not scan unrelated working-tree changes or retroactively reject an edit.

Persistent Codex tooling tests live under `.codex/tests` and run separately
from the application suite with Python 3.12 and Git:

    uv run --isolated --no-project --managed-python --python 3.12.13 --with pytest==9.1.1 python -m pytest -c /dev/null -v .codex/tests/test_task_011_codex_hooks.py

The normal application validation remains `docker compose exec web pytest -v`;
`.codex` and Git remain excluded from the application image.

## Coverage limitations

These hooks are defense in depth, not a security boundary. The Bash guard
recognizes straightforward redirections and common file-writing utilities; it
does not fully interpret shell variables, command generation, indirect
interpreters, dynamically evaluated code, every utility, or specialized tool
paths. `write_stdin` does not rerun `PreToolUse`, and hook paths that Codex does
not expose cannot be intercepted. Project hooks run only when the project layer
and current hook definitions are trusted.

## Acceptance criteria

1. Native Codex 0.147.0 loads the project hooks from a trusted project layer.
2. `apply_patch` is denied before writing protected environment and PostgreSQL
   data paths, while a benign source patch is allowed.
3. Obvious Bash writes to protected environment and PostgreSQL data paths are
   denied before execution, while benign Bash operations are allowed.
4. Malformed matching PreToolUse input fails closed without traceback or secret
   output.
5. A Python patch adding `float(` or `FloatField` succeeds and produces a
   model-visible advisory; a benign Python patch and prose occurrence do not.
6. The dedicated Codex tooling test module's direct unit-level inputs cover
   expected, malformed, missing, allowed, blocked, normalized, matching, and
   non-matching cases.
7. An exact staged snapshot contains all three hook files, discovers the hooks,
   and still excludes `.codex` from the Docker image.
8. The scratch Docker build uses PostgreSQL 16, applies migrations from zero,
   passes the full application suite, reports no migration drift, and retains
   enforced
   `rawlisting_immutable` protection.
9. A read-only parent successfully spawns the TASK_010 project reviewer, which
   reports no blockers for the staged TASK_011 evidence.
