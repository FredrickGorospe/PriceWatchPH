"""Frozen BENCH_002 acceptance tests.

The implementation-facing tests deliberately fail until BENCH_002 modules and
the owner-reviewable fixture exist. They use only tiny deterministic datasets;
none of their values are portfolio benchmark results.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "tasks" / "BENCH_002_SYNTHETIC_BENCHMARK_DATASET.md"
FIXTURE_PATH = REPO_ROOT / "benchmarks" / "fixtures" / "catalogue_v1.json"

RELEASE_SHA = "ab0646e9fcb4c3c5d1f567a46848a3a98dbda9a5"
BENCH_001_HASHES = {
    REPO_ROOT / "tasks" / "BENCH_001_PORTFOLIO_BENCHMARK_CONTRACT.md":
        "1f7f1a97d89c0ea9e85709c6ff8439ec9228c80ad84c579e80ffc9e1f57f2ece",
    REPO_ROOT / "tests" / "test_bench_001_portfolio_benchmark_contract.py":
        "2f2bbcc3090f104ff1afeda3fb7a4ce37e612d14e66c743523310d6b81d31338",
}
EXPECTED_CATEGORY_COUNTS = {
    "gpu": 30,
    "cpu": 25,
    "ram": 20,
    "mobo": 20,
    "monitor": 15,
    "peripheral": 10,
}
REAL_VENDOR_NAMES = {
    "acer",
    "amd",
    "apple",
    "asus",
    "corsair",
    "dell",
    "gigabyte",
    "hp",
    "intel",
    "kingston",
    "lenovo",
    "logitech",
    "msi",
    "nvidia",
    "razer",
    "samsung",
}
MARKETPLACE_NOISE_TOKENS = {
    "rush",
    "used",
    "swap",
    "issue",
    "box",
    "unit only",
    "gpu only",
}
AS_OF_DAY = date(2026, 8, 29)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_path(path: Path) -> Path:
    assert path.is_file(), f"BENCH_002 implementation artifact is missing: {path}"
    return path


def _module(name: str):
    importlib.invalidate_caches()
    return importlib.import_module(name)


def _fixture_json() -> dict:
    return json.loads(_require_path(FIXTURE_PATH).read_text(encoding="utf-8"))


def _catalogue():
    return _module("benchmarks.catalogue").load_catalogue(FIXTURE_PATH)


def _records(count: int):
    generator = _module("benchmarks.generator")
    return list(
        generator.iter_observations(
            count=count,
            catalogue=_catalogue(),
            as_of_day=AS_OF_DAY,
        )
    )


def _rate(result: dict, name: str):
    return result["rates"][name]


def test_bench_001_artifacts_remain_byte_exact():
    for path, expected_hash in BENCH_001_HASHES.items():
        assert _sha256(path) == expected_hash


def test_bench_002_spec_freezes_scope_and_release_boundary():
    spec = _require_path(SPEC_PATH).read_text(encoding="utf-8")

    assert spec.startswith("# BENCH_002")
    assert RELEASE_SHA in spec
    assert "BENCH_001 is authoritative and immutable" in spec
    assert "No measured portfolio benchmark run" in spec
    assert "10,000" in spec and "must not be generated" in spec
    assert "No production runtime file may change" in spec
    assert "pre-measurement owner review gate" in spec


def test_catalogue_fixture_has_exact_schema_and_composition():
    fixture = _fixture_json()

    assert set(fixture) == {
        "schema_version",
        "fixture_version",
        "catalogue_kind",
        "sku_count",
        "category_counts",
        "alias_policy",
        "skus",
    }
    assert fixture["schema_version"] == "benchmark_catalogue.v1"
    assert fixture["fixture_version"] == "1.0.0"
    assert fixture["catalogue_kind"] == "synthetic_benchmark_only"
    assert fixture["sku_count"] == 120
    assert fixture["category_counts"] == EXPECTED_CATEGORY_COUNTS
    assert len(fixture["skus"]) == 120

    categories = Counter(sku["category"] for sku in fixture["skus"])
    assert categories == EXPECTED_CATEGORY_COUNTS

    natural_keys = [sku["natural_key"] for sku in fixture["skus"]]
    identities = [
        (sku["brand"], sku["model"], sku["variant"])
        for sku in fixture["skus"]
    ]
    assert len(natural_keys) == len(set(natural_keys)) == 120
    assert len(identities) == len(set(identities)) == 120
    assert all(re.fullmatch(r"bench_(gpu|cpu|ram|mobo|monitor|peripheral)_\d{3}", key) for key in natural_keys)

    required_sku_fields = {
        "natural_key",
        "category",
        "brand",
        "model",
        "variant",
        "launch_msrp",
        "launch_date",
        "family_token",
        "ambiguity_group",
        "aliases",
    }
    for sku in fixture["skus"]:
        assert set(sku) == required_sku_fields
        assert sku["brand"].casefold() not in REAL_VENDOR_NAMES
        assert re.fullmatch(r"[0-9]+\.[0-9]{2}", sku["launch_msrp"])
        assert Decimal(sku["launch_msrp"]) > 0
        date.fromisoformat(sku["launch_date"])
        assert isinstance(sku["variant"], str)

    for category in EXPECTED_CATEGORY_COUNTS:
        category_skus = [sku for sku in fixture["skus"] if sku["category"] == category]
        assert any(sku["variant"] == "" for sku in category_skus)
        assert any(sku["variant"] != "" for sku in category_skus)
        assert any(re.search(r"\d", sku["model"]) for sku in category_skus)

    groups = defaultdict(list)
    for sku in fixture["skus"]:
        groups[sku["ambiguity_group"]].append(sku)
    assert len(groups) == 24
    for members in groups.values():
        assert len(members) == 5
        assert len({member["category"] for member in members}) == 1
        assert len({member["family_token"] for member in members}) == 1


def test_catalogue_aliases_are_frozen_unique_seed_evidence():
    from listings.normalisation import normalise_title

    fixture = _fixture_json()
    policy = fixture["alias_policy"]
    assert policy == {
        "aliases_per_sku": 2,
        "source_of_truth": "seed",
        "generated_evaluation_titles_may_be_added": False,
    }

    normalised_aliases = []
    for sku in fixture["skus"]:
        assert len(sku["aliases"]) == 2
        canonical = " ".join(
            value for value in (sku["brand"], sku["model"], sku["variant"]) if value
        )
        assert sku["aliases"][0] == {
            "alias_text": canonical,
            "source_of_truth": "seed",
        }
        assert sku["aliases"][1]["source_of_truth"] == "seed"
        assert normalise_title(sku["aliases"][1]["alias_text"]) != normalise_title(canonical)
        alternate = sku["aliases"][1]["alias_text"].casefold()
        assert all(token not in alternate for token in MARKETPLACE_NOISE_TOKENS)
        normalised_aliases.extend(
            normalise_title(alias["alias_text"])
            for alias in sku["aliases"]
        )

    assert len(normalised_aliases) == 240
    assert len(set(normalised_aliases)) == 240


def test_generator_identity_and_prefix_are_exact():
    generator = _module("benchmarks.generator")
    assert generator.GENERATOR_VERSION == "1.0.0"
    assert generator.MASTER_SEED == 20260829

    first = _records(40)
    repeated = _records(40)
    larger = _records(100)
    assert first == repeated
    assert first == larger[:40]

    alternate_day = list(
        generator.iter_observations(
            count=40,
            catalogue=_catalogue(),
            as_of_day=date(2026, 8, 30),
        )
    )
    assert first != alternate_day


def test_difficulty_distribution_and_labels_are_exact():
    records = _records(100)
    counts = Counter(record.label.difficulty for record in records)
    assert counts == {"A": 25, "B": 25, "C": 25, "D": 25}

    catalogue = _catalogue()
    by_key = {sku.natural_key: sku for sku in catalogue.skus}
    for record in records:
        label = record.label
        assert label.difficulty in {"A", "B", "C", "D"}
        assert label.transformations
        if label.difficulty in {"A", "B", "C"}:
            assert label.expected_sku_key in by_key
            assert label.candidate_sku_keys == (label.expected_sku_key,)
        else:
            assert label.expected_sku_key is None
            assert len(label.candidate_sku_keys) >= 2
            candidates = [by_key[key] for key in label.candidate_sku_keys]
            assert len({candidate.ambiguity_group for candidate in candidates}) == 1
            assert len({candidate.category for candidate in candidates}) == 1


def test_listing_repetition_is_balanced_by_difficulty_and_seller_pool_is_exact():
    generator = _module("benchmarks.generator")
    superblock = _records(40)
    superblock_external_ids = [
        record.production.external_id for record in superblock
    ]
    seen = set()
    repeated_by_difficulty = Counter()
    for record in superblock:
        external_id = record.production.external_id
        if external_id in seen:
            repeated_by_difficulty[record.label.difficulty] += 1
        seen.add(external_id)
    assert len(set(superblock_external_ids)) == 36
    assert repeated_by_difficulty == {"A": 1, "B": 1, "C": 1, "D": 1}

    records = _records(100)
    external_ids = [record.production.external_id for record in records]

    assert len(set(external_ids)) == 90
    seen = set()
    repeated_count = 0
    repeated_by_difficulty = Counter()
    fetched_by_external_id = defaultdict(set)
    for record in records:
        production = record.production
        if production.external_id in seen:
            repeated_count += 1
            repeated_by_difficulty[record.label.difficulty] += 1
        seen.add(production.external_id)
        fetched_by_external_id[production.external_id].add(production.fetched_at)
    assert repeated_count == 10
    repeat_counts = [repeated_by_difficulty[difficulty] for difficulty in "ABCD"]
    assert max(repeat_counts) - min(repeat_counts) <= 1
    assert all(
        len(instants) == external_ids.count(external_id)
        for external_id, instants in fetched_by_external_id.items()
    )

    exact_identities = {
        ("manual_capture", record.production.external_id, record.production.fetched_at)
        for record in records
    }
    assert len(exact_identities) == 100
    assert generator.SELLER_COHORT_SIZE == 4096
    seller_handles = [generator.seller_handle(index) for index in range(4096)]
    assert len(set(seller_handles)) == 4096
    assert all(re.fullmatch(r"benchmark_seller_\d{4}", handle) for handle in seller_handles)
    assert all(record.production.seller_handle in set(seller_handles) for record in records)


def test_money_time_pricing_support_and_alias_freeze():
    fixture_hash_before = _sha256(FIXTURE_PATH)
    catalogue = _catalogue()
    aliases_before = tuple(
        (sku.natural_key, tuple(alias.alias_text for alias in sku.aliases))
        for sku in catalogue.skus
    )
    records = _records(1000)
    aliases_after = tuple(
        (sku.natural_key, tuple(alias.alias_text for alias in sku.aliases))
        for sku in catalogue.skus
    )
    assert _sha256(FIXTURE_PATH) == fixture_hash_before
    assert aliases_after == aliases_before

    manila = ZoneInfo("Asia/Manila")
    observed_days = set()
    for record in records:
        production = record.production
        assert isinstance(production.raw_price, Decimal)
        assert not any(isinstance(value, float) for value in asdict(production).values())
        assert production.fetched_at.utcoffset() == timedelta(0)
        if production.occurred_at is not None:
            assert production.occurred_at.utcoffset() == timedelta(0)
            observed_days.add(production.occurred_at.astimezone(manila).date())
        assert production.payload["stated_price_kind"] == "asking"
        assert production.payload["stated_condition"] in {"new", "like_new", "used", "for_parts"}
    assert any(day < AS_OF_DAY for day in observed_days)
    assert AS_OF_DAY in observed_days

    summary = _module("benchmarks.generator").pricing_support_summary(records)
    assert len(summary) == 6
    assert {entry["category"] for entry in summary} == set(EXPECTED_CATEGORY_COUNTS)
    assert all(entry["condition"] == "used" for entry in summary)
    assert all(entry["historical_asking_count"] >= 5 for entry in summary)
    assert all(entry["current_candidate_count"] >= 1 for entry in summary)


def test_production_records_contain_no_label_fields_or_values():
    records = _records(100)
    allowed_production_fields = {
        "raw_title",
        "raw_price_text",
        "raw_price",
        "url",
        "seller_handle",
        "fetched_at",
        "occurred_at",
        "external_id",
        "payload",
    }
    forbidden_field_names = {
        "expected_sku_key",
        "candidate_sku_keys",
        "difficulty",
        "transformations",
        "generation_digest",
        "observation_key",
    }

    for record in records:
        production = asdict(record.production)
        assert set(production) == allowed_production_fields
        serialised = json.dumps(production, default=str, sort_keys=True)
        assert not forbidden_field_names.intersection(production)
        assert not forbidden_field_names.intersection(production["payload"])
        if record.label.expected_sku_key is not None:
            assert record.label.expected_sku_key not in serialised
        assert all(candidate not in serialised for candidate in record.label.candidate_sku_keys)
        assert record.label.observation_key not in serialised
        assert record.label.generation_digest not in serialised
        assert production["payload"] == {
            "stated_condition": production["payload"]["stated_condition"],
            "stated_price_kind": "asking",
        }
        assert ".invalid/" in production["url"]


def test_production_locator_fingerprint_uses_exact_versioned_canonical_framing():
    metrics = _module("benchmarks.metrics")
    fetched_at = datetime(2026, 8, 29, 1, 2, 3, 456789, tzinfo=timezone.utc)
    canonical_bytes = (
        b'{"external_id":"listing-42",'
        b'"fetched_at":"2026-08-29T01:02:03.456789Z",'
        b'"schema_version":"benchmark_production_locator.v1",'
        b'"source_name":"manual_capture"}'
    )
    expected = hashlib.sha256(canonical_bytes).hexdigest()

    assert metrics.production_locator_fingerprint(
        source_name="manual_capture",
        external_id="listing-42",
        fetched_at=fetched_at,
    ) == expected
    assert metrics.production_locator_fingerprint(
        source_name="manual_capture",
        external_id="listing-42",
        fetched_at=datetime(
            2026,
            8,
            29,
            9,
            2,
            3,
            456789,
            tzinfo=ZoneInfo("Asia/Manila"),
        ),
    ) == expected
    assert metrics.production_locator_fingerprint(
        source_name="manual_capture",
        external_id="listing-42",
        fetched_at=fetched_at + timedelta(seconds=1),
    ) != expected


def test_streaming_label_sidecar_has_exact_external_schema_and_locator_fingerprints():
    generator = _module("benchmarks.generator")
    metrics = _module("benchmarks.metrics")
    catalogue = _catalogue()
    records = _records(8)
    stream = io.StringIO()
    generator.write_label_sidecar(
        stream=stream,
        records=records,
        catalogue_sha256=catalogue.sha256,
        as_of_day=AS_OF_DAY,
    )
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(lines) == 9
    assert lines[0] == {
        "record_type": "header",
        "schema_version": "benchmark_labels.v1",
        "generator_version": "1.0.0",
        "master_seed": 20260829,
        "catalogue_sha256": catalogue.sha256,
        "as_of_day": "2026-08-29",
        "observation_count": 8,
    }
    expected_observation_fields = {
        "record_type",
        "observation_index",
        "observation_key",
        "production_fingerprint",
        "difficulty",
        "expected_sku_key",
        "candidate_sku_keys",
        "transformations",
        "generation_digest",
    }
    for record, line in zip(records, lines[1:], strict=True):
        assert set(line) == expected_observation_fields
        assert line["record_type"] == "observation"
        assert re.fullmatch(r"[0-9a-f]{64}", line["observation_key"])
        assert re.fullmatch(r"[0-9a-f]{64}", line["production_fingerprint"])
        assert re.fullmatch(r"[0-9a-f]{64}", line["generation_digest"])
        assert line["production_fingerprint"] == metrics.production_locator_fingerprint(
            source_name="manual_capture",
            external_id=record.production.external_id,
            fetched_at=record.production.fetched_at,
        )


def test_semantic_audit_sample_is_deterministic_balanced_and_pending():
    audit = _module("benchmarks.audit")
    catalogue = _catalogue()
    records = _records(1000)
    first = audit.select_semantic_audit(
        records=records,
        catalogue=catalogue,
        selector="bench_002_semantic_audit_v1",
    )
    second = audit.select_semantic_audit(
        records=records,
        catalogue=catalogue,
        selector="bench_002_semantic_audit_v1",
    )
    assert first == second
    assert first["review_status"] == "pending_owner_review"
    assert first["selector"] == "bench_002_semantic_audit_v1"
    assert len(first["entries"]) == 100
    assert Counter(entry["difficulty"] for entry in first["entries"]) == {
        "A": 25,
        "B": 25,
        "C": 25,
        "D": 25,
    }
    required_fields = {
        "generated_title",
        "difficulty",
        "expected_sku_key",
        "candidate_sku_keys",
        "transformations",
        "catalogue_context",
    }
    assert all(set(entry) == required_fields for entry in first["entries"])
    assert not any(key in first for key in ("passed", "approved"))


def test_resolution_metrics_match_hand_verified_confusion_cases():
    metrics = _module("benchmarks.metrics")
    labels = [
        {"observation_key": "a", "difficulty": "A", "expected_sku_key": "sku_a", "candidate_sku_keys": ["sku_a"]},
        {"observation_key": "b", "difficulty": "B", "expected_sku_key": "sku_b", "candidate_sku_keys": ["sku_b"]},
        {"observation_key": "c", "difficulty": "C", "expected_sku_key": "sku_c", "candidate_sku_keys": ["sku_c"]},
        {"observation_key": "d1", "difficulty": "D", "expected_sku_key": None, "candidate_sku_keys": ["sku_d1", "sku_d2"]},
        {"observation_key": "d2", "difficulty": "D", "expected_sku_key": None, "candidate_sku_keys": ["sku_d1", "sku_d2"]},
    ]
    outputs = [
        {"observation_key": "a", "returned_sku_key": "sku_a", "resolution_method": "exact_alias", "review_required": False},
        {"observation_key": "b", "returned_sku_key": None, "resolution_method": "unresolved", "review_required": True},
        {"observation_key": "c", "returned_sku_key": "wrong", "resolution_method": "exact_alias", "review_required": False},
        {"observation_key": "d1", "returned_sku_key": None, "resolution_method": "unresolved", "review_required": True},
        {"observation_key": "d2", "returned_sku_key": "sku_d1", "resolution_method": "exact_alias", "review_required": False},
    ]
    result = metrics.evaluate_resolution(labels=labels, outputs=outputs)

    assert result["schema_version"] == "resolution_quality.v1"
    assert result["counts"] == {
        "eligible_observation_count": 3,
        "ambiguous_observation_count": 2,
        "automatic_resolution_count_all": 3,
        "automatic_resolution_count_eligible": 2,
        "correct_automatic_resolution_count": 1,
        "incorrect_automatic_resolution_count": 2,
        "correct_abstention_count": 1,
        "unnecessary_abstention_count": 1,
        "unsafe_forced_resolution_count": 1,
        "review_required_count": 2,
    }
    expected_rates = {
        "resolution_coverage": (2, 3, "0.666667"),
        "correct_resolution_coverage": (1, 3, "0.333333"),
        "resolution_precision": (1, 3, "0.333333"),
        "correct_abstention_rate": (1, 2, "0.500000"),
        "unnecessary_abstention_rate": (1, 3, "0.333333"),
        "unsafe_forced_resolution_rate": (1, 2, "0.500000"),
        "unsafe_resolution_rate": (2, 3, "0.666667"),
        "review_required_rate": (2, 5, "0.400000"),
    }
    for name, (numerator, denominator, value) in expected_rates.items():
        assert _rate(result, name) == {
            "numerator": numerator,
            "denominator": denominator,
            "value": value,
        }
    assert set(result["by_difficulty"]) == {"A", "B", "C", "D"}


def test_resolution_metrics_use_na_and_exclude_human_confirmation_from_automatic():
    metrics = _module("benchmarks.metrics")
    labels = [
        {"observation_key": "a", "difficulty": "A", "expected_sku_key": "sku_a", "candidate_sku_keys": ["sku_a"]},
    ]
    outputs = [
        {"observation_key": "a", "returned_sku_key": "sku_a", "resolution_method": "human_confirmed", "review_required": False},
    ]
    result = metrics.evaluate_resolution(labels=labels, outputs=outputs)

    assert result["counts"]["automatic_resolution_count_all"] == 0
    assert result["counts"]["correct_automatic_resolution_count"] == 0
    assert _rate(result, "resolution_precision") == {
        "numerator": 0,
        "denominator": 0,
        "value": "N/A",
    }
    assert _rate(result, "correct_abstention_rate")["value"] == "N/A"


@pytest.mark.django_db(transaction=True)
def test_raw_loader_and_real_database_output_extraction_preserve_boundaries():
    _require_path(REPO_ROOT / "benchmarks" / "catalogue.py")
    _require_path(REPO_ROOT / "benchmarks" / "generator.py")
    _require_path(REPO_ROOT / "benchmarks" / "loader.py")
    _require_path(REPO_ROOT / "benchmarks" / "metrics.py")

    from django.core.management import call_command

    catalogue_module = _module("benchmarks.catalogue")
    generator = _module("benchmarks.generator")
    loader = _module("benchmarks.loader")
    metrics = _module("benchmarks.metrics")
    from sources.models import Source

    manual_source, _created = Source.objects.get_or_create(
        name="manual_capture",
        defaults={
            "base_url": "",
            "terms_notes": (
                "N/A — no automation involved, no external terms apply to this source"
            ),
            "rate_limit": None,
        },
    )
    assert manual_source.name == "manual_capture"
    assert manual_source.base_url == ""
    assert manual_source.terms_notes == (
        "N/A — no automation involved, no external terms apply to this source"
    )
    assert manual_source.rate_limit is None

    catalogue = catalogue_module.load_catalogue(FIXTURE_PATH)
    catalogue_module.install_catalogue(catalogue)

    from catalogue.models import Sku, SkuAlias
    from ingestion.models import RawListing
    from listings.models import Listing
    from pricing.models import DealFlag, PricePoint

    assert Sku.objects.count() == 120
    assert SkuAlias.objects.count() == 240
    records = _records(40)
    sidecar_stream = io.StringIO()
    generator.write_label_sidecar(
        stream=sidecar_stream,
        records=records,
        catalogue_sha256=catalogue.sha256,
        as_of_day=AS_OF_DAY,
    )
    sidecar_lines = [
        json.loads(line) for line in sidecar_stream.getvalue().splitlines()
    ]
    labels = sidecar_lines[1:]
    assert len(labels) == 40

    aliases_before = SkuAlias.objects.count()
    load_order = records[::2] + records[1::2]
    result = loader.load_raw_observations(
        observations=(record.production for record in load_order),
        chunk_size=10,
    )
    assert result.loaded_count == 40
    assert result.source_name == "manual_capture"
    assert result.timing_label == "benchmark_raw_load"
    assert RawListing.objects.count() == 40
    assert Listing.objects.count() == 0
    assert PricePoint.objects.count() == 0
    assert DealFlag.objects.count() == 0
    assert SkuAlias.objects.count() == aliases_before

    assert not RawListing.objects.exclude(source__name="manual_capture").exists()
    assert not RawListing.objects.exclude(payload__stated_price_kind="asking").exists()
    assert all(re.fullmatch(r"[0-9a-f]{64}", seller) for seller in RawListing.objects.values_list("seller", flat=True))

    call_command("resolve_listings")
    assert Listing.objects.count() == 40

    outputs = metrics.extract_resolution_outputs(
        labels=labels,
        catalogue=catalogue,
    )
    assert len(outputs) == 40
    assert all(
        set(output) == {
            "observation_key",
            "returned_sku_key",
            "resolution_method",
            "review_required",
        }
        for output in outputs
    )
    expected_observation_keys = [
        record.label.observation_key for record in records
    ]
    output_observation_keys = [
        output["observation_key"] for output in outputs
    ]
    assert output_observation_keys == expected_observation_keys
    assert Counter(output_observation_keys) == Counter(expected_observation_keys)
    assert len(set(output_observation_keys)) == 40

    output_by_key = {output["observation_key"]: output for output in outputs}
    natural_key_by_identity = {
        (sku.brand, sku.model, sku.variant): sku.natural_key
        for sku in catalogue.skus
    }
    for record in records:
        raw_listing = RawListing.objects.select_related("source", "listing__sku").get(
            source__name="manual_capture",
            external_id=record.production.external_id,
            fetched_at=record.production.fetched_at,
        )
        listing = raw_listing.listing
        returned_sku_key = None
        if listing.sku is not None:
            returned_sku_key = natural_key_by_identity[
                (listing.sku.brand, listing.sku.model, listing.sku.variant)
            ]
        assert output_by_key[record.label.observation_key] == {
            "observation_key": record.label.observation_key,
            "returned_sku_key": returned_sku_key,
            "resolution_method": listing.resolution_method,
            "review_required": (
                listing.sku_id is None
                and listing.reviewed_unresolved_at is None
            ),
        }

    label_by_key = {
        label["observation_key"]: label for label in labels
    }
    fingerprints_by_external_id = defaultdict(set)
    occurrences_by_external_id = Counter()
    for record in records:
        external_id = record.production.external_id
        occurrences_by_external_id[external_id] += 1
        fingerprints_by_external_id[external_id].add(
            label_by_key[record.label.observation_key]["production_fingerprint"]
        )
    for external_id, occurrence_count in occurrences_by_external_id.items():
        assert len(fingerprints_by_external_id[external_id]) == occurrence_count

    label_field_names = {
        "observation_key",
        "difficulty",
        "expected_sku_key",
        "candidate_sku_keys",
        "transformations",
        "generation_digest",
        "production_fingerprint",
    }
    assert label_field_names.isdisjoint(
        field.name for field in RawListing._meta.fields
    )
    assert all(
        label_field_names.isdisjoint(raw_listing.payload)
        for raw_listing in RawListing.objects.all()
    )

    with pytest.raises(ValueError):
        metrics.extract_resolution_outputs(
            labels=[*labels, labels[0]],
            catalogue=catalogue,
        )
    with pytest.raises(ValueError):
        metrics.extract_resolution_outputs(
            labels=labels[:-1],
            catalogue=catalogue,
        )
    unmatched_label = {
        **labels[0],
        "observation_key": "f" * 64,
        "production_fingerprint": "0" * 64,
    }
    with pytest.raises(ValueError):
        metrics.extract_resolution_outputs(
            labels=[*labels[1:], unmatched_label],
            catalogue=catalogue,
        )

    metric_result = metrics.evaluate_resolution(labels=labels, outputs=outputs)
    assert metric_result["counts"]["eligible_observation_count"] == 30
    assert metric_result["counts"]["ambiguous_observation_count"] == 10
    assert SkuAlias.objects.count() == aliases_before
    assert PricePoint.objects.count() == 0
    assert DealFlag.objects.count() == 0
