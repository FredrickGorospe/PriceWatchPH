# TASK_021 - Score Listings and persist immutable DealFlags

## 1. Goal

Build the reusable Phase 5 scoring service that evaluates one eligible
`Listing` against the sealed `PricePoint` for that Listing's own Manila
observation day and inserts one immutable `DealFlag` only when the approved v1
score qualifies.

TASK_021 owns Listing scoring eligibility, exact own-day PricePoint selection,
PricePoint usability, Decimal score calculation, the v1 deal threshold, and
idempotent DealFlag creation only. It does not aggregate baselines or provide
operational orchestration.

## 2. Authority and dependencies

This task follows:

- committed `CLAUDE.md` repository constraints;
- `docs/05_PLANNING.md` Sections 7.4, 8, 9, 11, 12, and 14;
- TASK_005 Manila-day bucketing;
- TASK_013 honest nullable Listing facts;
- TASK_014 and TASK_017 trusted resolution semantics;
- TASK_019 auditable and immutable PricePoint/DealFlag storage; and
- TASK_020 deterministic rolling PricePoint creation.

The frozen TASK_019 and TASK_020 specifications and tests remain authoritative.
TASK_021 consumes their schema, immutability, and baseline meaning without
redesigning or duplicating them.

## 3. Files

### HARDEN artifacts - frozen before implementation

- `tasks/TASK_021_DETERMINISTIC_DEAL_SCORING.md`
- `pricing/tests/test_task_021_deal_scoring.py`

After owner approval, neither artifact may be modified to make implementation
pass. A contradiction stops implementation for owner correction.

### IMPLEMENT file allowed

- `pricing/scoring.py`

No model, admin, migration, management-command, baseline, ingestion, resolver,
catalogue, source, outcome, planning, prior task, or prior frozen-test file is
in scope. Repository inspection confirms TASK_021 requires no schema change or
migration.

## 4. Stable service API

Add one reusable internal pricing service:

```python
score_listing(*, listing: Listing) -> DealFlag | None
```

The keyword-only Listing is the complete scoring subject. Callers cannot supply
an arbitrary PricePoint, effective day, score policy, threshold, or reason.

The service returns:

- the existing DealFlag when the Listing already has one;
- `None` when no flag exists and the Listing is ineligible, its original-day
  PricePoint is absent or unusable, or its final score does not qualify; or
- the newly created DealFlag when the Listing is eligible and its final score
  qualifies.

The existing-flag lookup occurs before Listing validation, PricePoint lookup,
or score calculation. Historical flags, including rows with arbitrary prose
reasons, are sealed evidence and must be returned unchanged.

Private eligibility, usability, score, and create-or-return helpers are
implementation details and are not frozen API.

## 5. Listing scoring prerequisites

A Listing can be scored only when all of these Listing-layer facts hold:

```text
sku IS NOT NULL
price IS NOT NULL
condition IS NOT NULL
observed_at IS NOT NULL
price_kind = "asking"
resolution_method IN ("exact_alias", "human_confirmed")
resolution_confidence = Decimal("1.0000")
```

The approved resolution method establishes trust. Confidence is a consistency
guard and cannot independently make `fuzzy_match`, `unresolved`, or reviewed
unresolved state eligible.

Do not inspect or special-case `Source.name`. Do not read RawListing payload,
provenance, seller, source, title, price, timestamp, or identifiers to make the
scoring decision. Listing-layer facts are authoritative.

TASK_021 does not modify an ineligible Listing and does not attempt to resolve
it.

## 6. Original Manila day and exact PricePoint lookup

Derive the Listing's evaluation day only by calling the already-approved:

```python
pricing.bucketing.manila_day(listing.observed_at)
```

This converts the aware UTC-stored instant to the calendar date in
`settings.AGGREGATION_TIME_ZONE` (`Asia/Manila`). Do not duplicate timezone
logic, use the UTC date, use the wall clock, or use a database date transform.

Look up exactly one PricePoint identity:

```text
sku = Listing.sku
condition = Listing.condition
day = manila_day(Listing.observed_at)
```

Do not select the latest, nearest, earlier, later, or current-day PricePoint.
A later PricePoint never re-judges an older Listing. An absent original-day
identity produces no flag and does not invoke `build_pricepoint()`.

The exact identity lookup naturally rejects PricePoints for another SKU,
condition, or day.

## 7. PricePoint usability

The exact original-day PricePoint is usable for v1 scoring only when all of
these hold:

```text
n_listings >= 5
mad IS NOT NULL
mad > Decimal("0.0000")
window_start_day IS NOT NULL
window_end_day IS NOT NULL
calculated_at IS NOT NULL
calculation_contract_version = "asking_price_baseline_v1"
```

The schema already makes the five TASK_019 audit fields all-NULL or all-present,
and the recognized immutable version identifies the approved TASK_020 window
and calculation contract. TASK_021 checks presence and recognized identity; it
does not recompute baseline membership or statistics.

Legacy all-NULL rows, incomplete evidence, unrecognized versions, fewer than
five observations, NULL MAD, and zero MAD are unusable. Return `None`, create no
DealFlag, and do not repair, replace, update, delete, or rebuild the PricePoint.

One through four observations and zero MAD remain truthful snapshots. TASK_021
only declines to score them.

## 8. Deterministic Decimal score

Use only the Listing's persisted `price` and the selected PricePoint's
persisted `median` and `mad`:

```text
raw_score = (Listing.price - PricePoint.median) / PricePoint.mad
final_score = raw_score quantized to Decimal("0.0001")
```

Run subtraction, division, and quantization inside an explicit local Decimal
context:

```text
precision = 28 significant digits
rounding = ROUND_HALF_EVEN
```

Twenty-eight digits exceed the 18-digit persisted score capacity and preserve
guard digits for division before four-place persistence. Mutable process-global
Decimal settings must not change the result.

Use Decimal only. Do not convert through float, use a FloatField, recompute the
baseline, use ephemeral higher-precision TASK_020 values, scale MAD, clip a
score, cap an extreme supported value, or substitute an epsilon.

## 9. Deal threshold and stable reason

Apply the threshold to the final four-place score:

```text
final_score <= Decimal("-3.0000")
```

Exactly `-3.0000` qualifies. A final score of `-3.0001` qualifies. A final
score of `-2.9999` does not. Half-even rounding can therefore determine which
side of the threshold the reproducible persisted score occupies.

Every newly created TASK_021 flag uses:

```text
reason = "asking_price_mad_v1"
```

This stable machine-readable identifier permanently names the approved v1
Listing prerequisites, original-day lookup, PricePoint-usability predicate,
persisted-evidence formula, Decimal context, four-place rounding, inclusive
threshold, and one-flag lifecycle. The `-3.0000` threshold is a v1 pilot policy,
not an empirical market optimum.

Existing historical reason values remain valid and unchanged.

## 10. DealFlag persistence and sealed lifecycle

For a newly qualifying Listing, insert one complete DealFlag with:

```text
listing = evaluated Listing
score = final four-place score
baseline_pricepoint = exact original-day usable PricePoint
reason = "asking_price_mad_v1"
flagged_at = timezone-aware insertion time
```

TASK_019 database uniqueness on `listing` is the authoritative identity. A
Listing may receive at most one DealFlag.

If a flag already exists, return it unchanged. Never compare it with a newly
calculated score, update it, delete/recreate it, change its baseline, reason,
score, or `flagged_at`, or create a second flag because a later PricePoint now
exists.

The service inserts only. TASK_019 model, admin, and PostgreSQL immutability
remain authoritative.

## 11. Idempotency, concurrency, and failure atomicity

When no flag exists initially and the Listing qualifies:

1. calculate from the exact original-day persisted evidence;
2. attempt one complete insert inside a narrow transaction/savepoint; and
3. if another transaction wins the `UNIQUE(listing)` identity, return the
   now-existing flag unchanged.

Use `get_or_create(listing=listing, defaults=complete_fields)` for the final
insert-or-return step. It is the narrowest fit because it uses the database
identity, never updates an existing row, and Django re-raises an IntegrityError
when the fallback identity lookup finds no concurrent winner. TASK_021 does not
need a broader explicit conflict-recovery abstraction.

Do not use `update_or_create()`, conflict-update SQL, trigger bypasses,
process-local locks, or broad IntegrityError swallowing. Non-identity database
errors and unexpected insert errors propagate. A failed insert leaves no
partial DealFlag or other downstream state.

Concurrent qualifying attempts must be forced through database uniqueness and
converge on one returned row.

## 12. Approved later-resolution behavior

A Listing that was previously unresolved may receive its one historical
evaluation only after the existing approved SKU-confirmation workflow makes it
eligible with:

```text
resolution_method = "human_confirmed"
resolution_confidence = Decimal("1.0000")
```

The evaluation still derives the Listing's original Manila observation day
from its unchanged `observed_at` and uses only the already-existing PricePoint
for that original identity.

If that original-day PricePoint is absent or unusable, return `None`. Do not
create a historical PricePoint and do not substitute a later or current-day
snapshot.

This exception is not permission to generalize arbitrary historical mutation
or re-evaluation of price, condition, timestamp, provenance, or resolved
Listings.

## 13. Component boundaries and non-goals

TASK_021 must not:

- create, update, or delete a PricePoint;
- call `build_pricepoint()` or duplicate baseline aggregation;
- create a historical, latest, or current-day baseline as a substitute;
- update or delete a DealFlag;
- create more than one DealFlag for a Listing;
- modify a Listing, RawListing, Sku, SkuAlias, or Source;
- read RawListing or Source identity as scoring policy;
- create, update, or delete an Outcome;
- add notifications, alerts, scheduler state, or run bookkeeping;
- expose a management command;
- implement TASK_022;
- change TASK_019 immutability or TASK_020 baseline semantics;
- add a policy table, version field, cache, frontend, or retraction state; or
- claim empirical Philippine market accuracy from synthetic tests.

## 14. Acceptance criteria - frozen

The authoritative acceptance module is:

```text
pricing/tests/test_task_021_deal_scoring.py
```

It uses synthetic fixtures and freezes:

### Listing eligibility

- exact-alias and human-confirmed Listings can score;
- every missing or untrusted required Listing fact is excluded;
- unresolved, reviewed-unresolved, and fuzzy-match Listings are excluded;
- confidence cannot independently establish trust; and
- Source names do not allow or deny eligibility.

### PricePoint selection and usability

- lookup uses `manila_day()` and the Listing's exact original-day identity;
- UTC instants on both sides of Manila midnight select different days;
- earlier, later, other-SKU, and other-condition rows are not substitutes;
- absent original-day evidence creates no PricePoint or flag;
- legacy, small-sample, zero-MAD, and wrong-version rows are unusable; and
- a complete recognized v1 row with five observations may score.

### Score and persistence

- the score uses persisted Listing/PricePoint values and raw MAD;
- supported extreme negative scores are preserved without clipping;
- Decimal context is independent of mutable global settings;
- four-place `ROUND_HALF_EVEN` is behavioral at the threshold;
- exactly `-3.0000` and smaller scores qualify while `-2.9999` does not;
- a new row references the exact evidence and stores the stable reason and a
  truthful aware `flagged_at`; and
- nonqualifying evaluation writes nothing.

### Lifecycle and boundaries

- qualifying reruns return the same immutable row without mutation;
- nonqualifying reruns remain row-free;
- existing arbitrary-reason historical flags return unchanged;
- later PricePoints never create a second flag;
- approved later SKU confirmation can use an existing original-day snapshot;
- absent original-day evidence after later resolution creates no baseline;
- concurrent inserts converge through PostgreSQL uniqueness;
- unexpected and non-identity database failures propagate without partial
  state; and
- Listing, PricePoint, RawListing, Source, Sku, aliases, and Outcome state are
  not mutated or used outside the approved boundary.

Parameterized cases are collected separately by pytest. All database behavior
runs against PostgreSQL 16; SQLite is forbidden.

## 15. Frozen compatibility and validation

TASK_021 preserves TASK_019 and TASK_020 frozen behavior and changes no schema.
During IMPLEMENT, run from the repository root:

```text
docker compose exec web pytest -v pricing/tests/test_task_021_deal_scoring.py
docker compose exec web pytest -v pricing/tests/test_task_020_rolling_pricepoints.py
docker compose exec web pytest -v pricing/tests/test_task_019_pricing_evidence.py
docker compose exec web pytest -v pricing/tests/test_task_004_pricing.py outcomes/tests/test_task_004_outcomes.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py check
git diff --check
git diff --cached --check
```

Implementation validation must exercise concurrency against PostgreSQL 16 and
confirm the frozen artifact hashes. No TASK_021 production implementation is
approved until this specification and its frozen acceptance module receive
explicit owner approval.
