from __future__ import annotations

import json
from argparse import Namespace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from benchmarks.catalogue import load_catalogue
from benchmarks.generator import iter_observations, write_label_sidecar
from benchmarks.manifest import (
    ARTIFACT_SCHEMA_VERSION,
    CONTRACT_VERSION,
    RELEASE_SHA,
    STAGE_NAMES,
    stage,
    validate_manifest,
)
from benchmarks.run_pipeline_benchmark import (
    CATALOGUE_SHA256,
    _decimal_seconds,
    iter_production_artifact,
    read_labels,
    resource_preflight,
    run,
    write_generation_artifacts,
)


FIXTURE = Path("benchmarks/fixtures/catalogue_v1.json")
AS_OF_DAY = date(2026, 8, 29)


def _minimal_manifest() -> dict[str, object]:
    stages = {
        name: stage("not_attempted", explanation="focused unit fixture")
        for name in STAGE_NAMES
    }
    for name in (
        "generation",
        "benchmark_raw_load",
        "resolve_listings",
        "price_listings",
        "quality_extraction",
    ):
        stages[name] = stage("succeeded", duration_seconds="1", processed_count=4)
    return {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "release_sha": RELEASE_SHA,
        "contract_version": CONTRACT_VERSION,
        "implementation_sha": "a" * 40,
        "observation_count": 4,
        "repetition": 1,
        "run_state": "succeeded",
        "stages": stages,
        "timings": {
            "resolve_listings_seconds": "1.000000001",
            "price_listings_seconds": "2.000000002",
            "production_processing_seconds": "3.000000003",
            "pipeline_throughput_observations_per_second": str(
                Decimal(4) / Decimal("3.000000003")
            ),
        },
        "null_explanations": {},
        "initial_snapshot": {},
        "pre_processing_snapshot": {},
        "resolution_quality": {},
        "final_snapshot": {"counts": {"raw_listing": 4}},
    }


def test_monotonic_nanoseconds_become_exact_decimal_seconds():
    assert _decimal_seconds(3_000_000_003) == "3.000000003"


def test_manifest_rejects_inexact_production_timing_arithmetic():
    manifest = _minimal_manifest()
    validate_manifest(manifest)
    manifest["timings"]["production_processing_seconds"] = "3.000000004"
    with pytest.raises(ValueError, match="exact component sum"):
        validate_manifest(manifest)


def test_preflight_uses_exact_docker_bytes_and_does_not_round_up(tmp_path):
    result = resource_preflight(
        artifact_dir=tmp_path,
        observation_count=10_000,
        docker_memory_bytes=4_094_447_616,
        docker_memory_source="docker info .MemTotal",
        now_utc=datetime(2026, 8, 29, 12, tzinfo=timezone.utc),
    )
    assert result["passed"] is False
    assert result["docker_memory"]["required"]["bytes"] == 4_294_967_296
    assert result["docker_memory"]["observed"]["bytes"] == 4_094_447_616
    assert "Docker memory is below" in result["failures"][0]


def _set_sufficient_test_disk(monkeypatch):
    monkeypatch.setattr(
        "benchmarks.run_pipeline_benchmark.os.statvfs",
        lambda _path: Namespace(f_bavail=30 * 1024**3, f_frsize=1),
    )


def test_day_boundary_preflight_passes_with_more_than_frozen_timeout(
    tmp_path, monkeypatch
):
    _set_sufficient_test_disk(monkeypatch)
    result = resource_preflight(
        artifact_dir=tmp_path,
        observation_count=500_000,
        docker_memory_bytes=4_294_967_296,
        docker_memory_source="focused test",
        now_utc=datetime(2026, 8, 29, 13, 59, 59, tzinfo=timezone.utc),
    )
    assert result["passed"] is True
    assert result["manila_day_boundary"]["seconds_until_next_midnight"] == "7201"


def test_day_boundary_preflight_fails_before_generation(tmp_path, monkeypatch):
    _set_sufficient_test_disk(monkeypatch)
    manifest_path = tmp_path / "result.json"
    args = Namespace(
        observation_count=500_000,
        as_of_day=AS_OF_DAY,
        repetition=1,
        chunk_size=1000,
        artifact_dir=tmp_path,
        manifest=manifest_path,
        catalogue=FIXTURE,
        implementation_sha="a" * 40,
        implementation_state="clean",
        implementation_state_detail="focused unit fixture",
        postgresql_image="postgres:16.14-bookworm",
        postgresql_image_identity=None,
        docker_memory_bytes=4_294_967_296,
        docker_memory_source="focused test",
        docker_version=None,
        compose_version=None,
        machine_context_json=None,
    )
    result = run(
        args,
        preflight_now_utc=datetime(2026, 8, 29, 14, 0, 1, tzinfo=timezone.utc),
    )
    assert result["run_state"] == "not_attempted"
    assert "next Manila midnight" in result["failure_details"][0]
    assert result["stages"]["generation"]["status"] == "not_attempted"
    assert not (tmp_path / "production.ndjson").exists()
    assert not (tmp_path / "labels.ndjson").exists()


def test_day_boundary_preflight_rejects_exact_timeout_boundary(tmp_path, monkeypatch):
    _set_sufficient_test_disk(monkeypatch)
    result = resource_preflight(
        artifact_dir=tmp_path,
        observation_count=500_000,
        docker_memory_bytes=4_294_967_296,
        docker_memory_source="focused test",
        now_utc=datetime(2026, 8, 29, 14, tzinfo=timezone.utc),
    )
    assert result["passed"] is False
    assert result["manila_day_boundary"]["seconds_until_next_midnight"] == "7200"
    assert "next Manila midnight" in result["failures"][-1]


def test_generation_artifacts_preserve_public_sidecar_and_production_values(tmp_path):
    catalogue = load_catalogue(FIXTURE)
    assert catalogue.sha256 == CATALOGUE_SHA256
    production_path = tmp_path / "production.ndjson"
    label_path = tmp_path / "labels.ndjson"
    counts = write_generation_artifacts(
        production_path=production_path,
        labels_path=label_path,
        observation_count=8,
        catalogue=catalogue,
        as_of_day=AS_OF_DAY,
    )
    assert counts == {"A": 2, "B": 2, "C": 2, "D": 2}

    expected_sidecar = tmp_path / "expected-labels.ndjson"
    with expected_sidecar.open("w", encoding="utf-8", newline="\n") as stream:
        write_label_sidecar(
            stream=stream,
            records=iter_observations(count=8, catalogue=catalogue, as_of_day=AS_OF_DAY),
            catalogue_sha256=catalogue.sha256,
            as_of_day=AS_OF_DAY,
        )
    assert label_path.read_bytes() == expected_sidecar.read_bytes()

    actual_production = list(iter_production_artifact(production_path))
    expected_production = [
        observation.production
        for observation in iter_observations(
            count=8, catalogue=catalogue, as_of_day=AS_OF_DAY
        )
    ]
    assert actual_production == expected_production
    labels = read_labels(
        label_path,
        expected_count=8,
        catalogue_sha=catalogue.sha256,
        as_of_day=AS_OF_DAY,
    )
    assert len(labels) == 8
    production_rows = map(json.loads, production_path.read_text().splitlines())
    assert all("expected_sku_key" not in row for row in production_rows)


def test_failed_memory_preflight_writes_not_attempted_manifest_without_data(tmp_path):
    manifest_path = tmp_path / "result.json"
    args = Namespace(
        observation_count=8,
        as_of_day=AS_OF_DAY,
        repetition=1,
        chunk_size=1000,
        artifact_dir=tmp_path,
        manifest=manifest_path,
        catalogue=FIXTURE,
        implementation_sha="a" * 40,
        implementation_state="clean",
        implementation_state_detail="focused unit fixture",
        postgresql_image="postgres:16.14-bookworm",
        postgresql_image_identity=None,
        docker_memory_bytes=4_094_447_616,
        docker_memory_source="docker info .MemTotal",
        docker_version=None,
        compose_version=None,
        machine_context_json=None,
    )
    result = run(args)
    persisted = json.loads(manifest_path.read_text())
    assert result["run_state"] == "not_attempted"
    assert persisted["preflight"]["docker_memory"]["observed"]["bytes"] == 4_094_447_616
    assert persisted["stages"]["generation"]["status"] == "not_attempted"
    assert not (tmp_path / "production.ndjson").exists()
    assert not (tmp_path / "labels.ndjson").exists()
