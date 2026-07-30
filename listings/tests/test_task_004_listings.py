from datetime import date
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


def test_listing_can_be_created_with_all_fields(raw_listing, sku):
    """A Listing can be created with raw_listing, sku, price, condition, location, resolution_confidence, resolution_method, resolved_at — and price/resolution_confidence round-trip as Decimal."""
    from listings.models import Listing

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
    listing.refresh_from_db()
    assert listing.price == Decimal("15500.00")
    assert isinstance(listing.price, Decimal)
    assert listing.resolution_confidence == Decimal("0.9500")
    assert isinstance(listing.resolution_confidence, Decimal)


def test_listing_raw_listing_must_be_one_per_raw_listing(raw_listing, sku):
    """The database rejects a second Listing row pointing at the same RawListing."""
    from listings.models import Listing

    Listing.objects.create(
        raw_listing=raw_listing,
        sku=sku,
        price=Decimal("15500.00"),
        condition="used",
        location="Quezon City",
        resolution_confidence=Decimal("0.9500"),
        resolution_method="exact_alias",
        resolved_at=timezone.now(),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Listing.objects.create(
                raw_listing=raw_listing,
                sku=sku,
                price=Decimal("16000.00"),
                condition="used",
                location="Quezon City",
                resolution_confidence=Decimal("0.9000"),
                resolution_method="exact_alias",
                resolved_at=timezone.now(),
            )


def test_listing_price_must_be_non_negative(raw_listing, sku):
    """The database rejects a Listing row with a negative price."""
    from listings.models import Listing

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Listing.objects.create(
                raw_listing=raw_listing,
                sku=sku,
                price=Decimal("-1.00"),
                condition="used",
                location="Quezon City",
                resolution_confidence=Decimal("0.9000"),
                resolution_method="exact_alias",
                resolved_at=timezone.now(),
            )


def test_listing_resolution_confidence_must_be_within_unit_interval(raw_listing, sku):
    """The database rejects a Listing row with resolution_confidence outside [0, 1]."""
    from listings.models import Listing

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Listing.objects.create(
                raw_listing=raw_listing,
                sku=sku,
                price=Decimal("15500.00"),
                condition="used",
                location="Quezon City",
                resolution_confidence=Decimal("1.5000"),
                resolution_method="exact_alias",
                resolved_at=timezone.now(),
            )


def test_listing_condition_must_be_in_vocabulary(raw_listing, sku):
    """The database rejects a Listing row whose condition is outside the fixed vocabulary."""
    from listings.models import Listing

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Listing.objects.create(
                raw_listing=raw_listing,
                sku=sku,
                price=Decimal("15500.00"),
                condition="not_a_real_condition",
                location="Quezon City",
                resolution_confidence=Decimal("0.9000"),
                resolution_method="exact_alias",
                resolved_at=timezone.now(),
            )


def test_listing_resolution_method_must_be_in_vocabulary(raw_listing, sku):
    """The database rejects a Listing row whose resolution_method is outside the fixed vocabulary."""
    from listings.models import Listing

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Listing.objects.create(
                raw_listing=raw_listing,
                sku=sku,
                price=Decimal("15500.00"),
                condition="used",
                location="Quezon City",
                resolution_confidence=Decimal("0.9000"),
                resolution_method="not_a_real_method",
                resolved_at=timezone.now(),
            )


def test_listing_sku_can_be_null_for_review_queue(raw_listing):
    """A Listing can be created with sku=None — the review queue for unresolved titles."""
    from listings.models import Listing

    listing = Listing.objects.create(
        raw_listing=raw_listing,
        sku=None,
        price=Decimal("15500.00"),
        condition="used",
        location="Quezon City",
        resolution_confidence=Decimal("0.0000"),
        resolution_method="fuzzy_match",
        resolved_at=timezone.now(),
    )
    listing.refresh_from_db()
    assert listing.sku is None
