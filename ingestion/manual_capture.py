import json
import re
from decimal import Decimal

from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from ingestion.models import RawListing
from ingestion.pseudonymise import redact_payload
from sources.models import Source


ALLOWED_KEYS = frozenset({"title", "price", "url", "seller", "external_id"})
REQUIRED_KEYS = frozenset({"title", "price"})
PRICE_PATTERN = re.compile(
    r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?\Z"
)


def _invalid(message):
    raise CommandError(f"Invalid manual_capture input: {message}")


def _reject_nonstandard_json_constant(value):
    raise ValueError(f"{value} is not valid JSON")


def _load_payload(raw_input):
    try:
        # Decimal here prevents a rejected fractional JSON number becoming a float.
        payload = json.loads(
            raw_input,
            parse_float=Decimal,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise CommandError("Invalid manual_capture input: malformed JSON") from error

    if not isinstance(payload, dict):
        _invalid("top-level JSON value must be an object")

    unknown_keys = payload.keys() - ALLOWED_KEYS
    if unknown_keys:
        _invalid(f"unknown field(s): {', '.join(sorted(unknown_keys))}")

    missing_keys = REQUIRED_KEYS - payload.keys()
    if missing_keys:
        _invalid(f"missing field(s): {', '.join(sorted(missing_keys))}")

    for field_name in REQUIRED_KEYS:
        value = payload[field_name]
        if not isinstance(value, str):
            _invalid(f"{field_name} must be a string")
        if not value.strip():
            _invalid(f"{field_name} must not be blank")

    for field_name in ("url", "seller", "external_id"):
        if field_name in payload and not isinstance(payload[field_name], str):
            _invalid(f"{field_name} must be a string")

    if "external_id" in payload:
        external_id = payload["external_id"]
        if not external_id.strip():
            _invalid("external_id must not be blank")
        max_length = RawListing._meta.get_field("external_id").max_length
        if len(external_id) > max_length:
            _invalid(f"external_id must not exceed {max_length} characters")

    return payload


def _parse_price(price_text):
    candidate = price_text.strip()
    if PRICE_PATTERN.fullmatch(candidate) is None:
        return None

    value = Decimal(candidate.replace(",", ""))
    field = RawListing._meta.get_field("raw_price")
    whole_digit_limit = Decimal(10) ** (field.max_digits - field.decimal_places)
    if not value.is_finite() or value < 0 or value >= whole_digit_limit:
        return None
    return value


def ingest_manual_capture(raw_input):
    supplied_payload = _load_payload(raw_input)
    price = _parse_price(supplied_payload["price"])

    payload_for_storage = dict(supplied_payload)
    seller_text = payload_for_storage.get("seller", "")
    if not seller_text.strip():
        # Blank seller is an unstated fact, matching the personal-record convention.
        payload_for_storage.pop("seller", None)
    redacted_payload = redact_payload(payload_for_storage)
    seller = redacted_payload.get("seller", "")

    # The transaction keeps the immutable fact all-or-nothing with its source lookup.
    with transaction.atomic():
        source = Source.objects.get(name="manual_capture")
        return RawListing.objects.create(
            source=source,
            raw_title=supplied_payload["title"],
            raw_price_text=supplied_payload["price"],
            raw_price=price,
            url=supplied_payload.get("url", ""),
            seller=seller,
            fetched_at=timezone.now(),
            occurred_at=None,
            external_id=supplied_payload.get("external_id"),
            payload=redacted_payload,
        )
