"""Machine-readable BENCH_003 result manifests."""

from __future__ import annotations

import json
import os
import re
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping


ARTIFACT_SCHEMA_VERSION = "pricewatchph_pipeline_benchmark.v1"
CONTRACT_VERSION = "1.0.0"
RELEASE_SHA = "ab0646e9fcb4c3c5d1f567a46848a3a98dbda9a5"
STAGE_NAMES = (
    "preflight",
    "catalogue_install",
    "generation",
    "benchmark_raw_load",
    "resolve_listings",
    "price_listings",
    "quality_extraction",
    "api_workload",
    "backup",
    "restore",
    "verification",
    "manifest_validation",
)
TERMINAL_STATUSES = {"succeeded", "failed", "timed_out", "not_attempted"}
_HEX_SHA = re.compile(r"[0-9a-f]{40,64}\Z")


def unavailable(explanation: str) -> dict[str, object]:
    """Represent an unavailable value without replacing it with zero."""
    if not explanation:
        raise ValueError("unavailable values require an explanation")
    return {"value": None, "explanation": explanation}


def stage(
    status: str,
    *,
    duration_seconds: str | None = None,
    processed_count: int | None = None,
    failure_detail: str | None = None,
    explanation: str | None = None,
    details: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"invalid stage status: {status}")
    if duration_seconds is not None:
        _non_negative_decimal(duration_seconds, "stage duration")
    if processed_count is not None and processed_count < 0:
        raise ValueError("stage processed_count cannot be negative")
    if status == "failed" and not failure_detail:
        raise ValueError("failed stages require failure_detail")
    if status == "timed_out" and not failure_detail:
        raise ValueError("timed_out stages require failure_detail")
    if status == "not_attempted" and not explanation:
        raise ValueError("not_attempted stages require an explanation")
    return {
        "status": status,
        "duration_seconds": duration_seconds,
        "processed_count": processed_count,
        "failure_detail": failure_detail,
        "explanation": explanation,
        "details": dict(details or {}),
    }


def _non_negative_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be Decimal text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be Decimal text") from error
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return parsed


def validate_manifest(document: Mapping[str, object]) -> None:
    """Reject incomplete or arithmetically inconsistent result evidence."""
    if document.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unexpected artifact schema version")
    if document.get("release_sha") != RELEASE_SHA:
        raise ValueError("unexpected release SHA")
    if document.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("unexpected contract version")
    implementation_sha = document.get("implementation_sha")
    if not isinstance(implementation_sha, str) or not _HEX_SHA.fullmatch(
        implementation_sha
    ):
        raise ValueError("implementation_sha must be a lowercase Git SHA")
    observation_count = document.get("observation_count")
    if (
        isinstance(observation_count, bool)
        or not isinstance(observation_count, int)
        or observation_count <= 0
    ):
        raise ValueError("observation_count must be a positive integer")
    repetition = document.get("repetition")
    if isinstance(repetition, bool) or not isinstance(repetition, int) or repetition <= 0:
        raise ValueError("repetition must be a positive integer")

    stages = document.get("stages")
    if not isinstance(stages, Mapping) or set(stages) != set(STAGE_NAMES):
        raise ValueError("manifest must retain every BENCH_003 stage")
    for name in STAGE_NAMES:
        value = stages[name]
        if not isinstance(value, Mapping):
            raise ValueError(f"stage {name} must be an object")
        status = value.get("status")
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"stage {name} has an invalid status")
        duration = value.get("duration_seconds")
        if duration is not None:
            _non_negative_decimal(duration, f"stage {name} duration")
        if status in {"failed", "timed_out"} and not value.get("failure_detail"):
            raise ValueError(f"stage {name} must retain failure detail")
        if status == "not_attempted" and not value.get("explanation"):
            raise ValueError(f"stage {name} must explain why it was not attempted")

    timings = document.get("timings")
    if not isinstance(timings, Mapping):
        raise ValueError("timings must be an object")
    resolve = timings.get("resolve_listings_seconds")
    pricing = timings.get("price_listings_seconds")
    production = timings.get("production_processing_seconds")
    throughput = timings.get("pipeline_throughput_observations_per_second")
    if resolve is not None or pricing is not None or production is not None:
        if resolve is None or pricing is None or production is None:
            raise ValueError("production timing components must be present together")
        expected = _non_negative_decimal(resolve, "resolve timing") + _non_negative_decimal(
            pricing, "pricing timing"
        )
        if _non_negative_decimal(production, "production timing") != expected:
            raise ValueError("production processing timing is not the exact component sum")
        if expected == 0:
            if throughput is not None:
                raise ValueError("zero-duration throughput must be null")
        else:
            expected_throughput = Decimal(observation_count) / expected
            if not isinstance(throughput, str) or Decimal(throughput) != expected_throughput:
                raise ValueError("pipeline throughput is not exact")
    elif throughput is not None:
        raise ValueError("throughput cannot exist without production timings")

    null_explanations = document.get("null_explanations", {})
    if not isinstance(null_explanations, Mapping):
        raise ValueError("null_explanations must be an object")
    for field in (
        "initial_snapshot",
        "pre_processing_snapshot",
        "final_snapshot",
        "resolution_quality",
    ):
        if document.get(field) is None and not null_explanations.get(field):
            raise ValueError(f"null {field} requires an explanation")
    for field, value in timings.items():
        if value is None and not null_explanations.get(f"timings.{field}"):
            raise ValueError(f"null timing {field} requires an explanation")

    if document.get("run_state") == "succeeded":
        for required in (
            "generation",
            "benchmark_raw_load",
            "resolve_listings",
            "price_listings",
            "quality_extraction",
        ):
            if stages[required].get("status") != "succeeded":
                raise ValueError("a successful run cannot omit a required pipeline stage")
        final = document.get("final_snapshot")
        if not isinstance(final, Mapping):
            raise ValueError("a successful run requires a final snapshot")
        counts = final.get("counts")
        if not isinstance(counts, Mapping) or counts.get("raw_listing") != observation_count:
            raise ValueError("final raw count must equal requested observations")


def write_manifest(path: str | Path, document: Mapping[str, object]) -> None:
    """Validate and atomically durably replace one small JSON manifest."""
    validate_manifest(document)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
        directory_descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
