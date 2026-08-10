# Phase 7 Planning - Alerts

## 1. Phase goal

Deliver the smallest reliable outbound notification that tells the operator a
new DealFlag exists, without letting outbound networking contaminate the
deterministic pricing and scoring path.

Phase 7 owns application-level alert behavior and its testable delivery
boundary. It does not own production runtime provisioning (Section 14).

The phase is deliberately small: one persisted delivery claim, one Telegram
adapter, one management command, and read-only admin visibility. Nothing in
this phase generalises into a notification platform.

## 2. Non-goals

Explicitly excluded from Phase 7:

- a generic notification framework, channel registry, or plugin system;
- an email channel or any fallback channel (Decision A);
- multi-user subscriptions, per-user preferences, or a recipient model
  (Decision K);
- a notification dashboard, settings centre, or any new React surface;
- digests, batching windows, quiet hours, or scheduled summaries;
- a per-invocation alert cap (Decision D);
- automatic retry, retry counters, `next_retry_at`, cooldown timestamps, a
  retry daemon, or a separate attempt-history model (Decisions F, H, and the
  TASK_030 schema boundary in Section 16);
- manual resend, an admin resend action, a command `--force`, or a
  delete-and-recreate convention (Decision I);
- alerting on anything other than DealFlags - no pricing-run health alerts, no
  ingestion-failure alerts, no Outcome-derived alerts;
- Celery, Redis, or any message broker - the standing CLAUDE.md constraint;
- inbound webhooks or Telegram bot command handling - delivery is outbound only;
- production secret provisioning, cron deployment, TLS, or process supervision
  (Phase 9);
- external secondhand-source integrations. Facebook Marketplace remains
  permanently excluded, Carousell remains rejected, TipidPC remains a
  permission candidate only. No Phase 7 decision depends on any of them.

## 3. Confirmed repository facts

Established by reading the committed repository at `918fb48` (TASK_029), not
reconstructed from memory.

### 3.1 DealFlag is immutable and cannot carry delivery state

`pricing/models.py` `DealFlag.save()` raises `ValidationError` when
`self._state.adding` is false, and `DealFlag.delete()` raises unconditionally.
The same pattern guards `PricePoint`.

This is the single most decisive fact in the phase. An `alerted_at` column on
DealFlag is impossible: writing it would require an UPDATE, which the model
forbids. Durable delivery state therefore *must* live in a separate model
(Section 7). This is a repository constraint, not a design preference.

### 3.2 DealFlag creation is already idempotent and already threshold-gated

`pricing/scoring.py`:

- `score_listing()` returns the existing DealFlag immediately if one exists for
  the listing, before any eligibility or scoring work;
- `_DEAL_THRESHOLD = Decimal("-3.0000")` gates flag creation, alongside
  `_MINIMUM_SAMPLE_SIZE = 5`, a positive `mad`, `price_kind == "asking"`, and
  `_TRUSTED_RESOLUTION_METHODS = ("exact_alias", "human_confirmed")` with
  `resolution_confidence == 1.0000`;
- creation goes through `DealFlag.objects.get_or_create()`, with
  `dealflag_listing_unique` making a concurrent winner authoritative.

Consequence: **the existence of a DealFlag already means "this listing cleared
the deal threshold"**. Phase 7 does not need, and must not invent, a second
alerting threshold.

### 3.3 Scoring runs inside one transaction, which forbids inline delivery

`pricing/management/commands/price_listings.py` wraps both the PricePoint
snapshot loop and the entire `score_listing()` loop in a single
`with transaction.atomic():` block.

Performing outbound HTTP inside that block would hold a Postgres transaction
open across network I/O for every flagged listing, and a delivery timeout would
roll back correctly-computed pricing evidence. Decisive evidence for Section 4's
separate-command architecture, and for the "never hold a transaction across
HTTP" rule in Section 7.

### 3.4 There is no outbound HTTP anywhere in the repository yet

`requirements.txt` is Django, DRF, whitenoise, psycopg, pytest, pytest-django,
PyYAML. There is no `requests`, no `httpx`, no HTTP client of any kind.
`ingestion/management/commands/ingest.py` supports exactly one importer,
`manual_capture`, which reads UTF-8 from stdin. No eBay client exists despite
the ROADMAP naming one.

Phase 7 alerts would be the **first outbound network call in the codebase**.
That elevates the delivery-boundary and secrets tasks, and makes the "tests
never touch the network" rule load-bearing rather than routine. It also
supports Decision B: stdlib `urllib.request` adds no dependency to a repository
that currently has zero HTTP clients.

### 3.5 Injectable-dependency precedent already exists

`outcomes/outcome_services.py` accepts `audit_writer: AuditWriter | None = None`
(a `Callable`) on every governed operation, defaulting to the real
`LogEntry`-writing implementation. Tests substitute it.

This is the established repository pattern for isolating a side effect behind an
injectable seam, and Section 6's Telegram adapter should follow it rather than
inventing an abstract base class or a settings-driven backend registry.

### 3.6 `.env.example` and `settings.py` are bidirectionally frozen-tested

`tests/test_task_001_bootstrap.py::test_env_example_covers_every_environment_variable_settings_reads`
asserts set equality in both directions: every `os.environ[...]` /
`os.environ.get(...)` key in `config/settings.py` must appear in
`.env.example`, and every `.env.example` key must be read by settings.

Any new alert configuration variable is therefore a coupled two-file change
that will fail an existing frozen test if done in one file only.

### 3.7 `config/settings.py` is the only module that reads the environment

Verified by inspection: outside `manage.py` and `config/wsgi.py` setting
`DJANGO_SETTINGS_MODULE`, every `os.environ` read in the repository is in
`config/settings.py`.

This is a binding convention for TASK_031, not a stylistic note. Reading an
alert variable directly inside an `alerts/` module would place it **outside**
the frozen coverage test in 3.6, silently exempting it from the requirement to
be documented in `.env.example`. All Phase 7 configuration must therefore be
read in `config/settings.py` and consumed from `django.conf.settings`.

Existing precedent for opt-in side-effect behavior: `ENABLE_DEMO_DATA` accepts
only the literal string `"1"` - no `DEBUG` or hostname heuristic - so enabling
a side effect requires a deliberate environment change.

### 3.8 There is no scheduler container

`docker-compose.yml` declares exactly two services, `db` and `web`. The `web`
command is `runserver`. There is no cron container, no scheduler service, and no
crontab file, despite `docs/ROADMAP.md` describing "Scheduler (cron, own
container)".

Phase 7 cannot "integrate with the scheduler" because the scheduler does not
exist. Phase 7 delivers a command that *is safe to schedule*; scheduling it is
Phase 9 (Section 14).

### 3.9 Privacy-relevant structures already exist

`ingestion/pseudonymise.py` exists and `SELLER_PSEUDONYM_KEY` is documented in
settings as never-rotatable because tokens derived from it live in immutable
RawListing rows. RawListing is immutable and holds `raw_title`, `raw_price`,
`url`, `seller`, `fetched_at`.

The repository already treats seller identity and raw source evidence as
sensitive. An alert payload must not undo that (Section 10, Decision J).

### 3.10 OneToOne-to-DealFlag is exact existing precedent

`outcomes/models.py` declares
`deal_flag = models.OneToOneField(DealFlag, on_delete=models.PROTECT, related_name="outcome")`.
`listings/models.py` uses the same `OneToOneField(..., on_delete=PROTECT)`
shape for `raw_listing`, and every FK in `pricing/models.py` uses `PROTECT`.

Repository inspection therefore establishes **no** reason to avoid
`OneToOneField` for AlertDelivery, and a direct precedent for using it. Section
7 adopts it, satisfying Decision F's preferred representation.

### 3.11 The frozen API/DealFlag payload does not bind this phase

`api/serializers.py` exposes DealFlag as
`id, sku, listing, baseline_pricepoint, score, reason, flagged_at` and TASK_029
froze that set. Phase 7 adds no field to it and no alert data to any API
response, so no frozen API contract is reopened.

### 3.12 The internal actionable route already exists

TASK_029 shipped `/deals/:dealFlagId/outcome`, reachable from the deal feed and
backed by the governed TASK_028 Outcome API. It is the correct destination for
an alert's actionable link (Decision J), and it already requires an
authenticated staff session, so the link exposes nothing by itself.

## 4. Recommended architecture

```text
price_listings (unchanged, deterministic, no network)
    └── writes DealFlag rows inside one transaction

send_deal_alerts (new management command, separate invocation)
    ├── validate all alert configuration up front, before touching state
    ├── select DealFlags that have NO AlertDelivery row at all,
    │   and whose flagged_at >= configured activation cutoff
    ├── build and validate the deterministic payload
    ├── atomically create the unique AlertDelivery claim (status pending)
    │   and COMMIT that short transaction before any network I/O
    ├── only the claim winner calls the Telegram adapter (10s timeout)
    └── record the terminal status: sent or failed
```

Four properties, each traceable to a Section 3 fact:

1. pricing stays testable with no network and no new dependency (3.3, 3.4);
2. delivery state is durable and survives restarts, because it is a table, not
   process memory (3.1);
3. a delivery failure cannot roll back pricing evidence (3.3);
4. reruns are safe because eligibility is a database question - *is there a row?*
   - not a timestamp-window guess (3.1, 3.10).

**Eligibility is the absence of any AlertDelivery row.** Not "no successful
delivery". A `pending` row and a `failed` row both make a DealFlag ineligible
forever, by design (Decisions F and H). This is what makes at-most-once
enforceable with a single unique constraint.

Rejected alternative: calling the adapter from inside `score_listing()`. It
buries outbound networking in deterministic scoring, holds a transaction open
across network I/O, and makes every existing scoring test either
network-dependent or mock-dependent. Section 3.3 is direct evidence against it.

## 5. Alert trigger semantics

A DealFlag is a candidate when **both** hold:

1. **No AlertDelivery row exists for it** (Section 4); and
2. **`DealFlag.flagged_at >= the configured activation cutoff`** (Decision C).

Justification for (1): Section 3.2 establishes that DealFlag existence already
encodes the deal threshold, sample-size floor, resolution-trust requirement, and
price-kind requirement. Reusing it means Phase 7 invents no threshold and adds
no tunable.

Justification for (2): without a cutoff, first activation would alert on the
entire historical DealFlag backlog at once. The alternative - creating
suppression rows for every historical DealFlag via a data migration - is
explicitly rejected (Decision C): it writes a large volume of rows that assert a
delivery attempt that never happened, permanently falsifying the delivery
history the phase exists to produce.

**No per-run cap** (Decision D). Current first-party and manual acquisition
volume does not justify inventing a throttle number; if production evidence
later demonstrates the need, it can be added from that evidence.

Explicitly not v1 triggers: a second alert-only score threshold; cooldown
windows; pricing-run completion or health alerts; Outcome transitions (Outcome
is the human's *response* to an alert, so alerting on it inverts causality).

## 6. Delivery channel and service boundary

**Channel: Telegram Bot API** (Decision A, ratifying the ROADMAP line 40
recommendation). No email fallback, no channel registry, no multi-channel
abstraction beyond the narrow injectable seam below.

**Transport: Python stdlib `urllib.request`** (Decision B). HTTPS POST with a
JSON body. No `requests`, no `httpx` - one POST does not justify a dependency in
a repository that currently has none (3.4).

**Timeout: exactly 10 seconds, explicit** (Decision E). No in-process retry loop
inside or around that timeout.

Structure, following the `audit_writer` precedent (3.5):

```text
alerts/delivery.py     builds/validates the payload; defines the adapter
                       callable shape; defines one sanitized delivery-failure
                       exception type
alerts/telegram.py     the only module that knows Bot API details - endpoint
                       shape, token placement, request/response format
```

Rules:

- orchestration depends on the callable shape, never on Bot API details;
- `alerts/telegram.py` is the only place a Telegram URL, token, or wire format
  appears;
- tests inject a substitute and **never** perform a real network call; no test
  may depend on network availability or a live credential;
- every transport error is translated into the single sanitized
  delivery-failure exception, so callers never see a `urllib` exception type or
  message (Section 10 explains why this is a security requirement, not just
  tidiness).

**Success semantics (Decision G).** A send is recorded `sent` only when all
hold:

- the Bot API request completed without a transport error;
- the response body parses as JSON reporting Bot API success (`ok` true);
- `sendMessage` returned its successful `Message` result.

A Bot API rejection, a non-success `ok`, or a malformed/unparseable response is
`failed`. The terminology is deliberately `sent`, not `delivered`: this proves
the Bot API accepted the message, and proves nothing about whether the operator
received or read it.

## 7. Persistence, idempotency, and the delivery guarantee

**Guarantee: at-most-once send attempt per DealFlag** (Decision F).

### 7.1 Why the previous partial-unique design was wrong

An earlier draft of this document recommended a partial unique index on
successful deliveries, claiming it preserved at-most-once while permitting
retry after failure. That was incorrect. Two concurrent workers could each
insert a non-success attempt row - neither of which the partial index
constrains - and each could then perform the irreversible external send before
any success row ever met the constraint. The constraint would have prevented
only the *recording* of a duplicate, not the duplicate Telegram message itself,
which is the only thing that matters. The design below replaces it.

### 7.2 The v1 shape

**Exactly one logical AlertDelivery per DealFlag**, enforced by the database.

Adopt `OneToOneField(DealFlag, on_delete=models.PROTECT)`, per the exact
existing precedent in 3.10 (`Outcome.deal_flag`). Repository inspection
establishes no reason to prefer an equivalent explicit unique constraint, so the
OneToOne form is chosen for consistency with the model it most resembles.

Conceptual lifecycle - the only three states:

```text
pending → sent
pending → failed
```

A `pending` row is a **durable claim written before any network I/O**. It is not
an "in progress" convenience flag; it is the thing that makes the guarantee
enforceable.

Exact field names and types beyond this architecture-level shape are TASK_030
HARDEN work and must be proven against repository conventions before frozen
tests are written.

### 7.3 Claim ordering - the correctness core

1. validate **all** global configuration before touching any delivery state;
2. build and validate the deterministic payload;
3. atomically attempt to create the unique AlertDelivery claim;
4. **commit that short claim transaction before any network I/O**;
5. only the process that successfully created the claim may invoke the adapter;
6. record the terminal status (`sent` or `failed`) afterward.

Rules that fall out of this ordering:

- **never hold a database transaction open across Telegram HTTP I/O** (3.3 is
  the in-repository evidence for why this matters);
- a process that loses the claim race - observing the uniqueness violation -
  **must not call Telegram**, and must not treat losing as an error condition;
- steps 1 and 2 precede step 3 so that a configuration or payload defect can
  never consume a DealFlag's one-and-only claim.

**Implementation hazard for TASK_032 HARDEN:** step 4's guarantee is that the
claim is *committed* before the send. That is silently violated if the send path
ever runs inside an enclosing `transaction.atomic()` block - including a test
harness that wraps the command in a transaction. The frozen tests must pin the
commit-before-send ordering, not merely the presence of an `atomic()` call.

### 7.4 The accepted tradeoff, stated plainly

- a crash after the claim but before the terminal record leaves a `pending`
  row, and **that row is never retried automatically**;
- an ambiguous timeout may mean Telegram accepted the message even though
  PriceWatchPH never saw the response; that attempt is **never repeated
  automatically**, because repeating it could duplicate the external message;
- consequently a `pending` or `failed` DealFlag is permanently un-alertable in
  v1. With no manual resend (Decision I), the only recovery is deliberate
  database intervention by the operator. This is a real operational
  consequence, accepted knowingly, not an oversight.

**Duplicate suppression is prioritised over delivery completeness.** A rare
missed or ambiguous alert is acceptable because the deal feed remains the
authoritative surface and already shows every DealFlag. **Exactly-once external
delivery is not claimed and is not achievable** across a network boundary that
can fail after the peer has acted.

## 8. Failure and retry semantics

Settled by architecture:

- **A delivery failure never blocks or rolls back pricing.** Guaranteed
  structurally by running delivery in a separate command (3.3), not by
  exception handling.
- **One failing DealFlag must not abort the remaining candidates** in the same
  run; each is independently claimed and independently recorded.
- **No automatic retry of any kind** (Decision H). A `failed` row stays failed
  and causes every future run to skip that DealFlag. A `pending` row does the
  same. No retry daemon, no retry counter, no `next_retry_at`, no cooldown
  field, and no attempt-history model.
- **No manual resend** (Decision I): no admin action, no `--force`, no
  delete-and-recreate convention, no second invocation path. If real use later
  proves resends necessary, they get designed explicitly as a later feature
  rather than weakening the v1 invariant now.
- **Re-running the command is not a retry mechanism.** It only picks up
  DealFlags that have no row at all.
- **The command's exit status must reflect whether failures occurred**, so a
  future scheduler can surface a bad run.

## 9. Configuration and secrets

Bound by CLAUDE.md: secrets come from environment variables, never hardcoded,
never committed. Bound by 3.7: every value is read in `config/settings.py`.

Four configuration concerns, all read in settings, all documented in
`.env.example` with inert placeholders (3.6):

1. **Enable flag.** Follows the `ENABLE_DEMO_DATA` precedent: literal `"1"`
   only, default off, so no environment can begin sending outbound messages by
   accident.
2. **Telegram credentials.** A bot token and a single chat destination
   (Decision K - one operator, one destination, no recipient table).
3. **Activation cutoff** (Decision C). Required whenever alerts are enabled.
   Must be timezone-aware and unambiguous - an explicit-offset or UTC instant,
   parsed and validated by Phase 7. No browser-local, host-local, or implicit
   local-timezone semantics. This is consistent with the repository's existing
   three-way timezone discipline (storage UTC, `DISPLAY_TIME_ZONE`,
   `AGGREGATION_TIME_ZONE`), and the cutoff is compared against
   `DealFlag.flagged_at`, which is stored in UTC.
4. **Public application base URL** (Section 10.2). Required whenever alerts are
   enabled.

Validation rules:

- alert-specific configuration is validated **only when alerts are enabled**;
- when alerts are disabled, missing alert configuration must not break settings
  import, unrelated management commands, or unrelated tests - so validation
  must not happen at settings-import time the way `SECRET_KEY` does;
- when alerts are enabled and configuration is missing or malformed, the
  failure is loud and early - before any claim is created (Section 7.3 step 1);
- no credential value, sample token, or realistic-looking placeholder enters
  the repository; `.env.example` uses the existing `change_me` convention;
- no hardcoded `localhost` and no guessed production domain.

Exact variable names are frozen during TASK_031. Real production values are
Phase 9 (Section 14).

## 10. Privacy and security

### 10.1 Payload minimisation

The payload should carry only what identifies the opportunity: SKU
identification, price, condition, score, and the internal actionable link.

It must **not** carry any `RawListing` evidence field - `raw_title`,
`raw_price_text`, `seller`, pseudonymised seller tokens - and, per Decision J,
**must not carry `RawListing.url` or any other external source listing URL**.
The repository already treats this data as sensitive (3.9), and an outbound
message to a third-party service is precisely where that treatment matters.

### 10.2 The internal link, and why it needs configuration

The alert links to PriceWatchPH's own workflow instead: the TASK_029 route
`/deals/<deal_flag_id>/outcome` (3.12), which requires an authenticated staff
session.

A management command has **no HTTP request from which to infer the deployed
application's public origin**, so constructing an absolute URL requires the
configured public base URL from Section 9 item 4. Phase 7 owns reading it,
validating it, and constructing the link; Phase 9 owns the deployed value.

### 10.3 Telegram bot token leakage

The Telegram Bot API places the bot token **in the request URL**. This makes
ordinary diagnostic habits dangerous, and the following are hard requirements:

- **never persist the request URL** - not in the failure detail, not anywhere;
- **never log the request URL**;
- **never expose the `urllib` `Request` object, or its `repr`, as diagnostic
  text**;
- **never store or print raw transport exception text**, which can embed the
  full URL and therefore the token;
- translate every failure into sanitized, application-owned error information
  (Section 6), and store only that;
- do not needlessly echo the Telegram chat identifier in diagnostics either.

Frozen TASK_031 tests must prove the token cannot appear in raised delivery
errors, persisted failure detail, or command stdout/stderr (Section 13).

### 10.4 Outbound only

Phase 7 adds no inbound webhook, no callback URL, and no bot command handling.
An inbound surface would be a new authentication boundary and is out of scope.

## 11. Operational behavior

Proportional to a solo portfolio project:

- the command writes a concise stdout summary in the established style of
  `price_listings` ("Pricing ... complete: snapshot_identities=N
  listings_evaluated=N") - counts of candidates, sent, and failed, using the
  persisted vocabulary `pending` / `sent` / `failed`, never wording that implies
  a human received or read anything;
- per-DealFlag state is queryable in the database and visible in admin
  (Section 12), because delivery history is the diagnostic record - this is why
  no separate logging subsystem is introduced;
- **a stuck `pending` row is diagnosable** through that same persisted history
  and admin surface: it is the visible signature of a crash between claim and
  terminal record (7.4), and Section 12's admin view is what makes it
  noticeable;
- a non-zero exit status on failures (Section 8) is what a future cron entry
  will surface;
- no metrics backend, no alerting-on-the-alerter, no health endpoint.

## 12. UI and admin scope

**No React work in Phase 7.** The deal feed already surfaces DealFlags, and an
operator following an alert lands in the existing `/deals/<id>/outcome` flow
that TASK_029 shipped. A notifications UI would duplicate the deal feed.

Read-only Django admin registration for `AlertDelivery` is sufficient and
proportional: it answers "was this claimed, when, did it send, and did it fail",
and it is where a stuck `pending` row becomes visible. **No admin action that
triggers or resends a send** (Decision I) - that would be a second,
less-auditable invocation path alongside the command.

**Recipient model:** v1 is a single owner-operated channel with one configured
Telegram destination (Decision K). No recipient table, no preferences, no
subscriptions. The product has one operator - the same person who reviews the
queue and records outcomes.

## 13. Testing strategy

What eventual frozen tests should prove. **No test may perform a real Telegram
request**; the adapter is always injected.

**Eligibility**
- a DealFlag with no AlertDelivery row, flagged at or after the activation
  cutoff, is a candidate;
- **any** existing AlertDelivery row - `pending`, `sent`, or `failed` - produces
  no new send attempt on a later run;
- the activation cutoff excludes older DealFlags, and the boundary comparison is
  pinned explicitly;
- a Listing that never produced a DealFlag never alerts;
- no per-run cap behavior exists - a run with many candidates processes all of
  them (Decision D).

**Claim, uniqueness, and concurrency**
- the database enforces one AlertDelivery per DealFlag (OneToOne/unique proof),
  in the style of TASK_028's
  `test_concurrent_creation_race_yields_one_outcome_and_a_stable_conflict`;
- two concurrent claim attempts result in **exactly one injected adapter
  invocation** - the central at-most-once proof;
- the claim is **committed before** the adapter is invoked (7.3 hazard);
- configuration is validated **before** any claim row is created;
- a payload defect does not consume a DealFlag's claim.

**No-retry semantics**
- abandonment after claim leaves `pending`, and the next run does not resend;
- a failure leaves `failed`, and the next run does not resend;
- a transport timeout does not trigger any retry, in-process or on a later run.

**Payload and privacy**
- exact field set, asserted positively *and* negatively: no `RawListing` field,
  no `RawListing.url` or any external source URL, no seller value, no pseudonym
  token appears anywhere in the serialised payload;
- the internal link is constructed from the configured public base URL and the
  DealFlag id, matching the TASK_029 route shape;
- money renders as Decimal-derived strings, never floats.

**Token safety** (Section 10.3)
- the bot token cannot appear in a raised delivery error;
- the bot token cannot appear in persisted failure detail;
- the bot token cannot appear in command stdout or stderr;
- a raw `urllib` exception is never surfaced or stored verbatim.

**Telegram response handling**
- a successful Bot API response with a `Message` result records `sent`;
- a Bot API rejection, a non-success `ok`, and a malformed/unparseable response
  each record `failed` with sanitized detail.

**Command behavior**
- summary output shape; exit status on partial failure;
- one failing DealFlag does not abort the rest of the run;
- the command is a no-op, not an error, when alerts are disabled.

**Configuration**
- missing or malformed alert configuration while enabled fails loudly, before
  any claim;
- an unambiguous, timezone-aware activation cutoff is required when enabled;
- importing settings and running unrelated commands works with alerts disabled
  and no alert configuration present;
- `.env.example` stays in sync (already enforced by the frozen TASK_001 test).

**Compatibility**
- `price_listings` behavior is unchanged and still performs no network call;
- the frozen DealFlag API payload gains no field;
- DealFlag and PricePoint immutability still hold.

## 14. Phase 9 deployment boundary

| Phase 7 owns | Phase 9 owns |
|---|---|
| `send_deal_alerts` exists and is safe to schedule | the cron container, crontab entry, and schedule frequency |
| configuration is read, validated, and consumed | the real Telegram bot token and chat id |
| activation-cutoff parsing and validation | the real activation timestamp value |
| public-base-URL reading and link construction | the real deployed application URL |
| the enable flag defaults off | enabling alerts in the production environment |
| failures are recorded; exit status reflects them | operational monitoring of scheduled runs |
| all behavior proven with no network | any live smoke test against the real Bot API |

Phase 7 must not add a cron container, a crontab file, a supervisor
configuration, or a deployment-specific compose service. Section 3.8 confirms
none exists today; creating one here would pull Phase 9 forward.

## 15. Settled owner decisions

Decisions A-K are **settled** and are no longer unknowns. Nothing below may be
reopened during implementation without a new owner decision.

| # | Decision | Settled outcome |
|---|---|---|
| A | Delivery channel | **Telegram.** No email fallback, no channel registry, no multi-channel abstraction beyond the injectable seam. |
| B | HTTP client | **stdlib `urllib.request`**, HTTPS POST with JSON. No new dependency. |
| C | First-run backlog | **Environment-backed activation cutoff**; eligibility requires `flagged_at >= cutoff`. No suppression rows, no data migration. Required when enabled; timezone-aware and unambiguous. |
| D | Per-invocation maximum | **No cap in v1.** Not invented without evidence. |
| E | Transport timeout | **10 seconds, explicit.** No in-process retry loop. |
| F | Uniqueness / guarantee | **At-most-once send attempt per DealFlag.** Exactly one AlertDelivery per DealFlag via `OneToOneField` (3.10). Partial-unique-on-status is rejected as incorrect (7.1). |
| G | Definition of `sent` | Bot API request completed, response reports success, `sendMessage` returned its `Message` result. Terminology is `sent`, never `delivered`. |
| H | Automatic retry | **None.** `failed` and `pending` both permanently skip. No retry counters, `next_retry_at`, or daemon. |
| I | Manual resend | **None in v1.** No admin action, no `--force`, no delete-and-recreate. |
| J | Source listing URL | **Excluded.** No `RawListing.url` or external URL in the payload; link to `/deals/<id>/outcome` instead. |
| K | Recipient model | **Single operator, one destination.** No recipient table, preferences, or subscriptions. |

### 15.1 Remaining implementation details (no owner product decision needed)

These are resolved during task HARDEN against repository conventions, not by
further product decisions:

- exact environment-variable names for the four configuration concerns
  (TASK_031), subject to 3.6 and 3.7;
- exact AlertDelivery field names, types, status representation, and any
  supporting constraints (TASK_030);
- exact message text and formatting of the Telegram payload (TASK_031);
- exact stdout summary wording and exit-status convention (TASK_032);
- exact admin list/readonly configuration (TASK_033).

## 16. Ordered task breakdown

Four tasks, dependency-ordered. Decision C is configuration and eligibility
behavior rather than persistence shape, so it **no longer blocks TASK_030's
migration**.

**TASK_030 - AlertDelivery persistence and the unique claim**
The model, its one-per-DealFlag database guarantee, the three-state status
representation, and the migration. No networking, no payload, no command, no
eligibility query.
Schema boundary, binding: **no** retry/attempt history, **no** separate
`AlertAttempt` + `AlertDelivery` split, **no** recipient model, **no** channel
registry, **no** retry counters or cooldown timestamps. The v1 abstraction is
one durable logical delivery claim per DealFlag.
Depends on: Decisions F and K (both settled).

**TASK_031 - Payload, Telegram adapter, and configuration**
The payload builder and its privacy guarantees, the injectable adapter seam,
`alerts/telegram.py`, the sanitized failure exception, token-leakage
protections, and all four configuration concerns - enable flag, credentials,
activation cutoff parsing/validation, public base URL and link construction.
No orchestration, no eligibility query, no claiming.
Depends on: Decisions A, B, E, G, J, K, and the cutoff/base-URL semantics of C
(all settled).

**TASK_032 - `send_deal_alerts` command**
Eligibility query including the activation cutoff, configuration-validation
ordering, claim-before-send with commit ordering, claim-race losing behavior,
per-item isolation, no-retry behavior, summary output, and exit status. The
correctness core of the phase.
Depends on: TASK_030 + TASK_031, and Decisions C, D, F, H, I (all settled).

**TASK_033 - Admin visibility**
Read-only `AlertDelivery` admin registration, including making a stuck
`pending` row visible. No resend action (Decision I). Required, not optional:
Section 1 includes admin visibility in the phase goal, and Sections 11 and 12
make this the diagnostic surface for a stuck `pending` claim, so the phase is
not complete without it.

## 17. Risk tier per task

| Task | Tier | Why |
|---|---|---|
| TASK_030 | **HIGH** | Schema and migration; establishes the single database guarantee every at-most-once claim rests on. A wrong constraint is expensive to reverse once rows exist. |
| TASK_031 | **HIGH** | First outbound network code in the repository (3.4); handles secrets; the Bot API places the token in the URL (10.3); determines what data leaves the system. |
| TASK_032 | **HIGH** | Irreversible outbound side effect under at-most-once semantics; claim/commit/send ordering is genuine concurrency-correctness work; a defect means duplicate or lost alerts. |
| TASK_033 | **LOW** | Read-only admin registration over an existing model. No new behavior, no network, no schema. |

Three HIGH tasks reflect the phase's actual substance - secrets, irreversible
outbound effects, and schema - not ceremony inertia. TASK_033 is deliberately
LOW and must not inherit HIGH-tier ceremony because its siblings are HIGH.

## 18. Workflow and validation gates per task

**TASK_030 - HIGH**
Workflow: HARDEN → frozen acceptance tests → owner approval → IMPLEMENT →
independent REVIEW → independent VALIDATE → COMMIT.
Gates: targeted model/constraint tests including the one-per-DealFlag proof;
`makemigrations --check --dry-run` clean; `manage.py check` clean; full backend
suite.

**TASK_031 - HIGH**
Workflow: HARDEN → frozen acceptance tests → owner approval → IMPLEMENT →
independent REVIEW → independent VALIDATE → COMMIT.
Gates: targeted payload/adapter/configuration tests, including the negative
no-RawListing-leakage assertions, the token-leakage assertions, and the
no-real-network guarantee; full backend suite (Section 19); `manage.py check`
clean.

**TASK_032 - HIGH**
Workflow: HARDEN → frozen acceptance tests → owner approval → IMPLEMENT →
independent REVIEW → independent VALIDATE → COMMIT.
Gates: targeted command/eligibility/concurrency/no-retry tests; the
exactly-one-adapter-invocation proof under concurrent claims; the
commit-before-send ordering proof; `price_listings` compatibility tests re-run;
full backend suite; `makemigrations --check --dry-run` clean.

**TASK_033 - LOW**
Workflow: IMPLEMENT → targeted validation → review diff → COMMIT.
Gates: targeted admin-registration test; `manage.py check` clean.
No frozen-test ceremony, no independent reviewer or validator agent, no
full-suite run unless the targeted gates surface something unexpected.

Frontend gates appear nowhere in this phase: Section 12 establishes Phase 7
touches no frontend file, so `npm test` / lint / build are not phase gates. They
become relevant only if a task unexpectedly touches `frontend/`.

## 19. Dependencies justifying full-suite runs

Full backend suite is justified for TASK_030, TASK_031, and TASK_032 - and *not*
as a default:

- **TASK_030** adds a migration.
  `tests/test_task_001_bootstrap.py::test_no_missing_migrations` is
  repository-wide, and a new model in a new app changes `INSTALLED_APPS`, which
  every test loads. A model-local run cannot prove that.
- **TASK_031** touches `config/settings.py` and `.env.example`, bound by the
  bidirectional frozen test in 3.6 and by the settings-only convention in 3.7.
  Settings are imported by the entire suite, so a settings change that breaks
  import breaks everything; only a full run demonstrates it did not. The
  "unrelated commands still work with alerts disabled" requirement in Section 9
  is itself a whole-suite claim.
- **TASK_032** introduces a command that reads DealFlag state written by the
  pricing path. The claim "pricing is unchanged and still performs no network
  call" is a claim about `pricing/` tests, not `alerts/` tests, so the pricing
  suite must run.
- **TASK_033** does **not** justify a full suite. Admin registration is covered
  by targeted tests plus `manage.py check`, with precedent in
  `pricing/tests/test_task_022_operational_pricing.py`.

Frontend suite runs are not justified by any task in this phase (Section 18).
