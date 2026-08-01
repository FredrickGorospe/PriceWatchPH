from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone


@pytest.fixture
def raw_listing(db):
    from ingestion.models import RawListing
    from sources.models import Source

    source = Source.objects.create(
        name="test_source",
        base_url="https://example.invalid",
        terms_notes="test fixture",
        rate_limit=None,
    )
    return RawListing.objects.create(
        source=source,
        raw_title="ASUS TUF RTX 4070 12GB",
        raw_price_text="15500",
        raw_price=Decimal("15500.00"),
        url="https://example.invalid/x",
        seller="anon",
        fetched_at=timezone.now(),
        external_id=None,
    )


@pytest.fixture
def sku(db):
    from catalogue.models import Sku

    return Sku.objects.create(
        brand="ASUS",
        model="TUF Gaming RTX 4070",
        variant="",
        category="gpu",
        launch_msrp=Decimal("34995.00"),
        launch_date=date(2023, 4, 1),
    )


def _listing(raw_listing, sku, **overrides):
    from listings.models import Listing

    fields = dict(
        raw_listing=raw_listing,
        sku=sku,
        price=Decimal("15500.00"),
        condition="used",
        location="Quezon City",
        resolution_confidence=Decimal("0.9500"),
        resolution_method="exact_alias",
        resolved_at=timezone.now(),
    )
    fields.update(overrides)
    return Listing.objects.create(**fields)


def test_new_fields_are_optional_so_shipped_task_004_tests_still_construct_listings(raw_listing, sku):
    """observed_at, price_kind and trade_side default to NULL: TASK_004's frozen tests construct Listings without them and must keep passing."""
    listing = _listing(raw_listing, sku)
    listing.refresh_from_db()
    assert listing.observed_at is None
    assert listing.price_kind is None
    assert listing.trade_side is None


def test_price_kind_accepts_the_vocabulary(raw_listing, sku):
    """price_kind stores 'asking' and 'realised'."""
    listing = _listing(raw_listing, sku, price_kind="asking")
    listing.refresh_from_db()
    assert listing.price_kind == "asking"


def test_database_rejects_a_price_kind_outside_the_vocabulary(raw_listing, sku):
    """A CheckConstraint, not just choices, rejects an unknown price_kind."""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _listing(raw_listing, sku, price_kind="guessed")


def test_database_rejects_a_trade_side_outside_the_vocabulary(raw_listing, sku):
    """A CheckConstraint rejects an unknown trade_side."""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _listing(raw_listing, sku, price_kind="realised", trade_side="maybe")


def test_realised_price_may_carry_a_trade_side(raw_listing, sku):
    """A realised price records which side of the trade it was."""
    listing = _listing(raw_listing, sku, price_kind="realised", trade_side="buy")
    listing.refresh_from_db()
    assert listing.trade_side == "buy"


def test_realised_price_may_omit_the_trade_side(raw_listing, sku):
    """A 'sold for X' capture is realised with an unknown side, so trade_side stays optional on realised prices."""
    listing = _listing(raw_listing, sku, price_kind="realised", trade_side=None)
    listing.refresh_from_db()
    assert listing.trade_side is None


def test_database_rejects_a_trade_side_on_an_asking_price(raw_listing, sku):
    """Nothing has traded on an asking price, so it cannot have a buy or sell side."""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _listing(raw_listing, sku, price_kind="asking", trade_side="buy")


def test_observed_at_prefers_occurred_at_when_the_source_stated_one(db):
    """observed_at resolves to occurred_at, so a backfilled row is dated when the event happened."""
    from decimal import Decimal as D

    from ingestion.models import RawListing
    from listings.observation import observed_at_for
    from sources.models import Source

    source = Source.objects.create(
        name="pr", base_url="", terms_notes="fixture", rate_limit=None
    )
    occurred = datetime(2019, 3, 4, 16, 0, tzinfo=dt_timezone.utc)
    raw = RawListing.objects.create(
        source=source,
        raw_title="RTX 4070",
        raw_price_text="15500",
        raw_price=D("15500.00"),
        url="",
        seller="anon",
        fetched_at=datetime(2026, 8, 1, 2, 30, tzinfo=dt_timezone.utc),
        occurred_at=occurred,
        external_id=None,
    )
    assert observed_at_for(raw) == occurred


def test_observed_at_falls_back_to_fetched_at_when_occurred_at_is_null(raw_listing):
    """A live listing with no stated event date is dated by when it was fetched."""
    from listings.observation import observed_at_for

    assert raw_listing.occurred_at is None
    assert observed_at_for(raw_listing) == raw_listing.fetched_at
