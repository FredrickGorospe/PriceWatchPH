#!/bin/sh
set -eu

[ "$#" -eq 0 ] || {
    printf '%s\n' 'the restore drill accepts no arguments' >&2
    exit 2
}

umask 077

INHERITED_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME-}"
INHERITED_COMPOSE_FILE="${COMPOSE_FILE-}"
INHERITED_COMPOSE_PROFILES="${COMPOSE_PROFILES-}"
unset COMPOSE_PROJECT_NAME COMPOSE_FILE COMPOSE_PROFILES

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
TASK_COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
BACKUP_DIR="${PRICEWATCHPH_BACKUP_DIR:-$SCRIPT_DIR/backups}"
if [ -n "$INHERITED_COMPOSE_PROJECT_NAME" ]; then
    ACTIVE_PROJECT="$INHERITED_COMPOSE_PROJECT_NAME"
else
    ACTIVE_PROJECT="$(basename "$SCRIPT_DIR" | tr '[:upper:]' '[:lower:]')"
fi
DRILL_PROJECT="task037-drill-$(date -u +%Y%m%d%H%M%S)-$$"
SCRATCH_SERVICE="restore_scratch"
SCRATCH_USER="restore_scratch"
SOURCE_DB="pricewatch_backup_source_scratch"
TARGET_DB="pricewatch_restore_scratch"
DRILL_RESOURCES_ESTABLISHED=0
VERIFIED_DRILL_CONTAINER_ID=""
VERIFIED_DRILL_NETWORK_ID=""
VERIFIED_DRILL_VOLUME_NAME=""
APPLICATION_RUNNER_ENV_FILE=""
ACTIVE_WEB_CONTAINER_ID=""
ACTIVE_APPLICATION_IMAGE_ID=""
REJECTION_DIR=""
REJECTION_ARTIFACT="pricewatchph-20000101T000000Z.dump"

printf '%s\n' "$ACTIVE_PROJECT" | grep -Eq '^[a-z0-9][a-z0-9_-]*$' || {
    printf '%s\n' 'Active Compose project identity is invalid.' >&2
    exit 2
}
[ "$ACTIVE_PROJECT" != "$DRILL_PROJECT" ] || {
    printf '%s\n' 'Active and drill Compose projects must be distinct.' >&2
    exit 2
}

readonly SCRIPT_DIR TASK_COMPOSE_FILE BACKUP_DIR ACTIVE_PROJECT DRILL_PROJECT
readonly SCRATCH_SERVICE SCRATCH_USER SOURCE_DB TARGET_DB

cd "$SCRIPT_DIR"
mkdir -p "$BACKUP_DIR"

compose_drill() {
    docker compose --project-name "$DRILL_PROJECT" --file "$TASK_COMPOSE_FILE" "$@"
}

compose_active() {
    docker compose --project-name "$ACTIVE_PROJECT" --file "$TASK_COMPOSE_FILE" "$@"
}

nonempty_line_count() {
    printf '%s\n' "$1" | awk 'NF { count += 1 } END { print count + 0 }'
}

strict_drill_project_identity() {
    printf '%s\n' "$DRILL_PROJECT" \
        | grep -Eq '^task037-drill-[0-9]{14}-[0-9]+$' || return 1
    [ "$DRILL_PROJECT" != "$ACTIVE_PROJECT" ] || return 1
}

prove_drill_resource_ownership() {
    VERIFIED_DRILL_CONTAINER_ID=""
    VERIFIED_DRILL_NETWORK_ID=""
    VERIFIED_DRILL_VOLUME_NAME=""
    strict_drill_project_identity || return 1

    PROJECT_CONTAINER_IDS="$(
        docker ps --all --quiet --no-trunc \
            --filter "label=com.docker.compose.project=$DRILL_PROJECT"
    )" || return 1
    RESOLVED_CONTAINER_IDS="$(
        compose_drill ps --all --quiet "$SCRATCH_SERVICE"
    )" || return 1
    [ "$(nonempty_line_count "$PROJECT_CONTAINER_IDS")" -eq 1 ] || return 1
    [ "$PROJECT_CONTAINER_IDS" = "$RESOLVED_CONTAINER_IDS" ] || return 1

    DRILL_CONTAINER_ID="$PROJECT_CONTAINER_IDS"
    [ "$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$DRILL_CONTAINER_ID")" = "$DRILL_PROJECT" ] \
        || return 1
    [ "$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' "$DRILL_CONTAINER_ID")" = "$SCRATCH_SERVICE" ] \
        || return 1

    ATTACHED_NETWORK_IDS="$(
        docker inspect --format '{{ range .NetworkSettings.Networks }}{{ println .NetworkID }}{{ end }}' \
            "$DRILL_CONTAINER_ID"
    )" || return 1
    PROJECT_NETWORK_IDS="$(
        docker network ls --quiet --no-trunc \
            --filter "label=com.docker.compose.project=$DRILL_PROJECT"
    )" || return 1
    [ "$(nonempty_line_count "$ATTACHED_NETWORK_IDS")" -eq 1 ] || return 1
    [ "$ATTACHED_NETWORK_IDS" = "$PROJECT_NETWORK_IDS" ] || return 1
    [ "$(docker network inspect --format '{{ index .Labels "com.docker.compose.project" }}' "$PROJECT_NETWORK_IDS")" = "$DRILL_PROJECT" ] \
        || return 1
    [ "$(docker network inspect --format '{{ index .Labels "com.docker.compose.network" }}' "$PROJECT_NETWORK_IDS")" = "default" ] \
        || return 1

    ATTACHED_VOLUME_NAMES="$(
        docker inspect --format '{{ range .Mounts }}{{ if eq .Type "volume" }}{{ println .Name }}{{ end }}{{ end }}' \
            "$DRILL_CONTAINER_ID"
    )" || return 1
    PROJECT_VOLUME_NAMES="$(
        docker volume ls --quiet \
            --filter "label=com.docker.compose.project=$DRILL_PROJECT"
    )" || return 1
    [ "$(nonempty_line_count "$ATTACHED_VOLUME_NAMES")" -eq 1 ] || return 1
    [ "$ATTACHED_VOLUME_NAMES" = "$PROJECT_VOLUME_NAMES" ] || return 1
    [ "$(docker volume inspect --format '{{ index .Labels "com.docker.compose.project" }}' "$PROJECT_VOLUME_NAMES")" = "$DRILL_PROJECT" ] \
        || return 1
    [ "$(docker volume inspect --format '{{ index .Labels "com.docker.compose.volume" }}' "$PROJECT_VOLUME_NAMES")" = "task037_scratch_data" ] \
        || return 1

    VERIFIED_DRILL_CONTAINER_ID="$DRILL_CONTAINER_ID"
    VERIFIED_DRILL_NETWORK_ID="$PROJECT_NETWORK_IDS"
    VERIFIED_DRILL_VOLUME_NAME="$PROJECT_VOLUME_NAMES"
}

prepare_application_runner() {
    APPLICATION_RUNNER_ENV_FILE=""
    ACTIVE_WEB_CONTAINER_ID=""
    ACTIVE_APPLICATION_IMAGE_ID=""

    ACTIVE_WEB_CONTAINER_IDS="$(
        compose_active ps --status running --quiet web
    )" || return 1
    [ "$(nonempty_line_count "$ACTIVE_WEB_CONTAINER_IDS")" -eq 1 ] || return 1
    ACTIVE_WEB_CONTAINER_ID="$ACTIVE_WEB_CONTAINER_IDS"
    [ "$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$ACTIVE_WEB_CONTAINER_ID")" = "$ACTIVE_PROJECT" ] \
        || return 1
    [ "$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' "$ACTIVE_WEB_CONTAINER_ID")" = "web" ] \
        || return 1

    ACTIVE_APPLICATION_IMAGE_ID="$(
        docker inspect --format '{{ .Image }}' "$ACTIVE_WEB_CONTAINER_ID"
    )" || return 1
    printf '%s\n' "$ACTIVE_APPLICATION_IMAGE_ID" \
        | grep -Eq '^sha256:[0-9a-f]{64}$' || return 1
    [ "$(docker image inspect --format '{{ .Id }}' "$ACTIVE_APPLICATION_IMAGE_ID")" = "$ACTIVE_APPLICATION_IMAGE_ID" ] \
        || return 1
    ACTIVE_APPLICATION_DECLARED_VOLUMES="$(
        docker image inspect \
            --format '{{ range $path, $_ := (index .Config "Volumes") }}{{ println $path }}{{ end }}' \
            "$ACTIVE_APPLICATION_IMAGE_ID"
    )" || return 1
    [ "$(nonempty_line_count "$ACTIVE_APPLICATION_DECLARED_VOLUMES")" -eq 0 ] \
        || return 1

    ACTIVE_APPLICATION_ENVIRONMENT="$(
        docker inspect --format '{{ range .Config.Env }}{{ println . }}{{ end }}' \
            "$ACTIVE_WEB_CONTAINER_ID"
    )" || return 1
    APPLICATION_RUNNER_ENV_FILE="$(
        mktemp "${TMPDIR:-/tmp}/task037-application-env.XXXXXX"
    )" || return 1

    printf '%s\n' "$ACTIVE_APPLICATION_ENVIRONMENT" \
        | while IFS= read -r ENVIRONMENT_ENTRY; do
            case "$ENVIRONMENT_ENTRY" in
                POSTGRES_DB=*|POSTGRES_USER=*|POSTGRES_PASSWORD=*|POSTGRES_HOST=*|POSTGRES_PORT=*|PGHOST=*|PGPORT=*|PGDATABASE=*|PGUSER=*|PGPASSWORD=*|PYTHONDONTWRITEBYTECODE=*|PRICEWATCHPH_T037_*=*)
                    ;;
                *)
                    printf '%s\n' "$ENVIRONMENT_ENTRY"
                    ;;
            esac
        done > "$APPLICATION_RUNNER_ENV_FILE"
    printf '%s\n' \
        "POSTGRES_HOST=$SCRATCH_SERVICE" \
        "POSTGRES_PORT=5432" \
        "POSTGRES_DB=$SOURCE_DB" \
        "POSTGRES_USER=$SCRATCH_USER" \
        "POSTGRES_PASSWORD=$SCRATCH_PASSWORD" \
        "PGHOST=$SCRATCH_SERVICE" \
        "PGPORT=5432" \
        "PGDATABASE=$SOURCE_DB" \
        "PGUSER=$SCRATCH_USER" \
        "PGPASSWORD=$SCRATCH_PASSWORD" \
        "PYTHONDONTWRITEBYTECODE=1" \
        "PRICEWATCHPH_T037_CONTINUITY_SENTINEL=$PRICEWATCHPH_T037_CONTINUITY_SENTINEL" \
        >> "$APPLICATION_RUNNER_ENV_FILE"
    chmod 600 "$APPLICATION_RUNNER_ENV_FILE"

    printf 'Scratch application image: %s; active web container: %s\n' \
        "$ACTIVE_APPLICATION_IMAGE_ID" "$ACTIVE_WEB_CONTAINER_ID"
}

run_scratch_python() {
    RUNNER_DATABASE="$1"
    shift
    [ "$RUNNER_DATABASE" = "$SOURCE_DB" ] || [ "$RUNNER_DATABASE" = "$TARGET_DB" ] \
        || return 1
    [ "$DRILL_RESOURCES_ESTABLISHED" -eq 1 ] || return 1
    [ -n "$ACTIVE_APPLICATION_IMAGE_ID" ] || return 1
    [ -f "$APPLICATION_RUNNER_ENV_FILE" ] || return 1
    if ! prove_drill_resource_ownership; then
        printf '%s\n' 'Drill ownership is not exact before scratch application runner.' >&2
        return 1
    fi

    if docker run --rm --interactive \
            --network "$VERIFIED_DRILL_NETWORK_ID" \
            --env-file "$APPLICATION_RUNNER_ENV_FILE" \
            --env "POSTGRES_DB=$RUNNER_DATABASE" \
            --env "PGDATABASE=$RUNNER_DATABASE" \
            --mount "type=bind,src=$SCRIPT_DIR,dst=/app,readonly" \
            --entrypoint python \
            "$ACTIVE_APPLICATION_IMAGE_ID" "$@"; then
        RUNNER_STATUS=0
    else
        RUNNER_STATUS=$?
    fi
    if ! prove_drill_resource_ownership; then
        printf '%s\n' 'Drill ownership changed during scratch application runner.' >&2
        return 1
    fi
    [ "$RUNNER_STATUS" -eq 0 ] || return "$RUNNER_STATUS"
}

run_scratch_pytest() {
    RUNNER_DATABASE="$1"
    shift
    [ "$RUNNER_DATABASE" = "$TARGET_DB" ] || return 1
    [ "$DRILL_RESOURCES_ESTABLISHED" -eq 1 ] || return 1
    [ -n "$ACTIVE_APPLICATION_IMAGE_ID" ] || return 1
    [ -f "$APPLICATION_RUNNER_ENV_FILE" ] || return 1
    if ! prove_drill_resource_ownership; then
        printf '%s\n' 'Drill ownership is not exact before scratch pytest runner.' >&2
        return 1
    fi

    if docker run --rm --interactive \
            --network "$VERIFIED_DRILL_NETWORK_ID" \
            --env-file "$APPLICATION_RUNNER_ENV_FILE" \
            --env "POSTGRES_DB=$RUNNER_DATABASE" \
            --env "PGDATABASE=$RUNNER_DATABASE" \
            --env PRICEWATCHPH_T037_SCRATCH_HOST \
            --env PRICEWATCHPH_T037_SCRATCH_PORT \
            --env PRICEWATCHPH_T037_SCRATCH_DB \
            --env PRICEWATCHPH_T037_SCRATCH_USER \
            --env PRICEWATCHPH_T037_SCRATCH_PASSWORD \
            --env PRICEWATCHPH_T037_SOURCE_SNAPSHOT_JSON \
            --env PRICEWATCHPH_T037_ACTIVE_BEFORE_JSON \
            --env PRICEWATCHPH_T037_ACTIVE_AFTER_JSON \
            --env PRICEWATCHPH_T037_CONTINUITY_SENTINEL \
            --env PRICEWATCHPH_T037_ORIGINAL_PSEUDONYM_KEY \
            --mount "type=bind,src=$SCRIPT_DIR,dst=/app,readonly" \
            --entrypoint pytest \
            "$ACTIVE_APPLICATION_IMAGE_ID" "$@"; then
        RUNNER_STATUS=0
    else
        RUNNER_STATUS=$?
    fi
    if ! prove_drill_resource_ownership; then
        printf '%s\n' 'Drill ownership changed during scratch pytest runner.' >&2
        return 1
    fi
    [ "$RUNNER_STATUS" -eq 0 ] || return "$RUNNER_STATUS"
}

run_drill_backup() {
    [ "$DRILL_RESOURCES_ESTABLISHED" -eq 1 ] || return 1
    [ -n "$VERIFIED_DRILL_CONTAINER_ID" ] || return 1
    [ -n "$VERIFIED_DRILL_NETWORK_ID" ] || return 1

    PGHOST="$SCRATCH_SERVICE"
    PGPORT=5432
    PGDATABASE="$SOURCE_DB"
    PGUSER="$SCRATCH_USER"
    PGPASSWORD="$SCRATCH_PASSWORD"
    export PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD

    BACKUP_RUNNER_IMAGE_ID="$(
        docker inspect --format '{{.Image}}' "$VERIFIED_DRILL_CONTAINER_ID"
    )" || return 1
    printf '%s\n' "$BACKUP_RUNNER_IMAGE_ID" \
        | grep -Eq '^sha256:[0-9a-f]{64}$' || return 1
    [ "$(docker image inspect --format '{{.Id}}' "$BACKUP_RUNNER_IMAGE_ID")" \
        = "$BACKUP_RUNNER_IMAGE_ID" ] || return 1
    BACKUP_RUNNER_DECLARED_VOLUMES="$(
        docker image inspect \
            --format '{{ range $path, $_ := (index .Config "Volumes") }}{{ println $path }}{{ end }}' \
            "$BACKUP_RUNNER_IMAGE_ID"
    )" || return 1
    [ "$(nonempty_line_count "$BACKUP_RUNNER_DECLARED_VOLUMES")" -eq 1 ] \
        || return 1
    [ "$BACKUP_RUNNER_DECLARED_VOLUMES" = "/var/lib/postgresql/data" ] \
        || return 1
    docker volume ls --quiet >/dev/null || return 1
    BACKUP_RUNNER_VOLUMES_BEFORE="$(docker volume ls --quiet | LC_ALL=C sort)" || return 1

    if ! prove_drill_resource_ownership; then
        printf '%s\n' 'Drill ownership is not exact immediately before isolated backup runner; backup skipped.' >&2
        return 1
    fi
    if docker run \
            --rm \
            --network "$VERIFIED_DRILL_NETWORK_ID" \
            --env PGHOST \
            --env PGPORT \
            --env PGDATABASE \
            --env PGUSER \
            --env PGPASSWORD \
            --mount "type=bind,src=$SCRIPT_DIR/pg_backup.sh,dst=/usr/local/bin/pg_backup.sh,readonly" \
            --mount "type=bind,src=$BACKUP_DIR,dst=/backups" \
            --tmpfs /var/lib/postgresql/data \
            "$BACKUP_RUNNER_IMAGE_ID" /usr/local/bin/pg_backup.sh; then
        RUNNER_STATUS=0
    else
        RUNNER_STATUS=$?
    fi
    if ! prove_drill_resource_ownership; then
        printf '%s\n' 'Drill ownership changed during isolated backup runner; further work stopped.' >&2
        return 1
    fi
    docker volume ls --quiet >/dev/null || return 1
    BACKUP_RUNNER_VOLUMES_AFTER="$(docker volume ls --quiet | LC_ALL=C sort)" || return 1
    if [ "$BACKUP_RUNNER_VOLUMES_BEFORE" != "$BACKUP_RUNNER_VOLUMES_AFTER" ]; then
        printf '%s\n' 'Persistent Docker volume inventory changed during isolated backup runner.' >&2
        return 1
    fi
    [ "$RUNNER_STATUS" -eq 0 ] || return "$RUNNER_STATUS"
}

remove_verified_drill_resources() {
    [ -n "$VERIFIED_DRILL_CONTAINER_ID" ] || return 1
    [ -n "$VERIFIED_DRILL_NETWORK_ID" ] || return 1
    [ -n "$VERIFIED_DRILL_VOLUME_NAME" ] || return 1

    docker rm --force "$VERIFIED_DRILL_CONTAINER_ID" || return 1
    docker network rm "$VERIFIED_DRILL_NETWORK_ID" || return 1
    docker volume rm "$VERIFIED_DRILL_VOLUME_NAME" || return 1
}

mode_of() {
    if stat -f '%Lp' "$1" >/dev/null 2>&1; then
        stat -f '%Lp' "$1"
    else
        stat -c '%a' "$1"
    fi
}

pair_metadata_valid() {
    PAIR_DIR="$1"
    PAIR_ARTIFACT="$2"
    PAIR_DUMP="$PAIR_DIR/$PAIR_ARTIFACT"
    PAIR_CHECKSUM="$PAIR_DUMP.sha256"

    printf '%s\n' "$PAIR_ARTIFACT" \
        | grep -Eq '^pricewatchph-[0-9]{8}T[0-9]{6}Z\.dump$' || return 1
    [ ! -e "$PAIR_DIR/.$PAIR_ARTIFACT.partial" ] || return 1
    [ ! -e "$PAIR_DIR/.$PAIR_ARTIFACT.sha256.partial" ] || return 1
    [ -f "$PAIR_DUMP" ] || return 1
    [ -f "$PAIR_CHECKSUM" ] || return 1
    [ "$(mode_of "$PAIR_DUMP")" = "600" ] || return 1
    [ "$(mode_of "$PAIR_CHECKSUM")" = "600" ] || return 1

    CHECKSUM_LINE_COUNT="$(wc -l < "$PAIR_CHECKSUM")"
    [ "$CHECKSUM_LINE_COUNT" -eq 1 ] || return 1
    PAIR_DIGEST="$(sha256sum "$PAIR_DUMP" | cut -d ' ' -f 1)"
    [ "$(cat "$PAIR_CHECKSUM")" = "$PAIR_DIGEST  $PAIR_ARTIFACT" ] || return 1
    (cd "$PAIR_DIR" && sha256sum -c "$PAIR_ARTIFACT.sha256" >/dev/null 2>&1) \
        || return 1
}

validate_artifact_pair() {
    VALIDATED_ARTIFACT="$1"
    ARTIFACT_PATH="$BACKUP_DIR/$VALIDATED_ARTIFACT"
    CHECKSUM_PATH="$ARTIFACT_PATH.sha256"
    [ -f "$ARTIFACT_PATH" ]
    [ -f "$CHECKSUM_PATH" ]
    pair_metadata_valid "$BACKUP_DIR" "$VALIDATED_ARTIFACT"
    compose_drill exec -T "$SCRATCH_SERVICE" \
        pg_restore --list "/backups/$VALIDATED_ARTIFACT" >/dev/null
}

cleanup_rejection_dir() {
    [ -n "$REJECTION_DIR" ] || return 0
    rm -f \
        "$REJECTION_DIR/$REJECTION_ARTIFACT" \
        "$REJECTION_DIR/$REJECTION_ARTIFACT.sha256" \
        "$REJECTION_DIR/.$REJECTION_ARTIFACT.partial" \
        "$REJECTION_DIR/.$REJECTION_ARTIFACT.sha256.partial"
    rmdir "$REJECTION_DIR"
    REJECTION_DIR=""
}

cleanup_application_runner_environment() {
    [ -n "$APPLICATION_RUNNER_ENV_FILE" ] || return 0
    rm -f "$APPLICATION_RUNNER_ENV_FILE"
    APPLICATION_RUNNER_ENV_FILE=""
}

cleanup() {
    STATUS=$?
    trap - 0
    cleanup_rejection_dir || STATUS=1
    cleanup_application_runner_environment || STATUS=1
    if [ "$DRILL_RESOURCES_ESTABLISHED" -eq 1 ]; then
        if ! prove_drill_resource_ownership; then
            printf '%s\n' 'Drill resource ownership could not be proven; destructive cleanup skipped.' >&2
            STATUS=1
        else
            if ! remove_verified_drill_resources; then
                printf '%s\n' 'Exact verified drill resource cleanup failed; no broader cleanup attempted.' >&2
                STATUS=1
            fi
            if compose_active ps --status running --services | grep -qx 'db'; then
                printf '%s\n' 'Active application database container remains running.'
            else
                printf '%s\n' 'Active application database container is not running.' >&2
                STATUS=1
            fi
            if [ "$STATUS" -eq 0 ]; then
                printf '%s\n' "Scratch cleanup completed for $DRILL_PROJECT."
            fi
        fi
    fi
    exit "$STATUS"
}

trap cleanup 0
trap 'exit 130' HUP INT TERM

exercise_pair_rejections() {
    REJECTION_DIR="$(mktemp -d "${TMPDIR:-/tmp}/task037-pair.XXXXXX")"
    REJECTION_DUMP="$REJECTION_DIR/$REJECTION_ARTIFACT"
    REJECTION_CHECKSUM="$REJECTION_DUMP.sha256"

    : > "$REJECTION_DUMP"
    if pair_metadata_valid "$REJECTION_DIR" "$REJECTION_ARTIFACT"; then
        return 1
    fi
    rm "$REJECTION_DUMP"

    printf '%064d  %s\n' 0 "$REJECTION_ARTIFACT" > "$REJECTION_CHECKSUM"
    if pair_metadata_valid "$REJECTION_DIR" "$REJECTION_ARTIFACT"; then
        return 1
    fi
    rm "$REJECTION_CHECKSUM"

    : > "$REJECTION_DUMP"
    REJECTION_DIGEST="$(sha256sum "$REJECTION_DUMP" | cut -d ' ' -f 1)"
    printf '%s  %s\n' "$REJECTION_DIGEST" "$REJECTION_ARTIFACT" \
        > "$REJECTION_CHECKSUM"
    : > "$REJECTION_DIR/.$REJECTION_ARTIFACT.partial"
    if pair_metadata_valid "$REJECTION_DIR" "$REJECTION_ARTIFACT"; then
        return 1
    fi
    rm "$REJECTION_DIR/.$REJECTION_ARTIFACT.partial"

    printf '%s\n' 'malformed-sidecar' > "$REJECTION_CHECKSUM"
    if pair_metadata_valid "$REJECTION_DIR" "$REJECTION_ARTIFACT"; then
        return 1
    fi

    printf '%064d  %s\n' 0 "$REJECTION_ARTIFACT" > "$REJECTION_CHECKSUM"
    if pair_metadata_valid "$REJECTION_DIR" "$REJECTION_ARTIFACT"; then
        return 1
    fi

    cleanup_rejection_dir
    printf '%s\n' 'Orphan, partial, malformed-sidecar, and checksum-mismatch rejection verified.'
}

capture_active_snapshot() {
    compose_active exec -T web python -c \
        'import sys; exec(compile(sys.stdin.read(), "<active_snapshot>", "exec"))' <<'PY'
import json
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.db import connection

tables = (
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
)
with connection.cursor() as cursor:
    row_counts = {}
    for table in tables:
        cursor.execute(f"SELECT count(*) FROM {table};")
        row_counts[table] = cursor.fetchone()[0]
    cursor.execute("SELECT app, name FROM django_migrations ORDER BY app, name;")
    migration_state = [list(row) for row in cursor.fetchall()]

print(
    json.dumps(
        {"migration_state": migration_state, "row_counts": row_counts},
        sort_keys=True,
        separators=(",", ":"),
    )
)
PY
}

run_source_python() {
    run_scratch_python "$SOURCE_DB" -c \
        'import os, sys; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings"); import django; django.setup(); exec(compile(sys.stdin.read(), "<task037_source>", "exec"))'
}

populate_fixtures() {
    [ "$1" = "$SOURCE_DB" ]
    run_source_python <<'PY'
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from alerts.models import AlertDelivery
from catalogue.models import Sku, SkuAlias
from ingestion.admin import RawListingAdmin
from ingestion.models import RawListing, Swap
from listings.models import Listing
from outcomes.models import Outcome
from pricing.models import DealFlag, PricePoint
from sources.models import Source

fixed = datetime(2026, 8, 15, 1, 2, 3, tzinfo=timezone.utc)
later = datetime(2026, 8, 15, 1, 7, 3, tzinfo=timezone.utc)
sentinel = os.environ["PRICEWATCHPH_T037_CONTINUITY_SENTINEL"]

personal_source = Source.objects.get(name="personal_records")
synthetic_source = Source.objects.create(
    name="task_037_synthetic",
    base_url="https://example.invalid/task-037",
    terms_notes="Synthetic TASK_037 backup and restore fixture.",
    rate_limit=60,
    last_successful_fetch=fixed,
)
sku = Sku.objects.create(
    brand="Synthetic",
    model="TASK 037 GPU",
    variant="Restore Drill",
    category="gpu",
    launch_msrp=Decimal("29999.00"),
    launch_date=date(2026, 1, 1),
)
SkuAlias.objects.create(
    sku=sku,
    alias_text="Synthetic TASK 037 GPU Restore Drill",
    normalised_text="synthetic task 037 gpu restore drill",
    source_of_truth="human_confirmed",
)

null_payload = RawListing.objects.create(
    source=synthetic_source,
    raw_title="TASK 037 null payload listing",
    raw_price_text="PHP 12,345.67",
    raw_price=Decimal("12345.67"),
    url="https://example.invalid/task-037/null",
    seller="",
    fetched_at=fixed,
    occurred_at=None,
    external_id="task037-null-payload",
    payload=None,
)
empty_payload = RawListing.objects.create(
    source=synthetic_source,
    raw_title="TASK 037 empty payload listing",
    raw_price_text="PHP 13,500.00",
    raw_price=Decimal("13500.00"),
    url="https://example.invalid/task-037/empty",
    seller="",
    fetched_at=later,
    occurred_at=fixed,
    external_id="task037-empty-payload",
    payload={},
)
primary_listing = Listing.objects.create(
    raw_listing=null_payload,
    sku=sku,
    price=Decimal("12345.67"),
    condition="used",
    location="Quezon City",
    resolution_confidence=Decimal("1.0000"),
    resolution_method="human_confirmed",
    resolved_at=later,
    observed_at=fixed,
    price_kind="asking",
    trade_side=None,
)
secondary_listing = Listing.objects.create(
    raw_listing=empty_payload,
    sku=sku,
    price=Decimal("13500.00"),
    condition="used",
    location="Makati",
    resolution_confidence=Decimal("0.9500"),
    resolution_method="exact_alias",
    resolved_at=later,
    observed_at=later,
    price_kind="asking",
    trade_side=None,
)
baseline = PricePoint.objects.create(
    sku=sku,
    condition="used",
    day=date(2026, 8, 14),
    median=Decimal("16000.0000"),
    p25=Decimal("15000.0000"),
    p75=Decimal("17000.0000"),
    n_listings=8,
    mad=Decimal("750.0000"),
    window_start_day=date(2026, 7, 15),
    window_end_day=date(2026, 8, 15),
    calculated_at=later,
    calculation_contract_version="task037-v1",
)
alternate = PricePoint.objects.create(
    sku=sku,
    condition="used",
    day=date(2026, 8, 13),
    median=Decimal("16250.0000"),
    p25=Decimal("15250.0000"),
    p75=Decimal("17250.0000"),
    n_listings=7,
)
primary_flag = DealFlag.objects.create(
    listing=primary_listing,
    score=Decimal("-4.8720"),
    baseline_pricepoint=baseline,
    reason="task037-restored-deal",
    flagged_at=later,
)
unclaimed_flag = DealFlag.objects.create(
    listing=secondary_listing,
    score=Decimal("-3.6667"),
    baseline_pricepoint=baseline,
    reason="task037-unclaimed-deal",
    flagged_at=later,
)
Outcome.objects.create(
    deal_flag=primary_flag,
    acted=True,
    skip_reason=None,
    bought_at=later,
    bought_price=Decimal("12345.67"),
    sold_at=datetime(2026, 8, 20, 1, 7, 3, tzinfo=timezone.utc),
    sold_price=Decimal("14999.99"),
    days_held=5,
)
delivery = AlertDelivery.objects.create(
    deal_flag=primary_flag,
    status="pending",
    claimed_at=later,
    terminal_at=None,
    failure_detail=None,
)
delivery.status = "sent"
delivery.terminal_at = datetime(2026, 8, 15, 1, 8, 3, tzinfo=timezone.utc)
delivery.save(update_fields=("status", "terminal_at"))

trade = {
    "trade_type": "swap",
    "counterparty": sentinel,
    "occurred_on": date(2026, 8, 12),
    "given_item": "TASK 037 synthetic given item",
    "given_value_text": "PHP 8,000.00",
    "given_value": Decimal("8000.00"),
    "given_condition": "used",
    "received_item": "TASK 037 synthetic received item",
    "received_value_text": "PHP 9,500.00",
    "received_value": Decimal("9500.00"),
    "received_condition": "like_new",
    "cash_adjustment": Decimal("1500.00"),
}
with patch("ingestion.admin.timezone.now", return_value=fixed):
    RawListingAdmin._write_personal_trade(trade)

assert personal_source.raw_listings.count() == 2
assert Swap.objects.count() == 1
assert alternate.pk != baseline.pk
assert unclaimed_flag.pk != primary_flag.pk
PY
}

capture_source_snapshot() {
    run_source_python <<'PY'
import json
from datetime import date, datetime
from decimal import Decimal

from alerts.models import AlertDelivery
from ingestion.models import RawListing, Swap
from outcomes.models import Outcome
from pricing.models import DealFlag, PricePoint
from django.db import connection


def canonical(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    return value


def exact(model, row_id, fields):
    values = model.objects.values(*fields).get(pk=row_id)
    return {"id": row_id, **values}


tables = (
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
)
with connection.cursor() as cursor:
    row_counts = {}
    for table in tables:
        cursor.execute(f"SELECT count(*) FROM {table};")
        row_counts[table] = cursor.fetchone()[0]
    cursor.execute("SELECT app, name FROM django_migrations ORDER BY app, name;")
    migration_state = [list(row) for row in cursor.fetchall()]
    cursor.execute(
        "SELECT app, max(name) FROM django_migrations GROUP BY app ORDER BY app;"
    )
    migration_heads = dict(cursor.fetchall())

raw_fields = (
    "raw_title",
    "raw_price_text",
    "raw_price",
    "url",
    "fetched_at",
    "occurred_at",
    "external_id",
    "payload",
)
raw_listings = list(RawListing.objects.order_by("id").values("id", *raw_fields))
null_row = RawListing.objects.get(external_id="task037-null-payload")
empty_row = RawListing.objects.get(external_id="task037-empty-payload")
baseline = PricePoint.objects.get(calculation_contract_version="task037-v1")
alternate = PricePoint.objects.exclude(pk=baseline.pk).get()
primary_flag = DealFlag.objects.get(reason="task037-restored-deal")
unclaimed_flag = DealFlag.objects.get(reason="task037-unclaimed-deal")
outcome = Outcome.objects.get(deal_flag=primary_flag)
delivery = AlertDelivery.objects.get(deal_flag=primary_flag)
swap = Swap.objects.get()
given = swap.given_listing

snapshot = {
    "row_counts": row_counts,
    "migration_state": migration_state,
    "migration_heads": migration_heads,
    "money_fixture": {"id": null_row.pk, "raw_price": format(null_row.raw_price, "f")},
    "raw_listings": raw_listings,
    "payload_fixtures": {
        "null_rawlisting_id": null_row.pk,
        "empty_rawlisting_id": empty_row.pk,
    },
    "price_point": exact(
        PricePoint,
        baseline.pk,
        (
            "sku_id", "condition", "day", "median", "p25", "p75",
            "n_listings", "mad", "window_start_day", "window_end_day",
            "calculated_at", "calculation_contract_version",
        ),
    ),
    "deal_flag": exact(
        DealFlag,
        primary_flag.pk,
        ("listing_id", "score", "baseline_pricepoint_id", "reason", "flagged_at"),
    ),
    "outcome": exact(
        Outcome,
        outcome.pk,
        (
            "deal_flag_id", "acted", "skip_reason", "bought_at", "bought_price",
            "sold_at", "sold_price", "days_held", "realised_margin",
        ),
    ),
    "alert_delivery": exact(
        AlertDelivery,
        delivery.pk,
        ("deal_flag_id", "status", "claimed_at", "terminal_at", "failure_detail"),
    ),
    "personal_record": {
        "rawlisting_id": given.pk,
        "occurred_at": given.occurred_at,
    },
    "swap": {
        "id": swap.pk,
        "given_listing_id": swap.given_listing_id,
        "received_listing_id": swap.received_listing_id,
        "seller": given.seller,
    },
    "seller_tokens": [
        {"rawlisting_id": row.pk, "seller": row.seller}
        for row in RawListing.objects.order_by("id")
    ],
    "constraint_fixtures": {
        "rawlisting_id": null_row.pk,
        "pricepoint_id": baseline.pk,
        "dealflag_id": primary_flag.pk,
        "alternate_pricepoint_id": alternate.pk,
        "unclaimed_dealflag_id": unclaimed_flag.pk,
    },
    "continuity": {"rawlisting_id": given.pk, "seller": given.seller},
}

assert snapshot["migration_state"]
assert snapshot["migration_heads"]
assert snapshot["alert_delivery"]["status"] == "sent"
assert snapshot["payload_fixtures"]["null_rawlisting_id"] != snapshot["payload_fixtures"]["empty_rawlisting_id"]
print(json.dumps(canonical(snapshot), sort_keys=True, separators=(",", ":")))
PY
}

capture_original_key() {
    run_source_python <<'PY'
from django.conf import settings

print(getattr(settings, "SELLER_" + "PSEUDONYM_KEY"))
PY
}

ACTIVE_POSTGRES_DB="$(
    compose_active exec -T web \
        python -c 'import os; print(os.environ["POSTGRES_DB"])'
)"
ACTIVE_POSTGRES_HOST="$(
    compose_active exec -T web \
        python -c 'import os; print(os.environ["POSTGRES_HOST"])'
)"

if [ "$TARGET_DB" = "$ACTIVE_POSTGRES_DB" ] \
    || [ "$SOURCE_DB" = "$ACTIVE_POSTGRES_DB" ] \
    || [ "$SCRATCH_SERVICE" = "$ACTIVE_POSTGRES_HOST" ] \
    || [ "$TARGET_DB" = "$SOURCE_DB" ]; then
    printf '%s\n' 'Refusing unsafe scratch/application database identity.' >&2
    exit 2
fi

PRICEWATCHPH_T037_ACTIVE_BEFORE_JSON="$(capture_active_snapshot)"
[ -n "$PRICEWATCHPH_T037_ACTIVE_BEFORE_JSON" ]
export PRICEWATCHPH_T037_ACTIVE_BEFORE_JSON

SCRATCH_PASSWORD="$(openssl rand -hex 32)"
[ -n "$SCRATCH_PASSWORD" ]
PRICEWATCHPH_RESTORE_SCRATCH_PASSWORD="$SCRATCH_PASSWORD"
export PRICEWATCHPH_RESTORE_SCRATCH_PASSWORD

compose_drill --profile restore-verify up -d --no-deps "$SCRATCH_SERVICE"
if ! prove_drill_resource_ownership; then
    printf '%s\n' 'Scratch startup returned but dedicated resource ownership is unproven; resources preserved.' >&2
    exit 1
fi
DRILL_RESOURCES_ESTABLISHED=1

READY=0
ATTEMPT=0
while [ "$ATTEMPT" -lt 60 ]; do
    if compose_drill exec -T "$SCRATCH_SERVICE" \
        pg_isready -U "$SCRATCH_USER" -d postgres >/dev/null 2>&1; then
        READY=1
        break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    sleep 1
done
[ "$READY" -eq 1 ] || {
    printf '%s\n' 'Scratch PostgreSQL did not become ready.' >&2
    exit 1
}

compose_drill exec -T "$SCRATCH_SERVICE" \
    createdb -U "$SCRATCH_USER" "$SOURCE_DB"
compose_drill exec -T "$SCRATCH_SERVICE" \
    createdb -U "$SCRATCH_USER" "$TARGET_DB"
printf 'Scratch source: %s; restore target: %s\n' "$SOURCE_DB" "$TARGET_DB"

POSTGRES_HOST="$SCRATCH_SERVICE"
POSTGRES_PORT=5432
POSTGRES_DB="$SOURCE_DB"
POSTGRES_USER="$SCRATCH_USER"
POSTGRES_PASSWORD="$SCRATCH_PASSWORD"
PRICEWATCHPH_T037_CONTINUITY_SENTINEL="task037-continuity-sentinel-not-a-real-counterparty"
export POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
export PRICEWATCHPH_T037_CONTINUITY_SENTINEL

prepare_application_runner
run_scratch_python "$SOURCE_DB" manage.py migrate --noinput # pricewatch_backup_source_scratch

populate_fixtures pricewatch_backup_source_scratch
PRICEWATCHPH_T037_SOURCE_SNAPSHOT_JSON="$(capture_source_snapshot)"
[ -n "$PRICEWATCHPH_T037_SOURCE_SNAPSHOT_JSON" ]
export PRICEWATCHPH_T037_SOURCE_SNAPSHOT_JSON

PRICEWATCHPH_T037_ORIGINAL_PSEUDONYM_KEY="$(capture_original_key)"
[ -n "$PRICEWATCHPH_T037_ORIGINAL_PSEUDONYM_KEY" ]
export PRICEWATCHPH_T037_ORIGINAL_PSEUDONYM_KEY

if BACKUP_OUTPUT="$(run_drill_backup)"; then
    BACKUP_STATUS=0
else
    BACKUP_STATUS=$?
fi
printf '%s\n' "$BACKUP_OUTPUT"
[ "$BACKUP_STATUS" -eq 0 ] || {
    printf '%s\n' 'Isolated backup runner failed.' >&2
    exit 1
}

BACKUP_RECORD_COUNT="$(printf '%s\n' "$BACKUP_OUTPUT" | grep -c '^BACKUP_ARTIFACT=' || true)"
[ "$BACKUP_RECORD_COUNT" -eq 1 ] || {
    printf '%s\n' 'Backup did not emit exactly one artifact record.' >&2
    exit 1
}
ARTIFACT="$(printf '%s\n' "$BACKUP_OUTPUT" | sed -n 's/^BACKUP_ARTIFACT=//p')"
printf '%s\n' "$ARTIFACT" | grep -Eq '^pricewatchph-[0-9]{8}T[0-9]{6}Z\.dump$' || {
    printf '%s\n' 'Backup emitted an invalid artifact basename.' >&2
    exit 1
}

exercise_pair_rejections
validate_artifact_pair "$ARTIFACT"
printf 'Dump permission: %s; checksum permission: %s\n' \
    "$(mode_of "$BACKUP_DIR/$ARTIFACT")" \
    "$(mode_of "$BACKUP_DIR/$ARTIFACT.sha256")"
printf '%s\n' 'Checksum and custom-format structure verified.'

TARGET_TABLE_COUNT="$(
    compose_drill exec -T "$SCRATCH_SERVICE" \
        psql -At -U "$SCRATCH_USER" -d "$TARGET_DB" \
        -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'public';"
)"
[ "$TARGET_TABLE_COUNT" -eq 0 ] || {
    printf '%s\n' 'Restore target was not empty before restore.' >&2
    exit 1
}
printf '%s\n' 'Restore target confirmed empty.'

compose_drill exec -T "$SCRATCH_SERVICE" pg_restore -U "$SCRATCH_USER" -d "$TARGET_DB" --no-owner --no-privileges --exit-on-error "/backups/$ARTIFACT"
printf '%s\n' 'Restore completed.'

PRICEWATCHPH_T037_ACTIVE_AFTER_JSON="$(capture_active_snapshot)"
[ -n "$PRICEWATCHPH_T037_ACTIVE_AFTER_JSON" ]
export PRICEWATCHPH_T037_ACTIVE_AFTER_JSON

PRICEWATCHPH_T037_SCRATCH_HOST="$SCRATCH_SERVICE"
PRICEWATCHPH_T037_SCRATCH_PORT=5432
PRICEWATCHPH_T037_SCRATCH_DB="$TARGET_DB"
PRICEWATCHPH_T037_SCRATCH_USER="$SCRATCH_USER"
PRICEWATCHPH_T037_SCRATCH_PASSWORD="$SCRATCH_PASSWORD"
export PRICEWATCHPH_T037_SCRATCH_HOST PRICEWATCHPH_T037_SCRATCH_PORT
export PRICEWATCHPH_T037_SCRATCH_DB PRICEWATCHPH_T037_SCRATCH_USER
export PRICEWATCHPH_T037_SCRATCH_PASSWORD

run_scratch_pytest "$TARGET_DB" -v -p no:cacheprovider tests/test_task_037_backup_and_verified_restore.py

printf '%s\n' 'TASK_037 real backup and restore drill verified.'
