# TASK_001 — Bootstrap: Postgres 16 + Django 5.2 under Compose

## 1. Scope

Goal: from a fresh clone, `docker compose up` produces a Django 5.2 application
on Python 3.12 talking to Postgres 16, configured entirely from environment
variables, with no domain models.

**Out of scope for this task** — do not touch, do not scaffold, do not
anticipate:

- Domain models (`Sku`, `SkuAlias`, `Source`, `RawListing`, `Listing`,
  `PricePoint`, `DealFlag`, `Outcome`) and their migrations.
- Django REST Framework. Not installed, not configured.
- The scheduler (cron) and any Django management command it would call.
- Any ingestion code (`ebay_client`, `tipidpc_scraper`, `manual_capture`,
  `retailer_prices`).
- Django admin content — there is nothing to register yet.
- Alerts, the review queue, outcome tracking, or anything from phase 1 onward.

## 2. Files this task may create or modify (exhaustive)

Anything not on this list is out of scope by definition.

**Create:**

- `docker-compose.yml`
- `Dockerfile`
- `requirements.txt`
- `manage.py`
- `config/__init__.py`
- `config/settings.py`
- `config/urls.py`
- `config/wsgi.py`
- `conftest.py`
- `pytest.ini`
- `tests/__init__.py`
- `tests/test_task_001_bootstrap.py`

**Modify:**

- `.env.example` — only if `config/settings.py` genuinely needs a variable not
  already present. The existing keys (`POSTGRES_DB`, `POSTGRES_USER`,
  `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `DJANGO_SECRET_KEY`,
  `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_DISPLAY_TIME_ZONE`) already
  look sufficient for this task's scope, so no change is expected in practice.

Nothing else — not `.gitignore`, not any file under `docs/`, not
`SOURCES.md`, not admin registrations, not model files.

## 3. Acceptance criteria

Acceptance tests are written and approved here, before any implementation
exists, per the workflow in `CLAUDE.md`. All ten currently fail — most by
collection error (`ModuleNotFoundError: config`, `FileNotFoundError` on
`docker-compose.yml`) — because nothing referenced by them exists yet. That is
the required state. Implementation must make them pass without modifying them;
if a test turns out to be wrong, stop and say so rather than editing it.

Two of the ten need a design decision made explicit before they're written,
because the test's parsing strategy quietly commits the implementation to a
particular shape.

**Decision 1 — env-example coverage test.** This test scans
`config/settings.py`'s *source text* with a regex for the two plain-`os.environ`
read forms — `os.environ.get("X")` / `os.environ.get('X')` and
`os.environ["X"]` — and collects the variable names into a set. It parses
`.env.example` by splitting non-comment, non-blank lines on the first `=` and
collecting the left-hand side. The test asserts both directions of the
symmetric difference are empty: nothing read that isn't documented, nothing
documented that isn't read. The regex only matches plain `os.environ` — it
deliberately does not recognize `django-environ`'s `env()` helper or
`python-decouple`'s `config()`. That is a real design constraint this test
imposes, not a neutral parsing choice: it commits `config/settings.py` to plain
`os.environ`, no third-party env-parsing dependency. This is chosen
deliberately — explicit over clever, and one fewer dependency to justify in a
phase-0 bootstrap — rather than left for the test to decide silently.

**Decision 2 — compose parsing test.** This test parses `docker-compose.yml`
with `yaml.safe_load` (PyYAML, to be added to `requirements.txt`) rather than
by text/regex matching, since compose files are YAML with meaningful
structure. It asserts `services.db.image` *starts with* `"postgres:16"` (not
equality), so a valid tag like `postgres:16.4` or `postgres:16-alpine` still
passes — only the major version is pinned by this test, deliberately, since
the exact tag string is not decided here (see Unknowns). Separately, it asserts
the top-level `volumes:` map is non-empty, that some entry in
`services.db.volumes` mounts a path ending `/var/lib/postgresql/data`, and that
the mount's source name matches one of the declared named volumes — ruling out
an anonymous volume or a host bind-mount, either of which risks data loss or a
non-portable path across machines.

The exact content of `tests/test_task_001_bootstrap.py`:

```python
import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_database_vendor_is_postgresql(db):
    """Django's default database connection reports postgresql as its vendor."""
    from django.db import connection

    assert connection.vendor == "postgresql"


def test_settings_contain_no_sqlite_engine():
    """No configured database uses django.db.backends.sqlite3, in any environment."""
    from django.conf import settings

    for alias, config in settings.DATABASES.items():
        assert "sqlite" not in config["ENGINE"].lower(), (
            f"database alias {alias!r} uses engine {config['ENGINE']!r}"
        )


def test_postgres_server_version_is_16(db):
    """The live Postgres connection reports major version 16."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SHOW server_version;")
        version = cursor.fetchone()[0]
    assert version.startswith("16"), f"server_version was {version!r}"


def test_use_tz_is_true_and_storage_timezone_is_utc():
    """USE_TZ is enabled and the storage timezone (settings.TIME_ZONE) is UTC."""
    from django.conf import settings

    assert settings.USE_TZ is True
    assert settings.TIME_ZONE == "UTC"


def test_display_timezone_is_asia_manila():
    """A separate, explicit display-timezone setting names Asia/Manila."""
    from django.conf import settings

    assert settings.DISPLAY_TIME_ZONE == "Asia/Manila"
    assert settings.TIME_ZONE == "UTC", (
        "storage timezone must stay UTC even though a display timezone exists"
    )


def test_secret_key_is_loaded_from_environment(monkeypatch):
    """Reloading config.settings with a different DJANGO_SECRET_KEY changes SECRET_KEY."""
    from config import settings as settings_module

    monkeypatch.setenv("DJANGO_SECRET_KEY", "task-001-marker-secret")
    importlib.reload(settings_module)
    try:
        assert settings_module.SECRET_KEY == "task-001-marker-secret"
    finally:
        monkeypatch.undo()
        importlib.reload(settings_module)


def test_debug_is_false_when_env_var_is_absent(monkeypatch):
    """DEBUG defaults to False when DJANGO_DEBUG is not set in the environment."""
    from config import settings as settings_module

    monkeypatch.delenv("DJANGO_DEBUG", raising=False)
    importlib.reload(settings_module)
    try:
        assert settings_module.DEBUG is False
    finally:
        importlib.reload(settings_module)


def test_no_missing_migrations():
    """manage.py makemigrations --check --dry-run exits zero: no model changes are unmigrated."""
    result = subprocess.run(
        [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_env_example_covers_every_environment_variable_settings_reads():
    """Every os.environ key read in config/settings.py has a matching key in .env.example, and vice versa."""
    settings_source = (REPO_ROOT / "config" / "settings.py").read_text()
    env_source = (REPO_ROOT / ".env.example").read_text()

    read_pattern = re.compile(
        r"os\.environ\.get\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']"
        r"|os\.environ\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']\s*\]"
    )
    settings_vars = {
        m.group(1) or m.group(2) for m in read_pattern.finditer(settings_source)
    }

    env_vars = set()
    for line in env_source.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        env_vars.add(line.split("=", 1)[0].strip())

    missing_from_env_example = settings_vars - env_vars
    missing_from_settings = env_vars - settings_vars
    assert not missing_from_env_example, (
        f"settings.py reads these but .env.example is missing them: {missing_from_env_example}"
    )
    assert not missing_from_settings, (
        f".env.example declares these but settings.py never reads them: {missing_from_settings}"
    )


def test_compose_declares_postgres_16_with_a_named_data_volume():
    """docker-compose.yml's db service uses a postgres:16 image and mounts a named volume at the data directory."""
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())

    db_service = compose["services"]["db"]
    assert db_service["image"].startswith("postgres:16"), db_service["image"]

    named_volumes = set(compose.get("volumes", {}) or {})
    assert named_volumes, "docker-compose.yml declares no top-level named volumes"

    data_mounts = [
        v for v in db_service.get("volumes", [])
        if isinstance(v, str) and v.split(":")[1:2] == ["/var/lib/postgresql/data"]
    ]
    assert data_mounts, "db service does not mount anything at /var/lib/postgresql/data"

    mounted_source = data_mounts[0].split(":")[0]
    assert mounted_source in named_volumes, (
        f"data directory is mounted from {mounted_source!r}, which is not a named volume "
        f"(named volumes declared: {named_volumes}); an anonymous volume or bind-mount "
        "path will not persist reliably across `docker compose down`"
    )
```

## 4. Validation commands

From the repo root, in order:

```
docker compose build
docker compose up -d
docker compose exec web python manage.py migrate
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
```

Both `pytest -v` and `makemigrations --check --dry-run` must be clean, per
`CLAUDE.md`.

Persistence-across-restart proof, using a disposable probe table so it doesn't
depend on any domain model existing:

```
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "CREATE TABLE task_001_persistence_probe (id serial primary key);"
docker compose down
docker compose up -d
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "\dt task_001_persistence_probe"
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "DROP TABLE task_001_persistence_probe;"
```

The `\dt` output must list `task_001_persistence_probe` after the
down/up cycle — proof the named volume, not the container, is what's holding
the data.

## 5. Self-check against CLAUDE.md hard constraints

- **Postgres 16 only. SQLite is forbidden, including in tests.** Complied with
  directly — enforced by tests 1–3 (`test_database_vendor_is_postgresql`,
  `test_settings_contain_no_sqlite_engine`, `test_postgres_server_version_is_16`).
- **No Celery, no Redis, no message broker. Scheduling is cron plus a Django
  management command.** Not exercised by this task — there is no scheduler yet.
  Nothing introduced here is a broker.
- **Money is always Decimal. Never float. Never FloatField.** Not applicable —
  no domain models exist in this task, so no money fields exist to violate it.
- **RawListing is immutable after write.** Not applicable — RawListing doesn't
  exist yet.
- **Facebook Marketplace is out of scope permanently.** Not applicable — no
  ingestion code exists in this task.
- **Python 3.12, Django 5.2, DRF. No framework substitutions.** Python and
  Django are pinned directly by the `Dockerfile` and `requirements.txt`. **DRF
  is ambiguous for this task, and that ambiguity is being named rather than
  resolved**: Section 1's out-of-scope list puts DRF out of scope for this
  task, but this constraint bullet lists DRF alongside Python and Django as if
  it were part of a fixed stack that should already be present. This task
  treats "DRF may never be substituted for something else" as compatible with
  "DRF is not yet installed in phase 0," but that reading is an interpretation,
  not a stated fact — flagged here instead of picked silently.
- **Timestamps are stored in UTC, USE_TZ is True. Display timezone is
  Asia/Manila and is a separate setting, never the storage timezone.**
  Complied with directly — enforced by tests 4 and 5
  (`test_use_tz_is_true_and_storage_timezone_is_utc`,
  `test_display_timezone_is_asia_manila`).
- **No frontend framework before phase 6. Django admin is the UI until then.**
  Not applicable yet — no frontend is added, and there is nothing to
  administer.
- **Secrets come from environment variables. Never hardcoded, never
  committed.** Complied with directly — enforced by test 6
  (`test_secret_key_is_loaded_from_environment`). Test 9
  (`test_env_example_covers_every_environment_variable_settings_reads`)
  additionally guarantees the documented and actually-read variable sets can
  never silently drift apart.

## 6. Unknowns

Everything below would have had to be guessed to implement this task. None of
it is resolved here.

- The exact Postgres 16 image tag/variant to pin in `docker-compose.yml` —
  plain `postgres:16`, a specific `16.x` patch, or an `-alpine` variant. The
  acceptance test only checks the `postgres:16` prefix, deliberately, so this
  stays open.
- The exact Django 5.2 patch version and the exact `psycopg` driver
  package/version to pin in `requirements.txt` (`psycopg2-binary` vs.
  `psycopg[binary]`, i.e. psycopg3 — Django 5.2 supports both, and I don't know
  which is the better default here).
- The exact Python 3.12 patch tag for the `Dockerfile` base image.
- Whether Django 5.2's `makemigrations --check --dry-run` is guaranteed to
  exit 0 when `INSTALLED_APPS` contains zero apps with models. I believe this
  has been stable behavior across recent Django versions but am not certain it
  holds unchanged in 5.2 specifically.
- Whether pytest-django resolves `DJANGO_SETTINGS_MODULE` correctly from
  `pytest.ini` alone inside the container, or whether the same-named
  environment variable must also be set in `docker-compose.yml`'s
  `environment:` block for the `web` service. I have not verified the
  precedence between the two for pytest-django on Django 5.2.
- Whether a Postgres healthcheck (`pg_isready`, and its exact flags) combined
  with `depends_on: condition: service_healthy` is needed so the `web` service
  doesn't attempt to connect before `db` is ready to accept connections. A real
  design question for whoever implements this task, not resolved here.
