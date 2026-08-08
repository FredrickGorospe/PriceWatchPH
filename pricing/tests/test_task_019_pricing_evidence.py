"""Frozen TASK_019 schema and immutable-evidence acceptance tests."""

from datetime import date, timedelta
from decimal import Decimal
from itertools import count

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, ProgrammingError, connection, models, transaction
from django.db.models.deletion import PROTECT
from django.db.models.fields import NOT_PROVIDED
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone


AUDIT_FIELD_NAMES = (
    "mad",
    "window_start_day",
    "window_end_day",
    "calculated_at",
    "calculation_contract_version",
)


@pytest.fixture
def sku(db):
    from catalogue.models import Sku

    return Sku.objects.create(
        brand="Synthetic",
        model="TASK 019 GPU",
        variant="",
        category="gpu",
        launch_msrp=Decimal("34995.00"),
        launch_date=date(2026, 1, 1),
    )


@pytest.fixture
def source(db):
    from sources.models import Source

    return Source.objects.create(
        name="task_019_source",
        base_url="https://example.invalid",
        terms_notes="Synthetic TASK_019 fixture",
        rate_limit=None,
    )


@pytest.fixture
def listing_factory(db, sku, source):
    from ingestion.models import RawListing
    from listings.models import Listing

    sequence = count(1)

    def make():
        number = next(sequence)
        raw_listing = RawListing.objects.create(
            source=source,
            raw_title=f"Synthetic TASK 019 listing {number}",
            raw_price_text="15500.00",
            raw_price=Decimal("15500.00"),
            url=f"https://example.invalid/task-019/{number}",
            seller="seller_anon_token",
            fetched_at=timezone.now(),
            external_id=f"task-019-{number}",
        )
        return Listing.objects.create(
            raw_listing=raw_listing,
            sku=sku,
            price=Decimal("15500.00"),
            condition="used",
            location="Metro Manila",
            resolution_confidence=Decimal("1.0000"),
            resolution_method="exact_alias",
            resolved_at=timezone.now(),
            observed_at=raw_listing.fetched_at,
            price_kind="asking",
            trade_side=None,
        )

    return make


def _core_pricepoint_fields(sku, snapshot_day):
    return {
        "sku": sku,
        "condition": "used",
        "day": snapshot_day,
        "median": Decimal("15000.0000"),
        "p25": Decimal("14000.0000"),
        "p75": Decimal("16000.0000"),
        "n_listings": 5,
    }


def _audit_fields(snapshot_day):
    return {
        "mad": Decimal("1000.0000"),
        "window_start_day": snapshot_day - timedelta(days=90),
        "window_end_day": snapshot_day,
        "calculated_at": timezone.now(),
        "calculation_contract_version": "synthetic_contract_v1",
    }


@pytest.fixture
def legacy_pricepoint_factory(db, sku):
    from pricing.models import PricePoint

    sequence = count(0)

    def make(**overrides):
        snapshot_day = date(2026, 8, 1) + timedelta(days=next(sequence))
        fields = _core_pricepoint_fields(sku, snapshot_day)
        fields.update(overrides)
        return PricePoint.objects.create(**fields)

    return make


@pytest.fixture
def auditable_pricepoint_factory(db, sku):
    from pricing.models import PricePoint

    sequence = count(0)

    def make(**overrides):
        snapshot_day = overrides.pop(
            "day",
            date(2026, 9, 1) + timedelta(days=next(sequence)),
        )
        fields = _core_pricepoint_fields(sku, snapshot_day)
        fields.update(_audit_fields(snapshot_day))
        fields.update(overrides)
        return PricePoint.objects.create(**fields)

    return make


@pytest.fixture
def deal_flag_factory(db, listing_factory, legacy_pricepoint_factory):
    from pricing.models import DealFlag

    def make(**overrides):
        fields = {
            "listing": listing_factory(),
            "baseline_pricepoint": legacy_pricepoint_factory(),
            "score": Decimal("-3.0000"),
            "reason": "legacy arbitrary explanation remains valid",
            "flagged_at": timezone.now(),
        }
        fields.update(overrides)
        return DealFlag.objects.create(**fields)

    return make


# --- PricePoint schema and legacy compatibility ----------------------------


@pytest.mark.parametrize("field_name", ["median", "p25", "p75", "mad"])
def test_pricepoint_aggregate_fields_have_safe_four_place_precision(field_name):
    from pricing.models import PricePoint

    field = PricePoint._meta.get_field(field_name)
    assert isinstance(field, models.DecimalField)
    assert field.max_digits == 14
    assert field.decimal_places == 4


def test_pricepoint_new_audit_field_metadata_is_exact():
    from pricing.models import PricePoint

    mad = PricePoint._meta.get_field("mad")
    assert mad.null is True
    assert mad.blank is True
    assert mad.default is NOT_PROVIDED

    for field_name in ("window_start_day", "window_end_day"):
        field = PricePoint._meta.get_field(field_name)
        assert isinstance(field, models.DateField)
        assert not isinstance(field, models.DateTimeField)
        assert field.null is True
        assert field.blank is True
        assert field.default is NOT_PROVIDED

    calculated_at = PricePoint._meta.get_field("calculated_at")
    assert isinstance(calculated_at, models.DateTimeField)
    assert calculated_at.null is True
    assert calculated_at.blank is True
    assert calculated_at.default is NOT_PROVIDED

    version = PricePoint._meta.get_field("calculation_contract_version")
    assert isinstance(version, models.CharField)
    assert version.max_length == 64
    assert version.null is True
    assert version.blank is True
    assert version.default is NOT_PROVIDED


def test_truthful_all_null_legacy_pricepoint_remains_valid(legacy_pricepoint_factory):
    pricepoint = legacy_pricepoint_factory()
    pricepoint.refresh_from_db()
    assert all(getattr(pricepoint, field_name) is None for field_name in AUDIT_FIELD_NAMES)


def test_complete_auditable_pricepoint_remains_valid(auditable_pricepoint_factory):
    pricepoint = auditable_pricepoint_factory(
        median=Decimal("15000.0025"),
        p25=Decimal("14000.0025"),
        p75=Decimal("16000.0025"),
        mad=Decimal("1000.0025"),
    )
    pricepoint.refresh_from_db()
    assert pricepoint.median == Decimal("15000.0025")
    assert pricepoint.p25 == Decimal("14000.0025")
    assert pricepoint.p75 == Decimal("16000.0025")
    assert pricepoint.mad == Decimal("1000.0025")
    assert all(getattr(pricepoint, field_name) is not None for field_name in AUDIT_FIELD_NAMES)


@pytest.mark.parametrize("missing_field", AUDIT_FIELD_NAMES)
def test_partially_populated_audit_metadata_is_rejected(
    sku,
    missing_field,
):
    from pricing.models import PricePoint

    snapshot_day = date(2026, 10, 1)
    fields = _core_pricepoint_fields(sku, snapshot_day)
    fields.update(_audit_fields(snapshot_day))
    fields[missing_field] = None

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PricePoint.objects.create(**fields)


def test_blank_calculation_contract_version_is_rejected(sku):
    from pricing.models import PricePoint

    snapshot_day = date(2026, 10, 2)
    fields = _core_pricepoint_fields(sku, snapshot_day)
    fields.update(_audit_fields(snapshot_day))
    fields["calculation_contract_version"] = ""

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PricePoint.objects.create(**fields)


def test_negative_mad_is_rejected(sku):
    from pricing.models import PricePoint

    snapshot_day = date(2026, 10, 3)
    fields = _core_pricepoint_fields(sku, snapshot_day)
    fields.update(_audit_fields(snapshot_day))
    fields["mad"] = Decimal("-0.0001")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PricePoint.objects.create(**fields)


@pytest.mark.parametrize(
    "window_start_day",
    [date(2026, 10, 4), date(2026, 10, 5)],
)
def test_unordered_window_bounds_are_rejected(sku, window_start_day):
    from pricing.models import PricePoint

    snapshot_day = date(2026, 10, 4)
    fields = _core_pricepoint_fields(sku, snapshot_day)
    fields.update(_audit_fields(snapshot_day))
    fields["window_start_day"] = window_start_day
    fields["window_end_day"] = snapshot_day

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PricePoint.objects.create(**fields)


def test_existing_pricepoint_identity_remains_unique(legacy_pricepoint_factory, sku):
    from pricing.models import PricePoint

    existing = legacy_pricepoint_factory()
    fields = _core_pricepoint_fields(sku, existing.day)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PricePoint.objects.create(**fields)


# --- PricePoint immutability -----------------------------------------------


def test_pricepoint_model_save_rejects_update(legacy_pricepoint_factory):
    pricepoint = legacy_pricepoint_factory()
    pricepoint.n_listings = 99
    with pytest.raises(ValidationError, match="immutable"):
        pricepoint.save()


def test_pricepoint_model_delete_is_rejected(legacy_pricepoint_factory):
    pricepoint = legacy_pricepoint_factory()
    with pytest.raises(ValidationError, match="immutable"):
        pricepoint.delete()


def test_pricepoint_queryset_update_is_rejected_by_postgresql(legacy_pricepoint_factory):
    from pricing.models import PricePoint

    pricepoint = legacy_pricepoint_factory()
    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            PricePoint.objects.filter(pk=pricepoint.pk).update(n_listings=99)


def test_pricepoint_queryset_delete_is_rejected_by_postgresql(legacy_pricepoint_factory):
    from pricing.models import PricePoint

    pricepoint = legacy_pricepoint_factory()
    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            PricePoint.objects.filter(pk=pricepoint.pk).delete()


def test_pricepoint_raw_sql_update_is_rejected(legacy_pricepoint_factory):
    pricepoint = legacy_pricepoint_factory()
    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE pricing_pricepoint SET n_listings = %s WHERE id = %s",
                    [99, pricepoint.pk],
                )


def test_pricepoint_raw_sql_delete_is_rejected(legacy_pricepoint_factory):
    pricepoint = legacy_pricepoint_factory()
    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM pricing_pricepoint WHERE id = %s",
                    [pricepoint.pk],
                )


# --- DealFlag schema, compatibility, and immutability ---------------------


def test_dealflag_score_has_safe_four_place_capacity():
    from pricing.models import DealFlag

    field = DealFlag._meta.get_field("score")
    assert isinstance(field, models.DecimalField)
    assert field.max_digits == 18
    assert field.decimal_places == 4


def test_dealflag_score_supported_extreme_round_trips(deal_flag_factory):
    score = Decimal("-99999999999900.0000")
    flag = deal_flag_factory(score=score)
    flag.refresh_from_db()
    assert flag.score == score
    assert isinstance(flag.score, Decimal)


def test_dealflag_retains_foreign_key_and_frozen_constraints():
    from pricing.models import DealFlag

    listing_field = DealFlag._meta.get_field("listing")
    assert isinstance(listing_field, models.ForeignKey)
    assert not isinstance(listing_field, models.OneToOneField)
    assert listing_field.remote_field.related_name == "deal_flags"
    assert listing_field.remote_field.on_delete is PROTECT

    baseline_field = DealFlag._meta.get_field("baseline_pricepoint")
    assert baseline_field.remote_field.on_delete is PROTECT

    constraints = {constraint.name: constraint for constraint in DealFlag._meta.constraints}
    assert tuple(constraints["dealflag_listing_unique"].fields) == ("listing",)
    assert tuple(constraints["dealflag_listing_baseline_unique"].fields) == (
        "listing",
        "baseline_pricepoint",
    )


def test_second_dealflag_for_listing_with_different_baseline_is_rejected(
    listing_factory,
    legacy_pricepoint_factory,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    first_baseline = legacy_pricepoint_factory()
    second_baseline = legacy_pricepoint_factory()
    DealFlag.objects.create(
        listing=listing,
        baseline_pricepoint=first_baseline,
        score=Decimal("-3.0000"),
        reason="first legacy reason",
        flagged_at=timezone.now(),
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DealFlag.objects.create(
                listing=listing,
                baseline_pricepoint=second_baseline,
                score=Decimal("-4.0000"),
                reason="second legacy reason",
                flagged_at=timezone.now(),
            )


def test_arbitrary_legacy_reason_and_outcome_relationship_remain_valid(deal_flag_factory):
    from outcomes.models import Outcome

    reason = "historical prose: price looked unusual under an older rule"
    flag = deal_flag_factory(reason=reason)
    outcome = Outcome.objects.create(
        deal_flag=flag,
        acted=False,
        skip_reason="synthetic compatibility check",
        bought_at=None,
        bought_price=None,
        sold_at=None,
        sold_price=None,
        days_held=None,
    )
    flag.refresh_from_db()
    outcome.refresh_from_db()
    assert flag.reason == reason
    assert outcome.deal_flag_id == flag.pk


def test_dealflag_model_save_rejects_update(deal_flag_factory):
    flag = deal_flag_factory()
    flag.reason = "changed"
    with pytest.raises(ValidationError, match="immutable"):
        flag.save()


def test_dealflag_model_delete_is_rejected(deal_flag_factory):
    flag = deal_flag_factory()
    with pytest.raises(ValidationError, match="immutable"):
        flag.delete()


def test_dealflag_queryset_update_is_rejected_by_postgresql(deal_flag_factory):
    from pricing.models import DealFlag

    flag = deal_flag_factory()
    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            DealFlag.objects.filter(pk=flag.pk).update(reason="changed")


def test_dealflag_queryset_delete_is_rejected_by_postgresql(deal_flag_factory):
    from pricing.models import DealFlag

    flag = deal_flag_factory()
    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            DealFlag.objects.filter(pk=flag.pk).delete()


def test_dealflag_raw_sql_update_is_rejected(deal_flag_factory):
    flag = deal_flag_factory()
    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE pricing_dealflag SET reason = %s WHERE id = %s",
                    ["changed", flag.pk],
                )


def test_dealflag_raw_sql_delete_is_rejected(deal_flag_factory):
    flag = deal_flag_factory()
    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM pricing_dealflag WHERE id = %s",
                    [flag.pk],
                )


# --- Read-only pricing evidence admin -------------------------------------


@pytest.mark.parametrize("model_name", ["pricepoint", "dealflag"])
def test_pricing_admin_contract_is_view_only(
    model_name,
    admin_user,
):
    from pricing.models import DealFlag, PricePoint

    model = PricePoint if model_name == "pricepoint" else DealFlag
    model_admin = admin.site._registry[model]
    request = RequestFactory().get("/admin/")
    request.user = admin_user

    assert model_admin.has_view_permission(request) is True
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False
    assert model_admin.get_actions(request) == {}

    readonly_fields = set(model_admin.get_readonly_fields(request))
    concrete_fields = {field.name for field in model._meta.fields}
    assert concrete_fields <= readonly_fields


@pytest.mark.parametrize("model_name", ["pricepoint", "dealflag"])
def test_existing_pricing_evidence_is_viewable_in_admin(
    model_name,
    admin_client,
    legacy_pricepoint_factory,
    deal_flag_factory,
):
    obj = (
        legacy_pricepoint_factory()
        if model_name == "pricepoint"
        else deal_flag_factory()
    )
    response = admin_client.get(
        reverse(f"admin:pricing_{model_name}_change", args=[obj.pk])
    )
    assert response.status_code == 200


@pytest.mark.parametrize("model_name", ["pricepoint", "dealflag"])
@pytest.mark.parametrize("operation", ["add", "change", "delete"])
def test_forged_pricing_admin_mutation_is_rejected(
    model_name,
    operation,
    admin_client,
    legacy_pricepoint_factory,
    deal_flag_factory,
):
    from pricing.models import DealFlag, PricePoint

    model = PricePoint if model_name == "pricepoint" else DealFlag
    obj = (
        legacy_pricepoint_factory()
        if model_name == "pricepoint"
        else deal_flag_factory()
    )
    count_before = model.objects.count()

    if operation == "add":
        url = reverse(f"admin:pricing_{model_name}_add")
        data = {}
    elif operation == "change":
        url = reverse(f"admin:pricing_{model_name}_change", args=[obj.pk])
        data = {"reason": "forged", "n_listings": "999"}
    else:
        url = reverse(f"admin:pricing_{model_name}_delete", args=[obj.pk])
        data = {"post": "yes"}

    response = admin_client.post(url, data)
    assert response.status_code == 403
    assert model.objects.count() == count_before
    assert model.objects.filter(pk=obj.pk).exists()
