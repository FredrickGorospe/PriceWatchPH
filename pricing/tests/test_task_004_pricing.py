from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone


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


@pytest.fixture
def listing(db, sku):
    from ingestion.models import RawListing
    from listings.models import Listing
    from sources.models import Source

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
    return Listing.objects.create(
        raw_listing=raw_listing,
        sku=sku,
        price=Decimal("15500.00"),
        condition="used",
        location="Quezon City",
        resolution_confidence=Decimal("0.9500"),
        resolution_method="exact_alias",
        resolved_at=timezone.now(),
    )


@pytest.fixture
def pricepoint(db, sku):
    from pricing.models import PricePoint

    return PricePoint.objects.create(
        sku=sku,
        condition="used",
        day=date(2026, 7, 30),
        median=Decimal("15000.00"),
        p25=Decimal("14000.00"),
        p75=Decimal("16000.00"),
        n_listings=10,
    )


def test_pricepoint_can_be_created_with_all_fields(sku):
    """A PricePoint can be created with sku, condition, day, median, p25, p75, n_listings — and median/p25/p75 round-trip as Decimal."""
    from pricing.models import PricePoint

    pp = PricePoint.objects.create(
        sku=sku,
        condition="used",
        day=date(2026, 7, 30),
        median=Decimal("15000.00"),
        p25=Decimal("14000.00"),
        p75=Decimal("16000.00"),
        n_listings=10,
    )
    pp.refresh_from_db()
    assert pp.median == Decimal("15000.00")
    assert isinstance(pp.median, Decimal)
    assert pp.p25 == Decimal("14000.00")
    assert pp.p75 == Decimal("16000.00")


def test_pricepoint_sku_condition_day_must_be_unique(pricepoint, sku):
    """The database rejects a second PricePoint row with the same (sku, condition, day)."""
    from pricing.models import PricePoint

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PricePoint.objects.create(
                sku=sku,
                condition="used",
                day=pricepoint.day,
                median=Decimal("15500.00"),
                p25=Decimal("14500.00"),
                p75=Decimal("16500.00"),
                n_listings=5,
            )


def test_pricepoint_p25_median_p75_must_be_ordered(sku):
    """The database rejects a PricePoint row where p25 <= median <= p75 does not hold."""
    from pricing.models import PricePoint

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PricePoint.objects.create(
                sku=sku,
                condition="used",
                day=date(2026, 7, 31),
                median=Decimal("50.00"),
                p25=Decimal("100.00"),
                p75=Decimal("200.00"),
                n_listings=5,
            )


def test_pricepoint_n_listings_must_be_non_negative(sku):
    """The database rejects a PricePoint row with a negative n_listings."""
    from pricing.models import PricePoint

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PricePoint.objects.create(
                sku=sku,
                condition="used",
                day=date(2026, 8, 1),
                median=Decimal("15000.00"),
                p25=Decimal("14000.00"),
                p75=Decimal("16000.00"),
                n_listings=-1,
            )


def test_dealflag_can_be_created_with_all_fields(listing, pricepoint):
    """A DealFlag can be created with listing, score, baseline_pricepoint, reason, flagged_at — and score round-trips as Decimal and can be negative."""
    from pricing.models import DealFlag

    flag = DealFlag.objects.create(
        listing=listing,
        score=Decimal("-2.5000"),
        baseline_pricepoint=pricepoint,
        reason="price more than 2 MAD below baseline median",
        flagged_at=timezone.now(),
    )
    flag.refresh_from_db()
    assert flag.score == Decimal("-2.5000")
    assert isinstance(flag.score, Decimal)


def test_dealflag_listing_baseline_pricepoint_must_be_unique(listing, pricepoint):
    """The database rejects a second DealFlag row for the same (listing, baseline_pricepoint)."""
    from pricing.models import DealFlag

    DealFlag.objects.create(
        listing=listing,
        score=Decimal("-2.5000"),
        baseline_pricepoint=pricepoint,
        reason="price more than 2 MAD below baseline median",
        flagged_at=timezone.now(),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DealFlag.objects.create(
                listing=listing,
                score=Decimal("-3.0000"),
                baseline_pricepoint=pricepoint,
                reason="re-scored",
                flagged_at=timezone.now(),
            )


def test_dealflag_baseline_pricepoint_cannot_be_null(listing):
    """The database rejects a DealFlag row with no baseline_pricepoint."""
    from pricing.models import DealFlag

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DealFlag.objects.create(
                listing=listing,
                score=Decimal("-2.5000"),
                baseline_pricepoint=None,
                reason="price more than 2 MAD below baseline median",
                flagged_at=timezone.now(),
            )
