"""Synthetic TASK_016 fixtures only; these tests do not measure market accuracy."""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from itertools import count

import pytest
from django.contrib.admin.models import LogEntry
from django.core.management import call_command
from django.db import models
from django.db.models.fields import NOT_PROVIDED
from django.utils import timezone


MARKER = datetime(2026, 7, 1, 4, 0, tzinfo=dt_timezone.utc)
OLD_RESOLVED_AT = datetime(2021, 1, 1, 0, 0, tzinfo=dt_timezone.utc)
_OMITTED = object()


def _resolve(raw_listing):
    from listings.resolver import resolve_raw_listing

    return resolve_raw_listing(raw_listing)


@pytest.fixture
def source(db):
    from sources.models import Source

    return Source.objects.create(
        name="task_016_source",
        base_url="https://example.invalid",
        terms_notes="synthetic TASK_016 fixture",
        rate_limit=None,
    )


@pytest.fixture
def raw_listing_factory(db, source):
    from ingestion.models import RawListing

    sequence = count(1)

    def make(
        *,
        raw_title="Synthetic unresolved GPU",
        raw_price=Decimal("15500.00"),
        raw_price_text="15500",
        payload=None,
    ):
        return RawListing.objects.create(
            source=source,
            raw_title=raw_title,
            raw_price=raw_price,
            raw_price_text=raw_price_text,
            url="https://example.invalid/listing",
            seller="anon",
            fetched_at=timezone.now(),
            occurred_at=None,
            external_id=f"task-016-{next(sequence)}",
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


def _listing(
    raw_listing,
    *,
    sku=None,
    resolution_method="unresolved",
    resolution_confidence=Decimal("0.0000"),
    reviewed_unresolved_at=MARKER,
    **overrides,
):
    from listings.models import Listing

    fields = {
        "raw_listing": raw_listing,
        "sku": sku,
        "price": raw_listing.raw_price,
        "condition": None,
        "location": "",
        "resolution_confidence": resolution_confidence,
        "resolution_method": resolution_method,
        "resolved_at": OLD_RESOLVED_AT,
        "observed_at": raw_listing.fetched_at,
        "price_kind": None,
        "trade_side": None,
    }
    if reviewed_unresolved_at is not _OMITTED:
        fields["reviewed_unresolved_at"] = reviewed_unresolved_at
    fields.update(overrides)
    return Listing.objects.create(**fields)


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


def _listing_state(listing):
    return (
        listing.raw_listing_id,
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
        listing.reviewed_unresolved_at,
    )


# --- schema ----------------------------------------------------------------


def test_reviewed_unresolved_at_field_contract():
    from listings.models import Listing

    field = Listing._meta.get_field("reviewed_unresolved_at")
    assert isinstance(field, models.DateTimeField)
    assert field.null is True
    assert field.blank is True
    assert field.default is NOT_PROVIDED
    assert field.db_default is NOT_PROVIDED


def test_existing_listing_creation_uses_null_review_marker(raw_listing_factory):
    raw = raw_listing_factory()
    listing = _listing(raw, reviewed_unresolved_at=_OMITTED)

    listing.refresh_from_db()
    assert listing.reviewed_unresolved_at is None


# --- current TASK_014 result transitions ----------------------------------


def test_unresolved_to_unresolved_preserves_marker_and_resolved_at(raw_listing_factory):
    from listings.models import Listing

    raw = raw_listing_factory(raw_title="Still unresolved synthetic GPU")
    listing = _listing(raw)

    returned = _resolve(raw)
    returned.refresh_from_db()

    assert returned.pk == listing.pk
    assert returned.sku is None
    assert returned.resolution_method == "unresolved"
    assert returned.resolution_confidence == Decimal("0.0000")
    assert returned.reviewed_unresolved_at == MARKER
    assert returned.resolved_at == OLD_RESOLVED_AT
    assert Listing.objects.filter(raw_listing=raw).count() == 1


def test_unresolved_to_exact_alias_clears_marker(raw_listing_factory, sku_factory):
    raw = raw_listing_factory(raw_title="Promoted synthetic GPU")
    listing = _listing(raw)
    sku = sku_factory(model="Promoted target")
    _alias(sku, raw.raw_title)
    before = timezone.now()

    returned = _resolve(raw)
    returned.refresh_from_db()

    assert returned.pk == listing.pk
    assert returned.sku == sku
    assert returned.resolution_method == "exact_alias"
    assert returned.resolution_confidence == Decimal("1.0000")
    assert returned.reviewed_unresolved_at is None
    assert returned.resolved_at >= before


def test_exact_alias_to_unresolved_clears_marker(raw_listing_factory, sku_factory):
    raw = raw_listing_factory(raw_title="Removed alias synthetic GPU")
    old_sku = sku_factory(model="Removed target")
    listing = _listing(
        raw,
        sku=old_sku,
        resolution_method="exact_alias",
        resolution_confidence=Decimal("1.0000"),
    )
    before = timezone.now()

    returned = _resolve(raw)
    returned.refresh_from_db()

    assert returned.pk == listing.pk
    assert returned.sku is None
    assert returned.resolution_method == "unresolved"
    assert returned.resolution_confidence == Decimal("0.0000")
    assert returned.reviewed_unresolved_at is None
    assert returned.resolved_at >= before


def test_exact_alias_repoint_clears_marker(raw_listing_factory, sku_factory):
    raw = raw_listing_factory(raw_title="Repointed synthetic GPU")
    old_sku = sku_factory(model="Old alias target")
    new_sku = sku_factory(model="New alias target")
    listing = _listing(
        raw,
        sku=old_sku,
        resolution_method="exact_alias",
        resolution_confidence=Decimal("1.0000"),
    )
    _alias(new_sku, raw.raw_title)
    before = timezone.now()

    returned = _resolve(raw)
    returned.refresh_from_db()

    assert returned.pk == listing.pk
    assert returned.sku == new_sku
    assert returned.resolution_method == "exact_alias"
    assert returned.resolution_confidence == Decimal("1.0000")
    assert returned.reviewed_unresolved_at is None
    assert returned.resolved_at >= before


def test_unchanged_exact_alias_preserves_marker_and_resolved_at(
    raw_listing_factory,
    sku_factory,
):
    raw = raw_listing_factory(raw_title="Stable exact synthetic GPU")
    sku = sku_factory(model="Stable exact target")
    _alias(sku, raw.raw_title)
    listing = _listing(
        raw,
        sku=sku,
        resolution_method="exact_alias",
        resolution_confidence=Decimal("1.0000"),
    )

    returned = _resolve(raw)
    returned.refresh_from_db()

    assert returned.pk == listing.pk
    assert returned.sku == sku
    assert returned.resolution_method == "exact_alias"
    assert returned.reviewed_unresolved_at == MARKER
    assert returned.resolved_at == OLD_RESOLVED_AT


def test_human_confirmed_preserves_marker_and_every_listing_field(
    raw_listing_factory,
    sku_factory,
):
    raw = raw_listing_factory(
        raw_title="Human confirmed synthetic GPU",
        raw_price=Decimal("15500.00"),
        payload={"stated_condition": "used", "stated_trade_side": "buy"},
    )
    confirmed_sku = sku_factory(model="Human confirmed target")
    conflicting_sku = sku_factory(model="Conflicting automatic target")
    _alias(conflicting_sku, raw.raw_title)
    listing = _listing(
        raw,
        sku=confirmed_sku,
        resolution_method="human_confirmed",
        resolution_confidence=Decimal("1.0000"),
        price=Decimal("14000.00"),
        condition="for_parts",
        location="Cebu City",
        observed_at=OLD_RESOLVED_AT,
        price_kind="realised",
        trade_side="sell",
    )
    expected = _listing_state(listing)

    returned = _resolve(raw)
    returned.refresh_from_db()

    assert returned.pk == listing.pk
    assert _listing_state(returned) == expected


# --- historical compatibility ---------------------------------------------


def test_historical_fuzzy_to_unresolved_clears_marker(raw_listing_factory):
    raw = raw_listing_factory(raw_title="Historical fuzzy miss")
    listing = _listing(
        raw,
        resolution_method="fuzzy_match",
        resolution_confidence=Decimal("0.0000"),
    )

    returned = _resolve(raw)
    returned.refresh_from_db()

    assert returned.pk == listing.pk
    assert returned.sku is None
    assert returned.resolution_method == "unresolved"
    assert returned.resolution_confidence == Decimal("0.0000")
    assert returned.reviewed_unresolved_at is None
    assert returned.resolved_at > OLD_RESOLVED_AT


def test_historical_fuzzy_to_exact_alias_clears_marker(raw_listing_factory, sku_factory):
    raw = raw_listing_factory(raw_title="Historical fuzzy exact")
    listing = _listing(
        raw,
        resolution_method="fuzzy_match",
        resolution_confidence=Decimal("0.0000"),
    )
    sku = sku_factory(model="Historical fuzzy exact target")
    _alias(sku, raw.raw_title)

    returned = _resolve(raw)
    returned.refresh_from_db()

    assert returned.pk == listing.pk
    assert returned.sku == sku
    assert returned.resolution_method == "exact_alias"
    assert returned.resolution_confidence == Decimal("1.0000")
    assert returned.reviewed_unresolved_at is None
    assert returned.resolved_at > OLD_RESOLVED_AT


def test_historical_null_sku_fuzzy_match_remains_valid(raw_listing_factory):
    raw = raw_listing_factory(raw_title="Historical compatible fuzzy state")
    listing = _listing(
        raw,
        resolution_method="fuzzy_match",
        resolution_confidence=Decimal("0.0000"),
        reviewed_unresolved_at=_OMITTED,
    )

    listing.refresh_from_db()
    assert listing.sku is None
    assert listing.resolution_method == "fuzzy_match"
    assert listing.resolution_confidence == Decimal("0.0000")
    assert listing.reviewed_unresolved_at is None


# --- existing resolver and command invariants -----------------------------


@pytest.mark.parametrize(
    ("has_alias", "expected_method", "expected_confidence"),
    [
        (False, "unresolved", Decimal("0.0000")),
        (True, "exact_alias", Decimal("1.0000")),
    ],
)
def test_new_machine_results_never_emit_fuzzy_and_keep_confidence_semantics(
    raw_listing_factory,
    sku_factory,
    has_alias,
    expected_method,
    expected_confidence,
):
    raw = raw_listing_factory(raw_title=f"New machine result {has_alias}")
    if has_alias:
        _alias(sku_factory(model="New exact target"), raw.raw_title)

    listing = _resolve(raw)

    assert listing.resolution_method == expected_method
    assert listing.resolution_method != "fuzzy_match"
    assert listing.resolution_confidence == expected_confidence
    assert listing.reviewed_unresolved_at is None


def test_resolver_does_not_mutate_rawlisting(raw_listing_factory, sku_factory):
    raw = raw_listing_factory(
        raw_title="  Immutable RTX4070-Ti  ",
        raw_price=Decimal("15500.00"),
        raw_price_text="15,500",
        payload={"stated_condition": "used"},
    )
    _listing(raw)
    _alias(sku_factory(model="Immutable target"), raw.raw_title)
    before = _raw_state(raw)

    _resolve(raw)
    raw.refresh_from_db()

    assert _raw_state(raw) == before


def test_resolver_creates_no_catalogue_admin_or_downstream_state(
    raw_listing_factory,
    source,
):
    from catalogue.models import Sku, SkuAlias
    from ingestion.models import RawListing, Swap
    from listings.models import Listing
    from outcomes.models import Outcome
    from pricing.models import DealFlag, PricePoint

    raw = raw_listing_factory(raw_title="No automatic catalogue match")
    before = {
        "raw": RawListing.objects.count(),
        "sku": Sku.objects.count(),
        "alias": SkuAlias.objects.count(),
        "pricepoint": PricePoint.objects.count(),
        "dealflag": DealFlag.objects.count(),
        "outcome": Outcome.objects.count(),
        "swap": Swap.objects.count(),
        "admin_log": LogEntry.objects.count(),
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
    assert LogEntry.objects.count() == before["admin_log"]
    source.refresh_from_db()
    assert source.last_successful_fetch is None


def test_operational_command_inherits_review_marker_transitions(
    raw_listing_factory,
    sku_factory,
):
    from listings.models import Listing

    stable_raw = raw_listing_factory(raw_title="Command stable unresolved")
    stable = _listing(stable_raw)

    changed_raw = raw_listing_factory(raw_title="Command exact becomes unresolved")
    old_sku = sku_factory(model="Command removed target")
    changed = _listing(
        changed_raw,
        sku=old_sku,
        resolution_method="exact_alias",
        resolution_confidence=Decimal("1.0000"),
    )

    call_command("resolve_listings", verbosity=0)
    stable.refresh_from_db()
    changed.refresh_from_db()

    assert stable.resolution_method == "unresolved"
    assert stable.reviewed_unresolved_at == MARKER
    assert stable.resolved_at == OLD_RESOLVED_AT
    assert changed.sku is None
    assert changed.resolution_method == "unresolved"
    assert changed.reviewed_unresolved_at is None
    assert changed.resolved_at > OLD_RESOLVED_AT
    assert Listing.objects.count() == 2
