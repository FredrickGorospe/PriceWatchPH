"""Deterministic synthetic observations for BENCH_002 correctness checks."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Iterator, TextIO
from zoneinfo import ZoneInfo

from benchmarks.catalogue import CatalogueValue, SkuValue


GENERATOR_VERSION = "1.0.0"
MASTER_SEED = 20260829
SELLER_COHORT_SIZE = 4096
_DIFFICULTIES = "ABCD"
_CONDITIONS = ("new", "like_new", "used", "for_parts")
_MANILA = ZoneInfo("Asia/Manila")
_UTC = timezone.utc
_MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class ProductionRecord:
    raw_title: str
    raw_price_text: str
    raw_price: Decimal
    url: str
    seller_handle: str
    fetched_at: datetime
    occurred_at: datetime | None
    external_id: str
    payload: dict[str, str]


@dataclass(frozen=True)
class LabelRecord:
    observation_index: int
    observation_key: str
    difficulty: str
    expected_sku_key: str | None
    candidate_sku_keys: tuple[str, ...]
    transformations: tuple[str, ...]
    generation_digest: str


@dataclass(frozen=True)
class Observation:
    production: ProductionRecord
    label: LabelRecord


class _ObservationIterator(Iterator[Observation]):
    """Expose the exact remaining count without retaining generated records."""

    def __init__(
        self, *, count: int, catalogue: CatalogueValue, as_of_day: date
    ) -> None:
        self._count = count
        self._catalogue = catalogue
        self._as_of_day = as_of_day
        self._next_index = 0

    def __iter__(self) -> _ObservationIterator:
        return self

    def __next__(self) -> Observation:
        if self._next_index >= self._count:
            raise StopIteration
        observation = _observation(
            observation_index=self._next_index,
            catalogue=self._catalogue,
            as_of_day=self._as_of_day,
        )
        self._next_index += 1
        return observation

    def __len__(self) -> int:
        return self._count - self._next_index


def _length_delimited(parts: Iterable[object]) -> bytes:
    framed = bytearray()
    for part in parts:
        encoded = str(part).encode("utf-8")
        framed.extend(str(len(encoded)).encode("ascii"))
        framed.extend(b":")
        framed.extend(encoded)
        framed.extend(b";")
    return bytes(framed)


def _component_digest(
    *, catalogue_sha256: str, as_of_day: date, index: int, component: str
) -> bytes:
    return hashlib.sha256(
        _length_delimited(
            (
                GENERATOR_VERSION,
                MASTER_SEED,
                catalogue_sha256,
                as_of_day.isoformat(),
                index,
                component,
            )
        )
    ).digest()


def _component_int(
    *, catalogue_sha256: str, as_of_day: date, index: int, component: str
) -> int:
    return int.from_bytes(
        _component_digest(
            catalogue_sha256=catalogue_sha256,
            as_of_day=as_of_day,
            index=index,
            component=component,
        ),
        "big",
    )


def seller_handle(index: int) -> str:
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < SELLER_COHORT_SIZE:
        raise ValueError("seller index must be an integer from 0 through 4095")
    return f"benchmark_seller_{index:04d}"


def _repeat_source_index(
    *, observation_index: int, catalogue_sha256: str, as_of_day: date
) -> int:
    block_start = observation_index - observation_index % 10
    block_ordinal = block_start // 10
    designated = _DIFFICULTIES[block_ordinal % 4]
    eligible_offsets = [
        offset
        for offset in range(1, 10)
        if _DIFFICULTIES[(block_start + offset) % 4] == designated
    ]
    position_value = _component_int(
        catalogue_sha256=catalogue_sha256,
        as_of_day=as_of_day,
        index=block_start,
        component="repeat_position",
    )
    repeat_offset = eligible_offsets[position_value % len(eligible_offsets)]
    if observation_index != block_start + repeat_offset:
        return observation_index
    source_value = _component_int(
        catalogue_sha256=catalogue_sha256,
        as_of_day=as_of_day,
        index=block_start,
        component="repeat_source",
    )
    return block_start + source_value % repeat_offset


def _pricing_targets(catalogue: CatalogueValue) -> tuple[SkuValue, ...]:
    first_by_category: dict[str, SkuValue] = {}
    for sku in catalogue.skus:
        first_by_category.setdefault(sku.category, sku)
    category_order = ("gpu", "cpu", "ram", "mobo", "monitor", "peripheral")
    return tuple(first_by_category[category] for category in category_order)


def _choose_sku(
    *, identity_index: int, catalogue: CatalogueValue, as_of_day: date
) -> SkuValue:
    target_offset = identity_index % 50
    targets = _pricing_targets(catalogue)
    if target_offset < len(targets):
        return targets[target_offset]
    selected = _component_int(
        catalogue_sha256=catalogue.sha256,
        as_of_day=as_of_day,
        index=identity_index,
        component="sku_selection",
    )
    return catalogue.skus[selected % len(catalogue.skus)]


def _group_members(catalogue: CatalogueValue, sku: SkuValue) -> tuple[SkuValue, ...]:
    return tuple(
        member
        for member in catalogue.skus
        if member.ambiguity_group == sku.ambiguity_group
    )


def _title_and_label(
    *, difficulty: str, sku: SkuValue, catalogue: CatalogueValue, variant_value: int
) -> tuple[str, str | None, tuple[str, ...], tuple[str, ...]]:
    if difficulty == "A":
        alias = sku.aliases[variant_value % len(sku.aliases)].alias_text
        if variant_value % 3 == 0:
            return alias, sku.natural_key, (sku.natural_key,), ("exact_frozen_alias",)
        # Punctuation and whitespace preserve the release-normalised title.
        title = "  ".join(alias.upper().split())
        return title, sku.natural_key, (sku.natural_key,), (
            "case_change",
            "whitespace_change",
        )
    if difficulty == "B":
        canonical = sku.aliases[0].alias_text
        return (
            f"{canonical} showcase edition",
            sku.natural_key,
            (sku.natural_key,),
            ("modest_sales_phrase",),
        )
    if difficulty == "C":
        model_differentiator = sku.model.split()[-1]
        variant = f" {sku.variant}" if sku.variant else ""
        return (
            f"{sku.family_token} {model_differentiator}{variant} select {sku.brand}",
            sku.natural_key,
            (sku.natural_key,),
            ("substantial_reorder", "redundant_token_omission", "lexical_noise"),
        )
    candidates = _group_members(catalogue, sku)
    return (
        f"{sku.brand} {sku.family_token} family",
        None,
        tuple(member.natural_key for member in candidates),
        ("model_differentiator_omission", "variant_differentiator_omission"),
    )


def _observation(
    *, observation_index: int, catalogue: CatalogueValue, as_of_day: date
) -> Observation:
    identity_index = _repeat_source_index(
        observation_index=observation_index,
        catalogue_sha256=catalogue.sha256,
        as_of_day=as_of_day,
    )
    sku = _choose_sku(
        identity_index=identity_index,
        catalogue=catalogue,
        as_of_day=as_of_day,
    )
    difficulty = _DIFFICULTIES[observation_index % 4]
    variant_value = _component_int(
        catalogue_sha256=catalogue.sha256,
        as_of_day=as_of_day,
        index=observation_index,
        component="title_variant",
    )
    raw_title, expected_key, candidate_keys, transformations = _title_and_label(
        difficulty=difficulty,
        sku=sku,
        catalogue=catalogue,
        variant_value=variant_value,
    )

    identity_digest = _component_digest(
        catalogue_sha256=catalogue.sha256,
        as_of_day=as_of_day,
        index=identity_index,
        component="external_identity",
    ).hex()
    external_id = f"synthetic-{identity_digest[:32]}"
    seller_index = _component_int(
        catalogue_sha256=catalogue.sha256,
        as_of_day=as_of_day,
        index=identity_index,
        component="seller_selection",
    ) % SELLER_COHORT_SIZE

    # The largest authorised correctness prefix remains chronological and
    # reaches the as-of day without depending on the requested record count.
    local_occurred_at = datetime.combine(
        as_of_day - timedelta(days=6), time(hour=0), tzinfo=_MANILA
    ) + timedelta(minutes=10 * observation_index)
    occurred_at = local_occurred_at.astimezone(_UTC)
    fetch_lag_minutes = 30 + _component_int(
        catalogue_sha256=catalogue.sha256,
        as_of_day=as_of_day,
        index=observation_index,
        component="fetch_lag",
    ) % 10
    fetched_at = (local_occurred_at + timedelta(minutes=fetch_lag_minutes)).astimezone(
        _UTC
    )

    targets = {target.natural_key for target in _pricing_targets(catalogue)}
    if sku.natural_key in targets:
        condition = "used"
    else:
        condition_value = _component_int(
            catalogue_sha256=catalogue.sha256,
            as_of_day=as_of_day,
            index=observation_index,
            component="condition",
        )
        condition = _CONDITIONS[condition_value % len(_CONDITIONS)]

    percentage = 70 + _component_int(
        catalogue_sha256=catalogue.sha256,
        as_of_day=as_of_day,
        index=observation_index,
        component="price_percentage",
    ) % 61
    if observation_index % 97 == 0:
        percentage = 45
    elif observation_index % 89 == 0:
        percentage = 165
    msrp_minor_units = int(Decimal(sku.launch_msrp) * 100)
    price_minor_units = (msrp_minor_units * percentage + 50) // 100
    raw_price = (Decimal(price_minor_units) / Decimal(100)).quantize(
        _MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )
    raw_price_text = f"PHP {raw_price:,.2f}"

    observation_key = _component_digest(
        catalogue_sha256=catalogue.sha256,
        as_of_day=as_of_day,
        index=observation_index,
        component="observation_key",
    ).hex()
    production = ProductionRecord(
        raw_title=raw_title,
        raw_price_text=raw_price_text,
        raw_price=raw_price,
        url=f"https://synthetic-benchmark.invalid/listing/{external_id}",
        seller_handle=seller_handle(seller_index),
        fetched_at=fetched_at,
        occurred_at=occurred_at,
        external_id=external_id,
        payload={
            "stated_condition": condition,
            "stated_price_kind": "asking",
        },
    )
    digest_document = {
        "candidate_sku_keys": candidate_keys,
        "difficulty": difficulty,
        "expected_sku_key": expected_key,
        "observation_index": observation_index,
        "observation_key": observation_key,
        "transformations": transformations,
    }
    generation_digest = hashlib.sha256(
        json.dumps(
            digest_document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return Observation(
        production=production,
        label=LabelRecord(
            observation_index=observation_index,
            observation_key=observation_key,
            difficulty=difficulty,
            expected_sku_key=expected_key,
            candidate_sku_keys=candidate_keys,
            transformations=transformations,
            generation_digest=generation_digest,
        ),
    )


def iter_observations(
    *, count: int, catalogue: CatalogueValue, as_of_day: date
) -> Iterator[Observation]:
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("count must be a non-negative integer")
    if not isinstance(as_of_day, date) or isinstance(as_of_day, datetime):
        raise ValueError("as_of_day must be an explicit date")
    return _ObservationIterator(
        count=count,
        catalogue=catalogue,
        as_of_day=as_of_day,
    )


def pricing_support_summary(records: Iterable[Observation]) -> list[dict[str, object]]:
    materialised = list(records)
    if not materialised:
        return []
    observed_days = [
        record.production.occurred_at.astimezone(_MANILA).date()
        for record in materialised
        if record.production.occurred_at is not None
    ]
    if not observed_days:
        return []
    current_day = max(observed_days)
    evidence: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"historical": 0, "current": 0}
    )
    for record in materialised:
        key = record.label.expected_sku_key
        occurred_at = record.production.occurred_at
        if (
            key is None
            or occurred_at is None
            or record.production.payload["stated_condition"] != "used"
        ):
            continue
        match = re.fullmatch(
            r"bench_(gpu|cpu|ram|mobo|monitor|peripheral)_\d{3}", key
        )
        if match is None:
            continue
        bucket = "current" if occurred_at.astimezone(_MANILA).date() == current_day else "historical"
        evidence[(match.group(1), key)][bucket] += 1

    result = []
    for category in ("gpu", "cpu", "ram", "mobo", "monitor", "peripheral"):
        eligible = [
            (sku_key, counts)
            for (entry_category, sku_key), counts in evidence.items()
            if entry_category == category
            and counts["historical"] >= 5
            and counts["current"] >= 1
        ]
        if not eligible:
            continue
        sku_key, counts = sorted(eligible, key=lambda item: item[0])[0]
        result.append(
            {
                "category": category,
                "sku_key": sku_key,
                "condition": "used",
                "historical_asking_count": counts["historical"],
                "current_candidate_count": counts["current"],
            }
        )
    return result


def write_label_sidecar(
    *,
    stream: TextIO,
    records: Iterable[Observation],
    catalogue_sha256: str,
    as_of_day: date,
) -> None:
    from benchmarks.metrics import production_locator_fingerprint

    def write_observation(target: TextIO, record: Observation) -> None:
        label = record.label
        production = record.production
        line = {
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
        target.write(
            json.dumps(
                line,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        target.write("\n")

    def write_header(observation_count: int) -> None:
        header = {
            "record_type": "header",
            "schema_version": "benchmark_labels.v1",
            "generator_version": GENERATOR_VERSION,
            "master_seed": MASTER_SEED,
            "catalogue_sha256": catalogue_sha256,
            "as_of_day": as_of_day.isoformat(),
            "observation_count": observation_count,
        }
        stream.write(
            json.dumps(
                header,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        stream.write("\n")

    try:
        observation_count = len(records)  # type: ignore[arg-type]
    except TypeError:
        # An unsized one-shot iterable cannot declare a correct first-line
        # count. Spool its encoded body to disk while retaining one record at
        # a time, then prepend the counted header to the caller's stream.
        with tempfile.TemporaryFile(
            mode="w+", encoding="utf-8", newline="\n"
        ) as body:
            observation_count = 0
            for record in records:
                write_observation(body, record)
                observation_count += 1
            write_header(observation_count)
            body.seek(0)
            shutil.copyfileobj(body, stream, length=1024 * 1024)
        return

    write_header(observation_count)
    written_count = 0
    for record in records:
        write_observation(stream, record)
        written_count += 1
    if written_count != observation_count:
        raise ValueError("sized records iterable changed during sidecar writing")
