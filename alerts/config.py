"""Alert configuration: reading, parsing, and validating the five alert
settings. See tasks/TASK_031_ALERT_PAYLOAD_TELEGRAM_AND_CONFIGURATION.md
Section 5.

No module under alerts/ reads the process environment directly —
config/settings.py is the only environment reader in the repository
(TASK_001's frozen symmetry test), so every value below is read through
django.conf.settings.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from django.conf import settings


class AlertConfigurationError(Exception):
    """Raised when the configured alert settings cannot be validated."""


@dataclass(frozen=True, slots=True)
class AlertConfig:
    telegram_bot_token: str
    telegram_chat_id: str
    activation_at: datetime  # tz-aware, normalized to UTC
    public_base_url: str  # normalized, no trailing slash


def alerts_enabled() -> bool:
    return settings.ENABLE_ALERTS


def _validate_credential(value: str, label: str) -> str:
    """Empty/whitespace-only is unconfigured; padded is rejected, not
    stripped, so a misconfigured credential fails loudly instead of silently
    differing from what the operator set. A well-formed value passes through
    byte-for-byte unchanged.
    """
    if value == "":
        raise AlertConfigurationError(f"{label} is not configured.")
    if value.strip() == "":
        raise AlertConfigurationError(f"{label} is whitespace-only.")
    if value != value.strip():
        raise AlertConfigurationError(f"{label} has surrounding whitespace.")
    return value


def _validate_activation_at(value: str) -> datetime:
    """Must carry an explicit offset (Z or +HH:MM); a naive value parses fine
    under fromisoformat but is ambiguous, so rejecting it is our rule, not
    the parser's.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise AlertConfigurationError("ALERT_ACTIVATION_AT is not a valid ISO 8601 instant.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AlertConfigurationError("ALERT_ACTIVATION_AT must carry an explicit UTC offset.")
    return parsed.astimezone(timezone.utc)


def _validate_public_base_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        raise AlertConfigurationError("PUBLIC_BASE_URL must use http or https.")
    if not parts.netloc:
        raise AlertConfigurationError("PUBLIC_BASE_URL must include a network location.")
    if parts.path not in ("", "/"):
        raise AlertConfigurationError("PUBLIC_BASE_URL must not include a path prefix.")
    if parts.query:
        raise AlertConfigurationError("PUBLIC_BASE_URL must not include a query string.")
    if parts.fragment:
        raise AlertConfigurationError("PUBLIC_BASE_URL must not include a fragment.")
    return f"{parts.scheme}://{parts.netloc}"


def load_alert_config() -> AlertConfig:
    """Validate all four alert values and return a fully valid AlertConfig,
    or raise AlertConfigurationError. No database write, no network request.
    Deliberately does not consult the enable flag — TASK_032 orders the two.
    """
    telegram_bot_token = _validate_credential(settings.TELEGRAM_BOT_TOKEN, "TELEGRAM_BOT_TOKEN")
    telegram_chat_id = _validate_credential(settings.TELEGRAM_CHAT_ID, "TELEGRAM_CHAT_ID")
    activation_at = _validate_activation_at(settings.ALERT_ACTIVATION_AT)
    public_base_url = _validate_public_base_url(settings.PUBLIC_BASE_URL)

    return AlertConfig(
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        activation_at=activation_at,
        public_base_url=public_base_url,
    )
