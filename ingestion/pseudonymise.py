import hashlib
import hmac

from django.conf import settings

# Keys inside a RawListing.payload that name a counterparty and must be
# pseudonymised before write, via the same function that produces the
# `seller` column value — see TASK_005 Decision 5. Anything not in this set
# passes through redact_payload() verbatim, which makes this set a security
# boundary: it must be right on the first write, since the row it writes to
# is immutable.
PII_PAYLOAD_KEYS = frozenset({"seller"})


def pseudonymise(value: str) -> str:
    """A keyed HMAC-SHA256 token for a counterparty name or handle.

    Keyed, not a bare digest: the space of Filipino names and marketplace
    handles is small enough to brute-force, so an unkeyed hash would be
    obfuscation, not pseudonymisation. The key can never be rotated — tokens
    live in immutable rows, so a new key stops matching a counterparty's past
    tokens. See TASK_005 Decisions 5 and 6.
    """
    key = settings.SELLER_PSEUDONYM_KEY.encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def redact_payload(payload: dict) -> dict:
    """Replace PII_PAYLOAD_KEYS values with the identical token pseudonymise()
    writes to the `seller` column, so the two can never disagree — they are
    one code path, not two that merely agree today. Every other key passes
    through unchanged.
    """
    redacted = dict(payload)
    for key in PII_PAYLOAD_KEYS:
        if key in redacted and redacted[key] is not None:
            redacted[key] = pseudonymise(redacted[key])
    return redacted
