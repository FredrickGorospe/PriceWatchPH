"""Frozen TASK_032 alert send orchestration and management-command tests.

TASK_032 combines the TASK_030 durable claim with the TASK_031 payload and
transport. It owns eligibility, claiming, concurrency, transaction boundaries,
terminal transitions, and the scheduler-facing command. It re-uses TASK_030 and
TASK_031 exactly and reimplements neither. See
tasks/TASK_032_ALERT_SEND_ORCHESTRATION_AND_COMMAND.md and docs/07_PLANNING.md.

No test performs a real Telegram request: the sender is always injected, or
patched at the frozen alerts.orchestration.send_telegram_message seam.

Imports of alerts.orchestration are deliberately performed inside each test so
this module still collects cleanly before that module exists.
"""

import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone as django_timezone


# Obviously synthetic, inert values. Nothing here is a real credential.
FAKE_BOT_TOKEN = "1234567890:SYNTHETIC-TASK032-TOKEN-DO-NOT-USE"
FAKE_CHAT_ID = "-1009876543210"
FAKE_BASE_URL = "https://pricewatch.example.test"

# Manila noon == 04:00Z. Every DealFlag below is positioned relative to this.
ACTIVATION_AT_SETTING = "2026-06-15T12:00:00+08:00"
ACTIVATION_INSTANT = datetime(2026, 6, 15, 4, 0, tzinfo=timezone.utc)

DISABLED_LINE = "Alerts disabled: no deal flags were considered."
FAILURE_EXIT_MESSAGE = "Alert delivery completed with failures."

# Values that must never reach command output or persisted failure detail.
SECRET_RAW_TITLE = "TASK032 RAW TITLE MUST NOT LEAK"
SECRET_RAW_PRICE_TEXT = "TASK032-RAW-PRICE-TEXT"
SECRET_SELLER = "task032-seller-must-not-leak"
SECRET_SOURCE_URL = "https://external-marketplace.invalid/task032-listing"


def summary_line(candidates, sent, failed):
    return f"Alerts complete: candidates={candidates} sent={sent} failed={failed}"


def enabled_alert_settings(**overrides):
    values = {
        "ENABLE_ALERTS": True,
        "TELEGRAM_BOT_TOKEN": FAKE_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": FAKE_CHAT_ID,
        "ALERT_ACTIVATION_AT": ACTIVATION_AT_SETTING,
        "PUBLIC_BASE_URL": FAKE_BASE_URL,
    }
    values.update(overrides)
    return values


class RecordingSender:
    """An injected AlertSender that records calls and never touches a network."""

    def __init__(self, error_for=None, side_effect=None, on_call=None):
        self.calls = []
        self._error_for = error_for or {}
        self._side_effect = side_effect
        self._on_call = on_call

    def __call__(self, config, text):
        self.calls.append((config, text))
        if self._on_call is not None:
            self._on_call(config, text)
        if self._side_effect is not None:
            raise self._side_effect
        error = self._error_for.get(len(self.calls))
        if error is not None:
            raise error
        return None


@pytest.fixture
def deal_flag_factory(db):
    """Build real DealFlags through the full committed chain.

    The upstream RawListing deliberately carries values that must never appear
    in command output or persisted failure detail.
    """
    from catalogue.models import Sku
    from ingestion.models import RawListing
    from listings.models import Listing
    from pricing.models import DealFlag, PricePoint
    from sources.models import Source

    sku = Sku.objects.create(
        brand="ASUS",
        model="TUF Gaming RTX 4070",
        variant="OC",
        category="gpu",
        launch_msrp=Decimal("34995.00"),
        launch_date=date(2026, 1, 1),
    )
    source = Source.objects.create(
        name="task_032_source",
        base_url="https://example.invalid",
        terms_notes="Synthetic TASK_032 fixture",
        rate_limit=None,
    )
    pricepoint = PricePoint.objects.create(
        sku=sku,
        condition="used",
        day=date(2026, 6, 15),
        median=Decimal("18000.0000"),
        p25=Decimal("17000.0000"),
        p75=Decimal("19000.0000"),
        n_listings=10,
    )

    def make(flagged_at=None, price=Decimal("12500.00")):
        raw_listing = RawListing.objects.create(
            source=source,
            raw_title=SECRET_RAW_TITLE,
            raw_price_text=SECRET_RAW_PRICE_TEXT,
            raw_price=price,
            url=SECRET_SOURCE_URL,
            seller=SECRET_SELLER,
            fetched_at=django_timezone.now(),
            external_id=None,
        )
        listing = Listing.objects.create(
            raw_listing=raw_listing,
            sku=sku,
            price=price,
            condition="used",
            location="Quezon City",
            resolution_confidence=Decimal("1.0000"),
            resolution_method="exact_alias",
            resolved_at=django_timezone.now(),
        )
        return DealFlag.objects.create(
            listing=listing,
            score=Decimal("-3.5000"),
            baseline_pricepoint=pricepoint,
            reason="asking_price_mad_v1",
            flagged_at=flagged_at or (ACTIVATION_INSTANT + timedelta(hours=1)),
        )

    return make


@pytest.fixture
def eligible_deal_flag(deal_flag_factory):
    return deal_flag_factory()


def claim(deal_flag, status="pending", failure_detail=None):
    """Create an AlertDelivery directly, through the approved lifecycle only."""
    from alerts.models import AlertDelivery

    delivery = AlertDelivery.objects.create(
        deal_flag=deal_flag,
        status="pending",
        claimed_at=django_timezone.now(),
        terminal_at=None,
        failure_detail=None,
    )
    if status != "pending":
        delivery.status = status
        delivery.terminal_at = django_timezone.now()
        delivery.failure_detail = failure_detail
        delivery.save()
    return delivery


def run(sender):
    """Run the orchestration with an injected sender."""
    from alerts.orchestration import send_pending_deal_alerts

    return send_pending_deal_alerts(sender=sender)


# ---------------------------------------------------------------------------
# Alerts disabled
# ---------------------------------------------------------------------------


def test_disabled_command_prints_the_exact_no_op_line_and_exits_zero(db):
    """A visible successful no-op: a silent exit is indistinguishable from a cron
    entry that never fired."""
    stdout = StringIO()
    with override_settings(**enabled_alert_settings(ENABLE_ALERTS=False)):
        call_command("send_deal_alerts", stdout=stdout)

    assert stdout.getvalue().strip() == DISABLED_LINE


def test_disabled_command_creates_no_claim_and_calls_no_sender(db, eligible_deal_flag):
    from alerts.models import AlertDelivery

    sender = RecordingSender()
    with override_settings(**enabled_alert_settings(ENABLE_ALERTS=False)):
        run(sender)

    assert sender.calls == []
    assert AlertDelivery.objects.count() == 0


def test_disabled_run_performs_no_eligibility_query(db, eligible_deal_flag):
    """Short-circuit before any work: disabled means no DealFlag is even considered."""
    sender = RecordingSender()
    with override_settings(**enabled_alert_settings(ENABLE_ALERTS=False)):
        with CaptureQueriesContext(connection) as queries:
            run(sender)

    executed_sql = "\n".join(query["sql"].lower() for query in queries)
    assert "pricing_dealflag" not in executed_sql
    assert "alerts_alertdelivery" not in executed_sql


def test_disabled_run_tolerates_entirely_absent_alert_configuration(db):
    """Disabled alerts must not require credentials to be configured."""
    sender = RecordingSender()
    with override_settings(
        ENABLE_ALERTS=False,
        TELEGRAM_BOT_TOKEN="",
        TELEGRAM_CHAT_ID="",
        ALERT_ACTIVATION_AT="",
        PUBLIC_BASE_URL="",
    ):
        summary = run(sender)

    assert (summary.candidates, summary.sent, summary.failed) == (0, 0, 0)


# ---------------------------------------------------------------------------
# Configuration failure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "broken",
    ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ALERT_ACTIVATION_AT", "PUBLIC_BASE_URL"],
)
def test_invalid_configuration_raises_command_error(db, eligible_deal_flag, broken):
    """Configuration failure is loud and happens before any claim exists.

    The "Unknown command" guard matters: without it this test passes vacuously
    while the command does not exist yet, which would make it a false green
    rather than a real acceptance criterion.
    """
    from alerts.models import AlertDelivery

    with override_settings(**enabled_alert_settings(**{broken: ""})):
        with pytest.raises(CommandError) as raised:
            call_command("send_deal_alerts", stdout=StringIO())

    assert "Unknown command" not in str(raised.value)
    assert AlertDelivery.objects.count() == 0


def test_invalid_configuration_consumes_no_claim_and_calls_no_sender(db, eligible_deal_flag):
    """A misconfigured run must not burn the DealFlag's one and only claim."""
    from alerts.config import AlertConfigurationError
    from alerts.models import AlertDelivery

    sender = RecordingSender()
    with override_settings(**enabled_alert_settings(ALERT_ACTIVATION_AT="not-a-timestamp")):
        with pytest.raises((AlertConfigurationError, CommandError)):
            run(sender)

    assert sender.calls == []
    assert AlertDelivery.objects.count() == 0


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def test_deal_flag_after_the_cutoff_is_a_candidate(db, deal_flag_factory):
    deal_flag_factory(flagged_at=ACTIVATION_INSTANT + timedelta(seconds=1))
    sender = RecordingSender()

    with override_settings(**enabled_alert_settings()):
        summary = run(sender)

    assert summary.candidates == 1
    assert len(sender.calls) == 1


def test_deal_flag_exactly_at_the_cutoff_is_a_candidate(db, deal_flag_factory):
    """The boundary is inclusive: flagged_at >= activation, not >."""
    deal_flag_factory(flagged_at=ACTIVATION_INSTANT)
    sender = RecordingSender()

    with override_settings(**enabled_alert_settings()):
        summary = run(sender)

    assert summary.candidates == 1
    assert len(sender.calls) == 1


def test_deal_flag_before_the_cutoff_is_excluded(db, deal_flag_factory):
    """No backfilling of the historical DealFlag backlog."""
    from alerts.models import AlertDelivery

    deal_flag_factory(flagged_at=ACTIVATION_INSTANT - timedelta(seconds=1))
    sender = RecordingSender()

    with override_settings(**enabled_alert_settings()):
        summary = run(sender)

    assert summary.candidates == 0
    assert sender.calls == []
    assert AlertDelivery.objects.count() == 0


def test_cutoff_comparison_is_timezone_aware_across_the_manila_offset(db, deal_flag_factory):
    """The configured Manila wall clock is compared as an absolute instant.

    A flag one second before 04:00Z is excluded even though it is on the same
    Manila calendar day as the configured noon cutoff.
    """
    deal_flag_factory(flagged_at=datetime(2026, 6, 15, 3, 59, 59, tzinfo=timezone.utc))
    sender = RecordingSender()

    with override_settings(**enabled_alert_settings()):
        summary = run(sender)

    assert summary.candidates == 0


@pytest.mark.parametrize("existing_status", ["pending", "sent", "failed"])
def test_any_existing_claim_excludes_the_deal_flag_permanently(
    db,
    eligible_deal_flag,
    existing_status,
):
    """Eligibility is the absence of a row, not the absence of a successful one."""
    from alerts.models import AlertDelivery

    detail = "Telegram rejected the message." if existing_status == "failed" else None
    existing = claim(eligible_deal_flag, status=existing_status, failure_detail=detail)
    sender = RecordingSender()

    with override_settings(**enabled_alert_settings()):
        summary = run(sender)

    assert summary.candidates == 0
    assert sender.calls == []
    assert AlertDelivery.objects.count() == 1

    existing.refresh_from_db()
    assert existing.status == existing_status


def test_every_candidate_is_processed_exactly_once_regardless_of_order(db, deal_flag_factory):
    """No processing order is frozen: docs/07_PLANNING.md requires none, and
    repository precedent alone is not authority to invent one. What is frozen is
    that each candidate is handled exactly once."""
    flags = [deal_flag_factory() for _ in range(3)]
    sender = RecordingSender()

    with override_settings(**enabled_alert_settings()):
        run(sender)

    sent_links = sorted(text.splitlines()[-1] for _config, text in sender.calls)
    assert sent_links == sorted(
        f"{FAKE_BASE_URL}/deals/{flag.pk}/outcome" for flag in flags
    )


def test_no_per_run_cap_exists(db, deal_flag_factory):
    """Decision D: every candidate in a run is processed."""
    for _ in range(12):
        deal_flag_factory()
    sender = RecordingSender()

    with override_settings(**enabled_alert_settings()):
        summary = run(sender)

    assert summary.candidates == 12
    assert summary.sent == 12
    assert len(sender.calls) == 12


def test_orchestration_never_queries_rawlisting_or_source(db, eligible_deal_flag):
    """Privacy at the query boundary, matching TASK_031's payload guarantee."""
    sender = RecordingSender()

    with override_settings(**enabled_alert_settings()):
        with CaptureQueriesContext(connection) as queries:
            run(sender)

    executed_sql = "\n".join(query["sql"].lower() for query in queries)
    assert "ingestion_rawlisting" not in executed_sql
    assert "sources_source" not in executed_sql


# ---------------------------------------------------------------------------
# Payload preflight — before the claim
# ---------------------------------------------------------------------------


def test_payload_error_leaves_the_deal_flag_unclaimed(db, eligible_deal_flag):
    """TASK_030 forbids retry and resend, so a claim burned on an unsendable
    message would be unrecoverable. The payload is validated first."""
    from alerts.models import AlertDelivery

    # A structurally valid but pathologically long base URL pushes the rendered
    # message past Telegram's 4096-character limit.
    long_base = "https://" + "a" * 4200
    sender = RecordingSender()

    with override_settings(**enabled_alert_settings(PUBLIC_BASE_URL=long_base)):
        summary = run(sender)

    assert sender.calls == []
    assert AlertDelivery.objects.count() == 0
    assert summary.sent == 0
    assert summary.failed == 0


def test_payload_error_does_not_abort_the_remaining_candidates(db, deal_flag_factory):
    """One unsendable candidate must not stop the run.

    Payload construction is made to fail for exactly one specific candidate and
    to succeed for the other, and every attempt is recorded. That proves the run
    genuinely continues past the AlertPayloadError, rather than merely showing
    that a run in which *every* payload fails claims nothing - and it holds under
    any processing order, which Section 5 deliberately does not freeze.
    """
    from unittest import mock

    from alerts.delivery import AlertPayloadError, build_alert_message as real_build
    from alerts.models import AlertDelivery

    failing_flag = deal_flag_factory()
    valid_flag = deal_flag_factory()
    attempted = []

    def build(deal_flag, config):
        attempted.append(deal_flag.pk)
        if deal_flag.pk == failing_flag.pk:
            # TASK_031's real contract and its exact frozen message.
            raise AlertPayloadError(
                "Alert message exceeds Telegram's 4096-character limit."
            )
        return real_build(deal_flag, config)

    sender = RecordingSender()
    with override_settings(**enabled_alert_settings()):
        with mock.patch("alerts.orchestration.build_alert_message", side_effect=build):
            summary = run(sender)

    # Both candidates were attempted: the run did not abort at the failure.
    assert sorted(attempted) == sorted([failing_flag.pk, valid_flag.pk])

    assert (summary.candidates, summary.sent, summary.failed) == (2, 1, 0)

    # The unsendable candidate is completely unconsumed and was never sent.
    assert not AlertDelivery.objects.filter(deal_flag=failing_flag).exists()

    # The valid candidate was claimed and sent.
    delivered = AlertDelivery.objects.get(deal_flag=valid_flag)
    assert delivered.status == "sent"
    assert len(sender.calls) == 1
    assert sender.calls[0][1].endswith(f"{FAKE_BASE_URL}/deals/{valid_flag.pk}/outcome")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_successful_send_creates_one_claim_and_transitions_it_to_sent(db, eligible_deal_flag):
    from alerts.models import AlertDelivery

    sender = RecordingSender()
    with override_settings(**enabled_alert_settings()):
        summary = run(sender)

    assert (summary.candidates, summary.sent, summary.failed) == (1, 1, 0)

    delivery = AlertDelivery.objects.get(deal_flag=eligible_deal_flag)
    assert delivery.status == "sent"
    assert delivery.terminal_at is not None
    assert delivery.failure_detail is None
    assert delivery.claimed_at <= delivery.terminal_at
    assert AlertDelivery.objects.count() == 1


def test_sender_is_called_once_with_the_config_and_the_frozen_payload(db, eligible_deal_flag):
    """TASK_032 orchestrates TASK_031; it does not rebuild the message."""
    from alerts.config import load_alert_config
    from alerts.delivery import build_alert_message

    sender = RecordingSender()
    with override_settings(**enabled_alert_settings()):
        expected_config = load_alert_config()
        expected_message = build_alert_message(eligible_deal_flag, expected_config)
        run(sender)

    assert len(sender.calls) == 1
    used_config, used_text = sender.calls[0]
    assert used_config == expected_config
    assert used_text == expected_message


def test_default_sender_is_the_task_031_telegram_adapter(db, eligible_deal_flag):
    """The real default is TASK_031's transport, patchable at the frozen seam."""
    from unittest import mock

    with override_settings(**enabled_alert_settings()):
        with mock.patch("alerts.orchestration.send_telegram_message") as default_sender:
            default_sender.return_value = None
            from alerts.orchestration import send_pending_deal_alerts

            send_pending_deal_alerts()

    assert default_sender.call_count == 1


# ---------------------------------------------------------------------------
# Transaction boundary — claim committed before the send
# ---------------------------------------------------------------------------


def read_claim_from_another_connection(deal_flag_id):
    """Read the claim from a genuinely separate database connection.

    Django gives each thread its own connection, so a row visible here has been
    committed - it is not merely pending inside the caller's open transaction.
    """
    from alerts.models import AlertDelivery

    observed = {}

    def worker():
        close_old_connections()
        try:
            observed["row"] = (
                AlertDelivery.objects.filter(deal_flag_id=deal_flag_id)
                .values("status", "terminal_at")
                .first()
            )
        finally:
            close_old_connections()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive()
    return observed.get("row")


@pytest.mark.django_db(transaction=True)
def test_claim_is_committed_and_visible_elsewhere_before_the_sender_runs(deal_flag_factory):
    """The durable claim must exist before Telegram can receive anything.

    If the orchestrator sent while its claim transaction was still open, the
    separate connection below would see nothing - and two concurrent workers
    could both send.
    """
    deal_flag = deal_flag_factory()
    observed = {}

    def observe(_config, _text):
        observed["row"] = read_claim_from_another_connection(deal_flag.pk)

    sender = RecordingSender(on_call=observe)
    with override_settings(**enabled_alert_settings()):
        run(sender)

    assert observed["row"] is not None, "claim was not committed before the send"
    assert observed["row"]["status"] == "pending"
    assert observed["row"]["terminal_at"] is None


@pytest.mark.django_db(transaction=True)
def test_no_transaction_is_open_while_the_sender_runs(deal_flag_factory):
    """Holding a transaction across a 10-second external call creates contention
    without improving the at-most-once guarantee."""
    deal_flag_factory()
    observed = {}

    def observe(_config, _text):
        observed["in_atomic_block"] = connection.in_atomic_block

    sender = RecordingSender(on_call=observe)
    with override_settings(**enabled_alert_settings()):
        run(sender)

    assert observed["in_atomic_block"] is False


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_workers_race_at_the_claim_insert_and_only_one_sends(
    deal_flag_factory,
    monkeypatch,
):
    """The central at-most-once proof, with the race genuinely forced.

    Synchronising the workers only before the run would let one finish its claim
    before the other even selects candidates - the uniqueness conflict might then
    never execute and this test would pass without proving anything. So the
    barrier sits on the actual INSERT path (`AlertDelivery.save` while
    `_state.adding`), following TASK_021's
    `test_concurrent_qualification_converges_through_database_uniqueness`.
    Neither insert can complete until both workers have arrived, which
    guarantees both selected the same DealFlag as a candidate before the
    conflict resolves. Test-only monkeypatch; no production testing hook.
    """
    from alerts.models import AlertDelivery

    deal_flag = deal_flag_factory()

    insert_barrier = threading.Barrier(2)
    original_save = AlertDelivery.save

    def synchronized_save(self, *args, **kwargs):
        if self._state.adding:
            insert_barrier.wait(timeout=10)
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(AlertDelivery, "save", synchronized_save)

    calls = []
    calls_lock = threading.Lock()
    summaries = []
    errors = []

    def record(_config, text):
        with calls_lock:
            calls.append(text)

    def worker():
        close_old_connections()
        try:
            sender = RecordingSender(on_call=record)
            with override_settings(**enabled_alert_settings()):
                summaries.append(run(sender))
        except Exception as error:  # asserted below
            errors.append(error)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    assert errors == [], f"a worker raised: {errors!r}"
    assert len(summaries) == 2

    # Both workers selected the DealFlag before the conflict resolved.
    assert [summary.candidates for summary in summaries] == [1, 1]

    # The database decided the winner; exactly one claim and one send exist.
    assert AlertDelivery.objects.filter(deal_flag=deal_flag).count() == 1
    assert len(calls) == 1, "the losing worker must not send"

    # Exactly one worker sent; the loser sent nothing and recorded no failure,
    # because losing a race is normal operation, not a delivery failure - it
    # must never make the command exit non-zero.
    assert sorted(summary.sent for summary in summaries) == [0, 1]
    assert [summary.failed for summary in summaries] == [0, 0]

    assert AlertDelivery.objects.get(deal_flag=deal_flag).status == "sent"


# ---------------------------------------------------------------------------
# Sender failure — sanitized, terminal, never retried
# ---------------------------------------------------------------------------


def test_sanitized_delivery_error_transitions_the_claim_to_failed(db, eligible_deal_flag):
    from alerts.delivery import AlertDeliveryError
    from alerts.models import AlertDelivery

    error = AlertDeliveryError("api_rejected")
    sender = RecordingSender(side_effect=error)

    with override_settings(**enabled_alert_settings()):
        summary = run(sender)

    assert (summary.candidates, summary.sent, summary.failed) == (1, 0, 1)

    delivery = AlertDelivery.objects.get(deal_flag=eligible_deal_flag)
    assert delivery.status == "failed"
    assert delivery.terminal_at is not None
    assert delivery.failure_detail == "Telegram rejected the message."
    assert len(sender.calls) == 1


@pytest.mark.parametrize(
    "reason,expected_detail",
    [
        ("timeout", "Telegram request timed out."),
        ("transport_failure", "Telegram request could not be completed."),
        ("invalid_response", "Telegram returned an unreadable response."),
        ("api_rejected", "Telegram rejected the message."),
    ],
)
def test_every_sanitized_reason_persists_its_exact_frozen_message(
    db,
    eligible_deal_flag,
    reason,
    expected_detail,
):
    """failure_detail is exactly TASK_031's sanitized text - never raw transport
    detail, and always non-empty as TASK_030's constraint requires."""
    from alerts.delivery import AlertDeliveryError
    from alerts.models import AlertDelivery

    sender = RecordingSender(side_effect=AlertDeliveryError(reason))
    with override_settings(**enabled_alert_settings()):
        run(sender)

    delivery = AlertDelivery.objects.get(deal_flag=eligible_deal_flag)
    assert delivery.failure_detail == expected_detail


def test_a_failed_send_is_never_retried_within_the_run(db, eligible_deal_flag):
    from alerts.delivery import AlertDeliveryError

    sender = RecordingSender(side_effect=AlertDeliveryError("timeout"))
    with override_settings(**enabled_alert_settings()):
        run(sender)

    assert len(sender.calls) == 1


def test_a_failed_deal_flag_is_skipped_by_a_later_run(db, eligible_deal_flag):
    """Decision H: a failed row causes every future run to skip that DealFlag."""
    from alerts.delivery import AlertDeliveryError
    from alerts.models import AlertDelivery

    failing = RecordingSender(side_effect=AlertDeliveryError("transport_failure"))
    with override_settings(**enabled_alert_settings()):
        run(failing)

    later = RecordingSender()
    with override_settings(**enabled_alert_settings()):
        second_summary = run(later)

    assert second_summary.candidates == 0
    assert later.calls == []
    assert AlertDelivery.objects.count() == 1
    assert AlertDelivery.objects.get().status == "failed"


def test_one_failure_does_not_abort_the_remaining_candidates(db, deal_flag_factory):
    """Each candidate is claimed and recorded independently.

    Order-independent: whichever candidate happens to be second, all three are
    attempted and each gets its own terminal row.
    """
    from alerts.delivery import AlertDeliveryError
    from alerts.models import AlertDelivery

    for _ in range(3):
        deal_flag_factory()

    # Whichever candidate is processed second fails; the other two succeed.
    sender = RecordingSender(error_for={2: AlertDeliveryError("api_rejected")})
    with override_settings(**enabled_alert_settings()):
        summary = run(sender)

    assert (summary.candidates, summary.sent, summary.failed) == (3, 2, 1)
    assert len(sender.calls) == 3
    assert AlertDelivery.objects.count() == 3
    assert AlertDelivery.objects.filter(status="sent").count() == 2
    assert AlertDelivery.objects.filter(status="failed").count() == 1
    assert AlertDelivery.objects.filter(status="pending").count() == 0


# ---------------------------------------------------------------------------
# Unexpected exceptions propagate
# ---------------------------------------------------------------------------


def test_unexpected_exception_propagates_unchanged(db, eligible_deal_flag):
    """Only TASK_031's sanitized contract becomes `failed`. Anything else is a
    genuine defect and must surface rather than be recorded as a delivery
    failure."""
    sender = RecordingSender(side_effect=RuntimeError("unexpected defect"))

    with override_settings(**enabled_alert_settings()):
        with pytest.raises(RuntimeError, match="unexpected defect"):
            run(sender)


def test_unexpected_post_claim_exception_leaves_the_claim_pending(db, eligible_deal_flag):
    """The accepted consequence of the frozen at-most-once design: a stuck
    pending row is the diagnosable signature of a crash between claim and
    terminal record. TASK_032 must not repair it."""
    from alerts.models import AlertDelivery

    sender = RecordingSender(side_effect=RuntimeError("unexpected defect"))
    with override_settings(**enabled_alert_settings()):
        with pytest.raises(RuntimeError):
            run(sender)

    delivery = AlertDelivery.objects.get(deal_flag=eligible_deal_flag)
    assert delivery.status == "pending"
    assert delivery.terminal_at is None
    assert delivery.failure_detail is None


def test_unexpected_exception_is_never_converted_into_failure_detail(db, eligible_deal_flag):
    """No raw exception text may reach persistence."""
    from alerts.models import AlertDelivery

    sender = RecordingSender(side_effect=ValueError("raw internal detail TASK032"))
    with override_settings(**enabled_alert_settings()):
        with pytest.raises(ValueError):
            run(sender)

    delivery = AlertDelivery.objects.get(deal_flag=eligible_deal_flag)
    assert delivery.failure_detail is None
    assert delivery.status == "pending"


# ---------------------------------------------------------------------------
# Command surface
# ---------------------------------------------------------------------------


def test_command_prints_the_exact_summary_on_a_clean_run(db, eligible_deal_flag):
    from unittest import mock

    stdout = StringIO()
    with override_settings(**enabled_alert_settings()):
        with mock.patch("alerts.orchestration.send_telegram_message", return_value=None):
            call_command("send_deal_alerts", stdout=stdout)

    assert stdout.getvalue().strip() == summary_line(1, 1, 0)


def test_command_summary_reports_zero_candidates_when_nothing_is_eligible(db):
    stdout = StringIO()
    with override_settings(**enabled_alert_settings()):
        call_command("send_deal_alerts", stdout=stdout)

    assert stdout.getvalue().strip() == summary_line(0, 0, 0)


def test_command_exits_non_zero_when_any_send_failed(db, eligible_deal_flag):
    """docs/07_PLANNING.md section 8: the exit status must reflect failures so a
    scheduler can surface a bad run."""
    from unittest import mock

    from alerts.delivery import AlertDeliveryError

    stdout = StringIO()
    with override_settings(**enabled_alert_settings()):
        with mock.patch(
            "alerts.orchestration.send_telegram_message",
            side_effect=AlertDeliveryError("api_rejected"),
        ):
            with pytest.raises(CommandError, match=FAILURE_EXIT_MESSAGE):
                call_command("send_deal_alerts", stdout=stdout)

    # The summary is written before the failure is raised, so an operator
    # always sees the counts.
    assert summary_line(1, 0, 1) in stdout.getvalue()


def test_command_reports_mixed_results_and_still_exits_non_zero(db, deal_flag_factory):
    from unittest import mock

    from alerts.delivery import AlertDeliveryError

    deal_flag_factory()
    deal_flag_factory()
    deal_flag_factory()

    outcomes = [None, AlertDeliveryError("timeout"), None]

    def flaky(_config, _text):
        result = outcomes.pop(0)
        if result is not None:
            raise result
        return None

    stdout = StringIO()
    with override_settings(**enabled_alert_settings()):
        with mock.patch("alerts.orchestration.send_telegram_message", side_effect=flaky):
            with pytest.raises(CommandError):
                call_command("send_deal_alerts", stdout=stdout)

    assert summary_line(3, 2, 1) in stdout.getvalue()


def test_send_deal_alerts_command_is_registered(db):
    """The command exists under its frozen name and is reachable by the scheduler."""
    from django.core.management import get_commands

    assert get_commands().get("send_deal_alerts") == "alerts"


def test_command_takes_no_force_limit_or_dry_run_arguments(db):
    """No retry, resend, cap, or second invocation path exists in v1.

    The "Unknown command" guard keeps this from passing vacuously before the
    command exists.
    """
    for argument in ("--force", "--limit", "--dry-run", "--resend"):
        with override_settings(**enabled_alert_settings()):
            with pytest.raises(CommandError) as raised:
                call_command("send_deal_alerts", argument, stdout=StringIO())
            assert "Unknown command" not in str(raised.value)


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


FORBIDDEN_IN_OUTPUT = (
    FAKE_BOT_TOKEN,
    FAKE_CHAT_ID,
    "api.telegram.org",
    "/sendMessage",
    SECRET_RAW_TITLE,
    SECRET_RAW_PRICE_TEXT,
    SECRET_SELLER,
    SECRET_SOURCE_URL,
    "external-marketplace.invalid",
)


def test_command_output_contains_no_secret_or_raw_listing_evidence(db, eligible_deal_flag):
    from unittest import mock

    stdout = StringIO()
    stderr = StringIO()
    with override_settings(**enabled_alert_settings()):
        with mock.patch("alerts.orchestration.send_telegram_message", return_value=None):
            call_command("send_deal_alerts", stdout=stdout, stderr=stderr)

    combined = stdout.getvalue() + stderr.getvalue()
    for forbidden in FORBIDDEN_IN_OUTPUT:
        assert forbidden not in combined


def test_failed_command_output_contains_no_secret_or_raw_listing_evidence(
    db,
    eligible_deal_flag,
):
    from unittest import mock

    from alerts.delivery import AlertDeliveryError

    stdout = StringIO()
    stderr = StringIO()
    with override_settings(**enabled_alert_settings()):
        with mock.patch(
            "alerts.orchestration.send_telegram_message",
            side_effect=AlertDeliveryError("api_rejected"),
        ):
            with pytest.raises(CommandError) as raised:
                call_command("send_deal_alerts", stdout=stdout, stderr=stderr)

    combined = stdout.getvalue() + stderr.getvalue() + str(raised.value)
    for forbidden in FORBIDDEN_IN_OUTPUT:
        assert forbidden not in combined


def test_persisted_failure_detail_contains_no_secret_or_raw_listing_evidence(
    db,
    eligible_deal_flag,
):
    from alerts.delivery import AlertDeliveryError
    from alerts.models import AlertDelivery

    sender = RecordingSender(side_effect=AlertDeliveryError("transport_failure"))
    with override_settings(**enabled_alert_settings()):
        run(sender)

    detail = AlertDelivery.objects.get().failure_detail
    for forbidden in FORBIDDEN_IN_OUTPUT:
        assert forbidden not in detail


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------


def test_task_030_alert_delivery_contract_is_untouched():
    """TASK_032 orchestrates the persistence layer; it does not change it."""
    from alerts.models import AlertDelivery

    field_names = {field.name for field in AlertDelivery._meta.get_fields()}
    assert {"deal_flag", "status", "claimed_at", "terminal_at", "failure_detail"} <= field_names

    constraint_names = {c.name for c in AlertDelivery._meta.constraints}
    assert constraint_names == {
        "alertdelivery_status_in_vocabulary",
        "alertdelivery_terminal_at_matches_status",
        "alertdelivery_failure_detail_matches_status",
        "alertdelivery_terminal_at_not_before_claimed_at",
    }


def test_task_031_sanitized_vocabulary_is_reused_not_redefined():
    """The four reasons and their messages belong to TASK_031."""
    from alerts.delivery import AlertDeliveryError

    for reason, message in [
        ("timeout", "Telegram request timed out."),
        ("transport_failure", "Telegram request could not be completed."),
        ("invalid_response", "Telegram returned an unreadable response."),
        ("api_rejected", "Telegram rejected the message."),
    ]:
        assert str(AlertDeliveryError(reason)) == message


def test_orchestration_adds_no_new_third_party_dependency():
    from pathlib import Path

    requirements = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text().lower()

    assert "celery" not in requirements
    assert "redis" not in requirements
    assert "requests" not in requirements
    assert "httpx" not in requirements
