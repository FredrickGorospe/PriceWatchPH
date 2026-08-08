# Phase 5 Planning — Baseline Pricing and Deal Scoring

## 1. Status and authority

This document defines the Phase 5 product boundary after completion of Phase 3
deterministic resolution and Phase 4 human review and catalogue curation. It is
a planning artifact only. It does not implement pricing behavior, create a
migration, create a task specification, or establish frozen acceptance tests.

The contracts in Sections 5–9 were approved by the owner before this document
was written. They supersede the historical description of `PricePoint` as a
daily-only aggregate where that wording conflicts with the sealed rolling
snapshot definition below. Historical planning remains useful context but does
not override this more precise contract.

Proposed task identifiers and boundaries in Section 14 are planning order, not
frozen task contracts. Each task must still be hardened with owner-approved
failing acceptance tests before implementation.

## 2. Phase 5 objective

Phase 5 turns trustworthy asking-price `Listing` observations into reproducible
per-SKU, per-condition rolling baseline snapshots and records a deal candidate
when a Listing is at least three raw median-absolute-deviation units below its
applicable baseline.

The governing flow is:

```text
eligible derived Listings
    -> sealed PricePoint for (SKU, condition, as-of Manila day)
    -> deterministic MAD-unit score for a Listing on that day
    -> immutable DealFlag when score <= -3.0000
```

Every persisted judgement must remain explainable after later Listings,
catalogue decisions, calculation policies, or application code change.

The initial output is a baseline of captured asking listings. Phase 5 does not
claim that the current data is representative of the complete Philippine PC
component market.

## 3. Confirmed dependencies

Phase 5 builds on these completed capabilities:

- TASK_005 established `Listing.observed_at`, `price_kind`, trade provenance,
  and Manila-day bucketing semantics without making the pricing engine read
  `RawListing` directly.
- TASK_013 permits honest `NULL` price and condition and provides the explicit
  unresolved resolution state.
- TASK_014 derives exactly one `Listing` per immutable `RawListing`, performs
  exact curated-alias resolution, and records trusted exact matches with
  confidence `1.0000`.
- TASK_015 provides rerunnable operational resolution.
- TASK_016–TASK_018 provide durable unresolved review, human confirmation, and
  curated alias handling while protecting human-confirmed state.
- Existing `PricePoint`, `DealFlag`, and `Outcome` models provide schema
  scaffolding and frozen historical compatibility constraints.
- PostgreSQL 16, Django 5.2, UTC timestamp storage, and the configured
  Asia/Manila aggregation timezone are already locked repository constraints.

No upstream capture enhancement is a prerequisite. The currently approved
production write paths guarantee no baseline-eligible Listings, but synthetic
PostgreSQL fixtures can establish deterministic pricing correctness without
weakening eligibility merely to manufacture live output.

Phase 2 and TASK_008 remain deferred. Phase 5 does not require an approved
automated source, cron deployment, source-health semantics, or persistent run
bookkeeping.

## 4. Component boundaries

### 4.1 Pricing engine owns

The pricing engine owns:

- selecting baseline-eligible `Listing` rows using Listing-layer facts;
- assigning observations to Manila calendar days;
- calculating deterministic Type 7 quantiles and raw MAD with `Decimal` only;
- creating sealed rolling `PricePoint` snapshots;
- determining whether a snapshot is usable for scoring;
- scoring an eligible Listing against the snapshot for its own observation
  day;
- creating at most one immutable `DealFlag` for a qualifying Listing; and
- exposing an ordinary Django management command for explicit operation.

It reads `Listing` and `Sku`. It writes `PricePoint` and `DealFlag` only.

### 4.2 Pricing engine must not own

Phase 5 must not:

- read, edit, delete, or reinterpret `RawListing`;
- resolve or re-resolve titles;
- create or mutate `Sku` or `SkuAlias`;
- infer a missing SKU, price, condition, observed time, price kind, trade side,
  location, or confidence;
- use `Source.name` as a pricing eligibility rule;
- mutate a sealed `PricePoint` or historical `DealFlag`;
- decide whether a human acted on a flag or write `Outcome`;
- send alerts or notifications;
- implement a dashboard or non-admin frontend;
- implement TASK_008, run-history models, source health, cron, retries,
  background workers, Celery, Redis, or a message broker;
- add source weighting, seller weighting, deduplication, repeated-listing
  collapse, or outlier trimming;
- use float arithmetic, `FloatField`, external statistical services, web
  search, an API, an LLM, or machine-learned pricing; or
- claim empirical market accuracy from synthetic fixtures.

The Django admin may display pricing evidence but must not calculate it during
a web request or provide generic mutation of sealed rows.

## 5. Baseline eligibility contract

A `Listing` contributes one observation to the v1 asking-price population only
when all of these facts hold:

```text
sku IS NOT NULL
price IS NOT NULL
condition IS NOT NULL
observed_at IS NOT NULL
price_kind = "asking"
resolution_method IN ("exact_alias", "human_confirmed")
resolution_confidence = Decimal("1.0000")
```

The confidence check is a consistency guard on an already-approved trusted
resolution method. Confidence alone cannot make `fuzzy_match`, `unresolved`, or
another method eligible.

The population explicitly excludes:

- `price_kind=NULL`;
- realised prices and any trade side;
- current `personal_records` observations;
- missing SKU, price, condition, or observed time;
- unresolved and reviewed-unresolved Listings; and
- `fuzzy_match` unless a future separately approved contract makes that method
  trustworthy.

Eligibility is expressed entirely from `Listing` facts. It must not special
case `manual_capture`, `personal_records`, or another `Source.name`.

Each eligible Listing counts once. V1 does not weight by source or seller,
deduplicate similar content, collapse repeated advertisements, or trim apparent
outliers. This is a deliberate pilot limitation, not a claim that every row is
an independent market participant.

## 6. PricePoint semantic and lifecycle contract

### 6.1 Snapshot identity

One `PricePoint` is one sealed rolling-baseline snapshot for:

```text
(Sku, condition, as-of Manila calendar day)
```

The existing identity remains:

```text
UNIQUE (sku, condition, day)
```

`day` is the effective/as-of Manila day. It does not mean the statistics are
limited to observations occurring on that day.

There is at most one authoritative v1 snapshot for a SKU and condition on a
given Manila day. V1 has no intra-day versions.

### 6.2 Temporal population

For as-of day `D`, the population is:

```text
[D - 90 Manila calendar days, D)
```

The lower bound is inclusive and the upper bound is exclusive. These are
exactly the 90 complete Manila dates from `D-90` through `D-1`.

The entire current day is excluded. Consequently:

- a target Listing cannot influence its own baseline;
- all Listings observed on the same day use the same evidence;
- same-day processing order cannot change the snapshot; and
- one sealed daily snapshot remains coherent.

The temporal bounds are whole Manila dates, so Phase 5 requires date-valued
lower-inclusive and upper-exclusive audit fields rather than timestamp-valued
bounds.

The 90-day duration is a v1 pilot policy, not an empirically calibrated optimum.

### 6.3 Sealed lifecycle

A valid Phase 5 PricePoint is immutable immediately after insertion:

- a rerun for an existing `(sku, condition, day)` reuses the existing row;
- no rerun recomputes or overwrites it;
- later observations, corrections, eligibility changes, or catalogue changes
  do not rewrite historical snapshots; and
- later evidence may affect only later-day snapshots.

Immutability must cover ordinary model saves/deletes, bulk ORM writes, Django
admin, and direct PostgreSQL `UPDATE` or `DELETE`. Application-level errors are
useful, but PostgreSQL enforcement is the authoritative boundary.

### 6.4 Persisted audit evidence

A valid Phase 5 PricePoint must persist:

- `median`;
- `p25`;
- `p75`;
- `n_listings`;
- raw unscaled MAD;
- the lower-inclusive population date;
- the upper-exclusive population date;
- calculation time; and
- a stable calculation-contract version.

The calculation-contract identifier must permanently identify the approved
eligibility, temporal-population, quantile, MAD, precision, and rounding rules.
It must never silently change meaning.

V1 does not persist member-level snapshot input rows. The audit contract is the
exact aggregate evidence used for scoring, not permanent membership storage.

## 7. Statistical contract

### 7.1 Deterministic Decimal context

Every input and intermediate value is `Decimal`. No Python float may enter the
calculation path.

Implementation must use an explicit deterministic Decimal context rather than
depending on mutable process-global defaults. Persisted baseline statistics are
quantized with:

```python
Decimal("0.0001")
ROUND_HALF_EVEN
```

### 7.2 Type 7 quantiles

For ascending sorted prices `x` and percentile `p`:

```text
h = (n - 1) * p
lower = floor(h)
upper = ceil(h)
Q(p) = x[lower] + fractional(h) * (x[upper] - x[lower])
```

Use:

```text
median = Q(0.50)
p25 = Q(0.25)
p75 = Q(0.75)
```

For `n=1`, all three equal the sole observation.

### 7.3 Median absolute deviation

MAD is raw and unscaled:

1. calculate the exact Type 7 median of eligible prices;
2. calculate each absolute deviation from that median; and
3. take the Type 7 median of those deviations.

Do not apply `1.4826`, `0.6745`, modified-z scaling, or another normalization
factor.

Persist `median`, `p25`, `p75`, and MAD to four decimal places. Type 7
interpolation over two-decimal Listing prices can produce sub-cent aggregates,
so retaining four places is part of truthful deterministic evidence rather
than a change to source-money precision.

### 7.4 Sample-size and zero-MAD behavior

A snapshot is usable for scoring only when:

```text
n_listings >= 5
MAD > 0
all Phase 5 audit metadata is present
calculation-contract version is recognized
```

If the population contains zero observations, create no PricePoint because the
statistics are undefined.

For one through four observations, persist the truthful descriptive snapshot
but do not score and create no DealFlag.

For MAD equal to zero, persist the truthful snapshot but do not score and create
no DealFlag. Do not substitute epsilon, fall back to IQR, or fabricate a zero
score.

Five observations are only the v1 pilot minimum. They do not establish a
representative market sample.

## 8. Deal score contract

For a usable PricePoint, calculate from the values persisted on that PricePoint:

```text
score = (Listing.price - PricePoint.median) / PricePoint.mad
```

Quantize the result to four decimal places with `ROUND_HALF_EVEN`.

Negative values mean the Listing is below the median. The magnitude is the raw
number of baseline MAD units; do not use modified-z scaling.

A Listing qualifies as a deal candidate when:

```text
score <= Decimal("-3.0000")
```

Exactly `-3.0000` qualifies. The threshold is a conservative v1 pilot policy,
not an empirically calibrated optimum.

The stable v1 machine-readable rule code is:

```text
asking_price_mad_v1
```

That code must permanently mean the approved score formula, rounding,
usable-baseline requirements, threshold, and one-flag lifecycle. It is stored
in the existing `DealFlag.reason` field. Existing arbitrary or prose reason
values remain valid legacy data and must not be backfilled or invalidated.

The PricePoint calculation version identifies how baseline evidence was
calculated. The DealFlag reason code identifies why the scoring rule fired.
V1 requires no separate scoring-policy model or DealFlag version field.

## 9. DealFlag lifecycle contract

### 9.1 Identity and temporal baseline

V1 permits at most one DealFlag per Listing. Add database uniqueness on
`listing` while retaining the existing `(listing, baseline_pricepoint)`
constraint for frozen historical compatibility.

A Listing is judged only against the PricePoint for its own Manila observation
day. A later PricePoint must never be used to re-judge that historical Listing.

### 9.2 Idempotent creation

Under the same approved scoring policy:

- if a flag already exists for the Listing, return or reuse it without changing
  any field;
- if no flag exists and the Listing does not qualify, create nothing;
- if no flag exists and the Listing later becomes eligible specifically through
  an approved SKU-resolution workflow, it may receive its one evaluation using
  the PricePoint for its original observation day; and
- concurrent creation attempts must converge on one row through database
  uniqueness.

This exception for later approved SKU resolution is not permission to mutate
historical price, condition, timestamp, or provenance facts arbitrarily.

A future scoring policy must not silently rescore historical Listings. Any
retroactive evaluation requires a separately approved contract.

### 9.3 Immutability and outcomes

A DealFlag is immutable immediately:

- no update;
- no deletion;
- no replacement;
- no retraction field; and
- no mutable active state.

The same layered application, admin, and PostgreSQL protection required for
PricePoint applies to DealFlag.

An `Outcome` records later human action or non-action and never rewrites its
DealFlag. DealFlag immutability applies before and after an Outcome exists.
The existing one-to-one protected Outcome relationship remains unchanged.

If future correction or retraction history is required, it must be represented
by a separately approved append-only record rather than mutation of the
historical flag.

## 10. Existing scaffolding versus required Phase 5 work

### 10.1 Existing schema scaffolding

The repository already has:

- `PricePoint.sku`, `condition`, `day`, `median`, `p25`, `p75`, and
  `n_listings`;
- uniqueness on `(sku, condition, day)`;
- quartile ordering and non-negative sample-count checks;
- `DealFlag.listing`, `score`, `baseline_pricepoint`, `reason`, and
  `flagged_at`;
- uniqueness on `(listing, baseline_pricepoint)`;
- protected references from DealFlag to Listing and PricePoint; and
- a protected one-to-one Outcome reference to DealFlag.

These rows and constraints are scaffolding. No current production component
calculates a rolling baseline, creates a Phase 5 auditable PricePoint, scores a
Listing, or creates a v1 DealFlag.

### 10.2 Required PricePoint corrections and extensions

Phase 5 requires:

- widening `median`, `p25`, and `p75` from two to four decimal places;
- adding four-place MAD;
- adding the lower-inclusive and upper-exclusive Manila date bounds;
- adding calculation time;
- adding stable calculation-contract identity;
- preserving existing uniqueness and ordering constraints; and
- strong snapshot immutability at Django/admin and PostgreSQL levels.

TASK_019 hardening must derive the smallest safe `max_digits` values from the
current `DecimalField(max_digits=12, decimal_places=2)` Listing price range.
It must document the bound calculation rather than copy an arbitrary width.
Aggregate values cannot exceed the supported input price range, while Type 7
interpolation and MAD require four fractional places.

### 10.3 Required DealFlag corrections

Phase 5 requires:

- widening score capacity where necessary to preserve the supported price
  range divided by the smallest positive persisted four-place MAD without
  clipping;
- adding database uniqueness on `listing` while retaining the pair constraint;
- treating `reason="asking_price_mad_v1"` as the stable rule identity for new
  v1 flags; and
- strong immutability at Django/admin and PostgreSQL levels.

TASK_019 hardening must calculate the score bound from the supported price
range and the minimum positive persisted MAD (`0.0001`). Because score is not
money, its integer capacity need not match money fields, but it must remain a
four-place Decimal and may not be saturated or clipped.

No retraction, active-status, supersession, scoring-policy, or membership model
is required.

## 11. Migration and legacy-data contract

All Phase 5 schema changes must be additive or safe widening changes. Existing
migrations remain untouched.

Legacy/scaffolding PricePoints must remain distinguishable from valid Phase 5
snapshots:

- new audit fields are nullable for migration compatibility;
- existing rows receive `NULL`, not fabricated bounds, MAD, calculation time,
  or version;
- an all-required-metadata presence rule distinguishes a valid Phase 5
  snapshot; and
- any PricePoint lacking required metadata is unusable for scoring.

HARDEN must determine the smallest database constraint that prevents partially
populated Phase 5 audit metadata without invalidating truthful all-NULL legacy
rows.

Existing DealFlag reason text remains valid legacy data. Do not rewrite it to
`asking_price_mad_v1`.

Before adding `UNIQUE(listing)`, migration validation must inspect for duplicate
legacy DealFlags per Listing. If any exist, stop and require owner direction.
Do not silently delete, merge, select, or backfill those flags.

PricePoint and DealFlag PostgreSQL immutability should follow the repository's
established layered integrity posture while remaining compatible with clean
migration application and PostgreSQL test isolation. No data backfill or
`RunPython` fabrication is part of Phase 5.

## 12. Determinism and reproducibility rules

The following are versioned calculation behavior, not incidental
implementation choices:

- eligibility is one explicit Listing-layer predicate;
- temporal membership uses Manila calendar dates and `[D-90, D)`;
- each eligible Listing contributes exactly once;
- sorting is deterministic before quantile calculation;
- Type 7 interpolation uses Decimal operands only;
- MAD is raw and unscaled;
- calculations use an explicit Decimal context;
- baseline statistics and scores use four places and `ROUND_HALF_EVEN`;
- scoring reads the persisted median and MAD;
- existing snapshots and flags are reused without mutation; and
- concurrency is resolved by database identity constraints, not check-then-act
  assumptions.

Synthetic fixtures must cover exact boundary dates, timezone transitions,
quantile interpolation, rounding ties, zero MAD, insufficient samples,
eligibility exclusions, threshold equality, reruns, concurrency, and legacy
metadata. They prove contract correctness only and must not be described as
market evidence.

## 13. Operational expectations

Phase 5 must expose an ordinary Django management command that delegates to the
approved baseline and scoring services. The command remains tool-agnostic and
can later be invoked by cron without changing calculation semantics, but Phase
5 does not install or configure cron.

The operation must be rerunnable and deterministic:

- existing sealed PricePoints are reused;
- existing DealFlags are reused without update;
- unusable baselines create no flags;
- each Listing is associated only with its own observation-day snapshot;
- failures must be visible through non-zero command behavior rather than
  silently swallowed; and
- no Source bookkeeping or TASK_008 run-history state is written.

The command may provide a concise operational count, but no stable analytics,
run-summary, retry, parallel, or scheduler-health contract is required in v1.

PricePoint and DealFlag admin surfaces are read-only evidence views. They may
show persisted calculation metadata and linked evidence but must disable add,
change, delete, and bulk mutation. No calculation occurs at render time.

The exact command name, transaction granularity, and rule for creating an
otherwise absent historical PricePoint after its as-of day are intentionally
deferred to TASK_022 hardening. The approved lifecycle requires late data to
affect later snapshots and permits a later-resolved Listing to use an existing
snapshot for its original day; it does not yet authorize constructing a missing
historical snapshot from evidence learned later. This does not block the schema,
baseline, or scoring service tasks.

## 14. Proposed Phase 5 task sequence

The task identifiers below follow completed TASK_018. No task is frozen by this
planning document.

### TASK_019 — Make pricing evidence auditable and immutable

Goal:

- make the PricePoint and DealFlag schema capable of representing the approved
  contracts;
- add PricePoint MAD, temporal bounds, calculation time, and calculation
  version without fabricating legacy metadata;
- widen aggregate and score Decimals using explicit supported-bound proofs;
- add one-DealFlag-per-Listing uniqueness after a visible duplicate preflight;
- retain the existing pair and PricePoint identity constraints; and
- enforce PricePoint and DealFlag immutability through model/admin restrictions
  and PostgreSQL triggers.

Acceptance-risk areas:

- exact Decimal capacity calculations;
- four-place migration behavior for existing two-place values;
- all-NULL legacy versus complete v1 metadata;
- partially populated metadata rejection;
- duplicate legacy DealFlag detection;
- direct SQL and ORM update/delete protection;
- migration reversibility and clean-test teardown; and
- preservation of frozen TASK_004 and Outcome relationships.

Non-goals include aggregation, scoring, management commands, data backfill,
policy models, and Outcome behavior.

### TASK_020 — Build deterministic rolling PricePoint snapshots

Depends on TASK_019.

Goal:

- implement the exact Listing-layer eligibility predicate;
- implement Manila-day `[D-90, D)` membership;
- implement Decimal Type 7 quantiles, raw MAD, and half-even four-place
  persistence;
- persist no row for zero observations and a sealed descriptive row for one or
  more observations;
- classify usability from n, MAD, complete metadata, and recognized version;
  and
- reuse existing snapshots without mutation under reruns and concurrency.

Acceptance-risk areas:

- every eligibility exclusion and confidence consistency rule;
- lower-inclusive and upper-exclusive date boundaries;
- UTC-to-Manila date behavior;
- `n=1`, even-size, odd-size, interpolation, and rounding-tie examples;
- zero-MAD and one-to-four-sample snapshots;
- exact persistence of the calculation version and bounds;
- no float path;
- sealed rerun behavior; and
- no Source, RawListing, DealFlag, or Outcome writes.

Non-goals include scoring, flag creation, command orchestration, scheduling, and
market-accuracy claims.

### TASK_021 — Score Listings and persist immutable DealFlags

Depends on TASK_019 and TASK_020.

Goal:

- select the PricePoint for a Listing's own Manila observation day;
- reject absent, incomplete, unrecognized, small-sample, or zero-MAD snapshots
  as unusable;
- calculate the exact persisted-evidence MAD score;
- apply the inclusive `-3.0000` threshold;
- create at most one DealFlag using `asking_price_mad_v1`;
- converge safely under concurrent attempts; and
- reuse every existing flag without mutation.

Acceptance-risk areas:

- calculation from persisted rather than ephemeral statistics;
- half-even score rounding and exact threshold equality;
- score capacity extremes;
- later snapshots never re-judging an old Listing;
- approved later SKU resolution against the original-day snapshot;
- idempotent and concurrent creation;
- legacy reason compatibility;
- PostgreSQL DealFlag immutability; and
- Outcome references remaining valid and untouched.

Non-goals include retraction, replacement, policy backfill, alerts, Outcomes,
and operational scheduling.

### TASK_022 — Add operational pricing invocation and evidence visibility

Depends on TASK_020 and TASK_021.

Goal:

- add the ordinary management command that invokes baseline creation and
  scoring without duplicating either service;
- freeze deterministic selection, failure, and transaction behavior;
- demonstrate safe reruns across a complete invocation;
- expose PricePoint and DealFlag as read-only Django-admin evidence; and
- report only concise operational completion information.

Acceptance-risk areas:

- the remaining historical-snapshot creation boundary;
- exact command selection and ordering;
- batch rollback versus per-unit atomicity;
- non-zero propagation of unexpected failures;
- no duplicate snapshots or flags;
- no admin mutation through individual, bulk, or forged requests;
- no TASK_008, Source, Outcome, alert, or scheduler state; and
- full PostgreSQL validation against the exact staged snapshot.

Non-goals include cron deployment, persistent run summaries, retries,
parallelism, background workers, alerts, dashboards, and Outcome entry.

This ordering keeps schema integrity independent from calculation behavior,
freezes aggregate mathematics before scoring consumes it, and validates both
services before exposing a batch operational surface.

## 15. Pilot-policy disclaimers and evidence limits

These values are approved v1 pilot policy:

- 90 prior Manila days;
- minimum usable sample of five; and
- deal threshold at or below negative three raw MAD units.

They are not empirically calibrated optima. Synthetic tests can prove exact
software behavior but cannot establish precision, recall, market coverage, or
population representativeness.

Real-world evaluation must describe results as captured asking-listing
baselines and report, at minimum:

- sample size;
- collection period;
- source mix;
- SKU and condition coverage;
- unresolved and ineligible rates;
- repeated-listing and seller concentration limitations;
- flag count and human disposition where available;
- calculation-contract and scoring-rule versions; and
- any sampling or labelling method used.

No published claim may generalize the pilot corpus to the full Philippine
market without separately approved representative evidence.

## 16. Phase 5 completion criteria

Phase 5 is complete when approved frozen tests and implementation demonstrate:

1. Only Listings satisfying the exact approved fact predicate enter baseline
   populations.
2. A snapshot for day D contains exactly eligible observations from `[D-90,D)`
   in Manila dates and excludes all of D.
3. Type 7 quantiles and raw MAD are deterministic, Decimal-only, and persisted
   to four places using half-even rounding.
4. Zero observations create no PricePoint; one or more create a truthful sealed
   snapshot.
5. Snapshots with n below five or MAD zero never produce a score or flag.
6. Every valid Phase 5 snapshot contains complete bounds, calculation time,
   MAD, and stable calculation identity.
7. Legacy incomplete PricePoints remain identifiable and unusable without
   fabricated metadata.
8. Existing PricePoints are reused and cannot be updated or deleted through
   the model, ORM bulk operations, admin, or direct PostgreSQL writes.
9. Scores use persisted median and MAD, remain Decimal, and round to four
   places deterministically.
10. Exactly `-3.0000` qualifies and a larger score does not.
11. Every new flag uses reason `asking_price_mad_v1` and references the exact
    sealed PricePoint used.
12. At most one DealFlag exists per Listing, including under rerun and
    concurrency.
13. A later PricePoint never produces another flag for an old Listing.
14. DealFlags cannot be updated, deleted, replaced, or retracted through any
    ordinary or direct database path.
15. Existing Outcome references remain valid and never mutate DealFlag.
16. The operational command delegates to tested services, exposes failures,
    and writes no scheduler, source-health, or run-history state.
17. PricePoint and DealFlag admin views are evidence-only.
18. No Phase 5 path reads or changes RawListing, resolver, catalogue, ingestion,
    or Outcome state.
19. Full PostgreSQL tests and migration-drift validation are clean.

## 17. Remaining unknowns

No product or schema decision blocks TASK_019 hardening. Its exact field names,
constraint names, migration number, and Decimal `max_digits` are technical
outputs that must be frozen from the approved semantics and explicit bound
calculations during HARDEN.

Before TASK_022 can be hardened, the owner must settle one operational boundary:

- whether the pricing command may create a previously absent PricePoint for a
  historical as-of day after that day has passed, or whether it may create new
  snapshots only for the current Manila day while later-resolved Listings can
  use only an already-existing original-day snapshot.

The approved rule that late data affects later snapshots favors the latter,
but this planning document does not silently promote that recommendation into
an operational contract.

The exact command name and transaction granularity can be selected alongside
that decision during TASK_022 hardening; they do not affect stored statistical
meaning and do not block the earlier tasks.

## 18. Validation architecture

Each task must freeze acceptance tests before implementation. Validation must
use PostgreSQL 16 and include, as applicable:

- model metadata and generated-migration inspection;
- direct database constraint and trigger checks;
- ORM save/delete and bulk update/delete attempts;
- read-only admin permission and forged-request checks;
- exact Decimal arithmetic fixtures with no float values;
- Manila date boundary fixtures;
- concurrent identity tests;
- legacy all-NULL metadata and arbitrary reason compatibility;
- PricePoint and DealFlag rerun behavior;
- Outcome relationship compatibility;
- frozen-artifact hashing;
- the complete application suite; and
- `python manage.py makemigrations --check --dry-run`.

Synthetic fixtures establish deterministic contract behavior only. Runtime
validator evidence belongs to the independent validation phase; static review
owns staged schema, security, scope, and frozen-test integrity.

## 19. Readiness

TASK_019 has a settled goal, exact information requirements, legacy treatment,
integrity boundary, and bounded technical method for choosing numeric widths.
Its acceptance tests can be frozen without inventing product behavior.

```text
READY FOR PHASE 5 HARDEN
```
