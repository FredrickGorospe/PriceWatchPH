"""Synthetic admin fixtures only; these tests do not measure market accuracy."""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from itertools import count
from unittest.mock import patch

import pytest
from django.contrib import admin
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone


OLD_RESOLVED_AT = datetime(2025, 1, 1, 0, 0, tzinfo=dt_timezone.utc)
REVIEWED_AT = datetime(2026, 7, 1, 4, 0, tzinfo=dt_timezone.utc)


@pytest.fixture
def source(db):
    from sources.models import Source

    return Source.objects.create(
        name="task_017_source",
        base_url="https://example.invalid",
        terms_notes="synthetic TASK_017 fixture",
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
        raw_price_text="PHP 15,500",
        fetched_at=None,
        occurred_at=None,
        payload=None,
        url="https://example.invalid/listing",
        seller="seller_anon_token",
        external_id=None,
        raw_source=None,
    ):
        number = next(sequence)
        return RawListing.objects.create(
            source=raw_source or source,
            raw_title=raw_title,
            raw_price=raw_price,
            raw_price_text=raw_price_text,
            url=url,
            seller=seller,
            fetched_at=fetched_at or timezone.now(),
            occurred_at=occurred_at,
            external_id=external_id or f"task-017-{number}",
            payload=payload,
        )

    return make


@pytest.fixture
def sku_factory(db):
    from catalogue.models import Sku

    sequence = count(1)

    def make(*, brand="Synthetic", model=None, variant=None, category="gpu"):
        number = next(sequence)
        return Sku.objects.create(
            brand=brand,
            model=model or f"GPU {number}",
            variant=variant if variant is not None else f"variant-{number}",
            category=category,
            launch_msrp=Decimal("10000.00"),
            launch_date=date(2026, 1, 1),
        )

    return make


@pytest.fixture
def listing_factory(db, raw_listing_factory):
    from listings.models import Listing

    def make(
        *,
        raw_listing=None,
        sku=None,
        resolution_method="unresolved",
        resolution_confidence=None,
        reviewed_unresolved_at=None,
        resolved_at=OLD_RESOLVED_AT,
        condition="used",
        location="Metro Manila",
        price_kind="realised",
        trade_side="buy",
    ):
        raw = raw_listing or raw_listing_factory()
        if resolution_confidence is None:
            resolution_confidence = (
                Decimal("1.0000")
                if resolution_method in {"exact_alias", "human_confirmed"}
                else Decimal("0.0000")
            )
        return Listing.objects.create(
            raw_listing=raw,
            sku=sku,
            price=raw.raw_price,
            condition=condition,
            location=location,
            resolution_confidence=resolution_confidence,
            resolution_method=resolution_method,
            resolved_at=resolved_at,
            reviewed_unresolved_at=reviewed_unresolved_at,
            observed_at=raw.occurred_at or raw.fetched_at,
            price_kind=price_kind,
            trade_side=trade_side,
        )

    return make


@pytest.fixture
def staff_user_factory(db, django_user_model):
    sequence = count(1)

    def make(*, is_staff=True, is_superuser=False):
        number = next(sequence)
        return django_user_model.objects.create_user(
            username=f"task017-user-{number}",
            password="test-password",
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    return make


def _grant(user, model, *actions):
    content_type = ContentType.objects.get_for_model(model)
    codenames = [f"{action}_{model._meta.model_name}" for action in actions]
    permissions = list(
        Permission.objects.filter(content_type=content_type, codename__in=codenames)
    )
    assert {permission.codename for permission in permissions} == set(codenames)
    user.user_permissions.add(*permissions)


def _listing_admin():
    from listings.models import Listing

    return admin.site._registry[Listing]


def _queue_ids(response):
    assert response.status_code == 200
    return [listing.pk for listing in response.context["cl"].result_list]


def _mark_reviewed_url(listing):
    return reverse(
        "admin:listings_listing_mark_reviewed_unresolved",
        args=[listing.pk],
    )


def _change_url(listing):
    return reverse("admin:listings_listing_change", args=[listing.pk])


def _listing_state(listing):
    return {
        "raw_listing_id": listing.raw_listing_id,
        "sku_id": listing.sku_id,
        "price": listing.price,
        "condition": listing.condition,
        "location": listing.location,
        "resolution_confidence": listing.resolution_confidence,
        "resolution_method": listing.resolution_method,
        "resolved_at": listing.resolved_at,
        "reviewed_unresolved_at": listing.reviewed_unresolved_at,
        "observed_at": listing.observed_at,
        "price_kind": listing.price_kind,
        "trade_side": listing.trade_side,
    }


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


def _audit_entries(listing):
    from listings.models import Listing

    content_type = ContentType.objects.get_for_model(Listing)
    return LogEntry.objects.filter(
        content_type=content_type,
        object_id=str(listing.pk),
        action_flag=CHANGE,
    )


def _post_confirmation(client, listing, sku, **extra):
    data = {"sku": "" if sku is None else str(sku.pk), "_save": "Save"}
    data.update(extra)
    return client.post(_change_url(listing), data)


def _split_datetime(data, field_name, value):
    if value is None:
        data[f"{field_name}_0"] = ""
        data[f"{field_name}_1"] = ""
        return
    value = value.astimezone(dt_timezone.utc)
    data[f"{field_name}_0"] = value.date().isoformat()
    data[f"{field_name}_1"] = value.time().replace(tzinfo=None).isoformat()


def _generic_change_payload(listing, *, sku_value):
    """A valid payload for the pre-TASK_017 generic ModelAdmin form."""
    data = {
        "raw_listing": str(listing.raw_listing_id),
        "sku": sku_value,
        "price": str(listing.price),
        "condition": listing.condition,
        "location": listing.location,
        "resolution_confidence": str(listing.resolution_confidence),
        "resolution_method": listing.resolution_method,
        "price_kind": listing.price_kind or "",
        "trade_side": listing.trade_side or "",
        "_save": "Save",
    }
    _split_datetime(data, "resolved_at", listing.resolved_at)
    _split_datetime(data, "reviewed_unresolved_at", listing.reviewed_unresolved_at)
    _split_datetime(data, "observed_at", listing.observed_at)
    return data


# --- primary queue and evidence -------------------------------------------


def test_default_review_queue_uses_locked_membership_predicate(
    admin_client,
    listing_factory,
    sku_factory,
):
    pending = listing_factory()
    historical_fuzzy = listing_factory(resolution_method="fuzzy_match")
    integrity_exact = listing_factory(resolution_method="exact_alias")
    integrity_human = listing_factory(resolution_method="human_confirmed")
    reviewed = listing_factory(reviewed_unresolved_at=REVIEWED_AT)
    matched_sku = sku_factory()
    matched = listing_factory(sku=matched_sku, resolution_method="exact_alias")

    response = admin_client.get(reverse("admin:listings_listing_changelist"))

    assert _queue_ids(response) == [
        pending.pk,
        historical_fuzzy.pk,
        integrity_exact.pk,
        integrity_human.pk,
    ]
    assert reviewed.pk not in _queue_ids(response)
    assert matched.pk not in _queue_ids(response)


def test_review_queue_orders_by_source_observation_then_listing_pk(
    admin_client,
    raw_listing_factory,
    listing_factory,
):
    newer = listing_factory(
        raw_listing=raw_listing_factory(
            fetched_at=datetime(2026, 5, 1, tzinfo=dt_timezone.utc),
        )
    )
    oldest = listing_factory(
        raw_listing=raw_listing_factory(
            fetched_at=datetime(2026, 6, 1, tzinfo=dt_timezone.utc),
            occurred_at=datetime(2020, 1, 1, tzinfo=dt_timezone.utc),
        )
    )
    tied_at = datetime(2024, 1, 1, tzinfo=dt_timezone.utc)
    tie_a = listing_factory(raw_listing=raw_listing_factory(fetched_at=tied_at))
    tie_b = listing_factory(raw_listing=raw_listing_factory(fetched_at=tied_at))

    response = admin_client.get(reverse("admin:listings_listing_changelist"))

    assert _queue_ids(response) == [oldest.pk, tie_a.pk, tie_b.pk, newer.pk]


def test_all_listings_scope_exposes_non_queue_rows_for_correction(
    admin_client,
    listing_factory,
    sku_factory,
):
    pending = listing_factory()
    reviewed = listing_factory(reviewed_unresolved_at=REVIEWED_AT)
    confirmed = listing_factory(
        sku=sku_factory(),
        resolution_method="human_confirmed",
    )

    response = admin_client.get(
        reverse("admin:listings_listing_changelist"),
        {"review_scope": "all"},
    )

    assert set(_queue_ids(response)) == {pending.pk, reviewed.pk, confirmed.pk}


def test_view_permission_can_inspect_complete_read_only_evidence(
    client,
    staff_user_factory,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from listings.models import Listing

    user = staff_user_factory()
    _grant(user, Listing, "view")
    client.force_login(user)
    raw = raw_listing_factory(
        raw_title="Evidence RTX 4070—12GB",
        raw_price_text="PHP 15,500 exact",
        url="https://example.invalid/evidence-url",
        seller="seller_safe_pseudonym_017",
        external_id="external-evidence-017",
        payload={"serial": "SYNTHETIC-SERIAL-017"},
        occurred_at=datetime(2026, 2, 3, 4, 5, tzinfo=dt_timezone.utc),
    )
    sku = sku_factory(
        brand="EvidenceBrand",
        model="EvidenceModel",
        variant="EvidenceVariant",
    )
    listing = listing_factory(
        raw_listing=raw,
        sku=sku,
        resolution_method="exact_alias",
        location="Evidence Location",
    )

    response = client.get(_change_url(listing))

    assert response.status_code == 200
    for text in (
        "RawListing ID",
        "External ID",
        "Raw title",
        "Normalised title",
        "Raw price text",
        "Raw price",
        "Source",
        "URL",
        "Seller",
        "Payload",
        "Current SKU",
        "SKU category",
        "Resolution method",
        "Resolution confidence",
        "Price kind",
        "Trade side",
        "Evidence RTX 4070—12GB",
        "evidence rtx 4070 12gb",
        "PHP 15,500 exact",
        "task_017_source",
        "https://example.invalid/evidence-url",
        "seller_safe_pseudonym_017",
        "external-evidence-017",
        "SYNTHETIC-SERIAL-017",
        "EvidenceBrand",
        "EvidenceModel",
        "EvidenceVariant",
        "Evidence Location",
        "Fetched at",
        "Occurred at",
        "Resolved at",
        "Observed at",
        "Reviewed unresolved at",
    ):
        assert text in response.content.decode()


def test_listing_admin_form_exposes_only_required_existing_sku(
    staff_user_factory,
    listing_factory,
):
    from listings.models import Listing

    user = staff_user_factory(is_superuser=True)
    listing = listing_factory()
    request = RequestFactory().get(_change_url(listing))
    request.user = user

    form_class = _listing_admin().get_form(request, obj=listing)

    assert tuple(form_class.base_fields) == ("sku",)
    assert form_class.base_fields["sku"].required is True
    assert set(form_class.base_fields).isdisjoint(
        field.name for field in Listing._meta.concrete_fields if field.name != "sku"
    )


def test_listing_admin_disables_add_delete_and_bulk_actions(
    staff_user_factory,
    listing_factory,
):
    user = staff_user_factory(is_superuser=True)
    listing = listing_factory()
    request = RequestFactory().get(reverse("admin:listings_listing_changelist"))
    request.user = user
    model_admin = _listing_admin()

    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_delete_permission(request, listing) is False
    assert model_admin.get_actions(request) == {}


def test_listing_add_and_delete_urls_are_blocked(admin_client, listing_factory):
    listing = listing_factory()

    assert admin_client.get(reverse("admin:listings_listing_add")).status_code == 403
    assert admin_client.get(
        reverse("admin:listings_listing_delete", args=[listing.pk])
    ).status_code == 403


def test_reviewed_unresolved_operation_is_exposed_only_for_eligible_rows(
    admin_client,
    listing_factory,
    sku_factory,
):
    eligible = listing_factory()
    fuzzy = listing_factory(resolution_method="fuzzy_match")
    null_exact = listing_factory(resolution_method="exact_alias")
    null_human = listing_factory(resolution_method="human_confirmed")
    matched_exact = listing_factory(
        sku=sku_factory(),
        resolution_method="exact_alias",
    )

    eligible_page = admin_client.get(_change_url(eligible)).content.decode()
    fuzzy_page = admin_client.get(_change_url(fuzzy)).content.decode()
    null_exact_page = admin_client.get(_change_url(null_exact)).content.decode()
    null_human_page = admin_client.get(_change_url(null_human)).content.decode()
    matched_exact_page = admin_client.get(_change_url(matched_exact)).content.decode()

    assert _mark_reviewed_url(eligible) in eligible_page
    assert _mark_reviewed_url(fuzzy) in fuzzy_page
    assert _mark_reviewed_url(null_exact) not in null_exact_page
    assert _mark_reviewed_url(null_human) not in null_human_page
    assert _mark_reviewed_url(matched_exact) not in matched_exact_page


# --- reviewed but unresolved ----------------------------------------------


def test_mark_reviewed_unresolved_endpoint_is_post_only(
    admin_client,
    listing_factory,
):
    listing = listing_factory()
    before_state = _listing_state(listing)

    response = admin_client.get(_mark_reviewed_url(listing))

    assert response.status_code == 405
    listing.refresh_from_db()
    assert _listing_state(listing) == before_state
    assert not _audit_entries(listing).exists()


def test_mark_unresolved_reviewed_sets_only_marker_and_logs_change(
    admin_client,
    listing_factory,
):
    listing = listing_factory()
    before_state = _listing_state(listing)
    before = timezone.now()

    response = admin_client.post(_mark_reviewed_url(listing))

    assert response.status_code == 302
    listing.refresh_from_db()
    after_state = _listing_state(listing)
    assert before <= listing.reviewed_unresolved_at <= timezone.now()
    before_state.pop("reviewed_unresolved_at")
    after_state.pop("reviewed_unresolved_at")
    assert after_state == before_state
    assert _audit_entries(listing).count() == 1


def test_historical_fuzzy_can_be_marked_reviewed_without_rewriting_evidence(
    admin_client,
    listing_factory,
):
    listing = listing_factory(
        resolution_method="fuzzy_match",
        resolution_confidence=Decimal("0.4321"),
    )
    before_state = _listing_state(listing)

    response = admin_client.post(_mark_reviewed_url(listing))

    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.reviewed_unresolved_at is not None
    assert listing.resolution_method == "fuzzy_match"
    assert listing.resolution_confidence == Decimal("0.4321")
    assert listing.resolved_at == before_state["resolved_at"]


@pytest.mark.parametrize(
    "case",
    ["null_human_confirmed", "null_exact_alias", "nonnull_unresolved"],
)
def test_mark_reviewed_unresolved_rejects_ineligible_states(
    admin_client,
    listing_factory,
    sku_factory,
    case,
):
    if case == "null_human_confirmed":
        listing = listing_factory(resolution_method="human_confirmed")
    elif case == "null_exact_alias":
        listing = listing_factory(resolution_method="exact_alias")
    else:
        listing = listing_factory(sku=sku_factory(), resolution_method="unresolved")
    before_state = _listing_state(listing)

    response = admin_client.post(_mark_reviewed_url(listing))

    assert response.status_code in {302, 400, 403}
    listing.refresh_from_db()
    assert _listing_state(listing) == before_state
    assert not _audit_entries(listing).exists()


def test_forged_reviewed_unresolved_post_cannot_change_protected_fields(
    admin_client,
    listing_factory,
    sku_factory,
):
    listing = listing_factory()
    forged_sku = sku_factory()
    before_state = _listing_state(listing)

    response = admin_client.post(
        _mark_reviewed_url(listing),
        {
            "sku": str(forged_sku.pk),
            "condition": "for_parts",
            "price": "1.00",
            "resolution_method": "human_confirmed",
            "resolution_confidence": "1.0000",
        },
    )

    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.reviewed_unresolved_at is not None
    after_state = _listing_state(listing)
    before_state.pop("reviewed_unresolved_at")
    after_state.pop("reviewed_unresolved_at")
    assert after_state == before_state


def test_mark_reviewed_unresolved_rolls_back_when_admin_logging_raises(
    admin_client,
    listing_factory,
):
    listing = listing_factory()
    before_state = _listing_state(listing)
    model_admin = _listing_admin()

    with patch.object(model_admin, "log_change", side_effect=RuntimeError("audit failed")):
        with pytest.raises(RuntimeError, match="audit failed"):
            admin_client.post(_mark_reviewed_url(listing))

    listing.refresh_from_db()
    assert _listing_state(listing) == before_state
    assert not _audit_entries(listing).exists()


def test_view_only_user_cannot_mark_reviewed_unresolved(
    client,
    staff_user_factory,
    listing_factory,
):
    from listings.models import Listing

    user = staff_user_factory()
    _grant(user, Listing, "view")
    client.force_login(user)
    listing = listing_factory()

    response = client.post(_mark_reviewed_url(listing))

    assert response.status_code == 403
    listing.refresh_from_db()
    assert listing.reviewed_unresolved_at is None
    assert not _audit_entries(listing).exists()


def test_nonstaff_user_cannot_access_review_mutations(
    client,
    staff_user_factory,
    listing_factory,
):
    from listings.models import Listing

    user = staff_user_factory(is_staff=False)
    _grant(user, Listing, "view", "change")
    client.force_login(user)
    listing = listing_factory()

    response = client.post(_mark_reviewed_url(listing))

    assert response.status_code == 302
    assert "/admin/login/" in response.url
    listing.refresh_from_db()
    assert listing.reviewed_unresolved_at is None


# --- human confirmation ---------------------------------------------------


def test_confirmation_selects_existing_sku_and_preserves_provenance(
    admin_client,
    listing_factory,
    sku_factory,
):
    listing = listing_factory(reviewed_unresolved_at=REVIEWED_AT)
    sku = sku_factory()
    before_state = _listing_state(listing)
    before = timezone.now()

    response = _post_confirmation(admin_client, listing, sku)

    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.sku == sku
    assert listing.resolution_method == "human_confirmed"
    assert listing.resolution_confidence == Decimal("1.0000")
    assert before <= listing.resolved_at <= timezone.now()
    assert listing.reviewed_unresolved_at is None
    for field_name in (
        "raw_listing_id",
        "price",
        "condition",
        "location",
        "observed_at",
        "price_kind",
        "trade_side",
    ):
        assert _listing_state(listing)[field_name] == before_state[field_name]


def test_human_confirmed_listing_can_be_corrected_to_another_existing_sku(
    admin_client,
    listing_factory,
    sku_factory,
):
    original_sku = sku_factory()
    corrected_sku = sku_factory()
    listing = listing_factory(
        sku=original_sku,
        resolution_method="human_confirmed",
        reviewed_unresolved_at=REVIEWED_AT,
    )
    old_resolved_at = listing.resolved_at
    before = timezone.now()

    response = _post_confirmation(admin_client, listing, corrected_sku)

    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.sku == corrected_sku
    assert listing.resolution_method == "human_confirmed"
    assert listing.resolution_confidence == Decimal("1.0000")
    assert listing.resolved_at > old_resolved_at
    assert listing.resolved_at >= before
    assert listing.reviewed_unresolved_at is None
    assert _audit_entries(listing).count() == 1


@pytest.mark.parametrize("sku_value", ["", "999999999"])
def test_confirmation_requires_an_existing_nonempty_sku(
    admin_client,
    listing_factory,
    sku_value,
):
    listing = listing_factory()
    before_state = _listing_state(listing)

    response = admin_client.post(
        _change_url(listing),
        {"sku": sku_value, "_save": "Save"},
    )

    assert response.status_code == 200
    listing.refresh_from_db()
    assert _listing_state(listing) == before_state
    assert not _audit_entries(listing).exists()


def test_forged_confirmation_fields_cannot_mutate_protected_state(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    listing = listing_factory()
    selected_sku = sku_factory()
    other_raw = raw_listing_factory(raw_title="Forged replacement raw")
    before_state = _listing_state(listing)

    response = _post_confirmation(
        admin_client,
        listing,
        selected_sku,
        raw_listing=str(other_raw.pk),
        price="1.00",
        condition="for_parts",
        location="FORGED LOCATION",
        resolution_method="fuzzy_match",
        resolution_confidence="0.1234",
        resolved_at_0="2001-01-01",
        resolved_at_1="00:00:00",
        reviewed_unresolved_at_0="2001-01-01",
        reviewed_unresolved_at_1="00:00:00",
        observed_at_0="2001-01-01",
        observed_at_1="00:00:00",
        price_kind="asking",
        trade_side="",
    )

    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.sku == selected_sku
    assert listing.resolution_method == "human_confirmed"
    assert listing.resolution_confidence == Decimal("1.0000")
    for field_name in (
        "raw_listing_id",
        "price",
        "condition",
        "location",
        "observed_at",
        "price_kind",
        "trade_side",
    ):
        assert _listing_state(listing)[field_name] == before_state[field_name]


def test_view_only_user_cannot_confirm_sku(
    client,
    staff_user_factory,
    listing_factory,
    sku_factory,
):
    from listings.models import Listing

    user = staff_user_factory()
    _grant(user, Listing, "view")
    client.force_login(user)
    listing = listing_factory()
    sku = sku_factory()
    before_state = _listing_state(listing)

    response = _post_confirmation(client, listing, sku)

    assert response.status_code == 403
    listing.refresh_from_db()
    assert _listing_state(listing) == before_state


def test_confirmation_rolls_back_when_admin_logging_raises(
    admin_client,
    listing_factory,
    sku_factory,
):
    listing = listing_factory()
    sku = sku_factory()
    before_state = _listing_state(listing)
    model_admin = _listing_admin()

    with patch.object(model_admin, "log_change", side_effect=RuntimeError("audit failed")):
        with pytest.raises(RuntimeError, match="audit failed"):
            _post_confirmation(admin_client, listing, sku)

    listing.refresh_from_db()
    assert _listing_state(listing) == before_state
    assert not _audit_entries(listing).exists()


def test_confirmation_creates_normal_admin_audit_entry(
    admin_client,
    listing_factory,
    sku_factory,
):
    listing = listing_factory()

    response = _post_confirmation(admin_client, listing, sku_factory())

    assert response.status_code == 302
    entry = _audit_entries(listing).get()
    assert entry.action_flag == CHANGE
    assert entry.change_message


def test_confirmed_listing_survives_direct_and_operational_resolver_reruns(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias
    from listings.management.commands.resolve_listings import Command
    from listings.normalisation import normalise_title
    from listings.resolver import resolve_raw_listing

    raw = raw_listing_factory(raw_title="Resolver should prefer alias target")
    confirmed_sku = sku_factory(model="Human target")
    alias_target = sku_factory(model="Machine alias target")
    SkuAlias.objects.create(
        sku=alias_target,
        alias_text=raw.raw_title,
        normalised_text=normalise_title(raw.raw_title),
        source_of_truth="seed",
    )
    listing = listing_factory(raw_listing=raw)
    assert _post_confirmation(admin_client, listing, confirmed_sku).status_code == 302
    listing.refresh_from_db()
    confirmed_state = _listing_state(listing)

    resolve_raw_listing(raw)
    Command().handle(verbosity=0)

    listing.refresh_from_db()
    assert _listing_state(listing) == confirmed_state


# --- deletion guard and boundaries ---------------------------------------


def test_human_confirmed_sku_individual_admin_delete_is_blocked(
    admin_client,
    listing_factory,
    sku_factory,
):
    from catalogue.models import Sku

    sku = sku_factory()
    listing = listing_factory(sku=sku, resolution_method="human_confirmed")

    response = admin_client.post(
        reverse("admin:catalogue_sku_delete", args=[sku.pk]),
        {"post": "yes"},
    )

    assert response.status_code in {200, 403}
    assert Sku.objects.filter(pk=sku.pk).exists()
    listing.refresh_from_db()
    assert listing.sku_id == sku.pk
    assert listing.resolution_method == "human_confirmed"


def test_human_confirmed_sku_bulk_admin_delete_is_blocked(
    admin_client,
    listing_factory,
    sku_factory,
):
    from catalogue.models import Sku

    sku = sku_factory()
    listing = listing_factory(sku=sku, resolution_method="human_confirmed")

    response = admin_client.post(
        reverse("admin:catalogue_sku_changelist"),
        {
            "action": "delete_selected",
            "_selected_action": [str(sku.pk)],
            "post": "yes",
        },
    )

    assert response.status_code in {200, 403}
    assert Sku.objects.filter(pk=sku.pk).exists()
    listing.refresh_from_db()
    assert listing.sku_id == sku.pk


def test_unreferenced_sku_remains_deletable_through_admin(admin_client, sku_factory):
    from catalogue.models import Sku

    sku = sku_factory()

    response = admin_client.post(
        reverse("admin:catalogue_sku_delete", args=[sku.pk]),
        {"post": "yes"},
    )

    assert response.status_code == 302
    assert not Sku.objects.filter(pk=sku.pk).exists()


def test_forged_listing_edit_cannot_clear_human_confirmed_sku(
    admin_client,
    listing_factory,
    sku_factory,
):
    sku = sku_factory()
    listing = listing_factory(sku=sku, resolution_method="human_confirmed")
    payload = _generic_change_payload(listing, sku_value="")

    response = admin_client.post(_change_url(listing), payload)

    assert response.status_code == 200
    listing.refresh_from_db()
    assert listing.sku == sku
    assert listing.resolution_method == "human_confirmed"
    assert listing.resolution_confidence == Decimal("1.0000")


def test_review_operations_mutate_no_rawlisting_or_unapproved_state(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import Sku, SkuAlias
    from ingestion.models import Swap
    from outcomes.models import Outcome
    from pricing.models import DealFlag, PricePoint

    confirm_raw = raw_listing_factory(raw_title="Confirm immutable raw")
    unresolved_raw = raw_listing_factory(raw_title="Review immutable raw")
    confirm_listing = listing_factory(raw_listing=confirm_raw)
    unresolved_listing = listing_factory(raw_listing=unresolved_raw)
    sku = sku_factory()
    raw_states = {
        confirm_raw.pk: _raw_state(confirm_raw),
        unresolved_raw.pk: _raw_state(unresolved_raw),
    }
    counts_before = {
        "sku": Sku.objects.count(),
        "alias": SkuAlias.objects.count(),
        "pricepoint": PricePoint.objects.count(),
        "dealflag": DealFlag.objects.count(),
        "outcome": Outcome.objects.count(),
        "swap": Swap.objects.count(),
    }

    assert _post_confirmation(admin_client, confirm_listing, sku).status_code == 302
    assert admin_client.post(_mark_reviewed_url(unresolved_listing)).status_code == 302

    confirm_raw.refresh_from_db()
    unresolved_raw.refresh_from_db()
    assert _raw_state(confirm_raw) == raw_states[confirm_raw.pk]
    assert _raw_state(unresolved_raw) == raw_states[unresolved_raw.pk]
    assert Sku.objects.count() == counts_before["sku"]
    assert SkuAlias.objects.count() == counts_before["alias"]
    assert PricePoint.objects.count() == counts_before["pricepoint"]
    assert DealFlag.objects.count() == counts_before["dealflag"]
    assert Outcome.objects.count() == counts_before["outcome"]
    assert Swap.objects.count() == counts_before["swap"]
    confirm_raw.source.refresh_from_db()
    assert confirm_raw.source.last_successful_fetch is None


def test_task_017_requires_no_model_or_migration_change(db):
    call_command("makemigrations", check=True, dry_run=True, verbosity=0)
