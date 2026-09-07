"""Resolution extraction and BENCH_001 quality metrics."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from benchmarks.catalogue import CatalogueValue


_COUNT_FIELDS = (
    "eligible_observation_count",
    "ambiguous_observation_count",
    "automatic_resolution_count_all",
    "automatic_resolution_count_eligible",
    "correct_automatic_resolution_count",
    "incorrect_automatic_resolution_count",
    "correct_abstention_count",
    "unnecessary_abstention_count",
    "unsafe_forced_resolution_count",
    "review_required_count",
)
_RATE_DEFINITIONS = {
    "resolution_coverage": (
        "automatic_resolution_count_eligible",
        "eligible_observation_count",
    ),
    "correct_resolution_coverage": (
        "correct_automatic_resolution_count",
        "eligible_observation_count",
    ),
    "resolution_precision": (
        "correct_automatic_resolution_count",
        "automatic_resolution_count_all",
    ),
    "correct_abstention_rate": (
        "correct_abstention_count",
        "ambiguous_observation_count",
    ),
    "unnecessary_abstention_rate": (
        "unnecessary_abstention_count",
        "eligible_observation_count",
    ),
    "unsafe_forced_resolution_rate": (
        "unsafe_forced_resolution_count",
        "ambiguous_observation_count",
    ),
    "unsafe_resolution_rate": (
        "incorrect_automatic_resolution_count",
        "automatic_resolution_count_all",
    ),
    "review_required_rate": ("review_required_count", "observation_count"),
}


def production_locator_fingerprint(
    *, source_name: str, external_id: str, fetched_at: datetime
) -> str:
    if not isinstance(source_name, str) or not isinstance(external_id, str):
        raise ValueError("source_name and external_id must be strings")
    if not isinstance(fetched_at, datetime) or fetched_at.utcoffset() is None:
        raise ValueError("fetched_at must be timezone-aware")
    utc_value = fetched_at.astimezone(timezone.utc)
    canonical_timestamp = utc_value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    locator = {
        "external_id": external_id,
        "fetched_at": canonical_timestamp,
        "schema_version": "benchmark_production_locator.v1",
        "source_name": source_name,
    }
    canonical_bytes = json.dumps(
        locator,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def extract_resolution_outputs(
    *, labels: Iterable[Mapping[str, object]], catalogue: CatalogueValue
) -> list[dict[str, object]]:
    """Correlate sidecar labels to actual persisted resolver outputs."""
    from django.core.exceptions import ObjectDoesNotExist

    from ingestion.models import RawListing

    materialised_labels = list(labels)
    label_keys = [label.get("observation_key") for label in materialised_labels]
    label_fingerprints = [
        label.get("production_fingerprint") for label in materialised_labels
    ]
    if any(not isinstance(key, str) for key in label_keys):
        raise ValueError("every label must have an observation_key string")
    if any(not isinstance(value, str) for value in label_fingerprints):
        raise ValueError("every label must have a production_fingerprint string")
    if len(set(label_keys)) != len(label_keys):
        raise ValueError("label observation keys must be unique")
    if len(set(label_fingerprints)) != len(label_fingerprints):
        raise ValueError("label production fingerprints must be unique")

    rows_by_fingerprint = {}
    persisted_rows = RawListing.objects.filter(
        source__name="manual_capture"
    ).select_related("source", "listing__sku")
    for raw_listing in persisted_rows:
        if raw_listing.external_id is None:
            raise ValueError("persisted benchmark row has no external identity")
        fingerprint = production_locator_fingerprint(
            source_name=raw_listing.source.name,
            external_id=raw_listing.external_id,
            fetched_at=raw_listing.fetched_at,
        )
        if fingerprint in rows_by_fingerprint:
            raise ValueError("persisted production fingerprints must be unique")
        try:
            listing = raw_listing.listing
        except ObjectDoesNotExist as error:
            raise ValueError("persisted raw evidence has no derived Listing") from error
        rows_by_fingerprint[fingerprint] = listing

    if set(label_fingerprints) != set(rows_by_fingerprint):
        raise ValueError("sidecar and persisted production correlations differ")

    natural_key_by_identity = {
        (sku.brand, sku.model, sku.variant): sku.natural_key
        for sku in catalogue.skus
    }
    if len(natural_key_by_identity) != len(catalogue.skus):
        raise ValueError("catalogue identities must map one-to-one")

    outputs = []
    for label, fingerprint in zip(
        materialised_labels, label_fingerprints, strict=True
    ):
        listing = rows_by_fingerprint[fingerprint]
        returned_sku_key = None
        if listing.sku is not None:
            identity = (listing.sku.brand, listing.sku.model, listing.sku.variant)
            try:
                returned_sku_key = natural_key_by_identity[identity]
            except KeyError as error:
                raise ValueError(
                    "persisted resolved SKU is outside the frozen catalogue"
                ) from error
        outputs.append(
            {
                "observation_key": label["observation_key"],
                "returned_sku_key": returned_sku_key,
                "resolution_method": listing.resolution_method,
                "review_required": (
                    listing.sku_id is None
                    and listing.reviewed_unresolved_at is None
                ),
            }
        )
    return outputs


def _index_unique(
    values: Iterable[Mapping[str, object]], *, input_name: str
) -> dict[str, Mapping[str, object]]:
    indexed = {}
    for value in values:
        key = value.get("observation_key")
        if not isinstance(key, str):
            raise ValueError(f"every {input_name} must have an observation_key string")
        if key in indexed:
            raise ValueError(f"duplicate {input_name} observation_key: {key}")
        indexed[key] = value
    return indexed


def _counts(
    pairs: Iterable[tuple[Mapping[str, object], Mapping[str, object]]]
) -> tuple[dict[str, int], int]:
    counts = {field: 0 for field in _COUNT_FIELDS}
    observation_count = 0
    for label, output in pairs:
        observation_count += 1
        difficulty = label.get("difficulty")
        if not isinstance(difficulty, str) or difficulty not in {"A", "B", "C", "D"}:
            raise ValueError("difficulty must be one of A, B, C, or D")
        ambiguous = difficulty == "D"
        eligible = not ambiguous
        if eligible:
            counts["eligible_observation_count"] += 1
        else:
            counts["ambiguous_observation_count"] += 1

        returned_key = output.get("returned_sku_key")
        method = output.get("resolution_method")
        automatic = returned_key is not None and method != "human_confirmed"
        if automatic:
            counts["automatic_resolution_count_all"] += 1
            if eligible:
                counts["automatic_resolution_count_eligible"] += 1
        correct_automatic = (
            automatic
            and eligible
            and returned_key == label.get("expected_sku_key")
        )
        if correct_automatic:
            counts["correct_automatic_resolution_count"] += 1
        elif automatic:
            counts["incorrect_automatic_resolution_count"] += 1
        if ambiguous and not automatic:
            counts["correct_abstention_count"] += 1
        if eligible and not automatic:
            counts["unnecessary_abstention_count"] += 1
        if ambiguous and automatic:
            counts["unsafe_forced_resolution_count"] += 1
        if output.get("review_required") is True:
            counts["review_required_count"] += 1
    return counts, observation_count


def _rate(numerator: int, denominator: int) -> dict[str, int | str]:
    if denominator == 0:
        value = "N/A"
    else:
        value = str(
            (Decimal(numerator) / Decimal(denominator)).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
        )
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
    }


def _rates(counts: dict[str, int], observation_count: int) -> dict[str, dict]:
    values = {}
    for name, (numerator_field, denominator_field) in _RATE_DEFINITIONS.items():
        numerator = counts[numerator_field]
        denominator = (
            observation_count
            if denominator_field == "observation_count"
            else counts[denominator_field]
        )
        values[name] = _rate(numerator, denominator)
    return values


def evaluate_resolution(
    *,
    labels: Iterable[Mapping[str, object]],
    outputs: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    label_by_key = _index_unique(labels, input_name="label")
    output_by_key = _index_unique(outputs, input_name="output")
    if set(label_by_key) != set(output_by_key):
        raise ValueError("labels and outputs must have identical observation keys")
    pairs = [
        (label, output_by_key[key]) for key, label in label_by_key.items()
    ]
    aggregate_counts, observation_count = _counts(pairs)
    by_difficulty = {}
    for difficulty in "ABCD":
        subset = [pair for pair in pairs if pair[0]["difficulty"] == difficulty]
        subset_counts, subset_count = _counts(subset)
        by_difficulty[difficulty] = {
            "counts": subset_counts,
            "rates": _rates(subset_counts, subset_count),
        }
    return {
        "schema_version": "resolution_quality.v1",
        "counts": aggregate_counts,
        "rates": _rates(aggregate_counts, observation_count),
        "by_difficulty": by_difficulty,
    }
