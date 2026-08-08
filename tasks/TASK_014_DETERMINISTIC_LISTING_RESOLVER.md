# TASK_014 — Deterministic v1 Listing resolver

## 1. Goal

Implement the smallest deterministic Phase 3 transformation from one immutable
`RawListing` observation to its one mutable derived `Listing`.

V1 normalizes a title reproducibly, performs exact lookup against curated
`SkuAlias.normalised_text`, copies only explicit source facts, and records an
honest unresolved result when no exact alias exists.

The task does not claim market resolution accuracy. Its frozen examples are
synthetic contract fixtures, not an empirical corpus.

## 2. Authoritative context

This task follows:

- `CLAUDE.md`;
- `docs/03_PLANNING.md`;
- TASK_004 Listing and catalogue constraints;
- TASK_005 provenance fields and `listings.observation.observed_at_for()`;
- TASK_006 `manual_capture` payload semantics;
- TASK_007 `personal_records` payload semantics; and
- TASK_013's nullable price/condition and explicit `unresolved` state.

The repository already provides all required schema:

- `RawListing` is immutable and contains source title, nullable Decimal price,
  source/fetch timestamps, and nullable JSON payload;
- `Sku` and `SkuAlias` are curated catalogue data;
- `SkuAlias.normalised_text` is globally unique and points to one `Sku`;
- `Listing.raw_listing` is one-to-one;
- `Listing.sku`, `price`, `condition`, `observed_at`, `price_kind`, and
  `trade_side` can represent missing evidence honestly; and
- resolution method/confidence constraints accept `exact_alias` with `1.0000`
  and `unresolved` with `0.0000`.

TASK_014 requires no model or migration change.

## 3. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_014_DETERMINISTIC_LISTING_RESOLVER.md`
- `listings/tests/test_task_014_deterministic_resolver.py`

After approval, neither frozen artifact may be modified to make implementation
pass. A contradictory or incorrect frozen test stops implementation for human
review.

### IMPLEMENT files allowed

- `listings/normalisation.py`
- `listings/resolver.py`

No existing model, migration, ingestion path, frozen test, planning document,
admin surface, dependency, or tooling file is in scope.

## 4. Public implementation boundary

TASK_014 exposes two direct Python functions:

```python
from listings.normalisation import normalise_title
from listings.resolver import resolve_raw_listing

normalised = normalise_title(raw_title)
listing = resolve_raw_listing(raw_listing)
```

`normalise_title(text)` is a pure function from `str` to `str`. It reads and
writes no database state.

`resolve_raw_listing(raw_listing)` derives exactly one observation and returns
the corresponding `Listing` instance. It is atomic and performs no batch,
management-command, scheduler, or run-reporting work.

Separating the pure normalizer from persistence gives future seed and human
alias creation one reproducible normalization primitive without building a
generic resolver framework.

## 5. Deterministic normalization

The exact v1 algorithm is:

1. Apply `unicodedata.normalize("NFKC", text)`.
2. Apply Unicode `str.casefold()`.
3. Preserve each Unicode alphanumeric character for which `str.isalnum()` is
   true.
4. Treat every other character as a token boundary. This covers punctuation,
   separators, whitespace, and symbols without deleting adjacent alphanumeric
   tokens.
5. Collapse all resulting boundaries to one ASCII space and remove leading or
   trailing space.

The result contains alphanumeric token content in its original order. The
normalizer does not split an uninterrupted letter/digit run: `RTX4070` becomes
`rtx4070`, not `rtx 4070`.

V1 deliberately does not:

- remove price digits or ranges from a title;
- remove generic words such as `brand new`;
- remove brands, capacities, generation numbers, or variants;
- simplify or discard Ti, Super, XT, XTX, OC, Gaming, Ventus, TUF, mobile, or
  laptop tokens; or
- perform stemming, synonym expansion, edit-distance matching, token sorting,
  or another domain heuristic.

For example, the peso symbol and comma in `RTX 4070 ₱15,500` become boundaries,
but the source-stated `15` and `500` tokens remain in the derived normalized
text. `RawListing.raw_title` itself is never modified.

## 6. Exact alias resolution

The resolver computes `normalise_title(raw_listing.raw_title)` and performs an
exact lookup against the globally unique `SkuAlias.normalised_text` field.

### Exact curated alias

When one exact alias exists:

```python
sku = alias.sku
resolution_method = "exact_alias"
resolution_confidence = Decimal("1.0000")
```

The resolver consumes the curated alias but never changes or creates catalogue
rows.

### No exact alias

When no exact alias exists:

```python
sku = None
resolution_method = "unresolved"
resolution_confidence = Decimal("0.0000")
```

A near match is still unresolved. V1 never writes `fuzzy_match`; that value is
reserved for a future task that defines and actually runs a fuzzy mechanism
against independently labelled evidence.

Automatic resolution never creates a `Sku` or `SkuAlias` and never normalizes
or repairs a stored alias during lookup.

## 7. Provenance derivation

The resolver copies source facts without inventing missing facts:

| Listing field | V1 value |
|---|---|
| `raw_listing` | the input observation |
| `sku` | exact alias target, otherwise NULL |
| `price` | `RawListing.raw_price`, including NULL |
| `condition` | `payload["stated_condition"]` when supplied by the approved producer, otherwise NULL |
| `location` | `""` because current approved source contracts supply no location |
| `observed_at` | `observed_at_for(raw_listing)` |
| `price_kind` | `"realised"` when `stated_trade_side` is present, otherwise NULL |
| `trade_side` | `payload["stated_trade_side"]` when present, otherwise NULL |
| `resolved_at` | current UTC-aware derivation time for a create or changed automatic result |

Approved TASK_007 payloads constrain `stated_condition` to the Listing
condition vocabulary and `stated_trade_side` to `buy` or `sell`. TASK_006 never
emits either key. Handling a manually fabricated out-of-vocabulary payload is
not broadened into a new input contract by this task; existing model/database
constraints remain the final integrity boundary.

The resolver must not infer condition from title text. A title containing
`brand new`, `used`, or similar language still has condition NULL unless the
approved payload explicitly states a condition.

Source name alone is not evidence. A `personal_records` row without
`stated_trade_side` remains NULL for both `price_kind` and `trade_side`.

The resolver reuses `listings.observation.observed_at_for()` rather than
duplicating the occurred/fetched precedence rule.

## 8. Persistence and reruns

`resolve_raw_listing()` runs atomically.

### First derivation

If the RawListing has no Listing, create it with all fields in Sections 6 and
7. The existing one-to-one constraint remains the database guarantee that one
observation has at most one derived Listing.

### Unchanged automatic rerun

If every derived field already equals the current automatic result, return the
existing Listing without changing its state. In particular, preserve
`resolved_at`.

### Changed automatic rerun

An existing `exact_alias`, `unresolved`, or historical machine-generated
`fuzzy_match` Listing may be reconsidered. If current alias/catalogue evidence
changes the derived result, update the existing Listing in place and refresh
`resolved_at`; do not append a second Listing.

Consequences include:

- adding a curated exact alias promotes `unresolved` to `exact_alias`;
- repointing a curated alias changes the machine-derived SKU on rerun; and
- removing the matching alias changes the machine-derived Listing to
  `unresolved` on rerun.

### Human-confirmed preservation

If the existing Listing has `resolution_method="human_confirmed"`, return it
unchanged. Automatic resolution must not overwrite any of its derived fields or
its `resolved_at`, even if current aliases disagree.

At no point may the resolver update, delete, or repair `RawListing`.

## 9. Acceptance criteria — frozen

The authoritative acceptance module is:

```text
listings/tests/test_task_014_deterministic_resolver.py
```

It uses only hand-authored synthetic titles and aliases. These tests prove
deterministic behavior; they do not measure or claim Philippine market
resolution accuracy.

### Normalization

- `test_normalise_title_is_deterministic`
- `test_normalise_title_applies_nfkc_casefold_and_boundaries`
- `test_normalise_title_uses_unicode_casefold`
- `test_normalise_title_preserves_critical_alphanumeric_tokens`

### Matching and provenance

- `test_exact_normalised_alias_creates_resolved_listing`
- `test_near_alias_miss_is_honestly_unresolved_not_fuzzy`
- `test_null_raw_price_propagates_to_listing`
- `test_stated_condition_is_copied_and_absent_condition_is_not_inferred`
- `test_stated_trade_side_sets_realised_price_kind`
- `test_source_name_without_trade_fact_does_not_imply_trade_semantics`
- `test_observed_at_prefers_occurred_at`
- `test_observed_at_falls_back_to_fetched_at`

### Persistence, reruns, and boundaries

- `test_unchanged_rerun_keeps_one_listing_and_preserves_resolved_at`
- `test_alias_addition_promotes_unresolved_listing_in_place`
- `test_alias_repoint_and_removal_correct_machine_listing_in_place`
- `test_human_confirmed_listing_is_never_overwritten`
- `test_resolver_never_mutates_rawlisting`
- `test_resolver_creates_no_catalogue_or_downstream_state`

Parameterized cases are collected separately by pytest.

## 10. Explicit non-goals

TASK_014 does not include or scaffold:

- fuzzy, heuristic, similarity, embedding, or LLM matching;
- intermediate confidence values or confidence calibration;
- automatic `Sku` or `SkuAlias` creation;
- production catalogue or alias seed data;
- Phase 4 review workflow or admin UI;
- title-derived condition inference;
- pricing baselines, `PricePoint`, `DealFlag`, or `Outcome` writes;
- TASK_008 bookkeeping, `Source.last_successful_fetch`, scheduler, cron, or
  deployment behavior;
- a batch resolver or management command;
- new ingestion sources or changes to approved ingestion paths;
- external APIs, web search, scraping, or network calls;
- model or migration changes; or
- an empirical accuracy percentage from synthetic examples.

## 11. Validation and integrity

During IMPLEMENT, rebuild/recreate the Docker web service when needed because
source is baked into the application image, then run:

```text
docker compose exec web pytest -v listings/tests/test_task_014_deterministic_resolver.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
git diff --check
git diff --cached --check
```

Final validation must additionally confirm:

- the frozen task and test hashes are unchanged;
- no migration or model change exists;
- RawListing application and PostgreSQL immutability tests still pass;
- no float or `FloatField` money path exists;
- no `Sku`, `SkuAlias`, `PricePoint`, `DealFlag`, `Outcome`, or `Swap` row is
  created by resolution;
- `Source.last_successful_fetch` remains untouched; and
- unrelated working-tree changes remain unstaged and byte-identical.

No implementation is approved until this specification and its frozen test
module receive explicit human approval.
