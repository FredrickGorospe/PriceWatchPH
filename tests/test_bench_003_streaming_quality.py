from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from django.core.management import call_command

from benchmarks.catalogue import install_catalogue, load_catalogue
from benchmarks.generator import iter_observations, write_label_sidecar
from benchmarks.loader import load_raw_observations
from benchmarks.metrics import evaluate_resolution, extract_resolution_outputs
from benchmarks.run_pipeline_benchmark import read_labels
from benchmarks.streaming_quality import (
    _QualityAccumulator,
    extract_resolution_quality_streaming,
)


FIXTURE = Path("benchmarks/fixtures/catalogue_v1.json")
AS_OF_DAY = date(2026, 8, 29)


@dataclass(frozen=True)
class QualityCase:
    catalogue: object
    labels_path: Path
    count: int


def _write_sidecar(path: Path, header: dict, labels: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(header, separators=(",", ":")))
        stream.write("\n")
        for label in labels:
            stream.write(json.dumps(label, separators=(",", ":")))
            stream.write("\n")


def _read_sidecar(path: Path) -> tuple[dict, list[dict]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[0]), [json.loads(line) for line in lines[1:]]


@pytest.fixture
def quality_case(tmp_path) -> QualityCase:
    from sources.models import Source

    catalogue = load_catalogue(FIXTURE)
    Source.objects.get_or_create(
        name="manual_capture",
        defaults={
            "base_url": "",
            "terms_notes": "N/A - focused BENCH_003 synthetic fixture",
            "rate_limit": None,
        },
    )
    install_catalogue(catalogue)
    observations = list(
        iter_observations(count=40, catalogue=catalogue, as_of_day=AS_OF_DAY)
    )
    labels_path = tmp_path / "labels.ndjson"
    with labels_path.open("w", encoding="utf-8", newline="\n") as stream:
        write_label_sidecar(
            stream=stream,
            records=observations,
            catalogue_sha256=catalogue.sha256,
            as_of_day=AS_OF_DAY,
        )

    # Deliberately differ database insertion order from sidecar order.
    load_order = observations[::2] + observations[1::2]
    load_raw_observations(
        observations=(observation.production for observation in load_order),
        chunk_size=7,
    )
    call_command("resolve_listings")
    return QualityCase(catalogue=catalogue, labels_path=labels_path, count=40)


def test_streaming_accumulator_exactly_matches_hand_verified_abcd_metrics():
    labels = [
        {"observation_key": "a", "difficulty": "A", "expected_sku_key": "sku_a"},
        {"observation_key": "b", "difficulty": "B", "expected_sku_key": "sku_b"},
        {"observation_key": "c", "difficulty": "C", "expected_sku_key": "sku_c"},
        {"observation_key": "d1", "difficulty": "D", "expected_sku_key": None},
        {"observation_key": "d2", "difficulty": "D", "expected_sku_key": None},
    ]
    outputs = [
        {"observation_key": "a", "returned_sku_key": "sku_a", "resolution_method": "exact_alias", "review_required": False},
        {"observation_key": "b", "returned_sku_key": None, "resolution_method": "unresolved", "review_required": True},
        {"observation_key": "c", "returned_sku_key": "wrong", "resolution_method": "exact_alias", "review_required": False},
        {"observation_key": "d1", "returned_sku_key": None, "resolution_method": "unresolved", "review_required": True},
        {"observation_key": "d2", "returned_sku_key": "sku_d1", "resolution_method": "exact_alias", "review_required": False},
    ]
    accumulator = _QualityAccumulator()
    for label, output in zip(labels, outputs, strict=True):
        accumulator.add(
            difficulty=label["difficulty"],
            expected_sku_key=label["expected_sku_key"],
            returned_sku_key=output["returned_sku_key"],
            resolution_method=output["resolution_method"],
            review_required=output["review_required"],
        )

    assert accumulator.result() == evaluate_resolution(labels=labels, outputs=outputs)


@pytest.mark.django_db(transaction=True)
def test_streaming_quality_exactly_matches_frozen_extractor_on_fixture(quality_case):
    labels = read_labels(
        quality_case.labels_path,
        expected_count=quality_case.count,
        catalogue_sha=quality_case.catalogue.sha256,
        as_of_day=AS_OF_DAY,
    )
    expected = evaluate_resolution(
        labels=labels,
        outputs=extract_resolution_outputs(
            labels=labels,
            catalogue=quality_case.catalogue,
        ),
    )

    actual = extract_resolution_quality_streaming(
        labels_path=quality_case.labels_path,
        expected_count=quality_case.count,
        catalogue=quality_case.catalogue,
        as_of_day=AS_OF_DAY,
        chunk_size=3,
    )

    assert actual.processed_count == quality_case.count
    assert actual.quality == expected


@pytest.mark.django_db(transaction=True)
def test_streaming_quality_prepares_indexes_and_statistics_before_correlations(
    quality_case, monkeypatch
):
    from django.db.backends.utils import CursorWrapper

    statements = []
    original_execute = CursorWrapper.execute

    def tracking_execute(self, sql, params=None):
        statements.append(" ".join(sql.split()))
        return original_execute(self, sql, params)

    monkeypatch.setattr(CursorWrapper, "execute", tracking_execute)

    extract_resolution_quality_streaming(
        labels_path=quality_case.labels_path,
        expected_count=quality_case.count,
        catalogue=quality_case.catalogue,
        as_of_day=AS_OF_DAY,
        chunk_size=3,
    )

    duplicate_output_index = next(
        index
        for index, sql in enumerate(statements)
        if sql.startswith(
            "SELECT production_fingerprint FROM bench003_quality_outputs GROUP BY"
        )
    )
    index_positions = [
        index
        for index, sql in enumerate(statements)
        if sql.startswith("CREATE UNIQUE INDEX bench003_quality_")
    ]
    analyze_positions = [
        index
        for index, sql in enumerate(statements)
        if sql.startswith("ANALYZE bench003_quality_")
    ]
    correlation_positions = [
        index
        for index, sql in enumerate(statements)
        if sql.startswith("SELECT 1 FROM bench003_quality_")
    ]

    assert len(index_positions) == 4
    assert len(analyze_positions) == 2
    assert len(correlation_positions) == 2
    assert duplicate_output_index < min(index_positions)
    assert max(index_positions) < min(analyze_positions)
    assert max(analyze_positions) < min(correlation_positions)


@pytest.mark.django_db(transaction=True)
def test_streaming_quality_accumulates_in_sidecar_order(quality_case, monkeypatch):
    from benchmarks import streaming_quality

    _, labels = _read_sidecar(quality_case.labels_path)
    expected_order = [
        (label["difficulty"], label.get("expected_sku_key")) for label in labels
    ]
    actual_order = []
    original_add = streaming_quality._QualityAccumulator.add

    def tracking_add(self, **kwargs):
        actual_order.append((kwargs["difficulty"], kwargs["expected_sku_key"]))
        return original_add(self, **kwargs)

    monkeypatch.setattr(streaming_quality._QualityAccumulator, "add", tracking_add)

    extract_resolution_quality_streaming(
        labels_path=quality_case.labels_path,
        expected_count=quality_case.count,
        catalogue=quality_case.catalogue,
        as_of_day=AS_OF_DAY,
        chunk_size=3,
    )

    assert actual_order == expected_order


@pytest.mark.django_db(transaction=True)
def test_streaming_quality_drops_temporary_tables_before_returning(quality_case):
    from django.db import connection

    extract_resolution_quality_streaming(
        labels_path=quality_case.labels_path,
        expected_count=quality_case.count,
        catalogue=quality_case.catalogue,
        as_of_day=AS_OF_DAY,
        chunk_size=3,
    )

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass('pg_temp.bench003_quality_labels'), "
            "to_regclass('pg_temp.bench003_quality_outputs')"
        )
        temporary_relations = cursor.fetchone()

    assert temporary_relations == (None, None)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("observation_key", "duplicate label observation_key"),
        ("production_fingerprint", "duplicate label production_fingerprint"),
    ],
)
def test_streaming_quality_rejects_duplicates_across_chunks(
    quality_case, tmp_path, field, message
):
    header, labels = _read_sidecar(quality_case.labels_path)
    labels[-1][field] = labels[0][field]
    corrupted = tmp_path / f"duplicate-{field}.ndjson"
    _write_sidecar(corrupted, header, labels)

    with pytest.raises(ValueError, match=message):
        extract_resolution_quality_streaming(
            labels_path=corrupted,
            expected_count=quality_case.count,
            catalogue=quality_case.catalogue,
            as_of_day=AS_OF_DAY,
            chunk_size=3,
        )


@pytest.mark.django_db(transaction=True)
def test_streaming_quality_rejects_missing_persisted_row(quality_case, tmp_path):
    header, labels = _read_sidecar(quality_case.labels_path)
    extra = {
        **labels[0],
        "observation_index": quality_case.count,
        "observation_key": "e" * 64,
        "production_fingerprint": "f" * 64,
    }
    labels.append(extra)
    header["observation_count"] += 1
    corrupted = tmp_path / "missing-persisted.ndjson"
    _write_sidecar(corrupted, header, labels)

    with pytest.raises(ValueError, match="no persisted production correlation"):
        extract_resolution_quality_streaming(
            labels_path=corrupted,
            expected_count=quality_case.count + 1,
            catalogue=quality_case.catalogue,
            as_of_day=AS_OF_DAY,
            chunk_size=3,
        )


@pytest.mark.django_db(transaction=True)
def test_streaming_quality_rejects_extra_persisted_row(quality_case, tmp_path):
    header, labels = _read_sidecar(quality_case.labels_path)
    labels.pop()
    header["observation_count"] -= 1
    corrupted = tmp_path / "extra-persisted.ndjson"
    _write_sidecar(corrupted, header, labels)

    with pytest.raises(ValueError, match="no sidecar correlation"):
        extract_resolution_quality_streaming(
            labels_path=corrupted,
            expected_count=quality_case.count - 1,
            catalogue=quality_case.catalogue,
            as_of_day=AS_OF_DAY,
            chunk_size=3,
        )


@pytest.mark.django_db(transaction=True)
def test_streaming_quality_rejects_unmatched_fingerprints(quality_case, tmp_path):
    header, labels = _read_sidecar(quality_case.labels_path)
    labels[5]["production_fingerprint"] = "f" * 64
    corrupted = tmp_path / "unmatched.ndjson"
    _write_sidecar(corrupted, header, labels)

    with pytest.raises(ValueError, match="no persisted production correlation"):
        extract_resolution_quality_streaming(
            labels_path=corrupted,
            expected_count=quality_case.count,
            catalogue=quality_case.catalogue,
            as_of_day=AS_OF_DAY,
            chunk_size=3,
        )


@pytest.mark.django_db(transaction=True)
def test_streaming_quality_rejects_missing_listing(quality_case):
    from listings.models import Listing

    Listing.objects.order_by("pk").first().delete()

    with pytest.raises(ValueError, match="no derived Listing"):
        extract_resolution_quality_streaming(
            labels_path=quality_case.labels_path,
            expected_count=quality_case.count,
            catalogue=quality_case.catalogue,
            as_of_day=AS_OF_DAY,
            chunk_size=3,
        )


@pytest.mark.django_db(transaction=True)
def test_streaming_quality_rejects_out_of_catalogue_sku(quality_case):
    from catalogue.models import Sku
    from listings.models import Listing

    outsider = Sku.objects.create(
        brand="Outside",
        model="Frozen Catalogue",
        variant="",
        category="gpu",
        launch_msrp="1.00",
        launch_date=date(2020, 1, 1),
    )
    Listing.objects.order_by("pk").update(sku=outsider)

    with pytest.raises(ValueError, match="outside the frozen catalogue"):
        extract_resolution_quality_streaming(
            labels_path=quality_case.labels_path,
            expected_count=quality_case.count,
            catalogue=quality_case.catalogue,
            as_of_day=AS_OF_DAY,
            chunk_size=3,
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("corruption", ["malformed", "truncated", "wrong_header"])
def test_streaming_quality_rejects_malformed_or_incomplete_sidecar(
    quality_case, tmp_path, corruption
):
    header, labels = _read_sidecar(quality_case.labels_path)
    corrupted = tmp_path / f"{corruption}.ndjson"
    if corruption == "malformed":
        _write_sidecar(corrupted, header, labels[:-1])
        with corrupted.open("a", encoding="utf-8") as stream:
            stream.write("{not-json}\n")
        message = "malformed JSON"
    elif corruption == "truncated":
        _write_sidecar(corrupted, header, labels[:-1])
        message = "record count differs"
    else:
        header["catalogue_sha256"] = "0" * 64
        _write_sidecar(corrupted, header, labels)
        message = "header differs"

    with pytest.raises(ValueError, match=message):
        extract_resolution_quality_streaming(
            labels_path=corrupted,
            expected_count=quality_case.count,
            catalogue=quality_case.catalogue,
            as_of_day=AS_OF_DAY,
            chunk_size=3,
        )


@pytest.mark.django_db(transaction=True)
def test_streaming_quality_uses_uncached_chunked_queryset_once(
    quality_case, monkeypatch
):
    from django.db.models.query import QuerySet
    from benchmarks import streaming_quality

    original_iterator = QuerySet.iterator
    iterator_calls = []
    parsed_lines = 0
    original_parse = streaming_quality._parse_label

    def tracking_iterator(self, *args, **kwargs):
        assert self._result_cache is None
        iterator_calls.append(kwargs.get("chunk_size"))
        yield from original_iterator(self, *args, **kwargs)
        assert self._result_cache is None

    def tracking_parse(line, *, line_number):
        nonlocal parsed_lines
        parsed_lines += 1
        return original_parse(line, line_number=line_number)

    monkeypatch.setattr(QuerySet, "iterator", tracking_iterator)
    monkeypatch.setattr(streaming_quality, "_parse_label", tracking_parse)

    result = extract_resolution_quality_streaming(
        labels_path=quality_case.labels_path,
        expected_count=quality_case.count,
        catalogue=quality_case.catalogue,
        as_of_day=AS_OF_DAY,
        chunk_size=3,
    )

    assert result.processed_count == quality_case.count
    assert parsed_lines == quality_case.count
    assert len(iterator_calls) > 1
    assert set(iterator_calls) == {3}
