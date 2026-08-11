# TASK_031 — Alert payload, Telegram adapter, and configuration

## 1. Goal

Define what a PriceWatch PH alert *says*, what leaves the system, how the
Telegram Bot API is called, and how alert configuration is read and validated.

This is the first outbound network integration in the repository. It handles a
secret that the Bot API places **in the request URL**, so the sanitization
boundary in Section 9 is a security control, not tidiness.

TASK_031 owns payload construction, configuration, the injectable adapter seam,
the Telegram implementation of that seam, and sanitized failure behavior. It
owns no orchestration: it never queries DealFlags, never creates or updates an
`AlertDelivery`, and never decides what to send.

## 2. Authority and dependencies

- `CLAUDE.md`;
- `docs/07_PLANNING.md` (committed at `ae403b8`), owner-approved. Decisions A
  (Telegram), B (stdlib `urllib.request`), C (activation cutoff), D (no cap),
  E (10s timeout), G (`sent` semantics), H (no retry), I (no resend),
  J (no source URL), and K (single operator) bind this task;
- TASK_030 (committed at `9e60fac`), which owns `AlertDelivery` persistence and
  at-most-once claim semantics. **TASK_031 changes none of it** and writes no
  row;
- TASK_001's frozen `.env.example` ↔ `settings.py` symmetry test;
- `outcomes/outcome_services.py`, whose `AuditWriter = Callable[...]` type alias
  is the repository's precedent for an injectable side-effect seam.

### 2.1 Boundary with TASK_032

TASK_032 owns the eligibility query, claim creation, claim concurrency, the
persistence transitions, command summary output, and exit codes. TASK_031
provides the pieces TASK_032 calls. In particular TASK_031 exposes a
configuration-validation entry point with **no database side effect and no
network request**, so TASK_032 can be frozen to call it before creating a claim;
proving that ordering is TASK_032's job, not this task's.

## 3. Verified external contracts

Checked against primary sources during HARDEN rather than recalled.

### 3.1 Telegram Bot API — <https://core.telegram.org/bots/api>

Quoted from the official reference:

- endpoint and token placement: *"All queries to the Telegram Bot API must be
  served over HTTPS and need to be presented in this form:
  `https://api.telegram.org/bot<token>/METHOD_NAME`."*
- methods: *"We support GET and POST HTTP methods."*
- content types: *"We support four ways of passing parameters in Bot API
  requests: URL query string, application/x-www-form-urlencoded,
  application/json (except for uploading files), multipart/form-data (use to
  upload files)."*
- response envelope: *"The response contains a JSON object, which always has a
  Boolean field 'ok' and may have an optional String field 'description' … If
  'ok' equals True, the request was successful and the result of the query can
  be found in the 'result' field. In case of an unsuccessful request, 'ok'
  equals False and the error is explained in the 'description'. An Integer
  'error_code' field is also returned."*

`sendMessage` requires `chat_id` and `text`, `text` is 1–4096 characters, and a
successful call returns a `Message`. The reference page exceeds the documentation
fetcher's size limit and truncates before "Available methods", so these four
`sendMessage` facts were confirmed via an official-domain
(`core.telegram.org`) search summary rather than a direct quotation of the
method table. They are consistent with the quoted envelope semantics above and
with the endpoint form. **Nothing in this task depends on any further
`sendMessage` parameter.**

**The token is in the URL.** This single fact drives Section 9.

**No request-side idempotency.** No idempotency key or request-deduplication
mechanism for ordinary `sendMessage` appears in the official "Making requests"
documentation. This confirms the plan's position that at-most-once must be
enforced on our side (TASK_030's claim), not by Telegram.

`chat_id` is an integer *or* a string (`@channelusername` form). TASK_031
therefore treats the configured destination as an **opaque non-empty string**
passed through unchanged — no integer parsing, which would break `@username`
destinations for no benefit.

### 3.2 Python `urllib` — <https://docs.python.org/3/library/urllib.request.html> and <https://docs.python.org/3/library/urllib.error.html>

- `urlopen(url, data=None, [timeout,] *, context=None)`; *"The optional timeout
  parameter specifies a timeout in seconds for blocking operations like the
  connection attempt"*.
- `Request(url, data=None, headers={}, …, method=None)`; the method *"default is
  'GET' if data is None or 'POST' otherwise"*. `data` must be bytes (or a
  file-like/iterable of bytes). *"An appropriate Content-Type header should be
  included if the data argument is present"*, otherwise
  `application/x-www-form-urlencoded` is added — so the JSON content type must
  be set explicitly.
- `URLError` *"is a subclass of OSError"*; `HTTPError` is *"a subclass of
  URLError"* and *"can also function as a non-exceptional file-like return
  value"*. All non-2xx responses are turned into `HTTPError`.

Verified empirically on this repository's own runtime (Python 3.12.13 in the
`web` container), because the documentation does not state it:

```text
HTTPError.__mro__       -> HTTPError, URLError, OSError, Exception, …
socket.timeout is TimeoutError -> True
ssl.SSLError, ConnectionError, TimeoutError  -> all subclass OSError
json.JSONDecodeError    -> subclasses ValueError, NOT OSError
```

**Load-bearing finding.** `AbstractHTTPHandler.do_open` wraps `OSError` into
`URLError` only around the *request* phase:

```python
except OSError as err: # timeout error
    raise URLError(err)
```

The response `read()` happens after that block, so **a timeout while reading the
response body propagates as a bare `TimeoutError`, not a `URLError`.** Catching
only `URLError` would let it escape the adapter unsanitized. The catch boundary
in Section 9 is therefore `OSError`, which covers `HTTPError`, `URLError`,
`TimeoutError`, `ConnectionError`, and `ssl.SSLError` alike.

Also verified: `datetime.fromisoformat` accepts a `Z` suffix on 3.12 and yields
`tzinfo=UTC`; it accepts naive strings too, so a naive value must be rejected by
*our* check, not by the parser. And `str(Decimal("1E+2"))` is `"1E+2"` while
`format(Decimal("1E+2"), "f")` is `"100"` — which is why Section 7 freezes `:f`
formatting rather than `str()`.

## 4. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_031_ALERT_PAYLOAD_TELEGRAM_AND_CONFIGURATION.md`
- `tests/test_task_031_alert_payload_telegram_and_configuration.py`

### IMPLEMENT files allowed — after owner approval

- `alerts/config.py` (new) — configuration reading, parsing, validation
- `alerts/delivery.py` (new) — payload construction and its size invariant, the
  adapter seam, `AlertPayloadError`, and `AlertDeliveryError`
- `alerts/telegram.py` (new) — the Telegram transport, the only Bot API-aware module
- `config/settings.py` — the five alert settings only
- `.env.example` — the five alert keys only

Not authorized: `alerts/models.py`, `alerts/migrations/*`, `alerts/admin.py`,
`requirements.txt` (no new dependency — Decision B), any command, any existing
model, any migration, any frontend file, any previously frozen artifact.

A dedicated `alerts/config.py` is justified rather than folding configuration
into `delivery.py`: TASK_032 must call configuration validation as its own step
before claim creation, and keeping it a separate module makes that a real
boundary instead of an incidental import.

## 5. Configuration contract

### 5.1 Environment variables and settings

Five concrete values. The `PRICEWATCHPH_` prefix follows the existing
app-feature precedent (`PRICEWATCHPH_ENABLE_DEMO_DATA`); Django-core concerns
use `DJANGO_`, and these are not Django-core. Each setting name is the
environment name minus the prefix, exactly as `ENABLE_DEMO_DATA` does.

| Environment variable | Django setting | Type in settings |
|---|---|---|
| `PRICEWATCHPH_ENABLE_ALERTS` | `ENABLE_ALERTS` | `bool` |
| `PRICEWATCHPH_TELEGRAM_BOT_TOKEN` | `TELEGRAM_BOT_TOKEN` | `str` (`""` when unset) |
| `PRICEWATCHPH_TELEGRAM_CHAT_ID` | `TELEGRAM_CHAT_ID` | `str` (`""` when unset) |
| `PRICEWATCHPH_ALERT_ACTIVATION_AT` | `ALERT_ACTIVATION_AT` | `str` (`""` when unset) |
| `PRICEWATCHPH_PUBLIC_BASE_URL` | `PUBLIC_BASE_URL` | `str` (`""` when unset) |

`ENABLE_ALERTS` parses as `os.environ.get("PRICEWATCHPH_ENABLE_ALERTS", "0") == "1"`
— literal `"1"` only, default off, matching `ENABLE_DEMO_DATA`. No `DEBUG` or
hostname heuristic.

The other four are read as raw strings defaulting to `""`. Settings performs
**no** alert validation: parsing and validation happen in `alerts/config.py`
(Section 5.2), so importing settings with alerts disabled and no alert values
configured must keep working for every unrelated command and test.

All five appear in `.env.example` with inert placeholders, satisfying TASK_001's
bidirectional symmetry test. Secrets get no realistic-looking sample value.

### 5.2 `alerts/config.py`

```python
class AlertConfigurationError(Exception): ...

@dataclass(frozen=True, slots=True)
class AlertConfig:
    telegram_bot_token: str
    telegram_chat_id: str
    activation_at: datetime      # timezone-aware, normalized to UTC
    public_base_url: str         # normalized, no trailing slash

def alerts_enabled() -> bool: ...
def load_alert_config() -> AlertConfig: ...
```

`alerts_enabled()` returns `settings.ENABLE_ALERTS`.

`load_alert_config()` validates **all four** values and either returns a fully
valid `AlertConfig` or raises `AlertConfigurationError`. It has no database side
effect and makes no network request. It deliberately does **not** consult the
enable flag: each function stays single-purpose, and TASK_032 orders them.

**Credential whitespace.** A `telegram_bot_token` or `telegram_chat_id` whose
`.strip()` is empty is **not configured** and is rejected. A value carrying
surrounding whitespace is likewise **rejected, not silently stripped**: quietly
mutating a credential hides a real misconfiguration and would make the value
PriceWatch PH sends differ from the value the operator set. A well-formed
credential is passed through byte-for-byte unchanged — no normalization, no
trimming. This deliberately differs from `ALLOWED_HOSTS`, which strips because a
host list is a human-authored delimited list rather than a secret. No Telegram
token format/regex is invented, and no attempt is made to check whether a
credential is live.

Every value is read through `django.conf.settings`. **No module under `alerts/`
may read `os.environ`** — that would place the variable outside TASK_001's
frozen coverage test and silently exempt it from being documented in
`.env.example`. `config/settings.py` is the only environment reader in the
repository, and this task preserves that.

### 5.3 Activation cutoff

- **Accepted syntax:** an ISO 8601 instant parsable by `datetime.fromisoformat`,
  which **must** carry an explicit offset — either a `Z` suffix or a numeric
  `±HH:MM` offset.
- **Rejected:** empty; unparsable; and any value whose parsed `tzinfo` is
  `None` or whose `utcoffset()` is `None`. A naive value such as
  `2026-06-15T12:00:00` is rejected precisely because it is ambiguous; the
  parser accepts it, so the rejection is ours.
- **Normalization:** `.astimezone(timezone.utc)`. `2026-06-15T12:00:00+08:00`
  and `2026-06-15T04:00:00Z` both normalize to the same UTC instant.
- **Purpose:** an absolute instant comparable against timezone-aware
  `DealFlag.flagged_at` (stored UTC). No host-local, browser-local, or implicit
  timezone semantics anywhere.

TASK_031 parses and validates it. **TASK_032 performs the queryset comparison.**

### 5.4 Public application base URL

A management command has no HTTP request from which to infer the deployed
origin, so the absolute internal link needs configuration.

Parsed with `urllib.parse.urlsplit`. Valid only when **all** hold:

- scheme is `http` or `https`;
- netloc is non-empty;
- path is `""` or `"/"`;
- query is empty;
- fragment is empty.

Normalized to `f"{scheme}://{netloc}"` — a trailing slash is accepted and
stripped, so `https://pw.example` and `https://pw.example/` are equivalent.

Deliberate choices:

- **`http` is accepted.** Requiring HTTPS at application level would break local
  and development operation; Phase 9 owns production TLS. The alert link points
  at the operator's own deployment, not at a third party.
- **Path prefixes are rejected**, not silently supported. The repository serves
  the React app at the domain root (`/deals`, `/reviews`, `/skus/:id`), so a
  prefixed deployment does not exist. Rejecting is narrower and more honest than
  inventing join semantics nothing exercises.
- No hardcoded `localhost` and no guessed production hostname.

## 6. Action link

```text
{public_base_url}/deals/{deal_flag_id}/outcome
```

This is the TASK_029 route, verified still present in
`frontend/src/App.tsx` as `<Route path="/deals/:dealFlagId/outcome" …>`. It
requires an authenticated staff session, so the link discloses nothing by
itself.

The `DealFlag` primary key appears **only** here, because constructing this URL
is the one approved use for it.

## 7. Payload contract

### 7.1 Exact message

Plain text, lines joined with `\n`:

```text
PriceWatch PH deal flag
{sku}
Price: ₱{price}
Condition: {condition}
Score: {score}
{public_base_url}/deals/{deal_flag_id}/outcome
```

Field derivation, all from already-committed model behavior:

| Line | Source |
|---|---|
| `{sku}` | `str(deal_flag.listing.sku)` — the existing `Sku.__str__`, `"brand model variant"` stripped |
| `{price}` | `format(deal_flag.listing.price, "f")` |
| `{condition}` | `deal_flag.listing.get_condition_display()` — the existing `CONDITION_CHOICES` label, e.g. `Used` |
| `{score}` | `format(deal_flag.score, "f")` |
| link | Section 6 |

`listing.price` and `listing.condition` are guaranteed non-null for any
`DealFlag`: `pricing/scoring.py` `_is_eligible()` requires both before a flag can
be created.

### 7.2 Money and score — no float

`format(value, "f")` on a `Decimal` is exact fixed-point and never touches
binary floating point. `float()`, `Number`-like coercion, and arithmetic on a JS
or Python float are forbidden on any money or score value. `:f` is frozen rather
than `str()` because `str(Decimal("1E+2"))` yields `"1E+2"` (Section 3.2).

`₱` matches the product's existing money presentation
(`frontend/src/formatting/decimal.ts`) and exercises the UTF-8 encoding path
end to end.

### 7.3 Telegram text-size invariant, enforced before any claim

`sendMessage` accepts `text` of **1–4096 characters** (Section 3.1). A message
outside that range can never be delivered, so `build_alert_message()` enforces
the range itself:

1. construct the exact frozen six-line message;
2. verify its length is within 1–4096 (Python `len()` of the plain-text string);
3. return it when valid;
4. otherwise raise `AlertPayloadError` — before any networking and before any
   persistence.

```python
class AlertPayloadError(Exception): ...
```

The frozen message for the v1 oversized condition, and the only text this
exception carries:

```text
Alert message exceeds Telegram's 4096-character limit.
```

**Why this belongs to payload construction, not the sender.** The approved
orchestration is *validate config → build payload → create claim → commit →
send* (`docs/07_PLANNING.md` §7.3). If the size problem were discovered inside
`send_telegram_message()`, the durable `AlertDelivery` claim would already
exist, and TASK_030 forbids both retry and resend — so a DealFlag would be
permanently burned on a message that could never be delivered. Rejecting during
construction keeps the claim unconsumed. TASK_032 will be hardened to build and
validate the message before creating the claim.

The sender may additionally reject out-of-range text defensively, but only if it
does not duplicate this contract; the pre-claim guarantee is
`build_alert_message()`'s.

The range is frozen as 1–4096 rather than an upper bound alone so the API
contract matches Telegram's, even though the six-line template can never
legitimately render empty.

**No truncation.** SKU text and URLs are never silently shortened to fit. An
oversized payload is rejected honestly.

### 7.4 Plain text only

No `parse_mode`, no Markdown, no HTML, no inline keyboards, no buttons, no
rich-message features. The internal URL appears as a bare URL in the text.

This is a security decision as much as a simplicity one: adopting a `parse_mode`
would create an escaping surface where SKU text — derived from scraped listing
titles — could break or inject message formatting. Plain text has no such
surface. If a concrete usability need for formatting appears later, it is a
separate, argued change.

### 7.5 Privacy boundary — what must never appear

No `RawListing` evidence of any kind: raw title, raw price text, seller, seller
pseudonym token, `RawListing.url`, or any source listing URL. **Payload
construction must not traverse into `RawListing` at all.**

This is frozen at two independent levels, because either alone is insufficient:

1. **Output level** — none of those values appears anywhere in the rendered
   message; and
2. **Query level** — payload construction executes no SQL touching
   `ingestion_rawlisting` or `sources_source`, proven with
   `CaptureQueriesContext` in the style of TASK_020's
   `test_eligibility_query_does_not_read_rawlisting_or_source`.

Level 2 exists because an implementation could traverse `listing.raw_listing`,
discard the values, and still satisfy level 1 — reading the evidence it was told
not to read. Level 1 exists because a future refactor could reach the data by
some other path. The total query count is deliberately not frozen; only the
tables touched are.

No internal identifiers beyond the `DealFlag` id used for the action link. SKU
and Listing primary keys are not included — nothing in the approved product
behavior reads them, and the operator navigates by the link.

Because the payload is a single text string, the frozen tests assert the
*sensitive values themselves* are absent from the whole message, not merely that
some field name is missing.

## 8. Adapter seam

Following the `AuditWriter` precedent — a plain callable type alias, no abstract
base class, no registry, no plugin system, no channel factory:

```python
# alerts/delivery.py
AlertSender = Callable[[AlertConfig, str], None]
```

`(config, message) -> None`. It returns nothing: v1 persists no Telegram message
id, no approved behavior consumes the returned `Message`, and retaining an
identifier merely because Telegram returns one would be speculative. Success is
"returned without raising".

`alerts/telegram.py` provides the real implementation,
`send_telegram_message(config: AlertConfig, text: str) -> None`, which satisfies
`AlertSender`. TASK_032 will inject a substitute in tests. **No frozen test
performs real network I/O.**

## 9. Telegram transport and sanitization

### 9.1 Request

- URL: `https://api.telegram.org/bot{token}/sendMessage`
- method `POST`
- header `Content-Type: application/json`
- body: UTF-8 encoded JSON, exactly `{"chat_id": <destination>, "text": <message>}`
  — no `parse_mode`, no other key
- `urlopen(..., timeout=10)` — exactly 10 seconds, explicit (Decision E)
- exactly one call. No retry, no backoff, no second attempt (Decision H)

`alerts/telegram.py` is the only module that may know the endpoint, the token's
placement, the JSON shape, or `urllib` at all.

So the transport can be exercised without a network, `alerts/telegram.py` must
bind `urlopen` at module level so it is patchable as `alerts.telegram.urlopen`.
This is a deliberately frozen seam, not an incidental implementation detail.

### 9.2 Success

Recorded as success only when **all** hold:

1. the request completes without an exception, **and the response body is read
   without one** — the read phase is part of the request, not a separate
   best-effort step (Section 9.4);
2. the response body decodes **as UTF-8 specifically** (9.3.1 — not via
   `json.loads` byte auto-detection) and parses as JSON, and is an object;
3. `ok` is **exactly Boolean `True`** — an identity check, never truthiness.
   `1`, `"true"`, `"yes"`, a non-empty list, and a non-empty dict are all
   **not** success, because `if payload.get("ok"):` would accept every one of
   them and report a send Telegram never confirmed;
4. `result` is present and is an object (the `Message`).

The function then returns `None`. It never returns, stores, or logs the
`Message`. Nothing here means the operator *received* or *read* anything —
Decision G, and the reason the persisted vocabulary is `sent`, never
`delivered`. TASK_031 does not update `AlertDelivery`; TASK_032 persists `sent`.

### 9.3 Sanitized failure

One application-owned exception:

```python
class AlertDeliveryError(Exception):
    reason: str   # one of the four frozen values below
```

`str(exc)` is exactly the frozen message for its reason — nothing more.

| `reason` | Message | Raised when |
|---|---|---|
| `timeout` | `Telegram request timed out.` | bare `TimeoutError`, or `URLError` whose `.reason` is a `TimeoutError` |
| `transport_failure` | `Telegram request could not be completed.` | any other `OSError` (`URLError`, `ConnectionError`, `ssl.SSLError`, …) |
| `invalid_response` | `Telegram returned an unreadable response.` | body is not valid UTF-8, is not JSON, is not an object, or `ok` is `True` but `result` is missing/not an object |
| `api_rejected` | `Telegram rejected the message.` | `HTTPError` (Telegram answered with an error status), or a parsed body whose `ok` is not exactly `True` |

Classification order matters, because `HTTPError ⊂ URLError ⊂ OSError` and
`TimeoutError ⊂ OSError`: check `HTTPError` first, then the timeout cases, then
`OSError`.

An undecodable body must not let a `UnicodeDecodeError` escape; it normalizes
into `invalid_response`. No private parsing helper is frozen — only the boundary
behavior in 9.3.1.

#### 9.3.1 The response decode is explicitly UTF-8

The response boundary is exactly:

1. read the response bytes;
2. **decode them as UTF-8**;
3. a UTF-8 decode failure is `invalid_response`;
4. parse the decoded *string* as JSON;
5. apply the object / strict-`ok` / `result` validation of 9.2.

**Passing raw bytes to `json.loads` does not satisfy this.** `json.loads`
auto-detects supported Unicode encodings when handed bytes, verified on this
repository's runtime (Python 3.12.13):

```text
utf-8      accepted by json.loads(bytes)   decodes as utf-8
utf-16     accepted by json.loads(bytes)   FAILS explicit utf-8 decode
utf-32     accepted by json.loads(bytes)   FAILS explicit utf-8 decode
```

So `json.loads(body)` would silently accept a UTF-16 or UTF-32 Telegram
response while every invalid-byte test still passed. This is an external
protocol boundary, and explicit encoding is preferable to
implementation-dependent auto-detection: the adapter accepts UTF-8 and nothing
else.

A valid-JSON-but-UTF-16 body is therefore `invalid_response`, and the frozen
tests cover it alongside the truly-undecodable-bytes case. The two prove
different properties — undecodable bytes prove decode errors are sanitized; a
valid UTF-16 document proves the adapter actually requires UTF-8 rather than
leaning on `json.loads` byte auto-detection.

### 9.4 The read phase is inside the boundary

Both timeout phases classify as `timeout`, and both must be caught.

Section 3.2 established that `urllib` wraps `OSError` into `URLError` only
around the *request* phase, so a timeout raised by `response.read()` arrives as
a bare `TimeoutError`. An implementation shaped like:

```python
try:
    response = urlopen(request, timeout=10)
except OSError:
    ...
body = response.read()          # outside the guard - leaks
```

would pass a test that only makes `urlopen()` itself raise, while a real
mid-stream timeout escapes unsanitized and carries the request URL — and
therefore the bot token. **The sanitization boundary must enclose the response
read as well as the request.** The frozen tests exercise both phases separately,
including a non-timeout mid-stream failure.

The operator-visible meaning of a connect-phase and a read-phase timeout is the
same, and the plan's ambiguous-timeout tradeoff (`docs/07_PLANNING.md` §7.4)
makes both worth distinguishing from a plain transport failure.

**Never crossing the boundary**, because the bot token is in the request URL:
the request URL, the `urllib` `Request` object or its `repr`, `HTTPError` or
`URLError` text, `errno`/socket detail, the raw response body, and Telegram's
own `description` field. Telegram's `description` is excluded even though it
cannot contain our token, because the owner-approved rule is that no raw
external error text crosses the adapter boundary; the cost is that all API
rejections share one message, which is a deliberate, recorded trade of
diagnostic granularity for a guaranteed-safe failure string.

### 9.5 Exception chaining and formatted tracebacks

A sanitized `str()` and `repr()` are **not sufficient**. Both of these leak:

```python
except OSError as exc:
    raise AlertDeliveryError("transport_failure") from exc   # explicit __cause__
```

```python
except OSError:
    raise AlertDeliveryError("transport_failure")            # implicit __context__
```

In each case the application-owned error's own text stays clean while a normally
formatted traceback still prints the underlying `HTTPError`/`URLError` — and
therefore the token-bearing request URL — under *"The above exception was the
direct cause…"* or *"During handling of the above exception…"*. Anything that
renders a traceback (an unhandled crash, a logging call with `exc_info`, a
debugger, an error reporter) would expose the bot token.

**`raise … from None` is NOT sufficient.** It sets `__cause__ = None` and
suppresses *display* of the implicit context, but the original exception object
remains attached at `__context__`. Verified on this repository's runtime:

```text
raise ... from exc   -> __cause__=URLError(...)  __context__=URLError  traceback leaks
raise ... from None  -> __cause__=None           __context__=URLError  traceback clean
classify, leave the
except block, then
raise                -> __cause__=None           __context__=None      traceback clean
```

So `from None` yields clean traceback *display* while the token-bearing
`URLError` is still reachable as `error.__context__` — readable by any error
reporter, structured logger, or debugger that walks the chain. An earlier draft
of this specification asserted both the stronger no-reachable-exception rule and
that `from None` satisfied it; those two statements are not simultaneously true
in Python, and the stronger rule is the one that is frozen.

**Frozen property.** When an `AlertDeliveryError` leaves
`send_telegram_message()` — for **every** failure path, not only transport ones:

- `error.__cause__ is None`;
- `error.__context__ is None`;
- the fully formatted traceback reveals no raw external exception; and
- no raw `HTTPError` / `URLError` / `TimeoutError` / socket-error **or parser
  exception** object is reachable from the application-owned exception at all.

The bot token, destination, `api.telegram.org`, `/sendMessage`, raw external
exception text, the raw response body, and Telegram's `description` remain
absent from every one of these surfaces.

**Parser exceptions are included, and are their own leak vector.** A shape like

```python
except (UnicodeDecodeError, json.JSONDecodeError):
    raise AlertDeliveryError("invalid_response")
```

sanitizes the outer message while Python implicitly attaches the parser
exception at `__context__`. That matters more than it first appears:
`json.JSONDecodeError` carries **the entire raw response document** on its `.doc`
attribute, and `UnicodeDecodeError` carries the offending bytes and decoder
detail in its message. Either would put raw external response material back
across the boundary that Section 9.3 says it must never cross. The detachment
rule therefore applies to `invalid_response` exactly as it does to
`transport_failure`, `timeout`, and `api_rejected`.

**Implementation-neutral.** No private helper or code layout is frozen. One
conforming shape is: catch and classify the external exception, retain only the
safe application-owned reason, leave the `except` block, and raise the sanitized
`AlertDeliveryError` where no exception is active. Any equally safe structure is
acceptable — the frozen behavior is what matters.

### 9.6 No logging of transport failures

**TASK_031 emits no log records at all from the `alerts` package on any failure
path** — transport failure, timeout, HTTP/API rejection, malformed JSON, and
undecodable body alike. The sanitized exception is the diagnostic channel, and
TASK_032 persists it into `AlertDelivery.failure_detail` — a field TASK_030
already constrains to be non-empty for a `failed` row. The four messages in 9.3
are safe to persist and print verbatim.

This is frozen because logging is a distinct output channel from stdout/stderr:
an adapter calling `logger.exception("Telegram request failed: %s", exc)` before
raising the sanitized error would write the token-bearing URL into application
logs while every stdout/stderr assertion still passed.

The frozen tests assert this at two scopes: no record whose logger name is under
`alerts` is emitted at all (scoped so unrelated framework logging cannot make it
brittle), and no captured record under *any* logger name contains the forbidden
strings.

## 10. Acceptance criteria — frozen

The authoritative artifact is
`tests/test_task_031_alert_payload_telegram_and_configuration.py`. It freezes,
at minimum:

**Configuration** — default disabled; literal `"1"` enables and other values do
not; disabled state tolerates entirely absent alert configuration; enabled
validation requires each of token, destination, cutoff, and base URL;
whitespace-only credentials rejected and padded credentials rejected rather than
stripped, with valid credentials passed through unchanged; malformed and naive
cutoffs rejected; offset and `Z` forms parse to the same UTC instant; base-URL
scheme/netloc/path/query/fragment rules and trailing-slash normalization; no
`alerts/` module reads `os.environ`; all five keys present in both `settings.py`
and `.env.example`.

**Payload** — the exact six-line message; SKU, Decimal price, condition label,
Decimal score, and absolute action link; no float anywhere; no RawListing value
present anywhere in the message; no source URL; no SKU/Listing primary keys;
**payload construction executes no SQL against `ingestion_rawlisting` or
`sources_source`**.

**Payload size** — a message of exactly 4096 characters is accepted; one
character more raises `AlertPayloadError` with exactly the frozen message,
performs no network request, creates no `AlertDelivery` row, and is never
truncated.

**Adapter seam** — a substitute satisfies it with no network; success is a
plain return; no registry or plugin machinery exists.

**Telegram request** — exact endpoint, POST, JSON content type, UTF-8 JSON body
of exactly `chat_id` and `text`, `timeout=10`, no `parse_mode`, exactly one call.

**Telegram response** — `{"ok": true, "result": {...}}` accepted; `ok: false`
rejected; **truthy non-Boolean `ok` values (`1`, `"true"`, `"yes"`, non-empty
list/dict) rejected as `api_rejected`**; malformed JSON rejected; a body that is
not valid UTF-8 rejected as `invalid_response` with no `UnicodeDecodeError`
escaping; **a valid JSON document encoded as UTF-16 rejected as
`invalid_response`**, proving the adapter requires UTF-8 rather than relying on
`json.loads` byte auto-detection; `ok: true` without a `result` object rejected.

**Sanitization** — `HTTPError`, `URLError`, bare `TimeoutError`, wrapped connect
timeout, **read-phase `TimeoutError`**, **read-phase transport failure**,
undecodable body, malformed body, and API rejection each map to the frozen
reason and message; and for every one of them the bot token, the destination,
the request URL, and the raw external text are absent from the exception, its
`repr`, and anything the adapter writes to stdout/stderr.

**Exception chaining** — across **all four failure categories**: token-bearing
transport failures (`HTTPError`, `URLError`, read-phase timeout, read-phase
transport failure) **and invalid-response parsing failures (malformed JSON,
undecodable UTF-8)**. For each: the **fully formatted traceback** contains none
of the forbidden strings or the distinctive raw body, **and `__cause__ is None`
and `__context__ is None`** — the strict object-level rule, not
traceback-display-only sanitization; the `reason` and message remain the frozen
vocabulary, so sanitization cannot be achieved by breaking the public error
vocabulary.

**Logging** — for all of those failures, and for an API rejection carrying a
Telegram `description`, **no log record originates from the `alerts` package**,
and no captured record under any logger name contains the bot token, the
destination, the request URL, the raw external text, the raw response body, or
Telegram's `description`.

**Compatibility** — TASK_001 symmetry still holds; TASK_030's `AlertDelivery`
contract is untouched and no row is created by any TASK_031 code path.

Tests use obviously synthetic, inert credentials. No real credential appears in
the repository.

## 11. Explicit non-goals

No eligibility query, claim creation, claim concurrency, persistence
transition, command, summary output, or exit code (TASK_032). No admin
(TASK_033). No retry, resend, attempt history, or cooldown. No recipient model,
channel registry, or second channel. No new dependency. No `parse_mode` or rich
Telegram features. No inbound webhook or bot command handling. No change to
`AlertDelivery`, its migration, any existing model, or any frontend file. No
production secret values — Phase 9 owns those.

## 12. Validation

HARDEN baseline (implementation absent — failures expected):

```text
docker compose exec web pytest -v tests/test_task_031_alert_payload_telegram_and_configuration.py
```

After implementation:

```text
docker compose exec web pytest -v tests/test_task_031_alert_payload_telegram_and_configuration.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py check
```

A full backend run is justified: this task modifies `config/settings.py`, which
every test imports, and `.env.example`, which TASK_001's frozen test reads. No
frontend validation applies — TASK_031 touches no frontend file.

## 13. Stop conditions

Implementation stops and reports rather than improvising if: the live Bot API
contradicts Section 3.1; `urllib.request` cannot implement Section 9 without
leaking the token; the five settings cannot satisfy TASK_001 symmetry without
changing a frozen contract; the payload cannot be built without `RawListing`;
`/deals/<id>/outcome` is no longer the authoritative internal route; or any
frozen behavior requires modifying TASK_030 persistence or its migration.

No implementation begins until this specification and its frozen acceptance
module receive explicit owner approval.
