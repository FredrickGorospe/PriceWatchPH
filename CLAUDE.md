# CLAUDE.md — PriceWatch PH

Scheduled ingestion pipeline for Philippine PC component listing prices.
Resolves messy listing titles to canonical SKUs, flags underpriced listings
against a per-SKU rolling baseline, tracks realised outcomes.

## Hard constraints — never violate, never propose alternatives

- Postgres 16 only. SQLite is forbidden, including in tests.
- No Celery, no Redis, no message broker. Scheduling is cron plus a Django
  management command.
- Money is always Decimal. Never float. Never FloatField.
- RawListing is immutable after write. No downstream process edits it.
- Facebook Marketplace is out of scope permanently. Do not propose it or
  workarounds for it.
- Python 3.12, Django 5.2, DRF. No framework substitutions.
- Timestamps are stored in UTC, USE_TZ is True. Display timezone is
  Asia/Manila and is a separate setting, never the storage timezone.
- No frontend framework before phase 6. Django admin is the UI until then.
- Secrets come from environment variables. Never hardcoded, never committed.

## Workflow

- One task file at a time, from tasks/. Never implement ahead of the current
  task.
- Acceptance criteria are failing test functions, approved by me before any
  implementation exists. Implementation makes them pass without modifying
  them. If a test is wrong, stop and say so — do not edit it.
- Plan at most four tasks ahead.
- One commit per task. The message starts with the task ID.
- If a fact is not in this file, docs/ROADMAP.md, or the current task file,
  say you do not know it. Do not reconstruct it.

## Validation

Every task ends with, from the repo root:

    docker compose exec web pytest -v
    docker compose exec web python manage.py makemigrations --check --dry-run

Both must be clean before the task is done.

## Style

- Explicit over clever. This repo will be read by interviewers.
- Every non-obvious decision gets a one-line comment saying why, not what.
