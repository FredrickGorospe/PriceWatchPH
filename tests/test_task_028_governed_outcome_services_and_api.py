import importlib
import importlib.util
import json
import threading
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import close_old_connections, transaction
from django.urls import NoReverseMatch, Resolver404, resolve, reverse


UTC = dt_timezone.utc

# Noon Manila on 2026-06-15 is 04:00Z; 18:00 Manila the same day is 10:00Z.
BOUGHT_AT = datetime(2026, 6, 15, 4, 0, tzinfo=UTC)
SOLD_SAME_MANILA_DAY = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
SOLD_NEXT_MANILA_DAY = datetime(2026, 6, 16, 4, 0, tzinfo=UTC)

BOUGHT_TEXT = "12500.00"
SOLD_TEXT = "14000.00"
SOLD_AT_A_LOSS_TEXT = "10000.00"

STATE_FIELDS = {
    "deal_flag_id",
    "outcome_id",
    "lifecycle_state",
    "acted",
    "skip_reason",
    "bought_at",
    "bought_price",
    "sold_at",
    "sold_price",
    "days_held",
    "realised_margin",
}
OPERATION_FIELDS = STATE_FIELDS | {"operation"}

DEALFLAG_FEED_FIELDS = {
    "id",
    "sku",
    "listing",
    "baseline_pricepoint",
    "score",
    "reason",
    "flagged_at",
}

# Exact and frozen, matching the TASK_025 precedent of asserting audit prose
# verbatim. See TASK_028 specification Section 15.
SKIP_MESSAGE = "Skipped deal flag."
PURCHASE_MESSAGE = "Recorded purchase."
PURCHASE_AFTER_SKIP_MESSAGE = "Recorded purchase after previously skipping."
SALE_MESSAGE = "Recorded sale."
CORRECT_PURCHASE_MESSAGE = "Corrected purchase evidence."
CORRECT_SALE_MESSAGE = "Corrected sale evidence."

INVALID_STATE_DETAIL = (
    "Outcome is in an invalid persisted state and must be corrected manually."
)

OPERATION_ROUTES = (
    ("skip", "api-v1:dealflag-outcome-skip"),
    ("record-purchase", "api-v1:dealflag-outcome-record-purchase"),
    ("record-sale", "api-v1:dealflag-outcome-record-sale"),
    ("correct-purchase", "api-v1:dealflag-outcome-correct-purchase"),
    ("correct-sale", "api-v1:dealflag-outcome-correct-sale"),
)

ADMIN_OPERATION_VIEWS = (
    "skip",
    "record_purchase",
    "record_sale",
    "correct_purchase",
    "correct_sale",
)


def _require_services():
    assert importlib.util.find_spec("outcomes.outcome_services") is not None, (
        "TASK_028 implementation must create outcomes/outcome_services.py"
    )
    return importlib.import_module("outcomes.outcome_services")


def _required_reverse(name, args=None):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        pytest.fail(f"TASK_028 implementation must register {name}")


def _detail_url(deal_flag_pk):
    return _required_reverse("api-v1:dealflag-outcome-detail", [deal_flag_pk])


def _operation_url(segment, deal_flag_pk):
    name = dict(OPERATION_ROUTES)[segment]
    return _required_reverse(name, [deal_flag_pk])


def _post_json(client, url, body, **extra):
    return client.post(
        url,
        data=json.dumps(body),
        content_type="application/json",
        **extra,
    )


def _grant(user, model, *actions):
    content_type = ContentType.objects.get_for_model(model)
    codenames = {f"{action}_{model._meta.model_name}" for action in actions}
    permissions = Permission.objects.filter(
        content_type=content_type,
        codename__in=codenames,
    )
    assert set(permissions.values_list("codename", flat=True)) == codenames
    user.user_permissions.add(*permissions)


def _revoke(user, model, *actions):
    content_type = ContentType.objects.get_for_model(model)
    codenames = {f"{action}_{model._meta.model_name}" for action in actions}
    user.user_permissions.remove(
        *Permission.objects.filter(
            content_type=content_type,
            codename__in=codenames,
        )
    )


def _audit_entries(outcome_pk):
    from outcomes.models import Outcome

    return LogEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(Outcome),
        object_id=str(outcome_pk),
    )


def _all_outcome_audit_entries():
    from outcomes.models import Outcome

    return LogEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(Outcome)
    )


def _outcome_row(deal_flag):
    from outcomes.models import Outcome

    return Outcome.objects.filter(deal_flag=deal_flag).first()


@pytest.fixture
def user_factory(db):
    def make(*, is_active=True, is_staff=True, is_superuser=False):
        return get_user_model().objects.create_user(
            username=f"task028-{uuid4().hex}",
            password="test-password",
            is_active=is_active,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    return make


@pytest.fixture
def dealflag_factory(db):
    from catalogue.models import Sku
    from ingestion.models import RawListing
    from listings.models import Listing
    from pricing.models import DealFlag, PricePoint
    from sources.models import Source

    def make(**overrides):
        marker = uuid4().hex
        source = Source.objects.create(
            name=f"task_028_{marker}",
            base_url="https://task028.example.invalid",
            terms_notes="synthetic TASK_028 fixture",
            rate_limit=None,
        )
        sku = Sku.objects.create(
            brand="Synthetic",
            model=f"GPU {marker}",
            variant="",
            category="gpu",
            launch_msrp=Decimal("34995.00"),
            launch_date=date(2026, 1, 1),
        )
        raw_listing = RawListing.objects.create(
            source=source,
            raw_title=f"Synthetic TASK 028 GPU {marker}",
            raw_price_text="15500.00",
            raw_price=Decimal("15500.00"),
            url=f"https://task028.example.invalid/{marker}",
            seller="",
            fetched_at=datetime(2026, 6, 15, 4, 5, tzinfo=UTC),
            occurred_at=BOUGHT_AT,
            external_id=f"task-028-{marker}",
            payload={"synthetic": marker},
        )
        listing = Listing.objects.create(
            raw_listing=raw_listing,
            sku=sku,
            price=Decimal("15500.00"),
            condition="used",
            location="",
            resolution_confidence=Decimal("1.0000"),
            resolution_method="exact_alias",
            resolved_at=datetime(2026, 6, 15, 5, 0, tzinfo=UTC),
            observed_at=BOUGHT_AT,
            price_kind="asking",
        )
        pricepoint = PricePoint.objects.create(
            sku=sku,
            condition="used",
            day=date(2026, 6, 15),
            median=Decimal("18000.0000"),
            p25=Decimal("17000.0000"),
            p75=Decimal("19000.0000"),
            n_listings=5,
            mad=Decimal("1000.0000"),
            window_start_day=date(2026, 3, 17),
            window_end_day=date(2026, 6, 15),
            calculated_at=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
            calculation_contract_version="asking_price_baseline_v1",
        )
        values = {
            "listing": listing,
            "score": Decimal("-3.0000"),
            "baseline_pricepoint": pricepoint,
            "reason": "asking_price_mad_v1",
            "flagged_at": datetime(2026, 6, 15, 6, 30, tzinfo=UTC),
        }
        values.update(overrides)
        return DealFlag.objects.create(**values)

    return make


@pytest.fixture
def actor_factory(user_factory):
    from outcomes.models import Outcome
    from pricing.models import DealFlag

    def make(*outcome_actions, view_dealflag=True, **user_options):
        actor = user_factory(**user_options)
        if view_dealflag:
            _grant(actor, DealFlag, "view")
        if outcome_actions:
            _grant(actor, Outcome, *outcome_actions)
        return actor

    return make


@pytest.fixture
def skipped_factory(dealflag_factory, actor_factory):
    def make():
        services = _require_services()
        deal_flag = dealflag_factory()
        services.skip(
            actor=actor_factory("add"),
            deal_flag_id=deal_flag.pk,
            skip_reason="already sold by the time I followed up",
        )
        return deal_flag

    return make


@pytest.fixture
def open_factory(dealflag_factory, actor_factory):
    def make():
        services = _require_services()
        deal_flag = dealflag_factory()
        services.record_purchase(
            actor=actor_factory("add"),
            deal_flag_id=deal_flag.pk,
            bought_at=BOUGHT_AT,
            bought_price=Decimal(BOUGHT_TEXT),
        )
        return deal_flag

    return make


@pytest.fixture
def closed_factory(open_factory, actor_factory):
    def make(sold_price=SOLD_TEXT, sold_at=SOLD_NEXT_MANILA_DAY):
        services = _require_services()
        deal_flag = open_factory()
        services.record_sale(
            actor=actor_factory("change"),
            deal_flag_id=deal_flag.pk,
            sold_at=sold_at,
            sold_price=Decimal(sold_price),
        )
        return deal_flag

    return make


# ---------------------------------------------------------------------------
# Preservation: these must already hold before TASK_028 is implemented.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_generic_outcome_collection_route_remains_unavailable(admin_client):
    with pytest.raises(Resolver404):
        resolve("/api/v1/outcomes/")
    assert admin_client.get("/api/v1/outcomes/").status_code == 404


@pytest.mark.django_db
def test_dealflag_feed_field_set_is_unchanged(admin_client, dealflag_factory):
    dealflag_factory()

    response = admin_client.get(reverse("api-v1:dealflag-list"))

    assert response.status_code == 200
    assert set(response.json()["results"][0]) == DEALFLAG_FEED_FIELDS


@pytest.mark.django_db
def test_existing_outcome_schema_contract_is_unchanged():
    from outcomes.models import Outcome

    field = {f.name: f for f in Outcome._meta.get_fields()}
    assert field["deal_flag"].one_to_one is True
    assert field["deal_flag"].remote_field.related_name == "outcome"
    assert field["bought_price"].max_digits == 12
    assert field["bought_price"].decimal_places == 2
    assert field["sold_price"].max_digits == 12
    assert field["sold_price"].decimal_places == 2
    assert field["realised_margin"].generated is True

    constraints = {c.name for c in Outcome._meta.constraints}
    assert "outcome_skip_reason_required_when_not_acted" in constraints
    assert "outcome_days_held_non_negative" in constraints


@pytest.mark.django_db
def test_task_027_bootstrap_still_creates_zero_outcomes():
    from django.test import override_settings
    from io import StringIO
    from outcomes.models import Outcome

    with override_settings(ENABLE_DEMO_DATA=True):
        call_command("bootstrap_demo_data", stdout=StringIO())

    assert Outcome.objects.count() == 0


@pytest.mark.django_db
def test_task_028_requires_no_model_or_migration_change():
    call_command("makemigrations", check=True, dry_run=True, verbosity=0)


# ---------------------------------------------------------------------------
# Lifecycle states and transitions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_untracked_dealflag_reports_untracked_state_without_creating_a_row(
    dealflag_factory,
    actor_factory,
):
    services = _require_services()
    from outcomes.models import Outcome

    deal_flag = dealflag_factory()

    state = services.get_outcome_state(
        actor=actor_factory("view"),
        deal_flag_id=deal_flag.pk,
    )

    assert state.lifecycle_state == "untracked"
    assert state.deal_flag_id == deal_flag.pk
    assert state.outcome_id is None
    assert state.acted is None
    assert state.skip_reason is None
    assert state.bought_at is None
    assert state.bought_price is None
    assert state.sold_at is None
    assert state.sold_price is None
    assert state.days_held is None
    assert state.realised_margin is None
    assert Outcome.objects.count() == 0


@pytest.mark.django_db
def test_skip_creates_skipped_state_with_stripped_reason(
    dealflag_factory,
    actor_factory,
):
    services = _require_services()

    deal_flag = dealflag_factory()
    result = services.skip(
        actor=actor_factory("add"),
        deal_flag_id=deal_flag.pk,
        skip_reason="   gone before I replied   ",
    )

    assert result.operation == "skip"
    assert result.lifecycle_state == "skipped"
    assert result.acted is False
    assert result.skip_reason == "gone before I replied"
    assert result.bought_at is None
    assert result.bought_price is None
    assert result.sold_at is None
    assert result.sold_price is None
    assert result.days_held is None
    assert result.realised_margin is None

    outcome = _outcome_row(deal_flag)
    assert outcome.acted is False
    assert outcome.skip_reason == "gone before I replied"


@pytest.mark.django_db
def test_record_purchase_from_untracked_opens_position(
    dealflag_factory,
    actor_factory,
):
    services = _require_services()

    deal_flag = dealflag_factory()
    result = services.record_purchase(
        actor=actor_factory("add"),
        deal_flag_id=deal_flag.pk,
        bought_at=BOUGHT_AT,
        bought_price=Decimal(BOUGHT_TEXT),
    )

    assert result.operation == "record_purchase"
    assert result.lifecycle_state == "open"
    assert result.acted is True
    assert result.skip_reason is None
    assert result.bought_at == BOUGHT_AT
    assert result.bought_price == Decimal(BOUGHT_TEXT)
    assert result.sold_at is None
    assert result.sold_price is None
    assert result.days_held is None
    assert result.realised_margin is None

    outcome = _outcome_row(deal_flag)
    assert outcome.acted is True
    assert outcome.skip_reason is None
    assert outcome.realised_margin is None


@pytest.mark.django_db
def test_record_purchase_transitions_a_skipped_outcome_to_open(
    skipped_factory,
    actor_factory,
):
    services = _require_services()

    deal_flag = skipped_factory()
    existing = _outcome_row(deal_flag)

    result = services.record_purchase(
        actor=actor_factory("add"),
        deal_flag_id=deal_flag.pk,
        bought_at=BOUGHT_AT,
        bought_price=Decimal(BOUGHT_TEXT),
    )

    assert result.lifecycle_state == "open"
    assert result.acted is True
    assert result.skip_reason is None
    assert result.bought_price == Decimal(BOUGHT_TEXT)
    assert result.days_held is None
    assert result.realised_margin is None

    outcome = _outcome_row(deal_flag)
    # The same row is transitioned, never deleted and recreated.
    assert outcome.pk == existing.pk
    assert outcome.acted is True
    assert outcome.skip_reason is None


@pytest.mark.django_db
def test_record_sale_closes_position_and_reads_generated_margin(
    open_factory,
    actor_factory,
):
    services = _require_services()

    deal_flag = open_factory()
    result = services.record_sale(
        actor=actor_factory("change"),
        deal_flag_id=deal_flag.pk,
        sold_at=SOLD_NEXT_MANILA_DAY,
        sold_price=Decimal(SOLD_TEXT),
    )

    assert result.operation == "record_sale"
    assert result.lifecycle_state == "closed"
    assert result.sold_price == Decimal(SOLD_TEXT)
    assert result.days_held == 1
    assert result.realised_margin == Decimal("1500.00")

    outcome = _outcome_row(deal_flag)
    assert outcome.realised_margin == Decimal("1500.00")


@pytest.mark.django_db
def test_acted_true_without_purchase_evidence_is_never_produced(
    skipped_factory,
    open_factory,
):
    _require_services()
    from outcomes.models import Outcome

    skipped_factory()
    open_factory()

    for outcome in Outcome.objects.all():
        if outcome.acted:
            assert outcome.bought_at is not None
            assert outcome.bought_price is not None


# ---------------------------------------------------------------------------
# Invalid persisted state (DB-valid, lifecycle-invalid)
# ---------------------------------------------------------------------------


# Each shape below satisfies every Outcome CHECK constraint in the live schema
# but matches none of the four approved lifecycle states.
INVALID_PERSISTED_SHAPES = {
    "acted_without_purchase": {
        "acted": True,
        "skip_reason": None,
        "bought_at": None,
        "bought_price": None,
    },
    "skipped_with_purchase_evidence": {
        "acted": False,
        "skip_reason": "changed my mind",
        "bought_at": BOUGHT_AT,
        "bought_price": Decimal(BOUGHT_TEXT),
    },
    "partial_purchase_pair": {
        "acted": True,
        "skip_reason": None,
        "bought_at": BOUGHT_AT,
        "bought_price": None,
    },
    "partial_sale_pair": {
        "acted": True,
        "skip_reason": None,
        "bought_at": BOUGHT_AT,
        "bought_price": Decimal(BOUGHT_TEXT),
        "sold_at": SOLD_NEXT_MANILA_DAY,
        "sold_price": None,
    },
    "sale_without_purchase": {
        "acted": True,
        "skip_reason": None,
        "bought_at": None,
        "bought_price": None,
        "sold_at": SOLD_NEXT_MANILA_DAY,
        "sold_price": Decimal(SOLD_TEXT),
    },
}


@pytest.fixture
def invalid_outcome_factory(dealflag_factory):
    from outcomes.models import Outcome

    def make(shape):
        deal_flag = dealflag_factory()
        Outcome.objects.create(deal_flag=deal_flag, **INVALID_PERSISTED_SHAPES[shape])
        return deal_flag

    return make


@pytest.mark.django_db
@pytest.mark.parametrize("shape", sorted(INVALID_PERSISTED_SHAPES))
def test_invalid_persisted_shapes_are_accepted_by_the_database(
    invalid_outcome_factory,
    shape,
):
    """The schema really is more permissive than the Phase 8 lifecycle."""
    from outcomes.models import Outcome

    deal_flag = invalid_outcome_factory(shape)

    assert Outcome.objects.filter(deal_flag=deal_flag).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("shape", sorted(INVALID_PERSISTED_SHAPES))
def test_reading_an_invalid_persisted_row_fails_loudly(
    invalid_outcome_factory,
    actor_factory,
    shape,
):
    services = _require_services()

    deal_flag = invalid_outcome_factory(shape)

    with pytest.raises(services.OutcomeConflict) as error:
        services.get_outcome_state(
            actor=actor_factory("view"),
            deal_flag_id=deal_flag.pk,
        )

    assert error.value.code == "invalid_outcome_state"
    assert error.value.detail == INVALID_STATE_DETAIL


@pytest.mark.django_db
@pytest.mark.parametrize("shape", sorted(INVALID_PERSISTED_SHAPES))
def test_mutating_an_invalid_persisted_row_changes_and_audits_nothing(
    invalid_outcome_factory,
    actor_factory,
    shape,
):
    services = _require_services()

    deal_flag = invalid_outcome_factory(shape)
    outcome = _outcome_row(deal_flag)
    before = {
        field.name: getattr(outcome, field.name)
        for field in outcome._meta.concrete_fields
    }

    calls = (
        lambda: services.skip(
            actor=actor_factory("add"),
            deal_flag_id=deal_flag.pk,
            skip_reason="attempted",
        ),
        lambda: services.record_purchase(
            actor=actor_factory("add"),
            deal_flag_id=deal_flag.pk,
            bought_at=BOUGHT_AT,
            bought_price=Decimal(BOUGHT_TEXT),
        ),
        lambda: services.record_sale(
            actor=actor_factory("change"),
            deal_flag_id=deal_flag.pk,
            sold_at=SOLD_NEXT_MANILA_DAY,
            sold_price=Decimal(SOLD_TEXT),
        ),
        lambda: services.correct_purchase(
            actor=actor_factory("change"),
            deal_flag_id=deal_flag.pk,
            bought_at=BOUGHT_AT,
            bought_price=Decimal(BOUGHT_TEXT),
        ),
        lambda: services.correct_sale(
            actor=actor_factory("change"),
            deal_flag_id=deal_flag.pk,
            sold_at=SOLD_NEXT_MANILA_DAY,
            sold_price=Decimal(SOLD_TEXT),
        ),
    )
    for call in calls:
        with pytest.raises(services.OutcomeConflict) as error:
            call()
        assert error.value.code == "invalid_outcome_state"

    outcome.refresh_from_db()
    after = {
        field.name: getattr(outcome, field.name)
        for field in outcome._meta.concrete_fields
    }
    # Never normalized, never repaired, never mutated.
    assert after == before
    assert _audit_entries(outcome.pk).count() == 0


@pytest.mark.django_db
def test_invalid_persisted_state_is_a_409_and_not_a_lifecycle_projection(
    admin_client,
    invalid_outcome_factory,
):
    _require_services()

    deal_flag = invalid_outcome_factory("acted_without_purchase")

    response = admin_client.get(_detail_url(deal_flag.pk))

    assert response.status_code == 409
    assert response.json()["code"] == "invalid_outcome_state"
    # "invalid" is deliberately not a fifth lifecycle_state value.
    assert "lifecycle_state" not in response.json()


# ---------------------------------------------------------------------------
# days_held and Manila calendar semantics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_same_manila_day_sale_yields_zero_days_held(open_factory, actor_factory):
    services = _require_services()

    deal_flag = open_factory()
    result = services.record_sale(
        actor=actor_factory("change"),
        deal_flag_id=deal_flag.pk,
        sold_at=SOLD_SAME_MANILA_DAY,
        sold_price=Decimal(SOLD_TEXT),
    )

    assert result.days_held == 0


@pytest.mark.django_db
def test_days_held_uses_manila_calendar_days_not_utc_dates(
    dealflag_factory,
    actor_factory,
):
    services = _require_services()

    # 2026-06-15T20:00Z and 2026-06-16T02:00Z are different UTC dates but the
    # same Manila calendar day (2026-06-16), so UTC subtraction would give 1.
    bought_at = datetime(2026, 6, 15, 20, 0, tzinfo=UTC)
    sold_at = datetime(2026, 6, 16, 2, 0, tzinfo=UTC)
    deal_flag = dealflag_factory()
    services.record_purchase(
        actor=actor_factory("add"),
        deal_flag_id=deal_flag.pk,
        bought_at=bought_at,
        bought_price=Decimal(BOUGHT_TEXT),
    )

    result = services.record_sale(
        actor=actor_factory("change"),
        deal_flag_id=deal_flag.pk,
        sold_at=sold_at,
        sold_price=Decimal(SOLD_TEXT),
    )

    assert result.days_held == 0


@pytest.mark.django_db
def test_timestamps_are_stored_as_utc_instants(open_factory):
    _require_services()

    deal_flag = open_factory()
    outcome = _outcome_row(deal_flag)

    assert outcome.bought_at == BOUGHT_AT
    assert outcome.bought_at.utcoffset() == BOUGHT_AT.utcoffset()


@pytest.mark.django_db
def test_sale_before_purchase_is_rejected_before_the_database_constraint(
    open_factory,
    actor_factory,
):
    services = _require_services()

    deal_flag = open_factory()
    with pytest.raises(services.OutcomeValidationError):
        services.record_sale(
            actor=actor_factory("change"),
            deal_flag_id=deal_flag.pk,
            sold_at=BOUGHT_AT.replace(hour=3),
            sold_price=Decimal(SOLD_TEXT),
        )

    outcome = _outcome_row(deal_flag)
    assert outcome.sold_at is None
    assert outcome.days_held is None


# ---------------------------------------------------------------------------
# realised_margin authority
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_negative_realised_margin_is_valid_and_persisted(
    open_factory,
    actor_factory,
):
    services = _require_services()

    deal_flag = open_factory()
    result = services.record_sale(
        actor=actor_factory("change"),
        deal_flag_id=deal_flag.pk,
        sold_at=SOLD_NEXT_MANILA_DAY,
        sold_price=Decimal(SOLD_AT_A_LOSS_TEXT),
    )

    assert result.realised_margin == Decimal("-2500.00")
    assert _outcome_row(deal_flag).realised_margin == Decimal("-2500.00")


@pytest.mark.django_db
def test_realised_margin_is_never_accepted_as_request_input(
    admin_client,
    open_factory,
):
    _require_services()

    deal_flag = open_factory()
    response = _post_json(
        admin_client,
        _operation_url("record-sale", deal_flag.pk),
        {
            "sold_at": SOLD_NEXT_MANILA_DAY.isoformat().replace("+00:00", "Z"),
            "sold_price": SOLD_TEXT,
            "realised_margin": "999999.00",
        },
    )

    assert response.status_code == 400
    assert _outcome_row(deal_flag).sold_at is None


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_correct_purchase_on_open_replaces_purchase_pair_only(
    open_factory,
    actor_factory,
):
    services = _require_services()

    deal_flag = open_factory()
    corrected_at = datetime(2026, 6, 14, 4, 0, tzinfo=UTC)
    result = services.correct_purchase(
        actor=actor_factory("change"),
        deal_flag_id=deal_flag.pk,
        bought_at=corrected_at,
        bought_price=Decimal("11000.00"),
    )

    assert result.operation == "correct_purchase"
    assert result.lifecycle_state == "open"
    assert result.bought_at == corrected_at
    assert result.bought_price == Decimal("11000.00")
    assert result.sold_at is None
    assert result.days_held is None
    assert result.realised_margin is None


@pytest.mark.django_db
def test_correct_purchase_on_closed_recomputes_days_held_and_margin(
    closed_factory,
    actor_factory,
):
    services = _require_services()

    deal_flag = closed_factory()
    assert _outcome_row(deal_flag).days_held == 1

    corrected_at = datetime(2026, 6, 13, 4, 0, tzinfo=UTC)
    result = services.correct_purchase(
        actor=actor_factory("change"),
        deal_flag_id=deal_flag.pk,
        bought_at=corrected_at,
        bought_price=Decimal("11000.00"),
    )

    assert result.lifecycle_state == "closed"
    assert result.days_held == 3
    assert result.sold_price == Decimal(SOLD_TEXT)
    assert result.realised_margin == Decimal("3000.00")


@pytest.mark.django_db
def test_correct_sale_replaces_sale_pair_and_recomputes_days_held(
    closed_factory,
    actor_factory,
):
    services = _require_services()

    deal_flag = closed_factory()
    corrected_at = datetime(2026, 6, 18, 4, 0, tzinfo=UTC)
    result = services.correct_sale(
        actor=actor_factory("change"),
        deal_flag_id=deal_flag.pk,
        sold_at=corrected_at,
        sold_price=Decimal("13000.00"),
    )

    assert result.operation == "correct_sale"
    assert result.lifecycle_state == "closed"
    assert result.bought_at == BOUGHT_AT
    assert result.bought_price == Decimal(BOUGHT_TEXT)
    assert result.sold_at == corrected_at
    assert result.days_held == 3
    assert result.realised_margin == Decimal("500.00")


# ---------------------------------------------------------------------------
# Conflict matrix
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_missing_deal_flag_is_reported_for_every_operation(actor_factory):
    services = _require_services()

    actor = actor_factory("view", "add", "change")
    missing = 987654321

    with pytest.raises(services.OutcomeNotFound) as read_error:
        services.get_outcome_state(actor=actor, deal_flag_id=missing)
    assert read_error.value.code == "deal_flag_not_found"

    for call in (
        lambda: services.skip(
            actor=actor, deal_flag_id=missing, skip_reason="none"
        ),
        lambda: services.record_purchase(
            actor=actor,
            deal_flag_id=missing,
            bought_at=BOUGHT_AT,
            bought_price=Decimal(BOUGHT_TEXT),
        ),
        lambda: services.record_sale(
            actor=actor,
            deal_flag_id=missing,
            sold_at=SOLD_NEXT_MANILA_DAY,
            sold_price=Decimal(SOLD_TEXT),
        ),
        lambda: services.correct_purchase(
            actor=actor,
            deal_flag_id=missing,
            bought_at=BOUGHT_AT,
            bought_price=Decimal(BOUGHT_TEXT),
        ),
        lambda: services.correct_sale(
            actor=actor,
            deal_flag_id=missing,
            sold_at=SOLD_NEXT_MANILA_DAY,
            sold_price=Decimal(SOLD_TEXT),
        ),
    ):
        with pytest.raises(services.OutcomeNotFound) as error:
            call()
        assert error.value.code == "deal_flag_not_found"


@pytest.mark.django_db
def test_missing_dealflag_is_404_on_every_mutation_route(admin_client):
    _require_services()

    missing = 987654321
    bodies = {
        "skip": {"skip_reason": "none"},
        "record-purchase": {
            "bought_at": "2026-06-15T04:00:00Z",
            "bought_price": BOUGHT_TEXT,
        },
        "record-sale": {
            "sold_at": "2026-06-16T04:00:00Z",
            "sold_price": SOLD_TEXT,
        },
        "correct-purchase": {
            "bought_at": "2026-06-15T04:00:00Z",
            "bought_price": BOUGHT_TEXT,
        },
        "correct-sale": {
            "sold_at": "2026-06-16T04:00:00Z",
            "sold_price": SOLD_TEXT,
        },
    }
    for segment, body in bodies.items():
        response = _post_json(
            admin_client, _operation_url(segment, missing), body
        )
        assert response.status_code == 404, segment
        assert response.json()["code"] == "deal_flag_not_found", segment


@pytest.mark.django_db
def test_skip_conflicts_when_any_outcome_already_exists(
    skipped_factory,
    open_factory,
    actor_factory,
):
    services = _require_services()

    for deal_flag in (skipped_factory(), open_factory()):
        with pytest.raises(services.OutcomeConflict) as error:
            services.skip(
                actor=actor_factory("add"),
                deal_flag_id=deal_flag.pk,
                skip_reason="second attempt",
            )
        assert error.value.code == "outcome_already_exists"


@pytest.mark.django_db
def test_record_purchase_conflicts_against_open_and_closed(
    open_factory,
    closed_factory,
    actor_factory,
):
    services = _require_services()

    for deal_flag in (open_factory(), closed_factory()):
        before = _outcome_row(deal_flag)
        with pytest.raises(services.OutcomeConflict) as error:
            services.record_purchase(
                actor=actor_factory("add"),
                deal_flag_id=deal_flag.pk,
                bought_at=datetime(2026, 1, 1, tzinfo=UTC),
                bought_price=Decimal("1.00"),
            )
        assert error.value.code == "outcome_already_exists"
        after = _outcome_row(deal_flag)
        # Existing acquisition evidence is never overwritten.
        assert after.bought_at == before.bought_at
        assert after.bought_price == before.bought_price


@pytest.mark.django_db
def test_record_sale_requires_an_open_position(
    dealflag_factory,
    skipped_factory,
    closed_factory,
    actor_factory,
):
    services = _require_services()

    with pytest.raises(services.OutcomeNotFound) as missing:
        services.record_sale(
            actor=actor_factory("change"),
            deal_flag_id=dealflag_factory().pk,
            sold_at=SOLD_NEXT_MANILA_DAY,
            sold_price=Decimal(SOLD_TEXT),
        )
    assert missing.value.code == "outcome_not_found"

    for deal_flag in (skipped_factory(), closed_factory()):
        with pytest.raises(services.OutcomeConflict) as error:
            services.record_sale(
                actor=actor_factory("change"),
                deal_flag_id=deal_flag.pk,
                sold_at=SOLD_NEXT_MANILA_DAY,
                sold_price=Decimal(SOLD_TEXT),
            )
        assert error.value.code == "ineligible_outcome_state"


@pytest.mark.django_db
def test_correct_purchase_requires_recorded_acquisition(
    dealflag_factory,
    skipped_factory,
    actor_factory,
):
    services = _require_services()

    with pytest.raises(services.OutcomeNotFound) as missing:
        services.correct_purchase(
            actor=actor_factory("change"),
            deal_flag_id=dealflag_factory().pk,
            bought_at=BOUGHT_AT,
            bought_price=Decimal(BOUGHT_TEXT),
        )
    assert missing.value.code == "outcome_not_found"

    with pytest.raises(services.OutcomeConflict) as error:
        services.correct_purchase(
            actor=actor_factory("change"),
            deal_flag_id=skipped_factory().pk,
            bought_at=BOUGHT_AT,
            bought_price=Decimal(BOUGHT_TEXT),
        )
    assert error.value.code == "ineligible_outcome_state"


@pytest.mark.django_db
def test_correct_sale_requires_a_closed_position(
    dealflag_factory,
    skipped_factory,
    open_factory,
    actor_factory,
):
    services = _require_services()

    with pytest.raises(services.OutcomeNotFound) as missing:
        services.correct_sale(
            actor=actor_factory("change"),
            deal_flag_id=dealflag_factory().pk,
            sold_at=SOLD_NEXT_MANILA_DAY,
            sold_price=Decimal(SOLD_TEXT),
        )
    assert missing.value.code == "outcome_not_found"

    for deal_flag in (skipped_factory(), open_factory()):
        with pytest.raises(services.OutcomeConflict) as error:
            services.correct_sale(
                actor=actor_factory("change"),
                deal_flag_id=deal_flag.pk,
                sold_at=SOLD_NEXT_MANILA_DAY,
                sold_price=Decimal(SOLD_TEXT),
            )
        assert error.value.code == "ineligible_outcome_state"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("reason", ["", "   ", "\t\n"])
def test_blank_skip_reason_is_rejected(dealflag_factory, actor_factory, reason):
    services = _require_services()
    from outcomes.models import Outcome

    with pytest.raises(services.OutcomeValidationError):
        services.skip(
            actor=actor_factory("add"),
            deal_flag_id=dealflag_factory().pk,
            skip_reason=reason,
        )

    assert Outcome.objects.count() == 0


@pytest.mark.django_db
def test_negative_price_is_rejected_and_zero_is_accepted(
    dealflag_factory,
    actor_factory,
):
    services = _require_services()

    with pytest.raises(services.OutcomeValidationError):
        services.record_purchase(
            actor=actor_factory("add"),
            deal_flag_id=dealflag_factory().pk,
            bought_at=BOUGHT_AT,
            bought_price=Decimal("-1.00"),
        )

    # Every money constraint in this repository is >= 0, never > 0.
    free_flag = dealflag_factory()
    result = services.record_purchase(
        actor=actor_factory("add"),
        deal_flag_id=free_flag.pk,
        bought_at=BOUGHT_AT,
        bought_price=Decimal("0.00"),
    )
    assert result.bought_price == Decimal("0.00")


@pytest.mark.django_db
def test_naive_timestamp_input_is_rejected(dealflag_factory, actor_factory):
    services = _require_services()

    with pytest.raises(services.OutcomeValidationError):
        services.record_purchase(
            actor=actor_factory("add"),
            deal_flag_id=dealflag_factory().pk,
            bought_at=datetime(2026, 6, 15, 12, 0),
            bought_price=Decimal(BOUGHT_TEXT),
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "price",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("12500.001"),
        Decimal("99999999999.00"),
    ],
)
def test_service_rejects_non_finite_and_out_of_range_decimals(
    dealflag_factory,
    actor_factory,
    price,
):
    """The service validates typed Decimals directly, independent of transport."""
    services = _require_services()
    from outcomes.models import Outcome

    with pytest.raises(services.OutcomeValidationError):
        services.record_purchase(
            actor=actor_factory("add"),
            deal_flag_id=dealflag_factory().pk,
            bought_at=BOUGHT_AT,
            bought_price=price,
        )

    assert Outcome.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {"bought_at": "2026-06-15T04:00:00Z", "bought_price": 12500},
        {"bought_at": "2026-06-15T04:00:00Z", "bought_price": 12500.00},
        {"bought_at": "2026-06-15T04:00:00Z", "bought_price": None},
        {"bought_at": "2026-06-15T04:00:00Z", "bought_price": "12500.001"},
        {"bought_at": "2026-06-15T04:00:00Z", "bought_price": "not-a-price"},
        {"bought_at": "2026-06-15T04:00:00Z", "bought_price": "NaN"},
        {"bought_at": "2026-06-15T12:00:00", "bought_price": "12500.00"},
        {"bought_price": "12500.00"},
        {"bought_at": "2026-06-15T04:00:00Z"},
        {
            "bought_at": "2026-06-15T04:00:00Z",
            "bought_price": "12500.00",
            "days_held": 3,
        },
    ],
)
def test_invalid_record_purchase_bodies_are_rejected(
    admin_client,
    dealflag_factory,
    body,
):
    _require_services()
    from outcomes.models import Outcome

    deal_flag = dealflag_factory()
    response = _post_json(
        admin_client,
        _operation_url("record-purchase", deal_flag.pk),
        body,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"
    assert Outcome.objects.count() == 0


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_operation_requires_parent_dealflag_view_permission(
    dealflag_factory,
    actor_factory,
):
    services = _require_services()
    from outcomes.models import Outcome

    deal_flag = dealflag_factory()
    actor = actor_factory("view", "add", "change", view_dealflag=False)

    calls = (
        lambda: services.get_outcome_state(
            actor=actor, deal_flag_id=deal_flag.pk
        ),
        lambda: services.skip(
            actor=actor, deal_flag_id=deal_flag.pk, skip_reason="no"
        ),
        lambda: services.record_purchase(
            actor=actor,
            deal_flag_id=deal_flag.pk,
            bought_at=BOUGHT_AT,
            bought_price=Decimal(BOUGHT_TEXT),
        ),
        lambda: services.record_sale(
            actor=actor,
            deal_flag_id=deal_flag.pk,
            sold_at=SOLD_NEXT_MANILA_DAY,
            sold_price=Decimal(SOLD_TEXT),
        ),
        lambda: services.correct_purchase(
            actor=actor,
            deal_flag_id=deal_flag.pk,
            bought_at=BOUGHT_AT,
            bought_price=Decimal(BOUGHT_TEXT),
        ),
        lambda: services.correct_sale(
            actor=actor,
            deal_flag_id=deal_flag.pk,
            sold_at=SOLD_NEXT_MANILA_DAY,
            sold_price=Decimal(SOLD_TEXT),
        ),
    )
    for call in calls:
        with pytest.raises(services.OutcomePermissionDenied) as error:
            call()
        assert error.value.code == "permission_denied"

    assert Outcome.objects.count() == 0


@pytest.mark.django_db
def test_missing_dealflag_permission_cannot_distinguish_missing_from_existing(
    dealflag_factory,
    actor_factory,
):
    services = _require_services()

    existing = dealflag_factory()
    actor = actor_factory("view", view_dealflag=False)

    with pytest.raises(services.OutcomePermissionDenied):
        services.get_outcome_state(actor=actor, deal_flag_id=existing.pk)
    with pytest.raises(services.OutcomePermissionDenied):
        services.get_outcome_state(actor=actor, deal_flag_id=987654321)


@pytest.mark.django_db
def test_record_purchase_requires_add_permission_on_both_paths(
    dealflag_factory,
    skipped_factory,
    actor_factory,
):
    services = _require_services()

    # change_outcome alone must not reach either path, including skipped->open.
    for deal_flag in (dealflag_factory(), skipped_factory()):
        with pytest.raises(services.OutcomePermissionDenied):
            services.record_purchase(
                actor=actor_factory("change"),
                deal_flag_id=deal_flag.pk,
                bought_at=BOUGHT_AT,
                bought_price=Decimal(BOUGHT_TEXT),
            )


@pytest.mark.django_db
def test_change_operations_require_change_permission(open_factory, actor_factory):
    services = _require_services()

    with pytest.raises(services.OutcomePermissionDenied):
        services.record_sale(
            actor=actor_factory("add"),
            deal_flag_id=open_factory().pk,
            sold_at=SOLD_NEXT_MANILA_DAY,
            sold_price=Decimal(SOLD_TEXT),
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("is_active", "is_staff"),
    [(False, True), (True, False)],
)
def test_inactive_and_nonstaff_actors_are_denied(
    dealflag_factory,
    actor_factory,
    is_active,
    is_staff,
):
    services = _require_services()

    actor = actor_factory("add", is_active=is_active, is_staff=is_staff)
    with pytest.raises(services.OutcomePermissionDenied):
        services.skip(
            actor=actor,
            deal_flag_id=dealflag_factory().pk,
            skip_reason="denied",
        )


@pytest.mark.django_db
def test_service_observes_permission_revoked_after_an_earlier_decision(
    dealflag_factory,
    actor_factory,
):
    services = _require_services()
    from outcomes.models import Outcome

    actor = actor_factory("add")
    services.skip(
        actor=actor,
        deal_flag_id=dealflag_factory().pk,
        skip_reason="first decision",
    )

    _revoke(actor, Outcome, "add")

    with pytest.raises(services.OutcomePermissionDenied):
        services.skip(
            actor=actor,
            deal_flag_id=dealflag_factory().pk,
            skip_reason="must be denied",
        )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_each_successful_operation_writes_exactly_one_audit_entry(
    dealflag_factory,
    actor_factory,
):
    services = _require_services()

    deal_flag = dealflag_factory()
    services.record_purchase(
        actor=actor_factory("add"),
        deal_flag_id=deal_flag.pk,
        bought_at=BOUGHT_AT,
        bought_price=Decimal(BOUGHT_TEXT),
    )
    outcome_pk = _outcome_row(deal_flag).pk
    assert _audit_entries(outcome_pk).count() == 1
    assert _audit_entries(outcome_pk).get().action_flag == ADDITION

    services.record_sale(
        actor=actor_factory("change"),
        deal_flag_id=deal_flag.pk,
        sold_at=SOLD_NEXT_MANILA_DAY,
        sold_price=Decimal(SOLD_TEXT),
    )
    assert _audit_entries(outcome_pk).count() == 2

    services.correct_sale(
        actor=actor_factory("change"),
        deal_flag_id=deal_flag.pk,
        sold_at=SOLD_NEXT_MANILA_DAY,
        sold_price=Decimal("13500.00"),
    )
    entries = _audit_entries(outcome_pk).order_by("pk")
    assert entries.count() == 3
    assert [entry.action_flag for entry in entries] == [ADDITION, CHANGE, CHANGE]
    assert [entry.change_message for entry in entries] == [
        PURCHASE_MESSAGE,
        SALE_MESSAGE,
        CORRECT_SALE_MESSAGE,
    ]


@pytest.mark.django_db
def test_audit_messages_are_exact_for_every_operation(
    dealflag_factory,
    skipped_factory,
    actor_factory,
):
    services = _require_services()

    skipped = skipped_factory()
    skipped_pk = _outcome_row(skipped).pk
    assert _audit_entries(skipped_pk).get().change_message == SKIP_MESSAGE

    services.record_purchase(
        actor=actor_factory("add"),
        deal_flag_id=skipped.pk,
        bought_at=BOUGHT_AT,
        bought_price=Decimal(BOUGHT_TEXT),
    )
    assert _audit_entries(skipped_pk).order_by("pk").last().change_message == (
        PURCHASE_AFTER_SKIP_MESSAGE
    )

    fresh = dealflag_factory()
    services.record_purchase(
        actor=actor_factory("add"),
        deal_flag_id=fresh.pk,
        bought_at=BOUGHT_AT,
        bought_price=Decimal(BOUGHT_TEXT),
    )
    fresh_pk = _outcome_row(fresh).pk
    assert _audit_entries(fresh_pk).get().change_message == PURCHASE_MESSAGE

    services.correct_purchase(
        actor=actor_factory("change"),
        deal_flag_id=fresh.pk,
        bought_at=BOUGHT_AT,
        bought_price=Decimal("11000.00"),
    )
    assert _audit_entries(fresh_pk).order_by("pk").last().change_message == (
        CORRECT_PURCHASE_MESSAGE
    )


@pytest.mark.django_db
def test_skipped_to_open_purchase_is_audited_as_a_distinguishable_change(
    skipped_factory,
    actor_factory,
):
    services = _require_services()

    deal_flag = skipped_factory()
    outcome_pk = _outcome_row(deal_flag).pk
    assert _audit_entries(outcome_pk).get().action_flag == ADDITION

    services.record_purchase(
        actor=actor_factory("add"),
        deal_flag_id=deal_flag.pk,
        bought_at=BOUGHT_AT,
        bought_price=Decimal(BOUGHT_TEXT),
    )

    entries = list(_audit_entries(outcome_pk).order_by("pk"))
    assert [entry.action_flag for entry in entries] == [ADDITION, CHANGE]
    # The two record_purchase paths must be distinguishable in the audit trail.
    assert [entry.change_message for entry in entries] == [
        SKIP_MESSAGE,
        PURCHASE_AFTER_SKIP_MESSAGE,
    ]
    assert PURCHASE_AFTER_SKIP_MESSAGE != PURCHASE_MESSAGE


@pytest.mark.django_db
def test_failed_operations_write_no_audit_entry(
    dealflag_factory,
    open_factory,
    actor_factory,
):
    services = _require_services()

    with pytest.raises(services.OutcomeValidationError):
        services.skip(
            actor=actor_factory("add"),
            deal_flag_id=dealflag_factory().pk,
            skip_reason="  ",
        )

    deal_flag = open_factory()
    outcome_pk = _outcome_row(deal_flag).pk
    before = _audit_entries(outcome_pk).count()

    with pytest.raises(services.OutcomeConflict):
        services.record_purchase(
            actor=actor_factory("add"),
            deal_flag_id=deal_flag.pk,
            bought_at=BOUGHT_AT,
            bought_price=Decimal(BOUGHT_TEXT),
        )

    assert _audit_entries(outcome_pk).count() == before


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_nested_outcome_routes_are_exact():
    assert _detail_url(23) == "/api/v1/deal-flags/23/outcome/"
    for segment, name in OPERATION_ROUTES:
        assert _required_reverse(name, [23]) == (
            f"/api/v1/deal-flags/23/outcome/{segment}/"
        )


@pytest.mark.django_db
def test_get_untracked_dealflag_returns_200_untracked_projection(
    admin_client,
    dealflag_factory,
):
    _require_services()

    deal_flag = dealflag_factory()
    response = admin_client.get(_detail_url(deal_flag.pk))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == STATE_FIELDS
    assert body["deal_flag_id"] == deal_flag.pk
    assert body["outcome_id"] is None
    assert body["lifecycle_state"] == "untracked"
    assert body["acted"] is None
    assert body["realised_margin"] is None


@pytest.mark.django_db
def test_get_missing_dealflag_returns_404(admin_client):
    _require_services()

    response = admin_client.get(_detail_url(987654321))

    assert response.status_code == 404
    assert response.json()["code"] == "deal_flag_not_found"


@pytest.mark.django_db
def test_api_mutation_envelope_is_decimal_safe_and_utc(
    admin_client,
    open_factory,
):
    _require_services()

    deal_flag = open_factory()
    response = _post_json(
        admin_client,
        _operation_url("record-sale", deal_flag.pk),
        {
            "sold_at": "2026-06-16T04:00:00Z",
            "sold_price": SOLD_TEXT,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == OPERATION_FIELDS
    assert body["operation"] == "record_sale"
    assert body["lifecycle_state"] == "closed"
    assert body["bought_price"] == BOUGHT_TEXT
    assert body["sold_price"] == SOLD_TEXT
    assert body["realised_margin"] == "1500.00"
    assert body["days_held"] == 1
    assert body["bought_at"].endswith("Z")
    assert body["sold_at"] == "2026-06-16T04:00:00Z"


@pytest.mark.django_db
def test_api_conflicts_use_stable_codes_and_statuses(
    admin_client,
    open_factory,
    skipped_factory,
):
    _require_services()

    conflict = _post_json(
        admin_client,
        _operation_url("record-purchase", open_factory().pk),
        {"bought_at": "2026-06-15T04:00:00Z", "bought_price": BOUGHT_TEXT},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "outcome_already_exists"

    ineligible = _post_json(
        admin_client,
        _operation_url("record-sale", skipped_factory().pk),
        {"sold_at": "2026-06-16T04:00:00Z", "sold_price": SOLD_TEXT},
    )
    assert ineligible.status_code == 409
    assert ineligible.json()["code"] == "ineligible_outcome_state"


@pytest.mark.django_db
def test_api_rejects_unsupported_methods_and_media_types(
    admin_client,
    dealflag_factory,
):
    _require_services()

    deal_flag = dealflag_factory()
    assert admin_client.post(_detail_url(deal_flag.pk)).status_code == 405
    for segment, _name in OPERATION_ROUTES:
        url = _operation_url(segment, deal_flag.pk)
        assert admin_client.get(url).status_code == 405
        assert admin_client.delete(url).status_code == 405
        assert admin_client.post(
            url,
            data="x",
            content_type="text/plain",
        ).status_code == 415


@pytest.mark.django_db
def test_api_requires_session_active_staff_and_permissions(
    client,
    dealflag_factory,
    user_factory,
):
    _require_services()
    from pricing.models import DealFlag

    deal_flag = dealflag_factory()
    url = _operation_url("skip", deal_flag.pk)
    body = {"skip_reason": "denied"}

    assert _post_json(client, url, body).status_code == 403

    nonstaff = user_factory(is_staff=False)
    _grant(nonstaff, DealFlag, "view")
    client.force_login(nonstaff)
    assert _post_json(client, url, body).status_code == 403

    staff_without_permissions = user_factory()
    client.force_login(staff_without_permissions)
    assert _post_json(client, url, body).status_code == 403
    assert client.get(_detail_url(deal_flag.pk)).status_code == 403


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_creation_race_yields_one_outcome_and_a_stable_conflict(
    dealflag_factory,
    actor_factory,
):
    services = _require_services()
    from outcomes.models import Outcome

    deal_flag = dealflag_factory()
    actor = actor_factory("add")
    start = threading.Barrier(2)
    outcomes = []
    failures = []
    transaction_usable = []

    def attempt():
        close_old_connections()
        try:
            thread_actor = get_user_model().objects.get(pk=actor.pk)
            start.wait(timeout=5)
            with transaction.atomic():
                try:
                    result = services.record_purchase(
                        actor=thread_actor,
                        deal_flag_id=deal_flag.pk,
                        bought_at=BOUGHT_AT,
                        bought_price=Decimal(BOUGHT_TEXT),
                    )
                except services.OutcomeConflict as conflict:
                    failures.append(conflict)
                    # A savepoint-safe conflict leaves the caller's transaction
                    # usable; a bare IntegrityError catch would raise here.
                    transaction_usable.append(Outcome.objects.count())
                else:
                    outcomes.append(result)
        except Exception as error:  # Asserted below.
            failures.append(error)
        finally:
            close_old_connections()

    workers = [threading.Thread(target=attempt) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive()

    assert Outcome.objects.filter(deal_flag=deal_flag).count() == 1
    assert len(outcomes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], services.OutcomeConflict)
    assert failures[0].code == "outcome_already_exists"
    assert transaction_usable == [1]
    assert _audit_entries(_outcome_row(deal_flag).pk).count() == 1


# ---------------------------------------------------------------------------
# Django admin
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_generic_admin_outcome_mutation_is_unavailable(user_factory):
    from django.contrib import admin as django_admin
    from django.test import RequestFactory
    from outcomes.models import Outcome

    model_admin = django_admin.site._registry[Outcome]
    request = RequestFactory().get("/admin/outcomes/outcome/")
    request.user = user_factory(is_superuser=True)

    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False
    assert model_admin.actions in (None, [], ())


@pytest.mark.django_db
def test_admin_generic_add_and_delete_urls_are_blocked(admin_client, open_factory):
    _require_services()

    deal_flag = open_factory()
    outcome_pk = _outcome_row(deal_flag).pk

    assert admin_client.get("/admin/outcomes/outcome/add/").status_code in (
        302,
        403,
        404,
    )
    assert admin_client.post(
        f"/admin/outcomes/outcome/{outcome_pk}/delete/"
    ).status_code in (302, 403, 404)


@pytest.mark.django_db
def test_admin_untracked_worklist_and_operation_views_are_registered():
    for name in (
        "admin:outcomes_outcome_untracked",
        *(f"admin:outcomes_outcome_{view}" for view in ADMIN_OPERATION_VIEWS),
    ):
        args = None if name.endswith("untracked") else [23]
        _required_reverse(name, args)


@pytest.mark.django_db
def test_admin_untracked_worklist_lists_dealflags_without_an_outcome(
    admin_client,
    dealflag_factory,
    open_factory,
):
    _require_services()

    untracked = dealflag_factory()
    tracked = open_factory()

    response = admin_client.get(
        _required_reverse("admin:outcomes_outcome_untracked")
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert str(untracked.pk) in content
    assert _required_reverse(
        "admin:outcomes_outcome_record_purchase", [untracked.pk]
    ) in content
    assert _required_reverse(
        "admin:outcomes_outcome_record_purchase", [tracked.pk]
    ) not in content


@pytest.mark.django_db
def test_admin_operation_views_are_post_only(admin_client, dealflag_factory):
    _require_services()

    deal_flag = dealflag_factory()
    for view in ADMIN_OPERATION_VIEWS:
        url = _required_reverse(f"admin:outcomes_outcome_{view}", [deal_flag.pk])
        assert admin_client.get(url).status_code == 405


def _admin_post(admin_client, view, deal_flag_pk, data):
    return admin_client.post(
        _required_reverse(f"admin:outcomes_outcome_{view}", [deal_flag_pk]),
        data=data,
    )


ADMIN_OPERATION_CASES = (
    (
        "skip",
        "dealflag_factory",
        {"skip_reason": "  not worth the trip  "},
        "skipped",
        SKIP_MESSAGE,
        ADDITION,
    ),
    (
        "record_purchase",
        "dealflag_factory",
        {"bought_at": "2026-06-15T04:00:00Z", "bought_price": BOUGHT_TEXT},
        "open",
        PURCHASE_MESSAGE,
        ADDITION,
    ),
    (
        "record_sale",
        "open_factory",
        {"sold_at": "2026-06-16T04:00:00Z", "sold_price": SOLD_TEXT},
        "closed",
        SALE_MESSAGE,
        CHANGE,
    ),
    (
        "correct_purchase",
        "open_factory",
        {"bought_at": "2026-06-14T04:00:00Z", "bought_price": "11000.00"},
        "open",
        CORRECT_PURCHASE_MESSAGE,
        CHANGE,
    ),
    (
        "correct_sale",
        "closed_factory",
        {"sold_at": "2026-06-18T04:00:00Z", "sold_price": "13000.00"},
        "closed",
        CORRECT_SALE_MESSAGE,
        CHANGE,
    ),
)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("view", "starting_factory", "data", "expected_state", "message", "flag"),
    ADMIN_OPERATION_CASES,
    ids=[case[0] for case in ADMIN_OPERATION_CASES],
)
def test_admin_governed_views_perform_every_domain_operation(
    admin_client,
    admin_user,
    request,
    view,
    starting_factory,
    data,
    expected_state,
    message,
    flag,
):
    services = _require_services()

    deal_flag = request.getfixturevalue(starting_factory)()
    existing = _outcome_row(deal_flag)
    audit_before = 0 if existing is None else _audit_entries(existing.pk).count()

    response = _admin_post(admin_client, view, deal_flag.pk, data)

    assert response.status_code in (200, 302)
    outcome = _outcome_row(deal_flag)
    assert outcome is not None

    state = services.get_outcome_state(
        actor=admin_user,
        deal_flag_id=deal_flag.pk,
    )
    assert state.lifecycle_state == expected_state

    entries = _audit_entries(outcome.pk).order_by("pk")
    assert entries.count() == audit_before + 1
    assert entries.last().action_flag == flag
    assert entries.last().change_message == message


@pytest.mark.django_db
def test_admin_views_honor_service_lifecycle_and_permission_contract(
    client,
    user_factory,
    skipped_factory,
    dealflag_factory,
):
    _require_services()
    from outcomes.models import Outcome
    from pricing.models import DealFlag

    # A lifecycle conflict through admin must not mutate or audit.
    admin_user = user_factory(is_superuser=True)
    client.force_login(admin_user)
    skipped = skipped_factory()
    outcome_pk = _outcome_row(skipped).pk
    _admin_post(
        client,
        "record_sale",
        skipped.pk,
        {"sold_at": "2026-06-16T04:00:00Z", "sold_price": SOLD_TEXT},
    )
    outcome = _outcome_row(skipped)
    assert outcome.sold_at is None
    assert _audit_entries(outcome_pk).count() == 1

    # Staff lacking outcomes.add_outcome cannot skip through admin either.
    weak = user_factory()
    _grant(weak, DealFlag, "view")
    client.force_login(weak)
    fresh = dealflag_factory()
    _admin_post(client, "skip", fresh.pk, {"skip_reason": "denied"})
    assert not Outcome.objects.filter(deal_flag=fresh).exists()


# ---------------------------------------------------------------------------
# Session and CSRF
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mutation_endpoint_requires_a_valid_csrf_token(
    user_factory,
    dealflag_factory,
):
    from django.test import Client
    from outcomes.models import Outcome
    from pricing.models import DealFlag

    _require_services()

    actor = user_factory()
    _grant(actor, DealFlag, "view")
    _grant(actor, Outcome, "add")
    deal_flag = dealflag_factory()
    url = _operation_url("skip", deal_flag.pk)
    body = {"skip_reason": "csrf coverage"}

    unprotected = Client(enforce_csrf_checks=True)
    unprotected.force_login(actor)
    missing_token = _post_json(unprotected, url, body)

    assert missing_token.status_code == 403
    assert not Outcome.objects.filter(deal_flag=deal_flag).exists()
    assert _all_outcome_audit_entries().count() == 0

    protected = Client(enforce_csrf_checks=True)
    protected.force_login(actor)
    bootstrap = protected.get(_required_reverse("api-v1:session-csrf"))
    assert bootstrap.status_code == 200
    accepted = _post_json(
        protected,
        url,
        body,
        HTTP_X_CSRFTOKEN=bootstrap.json()["csrf_token"],
    )

    assert accepted.status_code == 200
    assert accepted.json()["lifecycle_state"] == "skipped"
    assert Outcome.objects.filter(deal_flag=deal_flag).count() == 1


# ---------------------------------------------------------------------------
# Adjacent-domain boundary
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_outcome_operations_write_no_adjacent_domain_state(
    dealflag_factory,
    actor_factory,
):
    services = _require_services()
    from catalogue.models import Sku, SkuAlias
    from ingestion.models import RawListing
    from listings.models import Listing
    from pricing.models import DealFlag, PricePoint

    deal_flag = dealflag_factory()

    def snapshot():
        return (
            list(RawListing.objects.order_by("pk").values()),
            list(Listing.objects.order_by("pk").values()),
            list(Sku.objects.order_by("pk").values()),
            list(SkuAlias.objects.order_by("pk").values()),
            list(PricePoint.objects.order_by("pk").values()),
            list(DealFlag.objects.order_by("pk").values()),
        )

    before = snapshot()
    services.record_purchase(
        actor=actor_factory("add"),
        deal_flag_id=deal_flag.pk,
        bought_at=BOUGHT_AT,
        bought_price=Decimal(BOUGHT_TEXT),
    )
    services.record_sale(
        actor=actor_factory("change"),
        deal_flag_id=deal_flag.pk,
        sold_at=SOLD_NEXT_MANILA_DAY,
        sold_price=Decimal(SOLD_TEXT),
    )

    assert snapshot() == before


@pytest.mark.django_db
def test_api_reads_never_create_an_outcome(admin_client, dealflag_factory):
    _require_services()
    from outcomes.models import Outcome

    deal_flag = dealflag_factory()
    for _ in range(3):
        assert admin_client.get(_detail_url(deal_flag.pk)).status_code == 200
    admin_client.get(reverse("api-v1:dealflag-list"))

    assert Outcome.objects.count() == 0
