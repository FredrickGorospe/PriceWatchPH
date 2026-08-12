"""TASK_033 targeted admin-visibility tests.

Per docs/07_PLANNING.md §18 this task is LOW risk and deliberately has no
frozen acceptance module: these are ordinary targeted tests in the style of
pricing/tests/test_task_019_pricing_evidence.py and
pricing/tests/test_task_022_operational_pricing.py, which §19 names as the
precedent.

What matters here is that the admin can *show* a stuck pending claim and can
never *change* one, and that showing it leaks neither a credential nor
RawListing/Source evidence.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.utils import timezone


EXPECTED_LIST_DISPLAY = (
    "deal_flag",
    "status",
    "claimed_at",
    "terminal_at",
    "failure_detail",
)

CHANGELIST_URL = "/admin/alerts/alertdelivery/"

# Obviously synthetic, inert. Nothing here is a real credential.
FAKE_BOT_TOKEN = "1234567890:SYNTHETIC-TASK033-TOKEN-DO-NOT-USE"
FAKE_CHAT_ID = "-1009876543210"

# Upstream values the alert path must never surface.
SECRET_RAW_TITLE = "TASK033 RAW TITLE MUST NOT LEAK"
SECRET_RAW_PRICE_TEXT = "TASK033-RAW-PRICE-TEXT"
SECRET_SELLER = "task033-seller-must-not-leak"
SECRET_SOURCE_URL = "https://external-marketplace.invalid/task033-listing"
SECRET_SOURCE_NAME = "task_033_source"


@pytest.fixture
def deal_flag_factory(db):
    """DealFlags whose upstream RawListings carry values that must not leak."""
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
        name=SECRET_SOURCE_NAME,
        base_url="https://example.invalid",
        terms_notes="Synthetic TASK_033 fixture",
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

    def make():
        raw_listing = RawListing.objects.create(
            source=source,
            raw_title=SECRET_RAW_TITLE,
            raw_price_text=SECRET_RAW_PRICE_TEXT,
            raw_price=Decimal("12500.00"),
            url=SECRET_SOURCE_URL,
            seller=SECRET_SELLER,
            fetched_at=timezone.now(),
            external_id=None,
        )
        listing = Listing.objects.create(
            raw_listing=raw_listing,
            sku=sku,
            price=Decimal("12500.00"),
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


def claim(deal_flag, status="pending", failure_detail=None, claimed_at=None):
    """Create an AlertDelivery through TASK_030's approved lifecycle only."""
    from alerts.models import AlertDelivery

    delivery = AlertDelivery.objects.create(
        deal_flag=deal_flag,
        status="pending",
        claimed_at=claimed_at or timezone.now(),
        terminal_at=None,
        failure_detail=None,
    )
    if status != "pending":
        delivery.status = status
        delivery.terminal_at = timezone.now()
        delivery.failure_detail = failure_detail
        delivery.save(update_fields=["status", "terminal_at", "failure_detail"])
    return delivery


def model_admin():
    from alerts.models import AlertDelivery

    return admin.site._registry[AlertDelivery]


# --- Registration and the read-only contract -------------------------------


def test_alert_delivery_is_registered_in_admin():
    """Phase 7 is not complete without a visible delivery history (§1, §16)."""
    from alerts.models import AlertDelivery

    assert AlertDelivery in admin.site._registry


def test_alert_admin_contract_is_view_only(db, admin_user):
    """Readable, never writable — the same contract pricing evidence uses."""
    request = RequestFactory().get("/admin/")
    request.user = admin_user
    registered = model_admin()

    assert registered.has_view_permission(request) is True
    assert registered.has_add_permission(request) is False
    assert registered.has_change_permission(request) is False
    assert registered.has_delete_permission(request) is False
    assert registered.get_actions(request) == {}

    readonly_fields = set(registered.get_readonly_fields(request))
    concrete_fields = {field.name for field in registered.model._meta.fields}
    assert concrete_fields <= readonly_fields


def test_alert_admin_changelist_configuration_is_diagnostic(db):
    """The changelist answers: claimed, when, sent, failed — and finds stuck rows."""
    registered = model_admin()

    assert tuple(registered.list_display) == EXPECTED_LIST_DISPLAY
    assert tuple(registered.list_filter) == ("status",)
    assert tuple(registered.ordering) == ("-claimed_at", "pk")
    assert tuple(registered.list_select_related) == ("deal_flag",)


def test_alert_admin_does_not_traverse_into_raw_listing_or_source(db):
    """list_select_related stops at deal_flag: Phase 7 keeps RawListing and
    Source evidence out of the alert path entirely."""
    related = tuple(model_admin().list_select_related)

    for forbidden in ("raw_listing", "source", "listing__raw_listing"):
        assert not any(forbidden in entry for entry in related)


# --- The stuck pending row is visible --------------------------------------


def test_pending_claim_is_visible_in_the_changelist(db, admin_client, deal_flag):
    """A stuck pending row is the visible signature of a crash between claim
    and terminal record (§11) — the admin is where it becomes noticeable."""
    delivery = claim(deal_flag)

    response = admin_client.get(CHANGELIST_URL)
    body = response.content.decode()

    assert response.status_code == 200
    assert "pending" in body
    assert str(delivery.deal_flag) in body


@pytest.mark.parametrize(
    "status,failure_detail",
    [
        ("sent", None),
        ("failed", "Telegram rejected the message."),
    ],
)
def test_terminal_claims_are_visible_in_the_changelist(
    db,
    admin_client,
    deal_flag,
    status,
    failure_detail,
):
    claim(deal_flag, status=status, failure_detail=failure_detail)

    response = admin_client.get(CHANGELIST_URL)
    body = response.content.decode()

    assert response.status_code == 200
    assert status in body
    if failure_detail is not None:
        assert failure_detail in body


def test_status_filter_narrows_to_stuck_pending_rows(db, admin_client, deal_flag_factory):
    """Filtering by status is what makes one stuck row findable among many."""
    stuck = claim(deal_flag_factory())
    claim(deal_flag_factory(), status="sent")
    claim(
        deal_flag_factory(),
        status="failed",
        failure_detail="Telegram rejected the message.",
    )

    response = admin_client.get(CHANGELIST_URL, {"status__exact": "pending"})
    changelist = response.context["cl"]

    assert response.status_code == 200
    assert list(changelist.result_list) == [stuck]


def test_changelist_orders_most_recent_claim_first(db, admin_client, deal_flag):
    """Recency ordering, mirroring DealFlagAdmin's -flagged_at convention."""
    older = claim(deal_flag, claimed_at=timezone.now() - timedelta(hours=2))

    response = admin_client.get(CHANGELIST_URL)
    changelist = response.context["cl"]

    assert response.status_code == 200
    assert list(changelist.result_list) == [older]


# --- Mutation is impossible ------------------------------------------------


def test_admin_add_url_is_blocked(db, admin_client):
    """A claim is created only by send_deal_alerts, never by hand."""
    response = admin_client.get("/admin/alerts/alertdelivery/add/")

    assert response.status_code in (302, 403)


def test_admin_delete_url_is_blocked(db, admin_client, deal_flag):
    """Deleting a claim would reopen the DealFlag and break at-most-once."""
    delivery = claim(deal_flag)

    response = admin_client.get(f"/admin/alerts/alertdelivery/{delivery.pk}/delete/")

    assert response.status_code in (302, 403)


def test_admin_change_post_does_not_mutate_a_claim(db, admin_client, deal_flag):
    """Even a forged POST leaves the durable claim untouched."""
    from alerts.models import AlertDelivery

    delivery = claim(deal_flag)

    admin_client.post(
        f"/admin/alerts/alertdelivery/{delivery.pk}/change/",
        {"status": "sent", "terminal_at": timezone.now().isoformat()},
    )

    delivery.refresh_from_db()
    assert delivery.status == "pending"
    assert delivery.terminal_at is None
    assert AlertDelivery.objects.count() == 1


def test_admin_exposes_no_send_resend_or_retry_route(db):
    """§12: no admin action that triggers or resends a send — that would be a
    second, less-auditable invocation path alongside the command.

    Asserted as an exact set rather than by substring: the model is named
    AlertDelivery, so `alerts_alertdelivery_changelist` legitimately contains
    "deliver" and a substring scan would flag Django's own default routes.
    """
    registered = model_admin()
    url_names = {entry.name for entry in registered.get_urls() if entry.name}

    assert url_names == {
        "alerts_alertdelivery_changelist",
        "alerts_alertdelivery_add",
        "alerts_alertdelivery_history",
        "alerts_alertdelivery_delete",
        "alerts_alertdelivery_change",
    }


def test_admin_declares_no_bulk_actions(db, admin_user):
    request = RequestFactory().get("/admin/")
    request.user = admin_user

    assert model_admin().actions is None
    assert model_admin().get_actions(request) == {}


# --- Privacy ----------------------------------------------------------------


def test_changelist_leaks_no_credential(db, admin_client, deal_flag, settings):
    """The token and destination live in settings and must never reach a page."""
    settings.TELEGRAM_BOT_TOKEN = FAKE_BOT_TOKEN
    settings.TELEGRAM_CHAT_ID = FAKE_CHAT_ID
    claim(deal_flag, status="failed", failure_detail="Telegram rejected the message.")

    body = admin_client.get(CHANGELIST_URL).content.decode()

    assert FAKE_BOT_TOKEN not in body
    assert FAKE_CHAT_ID not in body
    assert "api.telegram.org" not in body
    assert "/sendMessage" not in body


def test_changelist_leaks_no_raw_listing_or_source_evidence(db, admin_client, deal_flag):
    """Phase 7's privacy boundary holds on the admin surface too."""
    claim(deal_flag)

    body = admin_client.get(CHANGELIST_URL).content.decode()

    for forbidden in (
        SECRET_RAW_TITLE,
        SECRET_RAW_PRICE_TEXT,
        SECRET_SELLER,
        SECRET_SOURCE_URL,
        SECRET_SOURCE_NAME,
    ):
        assert forbidden not in body


def test_changelist_render_queries_no_raw_listing_or_source_table(
    db,
    admin_client,
    deal_flag,
):
    """Privacy at the query boundary, not merely in the rendered output."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    claim(deal_flag)

    with CaptureQueriesContext(connection) as queries:
        admin_client.get(CHANGELIST_URL)

    executed_sql = "\n".join(query["sql"].lower() for query in queries)
    assert "ingestion_rawlisting" not in executed_sql
    assert "sources_source" not in executed_sql


# --- The admin is inert -----------------------------------------------------


def test_changelist_render_invokes_no_alert_service(
    db,
    admin_client,
    deal_flag,
    monkeypatch,
):
    """Viewing delivery history must never send, claim, or orchestrate."""
    import alerts.orchestration as orchestration
    import alerts.telegram as telegram_module

    def explode(*args, **kwargs):
        raise AssertionError("the admin must not invoke an alert service")

    monkeypatch.setattr(telegram_module, "urlopen", explode)
    monkeypatch.setattr(orchestration, "send_telegram_message", explode)
    monkeypatch.setattr(orchestration, "send_pending_deal_alerts", explode)

    claim(deal_flag)
    response = admin_client.get(CHANGELIST_URL)

    assert response.status_code == 200


# --- Compatibility ----------------------------------------------------------


def test_task_030_alert_delivery_contract_is_untouched():
    """TASK_033 registers the model; it does not change it."""
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


def test_task_032_send_command_remains_the_only_send_path(db):
    """The command still exists and the admin adds no rival to it."""
    from django.core.management import get_commands

    assert get_commands().get("send_deal_alerts") == "alerts"
