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
