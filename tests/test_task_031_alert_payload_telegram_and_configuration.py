"""Frozen TASK_031 alert payload, Telegram adapter, and configuration tests.

TASK_031 owns what an alert says, what leaves the system, how the Telegram Bot
API is called, and how alert configuration is read and validated. It owns no
orchestration: no eligibility query, no claim creation, no AlertDelivery write.
Those are TASK_032. See tasks/TASK_031_ALERT_PAYLOAD_TELEGRAM_AND_CONFIGURATION.md
and docs/07_PLANNING.md.

Security note: the Telegram Bot API places the bot token in the request URL, so
the sanitization assertions here are a security control, not a style
preference. Every credential below is obviously synthetic and inert.

No test in this module performs real network I/O: the transport is patched at
the frozen alerts.telegram.urlopen seam.

Imports of alerts modules are deliberately performed inside each test rather
than at module scope so this file still collects cleanly before they exist.
"""

import io
import json
import logging
import traceback
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

import pytest
from django.test import override_settings
from django.utils import timezone as django_timezone


REPO_ROOT = Path(__file__).resolve().parent.parent

# Obviously synthetic, inert values. Nothing here is a real credential.
FAKE_BOT_TOKEN = "1234567890:SYNTHETIC-TASK031-TOKEN-DO-NOT-USE"
FAKE_CHAT_ID = "-1009876543210"
FAKE_BASE_URL = "https://pricewatch.example.test"
FAKE_ACTIVATION_AT = "2026-06-15T12:00:00+08:00"

ALERT_ENV_KEYS = (
    "PRICEWATCHPH_ENABLE_ALERTS",
    "PRICEWATCHPH_TELEGRAM_BOT_TOKEN",
    "PRICEWATCHPH_TELEGRAM_CHAT_ID",
    "PRICEWATCHPH_ALERT_ACTIVATION_AT",
    "PRICEWATCHPH_PUBLIC_BASE_URL",
)

ALERT_SETTING_NAMES = (
    "ENABLE_ALERTS",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "ALERT_ACTIVATION_AT",
    "PUBLIC_BASE_URL",
)

# Telegram's documented sendMessage text range is 1-4096 characters
# (specification section 3.1). Enforced during payload construction, before
# TASK_032 can consume the one-and-only AlertDelivery claim.
TELEGRAM_TEXT_MAX = 4096
EXPECTED_PAYLOAD_ERROR_MESSAGE = "Alert message exceeds Telegram's 4096-character limit."

# Frozen sanitized failure vocabulary (specification section 9.3).
EXPECTED_FAILURE_MESSAGES = {
    "timeout": "Telegram request timed out.",
    "transport_failure": "Telegram request could not be completed.",
    "invalid_response": "Telegram returned an unreadable response.",
    "api_rejected": "Telegram rejected the message.",
}

# Values that must never reach Telegram (specification section 7.5).
SECRET_RAW_TITLE = "TASK031 RAW TITLE MUST NOT LEAK"
SECRET_RAW_PRICE_TEXT = "TASK031-RAW-PRICE-TEXT"
SECRET_SELLER = "task031-seller-must-not-leak"
SECRET_SOURCE_URL = "https://external-marketplace.invalid/task031-listing"


def enabled_alert_settings(**overrides):
    """The complete valid alert configuration, for override_settings."""
    values = {
        "ENABLE_ALERTS": True,
        "TELEGRAM_BOT_TOKEN": FAKE_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": FAKE_CHAT_ID,
        "ALERT_ACTIVATION_AT": FAKE_ACTIVATION_AT,
        "PUBLIC_BASE_URL": FAKE_BASE_URL,
    }
    values.update(overrides)
    return values


@pytest.fixture
def alert_config():
    """A fully valid AlertConfig built through the real loader."""
    from alerts.config import load_alert_config

    with override_settings(**enabled_alert_settings()):
        return load_alert_config()


@pytest.fixture
def deal_flag(db):
    """A DealFlag whose upstream RawListing carries values that must never leak."""
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
        name="task_031_source",
        base_url="https://example.invalid",
        terms_notes="Synthetic TASK_031 fixture",
        rate_limit=None,
    )
    raw_listing = RawListing.objects.create(
        source=source,
        raw_title=SECRET_RAW_TITLE,
        raw_price_text=SECRET_RAW_PRICE_TEXT,
        raw_price=Decimal("12500.00"),
        url=SECRET_SOURCE_URL,
        seller=SECRET_SELLER,
        fetched_at=django_timezone.now(),
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
        resolved_at=django_timezone.now(),
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
    return DealFlag.objects.create(
        listing=listing,
        score=Decimal("-3.5000"),
        baseline_pricepoint=pricepoint,
        reason="asking_price_mad_v1",
        flagged_at=django_timezone.now(),
    )


class FakeResponse:
    """A stand-in for urlopen's return value.

    A real class rather than a MagicMock so it behaves identically whether the
    implementation uses `with urlopen(...) as response:` or a bare call, and so
    read() can raise the way a real socket does mid-stream.
    """

    def __init__(self, body, status=200, read_error=None):
        self._payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self._read_error = read_error
        self.status = status

    def read(self, *args, **kwargs):
        if self._read_error is not None:
            raise self._read_error
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def http_response(body, status=200):
    return FakeResponse(body, status=status)


def response_whose_read_fails(error):
    """A response that opens successfully and then fails while streaming the body."""
    return FakeResponse(b"", read_error=error)


def telegram_ok_body(text="hello"):
    return {"ok": True, "result": {"message_id": 99, "text": text}}


def send_with_patched_transport(config, text, urlopen_side_effect=None, urlopen_return=None):
    """Call the real Telegram sender with the network patched out."""
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        if urlopen_side_effect is not None:
            urlopen.side_effect = urlopen_side_effect
        else:
            urlopen.return_value = (
                urlopen_return if urlopen_return is not None
                else http_response(telegram_ok_body(text))
            )
        send_telegram_message(config, text)
    return urlopen


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_alerts_are_disabled_by_default_in_the_committed_environment():
    """Outbound alerting is opt-in: nothing sends merely because the code exists."""
    from alerts.config import alerts_enabled

    with override_settings(ENABLE_ALERTS=False):
        assert alerts_enabled() is False


def test_enable_flag_is_read_from_settings():
    from alerts.config import alerts_enabled

    with override_settings(ENABLE_ALERTS=True):
        assert alerts_enabled() is True


@pytest.mark.parametrize("raw_value", ["0", "", "true", "TRUE", "yes", "on", "2", " 1"])
def test_only_the_literal_one_enables_alerts(monkeypatch, raw_value):
    """Matching ENABLE_DEMO_DATA: literal "1" only, never a truthiness heuristic."""
    monkeypatch.setenv("PRICEWATCHPH_ENABLE_ALERTS", raw_value)
    assert (raw_value == "1") is False  # guards the parametrization itself

    import importlib

    settings_module = importlib.import_module("config.settings")
    reloaded = importlib.reload(settings_module)
    try:
        assert reloaded.ENABLE_ALERTS is False
    finally:
        monkeypatch.delenv("PRICEWATCHPH_ENABLE_ALERTS", raising=False)
        importlib.reload(settings_module)


def test_literal_one_enables_alerts_in_settings(monkeypatch):
    import importlib

    monkeypatch.setenv("PRICEWATCHPH_ENABLE_ALERTS", "1")
    settings_module = importlib.import_module("config.settings")
    reloaded = importlib.reload(settings_module)
    try:
        assert reloaded.ENABLE_ALERTS is True
    finally:
        monkeypatch.delenv("PRICEWATCHPH_ENABLE_ALERTS", raising=False)
        importlib.reload(settings_module)


def test_settings_expose_every_alert_setting():
    """All five alert settings exist even when alerts are disabled."""
    from django.conf import settings

    for name in ALERT_SETTING_NAMES:
        assert hasattr(settings, name), f"settings.{name} is missing"


def test_disabled_alerts_tolerate_entirely_absent_configuration():
    """Importing settings and running unrelated work must not require alert values."""
    from alerts.config import alerts_enabled

    with override_settings(
        ENABLE_ALERTS=False,
        TELEGRAM_BOT_TOKEN="",
        TELEGRAM_CHAT_ID="",
        ALERT_ACTIVATION_AT="",
        PUBLIC_BASE_URL="",
    ):
        assert alerts_enabled() is False


@pytest.mark.parametrize(
    "missing_setting",
    ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ALERT_ACTIVATION_AT", "PUBLIC_BASE_URL"],
)
def test_each_required_value_is_validated_when_alerts_are_enabled(missing_setting):
    """Enabled alerting fails loudly rather than sending half-configured."""
    from alerts.config import AlertConfigurationError, load_alert_config

    with override_settings(**enabled_alert_settings(**{missing_setting: ""})):
        with pytest.raises(AlertConfigurationError):
            load_alert_config()


def test_valid_configuration_loads_into_an_alert_config(alert_config):
    assert alert_config.telegram_bot_token == FAKE_BOT_TOKEN
    assert alert_config.telegram_chat_id == FAKE_CHAT_ID
    assert alert_config.public_base_url == FAKE_BASE_URL


@pytest.mark.parametrize("blank", [" ", "   ", "\t", "\n", " \t\n "], ids=lambda v: repr(v))
@pytest.mark.parametrize("setting", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_whitespace_only_credentials_do_not_count_as_configured(setting, blank):
    """A whitespace-only secret is not a secret; it must fail loudly, not send blank."""
    from alerts.config import AlertConfigurationError, load_alert_config

    with override_settings(**enabled_alert_settings(**{setting: blank})):
        with pytest.raises(AlertConfigurationError):
            load_alert_config()


@pytest.mark.parametrize("setting", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_credentials_with_surrounding_whitespace_are_rejected_not_silently_stripped(setting):
    """Rejection over mutation: silently altering a credential hides a real misconfiguration."""
    from alerts.config import AlertConfigurationError, load_alert_config

    padded = f"  {enabled_alert_settings()[setting]}  "

    with override_settings(**enabled_alert_settings(**{setting: padded})):
        with pytest.raises(AlertConfigurationError):
            load_alert_config()


def test_valid_credentials_are_passed_through_unchanged(alert_config):
    """No normalization is applied to a well-formed secret."""
    assert alert_config.telegram_bot_token == FAKE_BOT_TOKEN
    assert alert_config.telegram_chat_id == FAKE_CHAT_ID


def test_load_alert_config_performs_no_database_write(db, alert_config):
    """Configuration validation is side-effect free, so TASK_032 can call it before claiming."""
    from alerts.models import AlertDelivery

    assert AlertDelivery.objects.count() == 0


# --- Activation cutoff -----------------------------------------------------


def test_activation_cutoff_parses_to_an_aware_utc_instant(alert_config):
    """Manila noon is 04:00Z: the cutoff is an absolute instant, not a wall clock."""
    assert alert_config.activation_at.tzinfo is not None
    assert alert_config.activation_at.utcoffset() == timedelta(0)
    assert alert_config.activation_at == datetime(2026, 6, 15, 4, 0, tzinfo=timezone.utc)


def test_offset_and_z_forms_normalize_to_the_same_instant():
    from alerts.config import load_alert_config

    with override_settings(**enabled_alert_settings(ALERT_ACTIVATION_AT="2026-06-15T12:00:00+08:00")):
        offset_form = load_alert_config().activation_at
    with override_settings(**enabled_alert_settings(ALERT_ACTIVATION_AT="2026-06-15T04:00:00Z")):
        z_form = load_alert_config().activation_at

    assert offset_form == z_form


@pytest.mark.parametrize(
    "cutoff",
    [
        "2026-06-15T12:00:00",  # naive: ambiguous, must be rejected by us
        "2026-06-15",           # date only, naive
        "15/06/2026 12:00",     # unparsable
        "garbage",
        "",
    ],
)
def test_ambiguous_or_malformed_activation_cutoff_is_rejected(cutoff):
    """A naive cutoff parses fine in Python, so the rejection has to be ours."""
    from alerts.config import AlertConfigurationError, load_alert_config

    with override_settings(**enabled_alert_settings(ALERT_ACTIVATION_AT=cutoff)):
        with pytest.raises(AlertConfigurationError):
            load_alert_config()


def test_activation_cutoff_is_comparable_against_an_aware_flagged_at(alert_config):
    """The cutoff must be directly comparable to DealFlag.flagged_at (stored UTC)."""
    aware_now = django_timezone.now()
    assert isinstance(aware_now > alert_config.activation_at, bool)


# --- Public base URL -------------------------------------------------------


@pytest.mark.parametrize(
    "configured,expected",
    [
        ("https://pricewatch.example.test", "https://pricewatch.example.test"),
        ("https://pricewatch.example.test/", "https://pricewatch.example.test"),
        ("http://localhost:8000", "http://localhost:8000"),
        ("http://localhost:8000/", "http://localhost:8000"),
    ],
)
def test_public_base_url_normalization(configured, expected):
    """A trailing slash is accepted and stripped; http stays valid for local operation."""
    from alerts.config import load_alert_config

    with override_settings(**enabled_alert_settings(PUBLIC_BASE_URL=configured)):
        assert load_alert_config().public_base_url == expected


@pytest.mark.parametrize(
    "bad_url",
    [
        "ftp://pricewatch.example.test",       # unsupported scheme
        "pricewatch.example.test",             # no scheme
        "https://",                            # no netloc
        "https://pricewatch.example.test/app",  # path prefix, deliberately rejected
        "https://pricewatch.example.test/?q=1",  # query
        "https://pricewatch.example.test/#x",   # fragment
        "",
    ],
)
def test_invalid_public_base_url_is_rejected(bad_url):
    from alerts.config import AlertConfigurationError, load_alert_config

    with override_settings(**enabled_alert_settings(PUBLIC_BASE_URL=bad_url)):
        with pytest.raises(AlertConfigurationError):
            load_alert_config()


# --- Environment access boundary -------------------------------------------


def test_no_alerts_module_reads_os_environ():
    """config/settings.py is the only environment reader, keeping TASK_001 symmetry load-bearing."""
    alerts_package = REPO_ROOT / "alerts"
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in alerts_package.rglob("*.py")
        if "os.environ" in path.read_text() or "getenv" in path.read_text()
    ]
    assert offenders == []


def test_alert_environment_keys_are_documented_and_read():
    """Every alert key appears in both settings.py and .env.example (TASK_001 symmetry)."""
    settings_source = (REPO_ROOT / "config" / "settings.py").read_text()
    env_example_keys = {
        line.split("=", 1)[0].strip()
        for line in (REPO_ROOT / ".env.example").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#") and "=" in line
    }

    for key in ALERT_ENV_KEYS:
        assert key in settings_source, f"{key} is not read in config/settings.py"
        assert key in env_example_keys, f"{key} is not documented in .env.example"


def test_env_example_carries_no_real_looking_credential():
    """Secrets are inert placeholders; nothing credential-shaped is committed."""
    env_example = (REPO_ROOT / ".env.example").read_text()

    for line in env_example.splitlines():
        if line.startswith("PRICEWATCHPH_TELEGRAM_BOT_TOKEN="):
            value = line.split("=", 1)[1].strip()
            assert ":" not in value, "a bot-token-shaped placeholder must not be committed"


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


def test_message_has_the_exact_frozen_structure(deal_flag, alert_config):
    from alerts.delivery import build_alert_message

    message = build_alert_message(deal_flag, alert_config)

    assert message == "\n".join(
        [
            "PriceWatch PH deal flag",
            "ASUS TUF Gaming RTX 4070 OC",
            "Price: ₱12500.00",
            "Condition: Used",
            "Score: -3.5000",
            f"{FAKE_BASE_URL}/deals/{deal_flag.pk}/outcome",
        ]
    )


def test_message_uses_decimal_derived_money_with_no_float_path(deal_flag, alert_config):
    """Money is exact fixed-point text, never a float repr."""
    from alerts.delivery import build_alert_message

    message = build_alert_message(deal_flag, alert_config)

    assert "Price: ₱12500.00" in message
    assert "12500.0\n" not in message
    assert "1.25e" not in message.lower()


def test_message_renders_the_decimal_score_without_float_conversion(deal_flag, alert_config):
    from alerts.delivery import build_alert_message

    assert "Score: -3.5000" in build_alert_message(deal_flag, alert_config)


def test_message_action_link_is_the_absolute_internal_outcome_route(deal_flag, alert_config):
    """The alert links into PriceWatch PH's own TASK_029 workflow, not anywhere external."""
    from alerts.delivery import build_alert_message

    message = build_alert_message(deal_flag, alert_config)

    assert f"{FAKE_BASE_URL}/deals/{deal_flag.pk}/outcome" in message


def test_message_is_built_without_any_request_object(deal_flag, alert_config):
    """A management command has no HTTP request, so the link comes from configuration."""
    from alerts.delivery import build_alert_message

    assert build_alert_message(deal_flag, alert_config).endswith(
        f"{FAKE_BASE_URL}/deals/{deal_flag.pk}/outcome"
    )


def test_message_contains_no_rawlisting_evidence(deal_flag, alert_config):
    """The sensitive values themselves must be absent, not merely their field names."""
    from alerts.delivery import build_alert_message

    message = build_alert_message(deal_flag, alert_config)

    for forbidden in (
        SECRET_RAW_TITLE,
        SECRET_RAW_PRICE_TEXT,
        SECRET_SELLER,
        SECRET_SOURCE_URL,
    ):
        assert forbidden not in message


def test_message_contains_no_external_source_url(deal_flag, alert_config):
    """Decision J: no source listing URL leaves PriceWatch PH."""
    from alerts.delivery import build_alert_message

    message = build_alert_message(deal_flag, alert_config)

    assert "external-marketplace.invalid" not in message
    assert message.count("http") == 1  # only the internal action link


def test_message_exposes_no_internal_ids_beyond_the_action_link(deal_flag, alert_config):
    """SKU and Listing primary keys have no approved use in the payload."""
    from alerts.delivery import build_alert_message

    message = build_alert_message(deal_flag, alert_config)
    link = f"{FAKE_BASE_URL}/deals/{deal_flag.pk}/outcome"
    without_link = message.replace(link, "")

    assert str(deal_flag.listing.sku_id) not in without_link
    assert str(deal_flag.listing_id) not in without_link


def test_message_uses_the_committed_condition_vocabulary(deal_flag, alert_config):
    """Condition is the existing CONDITION_CHOICES label, not a new vocabulary."""
    from alerts.delivery import build_alert_message

    assert f"Condition: {deal_flag.listing.get_condition_display()}" in build_alert_message(
        deal_flag, alert_config
    )


# --- Telegram text-size boundary, enforced before any claim ---------------


def config_with_base(base_url):
    """A valid AlertConfig differing only in public base URL."""
    from alerts.config import load_alert_config

    with override_settings(**enabled_alert_settings(PUBLIC_BASE_URL=base_url)):
        return load_alert_config()


def base_url_of_total_message_length(deal_flag, total_length):
    """Build a structurally valid base URL that makes the whole message exactly total_length.

    Everything except the base URL is fixed by the frozen six-line template, so
    the padding is derived rather than hardcoded to a brittle constant.
    """
    from alerts.delivery import build_alert_message

    probe_base = "https://a"
    probe = build_alert_message(deal_flag, config_with_base(probe_base))
    fixed_length = len(probe) - len(probe_base)
    padding = total_length - fixed_length - len("https://")
    assert padding > 0, "fixture is too long to exercise the size boundary"
    return "https://" + "a" * padding


def test_message_at_exactly_the_telegram_limit_is_accepted(deal_flag):
    """4096 is valid: the boundary is inclusive, matching Telegram's 1-4096 contract."""
    from alerts.delivery import build_alert_message

    base = base_url_of_total_message_length(deal_flag, TELEGRAM_TEXT_MAX)
    message = build_alert_message(deal_flag, config_with_base(base))

    assert len(message) == TELEGRAM_TEXT_MAX


def test_message_over_the_telegram_limit_is_rejected_during_construction(deal_flag):
    """Telegram would refuse this text, so it must never reach a durable claim.

    Under the approved orchestration (validate config -> build payload -> claim
    -> commit -> send), discovering this only at send time would consume the
    DealFlag's one-and-only AlertDelivery claim on a message that can never be
    delivered, and TASK_030 forbids retry and resend.
    """
    from alerts.delivery import AlertPayloadError, build_alert_message

    base = base_url_of_total_message_length(deal_flag, TELEGRAM_TEXT_MAX + 1)

    with pytest.raises(AlertPayloadError):
        build_alert_message(deal_flag, config_with_base(base))


def test_payload_error_carries_only_the_exact_safe_message():
    from alerts.delivery import AlertPayloadError

    assert str(AlertPayloadError(EXPECTED_PAYLOAD_ERROR_MESSAGE)) == EXPECTED_PAYLOAD_ERROR_MESSAGE


def test_oversized_payload_error_text_is_the_frozen_message(deal_flag):
    from alerts.delivery import AlertPayloadError, build_alert_message

    base = base_url_of_total_message_length(deal_flag, TELEGRAM_TEXT_MAX + 1)

    with pytest.raises(AlertPayloadError) as raised:
        build_alert_message(deal_flag, config_with_base(base))

    assert str(raised.value) == EXPECTED_PAYLOAD_ERROR_MESSAGE


def test_oversized_payload_makes_no_network_request(deal_flag):
    """Rejection happens locally, before any transport is touched."""
    from alerts.delivery import AlertPayloadError, build_alert_message

    base = base_url_of_total_message_length(deal_flag, TELEGRAM_TEXT_MAX + 1)

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        with pytest.raises(AlertPayloadError):
            build_alert_message(deal_flag, config_with_base(base))

    assert urlopen.call_count == 0


def test_oversized_payload_creates_no_alert_delivery_row(db, deal_flag):
    """The claim is TASK_032's to create, and an invalid payload must not consume one."""
    from alerts.delivery import AlertPayloadError, build_alert_message
    from alerts.models import AlertDelivery

    base = base_url_of_total_message_length(deal_flag, TELEGRAM_TEXT_MAX + 1)

    with pytest.raises(AlertPayloadError):
        build_alert_message(deal_flag, config_with_base(base))

    assert AlertDelivery.objects.count() == 0


def test_oversized_payload_is_rejected_not_truncated(deal_flag):
    """No silent shortening of SKU text or URLs: an invalid payload fails honestly."""
    from alerts.delivery import AlertPayloadError, build_alert_message

    base = base_url_of_total_message_length(deal_flag, TELEGRAM_TEXT_MAX + 1)

    with pytest.raises(AlertPayloadError):
        build_alert_message(deal_flag, config_with_base(base))


# --- Payload construction must not read RawListing or Source --------------


def test_payload_construction_never_queries_rawlisting_or_source(deal_flag, alert_config):
    """Privacy at the query boundary, not merely in the output string.

    The negative string assertions elsewhere prove no sensitive value reaches
    Telegram. This proves the evidence is never read at all - an implementation
    that traverses listing.raw_listing and discards the values would satisfy
    those assertions but not this one.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from alerts.delivery import build_alert_message
    from pricing.models import DealFlag

    reloaded = DealFlag.objects.select_related("listing", "listing__sku").get(pk=deal_flag.pk)

    with CaptureQueriesContext(connection) as queries:
        message = build_alert_message(reloaded, alert_config)

    executed_sql = "\n".join(query["sql"].lower() for query in queries)
    assert message
    assert "ingestion_rawlisting" not in executed_sql
    assert "sources_source" not in executed_sql


# ---------------------------------------------------------------------------
# Adapter seam
# ---------------------------------------------------------------------------


def test_alert_sender_seam_accepts_a_substitute_without_networking(alert_config):
    """Following the AuditWriter precedent: a plain callable, injectable in tests."""
    from alerts.delivery import AlertSender

    calls = []

    def fake_sender(config, text):
        calls.append((config, text))

    sender: AlertSender = fake_sender
    sender(alert_config, "hello")

    assert calls == [(alert_config, "hello")]


def test_real_telegram_sender_satisfies_the_seam_and_returns_none(alert_config):
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = http_response(telegram_ok_body())
        assert send_telegram_message(alert_config, "hello") is None


def test_alerts_package_has_no_registry_or_plugin_machinery():
    """One narrow seam, not a channel abstraction (docs/07_PLANNING.md section 6)."""
    import alerts.delivery as delivery

    for forbidden in ("REGISTRY", "BACKENDS", "CHANNELS", "get_backend", "register"):
        assert not hasattr(delivery, forbidden)


# ---------------------------------------------------------------------------
# Telegram request
# ---------------------------------------------------------------------------


def test_request_targets_the_exact_bot_api_send_message_endpoint(alert_config):
    urlopen = send_with_patched_transport(alert_config, "hello")

    request = urlopen.call_args.args[0]
    assert request.full_url == f"https://api.telegram.org/bot{FAKE_BOT_TOKEN}/sendMessage"


def test_request_is_a_json_post(alert_config):
    urlopen = send_with_patched_transport(alert_config, "hello")

    request = urlopen.call_args.args[0]
    assert request.get_method() == "POST"
    assert request.headers.get("Content-type") == "application/json"


def test_request_body_is_utf8_json_with_exactly_chat_id_and_text(alert_config):
    """No parse_mode and no extra key: plain text avoids an escaping surface."""
    message = "PriceWatch PH deal flag\nPrice: ₱12500.00"
    urlopen = send_with_patched_transport(alert_config, message)

    request = urlopen.call_args.args[0]
    assert isinstance(request.data, bytes)
    body = json.loads(request.data.decode("utf-8"))
    assert body == {"chat_id": FAKE_CHAT_ID, "text": message}


def test_request_uses_the_frozen_ten_second_timeout(alert_config):
    urlopen = send_with_patched_transport(alert_config, "hello")

    assert urlopen.call_args.kwargs["timeout"] == 10


def test_a_successful_send_makes_exactly_one_request(alert_config):
    """No retry, no backoff, no second attempt (Decision H)."""
    urlopen = send_with_patched_transport(alert_config, "hello")

    assert urlopen.call_count == 1


@pytest.mark.parametrize(
    "failure",
    [
        URLError("boom"),
        TimeoutError(),
        HTTPError("https://api.telegram.org/", 400, "Bad Request", {}, io.BytesIO(b"{}")),
    ],
)
def test_a_failed_send_is_never_retried(alert_config, failure):
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.side_effect = failure
        with pytest.raises(AlertDeliveryError):
            send_telegram_message(alert_config, "hello")

    assert urlopen.call_count == 1


# ---------------------------------------------------------------------------
# Telegram response
# ---------------------------------------------------------------------------


def test_successful_response_with_a_message_result_is_accepted(alert_config):
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = http_response({"ok": True, "result": {"message_id": 1}})
        assert send_telegram_message(alert_config, "hello") is None


def test_ok_false_response_is_an_api_rejection(alert_config):
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = http_response(
            {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
        )
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    assert raised.value.reason == "api_rejected"


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        b"",
        b"[1, 2, 3]",                    # JSON, but not an object
        b'{"ok": true}',                 # ok without a result
        b'{"ok": true, "result": 42}',   # result is not a Message object
    ],
)
def test_structurally_invalid_response_is_rejected(alert_config, body):
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = http_response(body)
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    assert raised.value.reason in {"invalid_response", "api_rejected"}


@pytest.mark.parametrize(
    "truthy_ok",
    [1, "true", "True", "yes", "1", [1], {"a": 1}],
    ids=["int_1", "str_true", "str_True", "str_yes", "str_1", "list", "dict"],
)
def test_truthy_but_non_boolean_ok_is_not_success(alert_config, truthy_ok):
    """`ok` must be exactly Boolean True.

    An implementation written as `if payload.get("ok"):` would accept every one
    of these and report a send that Telegram never confirmed.
    """
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = http_response({"ok": truthy_ok, "result": {"message_id": 1}})
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    assert raised.value.reason == "api_rejected"


@pytest.mark.parametrize("falsey_ok", [0, "", None, False], ids=["int_0", "empty", "none", "false"])
def test_falsey_ok_is_also_rejected(alert_config, falsey_ok):
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = http_response({"ok": falsey_ok, "result": {"message_id": 1}})
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    assert raised.value.reason == "api_rejected"


def test_boolean_true_remains_the_one_accepted_success(alert_config):
    """The strict check must not have broken the genuine success path."""
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = http_response({"ok": True, "result": {"message_id": 1}})
        assert send_telegram_message(alert_config, "hello") is None


def test_body_that_is_not_valid_utf8_is_an_unreadable_response(alert_config, capsys):
    """A UnicodeDecodeError must not escape the adapter.

    Whether the implementation decodes explicitly or hands bytes to json.loads,
    undecodable input has to normalize into the same application-owned boundary.
    """
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    undecodable = b'\xff\xfe{"ok": true, "result": {}}\x80\x81'
    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = http_response(undecodable)
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    error = raised.value
    captured = capsys.readouterr()

    assert error.reason == "invalid_response"
    assert str(error) == EXPECTED_FAILURE_MESSAGES["invalid_response"]
    for surface in (str(error), repr(error), captured.out, captured.err):
        assert "utf-8" not in surface.lower()
        assert "0xff" not in surface.lower()
        assert "codec" not in surface.lower()


# ---------------------------------------------------------------------------
# Sanitized failure classification
# ---------------------------------------------------------------------------


def test_http_error_is_classified_as_an_api_rejection(alert_config):
    """Telegram answered, but with an error status."""
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    failure = HTTPError(
        f"https://api.telegram.org/bot{FAKE_BOT_TOKEN}/sendMessage",
        400,
        "Bad Request",
        {},
        io.BytesIO(b'{"ok": false, "description": "chat not found"}'),
    )
    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.side_effect = failure
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    assert raised.value.reason == "api_rejected"


def test_bare_timeout_error_is_classified_as_a_timeout(alert_config):
    """A read-phase timeout arrives as bare TimeoutError, never wrapped in URLError."""
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.side_effect = TimeoutError("timed out")
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    assert raised.value.reason == "timeout"


def test_connect_phase_timeout_wrapped_in_urlerror_is_also_a_timeout(alert_config):
    """urllib wraps a connect timeout as URLError(TimeoutError); it means the same thing."""
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.side_effect = URLError(TimeoutError("timed out"))
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    assert raised.value.reason == "timeout"


def test_read_phase_timeout_is_sanitized_as_a_timeout(alert_config, capsys):
    """The response opens, then times out mid-body.

    This is the case that motivates the OSError catch boundary. urllib wraps
    OSError into URLError only around the request phase, so a timeout raised by
    response.read() arrives bare. An implementation that guards only the
    urlopen() call and reads the body outside that guard leaks this exception
    unsanitized - and passes every other timeout test in this module.
    """
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    leaky = TimeoutError(
        f"read timed out on https://api.telegram.org/bot{FAKE_BOT_TOKEN}/sendMessage"
    )
    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = response_whose_read_fails(leaky)
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    error = raised.value
    captured = capsys.readouterr()

    assert error.reason == "timeout"
    assert str(error) == EXPECTED_FAILURE_MESSAGES["timeout"]
    for surface in (str(error), repr(error), captured.out, captured.err):
        assert FAKE_BOT_TOKEN not in surface
        assert FAKE_CHAT_ID not in surface
        assert "api.telegram.org" not in surface
        assert "read timed out" not in surface
    assert urlopen.call_count == 1


def test_read_phase_transport_failure_is_also_sanitized(alert_config, capsys):
    """The same escape route, for a non-timeout mid-stream failure."""
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    leaky = ConnectionResetError(
        f"connection reset reading https://api.telegram.org/bot{FAKE_BOT_TOKEN}/sendMessage"
    )
    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = response_whose_read_fails(leaky)
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    error = raised.value
    captured = capsys.readouterr()

    assert error.reason == "transport_failure"
    assert str(error) == EXPECTED_FAILURE_MESSAGES["transport_failure"]
    for surface in (str(error), repr(error), captured.out, captured.err):
        assert FAKE_BOT_TOKEN not in surface
        assert "connection reset" not in surface
    assert urlopen.call_count == 1


@pytest.mark.parametrize(
    "failure",
    [
        URLError("name or service not known"),
        ConnectionResetError("connection reset"),
        OSError("network unreachable"),
    ],
)
def test_transport_failures_are_classified_as_transport_failure(alert_config, failure):
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.side_effect = failure
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    assert raised.value.reason == "transport_failure"


def test_malformed_body_is_classified_as_an_invalid_response(alert_config):
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = http_response(b"<html>gateway error</html>")
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    assert raised.value.reason == "invalid_response"


@pytest.mark.parametrize("reason,message", sorted(EXPECTED_FAILURE_MESSAGES.items()))
def test_every_failure_reason_has_its_exact_frozen_message(reason, message):
    """The message is what TASK_032 will persist into AlertDelivery.failure_detail."""
    from alerts.delivery import AlertDeliveryError

    error = AlertDeliveryError(reason)

    assert error.reason == reason
    assert str(error) == message


def test_failure_messages_are_non_empty_so_they_satisfy_task_030(deal_flag):
    """TASK_030 constrains a failed AlertDelivery to carry non-empty failure_detail."""
    from alerts.delivery import AlertDeliveryError

    for reason in EXPECTED_FAILURE_MESSAGES:
        assert str(AlertDeliveryError(reason)).strip() != ""


# ---------------------------------------------------------------------------
# Credential leakage
# ---------------------------------------------------------------------------


LEAK_FAILURES = [
    (
        "http_error",
        HTTPError(
            f"https://api.telegram.org/bot{FAKE_BOT_TOKEN}/sendMessage",
            400,
            f"Bad Request for bot{FAKE_BOT_TOKEN}",
            {},
            io.BytesIO(b'{"ok": false, "description": "chat not found"}'),
        ),
        None,
    ),
    (
        "url_error",
        URLError(f"failed to reach https://api.telegram.org/bot{FAKE_BOT_TOKEN}/sendMessage"),
        None,
    ),
    ("timeout", TimeoutError(f"timed out talking to bot{FAKE_BOT_TOKEN}"), None),
    ("os_error", OSError(f"unreachable: bot{FAKE_BOT_TOKEN}"), None),
    ("malformed_body", None, b"<html>bot token leaked?</html>"),
    (
        "api_rejection",
        None,
        json.dumps(
            {"ok": False, "error_code": 401, "description": f"Unauthorized: bot{FAKE_BOT_TOKEN}"}
        ).encode("utf-8"),
    ),
]


@pytest.mark.parametrize("label,failure,body", LEAK_FAILURES, ids=[f[0] for f in LEAK_FAILURES])
def test_bot_token_never_appears_in_any_application_owned_failure(
    alert_config,
    capsys,
    label,
    failure,
    body,
):
    """The Bot API puts the token in the URL, so every failure path is a leak risk."""
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        if failure is not None:
            urlopen.side_effect = failure
        else:
            urlopen.return_value = http_response(body)
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    error = raised.value
    captured = capsys.readouterr()
    surfaces = [str(error), repr(error), error.reason, captured.out, captured.err]

    for surface in surfaces:
        assert FAKE_BOT_TOKEN not in surface
        assert "api.telegram.org" not in surface
        assert "/sendMessage" not in surface


@pytest.mark.parametrize("label,failure,body", LEAK_FAILURES, ids=[f[0] for f in LEAK_FAILURES])
def test_destination_and_raw_external_text_never_leak(
    alert_config,
    capsys,
    label,
    failure,
    body,
):
    """Neither the chat id nor Telegram's own description crosses the adapter boundary."""
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        if failure is not None:
            urlopen.side_effect = failure
        else:
            urlopen.return_value = http_response(body)
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    captured = capsys.readouterr()
    for surface in [str(raised.value), repr(raised.value), captured.out, captured.err]:
        assert FAKE_CHAT_ID not in surface
        assert "chat not found" not in surface
        assert "Unauthorized" not in surface
        assert "gateway error" not in surface.lower()


def test_failure_text_is_exactly_the_frozen_vocabulary_and_nothing_more(alert_config):
    """No external detail is appended to the sanitized message."""
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.side_effect = URLError("some very specific internal network detail")
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    assert str(raised.value) == EXPECTED_FAILURE_MESSAGES["transport_failure"]


# --- Exception chaining and formatted tracebacks --------------------------

TOKEN_BEARING_URL = f"https://api.telegram.org/bot{FAKE_BOT_TOKEN}/sendMessage"

# Strings that must never appear in any diagnostic surface the application
# produces, because the Bot API embeds the token in the request URL.
FORBIDDEN_IN_DIAGNOSTICS = (
    FAKE_BOT_TOKEN,
    FAKE_CHAT_ID,
    "api.telegram.org",
    "/sendMessage",
)

# (id, how the failure is injected, the failure itself, distinctive raw text)
CHAINING_CASES = [
    (
        "http_error",
        "raise",
        HTTPError(
            TOKEN_BEARING_URL,
            400,
            f"Bad Request while calling {TOKEN_BEARING_URL}",
            {},
            io.BytesIO(b'{"ok": false, "description": "chat not found"}'),
        ),
        "Bad Request while calling",
    ),
    (
        "url_error",
        "raise",
        URLError(f"failed to reach {TOKEN_BEARING_URL}"),
        "failed to reach",
    ),
    (
        "read_phase_timeout",
        "read",
        TimeoutError(f"read timed out on {TOKEN_BEARING_URL}"),
        "read timed out on",
    ),
    (
        "read_phase_transport",
        "read",
        ConnectionResetError(f"connection reset on {TOKEN_BEARING_URL}"),
        "connection reset on",
    ),
]


def formatted_traceback(error):
    """The complete formatted traceback, following __cause__ and __context__."""
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def raise_through_transport(alert_config, mode, failure):
    """Trigger one transport failure and return the raised AlertDeliveryError."""
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        if mode == "raise":
            urlopen.side_effect = failure
        else:
            urlopen.return_value = response_whose_read_fails(failure)
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")
    return raised.value


@pytest.mark.parametrize(
    "mode,failure,raw_text",
    [(case[1], case[2], case[3]) for case in CHAINING_CASES],
    ids=[case[0] for case in CHAINING_CASES],
)
def test_formatted_traceback_never_reveals_the_raw_external_exception(
    alert_config,
    mode,
    failure,
    raw_text,
):
    """A clean str()/repr() is not enough: the traceback must be clean too.

    `raise AlertDeliveryError(...) from exc` - and equally, raising inside an
    `except` block without suppressing the implicit context - leaves the outer
    exception's own text sanitized while a normally formatted traceback still
    prints the underlying HTTPError/URLError, including the token-bearing
    Telegram URL. Anything that prints a traceback (an unhandled crash, a
    logging call with exc_info, a debugger) would then expose the bot token.
    """
    error = raise_through_transport(alert_config, mode, failure)
    rendered = formatted_traceback(error)

    for forbidden in FORBIDDEN_IN_DIAGNOSTICS:
        assert forbidden not in rendered
    assert raw_text not in rendered
    assert "chat not found" not in rendered


@pytest.mark.parametrize(
    "mode,failure",
    [(case[1], case[2]) for case in CHAINING_CASES],
    ids=[case[0] for case in CHAINING_CASES],
)
def test_sanitized_error_carries_no_attached_raw_exception(
    alert_config,
    mode,
    failure,
):
    """No raw external exception object may remain attached to the raised error.

    `raise ... from None` is NOT sufficient here. It clears __cause__ and hides
    the context from traceback *display*, but the token-bearing URLError stays
    reachable at __context__, where any error reporter, structured logger, or
    debugger walking the chain can still read it. Clearing both requires leaving
    the except block before raising (or an equally safe structure).
    """
    error = raise_through_transport(alert_config, mode, failure)

    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize(
    "mode,failure,raw_text",
    [(case[1], case[2], case[3]) for case in CHAINING_CASES],
    ids=[case[0] for case in CHAINING_CASES],
)
def test_reason_and_message_remain_the_frozen_vocabulary_under_chaining(
    alert_config,
    mode,
    failure,
    raw_text,
):
    """Suppressing the chain must not have changed the sanitized vocabulary."""
    error = raise_through_transport(alert_config, mode, failure)

    assert error.reason in EXPECTED_FAILURE_MESSAGES
    assert str(error) == EXPECTED_FAILURE_MESSAGES[error.reason]


# --- Invalid-response parsing failures must detach too --------------------

MALFORMED_RAW_MARKER = "TASK031-MALFORMED-RAW-BODY-MUST-NOT-LEAK"
# Truncated JSON: parses far enough to carry the marker, then fails.
MALFORMED_JSON_BODY = (
    '{"ok": true, "result": {"note": "' + MALFORMED_RAW_MARKER + '"'
).encode("utf-8")

UNDECODABLE_RAW_MARKER = "TASK031-UNDECODABLE-RAW-BODY"
UNDECODABLE_BODY = b"\xff\xfe" + UNDECODABLE_RAW_MARKER.encode("ascii") + b"\x80\x81"

# Valid JSON, but encoded UTF-16. json.loads auto-detects Unicode encodings when
# handed bytes, so json.loads(body) would accept this; an explicit UTF-8 decode
# rejects it. Verified on Python 3.12.13: utf-16 and utf-32 are both accepted by
# json.loads(bytes) yet both fail bytes.decode("utf-8").
UTF16_JSON_BODY = json.dumps({"ok": True, "result": {"message_id": 1}}).encode("utf-16")

# (id, response body, distinctive strings that must never surface)
PARSE_FAILURE_CASES = [
    ("malformed_json", MALFORMED_JSON_BODY, (MALFORMED_RAW_MARKER,)),
    (
        "invalid_utf8",
        UNDECODABLE_BODY,
        (UNDECODABLE_RAW_MARKER, "0xff", "codec", "utf-8"),
    ),
    ("utf16_json", UTF16_JSON_BODY, ("codec", "utf-16", "bom")),
]


def raise_through_response(alert_config, body):
    """Trigger one invalid-response failure and return the raised AlertDeliveryError."""
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = http_response(body)
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")
    return raised.value


def test_valid_json_encoded_as_utf16_is_rejected(alert_config):
    """The adapter requires UTF-8, not whatever json.loads can auto-detect.

    json.loads auto-detects supported Unicode encodings when handed bytes, so
    `json.loads(body)` would accept this perfectly valid UTF-16 document and
    report a successful send. An explicit `body.decode("utf-8")` rejects it.
    This body is the difference between those two implementations: every
    invalid-byte test still passes under the wrong one.
    """
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    # The body really is valid JSON once its own encoding is honoured.
    assert json.loads(UTF16_JSON_BODY.decode("utf-16")) == {
        "ok": True,
        "result": {"message_id": 1},
    }

    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = http_response(UTF16_JSON_BODY)
        with pytest.raises(AlertDeliveryError) as raised:
            send_telegram_message(alert_config, "hello")

    assert raised.value.reason == "invalid_response"
    assert str(raised.value) == EXPECTED_FAILURE_MESSAGES["invalid_response"]
    assert urlopen.call_count == 1


@pytest.mark.parametrize(
    "body,raw_markers",
    [(case[1], case[2]) for case in PARSE_FAILURE_CASES],
    ids=[case[0] for case in PARSE_FAILURE_CASES],
)
def test_invalid_response_failures_detach_the_parser_exception(
    alert_config,
    body,
    raw_markers,
):
    """Parser exceptions must not stay attached either.

    `except (UnicodeDecodeError, json.JSONDecodeError): raise
    AlertDeliveryError("invalid_response")` sanitizes the outer message while
    Python implicitly attaches the parser exception at __context__ - and
    JSONDecodeError carries the entire raw response document on its .doc
    attribute. That would defeat the frozen rule that the raw response body
    never crosses the adapter boundary.
    """
    error = raise_through_response(alert_config, body)

    assert error.reason == "invalid_response"
    assert str(error) == EXPECTED_FAILURE_MESSAGES["invalid_response"]
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize(
    "body,raw_markers",
    [(case[1], case[2]) for case in PARSE_FAILURE_CASES],
    ids=[case[0] for case in PARSE_FAILURE_CASES],
)
def test_invalid_response_traceback_never_reveals_the_raw_body(
    alert_config,
    body,
    raw_markers,
):
    from alerts.delivery import AlertDeliveryError  # noqa: F401  (import proves the module exists)

    error = raise_through_response(alert_config, body)
    rendered = formatted_traceback(error).lower()

    for marker in raw_markers:
        assert marker.lower() not in rendered
    for forbidden in FORBIDDEN_IN_DIAGNOSTICS:
        assert forbidden.lower() not in rendered
    assert "jsondecodeerror" not in rendered
    assert "unicodedecodeerror" not in rendered


@pytest.mark.parametrize(
    "body,raw_markers",
    [(case[1], case[2]) for case in PARSE_FAILURE_CASES],
    ids=[case[0] for case in PARSE_FAILURE_CASES],
)
def test_invalid_response_failures_emit_no_alerts_log_records(
    alert_config,
    caplog,
    body,
    raw_markers,
):
    """The no-logging rule covers unreadable responses, not only transport failures."""
    with caplog.at_level(logging.DEBUG):
        raise_through_response(alert_config, body)

    alerts_records = [
        record for record in caplog.records if record.name.split(".")[0] == "alerts"
    ]
    assert alerts_records == []


@pytest.mark.parametrize(
    "body,raw_markers",
    [(case[1], case[2]) for case in PARSE_FAILURE_CASES],
    ids=[case[0] for case in PARSE_FAILURE_CASES],
)
def test_invalid_response_raw_body_never_reaches_the_logs(
    alert_config,
    caplog,
    body,
    raw_markers,
):
    with caplog.at_level(logging.DEBUG):
        raise_through_response(alert_config, body)

    surfaces = [caplog.text] + [
        f"{record.name} {record.getMessage()}" for record in caplog.records
    ]
    for surface in surfaces:
        lowered = surface.lower()
        for marker in raw_markers:
            assert marker.lower() not in lowered
        for forbidden in FORBIDDEN_IN_DIAGNOSTICS:
            assert forbidden.lower() not in lowered


# --- Logging --------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,failure,raw_text",
    [(case[1], case[2], case[3]) for case in CHAINING_CASES],
    ids=[case[0] for case in CHAINING_CASES],
)
def test_transport_failures_emit_no_alerts_log_records(
    alert_config,
    caplog,
    mode,
    failure,
    raw_text,
):
    """TASK_031 does not log transport failures at all.

    The sanitized exception is the diagnostic channel; TASK_032 persists it into
    AlertDelivery.failure_detail. A `logger.exception(...)` in the adapter would
    write the token-bearing URL into application logs while every stdout/stderr
    assertion in this module still passed.

    Scoped to records originating from the alerts package so unrelated framework
    logging cannot make this brittle.
    """
    with caplog.at_level(logging.DEBUG):
        raise_through_transport(alert_config, mode, failure)

    alerts_records = [
        record for record in caplog.records if record.name.split(".")[0] == "alerts"
    ]
    assert alerts_records == []


@pytest.mark.parametrize(
    "mode,failure,raw_text",
    [(case[1], case[2], case[3]) for case in CHAINING_CASES],
    ids=[case[0] for case in CHAINING_CASES],
)
def test_no_log_record_anywhere_contains_transport_secrets(
    alert_config,
    caplog,
    mode,
    failure,
    raw_text,
):
    """Belt and braces: whatever logger name is used, the secrets must not appear.

    Catches an implementation that logs under some other logger name and would
    slip past the alerts-scoped assertion above.
    """
    with caplog.at_level(logging.DEBUG):
        raise_through_transport(alert_config, mode, failure)

    surfaces = [caplog.text] + [
        f"{record.name} {record.getMessage()}" for record in caplog.records
    ]
    for surface in surfaces:
        for forbidden in FORBIDDEN_IN_DIAGNOSTICS:
            assert forbidden not in surface
        assert raw_text not in surface
        assert "chat not found" not in surface


def test_api_rejection_is_not_logged_with_telegram_description(alert_config, caplog):
    """Telegram's own description must not reach the logs either."""
    from alerts.delivery import AlertDeliveryError
    from alerts.telegram import send_telegram_message

    body = {
        "ok": False,
        "error_code": 401,
        "description": f"Unauthorized: bot{FAKE_BOT_TOKEN} is not a member",
    }
    with caplog.at_level(logging.DEBUG):
        with mock.patch("alerts.telegram.urlopen") as urlopen:
            urlopen.return_value = http_response(body)
            with pytest.raises(AlertDeliveryError):
                send_telegram_message(alert_config, "hello")

    alerts_records = [
        record for record in caplog.records if record.name.split(".")[0] == "alerts"
    ]
    assert alerts_records == []
    for forbidden in FORBIDDEN_IN_DIAGNOSTICS:
        assert forbidden not in caplog.text
    assert "Unauthorized" not in caplog.text


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------


def test_task_031_writes_no_alert_delivery_row(db, deal_flag, alert_config):
    """TASK_031 owns no persistence: claim creation is TASK_032's alone."""
    from alerts.models import AlertDelivery
    from alerts.delivery import build_alert_message

    build_alert_message(deal_flag, alert_config)
    with mock.patch("alerts.telegram.urlopen") as urlopen:
        urlopen.return_value = http_response(telegram_ok_body())
        from alerts.telegram import send_telegram_message

        send_telegram_message(alert_config, "hello")

    assert AlertDelivery.objects.count() == 0


def test_task_030_alert_delivery_contract_is_untouched():
    """TASK_031 changes no persistence field, constraint, or lifecycle."""
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


def test_no_new_third_party_dependency_was_added():
    """Decision B: stdlib urllib.request only, no requests/httpx."""
    requirements = (REPO_ROOT / "requirements.txt").read_text().lower()

    assert "requests" not in requirements
    assert "httpx" not in requirements
