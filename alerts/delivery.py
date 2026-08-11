"""Alert payload construction and the injectable sender seam.

TASK_031 owns what an alert says and how it is handed off to a transport. It
owns no orchestration: no eligibility query, no claim creation, no
AlertDelivery write. See
tasks/TASK_031_ALERT_PAYLOAD_TELEGRAM_AND_CONFIGURATION.md Sections 7-9.
"""

from typing import Callable

from alerts.config import AlertConfig

# Telegram's documented sendMessage text range (specification Section 7.3).
_TELEGRAM_TEXT_MIN = 1
_TELEGRAM_TEXT_MAX = 4096

# Frozen sanitized failure vocabulary (specification Section 9.3). The bot
# token lives in the request URL, so these messages must never carry any raw
# transport, parser, or Telegram-supplied detail.
_FAILURE_MESSAGES = {
    "timeout": "Telegram request timed out.",
    "transport_failure": "Telegram request could not be completed.",
    "invalid_response": "Telegram returned an unreadable response.",
    "api_rejected": "Telegram rejected the message.",
}


class AlertPayloadError(Exception):
    """Raised when a constructed alert message cannot be sent."""


class AlertDeliveryError(Exception):
    """Sanitized failure from an alert transport. `reason` is one of the
    four frozen values in _FAILURE_MESSAGES; str(error) is exactly that
    message and carries no raw external detail.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(_FAILURE_MESSAGES[reason])


# Following the AuditWriter precedent (outcomes/outcome_services.py): a plain
# callable type alias, no ABC, no registry, no plugin system.
AlertSender = Callable[[AlertConfig, str], None]


def build_alert_message(deal_flag, config: AlertConfig) -> str:
    """Construct the frozen six-line plain-text alert message.

    Privacy boundary (specification Section 7.5): this function must access
    only deal_flag.score, deal_flag.listing.price, deal_flag.listing.condition
    (via get_condition_display()), deal_flag.listing.sku (via str()), and
    deal_flag.pk. It must never traverse deal_flag.listing.raw_listing or any
    RawListing/Source field — not even to discard the value, since accessing
    it triggers a query.
    """
    lines = [
        "PriceWatch PH deal flag",
        str(deal_flag.listing.sku),
        f"Price: ₱{format(deal_flag.listing.price, 'f')}",
        f"Condition: {deal_flag.listing.get_condition_display()}",
        f"Score: {format(deal_flag.score, 'f')}",
        f"{config.public_base_url}/deals/{deal_flag.pk}/outcome",
    ]
    message = "\n".join(lines)

    if not (_TELEGRAM_TEXT_MIN <= len(message) <= _TELEGRAM_TEXT_MAX):
        raise AlertPayloadError("Alert message exceeds Telegram's 4096-character limit.")

    return message
