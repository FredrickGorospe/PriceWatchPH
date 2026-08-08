from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, models, transaction
from django.db.models.deletion import SET_NULL
from django.db.models.fields import NOT_PROVIDED
from django.utils import timezone


@pytest.fixture
def raw_listing(db):
    from ingestion.models import RawListing
    from sources.models import Source

    source = Source.objects.create(
        name="task_013_source",
        base_url="https://example.invalid",
        terms_notes="TASK_013 fixture",
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

    fields = {
        "raw_listing": raw_listing,
        "sku": sku,
        "price": Decimal("15500.00"),
        "condition": "used",
        "location": "Quezon City",
        "resolution_confidence": Decimal("0.9500"),
        "resolution_method": "exact_alias",
        "resolved_at": timezone.now(),
    }
    fields.update(overrides)
    return Listing.objects.create(**fields)


# --- nullable price ---------------------------------------------------------


def test_price_field_is_nullable_decimal_without_default():
    from listings.models import Listing

    field = Listing._meta.get_field("price")
    assert isinstance(field, models.DecimalField)
    assert field.max_digits == 12
    assert field.decimal_places == 2
    assert field.null is True
    assert field.default is NOT_PROVIDED


def test_listing_accepts_null_price(raw_listing, sku):
    listing = _listing(raw_listing, sku, price=None)
    listing.refresh_from_db()
    assert listing.price is None


def test_existing_non_null_decimal_price_remains_valid(raw_listing, sku):
    listing = _listing(raw_listing, sku, price=Decimal("15500.25"))
    listing.refresh_from_db()
    assert listing.price == Decimal("15500.25")
    assert isinstance(listing.price, Decimal)


def test_negative_non_null_price_remains_rejected(raw_listing, sku):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _listing(raw_listing, sku, price=Decimal("-0.01"))


# --- nullable condition -----------------------------------------------------


def test_condition_field_is_nullable_without_default():
    from listings.models import Listing

    field = Listing._meta.get_field("condition")
    assert isinstance(field, models.CharField)
    assert field.max_length == 20
    assert field.null is True
    assert field.default is NOT_PROVIDED


def test_listing_accepts_null_condition(raw_listing, sku):
    listing = _listing(raw_listing, sku, condition=None)
    listing.refresh_from_db()
    assert listing.condition is None


@pytest.mark.parametrize("condition", ["new", "like_new", "used", "for_parts"])
def test_existing_condition_values_remain_valid(raw_listing, sku, condition):
    listing = _listing(raw_listing, sku, condition=condition)
    listing.refresh_from_db()
    assert listing.condition == condition


def test_invalid_non_null_condition_remains_rejected(raw_listing, sku):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _listing(raw_listing, sku, condition="not_a_real_condition")


# --- resolution method ------------------------------------------------------


def test_unresolved_is_in_resolution_method_choices():
    from listings.models import Listing, RESOLUTION_METHOD_CHOICES

    assert ("unresolved", "Unresolved") in RESOLUTION_METHOD_CHOICES
    field = Listing._meta.get_field("resolution_method")
    assert ("unresolved", "Unresolved") in field.choices


def test_listing_accepts_unresolved_resolution_method(raw_listing):
    listing = _listing(
        raw_listing,
        None,
        resolution_method="unresolved",
        resolution_confidence=Decimal("0.0000"),
    )
    listing.refresh_from_db()
    assert listing.sku is None
    assert listing.resolution_method == "unresolved"
    assert listing.resolution_confidence == Decimal("0.0000")


@pytest.mark.parametrize(
    "resolution_method",
    ["exact_alias", "fuzzy_match", "human_confirmed"],
)
def test_existing_resolution_methods_remain_valid(raw_listing, sku, resolution_method):
    listing = _listing(raw_listing, sku, resolution_method=resolution_method)
    listing.refresh_from_db()
    assert listing.resolution_method == resolution_method


def test_unknown_resolution_method_remains_rejected(raw_listing, sku):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _listing(raw_listing, sku, resolution_method="not_a_real_method")


# --- historical compatibility and unrelated field state -------------------


def test_historical_null_sku_fuzzy_match_state_remains_valid(raw_listing):
    listing = _listing(
        raw_listing,
        None,
        resolution_method="fuzzy_match",
        resolution_confidence=Decimal("0.0000"),
    )
    listing.refresh_from_db()
    assert listing.sku is None
    assert listing.resolution_method == "fuzzy_match"
    assert listing.resolution_confidence == Decimal("0.0000")


def test_unrelated_listing_field_metadata_is_unchanged():
    from listings.models import Listing

    sku_field = Listing._meta.get_field("sku")
    assert sku_field.null is True
    assert sku_field.blank is True
    assert sku_field.default is NOT_PROVIDED
    assert sku_field.remote_field.on_delete is SET_NULL

    confidence_field = Listing._meta.get_field("resolution_confidence")
    assert isinstance(confidence_field, models.DecimalField)
    assert confidence_field.max_digits == 5
    assert confidence_field.decimal_places == 4
    assert confidence_field.null is False
    assert confidence_field.default is NOT_PROVIDED

    method_field = Listing._meta.get_field("resolution_method")
    assert isinstance(method_field, models.CharField)
    assert method_field.max_length == 20
    assert method_field.null is False
    assert method_field.default is NOT_PROVIDED

    resolved_at_field = Listing._meta.get_field("resolved_at")
    assert isinstance(resolved_at_field, models.DateTimeField)
    assert resolved_at_field.null is False
    assert resolved_at_field.default is NOT_PROVIDED

    for field_name in ("observed_at", "price_kind", "trade_side"):
        field = Listing._meta.get_field(field_name)
        assert field.null is True
        assert field.blank is True
        assert field.default is None
