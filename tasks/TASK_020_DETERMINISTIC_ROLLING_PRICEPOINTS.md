# TASK_020 — Build deterministic rolling PricePoint snapshots

## 1. Goal

Build the reusable Phase 5 pricing service that turns eligible derived
`Listing` observations into one sealed, auditable rolling `PricePoint` for a
specific `(Sku, condition, as-of Manila day)`.

TASK_020 owns baseline eligibility, temporal population, Decimal aggregation,
and idempotent PricePoint creation only. It does not score Listings, create
DealFlags, expose a management command, or perform scheduling.

## 2. Authority and dependencies

This task follows:

- committed `CLAUDE.md` repository constraints;
- `docs/05_PLANNING.md` Sections 4–7, 12, and 14;
- TASK_005 Manila-day bucketing;
- TASK_013 honest nullable Listing facts;
- TASK_014 and TASK_017 trusted resolution semantics; and
- TASK_019 auditable, immutable PricePoint storage.

The frozen TASK_019 specification and tests remain authoritative. TASK_020
uses their schema and immutability guarantees without weakening or redesigning
them.

## 3. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_020_DETERMINISTIC_ROLLING_PRICEPOINTS.md`
- `pricing/tests/test_task_020_rolling_pricepoints.py`

After owner approval, neither artifact may be modified to make implementation
pass. A contradiction stops implementation for owner correction.

### IMPLEMENT files allowed

- `pricing/baselines.py`

No model, admin, migration, management-command, ingestion, resolver, catalogue,
outcome, dependency, Docker, planning, prior task, or prior frozen-test file is
in scope. TASK_020 requires no schema change or migration.

## 4. Stable service API

Add one reusable internal pricing service:

```python
build_pricepoint(*, sku: Sku, condition: str, as_of_day: date) -> PricePoint | None
```

`as_of_day` is an explicit Manila calendar date. Deterministic aggregation must
not read the wall clock to choose its effective day. Wall-clock time is used
only to truthfully populate `calculated_at` when a new snapshot is inserted.

The service returns:

- the existing PricePoint when the identity already exists;
- `None` when the identity does not exist and there are zero eligible
  observations; or
- the newly created PricePoint when at least one eligible observation exists.

Private quantile, boundary, and query helpers are implementation details and
are not frozen API.

## 5. Baseline eligibility

A Listing contributes exactly one price when all of these facts hold:

```text
sku = requested sku
condition = requested non-null condition
price IS NOT NULL
observed_at IS NOT NULL
price_kind = "asking"
resolution_method IN ("exact_alias", "human_confirmed")
resolution_confidence = Decimal("1.0000")
```

The method check establishes trust; confidence is a consistency guard and
cannot independently make another method eligible.

Exclude realised and NULL price kinds, missing facts, unresolved and
reviewed-unresolved Listings, and `fuzzy_match`. Do not inspect or special-case
`Source.name`. A synthetically constructed Listing whose Listing-layer facts
are eligible remains eligible even if its source has a historically familiar
name; current `personal_records` output is excluded naturally because its
facts describe realised trades.

Each eligible Listing counts once. Similar titles, equal prices, shared
sellers, repeated-looking advertisements, and different sources are not
weighted, collapsed, deduplicated, or trimmed.

The pricing service reads `Listing` and `Sku` only. It must not read RawListing
payload, seller, source, title, or identifiers to decide membership.

## 6. Manila temporal population

For explicit as-of Manila day `D`, define:

```text
window_start_day = D - 90 days
window_end_day = D
population = [window_start_day, window_end_day)
```

Convert midnight at each bound in
`settings.AGGREGATION_TIME_ZONE` (`Asia/Manila`) to aware instants. Filter the
UTC-stored `Listing.observed_at` using:

```text
observed_at >= aware Manila midnight at D-90
observed_at <  aware Manila midnight at D
```

Do not use the UTC calendar date or a database `__date` lookup whose meaning
depends on the connection timezone.

Consequences:

- every instant on `D-90` in Manila is included;
- `D-91` is excluded;
- every instant on `D` is excluded;
- a Listing cannot affect its own same-day baseline; and
- same-day Listings for the identity reuse the same sealed snapshot.

Persist the date values themselves in `window_start_day` and
`window_end_day`.

## 7. Deterministic Decimal calculation

### 7.1 Context and persistence precision

All input and intermediate arithmetic uses `Decimal`; no float conversion is
permitted.

Run calculation and quantization inside an explicit local Decimal context:

```text
precision = 28 significant digits
rounding = ROUND_HALF_EVEN
```

Twenty-eight digits safely exceed the supported 12-significant-digit Listing
price input and 14-significant-digit persisted aggregate bounds, leaving
fourteen guard digits for interpolation and deviation arithmetic. It also
prevents mutable process-global Decimal settings from changing results.

Persist with:

```python
Decimal("0.0001")
ROUND_HALF_EVEN
```

### 7.2 Type 7 quantiles

Sort eligible Decimal prices ascending. For percentile `p`:

```text
h = (n - 1) * p
lower = floor(h)
upper = ceil(h)
Q(p) = x[lower] + fractional(h) * (x[upper] - x[lower])
```

Compute:

- `median = Q(Decimal("0.50"))`;
- `p25 = Q(Decimal("0.25"))`; and
- `p75 = Q(Decimal("0.75"))`.

For one observation, all three equal its price.

### 7.3 Raw MAD

Calculate raw, unscaled median absolute deviation:

1. retain the exact unquantized Type 7 median;
2. compute `abs(price - median)` for every input;
3. sort the deviations; and
4. take their Type 7 median.

Quantize only the persisted median, quartiles, and MAD. Do not apply 1.4826,
0.6745, modified-z normalization, IQR fallback, epsilon, clipping, or float.

## 8. Snapshot persistence

For zero eligible observations and no existing identity, return `None` and
write nothing.

For one or more observations, insert one PricePoint with:

```text
sku = requested sku
condition = requested condition
day = as_of_day
median/p25/p75 = four-place aggregates
n_listings = exact eligible row count
mad = four-place raw MAD
window_start_day = as_of_day - 90 days
window_end_day = as_of_day
calculated_at = timezone-aware insertion/calculation time
calculation_contract_version = "asking_price_baseline_v1"
```

The identifier `asking_price_baseline_v1` permanently names this complete
contract: Listing-fact eligibility, 90-day Manila window, one-row-one-vote
policy, Type 7 quartiles, raw MAD, explicit Decimal context, and four-place
half-even persistence. Its meaning must never change; a future policy uses a
new identifier.

One through four observations still produce a truthful descriptive snapshot.
MAD equal to zero still produces a snapshot. TASK_021, not TASK_020, decides
whether a snapshot is usable for scoring.

All five TASK_019 audit fields must be populated together on every newly
created TASK_020 snapshot. Calculation failure must leave no partial row.

## 9. Sealed idempotency and concurrency

The `(sku, condition, day)` database uniqueness constraint is authoritative.

The service must check for and return an existing PricePoint before reading or
recalculating the population. This applies to both auditable TASK_020 rows and
truthful all-NULL legacy rows. It must never update, delete/recreate, compare,
repair, or bypass the TASK_019 immutable evidence.

When no row exists initially:

1. read and calculate the population;
2. attempt one complete insert inside a transaction/savepoint; and
3. if another transaction wins the same unique identity, recover from that
   identity conflict and return the now-existing row.

Django `get_or_create()` with complete creation defaults is an acceptable
narrow implementation because it uses the database identity and never updates
an existing object. An equivalent explicit savepoint/`IntegrityError` recovery
is also acceptable. Tests freeze behavior, not the internal helper choice.

Do not use `update_or_create()`, conflict-update SQL, trigger bypasses, advisory
catalogue versions, or a process-local lock. Unexpected calculation or insert
errors propagate, and no partial PricePoint may remain.

Later-arriving eligible data cannot rewrite a snapshot already sealed for that
day. It may affect only a different identity/day created later.

## 10. Boundaries and non-goals

TASK_020 must not:

- create, update, or delete a DealFlag or Outcome;
- read, update, or delete RawListing;
- update any Listing, Sku, SkuAlias, or Source;
- inspect Source names or RawListing provenance for eligibility;
- implement scoring, the `-3.0000` threshold, or `asking_price_mad_v1`;
- decide snapshot usability for DealFlag creation;
- expose a management command or scheduler;
- implement TASK_008, cron, retries, parallel workers, or run bookkeeping;
- create a cache, materialized view, policy model, or membership table;
- seed catalogue or market data;
- add source/seller weighting, deduplication, or outlier policy;
- change TASK_019 schema, triggers, admin, or immutability; or
- claim empirical Philippine market accuracy from synthetic tests.

The implementation should use a bounded number of set-based queries and avoid
per-Listing related-object lookup. No caching or premature optimization is
required.

## 11. Acceptance criteria — frozen

The authoritative acceptance module is:

```text
pricing/tests/test_task_020_rolling_pricepoints.py
```

It uses synthetic fixtures only and freezes:

### Eligibility and population

- exact-alias and human-confirmed trusted Listings contribute;
- every missing/untrusted fact is excluded;
- `Source.name` is not an eligibility allowlist;
- repeated-looking eligible observations each count once;
- `D-90` is included, `D-91` and `D` are excluded;
- UTC instants are classified by Manila midnight; and
- same-day observations cannot affect their own baseline.

### Statistics and Decimal rules

- odd/even Type 7 median;
- interpolated Type 7 quartiles;
- one-observation behavior;
- raw unscaled MAD;
- four-place persistence;
- explicit-context independence from mutable global Decimal state;
- `ROUND_HALF_EVEN`; and
- absence of a float/FloatField calculation path.

### Persistence and lifecycle

- zero observations create no row;
- one through four observations create truthful rows;
- zero MAD creates a row;
- all audit metadata, count, bounds, version, and calculation time are truthful;
- reruns return the same row without mutation;
- later data cannot rewrite an existing snapshot;
- an existing legacy row is reused unchanged;
- concurrent requests converge on one row; and
- unexpected insert failure leaves no partial row.

### Component boundaries

- no RawListing or Listing mutation;
- no DealFlag or Outcome creation; and
- no hidden source/provenance read is required.

Parameterized cases collect separately under pytest. Tests freeze deterministic
contract correctness only, not market coverage or accuracy.

## 12. Frozen compatibility

TASK_020 preserves TASK_019:

- PricePoint audit metadata completeness and numeric bounds;
- all-NULL legacy compatibility;
- PricePoint and DealFlag immutability;
- one PricePoint identity and one DealFlag per Listing;
- arbitrary legacy DealFlag reasons; and
- view-only pricing evidence admin.

No prior task specification, frozen test, model, migration, or production file
is modified during HARDEN.

## 13. Validation

During IMPLEMENT, rebuild/recreate or bind-mount the application source as
required, then run:

```text
docker compose exec web pytest -v pricing/tests/test_task_020_rolling_pricepoints.py
docker compose exec web pytest -v pricing/tests/test_task_019_pricing_evidence.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
git diff --check
git diff --cached --check
```

Implementation validation must use PostgreSQL 16 and include the concurrency
case. No migration is expected. The dedicated and complete suites must pass,
migration drift must report `No changes detected`, and frozen artifact hashes
must remain unchanged.

No TASK_020 implementation is approved until this specification and its frozen
acceptance module receive explicit owner approval.
