"""Benchmark-only loader for immutable raw observation evidence."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import islice
from typing import Iterable

from benchmarks.generator import ProductionRecord


_PRODUCTION_FIELDS = {
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
_CONDITIONS = {"new", "like_new", "used", "for_parts"}


@dataclass(frozen=True)
class LoadResult:
    loaded_count: int
    source_name: str
    timing_label: str


def _validate_record(record: ProductionRecord) -> None:
    if not isinstance(record, ProductionRecord):
        raise ValueError("raw loader accepts ProductionRecord values only")
    if {field.name for field in fields(record)} != _PRODUCTION_FIELDS:
        raise ValueError("production record fields differ from the frozen schema")
    for field_name in ("raw_title", "raw_price_text", "url", "seller_handle", "external_id"):
        if not isinstance(getattr(record, field_name), str) or not getattr(record, field_name):
            raise ValueError(f"production {field_name} must be a non-empty string")
    if not isinstance(record.raw_price, Decimal) or record.raw_price < 0:
        raise ValueError("production raw_price must be a non-negative Decimal")
    if not isinstance(record.fetched_at, datetime) or record.fetched_at.utcoffset() != timedelta(0):
        raise ValueError("production fetched_at must be UTC-aware")
    if record.occurred_at is not None and (
        not isinstance(record.occurred_at, datetime)
        or record.occurred_at.utcoffset() != timedelta(0)
    ):
        raise ValueError("production occurred_at must be null or UTC-aware")
    if not isinstance(record.payload, dict) or set(record.payload) != {
        "stated_condition",
        "stated_price_kind",
    }:
        raise ValueError("production payload differs from the frozen schema")
    if record.payload["stated_condition"] not in _CONDITIONS:
        raise ValueError("production condition is outside the frozen vocabulary")
    if record.payload["stated_price_kind"] != "asking":
        raise ValueError("production price kind must be asking")


def load_raw_observations(
    *, observations: Iterable[ProductionRecord], chunk_size: int = 1000
) -> LoadResult:
    """Insert production records only, retaining release immutability rules."""
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")

    from django.db import transaction

    from ingestion.models import RawListing
    from ingestion.pseudonymise import pseudonymise
    from sources.models import Source

    source = Source.objects.get(name="manual_capture")
    iterator = iter(observations)
    loaded_count = 0
    with transaction.atomic():
        while True:
            chunk = list(islice(iterator, chunk_size))
            if not chunk:
                break
            rows = []
            for record in chunk:
                _validate_record(record)
                rows.append(
                    RawListing(
                        source=source,
                        raw_title=record.raw_title,
                        raw_price_text=record.raw_price_text,
                        raw_price=record.raw_price,
                        url=record.url,
                        seller=pseudonymise(record.seller_handle),
                        fetched_at=record.fetched_at,
                        occurred_at=record.occurred_at,
                        external_id=record.external_id,
                        payload=dict(record.payload),
                    )
                )
            # Bulk insertion is benchmark timing support, while the database
            # uniqueness constraint remains the authoritative conflict check.
            RawListing.objects.bulk_create(rows, batch_size=chunk_size)
            loaded_count += len(rows)
    return LoadResult(
        loaded_count=loaded_count,
        source_name="manual_capture",
        timing_label="benchmark_raw_load",
    )
