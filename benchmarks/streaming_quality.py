"""Bounded-memory BENCH_003 resolution-quality extraction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

from django.db import connection, transaction

from benchmarks.catalogue import CatalogueValue
from benchmarks.metrics import _COUNT_FIELDS, _rates, production_locator_fingerprint


@dataclass(frozen=True)
class StreamingQualityResult:
    quality: dict[str, object]
    processed_count: int


def _empty_counts() -> dict[str, int]:
    return {field: 0 for field in _COUNT_FIELDS}


class _QualityAccumulator:
    def __init__(self) -> None:
        self.aggregate = _empty_counts()
        self.by_difficulty = {difficulty: _empty_counts() for difficulty in "ABCD"}
        self.observation_count = 0
        self.difficulty_counts = {difficulty: 0 for difficulty in "ABCD"}

    def add(
        self,
        *,
        difficulty: str,
        expected_sku_key: str | None,
        returned_sku_key: str | None,
        resolution_method: str,
        review_required: bool,
    ) -> None:
        if difficulty not in self.by_difficulty:
            raise ValueError("difficulty must be one of A, B, C, or D")
        self.observation_count += 1
        self.difficulty_counts[difficulty] += 1
        for counts in (self.aggregate, self.by_difficulty[difficulty]):
            self._add_to_counts(
                counts=counts,
                difficulty=difficulty,
                expected_sku_key=expected_sku_key,
                returned_sku_key=returned_sku_key,
                resolution_method=resolution_method,
                review_required=review_required,
            )

    @staticmethod
    def _add_to_counts(
        *,
        counts: dict[str, int],
        difficulty: str,
        expected_sku_key: str | None,
        returned_sku_key: str | None,
        resolution_method: str,
        review_required: bool,
    ) -> None:
        ambiguous = difficulty == "D"
        eligible = not ambiguous
        if eligible:
            counts["eligible_observation_count"] += 1
        else:
            counts["ambiguous_observation_count"] += 1

        automatic = (
            returned_sku_key is not None and resolution_method != "human_confirmed"
        )
        if automatic:
            counts["automatic_resolution_count_all"] += 1
            if eligible:
                counts["automatic_resolution_count_eligible"] += 1
        correct_automatic = (
            automatic
            and eligible
            and returned_sku_key == expected_sku_key
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
        if review_required:
            counts["review_required_count"] += 1

    def result(self) -> dict[str, object]:
        return {
            "schema_version": "resolution_quality.v1",
            "counts": self.aggregate,
            "rates": _rates(self.aggregate, self.observation_count),
            "by_difficulty": {
                difficulty: {
                    "counts": self.by_difficulty[difficulty],
                    "rates": _rates(
                        self.by_difficulty[difficulty],
                        self.difficulty_counts[difficulty],
                    ),
                }
                for difficulty in "ABCD"
            },
        }


def _expected_header(
    *, expected_count: int, catalogue_sha: str, as_of_day: date
) -> dict[str, object]:
    from benchmarks.generator import GENERATOR_VERSION, MASTER_SEED

    return {
        "record_type": "header",
        "schema_version": "benchmark_labels.v1",
        "generator_version": GENERATOR_VERSION,
        "master_seed": MASTER_SEED,
        "catalogue_sha256": catalogue_sha,
        "as_of_day": as_of_day.isoformat(),
        "observation_count": expected_count,
    }


def _parse_label(line: str, *, line_number: int) -> Mapping[str, object]:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as error:
        raise ValueError(f"label sidecar line {line_number} is malformed JSON") from error
    if not isinstance(value, Mapping):
        raise ValueError(f"label sidecar line {line_number} must be an object")
    if value.get("record_type") != "observation":
        raise ValueError(f"label sidecar line {line_number} is not an observation")
    if not isinstance(value.get("observation_index"), int):
        raise ValueError(f"label sidecar line {line_number} has an invalid observation_index")
    if not isinstance(value.get("observation_key"), str):
        raise ValueError("every label must have an observation_key string")
    if not isinstance(value.get("production_fingerprint"), str):
        raise ValueError("every label must have a production_fingerprint string")
    if value.get("difficulty") not in {"A", "B", "C", "D"}:
        raise ValueError("difficulty must be one of A, B, C, or D")
    expected_sku_key = value.get("expected_sku_key")
    if expected_sku_key is not None and not isinstance(expected_sku_key, str):
        raise ValueError(f"label sidecar line {line_number} has an invalid expected_sku_key")
    candidate_sku_keys = value.get("candidate_sku_keys")
    if not isinstance(candidate_sku_keys, list) or any(
        not isinstance(key, str) for key in candidate_sku_keys
    ):
        raise ValueError(f"label sidecar line {line_number} has invalid candidate_sku_keys")
    transformations = value.get("transformations")
    if not isinstance(transformations, list) or any(
        not isinstance(item, str) for item in transformations
    ):
        raise ValueError(f"label sidecar line {line_number} has invalid transformations")
    if not isinstance(value.get("generation_digest"), str):
        raise ValueError(f"label sidecar line {line_number} has an invalid generation_digest")
    return value


def _copy_labels(
    *,
    labels_path: Path,
    expected_count: int,
    catalogue_sha: str,
    as_of_day: date,
) -> int:
    with labels_path.open(encoding="utf-8") as stream:
        header_line = stream.readline()
        if not header_line:
            raise ValueError("label sidecar is empty")
        try:
            header = json.loads(header_line)
        except json.JSONDecodeError as error:
            raise ValueError("label sidecar header is malformed JSON") from error
        if header != _expected_header(
            expected_count=expected_count,
            catalogue_sha=catalogue_sha,
            as_of_day=as_of_day,
        ):
            raise ValueError("label sidecar header differs from the frozen identity")

        count = 0
        with connection.cursor() as django_cursor:
            with django_cursor.cursor.copy(
                "COPY bench003_quality_labels "
                "(ordinal, observation_key, production_fingerprint, difficulty, expected_sku_key) "
                "FROM STDIN"
            ) as copy:
                for line_number, line in enumerate(stream, start=2):
                    label = _parse_label(line, line_number=line_number)
                    copy.write_row(
                        (
                            count,
                            label["observation_key"],
                            label["production_fingerprint"],
                            label["difficulty"],
                            label.get("expected_sku_key"),
                        )
                    )
                    count += 1
        if count != expected_count:
            raise ValueError(
                "label sidecar record count differs from the requested observations"
            )
        return count


def _first_duplicate(column: str) -> str | None:
    if column not in {"observation_key", "production_fingerprint"}:
        raise ValueError("unsupported duplicate-check column")
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {column} FROM bench003_quality_labels "
            f"GROUP BY {column} HAVING COUNT(*) > 1 LIMIT 1"
        )
        row = cursor.fetchone()
    return None if row is None else str(row[0])


def _copy_persisted_outputs(
    *, catalogue: CatalogueValue, chunk_size: int
) -> int:
    from ingestion.models import RawListing

    natural_key_by_identity = {
        (sku.brand, sku.model, sku.variant): sku.natural_key
        for sku in catalogue.skus
    }
    if len(natural_key_by_identity) != len(catalogue.skus):
        raise ValueError("catalogue identities must map one-to-one")

    count = 0
    last_pk = 0
    while True:
        queryset = (
            RawListing.objects.filter(source__name="manual_capture", pk__gt=last_pk)
            .order_by("pk")
            .values_list(
                "pk",
                "source__name",
                "external_id",
                "fetched_at",
                "listing__pk",
                "listing__sku_id",
                "listing__sku__brand",
                "listing__sku__model",
                "listing__sku__variant",
                "listing__resolution_method",
                "listing__reviewed_unresolved_at",
            )[:chunk_size]
        )
        rows = list(queryset.iterator(chunk_size=chunk_size))
        if not rows:
            break

        output_rows = []
        for (
            raw_pk,
            source_name,
            external_id,
            fetched_at,
            listing_pk,
            sku_id,
            sku_brand,
            sku_model,
            sku_variant,
            resolution_method,
            reviewed_unresolved_at,
        ) in rows:
            if external_id is None:
                raise ValueError("persisted benchmark row has no external identity")
            if listing_pk is None:
                raise ValueError("persisted raw evidence has no derived Listing")
            returned_sku_key = None
            if sku_id is not None:
                identity = (sku_brand, sku_model, sku_variant)
                try:
                    returned_sku_key = natural_key_by_identity[identity]
                except KeyError as error:
                    raise ValueError(
                        "persisted resolved SKU is outside the frozen catalogue"
                    ) from error
            fingerprint = production_locator_fingerprint(
                source_name=source_name,
                external_id=external_id,
                fetched_at=fetched_at,
            )
            output_rows.append(
                (
                    fingerprint,
                    returned_sku_key,
                    resolution_method,
                    sku_id is None and reviewed_unresolved_at is None,
                )
            )
            last_pk = raw_pk

        with connection.cursor() as django_cursor:
            with django_cursor.cursor.copy(
                "COPY bench003_quality_outputs "
                "(production_fingerprint, returned_sku_key, resolution_method, review_required) "
                "FROM STDIN"
            ) as copy:
                for output_row in output_rows:
                    copy.write_row(output_row)
        count += len(output_rows)
    return count


def _prepare_correlation_tables() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE UNIQUE INDEX bench003_quality_labels_ordinal "
            "ON bench003_quality_labels (ordinal)"
        )
        cursor.execute(
            "CREATE UNIQUE INDEX bench003_quality_labels_key "
            "ON bench003_quality_labels (observation_key)"
        )
        cursor.execute(
            "CREATE UNIQUE INDEX bench003_quality_labels_fingerprint "
            "ON bench003_quality_labels (production_fingerprint)"
        )
        cursor.execute(
            "CREATE UNIQUE INDEX bench003_quality_outputs_fingerprint "
            "ON bench003_quality_outputs (production_fingerprint)"
        )
        # PostgreSQL needs current statistics to avoid a quadratic anti-join plan.
        cursor.execute("ANALYZE bench003_quality_labels")
        cursor.execute("ANALYZE bench003_quality_outputs")


def _validate_correlations(*, expected_count: int, persisted_count: int) -> None:
    duplicate_key = _first_duplicate("observation_key")
    if duplicate_key is not None:
        raise ValueError(f"duplicate label observation_key: {duplicate_key}")
    duplicate_fingerprint = _first_duplicate("production_fingerprint")
    if duplicate_fingerprint is not None:
        raise ValueError(
            f"duplicate label production_fingerprint: {duplicate_fingerprint}"
        )

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT production_fingerprint FROM bench003_quality_outputs "
            "GROUP BY production_fingerprint HAVING COUNT(*) > 1 LIMIT 1"
        )
        duplicate_output = cursor.fetchone()
        if duplicate_output is not None:
            raise ValueError("persisted production fingerprints must be unique")

    _prepare_correlation_tables()

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM bench003_quality_labels AS labels "
            "LEFT JOIN bench003_quality_outputs AS outputs USING (production_fingerprint) "
            "WHERE outputs.production_fingerprint IS NULL LIMIT 1"
        )
        if cursor.fetchone() is not None:
            raise ValueError("sidecar fingerprint has no persisted production correlation")

        cursor.execute(
            "SELECT 1 FROM bench003_quality_outputs AS outputs "
            "LEFT JOIN bench003_quality_labels AS labels USING (production_fingerprint) "
            "WHERE labels.production_fingerprint IS NULL LIMIT 1"
        )
        if cursor.fetchone() is not None:
            raise ValueError("persisted production fingerprint has no sidecar correlation")

    if persisted_count != expected_count:
        raise ValueError("sidecar and persisted production correlations differ")


def _accumulate_quality(*, chunk_size: int) -> StreamingQualityResult:
    accumulator = _QualityAccumulator()
    raw_connection = connection.connection
    if raw_connection is None:
        raise RuntimeError("database connection was not established")
    with raw_connection.cursor(name="bench003_quality_join") as cursor:
        cursor.itersize = chunk_size
        cursor.execute(
            "SELECT labels.difficulty, labels.expected_sku_key, "
            "outputs.returned_sku_key, outputs.resolution_method, outputs.review_required "
            "FROM bench003_quality_labels AS labels "
            "JOIN bench003_quality_outputs AS outputs USING (production_fingerprint) "
            "ORDER BY labels.ordinal"
        )
        while True:
            rows = cursor.fetchmany(chunk_size)
            if not rows:
                break
            for (
                difficulty,
                expected_sku_key,
                returned_sku_key,
                resolution_method,
                review_required,
            ) in rows:
                accumulator.add(
                    difficulty=difficulty,
                    expected_sku_key=expected_sku_key,
                    returned_sku_key=returned_sku_key,
                    resolution_method=resolution_method,
                    review_required=review_required,
                )
    return StreamingQualityResult(
        quality=accumulator.result(),
        processed_count=accumulator.observation_count,
    )


def extract_resolution_quality_streaming(
    *,
    labels_path: Path,
    expected_count: int,
    catalogue: CatalogueValue,
    as_of_day: date,
    chunk_size: int = 1000,
) -> StreamingQualityResult:
    """Validate, correlate, and score BENCH_003 evidence with bounded Python memory."""
    if chunk_size <= 0:
        raise ValueError("quality extraction chunk_size must be positive")
    if connection.vendor != "postgresql":
        raise ValueError("BENCH_003 quality extraction requires PostgreSQL")

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TEMPORARY TABLE bench003_quality_labels ("
                "ordinal bigint NOT NULL, "
                "observation_key text NOT NULL, "
                "production_fingerprint text NOT NULL, "
                "difficulty text NOT NULL, "
                "expected_sku_key text NULL"
                ") ON COMMIT DROP"
            )
            cursor.execute(
                "CREATE TEMPORARY TABLE bench003_quality_outputs ("
                "production_fingerprint text NOT NULL, "
                "returned_sku_key text NULL, "
                "resolution_method text NOT NULL, "
                "review_required boolean NOT NULL"
                ") ON COMMIT DROP"
            )

        label_count = _copy_labels(
            labels_path=labels_path,
            expected_count=expected_count,
            catalogue_sha=catalogue.sha256,
            as_of_day=as_of_day,
        )
        persisted_count = _copy_persisted_outputs(
            catalogue=catalogue,
            chunk_size=chunk_size,
        )
        _validate_correlations(
            expected_count=label_count,
            persisted_count=persisted_count,
        )
        result = _accumulate_quality(chunk_size=chunk_size)
        if result.processed_count != expected_count:
            raise ValueError("quality extraction count differs from requested observations")
        return result
