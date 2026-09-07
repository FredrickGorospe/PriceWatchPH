"""Run one isolated BENCH_003 synthetic pipeline measurement.

The caller owns creation of the fresh benchmark-only PostgreSQL project. This
runner never creates, restores, or removes Docker resources.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator, Mapping
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import TextIO
from zoneinfo import ZoneInfo

from benchmarks.catalogue import CATEGORY_COUNTS, install_catalogue, load_catalogue
from benchmarks.generator import (
    GENERATOR_VERSION,
    MASTER_SEED,
    ProductionRecord,
    iter_observations,
)
from benchmarks.loader import load_raw_observations
from benchmarks.manifest import (
    ARTIFACT_SCHEMA_VERSION,
    CONTRACT_VERSION,
    RELEASE_SHA,
    STAGE_NAMES,
    stage,
    unavailable,
    validate_manifest,
    write_manifest,
)
from benchmarks.metrics import production_locator_fingerprint
from benchmarks.streaming_quality import extract_resolution_quality_streaming


APP_RELATIONS = {
    "source": "sources_source",
    "sku": "catalogue_sku",
    "sku_alias": "catalogue_skualias",
    "raw_listing": "ingestion_rawlisting",
    "listing": "listings_listing",
    "price_point": "pricing_pricepoint",
    "deal_flag": "pricing_dealflag",
}
FROZEN_LIMITS = {
    10_000: (8 * 1024**3, 15 * 60),
    100_000: (12 * 1024**3, 45 * 60),
    500_000: (20 * 1024**3, 2 * 60 * 60),
    1_000_000: (30 * 1024**3, 4 * 60 * 60),
}
MINIMUM_DOCKER_MEMORY_BYTES = 4 * 1024**3
MANILA_TIME_ZONE = ZoneInfo("Asia/Manila")
CATALOGUE_SHA256 = "ec5622601174f8c7caf1a7d85c903b8d8591baca16c45990166125f231860058"
_PRICE_OUTPUT = re.compile(
    r"snapshot_identities=(?P<snapshot>\d+) listings_evaluated=(?P<evaluated>\d+)"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _decimal_seconds(elapsed_ns: int) -> str:
    if elapsed_ns < 0:
        raise ValueError("elapsed monotonic time cannot be negative")
    return str(Decimal(elapsed_ns) / Decimal(1_000_000_000))


def _human_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = Decimal(value)
    index = 0
    while amount >= 1024 and index < len(units) - 1:
        amount /= Decimal(1024)
        index += 1
    return f"{amount.quantize(Decimal('0.01'))} {units[index]}"


def _value_and_human(value: int) -> dict[str, object]:
    return {"bytes": value, "human": _human_bytes(value)}


def _limits_for_count(count: int) -> tuple[int, int]:
    for scale in sorted(FROZEN_LIMITS):
        if count <= scale:
            return FROZEN_LIMITS[scale]
    # Larger extension runs retain the strictest frozen floors and must be
    # identified separately from the four headline scale points.
    return FROZEN_LIMITS[1_000_000]


def _memory_limit_bytes() -> tuple[int | None, str]:
    cgroup_candidates = (
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    )
    for candidate in cgroup_candidates:
        try:
            raw = candidate.read_text(encoding="ascii").strip()
        except OSError:
            continue
        if raw != "max":
            value = int(raw)
            # Old cgroup versions encode unlimited as a very large integer.
            if value < 1 << 60:
                return value, str(candidate)
    try:
        return (
            os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"),
            "host physical memory visible to the process",
        )
    except (OSError, ValueError):
        return None, "no cgroup or system memory value was available"


def resource_preflight(
    *,
    artifact_dir: Path,
    observation_count: int,
    docker_memory_bytes: int,
    docker_memory_source: str,
    now_utc: datetime | None = None,
) -> dict[str, object]:
    disk_floor, timeout_seconds = _limits_for_count(observation_count)
    observed_utc = now_utc if now_utc is not None else datetime.now(timezone.utc)
    if observed_utc.utcoffset() is None:
        raise ValueError("preflight time must be timezone-aware")
    observed_manila = observed_utc.astimezone(MANILA_TIME_ZONE)
    next_midnight = datetime.combine(
        observed_manila.date() + timedelta(days=1),
        datetime_time.min,
        tzinfo=MANILA_TIME_ZONE,
    )
    until_midnight = next_midnight - observed_manila
    seconds_until_midnight = (
        Decimal(until_midnight.days * 86_400 + until_midnight.seconds)
        + Decimal(until_midnight.microseconds) / Decimal(1_000_000)
    )
    filesystem = os.statvfs(artifact_dir)
    disk_available = filesystem.f_bavail * filesystem.f_frsize
    failures = []
    if disk_available < disk_floor:
        failures.append("free disk is below the frozen safety floor")
    if docker_memory_bytes < MINIMUM_DOCKER_MEMORY_BYTES:
        failures.append("Docker memory is below the frozen 4 GiB safety floor")
    if seconds_until_midnight <= timeout_seconds:
        failures.append(
            "insufficient time remains before the next Manila midnight for the frozen full-run timeout"
        )
    return {
        "passed": not failures,
        "failures": failures,
        "free_disk": {
            "required": _value_and_human(disk_floor),
            "observed": _value_and_human(disk_available),
        },
        "docker_memory": {
            "required": _value_and_human(MINIMUM_DOCKER_MEMORY_BYTES),
            "observed": _value_and_human(docker_memory_bytes),
            "measurement_source": docker_memory_source,
        },
        "full_run_timeout_seconds": timeout_seconds,
        "manila_day_boundary": {
            "timezone": "Asia/Manila",
            "observed_at": observed_manila.isoformat(timespec="microseconds"),
            "next_midnight": next_midnight.isoformat(timespec="microseconds"),
            "seconds_until_next_midnight": str(seconds_until_midnight),
            "required_seconds": timeout_seconds,
            "requirement": (
                "seconds_until_next_manila_midnight > full_run_timeout_seconds"
            ),
        },
    }


def capture_machine_context() -> dict[str, object]:
    cpu_model = platform.processor().strip()
    if not cpu_model:
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if line.lower().startswith("model name"):
                    cpu_model = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
    memory = None
    memory_source = "installed memory was not exposed to the process"
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                memory = int(line.split()[1]) * 1024
                memory_source = "/proc/meminfo MemTotal"
                break
    except OSError:
        pass
    if memory is None and platform.system() == "Darwin":
        try:
            completed = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                check=True,
                capture_output=True,
                text=True,
            )
            memory = int(completed.stdout.strip())
            memory_source = "sysctl hw.memsize"
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return {
        "machine_cpu": {
            "model": cpu_model or unavailable("CPU model was not exposed to the process"),
            "logical_cpu_count": os.cpu_count()
            if os.cpu_count() is not None
            else unavailable("logical CPU count was not exposed to the process"),
        },
        "machine_memory": (
            {**_value_and_human(memory), "measurement_source": memory_source}
            if memory is not None
            else unavailable(memory_source)
        ),
        "operating_system": {
            "name": platform.system(),
            "version": platform.version(),
            "architecture": platform.machine(),
        },
    }


def _machine_context(path: Path | None) -> dict[str, object]:
    if path is None:
        return capture_machine_context()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {
        "machine_cpu",
        "machine_memory",
        "operating_system",
    }:
        raise ValueError(
            "machine context JSON must contain exactly machine_cpu, machine_memory, and operating_system"
        )
    return value


def _fsync_text(stream: TextIO) -> None:
    stream.flush()
    os.fsync(stream.fileno())


def _production_json(record: ProductionRecord) -> dict[str, object]:
    return {
        "raw_title": record.raw_title,
        "raw_price_text": record.raw_price_text,
        "raw_price": str(record.raw_price),
        "url": record.url,
        "seller_handle": record.seller_handle,
        "fetched_at": record.fetched_at.isoformat(timespec="microseconds"),
        "occurred_at": (
            record.occurred_at.isoformat(timespec="microseconds")
            if record.occurred_at is not None
            else None
        ),
        "external_id": record.external_id,
        "payload": record.payload,
    }


def _label_json(observation) -> dict[str, object]:
    label = observation.label
    production = observation.production
    return {
        "record_type": "observation",
        "observation_index": label.observation_index,
        "observation_key": label.observation_key,
        "production_fingerprint": production_locator_fingerprint(
            source_name="manual_capture",
            external_id=production.external_id,
            fetched_at=production.fetched_at,
        ),
        "difficulty": label.difficulty,
        "expected_sku_key": label.expected_sku_key,
        "candidate_sku_keys": list(label.candidate_sku_keys),
        "transformations": list(label.transformations),
        "generation_digest": label.generation_digest,
    }


def write_generation_artifacts(
    *,
    production_path: Path,
    labels_path: Path,
    observation_count: int,
    catalogue,
    as_of_day: date,
) -> dict[str, int]:
    """Stream production evidence and isolated labels to distinct files."""
    header = {
        "record_type": "header",
        "schema_version": "benchmark_labels.v1",
        "generator_version": GENERATOR_VERSION,
        "master_seed": MASTER_SEED,
        "catalogue_sha256": catalogue.sha256,
        "as_of_day": as_of_day.isoformat(),
        "observation_count": observation_count,
    }
    difficulty_counts: Counter[str] = Counter()
    with production_path.open("x", encoding="utf-8", newline="\n") as production_stream:
        with labels_path.open("x", encoding="utf-8", newline="\n") as labels_stream:
            labels_stream.write(json.dumps(header, separators=(",", ":"), allow_nan=False))
            labels_stream.write("\n")
            for observation in iter_observations(
                count=observation_count, catalogue=catalogue, as_of_day=as_of_day
            ):
                production_stream.write(
                    json.dumps(
                        _production_json(observation.production),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                )
                production_stream.write("\n")
                labels_stream.write(
                    json.dumps(
                        _label_json(observation),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                )
                labels_stream.write("\n")
                difficulty_counts[observation.label.difficulty] += 1
            _fsync_text(production_stream)
            _fsync_text(labels_stream)
    return dict(difficulty_counts)


def _parse_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be timestamp text")
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{field_name} must be UTC")
    return parsed


def iter_production_artifact(path: Path) -> Iterator[ProductionRecord]:
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"production artifact line {line_number} is not an object")
            occurred = value.get("occurred_at")
            yield ProductionRecord(
                raw_title=value["raw_title"],
                raw_price_text=value["raw_price_text"],
                raw_price=Decimal(value["raw_price"]),
                url=value["url"],
                seller_handle=value["seller_handle"],
                fetched_at=_parse_utc(value["fetched_at"], "fetched_at"),
                occurred_at=(
                    _parse_utc(occurred, "occurred_at") if occurred is not None else None
                ),
                external_id=value["external_id"],
                payload=value["payload"],
            )


def read_labels(path: Path, *, expected_count: int, catalogue_sha: str, as_of_day: date):
    with path.open(encoding="utf-8") as stream:
        header = json.loads(next(stream))
        expected_header = {
            "record_type": "header",
            "schema_version": "benchmark_labels.v1",
            "generator_version": GENERATOR_VERSION,
            "master_seed": MASTER_SEED,
            "catalogue_sha256": catalogue_sha,
            "as_of_day": as_of_day.isoformat(),
            "observation_count": expected_count,
        }
        if header != expected_header:
            raise ValueError("label sidecar header differs from the frozen identity")
        labels = [json.loads(line) for line in stream]
    if len(labels) != expected_count:
        raise ValueError("label sidecar count differs from the requested observations")
    return labels


def database_snapshot() -> dict[str, object]:
    from django.db import connection

    from catalogue.models import Sku, SkuAlias
    from ingestion.models import RawListing
    from listings.models import Listing
    from pricing.models import DealFlag, PricePoint
    from sources.models import Source

    counts = {
        "source": Source.objects.count(),
        "sku": Sku.objects.count(),
        "sku_alias": SkuAlias.objects.count(),
        "raw_listing": RawListing.objects.count(),
        "listing": Listing.objects.count(),
        "price_point": PricePoint.objects.count(),
        "deal_flag": DealFlag.objects.count(),
        "unresolved": Listing.objects.filter(sku_id__isnull=True).count(),
        "review_required": Listing.objects.filter(
            sku_id__isnull=True, reviewed_unresolved_at__isnull=True
        ).count(),
    }
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        database_bytes = int(cursor.fetchone()[0])
        relation_sizes = {}
        for label, relation in APP_RELATIONS.items():
            cursor.execute("SELECT pg_total_relation_size(%s::regclass)", [relation])
            relation_sizes[label] = _value_and_human(int(cursor.fetchone()[0]))
    return {
        "captured_at_utc": _utc_now(),
        "counts": counts,
        "database_size": _value_and_human(database_bytes),
        "core_relation_total_sizes": relation_sizes,
    }


def _assert_fresh_database() -> dict[str, object]:
    from django.db import connection

    initial = database_snapshot()
    non_seed_counts = {
        key: value for key, value in initial["counts"].items() if key != "source"
    }
    if any(non_seed_counts.values()):
        raise ValueError("benchmark database already contains pipeline evidence")
    with connection.cursor() as cursor:
        if connection.vendor != "postgresql":
            raise ValueError("BENCH_003 requires PostgreSQL")
        cursor.execute("SHOW server_version")
        version = cursor.fetchone()[0]
    if not str(version).startswith("16."):
        raise ValueError(f"BENCH_003 requires PostgreSQL 16, found {version}")
    return {"snapshot": initial, "postgresql_version": str(version)}


def _run_command(arguments: list[str], *, timeout_seconds: Decimal):
    start = time.monotonic_ns()
    try:
        completed = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=float(timeout_seconds),
        )
    except subprocess.TimeoutExpired as error:
        duration = _decimal_seconds(time.monotonic_ns() - start)
        raise TimeoutError(
            f"command exceeded remaining full-run timeout after {duration}s"
        ) from error
    duration = _decimal_seconds(time.monotonic_ns() - start)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            f"command exited {completed.returncode}: {detail[-4000:]}"
        )
    return duration, completed.stdout, completed.stderr


def _remaining_seconds(deadline_ns: int) -> Decimal:
    remaining_ns = deadline_ns - time.monotonic_ns()
    if remaining_ns <= 0:
        raise TimeoutError("frozen full-run timeout was exceeded")
    return Decimal(remaining_ns) / Decimal(1_000_000_000)


def _base_manifest(args, catalogue) -> dict[str, object]:
    machine = _machine_context(args.machine_context_json)
    stages = {
        name: stage("not_attempted", explanation="run has not reached this stage")
        for name in STAGE_NAMES
    }
    return {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "release_sha": RELEASE_SHA,
        "contract_version": CONTRACT_VERSION,
        "implementation_sha": args.implementation_sha,
        "implementation_state": {
            "value": args.implementation_state,
            "explanation": args.implementation_state_detail,
        },
        "generator_version": GENERATOR_VERSION,
        "master_seed": MASTER_SEED,
        "observation_count": args.observation_count,
        "catalogue_sha256": catalogue.sha256,
        "catalogue_sku_count": len(catalogue.skus),
        "catalogue_category_distribution": dict(CATEGORY_COUNTS),
        "difficulty_distribution": {
            key: args.observation_count // 4 + (index < args.observation_count % 4)
            for index, key in enumerate("ABCD")
        },
        "manila_as_of_day": args.as_of_day.isoformat(),
        "python_version": platform.python_version(),
        "postgresql_version": unavailable("database preflight has not completed"),
        "postgresql_image": {
            "image": args.postgresql_image,
            "immutable_identity": (
                args.postgresql_image_identity
                if args.postgresql_image_identity
                else unavailable("caller did not supply an inspected immutable image identity")
            ),
        },
        "docker_version": (
            args.docker_version
            if args.docker_version
            else unavailable("Docker CLI is outside the application container")
        ),
        "compose_version": (
            args.compose_version
            if args.compose_version
            else unavailable("Compose CLI is outside the application container")
        ),
        **machine,
        "repetition": args.repetition,
        "run_started_at_utc": _utc_now(),
        "run_ended_at_utc": None,
        "run_state": "not_attempted",
        "failure_details": [],
        "preflight": None,
        "stages": stages,
        "timings": {
            "generation_seconds": None,
            "benchmark_raw_load_seconds": None,
            "resolve_listings_seconds": None,
            "price_listings_seconds": None,
            "production_processing_seconds": None,
            "pipeline_throughput_observations_per_second": None,
            "pipeline_throughput_processed_count": args.observation_count,
        },
        "initial_snapshot": None,
        "pre_processing_snapshot": None,
        "final_snapshot": None,
        "resolution_quality": None,
        "null_explanations": {},
        "artifacts": {
            "production_dataset": str(args.artifact_dir / "production.ndjson"),
            "external_label_sidecar": str(args.artifact_dir / "labels.ndjson"),
            "manifest": str(args.manifest),
        },
        "scope_notes": [
            "Controlled labelled synthetic benchmark; not production or real-world accuracy.",
            "benchmark_raw_load is fixture loading, not production ingestion.",
            "API measurement is deferred because authenticated concurrent connection-reuse machinery is BENCH_004 scope.",
            "Backup, restore, and scaled recovery verification are outside BENCH_003 scope.",
        ],
    }


def _refresh_null_explanations(document: dict[str, object]) -> None:
    run_state = document["run_state"]
    explanation = f"unavailable because the run ended with state {run_state}"
    values = document["null_explanations"]
    values.clear()
    for field in (
        "initial_snapshot",
        "pre_processing_snapshot",
        "final_snapshot",
        "resolution_quality",
    ):
        if document[field] is None:
            values[field] = explanation
    for field, value in document["timings"].items():
        if value is None:
            if field == "pipeline_throughput_observations_per_second" and document["timings"].get(
                "production_processing_seconds"
            ) == "0":
                values[f"timings.{field}"] = "undefined because production duration was zero"
            else:
                values[f"timings.{field}"] = explanation


def run(args, *, preflight_now_utc: datetime | None = None) -> dict[str, object]:
    catalogue = load_catalogue(args.catalogue)
    if catalogue.sha256 != CATALOGUE_SHA256:
        raise ValueError("catalogue bytes differ from the owner-approved fixture")
    document = _base_manifest(args, catalogue)
    document["stages"]["api_workload"] = stage(
        "not_attempted",
        explanation="deferred to BENCH_004; frozen authenticated concurrency workload needs isolated machinery",
    )
    for name in ("backup", "restore", "verification"):
        document["stages"][name] = stage(
            "not_attempted", explanation="outside the owner-approved BENCH_003 scope"
        )

    preflight_started = time.monotonic_ns()
    preflight = resource_preflight(
        artifact_dir=args.artifact_dir,
        observation_count=args.observation_count,
        docker_memory_bytes=args.docker_memory_bytes,
        docker_memory_source=args.docker_memory_source,
        now_utc=preflight_now_utc,
    )
    document["preflight"] = preflight
    preflight_duration = _decimal_seconds(time.monotonic_ns() - preflight_started)
    if not preflight["passed"]:
        detail = "; ".join(preflight["failures"])
        document["stages"]["preflight"] = stage(
            "not_attempted", duration_seconds=preflight_duration, explanation=detail
        )
        document["failure_details"].append(detail)
        document["run_ended_at_utc"] = _utc_now()
        document["stages"]["manifest_validation"] = stage(
            "succeeded", processed_count=1, duration_seconds="0"
        )
        _refresh_null_explanations(document)
        write_manifest(args.manifest, document)
        return document
    document["stages"]["preflight"] = stage(
        "succeeded", duration_seconds=preflight_duration, processed_count=1
    )

    timeout_seconds = preflight["full_run_timeout_seconds"]
    deadline_ns = time.monotonic_ns() + int(timeout_seconds * 1_000_000_000)
    try:
        fresh = _assert_fresh_database()
        document["initial_snapshot"] = fresh["snapshot"]
        document["postgresql_version"] = fresh["postgresql_version"]

        started = time.monotonic_ns()
        install_catalogue(catalogue)
        duration = _decimal_seconds(time.monotonic_ns() - started)
        document["stages"]["catalogue_install"] = stage(
            "succeeded", duration_seconds=duration, processed_count=len(catalogue.skus)
        )
        _remaining_seconds(deadline_ns)

        production_path = args.artifact_dir / "production.ndjson"
        labels_path = args.artifact_dir / "labels.ndjson"
        started = time.monotonic_ns()
        difficulty_counts = write_generation_artifacts(
            production_path=production_path,
            labels_path=labels_path,
            observation_count=args.observation_count,
            catalogue=catalogue,
            as_of_day=args.as_of_day,
        )
        duration = _decimal_seconds(time.monotonic_ns() - started)
        _remaining_seconds(deadline_ns)
        document["difficulty_distribution"] = difficulty_counts
        document["timings"]["generation_seconds"] = duration
        document["stages"]["generation"] = stage(
            "succeeded", duration_seconds=duration, processed_count=args.observation_count
        )

        started = time.monotonic_ns()
        load_result = load_raw_observations(
            observations=iter_production_artifact(production_path), chunk_size=args.chunk_size
        )
        duration = _decimal_seconds(time.monotonic_ns() - started)
        _remaining_seconds(deadline_ns)
        if load_result.loaded_count != args.observation_count:
            raise ValueError("benchmark raw loader count differs from requested observations")
        document["timings"]["benchmark_raw_load_seconds"] = duration
        document["stages"]["benchmark_raw_load"] = stage(
            "succeeded",
            duration_seconds=duration,
            processed_count=load_result.loaded_count,
            details={"timing_label": load_result.timing_label, "source_name": load_result.source_name},
        )
        document["pre_processing_snapshot"] = database_snapshot()

        duration, stdout, stderr = _run_command(
            [sys.executable, "manage.py", "resolve_listings"],
            timeout_seconds=_remaining_seconds(deadline_ns),
        )
        resolved_count = database_snapshot()["counts"]["listing"]
        if resolved_count != args.observation_count:
            raise ValueError("resolve_listings did not derive one Listing per observation")
        document["timings"]["resolve_listings_seconds"] = duration
        document["stages"]["resolve_listings"] = stage(
            "succeeded",
            duration_seconds=duration,
            processed_count=resolved_count,
            details={"stdout": stdout.strip(), "stderr": stderr.strip()},
        )

        duration, stdout, stderr = _run_command(
            [sys.executable, "manage.py", "price_listings", "--day", args.as_of_day.isoformat()],
            timeout_seconds=_remaining_seconds(deadline_ns),
        )
        match = _PRICE_OUTPUT.search(stdout)
        if match is None:
            raise ValueError("price_listings output did not disclose processed counts")
        evaluated = int(match.group("evaluated"))
        document["timings"]["price_listings_seconds"] = duration
        document["stages"]["price_listings"] = stage(
            "succeeded",
            duration_seconds=duration,
            processed_count=evaluated,
            details={
                "snapshot_identities": int(match.group("snapshot")),
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            },
        )

        started = time.monotonic_ns()
        quality_result = extract_resolution_quality_streaming(
            labels_path=labels_path,
            expected_count=args.observation_count,
            catalogue=catalogue,
            as_of_day=args.as_of_day,
            chunk_size=args.chunk_size,
        )
        duration = _decimal_seconds(time.monotonic_ns() - started)
        _remaining_seconds(deadline_ns)
        document["resolution_quality"] = quality_result.quality
        document["final_snapshot"] = database_snapshot()
        document["stages"]["quality_extraction"] = stage(
            "succeeded",
            duration_seconds=duration,
            processed_count=quality_result.processed_count,
        )

        resolve_seconds = Decimal(document["timings"]["resolve_listings_seconds"])
        price_seconds = Decimal(document["timings"]["price_listings_seconds"])
        production_seconds = resolve_seconds + price_seconds
        document["timings"]["production_processing_seconds"] = str(production_seconds)
        document["timings"]["pipeline_throughput_observations_per_second"] = (
            str(Decimal(args.observation_count) / production_seconds)
            if production_seconds != 0
            else None
        )
        document["run_state"] = "succeeded"
    except TimeoutError as error:
        active = next(
            name
            for name in (
                "catalogue_install",
                "generation",
                "benchmark_raw_load",
                "resolve_listings",
                "price_listings",
                "quality_extraction",
            )
            if document["stages"][name]["status"] == "not_attempted"
        )
        document["stages"][active] = stage("timed_out", failure_detail=str(error))
        document["failure_details"].append(str(error))
        document["run_state"] = "timed_out"
    except Exception as error:
        active = next(
            (
                name
                for name in (
                    "catalogue_install",
                    "generation",
                    "benchmark_raw_load",
                    "resolve_listings",
                    "price_listings",
                    "quality_extraction",
                )
                if document["stages"][name]["status"] == "not_attempted"
            ),
            "manifest_validation",
        )
        if document["stages"][active]["status"] == "not_attempted":
            document["stages"][active] = stage("failed", failure_detail=str(error))
        document["failure_details"].append(f"{type(error).__name__}: {error}")
        document["run_state"] = "failed"
    finally:
        document["run_ended_at_utc"] = _utc_now()

    validation_started = time.monotonic_ns()
    try:
        document["stages"]["manifest_validation"] = stage(
            "succeeded", duration_seconds="0", processed_count=1
        )
        _refresh_null_explanations(document)
        validate_manifest(document)
        document["stages"]["manifest_validation"]["duration_seconds"] = _decimal_seconds(
            time.monotonic_ns() - validation_started
        )
        write_manifest(args.manifest, document)
    except Exception as error:
        document["stages"]["manifest_validation"] = stage(
            "failed",
            duration_seconds=_decimal_seconds(time.monotonic_ns() - validation_started),
            failure_detail=str(error),
        )
        raise
    return document


def _arguments(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation-count", type=int, required=True)
    parser.add_argument("--as-of-day", type=date.fromisoformat, required=True)
    parser.add_argument("--repetition", type=int, default=1)
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=Path("benchmarks/fixtures/catalogue_v1.json"),
    )
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--implementation-state", choices=("clean", "dirty"), required=True)
    parser.add_argument("--implementation-state-detail", required=True)
    parser.add_argument("--postgresql-image", default="postgres:16.14-bookworm")
    parser.add_argument("--postgresql-image-identity")
    parser.add_argument("--docker-memory-bytes", type=int, required=True)
    parser.add_argument("--docker-memory-source", required=True)
    parser.add_argument("--docker-version")
    parser.add_argument("--compose-version")
    parser.add_argument(
        "--machine-context-json",
        type=Path,
        help="optional host-captured machine context; container-visible context is used otherwise",
    )
    args = parser.parse_args(argv)
    if args.observation_count <= 0:
        parser.error("--observation-count must be positive")
    if args.repetition <= 0:
        parser.error("--repetition must be positive")
    if args.chunk_size <= 0:
        parser.error("--chunk-size must be positive")
    if args.docker_memory_bytes < 0:
        parser.error("--docker-memory-bytes cannot be negative")
    if not args.artifact_dir.is_dir():
        parser.error("--artifact-dir must already exist")
    if args.manifest.parent != args.artifact_dir:
        parser.error("--manifest must be directly inside --artifact-dir")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    document = run(args)
    print(json.dumps({"run_state": document["run_state"], "manifest": str(args.manifest)}))
    return 0 if document["run_state"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
