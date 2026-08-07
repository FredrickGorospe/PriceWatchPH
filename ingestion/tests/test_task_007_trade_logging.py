import json
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from ingestion.pseudonymise import pseudonymise
from ingestion.timeparse import manila_midnight


@pytest.fixture
def personal_records_source(db):
    from sources.models import Source

    return Source.objects.get(name="personal_records")


@pytest.fixture
def log_trade_url():
    return reverse("admin:ingestion_rawlisting_log_personal_trade")


@pytest.fixture
def rawlisting_add_url():
    return reverse("admin:ingestion_rawlisting_add")


# --- plain buy / sell --------------------------------------------------------

def test_buy_writes_one_rawlisting_with_correct_payload(admin_client, log_trade_url, personal_records_source):
    """Submitting a Buy writes exactly one RawListing under personal_records, with stated_trade_side and stated_condition captured in payload."""
    from ingestion.models import RawListing

    response = admin_client.post(log_trade_url, {
        "trade_type": "buy",
        "occurred_on": "2026-08-01",
        "counterparty": "Juan Dela Cruz",
        "item": "ASUS TUF RTX 4070 12GB",
        "condition": "used",
        "price": "15500",
    })
    assert response.status_code == 302

    rows = RawListing.objects.filter(source=personal_records_source)
    assert rows.count() == 1
    row = rows.get()
    assert row.raw_title == "ASUS TUF RTX 4070 12GB"
    assert row.raw_price == Decimal("15500")
    assert row.raw_price_text == "15500"
    assert row.occurred_at == manila_midnight(date(2026, 8, 1))
    assert row.payload == {"stated_trade_side": "buy", "stated_condition": "used"}
    assert row.seller == pseudonymise("Juan Dela Cruz")
    assert row.external_id is None


def test_sell_writes_one_rawlisting_with_stated_trade_side_sell(admin_client, log_trade_url, personal_records_source):
    """Submitting a Sell records stated_trade_side='sell' — the mirror case of Buy — and an empty counterparty stays an empty, non-pseudonymized string."""
    from ingestion.models import RawListing

    response = admin_client.post(log_trade_url, {
        "trade_type": "sell",
        "occurred_on": "2026-08-01",
        "counterparty": "",
        "item": "Corsair Vengeance 32GB DDR5",
        "condition": "like_new",
        "price": "4500",
    })
    assert response.status_code == 302

    row = RawListing.objects.get(source=personal_records_source)
    assert row.payload == {"stated_trade_side": "sell", "stated_condition": "like_new"}
    assert row.seller == ""


def test_condition_is_omitted_from_payload_when_not_given(admin_client, log_trade_url, personal_records_source):
    """payload only records what was actually stated: no condition given means no stated_condition key at all, not an empty or null one."""
    from ingestion.models import RawListing

    response = admin_client.post(log_trade_url, {
        "trade_type": "buy",
        "occurred_on": "2026-08-01",
        "counterparty": "",
        "item": "Mystery GPU",
        "condition": "",
        "price": "1000",
    })
    assert response.status_code == 302

    row = RawListing.objects.get(source=personal_records_source)
    assert row.payload == {"stated_trade_side": "buy"}
    assert "stated_condition" not in row.payload


# --- swap ---------------------------------------------------------------------

def test_swap_writes_two_linked_rawlistings_and_a_swap_row(admin_client, log_trade_url, personal_records_source):
    """A Swap writes two RawListing rows (given resolves sell, received resolves buy) and one Swap row linking them, sharing the same date and counterparty token."""
    from ingestion.models import RawListing, Swap

    response = admin_client.post(log_trade_url, {
        "trade_type": "swap",
        "occurred_on": "2026-08-01",
        "counterparty": "Maria Santos",
        "given_item": "RTX 4060",
        "given_condition": "used",
        "given_value": "18000",
        "received_item": "RTX 4070",
        "received_condition": "used",
        "received_value": "22000",
        "cash_adjustment": "4000",
    })
    assert response.status_code == 302

    assert RawListing.objects.filter(source=personal_records_source).count() == 2
    swap = Swap.objects.get()

    assert swap.given_listing.raw_title == "RTX 4060"
    assert swap.given_listing.raw_price == Decimal("18000")
    assert swap.given_listing.payload == {"stated_trade_side": "sell", "stated_condition": "used"}

    assert swap.received_listing.raw_title == "RTX 4070"
    assert swap.received_listing.raw_price == Decimal("22000")
    assert swap.received_listing.payload == {"stated_trade_side": "buy", "stated_condition": "used"}

    assert swap.cash_adjustment == Decimal("4000")

    expected_date = manila_midnight(date(2026, 8, 1))
    assert swap.given_listing.occurred_at == expected_date
    assert swap.received_listing.occurred_at == expected_date

    expected_token = pseudonymise("Maria Santos")
    assert swap.given_listing.seller == expected_token
    assert swap.received_listing.seller == expected_token


def test_swap_cash_adjustment_is_nullable_for_an_even_trade(admin_client, log_trade_url, personal_records_source):
    """An even swap (no cash changing hands) leaves cash_adjustment NULL — not defaulted to zero."""
    from ingestion.models import Swap

    response = admin_client.post(log_trade_url, {
        "trade_type": "swap",
        "occurred_on": "2026-08-01",
        "counterparty": "",
        "given_item": "RTX 4060",
        "given_value": "18000",
        "received_item": "RTX 4060 (different unit)",
        "received_value": "18000",
        "cash_adjustment": "",
    })
    assert response.status_code == 302
    assert Swap.objects.get().cash_adjustment is None


# --- invalid prices rejected before any write ----------------------------------

def test_invalid_price_on_a_plain_trade_writes_nothing(admin_client, log_trade_url, personal_records_source):
    """A non-numeric price is rejected by the form; no RawListing is created, unlike a scraped listing's tolerated unparseable price."""
    from ingestion.models import RawListing

    response = admin_client.post(log_trade_url, {
        "trade_type": "buy",
        "occurred_on": "2026-08-01",
        "counterparty": "",
        "item": "ASUS TUF RTX 4070 12GB",
        "condition": "used",
        "price": "PM for price",
    })
    assert response.status_code == 200
    assert RawListing.objects.filter(source=personal_records_source).count() == 0


def test_missing_required_price_writes_nothing(admin_client, log_trade_url, personal_records_source):
    """An empty price on a plain buy/sell is rejected the same as a non-numeric one — nothing gets written."""
    from ingestion.models import RawListing

    response = admin_client.post(log_trade_url, {
        "trade_type": "sell",
        "occurred_on": "2026-08-01",
        "counterparty": "",
        "item": "ASUS TUF RTX 4070 12GB",
        "condition": "",
        "price": "",
    })
    assert response.status_code == 200
    assert RawListing.objects.filter(source=personal_records_source).count() == 0


def test_invalid_price_on_a_swap_writes_nothing(admin_client, log_trade_url, personal_records_source):
    """The same rejection-before-write rule applies to a swap's give/get values: a bad received_value writes neither RawListing nor the Swap row."""
    from ingestion.models import RawListing, Swap

    response = admin_client.post(log_trade_url, {
        "trade_type": "swap",
        "occurred_on": "2026-08-01",
        "counterparty": "",
        "given_item": "RTX 4060",
        "given_value": "18000",
        "received_item": "RTX 4070",
        "received_value": "not-a-number",
        "cash_adjustment": "",
    })
    assert response.status_code == 200
    assert RawListing.objects.filter(source=personal_records_source).count() == 0
    assert Swap.objects.count() == 0


# --- RawListingAdmin permissions stay locked down ------------------------------

def test_rawlisting_add_view_is_still_blocked(admin_client, rawlisting_add_url):
    """The default admin Add form for RawListing stays forbidden — this feature adds a side channel, it doesn't loosen the existing guard."""
    response = admin_client.get(rawlisting_add_url)
    assert response.status_code == 403


def test_rawlisting_change_and_delete_stay_blocked_after_a_trade_is_logged(admin_client, log_trade_url, personal_records_source):
    """Even a RawListing created through the new trade-log view still can't be edited or deleted through the admin."""
    from ingestion.models import RawListing

    admin_client.post(log_trade_url, {
        "trade_type": "buy",
        "occurred_on": "2026-08-01",
        "counterparty": "",
        "item": "ASUS TUF RTX 4070 12GB",
        "condition": "used",
        "price": "15500",
    })
    row = RawListing.objects.get(source=personal_records_source)

    change_url = reverse("admin:ingestion_rawlisting_change", args=[row.pk])
    delete_url = reverse("admin:ingestion_rawlisting_delete", args=[row.pk])
    assert admin_client.get(change_url).status_code == 403
    assert admin_client.get(delete_url).status_code == 403


def test_log_trade_view_requires_login(client, log_trade_url):
    """The new view sits behind the same staff login as the rest of /admin/ — an anonymous request is redirected, not served."""
    response = client.get(log_trade_url)
    assert response.status_code == 302
    assert "/admin/login/" in response.url


# --- security property carried forward from TASK_005 ---------------------------

def test_plaintext_counterparty_appears_nowhere_after_a_swap(admin_client, log_trade_url):
    """The same property TASK_005 established for the plain importer holds here: after logging a swap, the plaintext name is absent from both resulting rows entirely."""
    from ingestion.models import Swap

    name = "Juan Dela Cruz"
    admin_client.post(log_trade_url, {
        "trade_type": "swap",
        "occurred_on": "2026-08-01",
        "counterparty": name,
        "given_item": "RTX 4060",
        "given_value": "18000",
        "received_item": "RTX 4070",
        "received_value": "22000",
        "cash_adjustment": "4000",
    })
    swap = Swap.objects.get()
    serialised = json.dumps(
        {
            "given": {
                "raw_title": swap.given_listing.raw_title,
                "seller": swap.given_listing.seller,
                "payload": swap.given_listing.payload,
            },
            "received": {
                "raw_title": swap.received_listing.raw_title,
                "seller": swap.received_listing.seller,
                "payload": swap.received_listing.payload,
            },
        },
        default=str,
    )
    assert name not in serialised
    assert name.lower() not in serialised.lower()
