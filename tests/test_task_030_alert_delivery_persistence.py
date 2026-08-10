"""Frozen TASK_030 AlertDelivery persistence and unique-claim acceptance tests.

TASK_030 is persistence only. Nothing here touches Telegram, configuration, the
eligibility query, or send orchestration - those belong to TASK_031 and
TASK_032. See tasks/TASK_030_ALERT_DELIVERY_PERSISTENCE.md and
docs/07_PLANNING.md sections 4, 7, and 16.

The durable at-most-once substrate needs two distinct database properties:
UNIQUE on deal_flag stops a second concurrent claim, and a lifecycle/delete
guard stops the existing claim from being moved or removed - either of which
would leave the DealFlag row-free and therefore alert-eligible again.

Two exception types are asserted deliberately and are not interchangeable:
CheckConstraint violations surface as IntegrityError; the PostgreSQL lifecycle
guard raises SQLSTATE P0001, which Django surfaces as ProgrammingError, matching
the TASK_019 immutability-trigger tests.

Model imports are deliberately performed inside each test rather than at module
scope so that this file still collects cleanly before the alerts app exists.
"""

import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import (
    IntegrityError,
    ProgrammingError,
    connection,
    models,
    transaction,
)
from django.db.models.deletion import PROTECT
from django.db.models.fields import NOT_PROVIDED
from django.utils import timezone


EXPECTED_STATUS_VALUES = ("pending", "sent", "failed")

# A sanitized, application-owned failure string: never a request URL, never a
# raw transport exception, never anything that could embed the bot token.
# See docs/07_PLANNING.md section 10.3.
SANITIZED_FAILURE_DETAIL = "Telegram rejected the message."

EXPECTED_CONSTRAINT_NAMES = (
    "alertdelivery_status_in_vocabulary",
    "alertdelivery_terminal_at_matches_status",
    "alertdelivery_failure_detail_matches_status",
    "alertdelivery_terminal_at_not_before_claimed_at",
)

# Field names the approved plan forbids: retry/attempt history, recipient and
# channel abstractions, and generic notification metadata.
# See docs/07_PLANNING.md section 2 and TASK_030 section 4.4.
FORBIDDEN_FIELD_NAMES = (
    "attempt_count",
    "attempts",
    "retry_count",
    "retries",
    "next_retry_at",
    "retry_after",
    "cooldown_until",
    "channel",
    "recipient",
    "recipients",
    "chat_id",
    "notification_type",
    "metadata",
    "payload",
    "message_id",
    "telegram_message_id",
)


@pytest.fixture
def deal_flag_factory(db):
    """Build real DealFlags through the full committed chain, as TASK_004 does."""
    from catalogue.models import Sku
    from ingestion.models import RawListing
    from listings.models import Listing
    from pricing.models import DealFlag, PricePoint
    from sources.models import Source

    sku = Sku.objects.create(
        brand="Synthetic",
        model="TASK 030 GPU",
        variant="",
        category="gpu",
        launch_msrp=Decimal("34995.00"),
        launch_date=date(2026, 1, 1),
    )
    source = Source.objects.create(
        name="task_030_source",
        base_url="https://example.invalid",
        terms_notes="Synthetic TASK_030 fixture",
        rate_limit=None,
    )
    pricepoint = PricePoint.objects.create(
        sku=sku,
        condition="used",
        day=date(2026, 7, 30),
        median=Decimal("18000.0000"),
        p25=Decimal("17000.0000"),
        p75=Decimal("19000.0000"),
        n_listings=10,
    )

    def make():
        raw_listing = RawListing.objects.create(
            source=source,
            raw_title="Synthetic TASK 030 GPU",
            raw_price_text="15500",
            raw_price=Decimal("15500.00"),
            url="https://example.invalid/task-030",
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
            resolution_confidence=Decimal("1.0000"),
            resolution_method="exact_alias",
            resolved_at=timezone.now(),
        )
        return DealFlag.objects.create(
            listing=listing,
            score=Decimal("-3.5000"),
            baseline_pricepoint=pricepoint,
            reason="asking_price_mad_v1",
            flagged_at=timezone.now(),
        )

    return make


@pytest.fixture
def deal_flag(deal_flag_factory):
    return deal_flag_factory()


def claim(deal_flag, claimed_at=None):
    """Create a durable claim the only way the contract allows: pending."""
    from alerts.models import AlertDelivery

    return AlertDelivery.objects.create(
        deal_flag=deal_flag,
        status="pending",
        claimed_at=claimed_at or timezone.now(),
        terminal_at=None,
        failure_detail=None,
    )


def drive_to_sent(delivery):
    """Move a pending claim to sent through the approved transition."""
    delivery.status = "sent"
    delivery.terminal_at = timezone.now()
    delivery.save()
    return delivery


def drive_to_failed(delivery, failure_detail=SANITIZED_FAILURE_DETAIL):
    """Move a pending claim to failed through the approved transition."""
    delivery.status = "failed"
    delivery.terminal_at = timezone.now()
    delivery.failure_detail = failure_detail
    delivery.save()
    return delivery


# --- App and model registration -------------------------------------------


def test_alerts_app_is_installed():
    """The alerts app is registered so its model and migration are part of the project."""
    from django.conf import settings

    assert "alerts" in settings.INSTALLED_APPS


def test_alert_delivery_model_is_importable_and_registered():
    """AlertDelivery lives in the alerts app."""
    from django.apps import apps

    from alerts.models import AlertDelivery

    assert apps.get_model("alerts", "AlertDelivery") is AlertDelivery


# --- Schema contract -------------------------------------------------------


def test_deal_flag_is_a_protected_one_to_one_to_dealflag():
    """One AlertDelivery per DealFlag, protectively related, mirroring Outcome.deal_flag.

    PROTECT is asserted as a declaration rather than provoked at runtime: TASK_019
    installed PostgreSQL triggers that make deleting a DealFlag impossible by any
    path, so a ProtectedError test would exercise that trigger, not this contract.
    See tasks/TASK_030_ALERT_DELIVERY_PERSISTENCE.md section 8.
    """
    from pricing.models import DealFlag

    from alerts.models import AlertDelivery

    field = AlertDelivery._meta.get_field("deal_flag")
    assert isinstance(field, models.OneToOneField)
    assert field.remote_field.model is DealFlag
    assert field.remote_field.on_delete is PROTECT
    assert field.remote_field.related_name == "alert_delivery"
    assert field.null is False


def test_status_vocabulary_is_exactly_pending_sent_failed():
    """Exactly three states exist. 'sent' is deliberate: it never claims a human received anything."""
    from alerts.models import AlertDelivery

    field = AlertDelivery._meta.get_field("status")
    assert isinstance(field, models.CharField)
    assert field.max_length == 20
    assert field.null is False
    assert field.default is NOT_PROVIDED
    assert tuple(choice[0] for choice in field.choices) == EXPECTED_STATUS_VALUES


def test_timestamp_and_failure_detail_field_metadata_is_exact():
    """claimed_at is always present; terminal_at and failure_detail are state-dependent."""
    from alerts.models import AlertDelivery

    claimed_at = AlertDelivery._meta.get_field("claimed_at")
    assert isinstance(claimed_at, models.DateTimeField)
    assert claimed_at.null is False
    # Set explicitly by the claiming caller, matching DealFlag.flagged_at.
    assert claimed_at.auto_now_add is False
    assert claimed_at.auto_now is False
    assert claimed_at.default is NOT_PROVIDED

    terminal_at = AlertDelivery._meta.get_field("terminal_at")
    assert isinstance(terminal_at, models.DateTimeField)
    assert terminal_at.null is True
    assert terminal_at.blank is True
    assert terminal_at.auto_now_add is False
    assert terminal_at.auto_now is False
    assert terminal_at.default is NOT_PROVIDED

    failure_detail = AlertDelivery._meta.get_field("failure_detail")
    assert isinstance(failure_detail, models.TextField)
    assert failure_detail.null is True
    assert failure_detail.blank is True
    assert failure_detail.default is NOT_PROVIDED


def test_declared_constraint_names_are_exact():
    """The four state-integrity constraints exist under their frozen names."""
    from alerts.models import AlertDelivery

    names = {constraint.name for constraint in AlertDelivery._meta.constraints}
    for expected in EXPECTED_CONSTRAINT_NAMES:
        assert expected in names


# --- Claim creation --------------------------------------------------------


def test_a_new_claim_is_storable_as_pending(deal_flag):
    """A pending row is the durable claim written before any network I/O."""
    claimed_at = timezone.now()
    delivery = claim(deal_flag, claimed_at=claimed_at)
    delivery.refresh_from_db()

    assert delivery.status == "pending"
    assert delivery.claimed_at == claimed_at
    assert delivery.terminal_at is None
    assert delivery.failure_detail is None
    assert delivery.deal_flag_id == deal_flag.pk


@pytest.mark.parametrize(
    "status,failure_detail",
    [("sent", None), ("failed", SANITIZED_FAILURE_DETAIL)],
)
def test_direct_creation_in_a_terminal_state_is_rejected(
    deal_flag,
    status,
    failure_detail,
):
    """A claim is always created pending; terminal states are only ever reached by transition."""
    from alerts.models import AlertDelivery

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            AlertDelivery.objects.create(
                deal_flag=deal_flag,
                status=status,
                claimed_at=timezone.now(),
                terminal_at=timezone.now(),
                failure_detail=failure_detail,
            )


# --- One claim per DealFlag ------------------------------------------------


def test_second_alert_delivery_for_the_same_deal_flag_is_rejected(deal_flag):
    """The database, not application code, enforces one claim per DealFlag."""
    claim(deal_flag)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            claim(deal_flag)


def test_a_sent_claim_still_blocks_a_second_claim(deal_flag):
    """A DealFlag driven to sent is not claimable again."""
    drive_to_sent(claim(deal_flag))

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            claim(deal_flag)


def test_a_failed_claim_still_blocks_a_second_claim(deal_flag):
    """A failed claim is not retried: it permanently blocks a new claim (Decision H)."""
    drive_to_failed(claim(deal_flag))

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            claim(deal_flag)


def test_distinct_deal_flags_each_get_their_own_claim(deal_flag_factory):
    """The uniqueness rule is per DealFlag, not global."""
    from alerts.models import AlertDelivery

    claim(deal_flag_factory())
    claim(deal_flag_factory())

    assert AlertDelivery.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_concurrent_claims_yield_exactly_one_durable_winner(deal_flag_factory):
    """Two racing processes cannot both own a durable claim.

    TASK_030 proves the database property. TASK_032 later proves it results in
    exactly one external adapter invocation.
    """
    from django.db import close_old_connections

    from alerts.models import AlertDelivery

    deal_flag = deal_flag_factory()
    start = threading.Barrier(2)
    winners = []
    conflicts = []

    def attempt():
        close_old_connections()
        try:
            start.wait(timeout=5)
            with transaction.atomic():
                delivery = claim(deal_flag)
            winners.append(delivery.pk)
        except IntegrityError as error:
            conflicts.append(error)
        finally:
            close_old_connections()

    workers = [threading.Thread(target=attempt) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive()

    assert len(winners) == 1
    assert len(conflicts) == 1
    assert AlertDelivery.objects.filter(deal_flag=deal_flag).count() == 1


# --- Claim identity is immutable -------------------------------------------


def test_deal_flag_cannot_be_reassigned_via_queryset_update(deal_flag_factory):
    """Moving a claim would leave its original DealFlag row-free and alert-eligible again."""
    from alerts.models import AlertDelivery

    original = deal_flag_factory()
    other = deal_flag_factory()
    delivery = claim(original)

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            AlertDelivery.objects.filter(pk=delivery.pk).update(deal_flag=other)

    delivery.refresh_from_db()
    assert delivery.deal_flag_id == original.pk


def test_deal_flag_cannot_be_reassigned_via_raw_sql(deal_flag_factory):
    """The identity guarantee is in the database, not in model validation."""
    original = deal_flag_factory()
    other = deal_flag_factory()
    delivery = claim(original)

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE alerts_alertdelivery SET deal_flag_id = %s WHERE id = %s",
                    [other.pk, delivery.pk],
                )


def test_claimed_at_cannot_be_rewritten(deal_flag):
    """The claim timestamp is evidence of when the claim was taken."""
    from alerts.models import AlertDelivery

    delivery = claim(deal_flag)

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            AlertDelivery.objects.filter(pk=delivery.pk).update(
                claimed_at=timezone.now() + timedelta(hours=1),
            )


# --- One-way lifecycle -----------------------------------------------------


def test_pending_claim_can_transition_to_sent(deal_flag):
    """The approved pending -> sent transition must persist."""
    delivery = drive_to_sent(claim(deal_flag))
    delivery.refresh_from_db()

    assert delivery.status == "sent"
    assert delivery.terminal_at is not None
    assert delivery.failure_detail is None


def test_pending_claim_can_transition_to_failed_with_sanitized_detail(deal_flag):
    """The approved pending -> failed transition persists sanitized, application-owned detail."""
    delivery = drive_to_failed(claim(deal_flag))
    delivery.refresh_from_db()

    assert delivery.status == "failed"
    assert delivery.terminal_at is not None
    assert delivery.failure_detail == SANITIZED_FAILURE_DETAIL


@pytest.mark.parametrize("new_status", ["pending", "failed"])
def test_sent_cannot_transition_to_another_state(deal_flag, new_status):
    """Terminal history is stable once recorded."""
    from alerts.models import AlertDelivery

    delivery = drive_to_sent(claim(deal_flag))

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            AlertDelivery.objects.filter(pk=delivery.pk).update(status=new_status)


@pytest.mark.parametrize("new_status", ["pending", "sent"])
def test_failed_cannot_transition_to_another_state(deal_flag, new_status):
    """A failed claim is never revived, in either direction."""
    from alerts.models import AlertDelivery

    delivery = drive_to_failed(claim(deal_flag))

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            AlertDelivery.objects.filter(pk=delivery.pk).update(status=new_status)


def test_terminal_evidence_cannot_be_rewritten_within_the_same_status(deal_flag):
    """Rewriting terminal_at on an already-terminal row is not an approved transition."""
    from alerts.models import AlertDelivery

    delivery = drive_to_sent(claim(deal_flag))

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            AlertDelivery.objects.filter(pk=delivery.pk).update(
                terminal_at=timezone.now() + timedelta(minutes=5),
            )


def test_failure_detail_cannot_be_rewritten_on_a_failed_row(deal_flag):
    """Recorded failure evidence is stable."""
    from alerts.models import AlertDelivery

    delivery = drive_to_failed(claim(deal_flag))

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            AlertDelivery.objects.filter(pk=delivery.pk).update(
                failure_detail="rewritten",
            )


# --- Deletion --------------------------------------------------------------


def test_queryset_delete_is_rejected(deal_flag):
    """Deleting the durable claim would reopen the DealFlag for a duplicate send."""
    from alerts.models import AlertDelivery

    delivery = claim(deal_flag)

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            AlertDelivery.objects.filter(pk=delivery.pk).delete()


def test_raw_sql_delete_is_rejected(deal_flag):
    """The deletion guarantee is in the database, not only in the ORM."""
    delivery = claim(deal_flag)

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM alerts_alertdelivery WHERE id = %s",
                    [delivery.pk],
                )


def test_model_delete_raises_a_readable_error(deal_flag):
    """An ORM caller gets a clear message rather than a raw database error."""
    from django.core.exceptions import ValidationError

    delivery = claim(deal_flag)

    with pytest.raises(ValidationError):
        delivery.delete()


@pytest.mark.parametrize("driver", [drive_to_sent, drive_to_failed])
def test_a_terminal_claim_cannot_be_deleted_either(deal_flag, driver):
    """The prohibition applies at every status, not only pending."""
    from alerts.models import AlertDelivery

    delivery = driver(claim(deal_flag))

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            AlertDelivery.objects.filter(pk=delivery.pk).delete()


def test_deleting_a_claim_cannot_reopen_its_deal_flag(deal_flag):
    """The acceptance fact: after any deletion attempt the DealFlag still has its claim."""
    from alerts.models import AlertDelivery

    claim(deal_flag)

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            AlertDelivery.objects.filter(deal_flag=deal_flag).delete()

    assert AlertDelivery.objects.filter(deal_flag=deal_flag).count() == 1


# --- Declarative state integrity -------------------------------------------


@pytest.mark.parametrize("bad_status", ["queued", "delivered", "unknown", ""])
def test_status_outside_the_vocabulary_is_rejected(deal_flag, bad_status):
    """Only pending, sent, and failed are persistable."""
    from alerts.models import AlertDelivery

    with pytest.raises((IntegrityError, ProgrammingError)):
        with transaction.atomic():
            AlertDelivery.objects.create(
                deal_flag=deal_flag,
                status=bad_status,
                claimed_at=timezone.now(),
                terminal_at=None,
                failure_detail=None,
            )


def test_pending_row_with_a_terminal_timestamp_is_rejected(deal_flag):
    """A pending claim has not reached a terminal state, so it cannot carry terminal_at."""
    from alerts.models import AlertDelivery

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AlertDelivery.objects.create(
                deal_flag=deal_flag,
                status="pending",
                claimed_at=timezone.now(),
                terminal_at=timezone.now(),
                failure_detail=None,
            )


def test_transition_to_a_terminal_state_without_a_timestamp_is_rejected(deal_flag):
    """A terminal row records when it became terminal."""
    from alerts.models import AlertDelivery

    delivery = claim(deal_flag)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AlertDelivery.objects.filter(pk=delivery.pk).update(status="sent")


@pytest.mark.parametrize("failure_detail", ["", SANITIZED_FAILURE_DETAIL])
def test_pending_row_carrying_failure_detail_is_rejected(deal_flag, failure_detail):
    """Failure text belongs only to a failed row - the empty string is not a loophole."""
    from alerts.models import AlertDelivery

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AlertDelivery.objects.create(
                deal_flag=deal_flag,
                status="pending",
                claimed_at=timezone.now(),
                terminal_at=None,
                failure_detail=failure_detail,
            )


@pytest.mark.parametrize("failure_detail", ["", SANITIZED_FAILURE_DETAIL])
def test_sent_row_carrying_failure_detail_is_rejected(deal_flag, failure_detail):
    """A successful send has nothing to explain, and an empty string is still not NULL."""
    from alerts.models import AlertDelivery

    delivery = claim(deal_flag)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AlertDelivery.objects.filter(pk=delivery.pk).update(
                status="sent",
                terminal_at=timezone.now(),
                failure_detail=failure_detail,
            )


@pytest.mark.parametrize("failure_detail", [None, ""])
def test_failed_row_without_failure_detail_is_rejected(deal_flag, failure_detail):
    """A failed row must say why, or it is not diagnosable."""
    from alerts.models import AlertDelivery

    delivery = claim(deal_flag)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AlertDelivery.objects.filter(pk=delivery.pk).update(
                status="failed",
                terminal_at=timezone.now(),
                failure_detail=failure_detail,
            )


# --- Timestamp chronology --------------------------------------------------


def test_terminal_at_equal_to_claimed_at_is_valid(deal_flag):
    """A claim and its terminal record can land within the same clock tick."""
    from alerts.models import AlertDelivery

    claimed_at = timezone.now()
    delivery = claim(deal_flag, claimed_at=claimed_at)

    updated = AlertDelivery.objects.filter(pk=delivery.pk).update(
        status="sent",
        terminal_at=claimed_at,
    )
    assert updated == 1


def test_terminal_at_after_claimed_at_is_valid(deal_flag):
    """The ordinary case."""
    from alerts.models import AlertDelivery

    claimed_at = timezone.now()
    delivery = claim(deal_flag, claimed_at=claimed_at)

    updated = AlertDelivery.objects.filter(pk=delivery.pk).update(
        status="sent",
        terminal_at=claimed_at + timedelta(seconds=1),
    )
    assert updated == 1


def test_terminal_at_before_claimed_at_is_rejected(deal_flag):
    """A terminal event cannot predate the claim it terminates."""
    from alerts.models import AlertDelivery

    claimed_at = timezone.now()
    delivery = claim(deal_flag, claimed_at=claimed_at)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AlertDelivery.objects.filter(pk=delivery.pk).update(
                status="sent",
                terminal_at=claimed_at - timedelta(seconds=1),
            )


# --- Frozen scope ----------------------------------------------------------


def test_no_retry_recipient_or_channel_fields_exist():
    """v1 is one claim per DealFlag: no retry history, recipients, channels, or metadata."""
    from alerts.models import AlertDelivery

    field_names = {field.name for field in AlertDelivery._meta.get_fields()}
    for forbidden in FORBIDDEN_FIELD_NAMES:
        assert forbidden not in field_names


def test_alerts_app_declares_exactly_one_model():
    """No AlertAttempt, no recipient model, no channel registry."""
    from django.apps import apps

    models_in_app = apps.get_app_config("alerts").get_models()
    assert [model.__name__ for model in models_in_app] == ["AlertDelivery"]


def test_existing_dealflag_and_outcome_relationships_remain_intact(deal_flag):
    """TASK_030 adds a relationship; it changes none of the committed ones."""
    from django.core.exceptions import ValidationError

    from outcomes.models import Outcome
    from pricing.models import DealFlag

    outcome_field = Outcome._meta.get_field("deal_flag")
    assert isinstance(outcome_field, models.OneToOneField)
    assert outcome_field.remote_field.on_delete is PROTECT
    assert outcome_field.remote_field.related_name == "outcome"

    listing_field = DealFlag._meta.get_field("listing")
    assert isinstance(listing_field, models.ForeignKey)
    assert not isinstance(listing_field, models.OneToOneField)

    # DealFlag immutability is untouched by this task.
    deal_flag.reason = "changed"
    with pytest.raises(ValidationError, match="immutable"):
        deal_flag.save()
