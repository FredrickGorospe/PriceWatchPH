import hashlib
import json
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone


@pytest.fixture
def source(db):
    from sources.models import Source

    return Source.objects.create(
        name="test_source",
        base_url="https://example.invalid",
        terms_notes="test fixture",
        rate_limit=None,
    )


def _raw(source, **overrides):
    from ingestion.models import RawListing

    fields = dict(
        source=source,
        raw_title="ASUS TUF RTX 4070 12GB",
        raw_price_text="15500",
        raw_price=Decimal("15500.00"),
        url="https://example.invalid/x",
        seller="anon",
        fetched_at=timezone.now(),
        external_id=None,
    )
    fields.update(overrides)
    return RawListing.objects.create(**fields)


# --- occurred_at ------------------------------------------------------------

def test_occurred_at_defaults_to_null_and_is_distinct_from_fetched_at(source):
    """occurred_at is optional and independent of fetched_at: a source that states no event date leaves it NULL."""
    row = _raw(source)
    row.refresh_from_db()
    assert row.occurred_at is None
    assert row.fetched_at is not None


def test_occurred_at_records_a_historical_date_while_fetched_at_records_the_import(source):
    """A 2019 transaction imported in 2026 keeps both facts: occurred_at in 2019, fetched_at at import time."""
    occurred = datetime(2019, 3, 4, 16, 0, tzinfo=dt_timezone.utc)
    imported = datetime(2026, 8, 1, 2, 30, tzinfo=dt_timezone.utc)
    row = _raw(source, occurred_at=occurred, fetched_at=imported)
    row.refresh_from_db()
    assert row.occurred_at == occurred
    assert row.fetched_at == imported
    assert row.occurred_at.year == 2019
    assert row.fetched_at.year == 2026


# --- payload ----------------------------------------------------------------

def test_payload_round_trips_a_verbatim_source_row(source):
    """The payload column stores the source row as JSON and returns it unchanged."""
    payload = {"record_id": "REC-001", "item": "RTX 4070", "price": "15500", "notes": "meetup QC"}
    row = _raw(source, payload=payload)
    row.refresh_from_db()
    assert row.payload == payload


def test_payload_null_and_empty_dict_are_distinguishable(source):
    """NULL payload ('none recorded') and {} ('recorded and empty') are different facts and stay different."""
    absent = _raw(source, payload=None)
    empty = _raw(source, payload={})
    absent.refresh_from_db()
    empty.refresh_from_db()
    assert absent.payload is None
    assert empty.payload == {}


# --- pseudonymisation -------------------------------------------------------

def test_pseudonymise_is_stable_for_the_same_counterparty():
    """The same counterparty yields the same token, which is what makes repeat-counterparty linkage possible."""
    from ingestion.pseudonymise import pseudonymise

    assert pseudonymise("Juan Dela Cruz") == pseudonymise("Juan Dela Cruz")
    assert pseudonymise("Juan Dela Cruz") != pseudonymise("Maria Santos")


def test_pseudonymise_is_keyed_not_a_bare_digest():
    """The token is an HMAC under a secret key, never a bare SHA-256 of the plaintext, which would be brute-forceable."""
    from ingestion.pseudonymise import pseudonymise

    plaintext = "Juan Dela Cruz"
    assert pseudonymise(plaintext) != hashlib.sha256(plaintext.encode()).hexdigest()


def test_pseudonymise_changes_with_the_key(monkeypatch):
    """A different key produces a different token — proving the key is actually an input."""
    from django.test import override_settings
    from ingestion.pseudonymise import pseudonymise

    with override_settings(SELLER_PSEUDONYM_KEY="key-one"):
        first = pseudonymise("Juan Dela Cruz")
    with override_settings(SELLER_PSEUDONYM_KEY="key-two"):
        second = pseudonymise("Juan Dela Cruz")
    assert first != second


def test_redactor_replaces_pii_keys_and_passes_everything_else_through():
    """redact_payload pseudonymises known PII keys and leaves every other key verbatim."""
    from ingestion.pseudonymise import pseudonymise, redact_payload

    redacted = redact_payload(
        {"seller": "Juan Dela Cruz", "item": "RTX 4070", "price": "15500"}
    )
    assert redacted["seller"] == pseudonymise("Juan Dela Cruz")
    assert redacted["item"] == "RTX 4070"
    assert redacted["price"] == "15500"


def test_redacted_payload_token_is_identical_to_the_seller_column_token(source):
    """The payload's counterparty token and the seller column's token are the same value from the same function — not two independently derived values that merely agree today."""
    from ingestion.pseudonymise import pseudonymise, redact_payload

    name = "Juan Dela Cruz"
    row = _raw(
        source,
        seller=pseudonymise(name),
        payload=redact_payload({"seller": name, "item": "RTX 4070"}),
    )
    row.refresh_from_db()
    assert row.payload["seller"] == row.seller
    assert row.seller == pseudonymise(name)


def test_plaintext_counterparty_name_appears_nowhere_in_the_persisted_row(source):
    """The security property: after a pseudonymised write, the plaintext name is absent from every column of the stored row, payload included."""
    from ingestion.pseudonymise import pseudonymise, redact_payload

    name = "Juan Dela Cruz"
    row = _raw(
        source,
        seller=pseudonymise(name),
        payload=redact_payload({"seller": name, "item": "RTX 4070", "notes": "meetup QC"}),
    )
    row.refresh_from_db()

    serialised = json.dumps(
        {
            "raw_title": row.raw_title,
            "raw_price_text": row.raw_price_text,
            "url": row.url,
            "seller": row.seller,
            "external_id": row.external_id,
            "payload": row.payload,
        },
        default=str,
    )
    assert name not in serialised
    assert name.lower() not in serialised.lower()


# --- side-qualified external_id ---------------------------------------------

def test_side_qualified_external_ids_let_both_sides_of_a_same_day_transaction_persist(source):
    """A transaction bought and sold on the same day writes two rows, because ':buy' and ':sell' make them distinct by construction."""
    from ingestion.models import RawListing

    now = timezone.now()
    occurred = datetime(2019, 3, 4, 16, 0, tzinfo=dt_timezone.utc)
    _raw(source, external_id="REC-001:buy", fetched_at=now, occurred_at=occurred)
    _raw(source, external_id="REC-001:sell", fetched_at=now, occurred_at=occurred)
    assert RawListing.objects.filter(source=source).count() == 2


def test_unqualified_external_id_collides_for_a_same_day_transaction(source):
    """The failure the suffix exists to prevent: without it, the second side of a same-day transaction is rejected as a false duplicate."""
    now = timezone.now()
    _raw(source, external_id="REC-001", fetched_at=now)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _raw(source, external_id="REC-001", fetched_at=now)


def test_side_qualified_external_id_still_rejects_a_true_duplicate(source):
    """Suffixing must not disable idempotency: re-importing the same side of the same record at the same fetch time still collides."""
    now = timezone.now()
    _raw(source, external_id="REC-001:buy", fetched_at=now)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _raw(source, external_id="REC-001:buy", fetched_at=now)


# --- date-only parsing ------------------------------------------------------

def test_a_bare_source_date_is_stored_as_manila_midnight(source):
    """A source stating '2019-03-04' with no time is stored as Manila midnight, i.e. 16:00 UTC on 2019-03-03."""
    from ingestion.timeparse import manila_midnight

    stored = manila_midnight(date(2019, 3, 4))
    assert stored == datetime(2019, 3, 3, 16, 0, tzinfo=dt_timezone.utc)
