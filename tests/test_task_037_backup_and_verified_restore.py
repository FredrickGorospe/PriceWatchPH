"""Frozen TASK_037 PostgreSQL backup and verified-restore tests.

TASK_037 owns the backup mechanism, its artifact format and safety properties,
the destination abstraction, the SELLER_PSEUDONYM_KEY recovery contract, and
the isolated scratch restore drill that proves a dump is actually restorable.
See tasks/TASK_037_BACKUP_AND_VERIFIED_RESTORE.md and docs/09_PLANNING.md
§3.7, §9 (TASK_037), §11 item 7.

This module is deliberately split into two halves, because a real restore
cannot honestly be proven inside an ordinary in-container pytest run: the
application image is python:3.12-slim + psycopg[binary] and contains no
pg_dump/pg_restore binary at all (task file §3.6).

    A. Static/contract tests — always run. They freeze the safety properties
       of the compose services and the two scripts.

    B. The integration restore drill — skipped unless the
       PRICEWATCHPH_T037_SCRATCH_* variables point at a genuinely restored
       scratch database, which pg_restore_verify.sh supplies. These assert the
       task file §12 verification criteria against real restored data.

pg_dump and pg_restore are NEVER mocked in this module. A mocked restore
proves nothing about recovery, so the static half asserts only properties that
are honestly static, and every claim about restored data lives in half B.

Half B additionally refuses to run unless its target database is the scratch
sentinel name, so this module can never be pointed at the live database.
"""

import hashlib
import hmac
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

BACKUP_SERVICE = "backup"
SCRATCH_SERVICE = "restore_scratch"
BACKUP_PROFILE = "backup"
RESTORE_PROFILE = "restore-verify"
SOURCE_DB_SENTINEL = "pricewatch_backup_source_scratch"
SCRATCH_DB_SENTINEL = "pricewatch_restore_scratch"
BACKUP_SCRIPT = "pg_backup.sh"
RESTORE_SCRIPT = "pg_restore_verify.sh"
DRILL_BACKUP_RUNNER_FUNCTION = "run_drill_backup"
CONTAINER_BACKUP_DIR = "/backups"
ARTIFACT_PATTERN = r"^pricewatchph-[0-9]{8}T[0-9]{6}Z\.dump$"
TASK_SCRATCH_VOLUME = "task037_scratch_data"

REPRESENTATIVE_TABLES = {
    "sources_source",
    "catalogue_sku",
    "catalogue_skualias",
    "ingestion_rawlisting",
    "ingestion_swap",
    "listings_listing",
    "pricing_pricepoint",
    "pricing_dealflag",
    "outcomes_outcome",
    "alerts_alertdelivery",
}

# Secrets that must never reach the backup/restore path (task file §9.1, §10).
FORBIDDEN_SECRET_ENV = ("DJANGO_SELLER_PSEUDONYM_KEY", "DJANGO_SECRET_KEY")

EXPECTED_TRIGGERS = {
    ("ingestion_rawlisting", "rawlisting_immutable"),
    ("pricing_pricepoint", "pricing_pricepoint_task019_immutable"),
    ("pricing_dealflag", "pricing_dealflag_task019_immutable"),
    ("alerts_alertdelivery", "alerts_alertdelivery_task030_lifecycle_guard"),
}

EXPECTED_TABLES = {
    "alerts_alertdelivery",
    "auth_group",
    "auth_group_permissions",
    "auth_permission",
    "auth_user",
    "auth_user_groups",
    "auth_user_user_permissions",
    "catalogue_sku",
    "catalogue_skualias",
    "django_admin_log",
    "django_content_type",
    "django_migrations",
    "django_session",
    "ingestion_rawlisting",
    "ingestion_swap",
    "listings_listing",
    "outcomes_outcome",
    "pricing_dealflag",
    "pricing_pricepoint",
    "sources_source",
}


def _compose():
    return yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())


def _service(name):
    services = _compose()["services"]
    if name not in services:
        pytest.fail(
            f"docker-compose.yml must define a {name!r} service "
            f"(TASK_037 task file §6.1/§11.2); found: {sorted(services)}"
        )
    return services[name]


def _script(name):
    path = REPO_ROOT / name
    if not path.is_file():
        pytest.fail(f"TASK_037 must add {name} at the repository root")
    return path.read_text()


def _shell_function_body(text, name):
    match = re.search(
        rf"(?ms)^\s*{re.escape(name)}\(\)\s*\{{\s*\n(?P<body>.*?)^\s*\}}\s*$",
        text,
    )
    if not match:
        pytest.fail(f"{RESTORE_SCRIPT} must define shell function {name}()")
    return match.group("body")


def _normalise_shell(text):
    return re.sub(r"\\\s*\n\s*", " ", text)


def _auditable_backup_runner(text):
    runner = _shell_function_body(text, DRILL_BACKUP_RUNNER_FUNCTION)
    assert not re.search(r"(?m)^\s*\w+\(\)\s*\{", runner), (
        "the direct backup runner must not hide a nested shell function"
    )
    assert "<<" not in runner, (
        "the direct backup runner must remain line-delimited and statically auditable"
    )
    return runner


def _backup_runner_command(runner):
    normalised = _normalise_shell(runner)
    calls = list(
        re.finditer(
            r"(?m)^\s*if\s+docker\s+run\s+(?P<arguments>.*?)\s*;\s*then\s*$",
            normalised,
        )
    )
    assert len(calls) == 1, (
        "run_drill_backup() must contain exactly one direct "
        "`if docker run ...; then` command"
    )
    assert len(re.findall(r"\bdocker\s+run\b", normalised)) == 1
    arguments = shlex.split(calls[0].group("arguments"), posix=True)
    assert not any(token in {";", "&&", "||", "|", "&"} for token in arguments)
    return normalised, calls[0], arguments


def _parse_backup_runner_arguments(arguments):
    """Parse only the small, explicit Docker option grammar frozen for the drill."""
    valued_options = {"--network", "--env", "--mount", "--tmpfs"}
    options = []
    index = 0
    while index < len(arguments) and arguments[index].startswith("-"):
        option = arguments[index]
        assert option in valued_options | {"--rm"}, (
            f"the direct backup runner uses forbidden Docker option {option!r}"
        )
        if option == "--rm":
            options.append((option, None))
            index += 1
            continue
        assert index + 1 < len(arguments), f"{option} requires an explicit value"
        options.append((option, arguments[index + 1]))
        index += 2

    assert index < len(arguments), "the direct Docker runner must name its image"
    return options, arguments[index], arguments[index + 1 :]


def _option_values(options, name):
    return [value for option, value in options if option == name]


def _mount_fields(specification):
    fields = {}
    for field in specification.split(","):
        key, separator, value = field.partition("=")
        assert key and key not in fields, f"invalid duplicate mount field: {key}"
        fields[key] = value if separator else True
    return fields


def _last_simple_assignment_before(text, variable, offset):
    matches = list(
        re.finditer(
            rf"(?m)^\s*{re.escape(variable)}=(?P<value>[^\n#]+?)\s*$",
            text[:offset],
        )
    )
    assert matches, f"{variable} must be assigned before the direct backup runner"
    return matches[-1].group("value").strip()


def _command_substitution_assignments(text):
    return list(
        re.finditer(
            r'(?ms)^\s*(?P<variable>[A-Z][A-Z0-9_]*)="\$\(\s*'
            r'(?P<command>.*?)\s*\)"\s*\|\|\s*return\s+1\s*$',
            text,
        )
    )


def _persistent_volume_inventory_assignments(text):
    assignments = []
    for match in _command_substitution_assignments(text):
        command = re.sub(r"\s+", " ", match.group("command")).strip()
        if command == "docker volume ls --quiet | LC_ALL=C sort":
            assignments.append(match)
    return assignments


def _backup_runner_call(text):
    pattern = re.compile(
        rf'(?m)^\s*if\s+BACKUP_OUTPUT="\$\(\s*'
        rf'{re.escape(DRILL_BACKUP_RUNNER_FUNCTION)}\s*\)"\s*;\s*then\s*$'
    )
    calls = list(pattern.finditer(text))
    assert len(calls) == 1, (
        "the drill must capture stdout from exactly one direct backup-runner call"
    )
    return calls[0]


def _env_keys(service):
    environment = service.get("environment") or {}
    if isinstance(environment, dict):
        return set(environment)
    return {entry.split("=", 1)[0] for entry in environment}


def _volume_strings(service):
    return [v for v in (service.get("volumes") or []) if isinstance(v, str)]


# ===========================================================================
# A. Static / contract tests
# ===========================================================================

# --- tooling and version strategy (task file §5) ---------------------------


def test_backup_and_scratch_services_use_the_db_services_exact_image_tag():
    """Client and server must match by construction. A floating or divergent
    tag would reintroduce the mismatched-client risk §3.6 rules out."""
    compose = _compose()
    db_image = compose["services"]["db"]["image"]
    assert db_image.startswith("postgres:16"), db_image
    for name in (BACKUP_SERVICE, SCRATCH_SERVICE):
        assert _service(name)["image"] == db_image, (
            f"{name} must pin the same image tag as db ({db_image})"
        )


def test_no_postgresql_client_is_added_to_the_application_image():
    """pg_dump/pg_restore come from the postgres image, never from a
    pip/apt addition to the app image (task file §5)."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    for token in ("pg_dump", "pg_restore", "postgresql-client", "libpq-dev"):
        assert token not in dockerfile, f"Dockerfile must not install {token}"
    requirements = (REPO_ROOT / "requirements.txt").read_text()
    assert "pgdump" not in requirements.lower()


def test_backup_uses_custom_format_and_never_a_data_directory_copy():
    """Custom format is the frozen choice (§4); a file/volume copy of a live
    cluster is not a database-consistent logical backup and is forbidden."""
    backup = _script(BACKUP_SCRIPT)
    assert "-Fc" in backup, "pg_dump must use custom format (-Fc)"
    assert "pg_dump" in backup
    for forbidden in (
        "/var/lib/postgresql/data",
        "postgres_data",
        "pg_basebackup",
        "tar ",
        "cp -r",
        "rsync",
    ):
        assert forbidden not in backup, (
            f"{BACKUP_SCRIPT} must not reference {forbidden!r}: a data-directory "
            "or volume copy is not a logical backup (§4)"
        )


# --- backup execution safety (task file §6) --------------------------------


def test_backup_service_is_profile_gated_and_one_shot():
    """It must never start during an ordinary `docker compose up`."""
    backup = _service(BACKUP_SERVICE)
    assert BACKUP_PROFILE in (backup.get("profiles") or [])
    assert str(backup.get("restart", "no")) == "no"
    assert backup["depends_on"]["db"]["condition"] == "service_healthy"


def test_backup_service_never_receives_the_pseudonym_key_or_django_secret():
    """Least privilege, and the structural reason the key cannot end up beside
    the dump (§6.1, §9.1). A blanket `env_file: .env` would hand the backup
    container every secret in the project."""
    backup = _service(BACKUP_SERVICE)
    assert "env_file" not in backup, (
        "the backup service must not load the whole .env; it needs only PG* "
        "connection variables"
    )
    keys = _env_keys(backup)
    for forbidden in FORBIDDEN_SECRET_ENV:
        assert forbidden not in keys, f"backup must not receive {forbidden}"
    assert keys == {"PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"}, keys


def test_backup_interpolation_is_inactive_safe_and_execution_rejects_empty_pg_values():
    """Model loading stays safe while execution rejects an unusable connection."""
    environment = _service(BACKUP_SERVICE).get("environment") or {}
    expected_interpolation = {
        "PGDATABASE": "${POSTGRES_DB:-}",
        "PGUSER": "${POSTGRES_USER:-}",
        "PGPASSWORD": "${POSTGRES_PASSWORD:-}",
    }
    for key, expected in expected_interpolation.items():
        assert environment.get(key) == expected
        assert ":?" not in str(environment[key]), (
            f"inactive {BACKUP_PROFILE!r} interpolation must not require {key}"
        )

    backup = _script(BACKUP_SCRIPT)
    before_dump = backup[: backup.index("pg_dump")]
    required = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
    assert re.search(
        r"for\s+\w+\s+in\s+PGHOST\s+PGPORT\s+PGDATABASE\s+PGUSER\s+PGPASSWORD",
        before_dump,
    )
    for variable in required:
        assert variable in before_dump, (
            f"{BACKUP_SCRIPT} must validate {variable} before pg_dump"
        )
    assert re.search(r"(?:-z|!\s+-n)[^\n]*printenv", before_dump), (
        "required PG variables must be checked for missing or empty values"
    )
    assert re.search(r"\bexit\s+[1-9][0-9]*\b", before_dump), (
        "missing or empty required PG variables must fail nonzero"
    )
    assert before_dump.index("printenv") < before_dump.index("ARTIFACT="), (
        "PG validation must precede artifact construction"
    )
    for secret_value in (
        "$PGPASSWORD",
        "${PGPASSWORD",
        "$POSTGRES_PASSWORD",
        "${POSTGRES_PASSWORD",
    ):
        assert not re.search(
            rf"(?:printf|echo)[^\n]*{re.escape(secret_value)}", before_dump
        ), "PG validation must never print password values"


def test_backup_password_is_passed_by_environment_not_on_the_command_line():
    """A password in argv is visible in `ps`."""
    backup = _service(BACKUP_SERVICE)
    command = backup.get("command")
    rendered = " ".join(command) if isinstance(command, list) else str(command)
    for forbidden in ("--password", "-W", "PGPASSWORD="):
        assert forbidden not in rendered, rendered
    assert _script(BACKUP_SCRIPT).count("--password") == 0


def test_backup_command_is_a_fixed_script_path_with_no_interpolated_shell():
    """No arbitrary command execution seam through the environment."""
    backup = _service(BACKUP_SERVICE)
    command = backup["command"]
    assert isinstance(command, list), "command must be exec-form, not a shell string"
    assert command == [f"/usr/local/bin/{BACKUP_SCRIPT}"], command
    assert not any("$" in part for part in command)


def test_backup_script_sets_a_restrictive_umask_before_dumping():
    """pg_dump's default output is 0644 — world readable — and the dump holds
    every pseudonym, price and personal record (§3.4)."""
    backup = _script(BACKUP_SCRIPT)
    assert re.search(r"^\s*umask\s+077\s*$", backup, re.MULTILINE), (
        f"{BACKUP_SCRIPT} must set `umask 077`"
    )
    assert backup.index("umask 077") < backup.index("pg_dump"), (
        "umask must be set before the dump is created"
    )


def test_backup_script_aborts_on_error():
    assert re.search(r"set -[eu]+", _script(BACKUP_SCRIPT))


def test_backup_script_refuses_to_overwrite_an_existing_artifact():
    """`pg_dump -f` silently overwrites and exits 0, which would destroy the
    last known-good dump on a name collision (§3.3)."""
    backup = _script(BACKUP_SCRIPT)
    assert "exit 3" in backup, (
        f"{BACKUP_SCRIPT} must refuse a pre-existing artifact with exit 3"
    )
    assert backup.index("exit 3") < backup.index("pg_dump"), (
        "the refusal must happen before any dump is attempted"
    )


def test_backup_script_publishes_a_verified_pair_and_claims_no_pair_atomicity():
    """Each rename may be atomic, but two final files cannot appear atomically
    as one unit. Success is allowed only after the complete pair verifies."""
    backup = _script(BACKUP_SCRIPT)
    assert backup.count(".partial") >= 2, (
        "both dump and checksum must be prepared under .partial names"
    )
    assert "pg_restore --list" in backup, "structure must be validated (§3.5)"
    assert len(re.findall(r"^\s*mv\s", backup, re.MULTILINE)) >= 2, (
        "the dump and sidecar must each be published by rename"
    )
    assert "sha256sum" in backup
    assert "sha256sum -c" in backup
    assert "BACKUP_ARTIFACT=" in backup

    dump = backup.index("pg_dump")
    validate = backup.index("pg_restore --list")
    checksum_write = backup.index("sha256sum")
    first_rename = backup.index("mv ")
    final_verify = backup.index("sha256sum -c")
    success = backup.index("BACKUP_ARTIFACT=")
    assert dump < validate < checksum_write < first_rename < final_verify < success, (
        "required order: dump -> structural validation -> checksum preparation -> "
        "publish both files -> verify final pair -> success record"
    )


def test_backup_refuses_collision_with_either_member_of_the_final_pair():
    backup = _script(BACKUP_SCRIPT)
    before_dump = backup[: backup.index("pg_dump")]
    assert ".sha256" in before_dump, "collision guard must include the sidecar"
    assert "exit 3" in before_dump


def test_backup_success_record_is_machine_readable_and_emitted_last():
    backup = _script(BACKUP_SCRIPT)
    assert re.search(r"BACKUP_ARTIFACT=%s", backup)
    success = backup.index("BACKUP_ARTIFACT=")
    assert backup.index("sha256sum -c") < success
    assert backup.index("pg_restore --list") < success


def test_backup_artifact_name_is_utc_timestamped_and_carries_no_secret():
    """UTC matches the repository's storage timezone; the name must not leak
    credentials or counterparty data (§12 naming, §10)."""
    backup = _script(BACKUP_SCRIPT)
    assert "date -u" in backup, "artifact naming must use UTC"
    assert "pricewatchph-" in backup
    assert ".dump" in backup
    for forbidden in ("$PGPASSWORD", "${PGPASSWORD", "$POSTGRES_PASSWORD", "seller"):
        assert forbidden not in backup.split("sha256sum")[0] or forbidden == "seller", (
            f"artifact naming must not include {forbidden}"
        )
    assert "seller" not in backup, "no counterparty concept belongs in the backup script"


def test_backup_does_not_print_dump_contents_or_row_values():
    """A successful run reports the artifact name, size and duration only."""
    backup = _script(BACKUP_SCRIPT)
    assert not re.search(r"pg_dump[^\n]*\|\s*(cat|head|tail|tee)", backup)
    assert "psql" not in backup, (
        "the backup path must not run ad-hoc queries whose output could echo row data"
    )


# --- destination abstraction (task file §7) --------------------------------


def test_backup_destination_is_a_configurable_bind_mount_not_container_only():
    """A dump that exists only inside an ephemeral container is not a backup;
    a named volume is not readily copyable off-host (§7.1, §7.2)."""
    volumes = _volume_strings(_service(BACKUP_SERVICE))
    destination = [v for v in volumes if v.rstrip(":ro").endswith(CONTAINER_BACKUP_DIR)]
    assert destination, f"the backup service must mount {CONTAINER_BACKUP_DIR}"
    source = destination[0].split(":")[0]
    assert source.startswith("./") or source.startswith("${") or source.startswith("/"), (
        f"{CONTAINER_BACKUP_DIR} must come from a host path, not a named volume: {source}"
    )
    named_volumes = set(_compose().get("volumes", {}) or {})
    assert source not in named_volumes, (
        "the backup destination must not be a named Docker volume (§7.2)"
    )
    assert "PRICEWATCHPH_BACKUP_DIR" in destination[0], (
        "the host destination must be configurable via PRICEWATCHPH_BACKUP_DIR"
    )


def test_no_backup_provider_or_vendor_is_invented():
    """docs/09_PLANNING.md §8.3 leaves the destination an open owner decision."""
    for name in (BACKUP_SCRIPT, RESTORE_SCRIPT):
        text = _script(name).lower()
        for vendor in ("s3", "aws", "backblaze", "b2", "gdrive", "dropbox", "rclone", "gsutil", "azure"):
            assert not re.search(rf"\b{re.escape(vendor)}\b", text), (
                f"{name} must not name a backup provider ({vendor}); that is an owner decision"
            )


def test_dump_artifacts_cannot_be_committed():
    """The default destination is inside the working tree, and Phase 9 requires
    confirmation that no dump is committed."""
    gitignore = (REPO_ROOT / ".gitignore").read_text()
    for pattern in ("*.dump", "backups"):
        assert pattern in gitignore, f".gitignore must cover {pattern}"


# --- retention (task file §8) ---------------------------------------------


def test_no_automatic_deletion_of_backup_artifacts_is_implemented():
    """Retention is an undecided owner decision, and a backup component is the
    worst place to debut an unproven rm against the only copies of the DB."""
    for name in (BACKUP_SCRIPT, RESTORE_SCRIPT):
        text = _script(name)
        assert "rm -rf" not in text, f"{name} must not contain `rm -rf`"
        assert not re.search(r"-delete\b", text), f"{name} must not contain `find -delete`"
        assert not re.search(rf"rm\s+[^\n]*{re.escape(CONTAINER_BACKUP_DIR)}", text), (
            f"{name} must not delete anything under {CONTAINER_BACKUP_DIR}"
        )


# --- restore isolation and the destructive boundary (task file §11) --------


def test_scratch_service_is_profile_gated_distinct_and_unpublished():
    scratch = _service(SCRATCH_SERVICE)
    compose = _compose()
    assert RESTORE_PROFILE in (scratch.get("profiles") or [])
    assert str(scratch.get("restart", "no")) == "no"
    assert not scratch.get("ports"), (
        "the restored copy must not be reachable from the host"
    )
    environment = scratch.get("environment") or {}
    assert environment.get("POSTGRES_DB") == "postgres", (
        "the container must bootstrap only postgres; the drill creates both fixed DBs"
    )
    assert environment.get("POSTGRES_DB") != compose["services"]["db"].get("environment", {}).get(
        "POSTGRES_DB"
    )
    assert "postgres_data" not in " ".join(_volume_strings(scratch)), (
        "the scratch target must never touch the application data volume"
    )
    named_volumes = set(compose.get("volumes", {}) or {})
    data_mounts = [
        volume
        for volume in _volume_strings(scratch)
        if volume.split(":", 1)[-1] == "/var/lib/postgresql/data"
    ]
    assert data_mounts == [f"{TASK_SCRATCH_VOLUME}:/var/lib/postgresql/data"]
    attached_named = [
        volume.split(":", 1)[0]
        for volume in _volume_strings(scratch)
        if volume.split(":", 1)[0] in named_volumes
    ]
    assert attached_named == [TASK_SCRATCH_VOLUME], (
        "restore_scratch must have exactly one Docker volume"
    )
    assert TASK_SCRATCH_VOLUME in named_volumes
    assert TASK_SCRATCH_VOLUME != "postgres_data"


def test_scratch_service_never_receives_production_credentials():
    """The restoring process cannot authenticate against db (§11.3 layer 2)."""
    scratch = _service(SCRATCH_SERVICE)
    assert "env_file" not in scratch
    keys = _env_keys(scratch)
    for forbidden in FORBIDDEN_SECRET_ENV:
        assert forbidden not in keys
    environment = scratch.get("environment") or {}
    rendered = " ".join(f"{k}={v}" for k, v in environment.items()) if isinstance(
        environment, dict
    ) else " ".join(environment)
    assert "${POSTGRES_PASSWORD" not in rendered, (
        "the scratch target must not be given the application database password"
    )


def test_scratch_password_is_optional_while_profile_is_inactive_but_generated_for_drill():
    """Profiles do not suppress interpolation. Ordinary Compose parsing must
    not require a restore-only secret; activation must supply a random one."""
    scratch = _service(SCRATCH_SERVICE)
    password = (scratch.get("environment") or {}).get("POSTGRES_PASSWORD", "")
    assert "PRICEWATCHPH_RESTORE_SCRATCH_PASSWORD" in str(password), password
    assert ":?" not in str(password), (
        "inactive profile services are still interpolated by Compose"
    )
    assert re.search(r"\$\{PRICEWATCHPH_RESTORE_SCRATCH_PASSWORD(?::-)?\}", str(password)), password
    assert "POSTGRES_HOST_AUTH_METHOD" not in _env_keys(scratch), (
        "trust auth would leave a full copy of production data unauthenticated"
    )
    restore = _script(RESTORE_SCRIPT)
    assert "PRICEWATCHPH_RESTORE_SCRATCH_PASSWORD" in restore
    assert re.search(r"/dev/urandom|openssl\s+rand", restore), (
        f"{RESTORE_SCRIPT} must generate an ephemeral scratch password per drill"
    )


def test_scratch_service_mounts_the_backup_directory_read_only():
    """Restore verification must not be able to mutate or delete an artifact."""
    volumes = _volume_strings(_service(SCRATCH_SERVICE))
    destination = [v for v in volumes if CONTAINER_BACKUP_DIR in v]
    assert destination, f"the scratch service must mount {CONTAINER_BACKUP_DIR}"
    assert destination[0].endswith(":ro"), destination[0]


def test_restore_target_is_fixed_and_not_expressible_as_an_argument():
    """Artifact hand-off is tested separately; no database target option is
    accepted or forwarded to pg_restore."""
    restore = _script(RESTORE_SCRIPT)
    assert re.search(r"\[\s*\"?\$#\"?\s+-eq\s+0\s*\]", restore), (
        "the mandatory drill must reject positional arguments"
    )
    assert not re.search(r"--(?:host|port|dbname|database|username|user)(?:=|\s)", restore)
    assert re.search(
        rf"pg_restore[^\n]*-d\s+(?:\"?\$?\{{?TARGET_DB\}}?\"?|{SCRATCH_DB_SENTINEL})",
        restore,
    ), "pg_restore must use the internally fixed target"


def test_restore_creates_exact_backup_and_uses_only_its_reported_pair():
    restore = _script(RESTORE_SCRIPT)
    runner_call = _backup_runner_call(restore)
    runner = _auditable_backup_runner(restore)
    assert f"/usr/local/bin/{BACKUP_SCRIPT}" in runner
    assert "BACKUP_ARTIFACT=" in restore
    assert ARTIFACT_PATTERN.replace("^", "").replace("$", "") in restore or (
        "[0-9]{8}T[0-9]{6}Z" in restore and "pricewatchph-" in restore
    )
    assert ".sha256" in restore
    assert re.search(r"grep\s+-c[^\n]*\^BACKUP_ARTIFACT=", restore), (
        "the drill must require exactly one structured backup success record"
    )
    for forbidden in ("ls -t", "ls -tr", "find ", "-mtime", "-newer", "latest"):
        assert forbidden not in restore.lower(), (
            f"artifact selection must not use {forbidden!r}"
        )
    artifact_handling = restore.find("BACKUP_RECORD_COUNT", runner_call.end())
    assert artifact_handling != -1, (
        "exact-record artifact handling must follow the captured runner output"
    )


def test_restore_rejects_every_incomplete_or_malformed_artifact_pair():
    restore = _script(RESTORE_SCRIPT)
    assert re.search(r"\[\s+-f\s+[^\]]*ARTIFACT", restore), (
        "the exact dump must be a regular file"
    )
    assert re.search(r"\[\s+-f\s+[^\]]*(?:CHECKSUM|sha256)", restore, re.IGNORECASE), (
        "the exact checksum sidecar must be a regular file"
    )
    assert ".partial" in restore, "partial artifacts must be explicitly rejected"
    assert "sha256sum -c" in restore
    assert "pg_restore --list" in restore
    assert "stat" in restore and "600" in restore, (
        "the drill must verify restrictive permissions on both final files"
    )


def test_restore_drill_uses_one_cluster_with_two_fixed_databases():
    restore = _script(RESTORE_SCRIPT)
    assert SOURCE_DB_SENTINEL in restore
    assert SCRATCH_DB_SENTINEL in restore
    assert restore.count("createdb") >= 2
    source_migration = re.search(
        rf"manage\.py\s+migrate[^\n]*{SOURCE_DB_SENTINEL}|"
        rf"{SOURCE_DB_SENTINEL}[^\n]*manage\.py\s+migrate",
        restore,
    )
    assert source_migration, "only the source scratch DB may be migrated"
    target_migration = re.search(
        rf"manage\.py\s+migrate[^\n]*{SCRATCH_DB_SENTINEL}|"
        rf"{SCRATCH_DB_SENTINEL}[^\n]*manage\.py\s+migrate",
        restore,
    )
    assert target_migration is None, "the restore target must never be migrated"
    backup_runner_call = _backup_runner_call(restore).start()
    source_database = restore.rfind('PGDATABASE="$SOURCE_DB"', 0, backup_runner_call)
    assert source_database != -1, (
        "the real drill backup runner must explicitly target source scratch"
    )


def test_restore_populates_and_snapshots_source_before_running_real_backup():
    restore = _script(RESTORE_SCRIPT)
    populate = re.search(r"(?:populate|fixture)[^\n]*" + SOURCE_DB_SENTINEL, restore, re.IGNORECASE)
    source_snapshot = re.search(
        r"PRICEWATCHPH_T037_SOURCE_SNAPSHOT_JSON=.*(?:snapshot|capture)",
        restore,
        re.IGNORECASE,
    )
    backup_run = _backup_runner_call(restore).start()
    assert populate, "deterministic fixtures must be populated in source scratch"
    assert source_snapshot, "the exact source snapshot must be captured before backup"
    assert populate.start() < source_snapshot.start() < backup_run


def test_restore_drill_uses_real_backup_script_in_exact_postgres_image():
    restore = _script(RESTORE_SCRIPT)
    runner = _auditable_backup_runner(restore)
    normalised, run, arguments = _backup_runner_command(runner)
    _, image, command = _parse_backup_runner_arguments(arguments)

    assert re.fullmatch(r"\$[A-Z][A-Z0-9_]*", image), (
        "the runner image must be an immutable identity derived from live metadata"
    )
    image_variable = image.removeprefix("$")
    image_assignments = [
        match
        for match in _command_substitution_assignments(normalised[: run.start()])
        if match.group("variable") == image_variable
    ]
    assert len(image_assignments) == 1
    image_lookup = re.sub(
        r"\s+", " ", image_assignments[0].group("command")
    ).strip()
    image_lookup_tokens = shlex.split(image_lookup, posix=True)
    assert image_lookup_tokens[:3] == ["docker", "inspect", "--format"]
    assert len(image_lookup_tokens) == 5
    assert re.sub(r"\s+", "", image_lookup_tokens[3]) == "{{.Image}}"
    assert image_lookup_tokens[4] == "$VERIFIED_DRILL_CONTAINER_ID"
    assert command == [f"/usr/local/bin/{BACKUP_SCRIPT}"], (
        "the immutable PostgreSQL image must execute the repository's real backup script"
    )


def test_restore_drill_backup_runner_receives_only_scratch_pg_environment():
    restore = _script(RESTORE_SCRIPT)
    runner = _auditable_backup_runner(restore)
    normalised, run, arguments = _backup_runner_command(runner)
    options, _, _ = _parse_backup_runner_arguments(arguments)
    expected_environment = [
        "PGHOST",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGPASSWORD",
    ]

    assert _option_values(options, "--env") == expected_environment
    expected_values = {
        "PGHOST": '"$SCRATCH_SERVICE"',
        "PGPORT": "5432",
        "PGDATABASE": '"$SOURCE_DB"',
        "PGUSER": '"$SCRATCH_USER"',
        "PGPASSWORD": '"$SCRATCH_PASSWORD"',
    }
    for variable, expected in expected_values.items():
        assert _last_simple_assignment_before(
            normalised, variable, run.start()
        ) == expected
    assert re.search(
        r"(?m)^\s*export\s+PGHOST\s+PGPORT\s+PGDATABASE\s+PGUSER\s+PGPASSWORD\s*$",
        normalised[: run.start()],
    )
    assert not any(value.startswith("PGPASSWORD=") for value in arguments), (
        "the scratch password must be inherited as environment, never embedded in argv"
    )


def test_restore_drill_backup_runner_is_direct_disposable_and_network_isolated():
    restore = _script(RESTORE_SCRIPT)
    runner = _auditable_backup_runner(restore)
    _, _, arguments = _backup_runner_command(runner)
    options, _, _ = _parse_backup_runner_arguments(arguments)
    normalised_restore = _normalise_shell(restore)

    assert _option_values(options, "--rm") == [None]
    assert _option_values(options, "--network") == ["$VERIFIED_DRILL_NETWORK_ID"]
    for forbidden_identity in (
        "COMPOSE_PROJECT_NAME",
        "COMPOSE_FILE",
        "COMPOSE_PROFILES",
        "DRILL_PROJECT",
        "com.docker.compose",
    ):
        assert forbidden_identity not in runner
    assert "postgres_data" not in runner
    assert TASK_SCRATCH_VOLUME not in runner
    assert not re.search(
        r"\b(?:docker\s+compose|compose_(?:drill|active))\b[^\n]*\brun\b",
        normalised_restore,
    ), "the mandatory drill must never invoke any Compose one-off service runner"
    assert not re.search(
        r"\bdocker\s+(?:create|container|network|system|compose|exec|rm)\b",
        runner,
    )
    assert not re.search(r"\bdocker\s+image\s+(?!inspect\b)", runner)
    assert not re.search(r"\bdocker\s+volume\s+(?!ls\b)", runner)


def test_restore_drill_backup_runner_mounts_writable_destination_only():
    restore = _script(RESTORE_SCRIPT)
    runner = _auditable_backup_runner(restore)
    _, _, arguments = _backup_runner_command(runner)
    options, _, _ = _parse_backup_runner_arguments(arguments)
    mounts = [_mount_fields(spec) for spec in _option_values(options, "--mount")]
    script_mount = {
        "type": "bind",
        "src": f"$SCRIPT_DIR/{BACKUP_SCRIPT}",
        "dst": f"/usr/local/bin/{BACKUP_SCRIPT}",
        "readonly": True,
    }
    destination_mount = {
        "type": "bind",
        "src": "$BACKUP_DIR",
        "dst": CONTAINER_BACKUP_DIR,
    }
    assert mounts.count(script_mount) == 1
    assert mounts.count(destination_mount) == 1

    data_path = "/var/lib/postgresql/data"
    tmpfs_masks = _option_values(options, "--tmpfs")
    mount_masks = [mount for mount in mounts if mount.get("dst") == data_path]
    assert len(tmpfs_masks) + len(mount_masks) == 1, (
        "every image-declared data path must be masked without a Docker volume"
    )
    if tmpfs_masks:
        assert tmpfs_masks == [data_path]
    else:
        mask = mount_masks[0]
        assert mask.get("type") in {"tmpfs", "bind"}
        if mask["type"] == "bind":
            assert mask.get("src")
            assert mask.get("readonly") is True
    assert len(mounts) == 2 + len(mount_masks), (
        "the direct runner may mount only the real script, backup destination, "
        "and an explicit non-volume data-path mask"
    )


def test_restore_drill_backup_runner_accounts_for_image_declared_volumes():
    restore = _script(RESTORE_SCRIPT)
    runner = _auditable_backup_runner(restore)
    normalised, run, arguments = _backup_runner_command(runner)
    _, image, _ = _parse_backup_runner_arguments(arguments)
    image_variable = image.removeprefix("$")

    declared_volume_assignments = [
        match
        for match in _command_substitution_assignments(normalised[: run.start()])
        if "docker image inspect" in re.sub(
            r"\s+", " ", match.group("command")
        )
        and (
            "Config.Volumes" in match.group("command")
            or 'index .Config "Volumes"' in match.group("command")
        )
        and f'"${image_variable}"' in match.group("command")
    ]
    assert len(declared_volume_assignments) == 1
    declared_variable = declared_volume_assignments[0].group("variable")
    declared_lookup = re.sub(
        r"\s+", " ", declared_volume_assignments[0].group("command")
    ).strip()
    declared_lookup_tokens = shlex.split(declared_lookup, posix=True)
    assert declared_lookup_tokens[:4] == ["docker", "image", "inspect", "--format"]
    assert len(declared_lookup_tokens) == 6
    assert "Volumes" in declared_lookup_tokens[4]
    assert declared_lookup_tokens[5] == f"${image_variable}"
    assert re.search(
        rf'\[\s*"\$\({re.escape("nonempty_line_count")}\s+'
        rf'"\${re.escape(declared_variable)}"\)"\s+-eq\s+1\s*\]'
        r"\s*\|\|\s*return\s+1",
        normalised[: run.start()],
    )
    assert re.search(
        rf'\[\s*"\${re.escape(declared_variable)}"\s*=\s*'
        r'"/var/lib/postgresql/data"\s*\]\s*\|\|\s*return\s+1',
        normalised[: run.start()],
    )

    inventories = _persistent_volume_inventory_assignments(normalised)
    assert len(inventories) == 2, (
        "the runner must capture exact sorted persistent-volume inventories "
        "immediately before and after Docker execution"
    )
    before, after = inventories
    assert before.end() < run.start() < run.end() < after.start()
    before_variable = before.group("variable")
    after_variable = after.group("variable")
    comparison = re.search(
        rf'(?ms)^\s*if\s+\[\s*"\${re.escape(before_variable)}"\s*!=\s*'
        rf'"\${re.escape(after_variable)}"\s*\]\s*;\s*then\s*$'
        r'(?P<failure>.*?)^\s*fi\s*$',
        normalised[after.end() :],
    )
    assert comparison, "a changed persistent-volume inventory must fail closed"
    failure = comparison.group("failure")
    assert re.search(r"\breturn\s+1\b", failure)
    assert "persistent" in failure.lower() and "volume" in failure.lower()
    assert not re.search(r"docker\s+volume\s+(?:rm|prune)\b", runner)


def test_restore_drill_backup_runner_is_surrounded_by_exact_ownership_proof():
    restore = _script(RESTORE_SCRIPT)
    runner = _auditable_backup_runner(restore)
    normalised, run, _ = _backup_runner_command(runner)
    guards = list(
        re.finditer(
            r"(?ms)^\s*if\s+!\s+prove_drill_resource_ownership\s*;\s*then\s*$"
            r"(?P<failure>.*?)^\s*fi\s*$",
            normalised,
        )
    )
    assert len(guards) == 2
    before, after = guards
    assert before.end() <= run.start() < run.end() <= after.start()
    assert normalised[before.end() : run.start()].strip() == "", (
        "ownership proof must be immediately before the direct Docker runner"
    )
    status_branch = normalised[run.end() : after.start()]
    assert re.fullmatch(
        r"\s*RUNNER_STATUS=0\s*else\s*RUNNER_STATUS=\$\?\s*fi\s*",
        status_branch,
    ), "post-run ownership proof must execute after success or failure"
    for guard in guards:
        failure = guard.group("failure")
        assert re.search(r"\breturn\s+1\b", failure)
        assert "ownership" in failure.lower()

    inventories = _persistent_volume_inventory_assignments(normalised)
    assert len(inventories) == 2
    assert inventories[0].end() <= before.start()
    assert after.end() <= inventories[1].start()
    assert re.search(
        r'\[\s*"\$RUNNER_STATUS"\s+-eq\s+0\s*\]\s*'
        r'\|\|\s*return\s+"\$RUNNER_STATUS"',
        normalised[inventories[1].end() :],
    )


def test_restore_drill_snapshots_active_database_before_and_after_and_cleans_only_itself():
    restore = _script(RESTORE_SCRIPT)
    for marker in (
        "PRICEWATCHPH_T037_ACTIVE_BEFORE_JSON",
        "PRICEWATCHPH_T037_ACTIVE_AFTER_JSON",
        "PRICEWATCHPH_T037_SOURCE_SNAPSHOT_JSON",
    ):
        assert marker in restore
    before_capture = re.search(
        r"PRICEWATCHPH_T037_ACTIVE_BEFORE_JSON=.*(?:active_snapshot|capture_active)",
        restore,
        re.IGNORECASE,
    )
    after_capture = re.search(
        r"PRICEWATCHPH_T037_ACTIVE_AFTER_JSON=.*(?:active_snapshot|capture_active)",
        restore,
        re.IGNORECASE,
    )
    restore_run = re.search(r"pg_restore[^\n]*--exit-on-error", restore)
    verify_run = re.search(r"pytest[^\n]*test_task_037_backup_and_verified_restore\.py", restore)
    assert before_capture and after_capture and restore_run and verify_run
    assert before_capture.start() < restore_run.start() < after_capture.start() < verify_run.start()
    assert re.search(r"trap\s+[^\n]*(?:EXIT|0)", restore), (
        "scratch cleanup must run on success and failure"
    )
    assert re.search(r"(?:--project-name|-p)\s+[^\n]*(?:task037|drill)", restore, re.IGNORECASE), (
        "scratch resources must use a dedicated Compose project"
    )


def test_cleanup_is_armed_only_after_successful_startup_and_complete_ownership_proof():
    restore = _script(RESTORE_SCRIPT)
    unarmed = restore.index("DRILL_RESOURCES_ESTABLISHED=0")
    startup = re.search(r"compose_drill[^\n]*\bup\b", restore)
    assert startup, "the drill must start only its dedicated scratch service"
    after_startup = restore[startup.end() :]
    proof = after_startup.index("prove_drill_resource_ownership")
    armed = after_startup.index("DRILL_RESOURCES_ESTABLISHED=1")
    assert unarmed < startup.start()
    assert proof < armed, "cleanup may be armed only after ownership proof succeeds"


def test_ownership_proof_clears_stale_values_and_proves_exact_labeled_resources():
    restore = _script(RESTORE_SCRIPT)
    proof = _shell_function_body(restore, "prove_drill_resource_ownership")
    identity = _shell_function_body(restore, "strict_drill_project_identity")
    verified = (
        "VERIFIED_DRILL_CONTAINER_ID",
        "VERIFIED_DRILL_NETWORK_ID",
        "VERIFIED_DRILL_VOLUME_NAME",
    )
    for variable in verified:
        clear = proof.index(f'{variable}=""')
        populate = proof.rindex(f"{variable}=")
        assert clear < proof.index("strict_drill_project_identity") < populate

    assert "task037-drill-" in identity and "ACTIVE_PROJECT" in identity
    assert "docker ps --all --quiet --no-trunc" in proof
    assert "docker network ls --quiet --no-trunc" in proof
    assert re.search(r"compose_drill\s+ps\s+--all\s+--quiet", proof)
    for collection in (
        "PROJECT_CONTAINER_IDS",
        "ATTACHED_NETWORK_IDS",
        "ATTACHED_VOLUME_NAMES",
    ):
        assert re.search(
            rf'nonempty_line_count\s+"\${collection}"\)[^\n]*-eq\s+1', proof
        ), f"{collection} must have exact cardinality one"
    for left, right in (
        ("PROJECT_CONTAINER_IDS", "RESOLVED_CONTAINER_IDS"),
        ("ATTACHED_NETWORK_IDS", "PROJECT_NETWORK_IDS"),
        ("ATTACHED_VOLUME_NAMES", "PROJECT_VOLUME_NAMES"),
    ):
        assert f'"${left}" = "${right}"' in proof
    for label in (
        "com.docker.compose.project",
        "com.docker.compose.service",
        "com.docker.compose.network",
        "com.docker.compose.volume",
    ):
        assert label in proof
    assert '"default"' in proof
    assert TASK_SCRATCH_VOLUME in proof
    final_label_check = proof.rindex("com.docker.compose.volume")
    for variable in verified:
        assert final_label_check < proof.rindex(f"{variable}="), (
            "destructive identifiers may be populated only after all proof checks"
        )


def test_cleanup_reproves_then_deletes_only_exact_verified_identifiers_and_fails_closed():
    restore = _script(RESTORE_SCRIPT)
    cleanup = _shell_function_body(restore, "cleanup")
    removal = _shell_function_body(restore, "remove_verified_drill_resources")

    proof_if = cleanup.index("if ! prove_drill_resource_ownership")
    proof_else = cleanup.index("else", proof_if)
    remove_call = cleanup.index("remove_verified_drill_resources")
    assert proof_if < proof_else < remove_call
    assert "remove_verified_drill_resources" not in cleanup[proof_if:proof_else]
    assert "destructive cleanup skipped" in cleanup[proof_if:proof_else]
    assert "STATUS=1" in cleanup[proof_if:proof_else]

    exact_commands = {
        'docker rm --force "$VERIFIED_DRILL_CONTAINER_ID" || return 1',
        'docker network rm "$VERIFIED_DRILL_NETWORK_ID" || return 1',
        'docker volume rm "$VERIFIED_DRILL_VOLUME_NAME" || return 1',
    }
    destructive_lines = [
        line.strip()
        for line in restore.splitlines()
        if re.match(r"\s*docker\s+(?:rm|network\s+rm|volume\s+rm)\b", line)
    ]
    assert len(destructive_lines) == 3
    assert set(destructive_lines) == exact_commands
    for command in exact_commands:
        assert command in removal
    assert restore.count("remove_verified_drill_resources") == 2, (
        "the exact-resource remover may be defined once and called only by cleanup"
    )
    assert "no broader cleanup attempted" in cleanup


def test_cleanup_has_no_compose_wide_guessed_or_broad_destructive_fallback():
    restore = _script(RESTORE_SCRIPT)
    assert "down -v" not in restore
    assert not re.search(r"docker\s+compose[^\n]*\bdown\b", restore)
    assert not re.search(r"\bcompose_(?:drill|active)\b[^\n]*\bdown\b", restore)
    assert not re.search(r"docker\s+(?:system|container|network|volume)\s+prune\b", restore)

    for line in restore.splitlines():
        if re.match(r"\s*docker\s+(?:rm|network\s+rm|volume\s+rm)\b", line):
            assert "label=" not in line, "label-filtered deletion is forbidden"
            assert "DRILL_PROJECT" not in line
            assert "SCRATCH_SERVICE" not in line
            assert TASK_SCRATCH_VOLUME not in line, (
                "destructive targets must be verified values, not guessed names"
            )


def test_restore_script_guards_the_scratch_sentinel_and_refuses_the_app_database():
    restore = _script(RESTORE_SCRIPT)
    assert SCRATCH_DB_SENTINEL in restore
    assert "POSTGRES_DB" in restore and "POSTGRES_HOST" in restore, (
        f"{RESTORE_SCRIPT} must compare its target against the configured "
        "application database and abort on a match (§11.3 layer 3)"
    )


def test_restore_verifies_checksum_and_structure_before_restoring():
    """Integrity is checked before any destructive scratch action (§11.1)."""
    restore = _script(RESTORE_SCRIPT)
    assert "sha256sum" in restore
    assert "-c" in restore
    assert "pg_restore" in restore
    assert restore.index("sha256sum") < restore.index("pg_restore"), (
        "the checksum must be verified before pg_restore runs"
    )
    assert "pg_restore --list" in restore, "structural validation must precede the restore"
    assert re.search(r"(?:wc\s+-l|grep\s+-c|awk)[^\n]*(?:sha256|CHECKSUM)", restore, re.IGNORECASE), (
        "the sidecar must be constrained to exactly one entry"
    )
    assert re.search(r"basename|ARTIFACT", restore), (
        "the sidecar entry must name the exact captured artifact basename"
    )


def test_restore_uses_correct_postgres_16_flags_and_no_destructive_ones():
    restore = _script(RESTORE_SCRIPT)
    for required in ("--no-owner", "--no-privileges", "--exit-on-error"):
        assert required in restore, f"{RESTORE_SCRIPT} must pass {required}"
    for forbidden in ("--clean", "--data-only", "--create", "--disable-triggers"):
        assert forbidden not in restore, (
            f"{RESTORE_SCRIPT} must not use {forbidden}: --clean/--create would act on "
            "the wrong database, and --data-only would hit the armed AlertDelivery "
            "guard (§3.2)"
        )
    assert "psql -f" not in restore, "a custom-format dump is restored with pg_restore"


def test_restore_migrates_only_source_and_never_target_to_mask_an_incomplete_backup():
    """The isolated source needs schema before fixtures. The restored target
    must receive schema only from pg_restore."""
    restore = _script(RESTORE_SCRIPT)
    migrations = [
        line for line in restore.splitlines()
        if re.search(r"manage\.py\s+migrate(?!\s+--check)", line)
    ]
    assert migrations, "the disposable source scratch DB must be migrated"
    assert all(SOURCE_DB_SENTINEL in line for line in migrations), (
        "every applying migrate must explicitly target source scratch"
    )
    assert all(SCRATCH_DB_SENTINEL not in line for line in migrations)


def test_no_secret_literal_is_committed_in_either_script():
    for name in (BACKUP_SCRIPT, RESTORE_SCRIPT):
        text = _script(name)
        assert not re.search(r"PGPASSWORD\s*=\s*['\"]?[A-Za-z0-9]{6,}", text), (
            f"{name} must not contain a password literal"
        )
        assert "change_me" not in text


# --- environment contract (task file §6.3) --------------------------------


def test_env_example_is_unchanged_and_compose_only_variables_stay_out_of_it():
    """TASK_001's frozen symmetry test asserts both directions, so a
    Compose-interpolation variable added to .env.example would break it."""
    env_example = (REPO_ROOT / ".env.example").read_text()
    compose_only_variables = (
        "PRICEWATCHPH_BACKUP_DIR",
        "PRICEWATCHPH_RESTORE_SCRATCH_PASSWORD",
        "PRICEWATCHPH_APP_ENV_FILE",
    )
    compose_source = (REPO_ROOT / "docker-compose.yml").read_text()
    for compose_only in compose_only_variables:
        assert compose_only in compose_source
        assert compose_only not in env_example, (
            f"{compose_only} is read by Compose, never by config/settings.py; adding it "
            "to .env.example breaks TASK_001's bidirectional symmetry test"
        )
    settings_source = (REPO_ROOT / "config" / "settings.py").read_text()
    for compose_only in compose_only_variables:
        assert compose_only not in settings_source


def test_task_037_introduces_no_model_or_migration_change():
    result = subprocess.run(
        [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_services_preserve_task_037_with_successor_contracts():
    """Successors supersede only database-env and ingress-topology ownership."""
    compose = _compose()
    expected_env_file = ["${PRICEWATCHPH_APP_ENV_FILE:-.env}"]
    for service_name in ("migrate", "web"):
        assert compose["services"][service_name]["env_file"] == expected_env_file

    db = compose["services"]["db"]
    assert set(db) == {"image", "environment", "volumes", "healthcheck", "restart"}
    assert db["image"].startswith("postgres:16")
    assert db["environment"] == {
        "POSTGRES_DB": "${POSTGRES_DB:-}",
        "POSTGRES_USER": "${POSTGRES_USER:-}",
        "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD:-}",
    }
    assert db["volumes"] == ["postgres_data:/var/lib/postgresql/data"]
    assert db["restart"] == "unless-stopped"

    migrate = compose["services"]["migrate"]
    assert set(migrate) == {"build", "env_file", "depends_on", "restart", "command"}
    assert migrate["build"] == "."
    assert migrate["depends_on"] == {"db": {"condition": "service_healthy"}}
    assert migrate["restart"] == "no"
    assert migrate["command"] == "python manage.py migrate --noinput"

    web = compose["services"]["web"]
    assert web["build"] == "."
    assert web["depends_on"] == {
        "db": {"condition": "service_healthy"},
        "migrate": {"condition": "service_completed_successfully"},
    }
    assert web["restart"] == "unless-stopped"


# --- the SELLER_PSEUDONYM_KEY contract (task file §9) ---------------------


def test_the_pseudonym_key_is_absent_from_every_backup_and_restore_path():
    """The key must not be in the dump, in an artifact, or beside the dump."""
    for name in (BACKUP_SCRIPT, RESTORE_SCRIPT):
        text = _script(name)
        assert "SELLER_PSEUDONYM" not in text, (
            f"{name} must never reference the pseudonym key"
        )


def test_the_pseudonym_key_is_stored_in_no_model_field_so_no_dump_can_contain_it():
    """The structural reason the key is categorically absent from pg_dump
    output: nothing persists it (§3.8, §9.1)."""
    from django.apps import apps

    for model in apps.get_models():
        for field in model._meta.get_fields():
            assert "pseudonym_key" not in getattr(field, "name", "").lower()
    settings_source = (REPO_ROOT / "config" / "settings.py").read_text()
    assert "DJANGO_SELLER_PSEUDONYM_KEY" in settings_source, (
        "the key must remain environment-only"
    )


def test_pseudonymisation_is_one_way_and_offers_no_reversal_api():
    """TASK_037 must not claim reversibility anywhere: HMAC-SHA256 is one-way,
    and no depseudonymise/decrypt entry point exists to pretend otherwise."""
    import ingestion.pseudonymise as module

    source = Path(module.__file__).read_text()
    assert "hmac" in source and "sha256" in source
    for forbidden in ("def depseudonymise", "def unpseudonymise", "def decrypt", "def reverse"):
        assert forbidden not in source
    assert not hasattr(module, "depseudonymise")


def test_pseudonym_continuity_recomputation_is_sound_and_key_sensitive():
    """The honest verification method (§9.2), proven in pure Python: the
    original key reproduces a stored token, and a wrong key does not. This is
    what makes the drill's continuity check meaningful rather than vacuous."""
    from django.test import override_settings

    from ingestion.pseudonymise import pseudonymise

    sentinel = "task037-continuity-sentinel-not-a-real-counterparty"
    original_key = "task037-original-synthetic-key"
    wrong_key = "task037-wrong-synthetic-key"

    with override_settings(SELLER_PSEUDONYM_KEY=original_key):
        token = pseudonymise(sentinel)

    expected = hmac.new(
        original_key.encode("utf-8"), sentinel.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert token == expected, "continuity must be recomputable as plain HMAC-SHA256"

    with override_settings(SELLER_PSEUDONYM_KEY=original_key):
        assert pseudonymise(sentinel) == token, "the same key must be deterministic"
    with override_settings(SELLER_PSEUDONYM_KEY=wrong_key):
        assert pseudonymise(sentinel) != token, (
            "a wrong key must not reproduce the token, or the check proves nothing"
        )

    assert sentinel not in token, "the token must not leak its input"
    assert len(token) == 64


# ===========================================================================
# B. Integration restore drill — real restored data only, never mocked
# ===========================================================================

_SCRATCH_ENV = (
    "PRICEWATCHPH_T037_SCRATCH_HOST",
    "PRICEWATCHPH_T037_SCRATCH_PORT",
    "PRICEWATCHPH_T037_SCRATCH_DB",
    "PRICEWATCHPH_T037_SCRATCH_USER",
    "PRICEWATCHPH_T037_SCRATCH_PASSWORD",
)

SOURCE_SNAPSHOT_ENV = "PRICEWATCHPH_T037_SOURCE_SNAPSHOT_JSON"
ACTIVE_BEFORE_ENV = "PRICEWATCHPH_T037_ACTIVE_BEFORE_JSON"
ACTIVE_AFTER_ENV = "PRICEWATCHPH_T037_ACTIVE_AFTER_JSON"

drill = pytest.mark.skipif(
    not all(os.environ.get(name) for name in _SCRATCH_ENV),
    reason=(
        "restore drill not enabled; pg_restore_verify.sh sets "
        "PRICEWATCHPH_T037_SCRATCH_* against a genuinely restored scratch database"
    ),
)


@pytest.fixture
def scratch_connection():
    """A read-mostly connection to the RESTORED scratch database.

    Refuses outright unless the target is the scratch sentinel, so this module
    can never be pointed at the live application database.
    """
    import psycopg

    target_db = os.environ["PRICEWATCHPH_T037_SCRATCH_DB"]
    if target_db != SCRATCH_DB_SENTINEL:
        pytest.fail(
            f"refusing to run the drill against {target_db!r}: the target must be "
            f"the scratch sentinel {SCRATCH_DB_SENTINEL!r}"
        )
    conn = psycopg.connect(
        host=os.environ["PRICEWATCHPH_T037_SCRATCH_HOST"],
        port=os.environ["PRICEWATCHPH_T037_SCRATCH_PORT"],
        dbname=target_db,
        user=os.environ["PRICEWATCHPH_T037_SCRATCH_USER"],
        password=os.environ["PRICEWATCHPH_T037_SCRATCH_PASSWORD"],
    )
    try:
        yield conn
    finally:
        conn.close()


def _json_env(name):
    raw = os.environ.get(name)
    if not raw:
        pytest.fail(f"{name} must contain a non-empty canonical JSON snapshot")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        pytest.fail(f"{name} is not valid JSON: {exc}")
    if not isinstance(value, dict) or not value:
        pytest.fail(f"{name} must decode to a non-empty object")
    return value


def _source_snapshot():
    """Exact facts captured from source scratch before pg_backup runs."""
    snapshot = _json_env(SOURCE_SNAPSHOT_ENV)
    required = {
        "row_counts",
        "migration_state",
        "migration_heads",
        "money_fixture",
        "raw_listings",
        "payload_fixtures",
        "price_point",
        "deal_flag",
        "outcome",
        "alert_delivery",
        "personal_record",
        "swap",
        "seller_tokens",
        "constraint_fixtures",
        "continuity",
    }
    missing = required - snapshot.keys()
    if missing:
        pytest.fail(f"source snapshot is missing sections: {sorted(missing)}")
    if set(snapshot["row_counts"]) != REPRESENTATIVE_TABLES:
        pytest.fail("source snapshot must contain exactly the §12 representative tables")
    if not snapshot["migration_state"] or not snapshot["migration_heads"]:
        pytest.fail("source migration state and per-app heads must both be non-empty")
    if len(snapshot["raw_listings"]) < 2:
        pytest.fail("source snapshot must contain deterministic NULL and {} RawListings")
    if not snapshot["seller_tokens"]:
        pytest.fail("source snapshot must contain exact fixture seller tokens")
    return snapshot


def _canonical(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    return value


def _fetch_record(cursor, table, row_id, fields):
    columns = ", ".join(fields)
    cursor.execute(f"SELECT {columns} FROM {table} WHERE id = %s;", (row_id,))
    row = cursor.fetchone()
    if row is None:
        pytest.fail(f"source-selected {table} id={row_id} did not survive restore")
    return {field: _canonical(value) for field, value in zip(fields, row, strict=True)}


def _assert_named_constraint(connection, expected_name, sql, params=()):
    import psycopg

    with pytest.raises(psycopg.IntegrityError) as exc_info:
        with connection.transaction(force_rollback=True):
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
    assert exc_info.value.diag.constraint_name == expected_name


@drill
def test_drill_restored_database_is_postgresql_16(scratch_connection):
    with scratch_connection.cursor() as cursor:
        cursor.execute("SHOW server_version;")
        assert cursor.fetchone()[0].startswith("16")


@drill
def test_drill_all_expected_tables_are_present(scratch_connection):
    with scratch_connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public';"
        )
        tables = {row[0] for row in cursor.fetchall()}
    missing = EXPECTED_TABLES - tables
    assert not missing, f"restored database is missing tables: {sorted(missing)}"


@drill
def test_drill_migrate_check_is_clean_against_unmigrated_restore_target():
    assert os.environ.get("POSTGRES_DB") == SCRATCH_DB_SENTINEL, (
        "the drill's Django process must be pointed at the fixed restore target"
    )
    result = subprocess.run(
        [sys.executable, "manage.py", "migrate", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@drill
def test_drill_full_migration_state_and_per_app_heads_match_source(scratch_connection):
    snapshot = _source_snapshot()
    with scratch_connection.cursor() as cursor:
        cursor.execute("SELECT app, name FROM django_migrations ORDER BY app, name;")
        state = [[app, name] for app, name in cursor.fetchall()]
        cursor.execute(
            "SELECT app, max(name) FROM django_migrations GROUP BY app ORDER BY app;"
        )
        heads = {app: name for app, name in cursor.fetchall()}
    assert state, "django_migrations must survive the restore"
    assert state == snapshot["migration_state"]
    assert heads == snapshot["migration_heads"]


@drill
def test_drill_all_four_triggers_survive_the_restore(scratch_connection):
    """Triggers are created in pg_dump's post-data section (§3.2); their
    presence in the restored database is the property that matters."""
    with scratch_connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname, t.tgname FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid WHERE NOT t.tgisinternal;"
        )
        found = {(row[0], row[1]) for row in cursor.fetchall()}
    missing = EXPECTED_TRIGGERS - found
    assert not missing, f"restored database lost triggers: {sorted(missing)}"


@drill
@pytest.mark.parametrize(
    ("table", "snapshot_key"),
    [
        ("ingestion_rawlisting", "rawlisting_id"),
        ("pricing_pricepoint", "pricepoint_id"),
        ("pricing_dealflag", "dealflag_id"),
    ],
)
def test_drill_immutability_triggers_are_armed_not_merely_present(
    scratch_connection, table, snapshot_key
):
    """A present-but-disabled trigger would be a silent regression, so the
    guard is exercised. Rolled back, so the restored copy is unchanged."""
    import psycopg

    row_id = _source_snapshot()["constraint_fixtures"][snapshot_key]
    with pytest.raises(psycopg.errors.RaiseException):
        with scratch_connection.transaction(force_rollback=True):
            with scratch_connection.cursor() as cursor:
                cursor.execute(f"UPDATE {table} SET id = id WHERE id = %s;", (row_id,))


@drill
def test_drill_alertdelivery_guard_is_armed_for_delete_and_terminal_insert(scratch_connection):
    """The hard case §3.2 exists for: a `sent` row must be restorable even
    though the armed guard rejects inserting one directly."""
    import psycopg

    snapshot = _source_snapshot()
    alert_id = snapshot["alert_delivery"]["id"]
    unclaimed_dealflag_id = snapshot["constraint_fixtures"]["unclaimed_dealflag_id"]
    assert snapshot["alert_delivery"]["status"] == "sent"
    with pytest.raises(psycopg.errors.RaiseException):
        with scratch_connection.transaction(force_rollback=True):
            with scratch_connection.cursor() as cursor:
                cursor.execute("DELETE FROM alerts_alertdelivery WHERE id = %s;", (alert_id,))
    with pytest.raises(psycopg.errors.RaiseException):
        with scratch_connection.transaction(force_rollback=True):
            with scratch_connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO alerts_alertdelivery "
                    "(deal_flag_id, status, claimed_at, terminal_at, failure_detail) "
                    "VALUES (%s, 'sent', now(), now(), NULL);",
                    (unclaimed_dealflag_id,),
                )


@drill
def test_drill_all_three_named_constraints_reject_violations(scratch_connection):
    fixtures = _source_snapshot()["constraint_fixtures"]
    rawlisting_id = fixtures["rawlisting_id"]
    _assert_named_constraint(
        scratch_connection,
        "rawlisting_source_external_id_fetched_at_unique",
        "INSERT INTO ingestion_rawlisting "
        "(source_id, raw_title, raw_price_text, raw_price, url, seller, fetched_at, "
        "occurred_at, external_id, payload) "
        "SELECT source_id, raw_title, raw_price_text, raw_price, url, seller, fetched_at, "
        "occurred_at, external_id, payload FROM ingestion_rawlisting WHERE id = %s;",
        (rawlisting_id,),
    )
    _assert_named_constraint(
        scratch_connection,
        "rawlisting_raw_price_non_negative",
        "INSERT INTO ingestion_rawlisting "
        "(source_id, raw_title, raw_price_text, raw_price, url, seller, fetched_at, "
        "occurred_at, external_id, payload) "
        "SELECT source_id, raw_title, raw_price_text, -0.01, url, seller, fetched_at, "
        "occurred_at, external_id || '-negative', payload "
        "FROM ingestion_rawlisting WHERE id = %s;",
        (rawlisting_id,),
    )
    assert fixtures["alternate_pricepoint_id"] != _source_snapshot()["deal_flag"][
        "baseline_pricepoint_id"
    ]
    _assert_named_constraint(
        scratch_connection,
        "dealflag_listing_unique",
        "INSERT INTO pricing_dealflag "
        "(listing_id, score, baseline_pricepoint_id, reason, flagged_at) "
        "SELECT listing_id, score, %s, reason, flagged_at "
        "FROM pricing_dealflag WHERE id = %s;",
        (fixtures["alternate_pricepoint_id"], fixtures["dealflag_id"]),
    )


@drill
def test_drill_representative_row_counts_match_the_source_snapshot(scratch_connection):
    counts = _source_snapshot()["row_counts"]
    assert set(counts) == REPRESENTATIVE_TABLES
    with scratch_connection.cursor() as cursor:
        for table, expected in sorted(counts.items()):
            cursor.execute(f"SELECT count(*) FROM {table};")
            assert cursor.fetchone()[0] == expected, (
                f"{table}: restored count differs from the dump-time source count"
            )


@drill
def test_drill_money_type_scale_and_exact_value_match_source(scratch_connection):
    """CLAUDE.md forbids float for money; numeric(12,2) must survive."""
    with scratch_connection.cursor() as cursor:
        cursor.execute(
            "SELECT numeric_precision, numeric_scale FROM information_schema.columns "
            "WHERE table_name = 'ingestion_rawlisting' AND column_name = 'raw_price';"
        )
        assert cursor.fetchone() == (12, 2)
        money = _source_snapshot()["money_fixture"]
        cursor.execute("SELECT raw_price FROM ingestion_rawlisting WHERE id = %s;", (money["id"],))
        value = cursor.fetchone()[0]
        assert isinstance(value, Decimal), type(value)
        assert value == Decimal(money["raw_price"])


@drill
def test_drill_every_named_rawlisting_matches_all_eight_source_fields(scratch_connection):
    fields = (
        "raw_title",
        "raw_price_text",
        "raw_price",
        "url",
        "fetched_at",
        "occurred_at",
        "external_id",
        "payload",
    )
    for expected in _source_snapshot()["raw_listings"]:
        assert set(expected) == {"id", *fields}
        with scratch_connection.cursor() as cursor:
            restored = _fetch_record(cursor, "ingestion_rawlisting", expected["id"], fields)
        assert restored == {field: expected[field] for field in fields}


@drill
def test_drill_rawlisting_payload_null_and_empty_remain_distinguishable(
    scratch_connection,
):
    """NULL and {} are different facts (ingestion/models.py); a restore that
    conflated them would lose information."""
    snapshot = _source_snapshot()
    fixtures = snapshot["payload_fixtures"]
    expected_by_id = {row["id"]: row["payload"] for row in snapshot["raw_listings"]}
    null_id = fixtures["null_rawlisting_id"]
    empty_id = fixtures["empty_rawlisting_id"]
    assert null_id != empty_id
    assert expected_by_id[null_id] is None
    assert expected_by_id[empty_id] == {}
    with scratch_connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, payload FROM ingestion_rawlisting WHERE id IN (%s, %s) ORDER BY id;",
            (null_id, empty_id),
        )
        restored = dict(cursor.fetchall())
    assert set(restored) == {null_id, empty_id}
    assert restored[null_id] is None
    assert restored[empty_id] == {}


@drill
def test_drill_listing_relationships_have_no_orphans(scratch_connection):
    with scratch_connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM listings_listing l "
            "LEFT JOIN ingestion_rawlisting r ON r.id = l.raw_listing_id "
            "WHERE r.id IS NULL;"
        )
        assert cursor.fetchone()[0] == 0, "Listing -> RawListing must not be orphaned"
        cursor.execute(
            "SELECT count(*) FROM listings_listing l "
            "LEFT JOIN catalogue_sku s ON s.id = l.sku_id "
            "WHERE l.sku_id IS NOT NULL AND s.id IS NULL;"
        )
        assert cursor.fetchone()[0] == 0, "Listing -> Sku must not be orphaned"


@drill
@pytest.mark.parametrize(
    ("snapshot_key", "table", "fields"),
    [
        (
            "price_point",
            "pricing_pricepoint",
            (
                "sku_id", "condition", "day", "median", "p25", "p75",
                "n_listings", "mad", "window_start_day", "window_end_day",
                "calculated_at", "calculation_contract_version",
            ),
        ),
        (
            "deal_flag",
            "pricing_dealflag",
            ("listing_id", "score", "baseline_pricepoint_id", "reason", "flagged_at"),
        ),
        (
            "outcome",
            "outcomes_outcome",
            (
                "deal_flag_id", "acted", "skip_reason", "bought_at", "bought_price",
                "sold_at", "sold_price", "days_held", "realised_margin",
            ),
        ),
        (
            "alert_delivery",
            "alerts_alertdelivery",
            ("deal_flag_id", "status", "claimed_at", "terminal_at", "failure_detail"),
        ),
    ],
)
def test_drill_representative_rows_match_source_field_for_field(
    scratch_connection, snapshot_key, table, fields
):
    expected = _source_snapshot()[snapshot_key]
    assert set(expected) == {"id", *fields}
    with scratch_connection.cursor() as cursor:
        restored = _fetch_record(cursor, table, expected["id"], fields)
    assert restored == {field: expected[field] for field in fields}


@drill
def test_drill_personal_records_and_swap_linkage_survive(scratch_connection):
    """TASK_007 forward-only records live in PostgreSQL, not in any source
    file (docs/09_PLANNING.md §3.7); both immutable sides of a swap must
    still join."""
    snapshot = _source_snapshot()
    personal = snapshot["personal_record"]
    swap = snapshot["swap"]
    assert personal["occurred_at"] is not None
    with scratch_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM sources_source WHERE name = 'personal_records';")
        assert cursor.fetchone()[0] == 1, "the personal_records Source must survive"
        cursor.execute(
            "SELECT r.occurred_at FROM ingestion_rawlisting r "
            "JOIN sources_source src ON src.id = r.source_id "
            "WHERE r.id = %s AND src.name = 'personal_records';",
            (personal["rawlisting_id"],),
        )
        occurred = cursor.fetchone()
        assert occurred is not None
        assert _canonical(occurred[0]) == personal["occurred_at"]
        cursor.execute(
            "SELECT s.given_listing_id, s.received_listing_id FROM ingestion_swap s "
            "JOIN ingestion_rawlisting g ON g.id = s.given_listing_id "
            "JOIN ingestion_rawlisting r ON r.id = s.received_listing_id "
            "WHERE s.id = %s;",
            (swap["id"],),
        )
        assert cursor.fetchone() == (swap["given_listing_id"], swap["received_listing_id"])


@drill
def test_drill_swap_sides_still_share_one_seller_token(scratch_connection):
    """Key-free repeat-counterparty linkage (§9.3)."""
    swap = _source_snapshot()["swap"]
    with scratch_connection.cursor() as cursor:
        cursor.execute(
            "SELECT g.seller, r.seller FROM ingestion_swap s "
            "JOIN ingestion_rawlisting g ON g.id = s.given_listing_id "
            "JOIN ingestion_rawlisting r ON r.id = s.received_listing_id "
            "WHERE s.id = %s;",
            (swap["id"],),
        )
        given, received = cursor.fetchone()
    assert given == received == swap["seller"] != "", (
        "both sides of a swap must still carry one identical seller token"
    )


@drill
def test_drill_every_fixture_seller_token_exactly_matches_source_snapshot(scratch_connection):
    expected = _source_snapshot()["seller_tokens"]
    assert expected
    with scratch_connection.cursor() as cursor:
        for fixture in expected:
            assert set(fixture) == {"rawlisting_id", "seller"}
            cursor.execute(
                "SELECT seller FROM ingestion_rawlisting WHERE id = %s;",
                (fixture["rawlisting_id"],),
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == fixture["seller"]


@drill
def test_drill_pseudonym_continuity_holds_with_the_original_key(scratch_connection):
    """The honest continuity check (§9.2): the operator-recovered ORIGINAL key
    must reproduce a restored token exactly, and a wrong key must not."""
    sentinel = os.environ.get("PRICEWATCHPH_T037_CONTINUITY_SENTINEL")
    original_key = os.environ.get("PRICEWATCHPH_T037_ORIGINAL_PSEUDONYM_KEY")
    if not sentinel or not original_key:
        pytest.fail(
            "the drill must supply the continuity sentinel and the independently "
            "recovered ORIGINAL pseudonym key"
        )

    snapshot = _source_snapshot()["continuity"]
    expected = hmac.new(
        original_key.encode("utf-8"), sentinel.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert expected == snapshot["seller"]

    with scratch_connection.cursor() as cursor:
        cursor.execute(
            "SELECT seller FROM ingestion_rawlisting WHERE id = %s;",
            (snapshot["rawlisting_id"],),
        )
        restored = cursor.fetchone()
    assert restored == (expected,)

    wrong = hmac.new(
        (original_key + "-wrong").encode("utf-8"), sentinel.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert wrong != expected
    assert wrong != restored[0]


@drill
def test_drill_no_counterparty_plaintext_survives_in_the_restored_row(
    scratch_connection,
):
    sentinel = os.environ.get("PRICEWATCHPH_T037_CONTINUITY_SENTINEL")
    if not sentinel:
        pytest.fail("the drill must supply the continuity sentinel")
    fixture = _source_snapshot()["continuity"]
    with scratch_connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM ingestion_rawlisting "
            "WHERE id = %s AND (seller = %s OR payload::text LIKE %s);",
            (fixture["rawlisting_id"], sentinel, f"%{sentinel}%"),
        )
        assert cursor.fetchone()[0] == 0, (
            "counterparty plaintext must never be stored, restored, or recoverable"
        )


@drill
def test_drill_active_application_database_is_empirically_unchanged():
    before = _json_env(ACTIVE_BEFORE_ENV)
    after = _json_env(ACTIVE_AFTER_ENV)
    required = {"row_counts", "migration_state"}
    assert set(before) == required
    assert set(after) == required
    assert before["row_counts"], "active row-count snapshot must be non-empty"
    assert before["migration_state"], "active migration snapshot must be non-empty"
    assert before == after
