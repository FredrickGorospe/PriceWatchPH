"""Frozen TASK_036 production-scheduler acceptance tests.

These tests intentionally fail at the TASK_034 checkpoint. They describe the
approved scheduler boundary without implementing production behavior.
"""

from __future__ import annotations

import ast
import fcntl
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEDULER_PATH = REPO_ROOT / "production_scheduler.py"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
LOCK_MOUNT = "/run/pricewatchph-scheduler"
SCHEDULE_SETTING = "PRICEWATCHPH_SCHEDULER_CRON"
AUTHORIZED_COMMANDS = (
    "resolve_listings",
    "price_listings",
    "send_deal_alerts",
)
FORBIDDEN_COMMANDS = {
    "ingest",
    "bootstrap_demo_data",
    "runserver",
    "migrate",
    "collectstatic",
}
SECRET_IDENTIFIERS = {
    "DJANGO_SECRET_KEY",
    "DJANGO_SELLER_PSEUDONYM_KEY",
    "POSTGRES_PASSWORD",
    "PRICEWATCHPH_TELEGRAM_BOT_TOKEN",
    "PRICEWATCHPH_TELEGRAM_CHAT_ID",
    "PRICEWATCHPH_ALERT_ACTIVATION_AT",
}


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text())


@pytest.fixture
def scheduler_module() -> ModuleType:
    if not SCHEDULER_PATH.is_file():
        class MissingScheduler:
            def __getattr__(self, name):
                pytest.fail("TASK_036 production scheduler is not implemented")

        return MissingScheduler()

    spec = importlib.util.spec_from_file_location(
        "task036_production_scheduler",
        SCHEDULER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recorded_commands(run_mock) -> list[str]:
    commands = []
    for recorded in run_mock.call_args_list:
        argv = recorded.args[0]
        assert isinstance(argv, list)
        assert len(argv) == 3
        assert Path(argv[0]).name == "python"
        assert Path(argv[1]).name == "manage.py"
        commands.append(argv[2])
        assert recorded.kwargs.get("shell", False) is False
        assert recorded.kwargs.get("env") is None
        assert Path(recorded.kwargs["cwd"]).resolve() == REPO_ROOT.resolve()
    return commands


def _completed(returncode: int) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode)


def test_compose_declares_scheduler_using_the_application_build():
    compose = _compose()
    scheduler = compose["services"]["scheduler"]
    web = compose["services"]["web"]

    assert scheduler.get("build") == web.get("build")
    assert scheduler.get("image") == web.get("image")
    assert scheduler.get("env_file") == web.get("env_file") == [
        "${PRICEWATCHPH_APP_ENV_FILE:-.env}"
    ]
    assert scheduler["command"] == [
        "/usr/local/bin/python",
        "/app/production_scheduler.py",
        "--serve",
    ]


def test_scheduler_waits_for_database_health_and_successful_migration():
    scheduler = _compose()["services"]["scheduler"]

    assert scheduler["depends_on"]["db"]["condition"] == "service_healthy"
    assert (
        scheduler["depends_on"]["migrate"]["condition"]
        == "service_completed_successfully"
    )
    assert "migrate" not in " ".join(scheduler["command"])


def test_scheduler_has_deliberate_restart_no_ingress_and_no_custom_network():
    scheduler = _compose()["services"]["scheduler"]

    assert scheduler["restart"] == "unless-stopped"
    assert not scheduler.get("ports")
    assert not scheduler.get("expose")
    assert not scheduler.get("healthcheck")
    assert not scheduler.get("networks")


def test_scheduler_uses_explicit_utc_and_a_shared_named_lock_volume():
    compose = _compose()
    scheduler = compose["services"]["scheduler"]

    assert scheduler["environment"]["TZ"] == "UTC"
    lock_mounts = [
        mount
        for mount in scheduler.get("volumes", [])
        if isinstance(mount, str) and mount.endswith(f":{LOCK_MOUNT}")
    ]
    assert len(lock_mounts) == 1
    volume_name = lock_mounts[0].split(":", 1)[0]
    assert volume_name == "scheduler_lock"
    assert volume_name in (compose.get("volumes") or {})


def test_schedule_is_required_by_compose_without_a_default():
    scheduler = _compose()["services"]["scheduler"]
    interpolation = scheduler["environment"][SCHEDULE_SETTING]

    assert interpolation.startswith(f"${{{SCHEDULE_SETTING}:?")
    assert interpolation.endswith("}")
    assert ":-" not in interpolation


def test_env_example_and_settings_keep_task_001_symmetry():
    env_lines = (REPO_ROOT / ".env.example").read_text().splitlines()
    schedule_lines = [
        line for line in env_lines if line.startswith(f"{SCHEDULE_SETTING}=")
    ]
    assert schedule_lines == [f"{SCHEDULE_SETTING}=change_me"]

    settings_source = (REPO_ROOT / "config" / "settings.py").read_text()
    assert f'os.environ.get("{SCHEDULE_SETTING}", "")' in settings_source


@pytest.mark.parametrize(
    "value",
    [
        "* * * * *",
        "*/15 * * * *",
        "0 * * * *",
        "0 */6 * * *",
        "30 2 * * *",
    ],
)
def test_narrow_schedule_grammar_accepts_safe_deployment_cadences(
    scheduler_module,
    value,
):
    assert scheduler_module.validate_schedule(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "change_me",
        "@hourly",
        "* * * *",
        "* * * * * extra",
        "* * * * *\n* * * * * /bin/true",
        "* * * * *; /bin/true",
        "60 * * * *",
        "*/0 * * * *",
        "*/60 * * * *",
        "0 24 * * *",
        "0 */0 * * *",
        "0 */24 * * *",
        "0 0 1 * *",
        "0 0 * 1 *",
        "0 0 * * 1",
        "0,15 * * * *",
        "0-15 * * * *",
        "midnight * * * *",
    ],
)
def test_schedule_grammar_rejects_invalid_calendar_or_injection_input(
    scheduler_module,
    value,
):
    with pytest.raises(ValueError, match=SCHEDULE_SETTING):
        scheduler_module.validate_schedule(value)


def test_invalid_serve_configuration_fails_loudly_before_daemon_exec(
    scheduler_module,
    monkeypatch,
    capsys,
):
    from django.conf import settings

    monkeypatch.setattr(settings, "SCHEDULER_CRON", "* * * * *; /bin/true")
    called = False

    def forbidden_exec(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(os, "execv", forbidden_exec)
    assert scheduler_module.main(["--serve"]) != 0

    captured = capsys.readouterr()
    assert SCHEDULE_SETTING in captured.err
    assert captured.out == ""
    assert called is False


def test_rendered_crontab_has_fixed_pipeline_mode_and_no_secret_material(
    scheduler_module,
    monkeypatch,
):
    for identifier in SECRET_IDENTIFIERS:
        monkeypatch.setenv(identifier, f"task036-secret-{identifier}")

    rendered = scheduler_module.render_crontab("*/15 * * * *")
    lines = rendered.splitlines()

    assert lines[:3] == [
        "SHELL=/bin/sh",
        "PATH=/usr/local/bin:/usr/bin:/bin",
        "HOME=/app",
    ]
    assert len(lines) == 4
    assert lines[3].startswith("*/15 * * * * ")
    assert (
        "/usr/local/bin/python /app/production_scheduler.py --run-pipeline"
        in lines[3]
    )
    assert ">>/proc/1/fd/1 2>>/proc/1/fd/2" in lines[3]
    assert not any(line.startswith(("TZ=", "CRON_TZ=")) for line in lines)
    for identifier in SECRET_IDENTIFIERS:
        assert identifier not in rendered
        assert f"task036-secret-{identifier}" not in rendered


def test_final_application_image_provides_selected_scheduler_binaries():
    busybox = subprocess.run(
        ["/usr/bin/busybox", "crond", "--help"],
        capture_output=True,
        text=True,
    )
    tini = subprocess.run(
        ["/usr/bin/tini", "--version"],
        capture_output=True,
        text=True,
    )

    assert busybox.returncode in {0, 1}
    assert "crond" in busybox.stdout + busybox.stderr
    assert tini.returncode == 0
    assert "tini version" in (tini.stdout + tini.stderr).lower()


def test_pipeline_invokes_only_fixed_authorized_commands_in_order(
    scheduler_module,
    monkeypatch,
    tmp_path,
):
    run_mock = Mock(return_value=_completed(0))
    monkeypatch.setattr(scheduler_module.subprocess, "run", run_mock)

    assert scheduler_module.run_pipeline(lock_path=tmp_path / "pipeline.lock") == 0
    assert _recorded_commands(run_mock) == list(AUTHORIZED_COMMANDS)
    assert not (set(_recorded_commands(run_mock)) & FORBIDDEN_COMMANDS)


def test_command_selection_cannot_be_overridden_from_environment(
    scheduler_module,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("PRICEWATCHPH_SCHEDULER_COMMAND", "ingest")
    monkeypatch.setenv("DJANGO_MANAGEMENT_COMMAND", "bootstrap_demo_data")
    monkeypatch.setenv("COMMAND", "migrate")
    run_mock = Mock(return_value=_completed(0))
    monkeypatch.setattr(scheduler_module.subprocess, "run", run_mock)

    assert scheduler_module.run_pipeline(lock_path=tmp_path / "pipeline.lock") == 0
    assert _recorded_commands(run_mock) == list(AUTHORIZED_COMMANDS)


@pytest.mark.parametrize(
    ("failed_stage", "status", "expected_calls"),
    [
        ("resolve_listings", 11, ["resolve_listings"]),
        ("price_listings", 12, ["resolve_listings", "price_listings"]),
        (
            "send_deal_alerts",
            13,
            ["resolve_listings", "price_listings", "send_deal_alerts"],
        ),
    ],
)
def test_failed_stage_is_visible_returns_its_status_and_blocks_later_stages(
    scheduler_module,
    monkeypatch,
    tmp_path,
    capsys,
    failed_stage,
    status,
    expected_calls,
):
    codes = {
        command: status if command == failed_stage else 0
        for command in AUTHORIZED_COMMANDS
    }

    def result_for(argv, **kwargs):
        return _completed(codes[argv[2]])

    run_mock = Mock(side_effect=result_for)
    monkeypatch.setattr(scheduler_module.subprocess, "run", run_mock)

    result = scheduler_module.run_pipeline(lock_path=tmp_path / "pipeline.lock")

    assert result == status
    assert _recorded_commands(run_mock) == expected_calls
    captured = capsys.readouterr()
    assert f"Scheduler stage failed: {failed_stage} exit_status={status}\n" in captured.err
    assert "Scheduler pipeline complete." not in captured.out


def test_success_output_names_every_stage_and_preserves_child_streams(
    scheduler_module,
    monkeypatch,
    tmp_path,
    capsys,
):
    def child_output(argv, **kwargs):
        print(f"child stdout: {argv[2]}")
        print(f"child stderr: {argv[2]}", file=sys.stderr)
        return _completed(0)

    run_mock = Mock(side_effect=child_output)
    monkeypatch.setattr(scheduler_module.subprocess, "run", run_mock)

    assert scheduler_module.run_pipeline(lock_path=tmp_path / "pipeline.lock") == 0

    captured = capsys.readouterr()
    for command in AUTHORIZED_COMMANDS:
        start = f"Scheduler stage starting: {command}\n"
        child = f"child stdout: {command}\n"
        complete = f"Scheduler stage complete: {command}\n"
        assert start in captured.out
        assert child in captured.out
        assert complete in captured.out
        assert captured.out.index(start) < captured.out.index(child)
        assert captured.out.index(child) < captured.out.index(complete)
        assert f"child stderr: {command}\n" in captured.err
    assert captured.out.endswith("Scheduler pipeline complete.\n")


def test_overlap_is_an_observable_no_op_before_any_command(
    scheduler_module,
    monkeypatch,
    tmp_path,
    capsys,
):
    lock_path = tmp_path / "pipeline.lock"
    lock_path.touch(mode=0o600)
    with lock_path.open("r+") as held_lock:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_mock = Mock(side_effect=AssertionError("overlap launched a stage"))
        monkeypatch.setattr(scheduler_module.subprocess, "run", run_mock)

        result = scheduler_module.run_pipeline(lock_path=lock_path)

    assert result == 0
    run_mock.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == "Scheduler pipeline skipped: another run is active.\n"
    assert captured.err == ""


def test_failure_releases_lock_and_next_normal_run_is_not_an_internal_retry(
    scheduler_module,
    monkeypatch,
    tmp_path,
):
    lock_path = tmp_path / "pipeline.lock"
    first_run = Mock(side_effect=[_completed(0), _completed(19)])
    monkeypatch.setattr(scheduler_module.subprocess, "run", first_run)

    assert scheduler_module.run_pipeline(lock_path=lock_path) == 19
    assert _recorded_commands(first_run) == ["resolve_listings", "price_listings"]

    next_run = Mock(return_value=_completed(0))
    monkeypatch.setattr(scheduler_module.subprocess, "run", next_run)

    assert scheduler_module.run_pipeline(lock_path=lock_path) == 0
    assert _recorded_commands(next_run) == list(AUTHORIZED_COMMANDS)
    assert next_run.call_count == 3


def test_alert_stage_is_only_the_existing_command_without_retry_or_resend_flags(
    scheduler_module,
    monkeypatch,
    tmp_path,
):
    run_mock = Mock(return_value=_completed(0))
    monkeypatch.setattr(scheduler_module.subprocess, "run", run_mock)

    assert scheduler_module.run_pipeline(lock_path=tmp_path / "pipeline.lock") == 0

    alert_calls = [
        recorded for recorded in run_mock.call_args_list if recorded.args[0][2] == "send_deal_alerts"
    ]
    assert len(alert_calls) == 1
    assert alert_calls[0].args[0][2:] == ["send_deal_alerts"]
    assert "--force" not in alert_calls[0].args[0]
    assert "--resend" not in alert_calls[0].args[0]
    assert "--retry" not in alert_calls[0].args[0]


def test_scheduler_has_no_direct_telegram_or_alert_delivery_implementation():
    assert SCHEDULER_PATH.is_file()
    source = SCHEDULER_PATH.read_text()
    tree = ast.parse(source)

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any(module == "alerts" or module.startswith("alerts.") for module in imported_modules)
    assert "send_telegram_message" not in source
    assert "AlertDelivery" not in source
    assert "urlopen" not in source


def test_scheduler_uses_django_settings_instead_of_reading_environment_directly():
    assert SCHEDULER_PATH.is_file()
    source = SCHEDULER_PATH.read_text()
    tree = ast.parse(source)

    assert (
        'os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")'
        in source
    )
    assert "settings.SCHEDULER_CRON" in source

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
                and node.func.attr == "getenv"
            ):
                pytest.fail("scheduler must not read configuration with os.getenv")
            if (
                isinstance(node.func.value, ast.Attribute)
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "os"
                and node.func.value.attr == "environ"
                and node.func.attr == "get"
            ):
                pytest.fail("scheduler must not read configuration with os.environ.get")
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "os"
            and node.value.attr == "environ"
        ):
            pytest.fail("scheduler must not index os.environ for configuration")

    env_example = (REPO_ROOT / ".env.example").read_text()
    assert "DJANGO_SETTINGS_MODULE=" not in env_example


def test_serve_bootstraps_django_settings_in_a_standalone_process():
    assert SCHEDULER_PATH.is_file()
    environment = os.environ.copy()
    environment.pop("DJANGO_SETTINGS_MODULE", None)
    environment.pop(SCHEDULE_SETTING, None)

    result = subprocess.run(
        [sys.executable, str(SCHEDULER_PATH), "--serve"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert SCHEDULE_SETTING in result.stderr
    assert "settings are not configured" not in result.stderr.lower()
    assert "DJANGO_SETTINGS_MODULE" not in result.stderr


def test_scheduler_artifacts_embed_no_secret_identifiers_or_values(monkeypatch):
    assert SCHEDULER_PATH.is_file()
    scheduler_source = SCHEDULER_PATH.read_text()
    compose_source = COMPOSE_PATH.read_text()

    for identifier in SECRET_IDENTIFIERS:
        assert identifier not in scheduler_source
        assert f"task036-secret-{identifier}" not in scheduler_source
        assert f"task036-secret-{identifier}" not in compose_source


def test_scheduler_introduces_no_model_or_migration_surface():
    assert not (REPO_ROOT / "scheduler" / "models.py").exists()
    assert not (REPO_ROOT / "scheduler" / "migrations").exists()
    if SCHEDULER_PATH.exists():
        source = SCHEDULER_PATH.read_text()
        assert "django.db" not in source
        assert "migrate" not in source
