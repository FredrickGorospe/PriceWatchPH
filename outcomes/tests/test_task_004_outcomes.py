from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone


@pytest.fixture
def deal_flag(db):
    from catalogue.models import Sku
    from ingestion.models import RawListing
    from listings.models import Listing
    from pricing.models import DealFlag, PricePoint
    from sources.models import Source

    sku = Sku.objects.create(
        brand="ASUS",
        model="TUF Gaming RTX 4070",
        variant="",
        category="gpu",
        launch_msrp=Decimal("34995.00"),
        launch_date=date(2023, 4, 1),
    )
    source = Source.objects.create(
        name="test_source",
        base_url="https://example.invalid",
        terms_notes="test fixture",
        rate_limit=None,
    )
    raw_listing = RawListing.objects.create(
        source=source,
        raw_title="ASUS TUF RTX 4070 12GB",
        raw_price_text="15500",
        raw_price=Decimal("15500.00"),
        url="https://example.invalid/x",
        seller="anon",
        fetched_at=timezone.now(),
        external_id=None,
    )
    listing = Listing.objects.create(
        raw_listing=raw_listing,
        sku=sku,
        price=Decimal("15500.00"),
        condition="used",
        location="Quezon City",
        resolution_confidence=Decimal("0.9500"),
        resolution_method="exact_alias",
        resolved_at=timezone.now(),
    )
    pricepoint = PricePoint.objects.create(
        sku=sku,
        condition="used",
        day=date(2026, 7, 30),
        median=Decimal("18000.00"),
        p25=Decimal("17000.00"),
        p75=Decimal("19000.00"),
        n_listings=10,
    )
    return DealFlag.objects.create(
        listing=listing,
        score=Decimal("-2.5000"),
        baseline_pricepoint=pricepoint,
        reason="price more than 2 MAD below baseline median",
        flagged_at=timezone.now(),
    )


def test_outcome_can_be_created_when_acted_true_with_no_skip_reason(deal_flag):
    """An Outcome with acted=True and no skip_reason is accepted — the accepted case docs/00_PLANNING.md §4 asks about."""
    from outcomes.models import Outcome

    outcome = Outcome.objects.create(
        deal_flag=deal_flag,
        acted=True,
        skip_reason=None,
        bought_at=timezone.now(),
        bought_price=Decimal("15500.00"),
        sold_at=None,
        sold_price=None,
        days_held=None,
    )
    outcome.refresh_from_db()
    assert outcome.acted is True


def test_outcome_requires_skip_reason_when_not_acted(deal_flag):
    """The database rejects an Outcome row with acted=False and no skip_reason — the rejected case docs/00_PLANNING.md §4 asks about."""
    from outcomes.models import Outcome

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Outcome.objects.create(
                deal_flag=deal_flag,
                acted=False,
                skip_reason=None,
                bought_at=None,
                bought_price=None,
                sold_at=None,
                sold_price=None,
                days_held=None,
            )


def test_outcome_can_be_created_when_not_acted_with_skip_reason(deal_flag):
    """An Outcome with acted=False and a non-empty skip_reason is accepted."""
    from outcomes.models import Outcome

    outcome = Outcome.objects.create(
        deal_flag=deal_flag,
        acted=False,
        skip_reason="already sold by the time I followed up",
        bought_at=None,
        bought_price=None,
        sold_at=None,
        sold_price=None,
        days_held=None,
    )
    outcome.refresh_from_db()
    assert outcome.skip_reason == "already sold by the time I followed up"


def test_outcome_deal_flag_must_be_unique(deal_flag):
    """The database rejects a second Outcome row for the same DealFlag."""
    from outcomes.models import Outcome

    Outcome.objects.create(
        deal_flag=deal_flag,
        acted=True,
        skip_reason=None,
        bought_at=timezone.now(),
        bought_price=Decimal("15500.00"),
        sold_at=None,
        sold_price=None,
        days_held=None,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Outcome.objects.create(
                deal_flag=deal_flag,
                acted=False,
                skip_reason="duplicate attempt",
                bought_at=None,
                bought_price=None,
                sold_at=None,
                sold_price=None,
                days_held=None,
            )


def test_outcome_days_held_must_be_non_negative(deal_flag):
    """The database rejects an Outcome row with a negative days_held."""
    from outcomes.models import Outcome

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Outcome.objects.create(
                deal_flag=deal_flag,
                acted=True,
                skip_reason=None,
                bought_at=timezone.now(),
                bought_price=Decimal("15500.00"),
                sold_at=timezone.now(),
                sold_price=Decimal("16000.00"),
                days_held=-1,
            )


def test_outcome_bought_price_and_sold_price_round_trip_as_decimal(deal_flag):
    """bought_price and sold_price round-trip as Decimal — answers docs/00_PLANNING.md §4's money-column question for Outcome."""
    from outcomes.models import Outcome

    outcome = Outcome.objects.create(
        deal_flag=deal_flag,
        acted=True,
        skip_reason=None,
        bought_at=timezone.now(),
        bought_price=Decimal("15500.00"),
        sold_at=timezone.now(),
        sold_price=Decimal("17000.00"),
        days_held=14,
    )
    outcome.refresh_from_db()
    assert outcome.bought_price == Decimal("15500.00")
    assert isinstance(outcome.bought_price, Decimal)
    assert outcome.sold_price == Decimal("17000.00")
    assert isinstance(outcome.sold_price, Decimal)


def test_outcome_realised_margin_is_generated_as_sold_minus_bought(deal_flag):
    """realised_margin is computed by the database as sold_price - bought_price, not settable directly — a profit case."""
    from outcomes.models import Outcome

    outcome = Outcome.objects.create(
        deal_flag=deal_flag,
        acted=True,
        skip_reason=None,
        bought_at=timezone.now(),
        bought_price=Decimal("15500.00"),
        sold_at=timezone.now(),
        sold_price=Decimal("17000.00"),
        days_held=14,
    )
    outcome.refresh_from_db()
    assert outcome.realised_margin == Decimal("1500.00")
    assert isinstance(outcome.realised_margin, Decimal)


def test_outcome_realised_margin_can_be_negative(deal_flag):
    """realised_margin is negative when sold_price is below bought_price — losses must be storable."""
    from outcomes.models import Outcome

    outcome = Outcome.objects.create(
        deal_flag=deal_flag,
        acted=True,
        skip_reason=None,
        bought_at=timezone.now(),
        bought_price=Decimal("15500.00"),
        sold_at=timezone.now(),
        sold_price=Decimal("14000.00"),
        days_held=20,
    )
    outcome.refresh_from_db()
    assert outcome.realised_margin == Decimal("-1500.00")


def test_outcome_realised_margin_is_null_when_prices_are_not_yet_set(deal_flag):
    """realised_margin is null when bought_price or sold_price is null — a flag that hasn't been fully closed out yet has no margin to report."""
    from outcomes.models import Outcome

    outcome = Outcome.objects.create(
        deal_flag=deal_flag,
        acted=True,
        skip_reason=None,
        bought_at=timezone.now(),
        bought_price=Decimal("15500.00"),
        sold_at=None,
        sold_price=None,
        days_held=None,
    )
    outcome.refresh_from_db()
    assert outcome.realised_margin is None
