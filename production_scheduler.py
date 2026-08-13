"""Run the fixed production pricing and alert pipeline on a cron cadence."""

from __future__ import annotations

import argparse
import fcntl
import os
import re
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.conf import settings


APP_DIR = Path("/app")
PYTHON = Path("/usr/local/bin/python")
MANAGE_PY = APP_DIR / "manage.py"
SCHEDULER_SCRIPT = APP_DIR / "production_scheduler.py"
CRONTAB_DIR = Path("/var/spool/cron/crontabs")
CRONTAB_PATH = CRONTAB_DIR / "root"
LOCK_PATH = Path("/run/pricewatchph-scheduler/pipeline.lock")
SCHEDULE_SETTING = "PRICEWATCHPH_SCHEDULER_CRON"

PIPELINE_COMMANDS = (
    "resolve_listings",
    "price_listings",
    "send_deal_alerts",
)

_INTEGER_PATTERN = re.compile(r"[0-9]+\Z")
_STEP_PATTERN = re.compile(r"\*/([0-9]+)\Z")


def _validate_time_field(field: str, *, maximum: int) -> None:
    if field == "*":
        return

    if _INTEGER_PATTERN.fullmatch(field):
        if 0 <= int(field) <= maximum:
            return
        raise ValueError

    step_match = _STEP_PATTERN.fullmatch(field)
    if step_match and 1 <= int(step_match.group(1)) <= maximum:
        return

    raise ValueError


def validate_schedule(value: str) -> str:
    """Return a safe five-field cadence or raise a setting-named error."""
    message = (
        f"{SCHEDULE_SETTING} must be five safe cron fields with wildcard "
        "calendar fields."
    )

    if not isinstance(value, str) or not value:
        raise ValueError(message)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(message)
    if value != value.strip():
        raise ValueError(message)

    fields = value.split(" ")
    if len(fields) != 5 or any(not field for field in fields):
        raise ValueError(message)

    minute, hour, day_of_month, month, day_of_week = fields
    try:
        _validate_time_field(minute, maximum=59)
        _validate_time_field(hour, maximum=23)
    except ValueError as error:
        raise ValueError(message) from error

    if (day_of_month, month, day_of_week) != ("*", "*", "*"):
        raise ValueError(message)

    return value


def render_crontab(schedule: str) -> str:
    """Render one fixed, secret-free BusyBox crontab."""
    validated_schedule = validate_schedule(schedule)
    return (
        "SHELL=/bin/sh\n"
        "PATH=/usr/local/bin:/usr/bin:/bin\n"
        "HOME=/app\n"
        f"{validated_schedule} {PYTHON} {SCHEDULER_SCRIPT} --run-pipeline "
        ">>/proc/1/fd/1 2>>/proc/1/fd/2\n"
    )


def _write_crontab(content: str) -> None:
    CRONTAB_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    CRONTAB_DIR.chmod(0o700)

    descriptor = os.open(
        CRONTAB_PATH,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as stream:
            stream.write(content)
            stream.flush()
    finally:
        os.close(descriptor)


def _run_locked_pipeline() -> int:
    for command in PIPELINE_COMMANDS:
        print(f"Scheduler stage starting: {command}", flush=True)
        result = subprocess.run(
            [str(PYTHON), str(MANAGE_PY), command],
            cwd=APP_DIR,
            shell=False,
        )
        if result.returncode != 0:
            print(
                f"Scheduler stage failed: {command} "
                f"exit_status={result.returncode}",
                file=sys.stderr,
                flush=True,
            )
            return result.returncode
        print(f"Scheduler stage complete: {command}", flush=True)

    print("Scheduler pipeline complete.", flush=True)
    return 0


def run_pipeline(*, lock_path: Path = LOCK_PATH) -> int:
    """Run the fixed pipeline once, or visibly skip an overlapping run."""
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path.parent.chmod(0o700)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(
                "Scheduler pipeline skipped: another run is active.",
                flush=True,
            )
            return 0
        return _run_locked_pipeline()
    finally:
        os.close(descriptor)


def _serve() -> int:
    try:
        crontab = render_crontab(settings.SCHEDULER_CRON)
    except ValueError as error:
        print(str(error), file=sys.stderr, flush=True)
        return 2

    _write_crontab(crontab)
    tini = "/usr/bin/tini"
    os.execv(
        tini,
        [
            tini,
            "-g",
            "--",
            "/usr/bin/busybox",
            "crond",
            "-f",
            "-l",
            "8",
            "-L",
            "/dev/stdout",
            "-c",
            str(CRONTAB_DIR),
        ],
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true")
    mode.add_argument("--run-pipeline", action="store_true")
    arguments = parser.parse_args(argv)

    if arguments.serve:
        return _serve()
    return run_pipeline()


if __name__ == "__main__":
    raise SystemExit(main())
