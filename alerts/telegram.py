"""Telegram Bot API transport for alerts.

The only module in this repository allowed to know api.telegram.org, the
Bot API's token-in-the-URL placement, the sendMessage JSON shape, or any
urllib detail. See
tasks/TASK_031_ALERT_PAYLOAD_TELEGRAM_AND_CONFIGURATION.md Section 9.

Security note: the Bot API embeds the bot token in the request URL, so any
exception capable of carrying that URL (HTTPError, URLError, a Request repr,
a formatted traceback) must never remain reachable — as __cause__, as
__context__, or via a raw body/parser exception — from the AlertDeliveryError
raised out of this module. Every branch below classifies the failure into a
safe `reason` string and only raises the sanitized error after leaving the
except block that observed the raw exception, so nothing is "currently being
handled" at the point of the raise and Python attaches neither __cause__ nor
__context__. This shape was verified empirically against this repository's
Python 3.12 runtime (see TASK_031 spec Section 9.5 and the HARDEN notes).
"""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen  # module-level: alerts.telegram.urlopen is the frozen, patchable seam

from alerts.config import AlertConfig
from alerts.delivery import AlertDeliveryError

_ENDPOINT_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT_SECONDS = 10  # exact and explicit — Decision E


def send_telegram_message(config: AlertConfig, text: str) -> None:
    """Send `text` via Telegram's sendMessage. Exactly one request, no retry.

    Raises AlertDeliveryError with a sanitized reason on any failure. Returns
    None on success; the Message result is never returned, stored, or logged
    (Decision G — "sent", not "delivered").
    """
    url = _ENDPOINT_TEMPLATE.format(token=config.telegram_bot_token)
    body = json.dumps({"chat_id": config.telegram_chat_id, "text": text}).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # --- request + read phase --------------------------------------------
    # The read must stay inside this guard: urllib only wraps OSError into
    # URLError around the connect/request phase, so a mid-stream read
    # timeout or reset arrives as a bare exception (spec Section 9.4).
    # Classification order matters because HTTPError ⊂ URLError ⊂ OSError
    # and TimeoutError ⊂ OSError (spec Section 9.3).
    reason = None
    raw_bytes = b""
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            raw_bytes = response.read()
    except HTTPError:
        reason = "api_rejected"
    except TimeoutError:
        reason = "timeout"
    except URLError as exc:
        reason = "timeout" if isinstance(exc.reason, TimeoutError) else "transport_failure"
    except OSError:
        reason = "transport_failure"

    if reason is not None:
        # No exception is active here (we are past every except block), so
        # the raised error's __cause__ and __context__ are both None.
        raise AlertDeliveryError(reason)

    # --- decode phase ------------------------------------------------------
    # Explicit UTF-8 decode, never json.loads(bytes): json.loads
    # auto-detects UTF-16/UTF-32 by BOM sniffing, which would silently
    # accept a non-UTF-8 response (spec Section 9.3.1).
    decode_failed = False
    decoded_text = ""
    try:
        decoded_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        decode_failed = True

    if decode_failed:
        raise AlertDeliveryError("invalid_response")

    # --- parse phase ---------------------------------------------------------
    # JSONDecodeError.doc carries the entire raw response document, so it
    # must never stay attached to what we raise.
    parse_failed = False
    parsed = None
    try:
        parsed = json.loads(decoded_text)
    except json.JSONDecodeError:
        parse_failed = True

    if parse_failed:
        raise AlertDeliveryError("invalid_response")

    # --- response validation (spec Section 9.2) -----------------------------
    if not isinstance(parsed, dict):
        raise AlertDeliveryError("invalid_response")

    # Strict identity check: ok must be exactly Boolean True, never merely
    # truthy (1, "true", "yes", a non-empty list/dict are all rejections).
    if parsed.get("ok") is not True:
        raise AlertDeliveryError("api_rejected")

    if not isinstance(parsed.get("result"), dict):
        raise AlertDeliveryError("invalid_response")

    return None
