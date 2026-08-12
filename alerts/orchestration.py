"""Alert send orchestration: eligibility, claiming, sending, terminal record.

TASK_032 combines TASK_030's durable claim with TASK_031's payload and
transport into the one operation Phase 7 exists to produce. It owns
orchestration only — no schema, no payload construction, no transport detail.
See tasks/TASK_032_ALERT_SEND_ORCHESTRATION_AND_COMMAND.md Sections 5-9.

The ordering in send_pending_deal_alerts() is the correctness core: the claim
is committed *before* the network call and no transaction is held open across
it (specification Section 6).
"""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from alerts.config import alerts_enabled, load_alert_config
# build_alert_message and send_telegram_message are bound at module level on
# purpose: they are the frozen testability seams (specification Section 4),
# patchable as alerts.orchestration.<name> exactly as alerts.telegram.urlopen
# is. Both are resolved as module globals at call time, so patching works.
from alerts.delivery import (
    AlertDeliveryError,
    AlertPayloadError,
    AlertSender,
    build_alert_message,
)
from alerts.models import AlertDelivery
from alerts.telegram import send_telegram_message
from pricing.models import DealFlag


@dataclass(frozen=True, slots=True)
class AlertRunSummary:
    candidates: int
    sent: int
    failed: int


def send_pending_deal_alerts(*, sender: AlertSender | None = None) -> AlertRunSummary:
    """Claim, send, and record every eligible DealFlag exactly once.

    `sender` follows the AuditWriter injection precedent
    (outcomes/outcome_services.py): a plain callable with a real default, no
    registry and no factory.
    """
    # Step 1: disabled short-circuits before any query, claim, or send —
    # disabled alerts must not even require credentials to be configured.
    if not alerts_enabled():
        return AlertRunSummary(candidates=0, sent=0, failed=0)

    # Step 2: AlertConfigurationError propagates; the command turns it into a
    # CommandError. This happens before any claim exists.
    config = load_alert_config()

    # Resolved here rather than in the signature so the module-level seam stays
    # patchable after import.
    send = send_telegram_message if sender is None else sender

    # Step 3: eligibility is the *absence* of an AlertDelivery row (pending,
    # sent and failed all exclude permanently) plus an inclusive activation
    # cutoff. select_related covers listing and listing__sku only: the alert
    # path must never touch RawListing or Source. Processing order is
    # deliberately unspecified (specification Section 5).
    candidates = list(
        DealFlag.objects.filter(
            alert_delivery__isnull=True,
            flagged_at__gte=config.activation_at,
        ).select_related("listing", "listing__sku")
    )

    sent = 0
    failed = 0

    for deal_flag in candidates:
        # Step 4: payload preflight precedes the claim. TASK_030 forbids retry
        # and resend, so a claim burned on an unsendable message would be
        # unrecoverable — skip the candidate entirely and keep going.
        try:
            message = build_alert_message(deal_flag, config)
        except AlertPayloadError:
            continue

        # Steps 5-6: the claim insert is attempted, not pre-checked. The
        # authoritative conflict boundary is TASK_030's OneToOne UNIQUE index,
        # and the atomic() block is required for savepoint safety — a bare
        # IntegrityError catch would leave the surrounding transaction
        # unusable. The block exits (commits) before the send below.
        try:
            with transaction.atomic():
                delivery = AlertDelivery.objects.create(
                    deal_flag=deal_flag,
                    status="pending",
                    claimed_at=timezone.now(),
                    terminal_at=None,
                    failure_detail=None,
                )
        except IntegrityError:
            # The unique index on deal_flag_id is the only conflict boundary
            # this insert can violate under normal operation — status,
            # claimed_at, terminal_at and failure_detail are literal values
            # above that always satisfy every CheckConstraint, and the
            # PROTECT/immutability triggers on DealFlag mean deal_flag_id can
            # never dangle. So an unrelated IntegrityError should not be
            # possible here — but if the database ever proves otherwise, it is
            # a genuine defect, not a lost race, and must surface rather than
            # being silently swallowed. Confirm a competing claim actually won
            # before treating this as the expected conflict: PostgreSQL's
            # unique index is not deferrable, so a UniqueViolation can only
            # fire after the winner's row has already committed, and Read
            # Committed guarantees this query sees it.
            if not AlertDelivery.objects.filter(deal_flag=deal_flag).exists():
                raise
            # Losing the race is normal operation, not a delivery failure: the
            # winner sends, so this worker counts neither sent nor failed.
            continue

        # Step 7: the send happens outside every transaction this function
        # opened. Only AlertDeliveryError — TASK_031's sanitized contract —
        # becomes `failed`; anything else is a genuine defect and propagates
        # unchanged, leaving the claim pending (specification Section 9).
        try:
            send(config, message)
        except AlertDeliveryError as error:
            # Step 9: str(error) is one of TASK_031's four frozen sanitized
            # messages, never raw transport text.
            delivery.status = "failed"
            delivery.terminal_at = timezone.now()
            delivery.failure_detail = str(error)
            # update_fields keeps deal_flag_id and claimed_at out of the
            # UPDATE entirely, which is what TASK_030's trigger permits.
            delivery.save(update_fields=["status", "terminal_at", "failure_detail"])
            failed += 1
            continue

        # Step 8: success leaves failure_detail NULL, as TASK_030's
        # alertdelivery_failure_detail_matches_status constraint requires.
        delivery.status = "sent"
        delivery.terminal_at = timezone.now()
        delivery.save(update_fields=["status", "terminal_at"])
        sent += 1

    return AlertRunSummary(candidates=len(candidates), sent=sent, failed=failed)
