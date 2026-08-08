"""Synthetic contract fixtures only; these tests do not measure market accuracy."""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from itertools import count

import pytest
from django.utils import timezone


def _normalise(title):
    from listings.normalisation import normalise_title

    return normalise_title(title)


def _resolve(raw_listing):
    from listings.resolver import resolve_raw_listing

    return resolve_raw_listing(raw_listing)


@pytest.fixture
def source(db):
    from sources.models import Source

    return Source.objects.create(
        name="task_014_source",
        base_url="https://example.invalid",
        terms_notes="synthetic TASK_014 fixture",
        rate_limit=None,
    )


@pytest.fixture
def raw_listing_factory(db, source):
    from ingestion.models import RawListing

    sequence = count(1)

    def make(
        *,
        raw_title="ASUS TUF RTX 4070 12GB",
        raw_price=Decimal("15500.00"),
        raw_price_text="15500",
        fetched_at=None,
        occurred_at=None,
        payload=None,
        raw_source=None,
    ):
        return RawListing.objects.create(
            source=raw_source or source,
            raw_title=raw_title,
            raw_price=raw_price,
            raw_price_text=raw_price_text,
            url="https://example.invalid/listing",
            seller="anon",
            fetched_at=fetched_at or timezone.now(),
            occurred_at=occurred_at,
            external_id=f"task-014-{next(sequence)}",
            payload=payload,
        )

    return make


@pytest.fixture
def sku_factory(db):
    from catalogue.models import Sku

    sequence = count(1)

    def make(*, model=None):
        number = next(sequence)
        return Sku.objects.create(
            brand="Synthetic",
            model=model or f"GPU {number}",
            variant=f"variant-{number}",
            category="gpu",
            launch_msrp=Decimal("10000.00"),
            launch_date=date(2026, 1, 1),
        )

    return make


def _alias(sku, *, alias_text, normalised_text):
    from catalogue.models import SkuAlias

    return SkuAlias.objects.create(
        sku=sku,
        alias_text=alias_text,
        normalised_text=normalised_text,
        source_of_truth="seed",
    )


# --- deterministic normalization -------------------------------------------


def test_normalise_title_is_deterministic():
    title = "  ASUS—TUF / RTX4070\t12GB  "
    assert _normalise(title) == _normalise(title)
    assert _normalise(title) == "asus tuf rtx4070 12gb"


def test_normalise_title_applies_nfkc_casefold_and_boundaries():
    assert _normalise("  ＡＳＵＳ—TUF／RTX4070\t12ＧＢ  ") == "asus tuf rtx4070 12gb"


def test_normalise_title_uses_unicode_casefold():
    assert _normalise("Straße GPU") == "strasse gpu"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("RTX 4070 Ti", "rtx 4070 ti"),
        ("RTX 4070 SUPER", "rtx 4070 super"),
        ("RX 7900 XT", "rx 7900 xt"),
        ("RX 7900 XTX", "rx 7900 xtx"),
        ("RTX4090 24GB", "rtx4090 24gb"),
        ("Core i7-13700K", "core i7 13700k"),
        ("RTX 4090 Laptop GPU", "rtx 4090 laptop gpu"),
        ("ASUS TUF Gaming RTX4070 OC", "asus tuf gaming rtx4070 oc"),
        ("RTX 4070 ₱15,500 Brand New", "rtx 4070 15 500 brand new"),
    ],
)
def test_normalise_title_preserves_critical_alphanumeric_tokens(title, expected):
    assert _normalise(title) == expected


# --- exact matching and provenance -----------------------------------------


def test_exact_normalised_alias_creates_resolved_listing(raw_listing_factory, sku_factory):
    raw = raw_listing_factory(raw_title="ＡＳＵＳ—TUF／RTX4070 12ＧＢ")
    sku = sku_factory(model="TUF RTX 4070 12GB")
    _alias(
        sku,
        alias_text="ASUS TUF RTX4070 12GB",
        normalised_text="asus tuf rtx4070 12gb",
    )
    before = timezone.now()

    listing = _resolve(raw)

    assert listing.raw_listing == raw
    assert listing.sku == sku
    assert listing.price == Decimal("15500.00")
    assert listing.condition is None
    assert listing.location == ""
    assert listing.resolution_method == "exact_alias"
    assert listing.resolution_confidence == Decimal("1.0000")
    assert listing.observed_at == raw.fetched_at
    assert listing.price_kind is None
    assert listing.trade_side is None
    assert before <= listing.resolved_at <= timezone.now()


def test_near_alias_miss_is_honestly_unresolved_not_fuzzy(raw_listing_factory, sku_factory):
    raw = raw_listing_factory(raw_title="ASUS TUF RTX 4070 Ti")
    sku = sku_factory(model="TUF RTX 4070")
    _alias(
        sku,
        alias_text="ASUS TUF RTX 4070",
        normalised_text="asus tuf rtx 4070",
    )

    listing = _resolve(raw)

    assert listing.sku is None
    assert listing.resolution_method == "unresolved"
    assert listing.resolution_method != "fuzzy_match"
    assert listing.resolution_confidence == Decimal("0.0000")


def test_null_raw_price_propagates_to_listing(raw_listing_factory):
    raw = raw_listing_factory(
        raw_title="Mystery GPU",
        raw_price=None,
        raw_price_text="PM for price",
    )

    listing = _resolve(raw)

    assert listing.price is None


@pytest.mark.parametrize(
    ("payload", "expected_condition"),
    [
        ({"stated_condition": "like_new"}, "like_new"),
        ({}, None),
        (None, None),
    ],
)
def test_stated_condition_is_copied_and_absent_condition_is_not_inferred(
    raw_listing_factory,
    payload,
    expected_condition,
):
    raw = raw_listing_factory(
        raw_title="Brand New RTX 4070",
        payload=payload,
    )

    listing = _resolve(raw)

    assert listing.condition == expected_condition


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_stated_trade_side_sets_realised_price_kind(raw_listing_factory, side):
    raw = raw_listing_factory(payload={"stated_trade_side": side})

    listing = _resolve(raw)

    assert listing.trade_side == side
    assert listing.price_kind == "realised"


def test_source_name_without_trade_fact_does_not_imply_trade_semantics(db, raw_listing_factory):
    from sources.models import Source

    personal_records = Source.objects.get(name="personal_records")
    raw = raw_listing_factory(
        raw_source=personal_records,
        payload={"stated_condition": "used"},
    )

    listing = _resolve(raw)

    assert listing.price_kind is None
    assert listing.trade_side is None


def test_observed_at_prefers_occurred_at(raw_listing_factory):
    fetched = datetime(2026, 8, 8, 1, 0, tzinfo=dt_timezone.utc)
    occurred = datetime(2020, 5, 1, 16, 0, tzinfo=dt_timezone.utc)
    raw = raw_listing_factory(fetched_at=fetched, occurred_at=occurred)

    listing = _resolve(raw)

    assert listing.observed_at == occurred


def test_observed_at_falls_back_to_fetched_at(raw_listing_factory):
    fetched = datetime(2026, 8, 8, 1, 0, tzinfo=dt_timezone.utc)
    raw = raw_listing_factory(fetched_at=fetched, occurred_at=None)

    listing = _resolve(raw)

    assert listing.observed_at == fetched


# --- persistence, reruns, and boundaries -----------------------------------


def test_unchanged_rerun_keeps_one_listing_and_preserves_resolved_at(raw_listing_factory):
    from listings.models import Listing

    raw = raw_listing_factory(raw_title="Uncatalogued GPU")
    first = _resolve(raw)
    original_resolved_at = first.resolved_at

    second = _resolve(raw)

    assert second.pk == first.pk
    assert second.resolved_at == original_resolved_at
    assert Listing.objects.filter(raw_listing=raw).count() == 1


def test_alias_addition_promotes_unresolved_listing_in_place(raw_listing_factory, sku_factory):
    from listings.models import Listing

    raw = raw_listing_factory(raw_title="Synthetic RTX4070 Ti 12GB")
    first = _resolve(raw)
    old_time = datetime(2020, 1, 1, tzinfo=dt_timezone.utc)
    Listing.objects.filter(pk=first.pk).update(resolved_at=old_time)
    sku = sku_factory(model="RTX 4070 Ti 12GB")
    _alias(
        sku,
        alias_text=raw.raw_title,
        normalised_text=_normalise(raw.raw_title),
    )

    promoted = _resolve(raw)

    assert promoted.pk == first.pk
    assert promoted.sku == sku
    assert promoted.resolution_method == "exact_alias"
    assert promoted.resolution_confidence == Decimal("1.0000")
    assert promoted.resolved_at > old_time
    assert Listing.objects.filter(raw_listing=raw).count() == 1


def test_alias_repoint_and_removal_correct_machine_listing_in_place(
    raw_listing_factory,
    sku_factory,
):
    from listings.models import Listing

    raw = raw_listing_factory(raw_title="Synthetic GPU Alias")
    first_sku = sku_factory(model="First GPU")
    second_sku = sku_factory(model="Second GPU")
    alias = _alias(
        first_sku,
        alias_text=raw.raw_title,
        normalised_text="synthetic gpu alias",
    )
    first = _resolve(raw)

    alias.sku = second_sku
    alias.save(update_fields=["sku"])
    repointed = _resolve(raw)

    assert repointed.pk == first.pk
    assert repointed.sku == second_sku
    assert repointed.resolution_method == "exact_alias"

    alias.delete()
    unresolved = _resolve(raw)

    assert unresolved.pk == first.pk
    assert unresolved.sku is None
    assert unresolved.resolution_method == "unresolved"
    assert unresolved.resolution_confidence == Decimal("0.0000")
    assert Listing.objects.filter(raw_listing=raw).count() == 1


def test_human_confirmed_listing_is_never_overwritten(raw_listing_factory, sku_factory):
    from listings.models import Listing

    raw = raw_listing_factory(
        raw_title="Human Chosen GPU",
        raw_price=Decimal("15500.00"),
        payload={"stated_condition": "used", "stated_trade_side": "buy"},
    )
    confirmed_sku = sku_factory(model="Confirmed GPU")
    conflicting_sku = sku_factory(model="Conflicting Alias GPU")
    _alias(
        conflicting_sku,
        alias_text=raw.raw_title,
        normalised_text="human chosen gpu",
    )
    confirmed_at = datetime(2021, 1, 1, tzinfo=dt_timezone.utc)
    listing = Listing.objects.create(
        raw_listing=raw,
        sku=confirmed_sku,
        price=Decimal("14000.00"),
        condition="for_parts",
        location="Cebu City",
        resolution_confidence=Decimal("1.0000"),
        resolution_method="human_confirmed",
        resolved_at=confirmed_at,
        observed_at=confirmed_at,
        price_kind="realised",
        trade_side="sell",
    )
    expected = (
        listing.sku_id,
        listing.price,
        listing.condition,
        listing.location,
        listing.resolution_confidence,
        listing.resolution_method,
        listing.resolved_at,
        listing.observed_at,
        listing.price_kind,
        listing.trade_side,
    )

    returned = _resolve(raw)
    returned.refresh_from_db()

    assert returned.pk == listing.pk
    assert (
        returned.sku_id,
        returned.price,
        returned.condition,
        returned.location,
        returned.resolution_confidence,
        returned.resolution_method,
        returned.resolved_at,
        returned.observed_at,
        returned.price_kind,
        returned.trade_side,
    ) == expected


def test_resolver_never_mutates_rawlisting(raw_listing_factory):
    raw = raw_listing_factory(
        raw_title="  RTX4070-Ti  ",
        raw_price=Decimal("15500.00"),
        raw_price_text="15,500",
        payload={"stated_condition": "used"},
    )
    before = (
        raw.source_id,
        raw.raw_title,
        raw.raw_price,
        raw.raw_price_text,
        raw.url,
        raw.seller,
        raw.fetched_at,
        raw.occurred_at,
        raw.external_id,
        raw.payload,
    )

    _resolve(raw)
    raw.refresh_from_db()

    assert (
        raw.source_id,
        raw.raw_title,
        raw.raw_price,
        raw.raw_price_text,
        raw.url,
        raw.seller,
        raw.fetched_at,
        raw.occurred_at,
        raw.external_id,
        raw.payload,
    ) == before


def test_resolver_creates_no_catalogue_or_downstream_state(raw_listing_factory, source):
    from catalogue.models import Sku, SkuAlias
    from ingestion.models import RawListing, Swap
    from listings.models import Listing
    from outcomes.models import Outcome
    from pricing.models import DealFlag, PricePoint

    raw = raw_listing_factory(raw_title="No Catalogue Match")
    before = {
        "raw": RawListing.objects.count(),
        "sku": Sku.objects.count(),
        "alias": SkuAlias.objects.count(),
        "pricepoint": PricePoint.objects.count(),
        "dealflag": DealFlag.objects.count(),
        "outcome": Outcome.objects.count(),
        "swap": Swap.objects.count(),
    }

    listing = _resolve(raw)

    assert listing.sku is None
    assert Listing.objects.filter(raw_listing=raw).count() == 1
    assert RawListing.objects.count() == before["raw"]
    assert Sku.objects.count() == before["sku"]
    assert SkuAlias.objects.count() == before["alias"]
    assert PricePoint.objects.count() == before["pricepoint"]
    assert DealFlag.objects.count() == before["dealflag"]
    assert Outcome.objects.count() == before["outcome"]
    assert Swap.objects.count() == before["swap"]
    source.refresh_from_db()
    assert source.last_successful_fetch is None
