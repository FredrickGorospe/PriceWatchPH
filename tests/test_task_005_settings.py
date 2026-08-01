import importlib

import pytest


def test_pseudonym_key_is_loaded_from_environment(monkeypatch):
    """Reloading config.settings with a different DJANGO_SELLER_PSEUDONYM_KEY changes SELLER_PSEUDONYM_KEY."""
    from config import settings as settings_module

    monkeypatch.setenv("DJANGO_SELLER_PSEUDONYM_KEY", "task-005-marker-key")
    importlib.reload(settings_module)
    try:
        assert settings_module.SELLER_PSEUDONYM_KEY == "task-005-marker-key"
    finally:
        monkeypatch.undo()
        importlib.reload(settings_module)


def test_missing_pseudonym_key_fails_loudly_at_settings_load(monkeypatch):
    """config.settings raises KeyError when DJANGO_SELLER_PSEUDONYM_KEY is absent — it never falls back to a default."""
    from config import settings as settings_module

    monkeypatch.delenv("DJANGO_SELLER_PSEUDONYM_KEY", raising=False)
    try:
        with pytest.raises(KeyError):
            importlib.reload(settings_module)
    finally:
        monkeypatch.undo()
        importlib.reload(settings_module)


def test_aggregation_timezone_is_manila_and_is_distinct_from_storage_and_display():
    """The day-bucketing timezone is its own setting: Manila, never merged with TIME_ZONE or DISPLAY_TIME_ZONE."""
    from django.conf import settings

    assert settings.AGGREGATION_TIME_ZONE == "Asia/Manila"
    # Storage must stay UTC even though two non-UTC zone settings now exist.
    assert settings.TIME_ZONE == "UTC"
    assert settings.TIME_ZONE != settings.AGGREGATION_TIME_ZONE


def test_aggregation_timezone_is_not_environment_configurable():
    """AGGREGATION_TIME_ZONE is a hardcoded constant: changing it rebuckets all history, so it must not be an env var."""
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "config" / "settings.py").read_text()
    assignment = re.search(r"^AGGREGATION_TIME_ZONE\s*=\s*(.+)$", source, re.MULTILINE)
    assert assignment, "AGGREGATION_TIME_ZONE is not assigned in config/settings.py"
    assert "os.environ" not in assignment.group(1), (
        f"AGGREGATION_TIME_ZONE must be a literal, got: {assignment.group(1)!r}"
    )
