import importlib
import importlib.util
import json
import threading
import time
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import close_old_connections, transaction
from django.test import Client
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from django.utils import timezone


UTC = dt_timezone.utc
OLD_RESOLVED_AT = datetime(2025, 1, 1, tzinfo=UTC)


def _require_services():
    assert importlib.util.find_spec("listings.review_services") is not None, (
        "TASK_025 implementation must create listings/review_services.py"
    )
    return importlib.import_module("listings.review_services")


def _required_reverse(name, args):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        pytest.fail(f"TASK_025 implementation must register {name}")


@pytest.fixture
def source(db):
    from sources.models import Source

    return Source.objects.create(
        name=f"task_025_{uuid4().hex}",
        base_url="https://task025.example.invalid",
        terms_notes="synthetic TASK_025 fixture",
        rate_limit=None,
    )


@pytest.fixture
def raw_listing_factory(db, source):
    from ingestion.models import RawListing

    def make(**overrides):
        marker = uuid4().hex
        values = {
            "source": source,
            "raw_title": f"Synthetic TASK 025 GPU {marker}",
            "raw_price": Decimal("15500.00"),
            "raw_price_text": "PHP 15,500",
            "url": f"https://task025.example.invalid/{marker}",
            "seller": f"anonymous-{marker}",
            "fetched_at": datetime(2026, 8, 9, 1, 2, 3, tzinfo=UTC),
            "occurred_at": datetime(2026, 8, 8, 1, 2, 3, tzinfo=UTC),
            "external_id": f"task-025-{marker}",
            "payload": {"synthetic": marker},
        }
        values.update(overrides)
        return RawListing.objects.create(**values)

    return make


@pytest.fixture
def sku_factory(db):
    from catalogue.models import Sku

    def make(**overrides):
        marker = uuid4().hex
        values = {
            "brand": "Synthetic",
            "model": f"GPU {marker}",
            "variant": "",
            "category": "gpu",
            "launch_msrp": Decimal("34995.00"),
            "launch_date": date(2026, 1, 1),
        }
        values.update(overrides)
        return Sku.objects.create(**values)

    return make


@pytest.fixture
def listing_factory(db, raw_listing_factory):
    from listings.models import Listing

    def make(**overrides):
        raw = overrides.pop("raw_listing", None) or raw_listing_factory()
        values = {
            "raw_listing": raw,
            "sku": None,
            "price": raw.raw_price,
            "condition": "used",
            "location": "Metro Manila",
            "resolution_confidence": Decimal("0.0000"),
            "resolution_method": "unresolved",
            "resolved_at": OLD_RESOLVED_AT,
            "reviewed_unresolved_at": None,
            "observed_at": raw.occurred_at or raw.fetched_at,
            "price_kind": "asking",
            "trade_side": None,
        }
        values.update(overrides)
        return Listing.objects.create(**values)

    return make


@pytest.fixture
def user_factory(db):
    def make(*, is_active=True, is_staff=True, is_superuser=False):
        return get_user_model().objects.create_user(
            username=f"task025-{uuid4().hex}",
            password="test-password",
            is_active=is_active,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    return make


def _grant(user, model, *actions):
    content_type = ContentType.objects.get_for_model(model)
    codenames = {f"{action}_{model._meta.model_name}" for action in actions}
    permissions = Permission.objects.filter(
        content_type=content_type,
        codename__in=codenames,
    )
    assert set(permissions.values_list("codename", flat=True)) == codenames
    user.user_permissions.add(*permissions)


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
    return {
        "source_id": raw_listing.source_id,
        "raw_title": raw_listing.raw_title,
        "raw_price": raw_listing.raw_price,
        "raw_price_text": raw_listing.raw_price_text,
        "url": raw_listing.url,
        "seller": raw_listing.seller,
        "fetched_at": raw_listing.fetched_at,
        "occurred_at": raw_listing.occurred_at,
        "external_id": raw_listing.external_id,
        "payload": raw_listing.payload,
    }


def _audit_entries(listing):
    from listings.models import Listing

    return LogEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(Listing),
        object_id=str(listing.pk),
        action_flag=CHANGE,
    )


def _mark_url(listing_id):
    return _required_reverse(
        "api-v1:review-mark-reviewed-unresolved",
        [listing_id],
    )


def _confirm_url(listing_id):
    return _required_reverse("api-v1:review-confirm-sku", [listing_id])


def _post_json(client, url, body, **extra):
    return client.post(
        url,
        data=json.dumps(body),
        content_type="application/json",
        **extra,
    )


@pytest.mark.django_db
def test_shared_service_module_routes_and_task023_routes_are_frozen():
    services = _require_services()

    assert callable(services.mark_reviewed_unresolved)
    assert callable(services.confirm_listing_sku)
    assert services.ReviewOperationResult is not None
    assert services.ReviewPermissionDenied is not None
    assert services.ReviewNotFound is not None
    assert services.ReviewConflict is not None
    assert _mark_url(23) == (
        "/api/v1/reviews/listings/23/mark-reviewed-unresolved/"
    )
    assert _confirm_url(23) == "/api/v1/reviews/listings/23/confirm-sku/"
    assert reverse("api-v1:sku-list") == "/api/v1/skus/"
    assert reverse("api-v1:listing-detail", args=[23]) == "/api/v1/listings/23/"
    assert reverse("api-v1:dealflag-list") == "/api/v1/deal-flags/"


@pytest.mark.django_db
def test_admin_and_api_call_the_same_service_module_once_per_decision(
    admin_client,
    listing_factory,
    sku_factory,
):
    services = _require_services()
    from api import views as api_views
    from listings import admin as listings_admin

    assert api_views.review_services is services
    assert listings_admin.review_services is services

    admin_listing = listing_factory()
    api_listing = listing_factory()
    admin_url = reverse(
        "admin:listings_listing_mark_reviewed_unresolved",
        args=[admin_listing.pk],
    )

    with patch.object(
        services,
        "mark_reviewed_unresolved",
        wraps=services.mark_reviewed_unresolved,
    ) as shared_operation:
        assert admin_client.post(admin_url).status_code == 302
        assert _post_json(admin_client, _mark_url(api_listing.pk), {}).status_code == 200

    assert shared_operation.call_count == 2
    assert _audit_entries(admin_listing).count() == 1
    assert _audit_entries(api_listing).count() == 1

    admin_confirmation = listing_factory()
    api_confirmation = listing_factory()
    admin_sku = sku_factory()
    api_sku = sku_factory()
    admin_change_url = reverse(
        "admin:listings_listing_change",
        args=[admin_confirmation.pk],
    )

    with patch.object(
        services,
        "confirm_listing_sku",
        wraps=services.confirm_listing_sku,
    ) as shared_confirmation:
        assert admin_client.post(
            admin_change_url,
            {"sku": str(admin_sku.pk), "_save": "Save"},
        ).status_code == 302
        assert _post_json(
            admin_client,
            _confirm_url(api_confirmation.pk),
            {"sku_id": api_sku.pk},
        ).status_code == 200

    assert shared_confirmation.call_count == 2
    assert _audit_entries(admin_confirmation).count() == 1
    assert _audit_entries(api_confirmation).count() == 1


@pytest.mark.django_db
def test_mark_reviewed_unresolved_preserves_evidence_exits_queue_and_audits(
    listing_factory,
    user_factory,
):
    services = _require_services()
    from listings.models import Listing

    actor = user_factory()
    _grant(actor, Listing, "change")
    listing = listing_factory(
        resolution_method="fuzzy_match",
        resolution_confidence=Decimal("0.4321"),
    )
    before = _listing_state(listing)

    result = services.mark_reviewed_unresolved(actor=actor, listing_id=listing.pk)

    listing.refresh_from_db()
    after = _listing_state(listing)
    assert listing.reviewed_unresolved_at is not None
    before.pop("reviewed_unresolved_at")
    after.pop("reviewed_unresolved_at")
    assert after == before
    assert not Listing.objects.filter(
        pk=listing.pk,
        sku__isnull=True,
        reviewed_unresolved_at__isnull=True,
    ).exists()
    assert result.operation == "mark_reviewed_unresolved"
    assert result.listing_id == listing.pk
    assert result.alias_status == "not_requested"
    assert result.alias_id is None
    entry = _audit_entries(listing).get()
    assert entry.user_id == actor.pk
    assert entry.object_repr == str(listing)
    assert entry.change_message == "Marked reviewed unresolved."


@pytest.mark.django_db
def test_repeated_reviewed_unresolved_is_a_new_logged_success(
    listing_factory,
    user_factory,
):
    services = _require_services()
    from listings.models import Listing

    actor = user_factory()
    _grant(actor, Listing, "change")
    listing = listing_factory()

    services.mark_reviewed_unresolved(actor=actor, listing_id=listing.pk)
    listing.refresh_from_db()
    first_marker = listing.reviewed_unresolved_at
    services.mark_reviewed_unresolved(actor=actor, listing_id=listing.pk)
    listing.refresh_from_db()

    assert listing.reviewed_unresolved_at >= first_marker
    assert _audit_entries(listing).count() == 2
    assert set(_audit_entries(listing).values_list("change_message", flat=True)) == {
        "Marked reviewed unresolved."
    }


@pytest.mark.django_db
def test_service_permission_and_ineligible_state_failures_write_nothing(
    listing_factory,
    sku_factory,
    user_factory,
):
    services = _require_services()
    from listings.models import Listing

    listing = listing_factory()
    before = _listing_state(listing)
    actors = [
        user_factory(is_active=False),
        user_factory(is_staff=False),
        user_factory(),
    ]
    _grant(actors[0], Listing, "change")
    _grant(actors[1], Listing, "change")

    for actor in actors:
        with pytest.raises(services.ReviewPermissionDenied) as denied:
            services.mark_reviewed_unresolved(actor=actor, listing_id=listing.pk)
        assert denied.value.code == "permission_denied"

    listing.refresh_from_db()
    assert _listing_state(listing) == before
    assert not _audit_entries(listing).exists()

    authorized = user_factory()
    _grant(authorized, Listing, "change")
    listing.sku = sku_factory()
    listing.resolution_method = "human_confirmed"
    listing.resolution_confidence = Decimal("1.0000")
    listing.save(update_fields=["sku", "resolution_method", "resolution_confidence"])
    locked_state = _listing_state(listing)

    with pytest.raises(services.ReviewConflict) as conflict:
        services.mark_reviewed_unresolved(actor=authorized, listing_id=listing.pk)
    assert conflict.value.code == "ineligible_review_state"
    listing.refresh_from_db()
    assert _listing_state(listing) == locked_state
    assert not _audit_entries(listing).exists()


@pytest.mark.django_db
def test_confirmation_and_correction_apply_only_the_five_decision_fields(
    listing_factory,
    sku_factory,
    user_factory,
):
    services = _require_services()
    from listings.models import Listing

    actor = user_factory()
    _grant(actor, Listing, "change")
    listing = listing_factory(reviewed_unresolved_at=timezone.now())
    first_sku = sku_factory(model="First target")
    second_sku = sku_factory(model="Corrected target")
    preserved = _listing_state(listing)

    first = services.confirm_listing_sku(
        actor=actor,
        listing_id=listing.pk,
        sku_id=first_sku.pk,
    )
    listing.refresh_from_db()
    first_resolved_at = listing.resolved_at
    assert listing.sku_id == first_sku.pk
    assert listing.resolution_method == "human_confirmed"
    assert listing.resolution_confidence == Decimal("1.0000")
    assert listing.reviewed_unresolved_at is None
    assert first.alias_status == "not_requested"

    corrected = services.confirm_listing_sku(
        actor=actor,
        listing_id=listing.pk,
        sku_id=second_sku.pk,
    )
    listing.refresh_from_db()
    assert listing.sku_id == second_sku.pk
    assert listing.resolved_at >= first_resolved_at
    assert corrected.sku_id == second_sku.pk
    for field in (
        "raw_listing_id",
        "price",
        "condition",
        "location",
        "observed_at",
        "price_kind",
        "trade_side",
    ):
        assert _listing_state(listing)[field] == preserved[field]
    assert _audit_entries(listing).count() == 2
    assert set(_audit_entries(listing).values_list("change_message", flat=True)) == {
        "Confirmed or corrected SKU."
    }


@pytest.mark.django_db
def test_alias_opt_in_is_exact_optional_and_same_sku_idempotent(
    raw_listing_factory,
    listing_factory,
    sku_factory,
    user_factory,
):
    services = _require_services()
    from catalogue.models import SkuAlias
    from listings.models import Listing
    from listings.normalisation import normalise_title

    actor = user_factory()
    _grant(actor, Listing, "change")
    selected_sku = sku_factory()
    no_alias_listing = listing_factory()
    no_alias = services.confirm_listing_sku(
        actor=actor,
        listing_id=no_alias_listing.pk,
        sku_id=selected_sku.pk,
        create_alias=False,
    )
    assert no_alias.alias_status == "not_requested"
    assert SkuAlias.objects.count() == 0

    _grant(actor, SkuAlias, "add")
    raw = raw_listing_factory(raw_title="  ASUS RTX 4070—SUPER 12GB  ")
    listing = listing_factory(raw_listing=raw)
    created = services.confirm_listing_sku(
        actor=actor,
        listing_id=listing.pk,
        sku_id=selected_sku.pk,
        create_alias=True,
    )
    alias = SkuAlias.objects.get()
    assert created.alias_status == "created"
    assert created.alias_id == alias.pk
    assert alias.sku_id == selected_sku.pk
    assert alias.alias_text == raw.raw_title
    assert alias.normalised_text == normalise_title(raw.raw_title)
    assert alias.source_of_truth == "human_confirmed"

    same_title = raw_listing_factory(raw_title="ASUS RTX 4070 SUPER 12GB")
    second_listing = listing_factory(raw_listing=same_title)
    alias_state = (alias.sku_id, alias.alias_text, alias.normalised_text, alias.source_of_truth)
    repeated = services.confirm_listing_sku(
        actor=actor,
        listing_id=second_listing.pk,
        sku_id=selected_sku.pk,
        create_alias=True,
    )
    alias.refresh_from_db()
    assert repeated.alias_status == "already_exists"
    assert repeated.alias_id == alias.pk
    assert SkuAlias.objects.count() == 1
    assert (
        alias.sku_id,
        alias.alias_text,
        alias.normalised_text,
        alias.source_of_truth,
    ) == alias_state


@pytest.mark.django_db
def test_alias_permission_conflict_and_persistence_failure_are_atomic(
    raw_listing_factory,
    listing_factory,
    sku_factory,
    user_factory,
):
    services = _require_services()
    from catalogue.models import SkuAlias
    from listings.models import Listing
    from listings.normalisation import normalise_title

    actor = user_factory()
    _grant(actor, Listing, "change")
    selected = sku_factory(model="Selected")
    listing = listing_factory()
    before = _listing_state(listing)

    with pytest.raises(services.ReviewPermissionDenied):
        services.confirm_listing_sku(
            actor=actor,
            listing_id=listing.pk,
            sku_id=selected.pk,
            create_alias=True,
        )
    listing.refresh_from_db()
    assert _listing_state(listing) == before

    _grant(actor, SkuAlias, "add")
    conflicting_raw = raw_listing_factory(raw_title="Global alias conflict")
    conflict_listing = listing_factory(raw_listing=conflicting_raw)
    existing_target = sku_factory(model="Existing")
    SkuAlias.objects.create(
        sku=existing_target,
        alias_text=conflicting_raw.raw_title,
        normalised_text=normalise_title(conflicting_raw.raw_title),
        source_of_truth="seed",
    )
    conflict_before = _listing_state(conflict_listing)
    with pytest.raises(services.ReviewConflict) as conflict:
        services.confirm_listing_sku(
            actor=actor,
            listing_id=conflict_listing.pk,
            sku_id=selected.pk,
            create_alias=True,
        )
    assert conflict.value.code == "alias_conflict"
    conflict_listing.refresh_from_db()
    assert _listing_state(conflict_listing) == conflict_before
    assert not _audit_entries(conflict_listing).exists()

    failure_listing = listing_factory()
    failure_before = _listing_state(failure_listing)
    with patch.object(SkuAlias.objects, "create", side_effect=RuntimeError("alias failed")):
        with pytest.raises(RuntimeError, match="alias failed"):
            services.confirm_listing_sku(
                actor=actor,
                listing_id=failure_listing.pk,
                sku_id=selected.pk,
                create_alias=True,
            )
    failure_listing.refresh_from_db()
    assert _listing_state(failure_listing) == failure_before
    assert not _audit_entries(failure_listing).exists()


@pytest.mark.django_db
def test_audit_failure_rolls_back_listing_alias_and_log(
    listing_factory,
    sku_factory,
    user_factory,
):
    services = _require_services()
    from catalogue.models import SkuAlias
    from listings.models import Listing

    actor = user_factory()
    _grant(actor, Listing, "change")
    _grant(actor, SkuAlias, "add")
    listing = listing_factory()
    before = _listing_state(listing)

    def failing_audit_writer(_listing, _message):
        assert SkuAlias.objects.exists()
        raise RuntimeError("audit failed")

    with pytest.raises(RuntimeError, match="audit failed"):
        services.confirm_listing_sku(
            actor=actor,
            listing_id=listing.pk,
            sku_id=sku_factory().pk,
            create_alias=True,
            audit_writer=failing_audit_writer,
        )

    listing.refresh_from_db()
    assert _listing_state(listing) == before
    assert not SkuAlias.objects.exists()
    assert not _audit_entries(listing).exists()


@pytest.mark.django_db(transaction=True)
def test_postgres_row_lock_serializes_and_rechecks_mutable_eligibility(
    listing_factory,
    sku_factory,
    user_factory,
):
    services = _require_services()
    from listings.models import Listing

    actor = user_factory()
    _grant(actor, Listing, "change")
    listing = listing_factory()
    selected_sku = sku_factory()
    worker_started = threading.Event()
    worker_finished = threading.Event()
    failures = []

    def run_mark():
        close_old_connections()
        try:
            thread_actor = get_user_model().objects.get(pk=actor.pk)
            worker_started.set()
            services.mark_reviewed_unresolved(
                actor=thread_actor,
                listing_id=listing.pk,
            )
        except Exception as error:  # The exact service error is asserted below.
            failures.append(error)
        finally:
            close_old_connections()
            worker_finished.set()

    with transaction.atomic():
        locked = Listing.objects.select_for_update().get(pk=listing.pk)
        worker = threading.Thread(target=run_mark)
        worker.start()
        assert worker_started.wait(timeout=2)
        time.sleep(0.15)
        assert not worker_finished.is_set()
        locked.sku = selected_sku
        locked.resolution_method = "human_confirmed"
        locked.resolution_confidence = Decimal("1.0000")
        locked.resolved_at = timezone.now()
        locked.save(
            update_fields=[
                "sku",
                "resolution_method",
                "resolution_confidence",
                "resolved_at",
            ]
        )

    worker.join(timeout=5)
    assert not worker.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], services.ReviewConflict)
    assert failures[0].code == "ineligible_review_state"
    listing.refresh_from_db()
    assert listing.sku_id == selected_sku.pk
    assert listing.reviewed_unresolved_at is None
    assert not _audit_entries(listing).exists()


@pytest.mark.django_db
def test_api_success_envelopes_are_decimal_safe_utc_and_operation_only(
    admin_client,
    listing_factory,
    sku_factory,
):
    _require_services()
    mark_listing = listing_factory()
    mark_response = _post_json(admin_client, _mark_url(mark_listing.pk), {})

    assert mark_response.status_code == 200
    assert set(mark_response.json()) == {
        "operation",
        "listing_id",
        "reviewed_unresolved_at",
    }
    assert mark_response.json()["operation"] == "mark_reviewed_unresolved"
    assert mark_response.json()["listing_id"] == mark_listing.pk
    assert mark_response.json()["reviewed_unresolved_at"].endswith("Z")

    confirmation = listing_factory()
    sku = sku_factory()
    confirm_response = _post_json(
        admin_client,
        _confirm_url(confirmation.pk),
        {"sku_id": sku.pk},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json() == {
        "operation": "confirm_sku",
        "listing_id": confirmation.pk,
        "sku_id": sku.pk,
        "resolution_method": "human_confirmed",
        "resolution_confidence": "1.0000",
        "resolved_at": confirm_response.json()["resolved_at"],
        "reviewed_unresolved_at": None,
        "alias_status": "not_requested",
    }
    assert confirm_response.json()["resolved_at"].endswith("Z")
    assert not {
        "raw_title",
        "seller",
        "payload",
        "url",
        "source",
    }.intersection(confirm_response.json())

    for method in ("get", "put", "patch", "delete"):
        response = getattr(admin_client, method)(_mark_url(mark_listing.pk))
        assert response.status_code == 405
    unsupported = admin_client.post(
        _mark_url(mark_listing.pk),
        data="x",
        content_type="text/plain",
    )
    assert unsupported.status_code == 415


@pytest.mark.django_db
def test_api_requires_session_active_staff_permission_and_csrf(
    client,
    listing_factory,
    user_factory,
):
    _require_services()
    from listings.models import Listing

    listing = listing_factory()
    url = _mark_url(listing.pk)
    assert _post_json(client, url, {}).status_code == 403

    nonstaff = user_factory(is_staff=False)
    _grant(nonstaff, Listing, "change")
    client.force_login(nonstaff)
    assert _post_json(client, url, {}).status_code == 403
    client.logout()

    no_permission = user_factory()
    client.force_login(no_permission)
    assert _post_json(client, url, {}).status_code == 403
    client.logout()

    actor = user_factory()
    _grant(actor, Listing, "change")
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(actor)
    assert _post_json(csrf_client, url, {}).status_code == 403
    token = "a" * 32
    csrf_client.cookies["csrftoken"] = token
    assert _post_json(
        csrf_client,
        url,
        {},
        HTTP_X_CSRFTOKEN=token,
    ).status_code == 200


@pytest.mark.django_db
def test_api_validation_not_found_permission_and_conflict_statuses(
    admin_client,
    client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
    user_factory,
):
    services = _require_services()
    from catalogue.models import SkuAlias
    from listings.models import Listing
    from listings.normalisation import normalise_title

    listing = listing_factory()
    invalid_mark = _post_json(admin_client, _mark_url(listing.pk), {"sku_id": 1})
    assert invalid_mark.status_code == 400
    assert invalid_mark.json()["code"] == "invalid_request"
    assert "errors" in invalid_mark.json()

    invalid_confirm = _post_json(admin_client, _confirm_url(listing.pk), {})
    assert invalid_confirm.status_code == 400
    assert invalid_confirm.json()["code"] == "invalid_request"
    assert "sku_id" in invalid_confirm.json()["errors"]
    non_boolean = _post_json(
        admin_client,
        _confirm_url(listing.pk),
        {"sku_id": sku_factory().pk, "create_alias": "true"},
    )
    assert non_boolean.status_code == 400

    malformed = admin_client.post(
        _confirm_url(listing.pk),
        data="{",
        content_type="application/json",
    )
    assert malformed.status_code == 400

    missing_listing = _post_json(admin_client, _mark_url(999999999), {})
    assert missing_listing.status_code == 404
    assert missing_listing.json() == {
        "code": "listing_not_found",
        "detail": "Listing not found.",
    }
    missing_sku = _post_json(
        admin_client,
        _confirm_url(listing.pk),
        {"sku_id": 999999999},
    )
    assert missing_sku.status_code == 404
    assert missing_sku.json()["code"] == "sku_not_found"

    ineligible = listing_factory(
        sku=sku_factory(),
        resolution_method="human_confirmed",
        resolution_confidence=Decimal("1.0000"),
    )
    state_conflict = _post_json(admin_client, _mark_url(ineligible.pk), {})
    assert state_conflict.status_code == 409
    assert state_conflict.json() == {
        "code": "ineligible_review_state",
        "detail": "Listing is not eligible to be marked reviewed unresolved.",
    }

    actor = user_factory()
    _grant(actor, Listing, "change")
    client.force_login(actor)
    alias_listing = listing_factory()
    alias_denied = _post_json(
        client,
        _confirm_url(alias_listing.pk),
        {"sku_id": sku_factory().pk, "create_alias": True},
    )
    assert alias_denied.status_code == 403
    alias_listing.refresh_from_db()
    assert alias_listing.sku_id is None
    assert not _audit_entries(alias_listing).exists()

    raw = raw_listing_factory(raw_title="API alias conflict")
    conflict_listing = listing_factory(raw_listing=raw)
    existing = sku_factory()
    selected = sku_factory()
    SkuAlias.objects.create(
        sku=existing,
        alias_text=raw.raw_title,
        normalised_text=normalise_title(raw.raw_title),
        source_of_truth="seed",
    )
    conflict_response = _post_json(
        admin_client,
        _confirm_url(conflict_listing.pk),
        {"sku_id": selected.pk, "create_alias": True},
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json() == {
        "code": "alias_conflict",
        "detail": "The normalized title is already an alias for a different SKU.",
    }


@pytest.mark.django_db
def test_no_generic_review_rawlisting_alias_or_existing_read_mutations(
    admin_client,
    listing_factory,
):
    _require_services()
    listing = listing_factory()

    for path in (
        "/api/v1/reviews/",
        "/api/v1/reviews/listings/",
        "/api/v1/raw-listings/",
        "/api/v1/sku-aliases/",
    ):
        with pytest.raises(Resolver404):
            resolve(path)

    assert admin_client.patch(
        reverse("api-v1:listing-detail", args=[listing.pk]),
        data=json.dumps({"sku_id": 1}),
        content_type="application/json",
    ).status_code == 405
    assert admin_client.get(_mark_url(listing.pk)).status_code == 405
    assert admin_client.get(_confirm_url(listing.pk)).status_code == 405


@pytest.mark.django_db
def test_review_services_preserve_rawlisting_and_write_no_adjacent_domain_state(
    listing_factory,
    sku_factory,
    user_factory,
):
    services = _require_services()
    from catalogue.models import Sku, SkuAlias
    from ingestion.models import Swap
    from listings.models import Listing
    from listings.resolver import resolve_raw_listing
    from outcomes.models import Outcome
    from pricing.models import DealFlag, PricePoint

    actor = user_factory()
    _grant(actor, Listing, "change")
    _grant(actor, SkuAlias, "add")
    listing = listing_factory()
    raw = listing.raw_listing
    raw_before = _raw_state(raw)
    source_fetch_before = raw.source.last_successful_fetch
    counts_before = {
        "sku": Sku.objects.count(),
        "pricepoint": PricePoint.objects.count(),
        "dealflag": DealFlag.objects.count(),
        "outcome": Outcome.objects.count(),
        "swap": Swap.objects.count(),
    }

    with patch(
        "listings.resolver.resolve_raw_listing",
        wraps=resolve_raw_listing,
    ) as resolver:
        services.confirm_listing_sku(
            actor=actor,
            listing_id=listing.pk,
            sku_id=sku_factory().pk,
            create_alias=True,
        )

    assert not resolver.called
    raw.refresh_from_db()
    raw.source.refresh_from_db()
    assert _raw_state(raw) == raw_before
    assert raw.source.last_successful_fetch == source_fetch_before
    assert Sku.objects.count() == counts_before["sku"] + 1
    assert SkuAlias.objects.count() == 1
    assert PricePoint.objects.count() == counts_before["pricepoint"]
    assert DealFlag.objects.count() == counts_before["dealflag"]
    assert Outcome.objects.count() == counts_before["outcome"]
    assert Swap.objects.count() == counts_before["swap"]


@pytest.mark.django_db
def test_task_025_requires_no_model_or_migration_change():
    _require_services()
    call_command("makemigrations", check=True, dry_run=True, verbosity=0)
