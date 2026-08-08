# TASK_019 — Make pricing evidence auditable and immutable

## 1. Goal

Make the existing `PricePoint` and `DealFlag` scaffolding capable of preserving
the exact historical evidence required by the approved Phase 5 pricing
contract.

TASK_019 is a schema, auditability, and integrity prerequisite only. It adds no
baseline population query, aggregation, score calculation, threshold decision,
or operational pricing command.

After TASK_019:

- a legacy PricePoint remains truthfully identifiable by absent audit metadata;
- a Phase 5 PricePoint can carry complete four-place aggregate evidence;
- PricePoint and DealFlag rows are immutable immediately after insertion;
- at most one DealFlag can exist for a Listing; and
- all previously frozen TASK_004 relationships and legacy values remain valid.

## 2. Authority and dependencies

This task follows:

- committed `CLAUDE.md` repository constraints;
- `docs/00_PLANNING.md` component and database-integrity boundaries;
- frozen TASK_004 PricePoint, DealFlag, and Outcome semantics;
- TASK_005 Manila-day provenance semantics;
- `docs/05_PLANNING.md` Sections 6, 9, 10, 11, and 14; and
- the current `pricing` and `outcomes` models and migrations.

Owner-approved Phase 5 contracts are not reopened here. In particular:

- one PricePoint is one sealed `(Sku, condition, as-of Manila day)` rolling
  snapshot;
- the temporal population is `[D-90, D)` in whole Manila calendar days;
- aggregate statistics and DealFlag score use four decimal places;
- a DealFlag is immutable and at most one may exist per Listing; and
- existing arbitrary DealFlag reason text remains valid legacy data.

## 3. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_019_AUDITABLE_PRICING_EVIDENCE.md`
- `pricing/tests/test_task_019_pricing_evidence.py`

After owner approval, neither artifact may be modified to make implementation
pass. If either artifact is wrong or conflicts with an older frozen contract,
implementation stops and reports the conflict.

### IMPLEMENT files allowed

- `pricing/models.py`
- `pricing/admin.py`
- exactly one new migration under `pricing/migrations/`, depending on
  `pricing.0001_initial`

No other production, model, migration, admin, test, task, planning, dependency,
Docker, or tooling file is in scope.

## 4. Exact PricePoint schema contract

### 4.1 Existing aggregate fields widen to four places

These existing required fields become:

```python
median = models.DecimalField(max_digits=14, decimal_places=4)
p25 = models.DecimalField(max_digits=14, decimal_places=4)
p75 = models.DecimalField(max_digits=14, decimal_places=4)
```

They remain non-null, retain no default, and retain the existing database
ordering constraint:

```text
p25 <= median <= p75
```

The existing `(sku, condition, day)` uniqueness and non-negative
`n_listings` behavior remain unchanged.

### 4.2 New audit fields

Add exactly these fields:

```python
mad = models.DecimalField(
    max_digits=14,
    decimal_places=4,
    null=True,
    blank=True,
)
window_start_day = models.DateField(null=True, blank=True)
window_end_day = models.DateField(null=True, blank=True)
calculated_at = models.DateTimeField(null=True, blank=True)
calculation_contract_version = models.CharField(
    max_length=64,
    null=True,
    blank=True,
)
```

None has a model or database default.

`window_start_day` is lower-inclusive. `window_end_day` is upper-exclusive.
`DateField` is the narrowest truthful type because the approved population is
defined entirely in Manila calendar dates, not timestamp instants.

`calculated_at` is a timezone-aware calculation timestamp stored under the
existing UTC/`USE_TZ=True` contract.

`calculation_contract_version` is a bounded stable machine identifier. A
64-character field provides ample room for an explicit slug-like version while
preventing an unbounded text value from becoming accidental configuration or
prose. TASK_019 does not select the later aggregation service's production
identifier and does not add a policy table.

### 4.3 Decimal-width derivation

Existing Listing prices are non-negative
`DecimalField(max_digits=12, decimal_places=2)` values. Their maximum supported
value is:

```text
Pmax = 9,999,999,999.99
```

That is ten integer digits and two fractional digits.

Type 7 quantiles are convex combinations of observed prices, so `median`,
`p25`, and `p75` remain between the minimum and maximum input. Raw MAD is an
absolute deviation from a median within the same non-negative range, so it is
no larger than `Pmax` either.

Four persisted fractional digits therefore require:

```text
10 integer digits + 4 fractional digits = max_digits 14
```

`DecimalField(max_digits=14, decimal_places=4)` is the smallest field that
preserves the complete supported price range and the approved aggregate
precision without clipping.

## 5. Audit-metadata integrity

Legacy/scaffolding PricePoints already carry the required core fields but do
not truthfully carry Phase 5 audit evidence. The five new fields therefore
remain nullable and use this database invariant:

```text
legacy:
    mad IS NULL
    AND window_start_day IS NULL
    AND window_end_day IS NULL
    AND calculated_at IS NULL
    AND calculation_contract_version IS NULL

OR

auditable:
    mad IS NOT NULL
    AND window_start_day IS NOT NULL
    AND window_end_day IS NOT NULL
    AND calculated_at IS NOT NULL
    AND calculation_contract_version IS NOT NULL
```

The invariant operates only on new audit fields. Existing core fields cannot
identify legacy rows because every historical PricePoint already has them.

Add these further database guarantees:

- `mad IS NULL OR mad >= 0`;
- an auditable version is not the empty string; and
- when window bounds are present, `window_start_day < window_end_day`.

TASK_019 does not constrain the dates to exactly 90 days in SQL. Window policy
belongs to the versioned TASK_020 calculation contract, and a future version
must not require rewriting this schema merely to express a different approved
window.

No migration backfill populates any new audit field. Existing rows naturally
receive all-NULL audit metadata and are not usable by future scoring.

## 6. PricePoint immutability

Every PricePoint becomes immutable immediately after creation, including a
legacy row. A legacy aggregate is still historical evidence; there is no
approved workflow that repairs it in place.

Layered enforcement is required:

1. normal model save on a persisted instance raises a clear
   `ValidationError`;
2. normal instance delete raises a clear `ValidationError`;
3. a PostgreSQL `BEFORE UPDATE OR DELETE` trigger rejects every row-level
   update or deletion; and
4. Django admin provides view-only evidence, with add, change, delete, and bulk
   mutation disabled.

The PostgreSQL trigger is authoritative for `QuerySet.update()`,
`QuerySet.delete()`, raw SQL, and future non-Django writers. It applies to every
PricePoint row and allows INSERT.

Rerun reuse and PricePoint creation services belong to TASK_020. TASK_019 only
establishes insert-only storage.

## 7. Exact DealFlag schema contract

### 7.1 Score width

`DealFlag.score` becomes:

```python
score = models.DecimalField(max_digits=18, decimal_places=4)
```

The approved score formula is:

```text
(Listing.price - PricePoint.median) / PricePoint.mad
```

The maximum absolute numerator is `Pmax = 9,999,999,999.99`. The smallest
positive persisted four-place MAD is `0.0001`. Therefore:

```text
Pmax / 0.0001 = 99,999,999,999,900
```

The result requires fourteen integer digits. Four fractional score digits
require:

```text
14 integer digits + 4 fractional digits = max_digits 18
```

The sign consumes no PostgreSQL numeric digit. `max_digits=18` is the smallest
safe width for all values produced from the approved persisted input bounds.
No score is capped, saturated, or coerced to fit.

### 7.2 One flag per Listing

Add:

```text
UNIQUE (listing)
```

as an additive database constraint. Keep `listing` as its existing
`ForeignKey` with `related_name="deal_flags"`; do not convert it to a
`OneToOneField` and change reverse/API behavior.

Retain the frozen historical constraint:

```text
UNIQUE (listing, baseline_pricepoint)
```

Retain the protected Listing and PricePoint foreign keys.

### 7.3 Reason compatibility

`reason` remains an unconstrained, required `TextField`. Existing arbitrary or
prose values remain valid. TASK_019 adds no choices, check constraint, policy
model, version field, or data backfill.

TASK_021 will write the approved stable code `asking_price_mad_v1`; TASK_019
does not implement that writer.

## 8. DealFlag immutability

Every DealFlag is immutable immediately after creation, regardless of whether
an Outcome exists.

Layered enforcement mirrors PricePoint:

1. normal model save on a persisted instance raises `ValidationError`;
2. normal instance delete raises `ValidationError`;
3. a PostgreSQL `BEFORE UPDATE OR DELETE` trigger rejects update or deletion
   through bulk ORM or direct SQL; and
4. Django admin is view-only with add, change, delete, and bulk mutation
   disabled.

INSERT remains allowed. Outcome insertion remains allowed and does not modify
the flag. Existing `PROTECT` relationships remain unchanged, but they do not
replace the immutable-row trigger.

## 9. Admin contract

`PricePoint` and `DealFlag` remain registered in Django admin as evidence
views.

For both models:

- users with normal model view permission may inspect existing rows;
- `has_add_permission()` returns false;
- `has_change_permission()` returns false;
- `has_delete_permission()` returns false;
- every concrete model field is presented read-only; and
- no bulk actions are exposed.

Forged add, change, and delete POST requests must not mutate rows. TASK_019 does
not freeze cosmetic field grouping, list columns, search behavior, or template
markup.

## 10. Migration contract and safety

Implementation creates exactly one new pricing migration depending on
`pricing.0001_initial`. Existing migrations are never modified.

The migration may contain only the approved model-state/schema changes, a
read-only duplicate precondition, and PricePoint/DealFlag immutability DDL.

Before adding `UNIQUE(listing)`, a read-only migration precondition must query
for any Listing referenced by more than one DealFlag. If any duplicate exists,
the migration raises a clear exception identifying the problem and stops.

The migration must never delete, merge, select, rewrite, or otherwise repair a
duplicate. The owner must decide how real duplicate historical evidence is
handled.

Migration operation ordering must ensure:

1. safe field additions/widening and metadata constraints;
2. duplicate preflight before one-Listing uniqueness;
3. uniqueness addition only after a clean preflight; and
4. immutable triggers after schema changes and preconditions succeed.

The trigger DDL must have explicit reverse SQL that removes only the TASK_019
triggers/functions. INSERT remains permitted. Reversing the migration removes
TASK_019 guards before reversing field/constraint state.

No `RunPython` operation may write or fabricate data. No field receives a
temporary or permanent default.

The frozen pytest module does not apply and reverse the production migration
inside the shared application suite. Migration-precondition behavior must be
validated later against a disposable exact pre-migration PostgreSQL snapshot:

- a clean snapshot migrates successfully;
- a snapshot with two DealFlags for one Listing fails visibly; and
- the duplicate rows remain unchanged after failure.

This isolates schema migration state from ordinary transactional tests while
still making the precondition a required runtime acceptance result.

## 11. Acceptance criteria — frozen

The authoritative acceptance module is:

```text
pricing/tests/test_task_019_pricing_evidence.py
```

It freezes:

### PricePoint schema and legacy compatibility

- four-place, safely bounded Decimal metadata for median, quartiles, and MAD;
- exact nullable audit field types with no defaults;
- valid all-NULL legacy metadata;
- valid complete audit metadata;
- rejection of every partially populated audit shape;
- rejection of blank calculation version, negative MAD, and unordered bounds;
  and
- preservation of `(sku, condition, day)` uniqueness.

### PricePoint immutability

- clear model-save and model-delete failures;
- PostgreSQL rejection through QuerySet update/delete and raw SQL
  update/delete; and
- immutable treatment of legacy as well as auditable rows.

### DealFlag schema and compatibility

- exact four-place score capacity derived above;
- successful round-trip at the supported extreme;
- retained ForeignKey/reverse and protected-FK semantics;
- retained pair uniqueness plus new one-Listing uniqueness;
- arbitrary legacy reason compatibility; and
- unchanged Outcome insertion referencing a flag.

### DealFlag immutability

- clear model-save and model-delete failures; and
- PostgreSQL rejection through QuerySet and raw SQL update/delete.

### Admin evidence boundary

- view access to existing evidence;
- no add, change, delete, or bulk action permissions;
- every concrete field read-only; and
- rejection of forged add/change/delete POST requests.

Parameterized cases are collected separately by pytest. All database behavior
runs against PostgreSQL 16; SQLite is forbidden.

## 12. Frozen compatibility

TASK_019 preserves all existing TASK_004 behavior:

- legacy PricePoints can still be inserted with only existing fields;
- two-place values widen exactly and round-trip as Decimal;
- `(sku, condition, day)` remains unique;
- quartile ordering and `n_listings` guarantees remain;
- arbitrary DealFlag reason strings remain valid;
- `(listing, baseline_pricepoint)` remains unique;
- the DealFlag baseline FK remains non-null and protected;
- `DealFlag.listing` retains its ForeignKey and plural reverse name; and
- Outcome retains its protected one-to-one link to DealFlag.

No existing frozen task or test is modified. No frozen artifact requires owner
correction.

## 13. Explicit non-goals

TASK_019 does not include:

- baseline eligibility query or source-name logic;
- Manila-window population selection;
- Type 7 quantile or MAD calculation;
- PricePoint creation/reuse service;
- PricePoint usability policy execution;
- score calculation or `-3.0000` threshold execution;
- `asking_price_mad_v1` writer behavior;
- DealFlag creation/reuse service;
- a pricing management command;
- operational transaction or scheduling semantics;
- a scoring-policy model or separate DealFlag version;
- member-level snapshot rows;
- retraction, active state, replacement, or supersession;
- Outcome workflow changes;
- ingestion, resolver, catalogue, source, or RawListing changes;
- alerts, dashboards, frontend work, TASK_008, cron, retries, or run history;
- data cleanup or backfill; or
- modification of any prior migration, task, or frozen test.

## 14. Validation

During IMPLEMENT, rebuild/recreate the web service if source is baked into its
image, then run:

```text
docker compose exec web pytest -v pricing/tests/test_task_019_pricing_evidence.py
docker compose exec web pytest -v pricing/tests/test_task_004_pricing.py outcomes/tests/test_task_004_outcomes.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
git diff --check
git diff --cached --check
```

Implementation validation must additionally inspect the generated migration
and actual PostgreSQL constraints/triggers. A disposable exact pre-TASK_019
snapshot must validate the duplicate-DealFlag migration precondition described
in Section 10.

The dedicated and complete suites must pass, migration drift must report
`No changes detected`, and no float/FloatField path may be introduced.

Final reviewer scope includes frozen-artifact integrity, exact staged schema,
trigger behavior, migration safety, admin mutation boundaries, legacy
compatibility, and absence of aggregation/scoring/operational scope.

No TASK_019 implementation is approved until this specification and its frozen
acceptance module receive explicit owner approval.
