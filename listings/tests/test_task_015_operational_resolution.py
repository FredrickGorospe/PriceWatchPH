"""Synthetic command fixtures only; these tests do not measure market accuracy."""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from itertools import count

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone


def _run_command():
    try:
        return call_command("resolve_listings", verbosity=0)
    except CommandError as error:
        assert "Unknown command" not in str(error), "resolve_listings is not implemented"
        raise


@pytest.fixture
def source(db):
    from sources.models import Source

    return Source.objects.create(
        name="task_015_source",
        base_url="https://example.invalid",
        terms_notes="synthetic TASK_015 fixture",
        rate_limit=None,
    )


@pytest.fixture
def raw_listing_factory(db, source):
    from ingestion.models import RawListing

    sequence = count(1)

    def make(
        *,
        raw_title="Synthetic RTX 4070",
        raw_price=Decimal("15500.00"),
        raw_price_text="15500",
        fetched_at=None,
        occurred_at=None,
        payload=None,
    ):
        return RawListing.objects.create(
            source=source,
            raw_title=raw_title,
            raw_price=raw_price,
            raw_price_text=raw_price_text,
            url="https://example.invalid/listing",
            seller="anon",
            fetched_at=fetched_at or timezone.now(),
            occurred_at=occurred_at,
            external_id=f"task-015-{next(sequence)}",
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


def _alias(sku, raw_title):
    from catalogue.models import SkuAlias
    from listings.normalisation import normalise_title

    return SkuAlias.objects.create(
        sku=sku,
        alias_text=raw_title,
        normalised_text=normalise_title(raw_title),
        source_of_truth="seed",
    )


def _raw_state(raw_listing):
    return (
        raw_listing.source_id,
        raw_listing.raw_title,
        raw_listing.raw_price,
        raw_listing.raw_price_text,
        raw_listing.url,
        raw_listing.seller,
        raw_listing.fetched_at,
        raw_listing.occurred_at,
        raw_listing.external_id,
        raw_listing.payload,
    )


def test_command_is_registered_and_handles_an_empty_database(db):
    from listings.models import Listing

    _run_command()

    assert Listing.objects.count() == 0


def test_command_delegates_every_rawlisting_in_primary_key_order(
    raw_listing_factory,
    monkeypatch,
):
    from listings.management.commands import resolve_listings as command_module

    raw_listings = [
        raw_listing_factory(raw_title="Third semantic title"),
        raw_listing_factory(raw_title="First semantic title"),
        raw_listing_factory(raw_title="Second semantic title"),
    ]
    visited = []

    monkeypatch.setattr(
        command_module,
        "resolve_raw_listing",
        lambda raw_listing: visited.append(raw_listing.pk),
    )

    _run_command()

    assert visited == sorted(raw.pk for raw in raw_listings)


def test_unprocessed_rawlistings_receive_task_014_listings(
    raw_listing_factory,
    sku_factory,
):
    from listings.models import Listing

    occurred = datetime(2026, 7, 1, 4, 0, tzinfo=dt_timezone.utc)
    exact_raw = raw_listing_factory(
        raw_title="Synthetic RTX4070 12GB",
        raw_price=Decimal("15000.25"),
        occurred_at=occurred,
        payload={"stated_condition": "like_new", "stated_trade_side": "sell"},
    )
    unresolved_raw = raw_listing_factory(
        raw_title="Uncatalogued synthetic GPU",
        raw_price=None,
        raw_price_text="PM for price",
    )
    sku = sku_factory(model="RTX 4070 12GB")
    _alias(sku, exact_raw.raw_title)

    _run_command()

    exact = Listing.objects.get(raw_listing=exact_raw)
    assert exact.sku == sku
    assert exact.price == Decimal("15000.25")
    assert exact.condition == "like_new"
    assert exact.observed_at == occurred
    assert exact.price_kind == "realised"
    assert exact.trade_side == "sell"
    assert exact.resolution_method == "exact_alias"
    assert exact.resolution_confidence == Decimal("1.0000")

    unresolved = Listing.objects.get(raw_listing=unresolved_raw)
    assert unresolved.sku is None
    assert unresolved.price is None
    assert unresolved.condition is None
    assert unresolved.resolution_method == "unresolved"
    assert unresolved.resolution_confidence == Decimal("0.0000")
    assert Listing.objects.count() == 2


def test_existing_machine_listings_are_reconsidered_on_rerun(
    raw_listing_factory,
    sku_factory,
):
    from listings.models import Listing

    promotion_raw = raw_listing_factory(raw_title="Synthetic promotion GPU")
    correction_raw = raw_listing_factory(raw_title="Synthetic correction GPU")
    first_sku = sku_factory(model="First correction target")
    second_sku = sku_factory(model="Second correction target")
    correction_alias = _alias(first_sku, correction_raw.raw_title)

    _run_command()
    promotion_listing = Listing.objects.get(raw_listing=promotion_raw)
    correction_listing = Listing.objects.get(raw_listing=correction_raw)

    promoted_sku = sku_factory(model="Promoted target")
    _alias(promoted_sku, promotion_raw.raw_title)
    correction_alias.sku = second_sku
    correction_alias.save(update_fields=["sku"])

    _run_command()

    promotion_listing.refresh_from_db()
    correction_listing.refresh_from_db()
    assert promotion_listing.sku == promoted_sku
    assert promotion_listing.resolution_method == "exact_alias"
    assert promotion_listing.resolution_confidence == Decimal("1.0000")
    assert correction_listing.sku == second_sku
    assert correction_listing.resolution_method == "exact_alias"
    assert Listing.objects.filter(raw_listing=promotion_raw).count() == 1
    assert Listing.objects.filter(raw_listing=correction_raw).count() == 1


def test_unchanged_command_rerun_preserves_listing_and_resolved_at(raw_listing_factory):
    from listings.models import Listing

    raw = raw_listing_factory(raw_title="Stable unresolved synthetic GPU")
    _run_command()
    listing = Listing.objects.get(raw_listing=raw)
    original_pk = listing.pk
    original_resolved_at = listing.resolved_at

    _run_command()

    listing.refresh_from_db()
    assert listing.pk == original_pk
    assert listing.resolved_at == original_resolved_at
    assert Listing.objects.filter(raw_listing=raw).count() == 1


def test_command_preserves_human_confirmed_listing(raw_listing_factory, sku_factory):
    from listings.models import Listing

    raw = raw_listing_factory(
        raw_title="Human confirmed synthetic GPU",
        raw_price=Decimal("15500.00"),
        payload={"stated_condition": "used", "stated_trade_side": "buy"},
    )
    confirmed_sku = sku_factory(model="Confirmed target")
    conflicting_sku = sku_factory(model="Conflicting alias target")
    _alias(conflicting_sku, raw.raw_title)
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

    _run_command()
    listing.refresh_from_db()

    assert (
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
    ) == expected


def test_command_never_mutates_rawlistings(raw_listing_factory):
    raw_listings = [
        raw_listing_factory(
            raw_title="  Synthetic RTX4070-Ti  ",
            raw_price_text="15,500",
            payload={"stated_condition": "used"},
        ),
        raw_listing_factory(raw_title="Another immutable observation"),
    ]
    before = {raw.pk: _raw_state(raw) for raw in raw_listings}

    _run_command()

    for raw in raw_listings:
        raw.refresh_from_db()
        assert _raw_state(raw) == before[raw.pk]


def test_command_creates_no_catalogue_downstream_or_bookkeeping_state(
    raw_listing_factory,
    source,
):
    from catalogue.models import Sku, SkuAlias
    from ingestion.models import RawListing, Swap
    from outcomes.models import Outcome
    from pricing.models import DealFlag, PricePoint

    raw_listing_factory(raw_title="No catalogue match")
    before = {
        "raw": RawListing.objects.count(),
        "sku": Sku.objects.count(),
        "alias": SkuAlias.objects.count(),
        "pricepoint": PricePoint.objects.count(),
        "dealflag": DealFlag.objects.count(),
        "outcome": Outcome.objects.count(),
        "swap": Swap.objects.count(),
    }

    _run_command()

    assert RawListing.objects.count() == before["raw"]
    assert Sku.objects.count() == before["sku"]
    assert SkuAlias.objects.count() == before["alias"]
    assert PricePoint.objects.count() == before["pricepoint"]
    assert DealFlag.objects.count() == before["dealflag"]
    assert Outcome.objects.count() == before["outcome"]
    assert Swap.objects.count() == before["swap"]
    source.refresh_from_db()
    assert source.last_successful_fetch is None


def test_batch_failure_rolls_back_earlier_listing_creates_and_updates(
    raw_listing_factory,
    sku_factory,
    monkeypatch,
):
    from listings.management.commands import resolve_listings as command_module
    from listings.models import Listing
    from listings.resolver import resolve_raw_listing

    existing_raw = raw_listing_factory(raw_title="Promote before later failure")
    existing_listing = resolve_raw_listing(existing_raw)
    existing_resolved_at = existing_listing.resolved_at
    promoted_sku = sku_factory(model="Promotion rolled back")
    _alias(promoted_sku, existing_raw.raw_title)
    new_raw = raw_listing_factory(raw_title="Create before later failure")
    failing_raw = raw_listing_factory(raw_title="Raise unexpected failure")

    def fail_on_last(raw_listing):
        if raw_listing.pk == failing_raw.pk:
            raise RuntimeError("synthetic resolver failure")
        return resolve_raw_listing(raw_listing)

    monkeypatch.setattr(command_module, "resolve_raw_listing", fail_on_last)

    with pytest.raises(RuntimeError, match="synthetic resolver failure"):
        _run_command()

    existing_listing.refresh_from_db()
    assert existing_listing.sku is None
    assert existing_listing.resolution_method == "unresolved"
    assert existing_listing.resolved_at == existing_resolved_at
    assert not Listing.objects.filter(raw_listing=new_raw).exists()
    assert not Listing.objects.filter(raw_listing=failing_raw).exists()


def test_unexpected_resolver_exception_is_not_swallowed(
    raw_listing_factory,
    monkeypatch,
):
    from listings.management.commands import resolve_listings as command_module
    from listings.models import Listing

    raw = raw_listing_factory(raw_title="Unexpected failure observation")

    def raise_unexpected(_raw_listing):
        raise ValueError("unexpected synthetic resolver error")

    monkeypatch.setattr(command_module, "resolve_raw_listing", raise_unexpected)

    with pytest.raises(ValueError, match="unexpected synthetic resolver error"):
        _run_command()

    assert not Listing.objects.filter(raw_listing=raw).exists()
