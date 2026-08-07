# TASK_009 — Docker build-context hardening

## Goal

Prevent secrets, Git metadata, local agent and MCP configuration, caches,
virtual environments, editor files, operating-system artifacts, and local
PostgreSQL data directories from entering the Docker build context.

## Scope

This is a non-schema tooling/security task. Its implementation change is limited
to `.dockerignore`; TASK_007, application code, migrations, and existing
configuration are out of scope.

## Acceptance criteria

1. The real `.env` and all other local environment files are excluded.
2. `.env.example` remains available because the bootstrap tests require it.
3. `.git`, `.claude`, `.codex`, and `.mcp.json` are excluded.
4. Python bytecode, tool caches, virtual environments, editor files, and
   operating-system artifacts are excluded.
5. Local PostgreSQL data directories are excluded defensively.
6. Application source, migrations, templates, tests, static assets,
   `Dockerfile`, `docker-compose.yml`, and required runtime files remain
   available.
7. An isolated scratch build proves excluded files are absent from the image.
8. PostgreSQL major version 16 is used.
9. Migrations apply from zero.
10. The complete pytest suite passes.
11. `makemigrations --check --dry-run` is clean.
12. The `rawlisting_immutable` trigger remains installed and enforced.
13. No real secret from the development `.env` is copied, printed, or exposed
    during validation.

## Validation

From an exact staged snapshot in an isolated Compose project:

    docker compose exec -T web pytest -v
    docker compose exec -T web python manage.py makemigrations --check --dry-run

Inspect the built image for excluded and required paths, verify PostgreSQL 16,
apply migrations from zero, and confirm the immutability trigger before removing
only the scratch resources.
