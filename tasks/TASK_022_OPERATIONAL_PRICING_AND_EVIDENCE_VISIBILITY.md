# TASK_022 - Operational pricing invocation and evidence visibility

## 1. Goal

Provide the smallest operational entry point that invokes the committed
TASK_020 and TASK_021 pricing services in the required order:

```text
python manage.py price_listings
```

TASK_022 owns Manila-run-day selection, bounded Listing selection, current-day
PricePoint invocation, whole-run failure behavior, a concise console summary,
and useful read-only Django-admin evidence lists. It does not own baseline or
scoring policy and must not duplicate either service.

## 2. Authority and dependencies

This task follows:

- committed `CLAUDE.md` repository constraints;
- `docs/05_PLANNING.md` Sections 4, 9, 13, 14, and 17;
- TASK_014 and TASK_017 `Listing.resolved_at` transition semantics;
- TASK_015 management-command and transaction conventions;
- TASK_019 immutable PricePoint and DealFlag evidence and read-only admin;
- TASK_020 `build_pricepoint(...)`; and
- TASK_021 `score_listing(...)`.

The owner has additionally approved that v1 never creates a missing historical
PricePoint merely because an older Listing becomes eligible later. A later
resolution may produce a historical DealFlag only when the PricePoint for the
Listing's original Manila observation day already exists.

The prior TASK_019 through TASK_021 specifications and frozen tests remain
authoritative. TASK_022 orchestrates their public services without reopening
their schema, eligibility, arithmetic, usability, threshold, identity, or
immutability contracts.

## 3. Files

### HARDEN artifacts - frozen before implementation

- `tasks/TASK_022_OPERATIONAL_PRICING_AND_EVIDENCE_VISIBILITY.md`
- `pricing/tests/test_task_022_operational_pricing.py`

After owner approval, neither artifact may be changed to make implementation
pass. A contradiction stops implementation for owner correction.

### IMPLEMENT files allowed after approval

- `pricing/management/__init__.py`
- `pricing/management/commands/__init__.py`
- `pricing/management/commands/price_listings.py`
- `pricing/admin.py`

No model, migration, baseline, scoring, bucketing, Listing, RawListing,
catalogue, source, outcome, ingestion, resolver, planning, prior task, or prior
frozen-test file is in scope. Repository inspection confirms TASK_022 needs no
schema change or migration.

## 4. Command and CLI contract

Add exactly this ordinary Django management command:

```text
python manage.py price_listings [--day YYYY-MM-DD]
```

The command:

- accepts no positional arguments;
- accepts one optional `--day` in strict ISO `YYYY-MM-DD` form;
- reads no stdin and prompts for no input;
- performs no network access; and
- uses Django's ordinary successful and non-zero exception behavior.

Invalid calendar input raises `CommandError` with a clear reference to
`YYYY-MM-DD`. A run day later than the current Manila calendar day is rejected
before any service call or write because v1 cannot create future evidence.

## 5. Run-day semantics

Let `D` be the command's one Manila run day.

When `--day` is present, parse it as `D` without consulting the process-local
timezone or coercing it through a timestamp. The explicit value makes tests,
manual operation, and same-day reruns deterministic.

When `--day` is absent, derive `D` once from `timezone.now()` converted to
`settings.AGGREGATION_TIME_ZONE`. Do not use the UTC calendar date or Django's
storage `TIME_ZONE`. The one derived value is reused for the whole invocation,
including if the wall clock crosses midnight during processing.

A past explicit day is a replay, not authorization to construct evidence that
was missed on that historical day. During a past-day replay the command performs
the scoring phase against already-existing evidence but calls no
`build_pricepoint()`. This is the smallest behavior that permits deterministic
re-evaluation while preserving the owner-approved no-retrospective-PricePoint
rule.

Only `D` equal to the current Manila day has a snapshot-creation phase.

## 6. Manila-day query bounds

For database selection, construct one aware half-open interval for D in the
configured aggregation timezone:

```text
[Manila D 00:00, Manila (D + 1) 00:00)
```

Django may convert these aware bounds to UTC for querying. Do not use a UTC
`__date` lookup. The lower bound is inclusive and the next Manila midnight is
exclusive.

## 7. Current-day PricePoint identity selection

On a current-day invocation only, derive candidate identities from current
`Listing` facts. Select Listings whose `observed_at` falls in D's Manila
half-open interval, then take distinct non-null:

```text
(sku_id, condition)
```

Process identities in ascending `(sku_id, condition)` order. For every selected
identity, load its `Sku` and call exactly:

```python
build_pricepoint(sku=sku, condition=condition, as_of_day=D)
```

The operational selector checks only the two non-null fields required by that
service API. It deliberately does not duplicate TASK_020 or TASK_021 price,
price-kind, resolution-method, confidence, or sample eligibility policy.
Therefore an identity may be requested by an ineligible current-day Listing;
`build_pricepoint()` remains authoritative for whether an eligible historical
population exists and whether a row is returned.

This rule does not:

- inspect RawListing;
- inspect or hardcode Source names;
- scan arbitrary catalogue SKUs;
- create snapshots for identities with no current-day Listing trigger;
- create a PricePoint for an earlier observation day; or
- create any PricePoint during a past-day replay.

Existing `(sku, condition, D)` snapshots are reused by TASK_020 without
mutation. A zero-observation identity still produces no row under TASK_020.

## 8. Operational Listing scoring selection

After the complete snapshot phase, evaluate the union of Listings satisfying
either event predicate:

```text
observed_at falls on Manila day D
OR
resolved_at falls on Manila day D
```

Deduplicate the union at the database row level and process it in ascending
`Listing.pk` order.

The observed-day arm evaluates the Listings for which a D snapshot may have
just been created. The resolved-day arm is the existing bounded mechanism for
new or changed automatic resolution and human confirmation/correction:
TASK_014 and TASK_017 refresh `resolved_at` for those transitions and preserve
it on unchanged reruns. No new marker, cursor, watermark, or full-table rescan
is required.

Call exactly this service for every selected Listing:

```python
score_listing(listing=listing)
```

Do not pre-filter or duplicate scoring eligibility. TASK_021 remains
authoritative for trusted resolution state, price facts, own-day PricePoint
selection, snapshot usability, score arithmetic, threshold, and DealFlag
idempotency.

A Listing present in both event arms is evaluated once. An older Listing whose
resolution changes on D is evaluated, but its historical identity is never
passed to `build_pricepoint()`. If its original-day PricePoint is absent,
TASK_021 returns `None`; the command creates no historical PricePoint, no
historical DealFlag, and does not substitute D or another snapshot.

Listings outside both bounded event predicates are not rescanned. An operator
may replay their relevant day explicitly, subject to the replay rule in Section
5. TASK_022 adds no durable processed state because TASK_008 remains deferred.

## 9. Ordering, transaction, and failure policy

One invocation is one outer database transaction:

1. validate and freeze D;
2. on current D, process every selected PricePoint identity in stable order;
3. process every selected Listing in stable order;
4. commit all new immutable evidence; and
5. print the success summary only after all service calls return successfully.

All baseline calls finish before the first scoring call. This lets a Listing
observed on D consume its D snapshot while TASK_020 still excludes all D
observations from that snapshot's `[D-90, D)` population.

Unexpected service or database exceptions are not caught, converted to
success, logged-and-continued, or broadly swallowed. They propagate through
Django's normal non-zero command behavior. The outer transaction rolls back
every PricePoint and DealFlag inserted by that failed invocation, including
successful earlier items. Pre-existing sealed evidence and all input rows stay
unchanged.

TASK_020 and TASK_021 retain their narrow concurrency behavior inside the outer
transaction. A retry starts the same deterministic selection again and safely
reuses every pre-existing snapshot and flag. TASK_022 defines no partial-success
contract, retry loop, rejection record, parallel worker, or error suppression.

## 10. Success output

After a successful commit-ready batch, write exactly one concise stdout line:

```text
Pricing 2026-08-09 complete: snapshot_identities=2 listings_evaluated=3
```

The date and integers vary with the invocation. `snapshot_identities` is the
number of current-day `(sku, condition)` identities passed to
`build_pricepoint()`; it is zero on a past-day replay. `listings_evaluated` is
the number of distinct Listings passed to `score_listing()`.

These are invocation counts, not claims that rows were created, samples were
representative, or flags qualified. No output is printed on a failed batch.
There is no stderr success output, durable summary, analytics contract,
per-source breakdown, rejection report, scheduler health, or notification.

## 11. TASK_008 boundary

TASK_022 writes no persistent run, scheduler, source-health, cursor, watermark,
or rejection state. In particular it does not update
`Source.last_successful_fetch`; that ingestion-health field and scheduler-facing
run reporting remain owned by deferred TASK_008.

The single stdout completion line is local operational feedback only. It does
not redefine TASK_008's per-ingestion rows-read, rows-written, rejection, or
success-timestamp contract.

## 12. Read-only admin evidence visibility

TASK_019's no-add, no-change, no-delete, no-action, all-fields-read-only admin
contract remains unchanged and authoritative. TASK_022 adds only useful
changelist visibility over persisted evidence.

`PricePointAdmin` exposes these persisted columns:

```text
sku
condition
day
median
mad
n_listings
window_start_day
window_end_day
calculation_contract_version
calculated_at
```

It permits ordinary admin filtering by `condition`, `day`, and
`calculation_contract_version`, selects the related SKU with the list query,
and orders newest day first with stable SKU and condition tie-breakers.

`DealFlagAdmin` exposes:

```text
listing
score
baseline_pricepoint
reason
flagged_at
```

It permits filtering by `reason` and `flagged_at`, selects the linked Listing,
PricePoint, and PricePoint SKU with the list query, and orders newest flag first
with primary-key tie-breaking.

Admin rendering reads persisted evidence only. It never invokes baseline or
scoring services and provides no custom calculation, editable field, bulk
action, alert, dashboard, or non-admin frontend.

## 13. Preserved state and write boundary

A successful command may insert only the PricePoints and DealFlags returned by
the approved TASK_020 and TASK_021 services. It must not create, update, or
delete:

- RawListing or Swap;
- Listing;
- Sku or SkuAlias;
- Source, including `last_successful_fetch`;
- Outcome;
- existing PricePoint or DealFlag evidence; or
- any run-history, scheduler, notification, or frontend state.

Operational queries may read `Listing`, `Sku`, and existing pricing evidence.
They must not join RawListing or Source to select pricing policy.

## 14. Acceptance criteria - frozen

The authoritative acceptance module is:

```text
pricing/tests/test_task_022_operational_pricing.py
```

It freezes focused orchestration behavior without repeating TASK_020 or
TASK_021 arithmetic suites.

### Command and run day

- the `price_listings` command is registered and handles an empty database;
- explicit ISO D is parsed and used unchanged;
- omitted D uses the Manila date rather than the UTC date;
- invalid input and a future day fail clearly before services or writes;
- a past explicit day performs scoring only and never calls the baseline
  service; and
- successful output contains only the approved concise invocation counts.

### Snapshot selection and orchestration

- current-day identities come only from observed-on-D Listing facts;
- null identities are skipped and distinct identities use stable ordering;
- no RawListing or Source identity is pricing policy;
- every build call uses `as_of_day=D` and no historical day;
- all build calls precede all score calls; and
- a complete rerun reuses sealed evidence without duplicates.

### Scoring selection and historical boundary

- observed-on-D and resolved-on-D Listings are evaluated in stable deduplicated
  order;
- Listings outside both event arms are not evaluated;
- no eligibility predicate is duplicated before `score_listing()`;
- a later-resolved historical Listing uses an already-existing original-day
  PricePoint; and
- missing original-day evidence produces neither historical PricePoint nor
  DealFlag and never substitutes D evidence.

### Failure, retry, and component boundaries

- an unexpected baseline or scoring failure propagates, prints no success
  summary, and rolls back every earlier write from the invocation;
- retry after failure completes once without rewriting or duplication;
- RawListing, Listing, Sku, SkuAlias, Source, Swap, and Outcome state remains
  unchanged;
- no TASK_008 durable state is created or updated; and
- no schema change or migration is required.

### Admin evidence

- PricePoint and DealFlag changelists expose the approved persisted evidence,
  filters, relation loading, and deterministic ordering;
- TASK_019 view-only permissions remain unchanged; and
- rendering either evidence changelist never invokes a calculation service.

The frozen TASK_019, TASK_020, and TASK_021 suites remain compatibility
authority and must pass unchanged.

## 15. Explicit non-goals

TASK_022 does not implement or scaffold:

- baseline membership, quantile, MAD, usability, score, threshold, or reason
  logic;
- historical PricePoint backfill;
- full-table historical rescoring;
- a new selection marker, cursor, watermark, or model field;
- schema changes or migrations;
- cron installation, deployment, TASK_008, durable run history, source health,
  scheduler summaries, retries, parallelism, background workers, Celery,
  Redis, or a broker;
- alerts, notifications, Outcome workflow, dashboards, APIs, or a frontend;
- ingestion, capture, resolver, catalogue, source, or RawListing changes;
- source/seller weighting, deduplication, or market-accuracy claims; or
- modification of any prior task, migration, or frozen acceptance test.

## 16. Validation

During HARDEN, run the frozen TASK_022 module against the current production
code and record the expected failures caused by the absent command/admin
behavior. Also run unchanged TASK_021, TASK_020, and TASK_019 suites for
compatibility.

During IMPLEMENT, required repository-root validation remains:

```text
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
```

No TASK_022 production behavior is implemented during HARDEN.

## 17. Remaining decisions

No unresolved product or schema decision blocks TASK_022 implementation.
Command package creation and the admin changelist declarations are technical
implementation work within this frozen contract.
