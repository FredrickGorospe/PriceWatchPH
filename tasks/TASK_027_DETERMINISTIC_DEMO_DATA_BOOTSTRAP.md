# TASK_027 - Deterministic development market-data bootstrap

## 1. Goal

Provide one explicitly enabled development command:

```text
python manage.py bootstrap_demo_data
```

The command populates a small, visibly synthetic, deterministic market-data
corpus that exercises the committed path from immutable `RawListing` evidence
through exact alias resolution, rolling `PricePoint` calculation, `DealFlag`
scoring, DRF, and the existing React surfaces.

The command is not production ingestion. It performs no network access, creates
no Source, and is disabled unless an explicit environment-backed setting is
enabled. It delegates resolution and pricing decisions to the existing
production services and never inserts `Listing`, `PricePoint`, or `DealFlag`
rows directly merely to populate the UI.

## 2. Authority and current gap

This task follows:

- `CLAUDE.md` and `docs/ROADMAP.md`;
- `SOURCES.md` approval of `manual_capture` and `personal_records` only;
- TASK_006's closed ordinary `manual_capture` command contract;
- TASK_014 and TASK_015 resolution behavior;
- TASK_019 through TASK_022 pricing evidence, arithmetic, and command behavior;
- TASK_023 through TASK_026 API and React evidence boundaries; and
- the owner-approved post-Phase-6 bridge assessment.

The current production producers cannot create a baseline-eligible asking
population:

- ordinary `manual_capture` deliberately supplies neither condition nor an
  asking/realised classification; and
- `personal_records` represents realised first-party trades, which pricing
  correctly excludes.

The local database has only the two approved seeded Sources and no catalogue or
market evidence. Honest Phase 6 empty states are therefore expected. TASK_027
closes the development and portfolio-readiness gap without changing the
ordinary production capture contract or claiming that synthetic observations
are real market evidence.

TASK_027 is a bridge task before roadmap Phase 7. It is not deferred TASK_008,
an alerts task, or a new roadmap phase.

## 3. Frozen and implementation files

### HARDEN artifacts

- `tasks/TASK_027_DETERMINISTIC_DEMO_DATA_BOOTSTRAP.md`
- `tests/test_task_027_deterministic_demo_data_bootstrap.py`

After owner approval, neither artifact may be modified to make implementation
pass. A contradiction stops implementation for owner correction.

### Files an IMPLEMENT pass may change

- `.env.example`
- `config/settings.py`
- `ingestion/demo_data.py`
- `ingestion/management/commands/bootstrap_demo_data.py`
- `listings/resolver.py`

No model, migration, Source seed, ordinary ingestion importer, API, frontend,
admin, pricing service, prior task, or prior frozen test is in scope.

## 4. Command and environment gate

The exact command is:

```text
python manage.py bootstrap_demo_data
```

It accepts no TASK_027-specific positional arguments or custom options. It has
no input-file, stdin, or interactive contract, and no reset, delete, or force
mode. Standard Django `BaseCommand` options remain available. In particular,
`--reset`, `--delete`, and `--force` do not exist.

`config.settings` reads exactly:

```text
PRICEWATCHPH_ENABLE_DEMO_DATA
```

into:

```python
ENABLE_DEMO_DATA = (
    os.environ.get("PRICEWATCHPH_ENABLE_DEMO_DATA", "0") == "1"
)
```

`.env.example` contains:

```text
PRICEWATCHPH_ENABLE_DEMO_DATA=0
```

The disabled default is authoritative. When `settings.ENABLE_DEMO_DATA` is not
true, the command raises `CommandError` before any database write with:

```text
Demo data bootstrap is disabled. Set PRICEWATCHPH_ENABLE_DEMO_DATA=1 to enable it.
```

The command uses no DEBUG exception and no implicit development-host or
database-name heuristic. Explicit opt-in is required even when DEBUG is true.
Only the literal environment value `"1"` enables the setting. Absence, `"0"`,
the empty string, `"true"`, and every other value leave it false.

## 5. Source-governance and synthetic-data boundary

The command requires the existing:

```text
Source.name = "manual_capture"
```

If it is absent, the enabled command raises `CommandError` with:

```text
Required approved Source manual_capture is missing.
```

It must not create, update, or delete any Source, including
`manual_capture`. It must not change `Source.last_successful_fetch`.
The complete pre-existing Source set and its field values must be identical
before and after the command. The command does not assume that only the two
currently seeded Sources exist.

`personal_records` is not used because the manifest describes asking
observations rather than first-party realised trades. No eBay, Carousell,
Facebook Marketplace, TipidPC, retailer, or other Source row or provenance
claim is introduced.

Every catalogue name and raw title visibly contains `PriceWatchPH Demo` or
`DEMO`. Every URL uses the reserved `.invalid` domain. Every external ID is in
the `pricewatchph_demo_v1:` namespace. Seller is always the existing empty
string absence value and seller is absent from payload. No real person,
merchant, URL, listing, product observation, benchmark, or outcome is claimed.

## 6. Narrow explicit asking-price provenance

TASK_027 adds one narrow resolver fact. It does not add a new user-facing
capture input.

For a dictionary payload, resolution derives price kind in this precedence:

1. If `stated_trade_side` is present and non-null, `price_kind` is
   `"realised"`, exactly as TASK_014 already requires. This takes precedence
   even if `stated_price_kind="asking"` is also present.
2. Otherwise, `stated_price_kind="asking"` is trusted only when the immutable
   RawListing belongs to `Source.name="manual_capture"`.
3. Every other case produces `price_kind=NULL`.

The new fact recognizes only the exact string `"asking"`. It does not make
explicit `"realised"`, arbitrary values, truthy values, or values from another
Source authoritative. Realised observations continue to require the existing
trade-side fact.

This remains an explicit source-fact mapping, not source-name inference:
`manual_capture` alone still produces NULL. The source and the exact payload
fact must both be present.

The ordinary `python manage.py ingest manual_capture` schema remains byte-for-
byte compatible with TASK_006. It continues to reject `condition`,
`occurred_at`, `stated_condition`, `stated_price_kind`, and every other unknown
top-level key. No browser, DRF endpoint, admin form, generic model API, or
ordinary command accepts a price-kind override.

The demo command is the only producer added by TASK_027 that writes
`stated_price_kind` into immutable payload evidence.

## 7. Fixed calendar and timestamp contract

The two primary pricing days are fixed Manila dates:

```text
D1 = 2026-06-15
D2 = 2026-07-15
```

Every source observation occurs at 12:00 Asia/Manila on its stated day and is
fetched five minutes later. The persisted aware UTC instants are therefore:

```text
occurred_at = <day>T04:00:00Z
fetched_at  = <day>T04:05:00Z
```

`Listing.observed_at` must equal `occurred_at`, preserving the committed
occurred-before-fetched rule. Storage remains UTC.

The committed 90-day Manila windows are:

```text
D1: [2026-03-17, 2026-06-15)
    UTC bounds [2026-03-16T16:00:00Z, 2026-06-14T16:00:00Z)

D2: [2026-04-16, 2026-07-15)
    UTC bounds [2026-04-15T16:00:00Z, 2026-07-14T16:00:00Z)
```

The five initial history dates are:

```text
2026-04-27
2026-05-07
2026-05-17
2026-05-27
2026-06-05
```

They fall inside both windows. Ordinary observations at noon Manila on D1 are
excluded from their D1 baselines and included in D2. Deal targets at noon
Manila on D2 are excluded from D2. Fixed source instants make fresh-database
results reproducible independently of wall-clock execution time.

`SkuAlias.created_at`, `Listing.resolved_at`, `PricePoint.calculated_at`, and
`DealFlag.flagged_at` truthfully record first-run execution time. They are not
backdated. Reruns reuse them without mutation.

## 8. Deterministic catalogue and aliases

The manifest contains exactly two visibly synthetic SKUs:

| Key | brand | model | variant | category | launch_msrp | launch_date |
|---|---|---|---|---|---:|---|
| atlas | PriceWatchPH Demo | Atlas GPU | 12GB | gpu | 40000.00 | 2025-01-15 |
| beacon | PriceWatchPH Demo | Beacon CPU | 8C16T | cpu | 25000.00 | 2025-02-15 |

The natural identity is the existing `(brand, model, variant)` uniqueness.
Existing rows with that identity are reused only when every remaining manifest
field matches. Otherwise the command fails transactionally.

The manifest contains exactly four aliases, all with
`source_of_truth="seed"`:

| SKU | alias_text |
|---|---|
| atlas | PRICEWATCHPH DEMO // Atlas GPU 12GB |
| atlas | DEMO Atlas-GPU / 12 GB |
| beacon | PRICEWATCHPH DEMO // Beacon CPU 8C16T |
| beacon | DEMO Beacon-CPU / 8C 16T |

`normalised_text` is produced only by the committed `normalise_title()`.
Existing aliases are identified by globally unique normalized text and are
reused only when SKU, original alias text, and source of truth all match.
Otherwise the command fails. The command never repoints or repairs an alias.

## 9. Deterministic RawListing manifest

Every RawListing uses the approved `manual_capture` Source, a Decimal-parsable
two-place price string, seller `""`, and this exact payload shape:

```json
{
  "title": "<exact raw title>",
  "price": "<exact two-place price text>",
  "url": "https://pricewatchph-demo.invalid/listings/<slug>/",
  "external_id": "pricewatchph_demo_v1:<identity>",
  "stated_condition": "<condition>",
  "stated_price_kind": "asking"
}
```

The column values equal their corresponding payload facts. `raw_price` is the
exact Decimal value. `occurred_at` and `fetched_at` follow Section 7. The
manifest contains exactly these 16 rows:

| External-ID suffix | SKU result | Condition | Day | Price | Title form |
|---|---|---|---|---:|---|
| atlas:used:history:01 | atlas | used | 2026-04-27 | 10000.00 | atlas canonical alias |
| atlas:used:history:02 | atlas | used | 2026-05-07 | 11000.00 | atlas alternate alias |
| atlas:used:history:03 | atlas | used | 2026-05-17 | 12000.00 | atlas canonical alias |
| atlas:used:history:04 | atlas | used | 2026-05-27 | 13000.00 | atlas alternate alias |
| atlas:used:history:05 | atlas | used | 2026-06-05 | 14000.00 | atlas canonical alias |
| atlas:used:ordinary:d1 | atlas | used | 2026-06-15 | 12500.00 | atlas alternate alias |
| atlas:used:deal:d2 | atlas | used | 2026-07-15 | 9250.00 | atlas canonical alias |
| atlas:new:history:01 | atlas | new | 2026-07-05 | 16000.00 | atlas alternate alias |
| beacon:like_new:history:01 | beacon | like_new | 2026-04-27 | 20000.00 | beacon canonical alias |
| beacon:like_new:history:02 | beacon | like_new | 2026-05-07 | 21000.00 | beacon alternate alias |
| beacon:like_new:history:03 | beacon | like_new | 2026-05-17 | 22000.00 | beacon canonical alias |
| beacon:like_new:history:04 | beacon | like_new | 2026-05-27 | 23000.00 | beacon alternate alias |
| beacon:like_new:history:05 | beacon | like_new | 2026-06-05 | 24000.00 | beacon canonical alias |
| beacon:like_new:ordinary:d1 | beacon | like_new | 2026-06-15 | 22500.00 | beacon alternate alias |
| beacon:like_new:deal:d2 | beacon | like_new | 2026-07-15 | 19250.00 | beacon canonical alias |
| unresolved:mystery:d2 | unresolved | used | 2026-07-15 | 9999.00 | PRICEWATCHPH DEMO // Mystery Component Prototype |

The full external ID is the prefix `pricewatchph_demo_v1:` plus the table
suffix. URL slugs replace colons with hyphens. The unresolved title has no
alias.

Sixteen observations are the smallest corpus that satisfies the approved
product properties without reusing one fact for incompatible roles. Each of
two scored SKUs needs five pre-D1 observations for a usable baseline, one D1
ordinary observation that is excluded from D1 but moves D2 history, and one D2
deal target that is excluded from D2: fourteen rows. One additional Atlas
`new` observation is the minimum for same-SKU condition-separated pricing, and
one alias miss is the minimum unresolved review queue. No row exists solely to
increase a count or cross an API page boundary.

The logical RawListing identity for bootstrap conflict detection is
`(manual_capture Source, external_id)`, which is deliberately narrower than the
existing database constraint `(source, external_id, fetched_at)`. For each
manifest external ID:

- zero rows means create the exact immutable row;
- one byte-for-byte matching row means reuse it; and
- more than one row, a different fetched time, or any different immutable
  field means conflict.

This prevents the database's wider triple identity from turning a conflicting
rerun into a second observation.

## 10. Resolver outcomes

The command calls `resolve_raw_listing()` for its owned RawListings. It does
not create Listings directly.

The 15 aliased rows resolve to their manifest SKU with:

```text
resolution_method = exact_alias
resolution_confidence = 1.0000
price = RawListing.raw_price
condition = stated_condition
price_kind = asking
trade_side = NULL
observed_at = occurred_at
```

The mystery row resolves with the same source-derived price, condition,
price-kind, and time facts, but:

```text
sku = NULL
resolution_method = unresolved
resolution_confidence = 0.0000
reviewed_unresolved_at = NULL
```

It is therefore the one existing `/reviews` queue row. The resolver creates no
SKU or alias for it.

If a manifest RawListing already has a Listing, the command compares every
stable expected derived field before delegating. Any disagreement, including a
human-confirmed or manually changed Listing, is a conflict. The command fails
and transaction rollback preserves the pre-existing state. It never uses the
resolver to repair owned drift.

## 11. Exact pricing proof and outputs

The command calls `build_pricepoint()` for exactly these identities, in stable
`(day, sku natural key, condition)` order:

| SKU | Condition | Day | n | median | p25 | p75 | MAD |
|---|---|---|---:|---:|---:|---:|---:|
| atlas | used | 2026-06-15 | 5 | 12000.0000 | 11000.0000 | 13000.0000 | 1000.0000 |
| atlas | new | 2026-07-15 | 1 | 16000.0000 | 16000.0000 | 16000.0000 | 0.0000 |
| atlas | used | 2026-07-15 | 6 | 12250.0000 | 11250.0000 | 12875.0000 | 1000.0000 |
| beacon | like_new | 2026-07-15 | 6 | 22250.0000 | 21250.0000 | 22875.0000 | 1000.0000 |

These values were derived with the committed Decimal Type 7 and raw-MAD
implementation. The D1 ordinary rows are excluded from D1 but become the sixth
D2 observations, producing a two-point primary history without adding a
separate row solely for charting. The D2 deals are excluded from D2. The Atlas
`new` point proves same-SKU condition separation and truthful insufficient,
zero-MAD evidence.

Every new PricePoint has the committed bounds, aware calculation time, and:

```text
calculation_contract_version = asking_price_baseline_v1
```

The command then calls `score_listing()` for every owned Listing in stable
RawListing identity order. Most have no own-day PricePoint or do not qualify.
The two D1 ordinary observations have score `0.5000` against their D1 baselines
and create no flags.

Exactly two D2 target rows qualify:

```text
atlas:  (9250.00 - 12250.0000) / 1000.0000 = -3.0000
beacon: (19250.00 - 22250.0000) / 1000.0000 = -3.0000
```

Exactly `-3.0000` is the committed inclusive threshold. Each flag references
the matching D2 PricePoint and has:

```text
reason = asking_price_mad_v1
```

No Outcome is created. The command performs no Decimal calculation itself and
does not directly insert PricePoint or DealFlag rows.

After bootstrap, ordinary `price_listings --day 2026-06-15` and
`price_listings --day 2026-07-15` replays reuse the sealed outputs without
mutation. They create no historical PricePoint, preserving TASK_022.

## 12. API-visible behavior

With existing authentication and model permissions:

- `/api/v1/deal-flags/` returns exactly the two persisted threshold flags;
- the Atlas SKU history contains two `used` points and one separate `new`
  point;
- the Beacon SKU history contains two `like_new` points;
- condition filters retain the committed API behavior; and
- `/api/v1/reviews/listings/` contains exactly the mystery row.

The dataset remains below the fixed page size of 25. TASK_027 does not inflate
it merely to retest pagination already frozen by TASK_023 through TASK_026.
No API request runs bootstrap, resolution, aggregation, or scoring. No frontend
file changes and no browser-side pricing are permitted.

## 13. Idempotency, conflicts, and transaction behavior

One enabled command invocation is one database transaction.

On a pristine migrated database, it creates exactly:

```text
2 Sku
4 SkuAlias
16 RawListing
16 Listing
5 PricePoint
2 DealFlag
0 Outcome
```

On an unchanged rerun, every row is reused and every persisted field and
primary key remains unchanged, including creation, resolution, calculation,
and flag timestamps. No new row is inserted and no row is updated or deleted.

The command validates all owned existing state:

- SKU natural identities and remaining catalogue facts;
- alias normalized identities and remaining alias facts;
- RawListing logical identities and every immutable field;
- pre-existing Listing stable derived fields;
- PricePoint identities, statistics, bounds, sample counts, MAD, and version;
  and
- DealFlag listing identity, exact baseline, score, and reason.

Any mismatch raises `CommandError`. Unexpected duplicate logical identities
also raise `CommandError`. The outer transaction rolls back every earlier
create or derived write from that invocation. Pre-existing conflicting rows
remain unchanged.

There is no cleanup, overwrite, repair, reset, delete/recreate, or partial
success. RawListing, PricePoint, and DealFlag immutability remains absolute.

## 14. Success output

After all expected state is present and validated, every successful first run
or no-op rerun writes exactly one stdout line:

```text
Demo data ready: dataset=pricewatchph_demo_v1 skus=2 aliases=4 raw_listings=16 listings=16 pricepoints=5 dealflags=2 unresolved=1
```

The line describes the ready dataset totals, not rows created by that
invocation and not market coverage or accuracy. No success line is written on
failure. There is no stderr success output, per-row output, analytics summary,
or persistent run record.

## 15. Frozen acceptance criteria

The authoritative executable artifact is:

```text
tests/test_task_027_deterministic_demo_data_bootstrap.py
```

It freezes these behavioral categories:

### Gate and command surface

- the environment setting defaults false, is documented false, and only the
  literal environment value `"1"` enables it;
- the disabled command writes nothing;
- the enabled command requires the existing approved Source;
- no reset, delete, or force option exists, while standard Django command
  options remain out of TASK_027's custom surface; and
- success output is the one exact totals line.

### Provenance and manifest

- exact synthetic catalogue, aliases, external IDs, URLs, source, payload,
  seller absence, UTC instants, and Manila days;
- the full pre-existing Source set and source-health state are preserved,
  `manual_capture` is used, and `personal_records` remains unused;
- exact alias resolution and the one unresolved queue row; and
- ordinary TASK_006 manual capture remains unchanged.

### Explicit price-kind trust

- exact manual-capture payload asking fact is trusted;
- source name alone remains insufficient;
- another Source cannot supply the new asking fact;
- trade-side facts take realised precedence; and
- unsupported explicit price-kind values remain untrusted.

### Pricing and product evidence

- exact five PricePoints, Type 7 values, nonzero primary MAD, zero-MAD
  secondary condition, bounds, and versions;
- D1 ordinary and D2 target membership boundaries;
- exactly two inclusive-threshold DealFlags and no ordinary flags;
- API-visible deal, condition-separated history, and review evidence; and
- no Outcome or browser/API pricing side effect.

### Reruns and conflicts

- unchanged second run preserves an exact database snapshot;
- a conflicting deterministic SKU fails atomically;
- a conflicting RawListing logical identity, including multiple rows sharing
  one logical identity at different fetched times, fails atomically;
- changed derived Listing state is not repaired; and
- conflicting sealed PricePoint evidence is not replaced.

## 16. Schema and migration disposition

No schema change or migration is required. Existing Sku, SkuAlias, RawListing,
Listing, PricePoint, DealFlag, Source, and Outcome fields and constraints
represent the complete contract.

`stated_price_kind` is immutable JSON payload evidence consumed narrowly by the
resolver. It is not a model field, generic override, or API field. No synthetic
marker column, run table, policy model, or cleanup relationship is added.

## 17. Explicit non-goals

TASK_027 does not include or scaffold:

- changes to the ordinary `ingest manual_capture` input contract;
- new Sources, live source integrations, scraping, APIs, or network access;
- personal-record import or Outcome fabrication;
- scheduler, TASK_008, cron, run health, alerts, notifications, or Phase 7;
- pricing formulas, thresholds, baseline windows, resolver normalization, or
  fuzzy matching changes;
- direct downstream evidence seeding;
- reset, cleanup, destructive deletion, repair, or mutable demo lifecycle;
- production deployment, Caddy, HTTPS, backups, or cloud configuration;
- API, serializer, view, route, React, CSS, or frontend test changes;
- users, passwords, sessions, permissions, or authentication setup;
- market accuracy, representativeness, benchmark, or performance claims;
- model, constraint, index, migration, or dependency changes; or
- modifications to prior task specifications or frozen tests.

## 18. Validation requirements

Before implementation is complete, run from the repository root:

```text
docker compose exec web pytest -v tests/test_task_027_deterministic_demo_data_bootstrap.py
docker compose exec web pytest -v sources/tests/test_task_002_sources.py ingestion/tests/test_task_003_ingestion.py ingestion/tests/test_task_005_provenance.py ingestion/tests/test_task_006_manual_capture.py ingestion/tests/test_task_007_trade_logging.py
docker compose exec web pytest -v listings/tests/test_task_013_honest_incomplete_listings.py listings/tests/test_task_014_deterministic_resolver.py listings/tests/test_task_015_operational_resolution.py listings/tests/test_task_016_reviewed_unresolved_state.py listings/tests/test_task_017_constrained_review.py listings/tests/test_task_018_alias_curation.py
docker compose exec web pytest -v pricing/tests/test_task_019_pricing_evidence.py pricing/tests/test_task_020_rolling_pricepoints.py pricing/tests/test_task_021_deal_scoring.py pricing/tests/test_task_022_operational_pricing.py
docker compose exec web pytest -v tests/test_task_023_drf_foundation_and_read_api.py tests/test_task_024_react_deal_and_sku_experience.py tests/test_task_025_shared_review_services_and_mutation_api.py tests/test_task_026_react_review_workflow_and_same_origin_integration.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py check
```

Also run the existing frontend test, lint, and production-build commands even
though TASK_027 changes no frontend file. Validate the real disabled and enabled
shell command, both fixed-day `price_listings` replays, the exact API surfaces,
and the unchanged second-run database snapshot on PostgreSQL 16.

Static review must confirm:

- only the approved IMPLEMENT files changed;
- no direct `Listing`, `PricePoint`, or `DealFlag` insertion bypass exists;
- no new source or network path exists;
- no ordinary capture or API/browser override was introduced;
- no mutable or destructive demo lifecycle exists;
- no migration or frontend change exists;
- all prior frozen artifacts remain unchanged; and
- unrelated working-tree changes remain unstaged and untouched.

No implementation begins until this specification and its frozen acceptance
module receive explicit owner approval.
