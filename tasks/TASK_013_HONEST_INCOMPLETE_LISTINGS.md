# TASK_013 — Allow honest incomplete Listing derivations

## 1. Goal

Allow `Listing` to represent truthful incomplete derivations before the Phase 3
resolver is implemented.

Approved ingestion can produce an observation with an unparseable price, no
condition evidence, or no safe canonical SKU match. The derived schema must
represent those facts directly rather than discard the observation or invent a
price, condition, or resolution mechanism.

TASK_013 is a schema-only prerequisite. It implements no normalization or
entity resolution.

## 2. Authoritative context

This task follows:

- `CLAUDE.md`;
- `docs/03_PLANNING.md` §4;
- the existing `Listing` model and migrations;
- frozen TASK_004 Listing semantics; and
- frozen TASK_005 classification semantics.

The current schema already provides:

- nullable `Listing.sku` for unresolved/review-queue rows;
- Decimal `Listing.price` with a non-negative database constraint;
- the condition vocabulary `new`, `like_new`, `used`, `for_parts`;
- resolution methods `exact_alias`, `fuzzy_match`, `human_confirmed`;
- a confidence constraint covering the closed interval `[0, 1]`; and
- nullable `observed_at`, `price_kind`, and `trade_side` fields added by
  TASK_005.

TASK_013 widens exactly three parts of that existing schema. Everything else
remains unchanged.

## 3. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_013_HONEST_INCOMPLETE_LISTINGS.md`
- `listings/tests/test_task_013_honest_incomplete_listings.py`

After approval, neither frozen artifact may be modified to make implementation
pass. If either is wrong, implementation stops and reports the conflict.

### IMPLEMENT files allowed

- `listings/models.py`
- one generated migration under `listings/migrations/`, depending on
  `0002_listing_observed_at_price_kind_trade_side`

No other production, migration, test, task, planning, tooling, or dependency
file is in scope.

## 4. Locked schema changes

TASK_013 contains exactly three schema changes.

### 4.1 Listing.price becomes nullable

`Listing.price` must accept SQL NULL while retaining:

```python
models.DecimalField(max_digits=12, decimal_places=2, null=True)
```

The existing field has no default and TASK_013 adds none. The existing
`listing_price_non_negative` database guarantee remains effective for every
non-NULL value.

Required behavior:

- NULL is valid;
- an existing non-NULL Decimal value round-trips unchanged;
- a negative non-NULL Decimal remains rejected by PostgreSQL; and
- the field remains Decimal money with `max_digits=12` and
  `decimal_places=2`—never float and never `FloatField`.

PostgreSQL check constraints treat NULL as unknown rather than false, so the
existing non-negative constraint can keep its present expression while still
rejecting negative non-NULL values.

### 4.2 Listing.condition becomes nullable

`Listing.condition` must accept SQL NULL while retaining the existing non-NULL
vocabulary:

- `new`
- `like_new`
- `used`
- `for_parts`

The field keeps its existing `max_length=20` and has no default. TASK_013 must
not substitute `used`, an empty string, or another sentinel when condition
evidence is absent.

Required behavior:

- NULL is valid;
- every existing valid non-NULL condition remains valid; and
- any non-NULL value outside the vocabulary remains rejected by PostgreSQL.

As with the price check, PostgreSQL's existing vocabulary check naturally
permits NULL while continuing to reject an invalid non-NULL value.

### 4.3 Listing.resolution_method gains unresolved

Add this choice:

```python
("unresolved", "Unresolved")
```

Retain the existing values:

- `exact_alias`
- `fuzzy_match`
- `human_confirmed`

Both the Django choices and the
`listing_resolution_method_in_vocabulary` database constraint must include
`unresolved`. The field remains non-null, keeps `max_length=20`, and gains no
default.

Required behavior:

- `unresolved` is valid at the model/schema and database levels;
- every existing method remains valid; and
- an arbitrary unknown method remains rejected by PostgreSQL.

`unresolved` exists so new v1 resolver output can state honestly that no
approved matching mechanism found a SKU. TASK_013 itself creates no Listing
rows and implements no resolver.

## 5. Historical compatibility

Frozen TASK_004 tests already create this valid historical row:

```python
sku = None
resolution_method = "fuzzy_match"
resolution_confidence = Decimal("0.0000")
```

That state remains valid. TASK_013 must not add a cross-field constraint such
as `sku IS NULL -> resolution_method = unresolved`, and must not remove
`fuzzy_match`.

`unresolved` governs new v1 resolver semantics; it does not retroactively
invalidate previously frozen schema behavior. No data backfill is required.

## 6. Fields that must not change

TASK_013 preserves these existing field semantics:

| Field | Required preserved state |
|---|---|
| `sku` | nullable and blank-allowed; `SET_NULL`; no default |
| `resolution_confidence` | non-null Decimal(5, 4); no default; existing `[0, 1]` constraint |
| `resolution_method` | non-null CharField(max_length=20); no default, with only the approved vocabulary expansion |
| `resolved_at` | non-null DateTimeField; no default |
| `observed_at` | nullable, blank-allowed, default `None` |
| `price_kind` | nullable, blank-allowed, default `None`; existing vocabulary and trade-side constraint |
| `trade_side` | nullable, blank-allowed, default `None`; existing vocabulary and price-kind relationship |

The one-to-one `raw_listing` relationship, `location`, all other Listing
constraints, and all other models also remain unchanged.

## 7. Migration contract

The IMPLEMENT pass must generate the smallest Django migration needed to make
the three model-state changes real in PostgreSQL:

- alter `price` to allow NULL;
- alter `condition` to allow NULL;
- expand `resolution_method` choices in migration state; and
- replace the named resolution-method vocabulary constraint with the same
  constraint expanded to include `unresolved`.

Constraint removal/re-addition needed to change the existing named database
constraint is part of the third schema change, not an additional product
change.

The migration must not:

- backfill or rewrite Listing data;
- alter any unrelated field or constraint;
- create a default; or
- depend on or modify another app's migration.

## 8. Acceptance criteria — frozen

The authoritative acceptance module is:

```text
listings/tests/test_task_013_honest_incomplete_listings.py
```

It freezes:

### Nullable price

- `test_price_field_is_nullable_decimal_without_default`
- `test_listing_accepts_null_price`
- `test_existing_non_null_decimal_price_remains_valid`
- `test_negative_non_null_price_remains_rejected`

### Nullable condition

- `test_condition_field_is_nullable_without_default`
- `test_listing_accepts_null_condition`
- `test_existing_condition_values_remain_valid`
- `test_invalid_non_null_condition_remains_rejected`

### Resolution method

- `test_unresolved_is_in_resolution_method_choices`
- `test_listing_accepts_unresolved_resolution_method`
- `test_existing_resolution_methods_remain_valid`
- `test_unknown_resolution_method_remains_rejected`

### Compatibility and scope

- `test_historical_null_sku_fuzzy_match_state_remains_valid`
- `test_unrelated_listing_field_metadata_is_unchanged`

Parameterized vocabulary cases are collected separately by pytest. All
database behavior runs against PostgreSQL; SQLite is forbidden.

## 9. Non-goals

TASK_013 does not include or scaffold:

- resolver or title-normalization implementation;
- `Sku` or `SkuAlias` creation or seeding;
- fuzzy matching or confidence calibration;
- Phase 4 review UI;
- ingestion, `manual_capture`, or personal-trade changes;
- pricing, `PricePoint`, `DealFlag`, or `Outcome` work;
- scheduling, TASK_008, cron, or run bookkeeping;
- changes to `observed_at`, `price_kind`, `trade_side`, `resolved_at`, `sku`,
  or `resolution_confidence` nullability or semantics;
- a data migration or backfill;
- unrelated model cleanup;
- dependencies, Docker, hooks, or tooling changes; or
- modifications to any existing frozen test.

## 10. Validation

During IMPLEMENT, rebuild/recreate the Docker web service if needed because the
application source is baked into its image, then run:

```text
docker compose exec web pytest -v listings/tests/test_task_013_honest_incomplete_listings.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
git diff --check
git diff --cached --check
```

The dedicated and full suites must pass, migration drift must report
`No changes detected`, and the generated migration must be inspected to confirm
that it contains only the three approved changes.

Final validation must also inspect the actual PostgreSQL schema/constraints and
confirm that:

- NULL price and condition persist;
- negative non-NULL price is rejected;
- invalid non-NULL condition is rejected;
- `unresolved` and all existing methods persist;
- an unknown method is rejected; and
- the historical `sku=NULL, fuzzy_match, confidence=0` state still persists.

No TASK_013 implementation is approved until the frozen acceptance module and
this specification receive explicit human approval.
