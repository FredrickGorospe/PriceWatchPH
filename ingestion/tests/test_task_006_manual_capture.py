import io
import json
import sys
import time
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import ProgrammingError, transaction
from django.utils import timezone

from ingestion.pseudonymise import pseudonymise


@pytest.fixture
def manual_capture_source(db):
    from sources.models import Source

    return Source.objects.get(name="manual_capture")


def _run_ingest(monkeypatch, value, *, importer="manual_capture"):
    raw_input = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw_input))
    call_command("ingest", importer, verbosity=0)


def _assert_structural_failure(monkeypatch, raw_input):
    from ingestion.models import RawListing

    before = RawListing.objects.count()
    with pytest.raises(CommandError) as caught:
        _run_ingest(monkeypatch, raw_input)

    # The missing pre-implementation command must not make failure-path tests
    # pass vacuously; this must be TASK_006 input validation rejecting the data.
    assert "Unknown command" not in str(caught.value)
    assert caught.value.returncode != 0
    assert RawListing.objects.count() == before


def _valid_payload(**overrides):
    payload = {"title": "ASUS TUF RTX 4070 12GB", "price": "15,500.00"}
    payload.update(overrides)
    return payload


# --- command interface -------------------------------------------------------


def test_ingest_manual_capture_reads_exactly_one_stdin_json_object(
    monkeypatch, manual_capture_source
):
    from ingestion.models import RawListing

    raw_input = json.dumps(_valid_payload(), ensure_ascii=False) + "\n\t"
    _run_ingest(monkeypatch, raw_input)

    assert RawListing.objects.filter(source=manual_capture_source).count() == 1


def test_ingest_manual_capture_accepts_utf8_without_an_interactive_terminal(
    monkeypatch, manual_capture_source
):
    from ingestion.models import RawListing

    def fail_if_prompted(*args, **kwargs):
        raise AssertionError("manual_capture must not prompt interactively")

    monkeypatch.setattr("builtins.input", fail_if_prompted)
    title = "Señor's GPU — edición especial"
    _run_ingest(monkeypatch, _valid_payload(title=title))

    assert RawListing.objects.get(source=manual_capture_source).raw_title == title


def test_importer_name_is_explicit_not_discovered_from_source_rows(monkeypatch, db):
    from ingestion.models import RawListing
    from sources.models import Source

    Source.objects.create(
        name="database_only_importer",
        base_url="",
        terms_notes="A row is not an importer registration.",
        rate_limit=None,
    )

    with pytest.raises(CommandError) as caught:
        _run_ingest(
            monkeypatch,
            _valid_payload(),
            importer="database_only_importer",
        )

    assert "Unknown command" not in str(caught.value)
    assert caught.value.returncode != 0
    assert RawListing.objects.count() == 0


def test_file_input_argument_is_not_accepted(monkeypatch, db):
    from ingestion.models import RawListing

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_valid_payload())))
    with pytest.raises(CommandError) as caught:
        call_command("ingest", "manual_capture", "capture.json", verbosity=0)

    assert "Unknown command" not in str(caught.value)
    assert caught.value.returncode != 0
    assert RawListing.objects.count() == 0


# --- structural validation and atomicity ------------------------------------


def test_malformed_json_raises_commanderror_and_writes_nothing(monkeypatch, db):
    _assert_structural_failure(monkeypatch, '{"title": "RTX 4070",')


@pytest.mark.parametrize("raw_input", ["[]", "null", '"just text"', "123"])
def test_non_object_json_writes_nothing(monkeypatch, db, raw_input):
    _assert_structural_failure(monkeypatch, raw_input)


def test_trailing_second_json_value_writes_nothing(monkeypatch, db):
    first = json.dumps(_valid_payload())
    second = json.dumps(_valid_payload(title="Second capture"))
    _assert_structural_failure(monkeypatch, f"{first}\n{second}")


@pytest.mark.parametrize(
    "payload",
    [
        {"price": "1000"},
        {"title": "RTX 4070"},
    ],
)
def test_missing_required_fields_write_nothing(monkeypatch, db, payload):
    _assert_structural_failure(monkeypatch, payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"title": 4070, "price": "1000"},
        {"title": ["RTX 4070"], "price": "1000"},
        {"title": {"name": "RTX 4070"}, "price": "1000"},
    ],
)
def test_wrong_title_type_writes_nothing(monkeypatch, db, payload):
    _assert_structural_failure(monkeypatch, payload)


@pytest.mark.parametrize("title", ["", "   ", "\t\n"])
def test_blank_or_whitespace_only_title_writes_nothing(monkeypatch, db, title):
    _assert_structural_failure(monkeypatch, _valid_payload(title=title))


@pytest.mark.parametrize("price", ["", "   ", "\t\n"])
def test_blank_or_whitespace_only_price_writes_nothing(monkeypatch, db, price):
    _assert_structural_failure(monkeypatch, _valid_payload(price=price))


@pytest.mark.parametrize(
    "raw_input",
    [
        '{"title": "RTX 4070", "price": 15500}',
        '{"title": "RTX 4070", "price": 15500.50}',
    ],
)
def test_json_numeric_price_writes_nothing(monkeypatch, db, raw_input):
    _assert_structural_failure(monkeypatch, raw_input)


@pytest.mark.parametrize(
    "extra",
    [
        {"occurred_at": "2026-08-08"},
        {"location": "Quezon City"},
        {"condition": "used"},
    ],
)
def test_unknown_top_level_keys_write_nothing(monkeypatch, db, extra):
    _assert_structural_failure(monkeypatch, _valid_payload(**extra))


@pytest.mark.parametrize(
    "field,value",
    [
        ("url", None),
        ("url", 123),
        ("seller", None),
        ("seller", {"name": "Juan Dela Cruz"}),
        ("external_id", 123),
        ("external_id", ["listing-1"]),
    ],
)
def test_invalid_optional_field_types_write_nothing(monkeypatch, db, field, value):
    _assert_structural_failure(monkeypatch, _valid_payload(**{field: value}))


@pytest.mark.parametrize("external_id", ["", "   ", "\t\n"])
def test_blank_supplied_external_id_writes_nothing(monkeypatch, db, external_id):
    _assert_structural_failure(
        monkeypatch,
        _valid_payload(external_id=external_id),
    )


def test_external_id_longer_than_model_field_writes_nothing(monkeypatch, db):
    from ingestion.models import RawListing

    max_length = RawListing._meta.get_field("external_id").max_length
    _assert_structural_failure(
        monkeypatch,
        _valid_payload(external_id="x" * (max_length + 1)),
    )


# --- RawListing fidelity -----------------------------------------------------


def test_capture_writes_one_faithful_rawlisting(monkeypatch, manual_capture_source):
    from ingestion.models import RawListing

    payload = {
        "title": "  ASUS TUF RTX 4070  12GB?!  ",
        "price": "  15,500.50  ",
        "url": "https://example.invalid/listing?id=ABC-123",
        "external_id": "  ABC-123  ",
    }
    before = timezone.now()
    _run_ingest(monkeypatch, payload)
    after = timezone.now()

    rows = RawListing.objects.filter(source=manual_capture_source)
    assert rows.count() == 1
    row = rows.get()
    assert row.raw_title == payload["title"]
    assert row.raw_price_text == payload["price"]
    assert row.raw_price == Decimal("15500.50")
    assert row.url == payload["url"]
    assert row.external_id == payload["external_id"]
    assert row.occurred_at is None
    assert before <= row.fetched_at <= after
    assert row.payload == payload


def test_absent_optional_fields_use_honest_empty_or_null_values(
    monkeypatch, manual_capture_source
):
    from ingestion.models import RawListing

    payload = _valid_payload()
    _run_ingest(monkeypatch, payload)

    row = RawListing.objects.get(source=manual_capture_source)
    assert row.url == ""
    assert row.seller == ""
    assert row.external_id is None
    assert row.occurred_at is None
    assert row.payload == payload


def test_repeated_capture_without_external_id_creates_distinct_observations(
    monkeypatch, manual_capture_source
):
    from ingestion.models import RawListing

    payload = _valid_payload(title="Same human capture")
    _run_ingest(monkeypatch, payload)
    _run_ingest(monkeypatch, payload)

    rows = RawListing.objects.filter(source=manual_capture_source).order_by("pk")
    assert rows.count() == 2
    assert all(row.external_id is None for row in rows)
    assert rows[0].pk != rows[1].pk


def test_null_rate_limit_completes_without_throttling(
    monkeypatch, manual_capture_source
):
    from ingestion.models import RawListing

    assert manual_capture_source.rate_limit is None

    def fail_if_slept(*args, **kwargs):
        raise AssertionError("rate_limit=None must not cause throttling")

    monkeypatch.setattr(time, "sleep", fail_if_slept)
    _run_ingest(monkeypatch, _valid_payload())

    assert RawListing.objects.filter(source=manual_capture_source).count() == 1


# --- Decimal-only price parsing ---------------------------------------------


@pytest.mark.parametrize(
    "price_text,expected",
    [
        ("15500", Decimal("15500.00")),
        ("15500.00", Decimal("15500.00")),
        ("15,500", Decimal("15500.00")),
        ("15,500.50", Decimal("15500.50")),
        ("0.5", Decimal("0.50")),
        ("0.05", Decimal("0.05")),
        ("  15,500.50  ", Decimal("15500.50")),
        # This loses cents if it travels through an IEEE-754 binary float.
        ("9999999999.99", Decimal("9999999999.99")),
    ],
)
def test_approved_price_grammar_parses_to_exact_decimal(
    monkeypatch, manual_capture_source, price_text, expected
):
    from ingestion.models import RawListing

    _run_ingest(monkeypatch, _valid_payload(price=price_text))

    row = RawListing.objects.get(source=manual_capture_source)
    assert row.raw_price_text == price_text
    assert row.raw_price == expected
    assert isinstance(row.raw_price, Decimal)


@pytest.mark.parametrize(
    "price_text",
    [
        "PM for price",
        "₱15,500",
        "PHP 15,500",
        "15,000-16,000",
        "1e3",
        "-5",
        "12.345",
        "10000000000.00",
        "1,23",
        "NaN",
        "Infinity",
    ],
)
def test_other_nonblank_price_text_succeeds_with_null_decimal(
    monkeypatch, manual_capture_source, price_text
):
    from ingestion.models import RawListing

    _run_ingest(monkeypatch, _valid_payload(price=price_text))

    row = RawListing.objects.get(source=manual_capture_source)
    assert row.raw_price_text == price_text
    assert row.raw_price is None


# --- privacy ----------------------------------------------------------------


def test_seller_column_and_payload_share_the_same_pseudonym(
    monkeypatch, manual_capture_source
):
    from ingestion.models import RawListing

    plaintext = "Juan Dela Cruz"
    _run_ingest(monkeypatch, _valid_payload(seller=plaintext))

    row = RawListing.objects.get(source=manual_capture_source)
    assert row.seller == pseudonymise(plaintext)
    assert row.payload["seller"] == row.seller


def test_plaintext_seller_appears_nowhere_in_persisted_rawlisting(
    monkeypatch, manual_capture_source
):
    from ingestion.models import RawListing

    plaintext = "Maria Santos"
    _run_ingest(
        monkeypatch,
        _valid_payload(
            seller=plaintext,
            url="https://example.invalid/listing/123",
            external_id="listing-123",
        ),
    )

    row = RawListing.objects.get(source=manual_capture_source)
    serialised = json.dumps(
        {
            "raw_title": row.raw_title,
            "raw_price_text": row.raw_price_text,
            "raw_price": str(row.raw_price),
            "url": row.url,
            "seller": row.seller,
            "fetched_at": row.fetched_at.isoformat(),
            "occurred_at": row.occurred_at,
            "external_id": row.external_id,
            "payload": row.payload,
        },
        ensure_ascii=False,
        default=str,
    ).casefold()
    assert plaintext.casefold() not in serialised


@pytest.mark.parametrize("seller", ["", "   ", "\t\n"])
def test_blank_seller_is_treated_as_absent(
    monkeypatch, manual_capture_source, seller
):
    from ingestion.models import RawListing

    _run_ingest(monkeypatch, _valid_payload(seller=seller))

    row = RawListing.objects.get(source=manual_capture_source)
    assert row.seller == ""
    assert "seller" not in row.payload


def test_context_is_rejected_before_write(monkeypatch, db):
    _assert_structural_failure(
        monkeypatch,
        _valid_payload(context={"seller": "Juan Dela Cruz"}),
    )


def test_unknown_pii_bearing_key_is_rejected_before_write(monkeypatch, db):
    _assert_structural_failure(
        monkeypatch,
        _valid_payload(counterparty="Juan Dela Cruz"),
    )


# --- phase boundaries --------------------------------------------------------


def test_capture_writes_no_downstream_or_swap_rows(monkeypatch, db):
    from catalogue.models import Sku, SkuAlias
    from ingestion.models import RawListing, Swap
    from listings.models import Listing
    from outcomes.models import Outcome
    from pricing.models import DealFlag, PricePoint

    _run_ingest(monkeypatch, _valid_payload())

    assert RawListing.objects.count() == 1
    assert Sku.objects.count() == 0
    assert SkuAlias.objects.count() == 0
    assert Listing.objects.count() == 0
    assert PricePoint.objects.count() == 0
    assert DealFlag.objects.count() == 0
    assert Outcome.objects.count() == 0
    assert Swap.objects.count() == 0


def test_success_does_not_update_last_successful_fetch(
    monkeypatch, manual_capture_source
):
    marker = timezone.now() - timedelta(days=2)
    type(manual_capture_source).objects.filter(pk=manual_capture_source.pk).update(
        last_successful_fetch=marker
    )

    _run_ingest(monkeypatch, _valid_payload())

    manual_capture_source.refresh_from_db()
    assert manual_capture_source.last_successful_fetch == marker


def test_structural_failure_does_not_update_last_successful_fetch(
    monkeypatch, manual_capture_source
):
    marker = timezone.now() - timedelta(days=2)
    type(manual_capture_source).objects.filter(pk=manual_capture_source.pk).update(
        last_successful_fetch=marker
    )

    _assert_structural_failure(monkeypatch, _valid_payload(unexpected="value"))

    manual_capture_source.refresh_from_db()
    assert manual_capture_source.last_successful_fetch == marker


def test_rawlisting_created_by_command_remains_database_immutable(
    monkeypatch, manual_capture_source
):
    from ingestion.models import RawListing

    _run_ingest(monkeypatch, _valid_payload())
    row = RawListing.objects.get(source=manual_capture_source)

    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            RawListing.objects.filter(pk=row.pk).update(raw_title="changed")
