# TASK_016 — Add durable reviewed-unresolved Listing state

## 1. Goal

Add the smallest durable state needed to distinguish a machine-unresolved
`Listing` that still needs human review from one a human already reviewed but
could not safely resolve.

TASK_016 adds one nullable timestamp to `Listing` and integrates that marker
with the existing TASK_014 deterministic resolver. It does not implement the
Phase 4 Django-admin review workflow.

## 2. Authoritative context

This task follows:

- `CLAUDE.md`;
- `docs/04_PLANNING.md`;
- TASK_013's honest incomplete `Listing` schema;
- TASK_014's deterministic exact-alias resolver and rerun semantics; and
- TASK_015's operational command, which delegates every `RawListing` to
  `resolve_raw_listing()`.

The current schema and resolver already establish:

- exactly one mutable derived `Listing` per immutable `RawListing`;
- `unresolved` with `sku=NULL` and confidence `0.0000` for an exact-alias miss;
- `exact_alias` with the matched curated SKU and confidence `1.0000`;
- historical schema validity for `sku=NULL + fuzzy_match`;
- no new fuzzy matching in TASK_014;
- preservation of every `human_confirmed` Listing field on automatic rerun;
- unchanged machine reruns preserving `resolved_at`; and
- changed machine results updating the existing Listing and `resolved_at`.

`sku IS NULL` alone cannot distinguish pending human review from an exhausted
human review. TASK_016 adds that distinction without redefining any resolution
method or confidence value.

## 3. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_016_DURABLE_REVIEWED_UNRESOLVED_STATE.md`
- `listings/tests/test_task_016_reviewed_unresolved_state.py`

After owner approval, neither frozen artifact may be modified to make
implementation pass. If a frozen test contradicts the authoritative repository
state, implementation must stop and report the conflict.

### IMPLEMENT files allowed

- `listings/models.py`
- `listings/resolver.py`
- one new generated migration under `listings/migrations/`, depending on
  `0003_remove_listing_listing_resolution_method_in_vocabulary_and_more`

No other model, resolver component, command, admin surface, migration, test,
task, planning document, dependency, Docker file, or tooling file is in scope.

## 4. Locked schema change

Add exactly this field to `Listing`:

```python
reviewed_unresolved_at = models.DateTimeField(
    null=True,
    blank=True,
)
```

Required metadata:

- `DateTimeField`;
- `null=True`;
- `blank=True`;
- no model default; and
- no database default.

Existing Listings naturally receive SQL `NULL` when the nullable column is
added. The migration performs no data backfill or other data operation.

No review status, reviewer foreign key, review model, catalogue version,
evidence version, condition-confirmation field, or other schema is added.

The future Phase 4 primary queue will be:

```text
sku IS NULL
AND reviewed_unresolved_at IS NULL
```

TASK_016 does not implement that queue or any UI action that writes the marker.

## 5. Resolver-result identity

TASK_016 responds only to the prior persisted machine result and the new result
computed by TASK_014's existing exact-alias resolver.

For this task, a machine result is identified by:

- `resolution_method`; and
- `sku_id` when the method is `exact_alias`.

The resolver must not add catalogue version tracking, signals, timestamps for
catalogue evidence, or an abstract "material change" detector.

TASK_014 continues to compute only:

```text
unresolved:
    sku_id = NULL
    resolution_method = unresolved
    resolution_confidence = 0.0000

exact alias:
    sku_id = matched curated SKU
    resolution_method = exact_alias
    resolution_confidence = 1.0000
```

## 6. Locked marker transitions

For an existing machine-derived Listing, `resolve_raw_listing()` must implement
exactly these transitions:

| Before result | After result | Marker behavior |
|---|---|---|
| `unresolved` | `unresolved` | Preserve `reviewed_unresolved_at` exactly. |
| `unresolved` | `exact_alias` | Clear the marker to `NULL`. |
| `exact_alias` | `unresolved` | Clear the marker to `NULL`. |
| `exact_alias` for SKU A | `exact_alias` for different SKU B | Clear the marker to `NULL`. |
| `exact_alias` for SKU A | unchanged `exact_alias` for SKU A | Preserve the marker exactly. |
| `human_confirmed` | automatic resolver returns early | Change no Listing field, including the marker. |

The marker is current queue state, not a catalogue history or accuracy field.
It is irrelevant to queue membership while `sku` is non-null, but the approved
unchanged-result rule still preserves its exact stored value.

### 6.1 `resolved_at`

TASK_014's existing `resolved_at` contract remains:

- an unchanged automatic result performs no write and preserves `resolved_at`;
- a changed automatic result updates the existing Listing and refreshes
  `resolved_at`; and
- `human_confirmed` returns early and preserves `resolved_at` with every other
  field.

Clearing an already-`NULL` marker does not turn an otherwise unchanged result
into a change. Conversely, the approved changed-result transitions already
change method or SKU and therefore retain TASK_014's normal update behavior.

## 7. Historical fuzzy compatibility

`fuzzy_match` remains an allowed historical resolution method. TASK_016 must
not remove it, constrain it against nullable SKU, or modify frozen TASK_004 and
TASK_013 compatibility.

TASK_014 does not perform fuzzy matching and must never emit a new
`fuzzy_match`. An existing historical fuzzy result is a machine-result class
distinct from the two current TASK_014 outputs. Therefore:

| Before result | After TASK_014 result | Marker behavior |
|---|---|---|
| historical `fuzzy_match` | `unresolved` | Clear the marker to `NULL`. |
| historical `fuzzy_match` | `exact_alias` | Clear the marker to `NULL`. |

The historical state remains valid before rerun, including:

```text
sku = NULL
resolution_method = fuzzy_match
resolution_confidence = 0.0000
```

No TASK_016 code creates a fuzzy result or assigns an intermediate confidence.

## 8. First derivation and existing rows

A first resolver derivation creates its single Listing with
`reviewed_unresolved_at=NULL` through the field's nullable no-default behavior.
It does not explicitly fabricate a review timestamp.

Existing rows receive `NULL` from the schema addition without a data migration.
Historical rows therefore remain eligible for the future queue until a Phase 4
human action explicitly records otherwise.

## 9. Preserved TASK_013–TASK_015 behavior

TASK_016 must preserve:

- nullable Decimal `Listing.price`;
- nullable `Listing.condition`;
- the complete condition and resolution-method vocabularies;
- historical `sku=NULL + fuzzy_match` validity;
- `unresolved` confidence `0.0000`;
- `exact_alias` confidence `1.0000`;
- no automatic fuzzy result;
- one Listing per RawListing;
- TASK_014 provenance copying and no fact inference;
- unchanged automatic reruns preserving Listing identity and `resolved_at`;
- automatic reconsideration of unresolved and exact-alias Listings;
- early return for every `human_confirmed` Listing;
- RawListing application and PostgreSQL immutability;
- no automatic `Sku` or `SkuAlias` creation; and
- TASK_015 all-row, primary-key-ordered, atomic delegation behavior.

The TASK_015 command requires no production change. It inherits TASK_016
behavior by continuing to call `resolve_raw_listing()`.

## 10. Migration contract

The IMPLEMENT pass creates the smallest generated Django migration needed to
add the single nullable field.

The migration must:

- depend on the current latest listings migration;
- contain one `AddField` operation for `reviewed_unresolved_at`;
- contain no default;
- contain no `RunPython`, `RunSQL`, backfill, or other data operation; and
- modify no existing field, constraint, table, or migration.

No existing migration may be regenerated, squashed, edited, or replaced.

## 11. Acceptance criteria — frozen

The authoritative acceptance module is:

```text
listings/tests/test_task_016_reviewed_unresolved_state.py
```

It uses synthetic records only and freezes:

### Schema

- `test_reviewed_unresolved_at_field_contract`
- `test_existing_listing_creation_uses_null_review_marker`

### Current TASK_014 transitions

- `test_unresolved_to_unresolved_preserves_marker_and_resolved_at`
- `test_unresolved_to_exact_alias_clears_marker`
- `test_exact_alias_to_unresolved_clears_marker`
- `test_exact_alias_repoint_clears_marker`
- `test_unchanged_exact_alias_preserves_marker_and_resolved_at`
- `test_human_confirmed_preserves_marker_and_every_listing_field`

### Historical compatibility

- `test_historical_fuzzy_to_unresolved_clears_marker`
- `test_historical_fuzzy_to_exact_alias_clears_marker`
- `test_historical_null_sku_fuzzy_match_remains_valid`

### Existing resolver invariants

- `test_new_machine_results_never_emit_fuzzy_and_keep_confidence_semantics`
  (two parameterized cases)
- `test_resolver_does_not_mutate_rawlisting`
- `test_resolver_creates_no_catalogue_admin_or_downstream_state`
- `test_operational_command_inherits_review_marker_transitions`

Parameterized cases are separately collected by pytest. Every database test
runs against PostgreSQL; SQLite is forbidden.

## 12. Explicit non-goals

TASK_016 does not implement or scaffold:

- Django admin review UI or queue filters;
- a reviewed-but-unresolved admin action;
- human SKU confirmation;
- SKU deletion guardrails;
- aliases, catalogue seed data, or catalogue mutation;
- condition editing or condition inference;
- a broader review model or status vocabulary;
- reviewer identity fields;
- fuzzy or heuristic matching;
- confidence calibration;
- pricing, `PricePoint`, `DealFlag`, or outcome behavior;
- TASK_008, source-health bookkeeping, cron, scheduling, or deployment;
- ingestion changes or new sources;
- web search, scraping, external APIs, embeddings, or LLM inference;
- frontend work;
- dependency, Docker, hook, or tooling changes; or
- modifications to an existing frozen test or migration.

## 13. Validation

During IMPLEMENT, rebuild/recreate the Docker web service when necessary
because application source is baked into its image, then run:

```text
docker compose exec web pytest -v listings/tests/test_task_016_reviewed_unresolved_state.py
docker compose exec web pytest -v \
    listings/tests/test_task_013_honest_incomplete_listings.py \
    listings/tests/test_task_014_deterministic_resolver.py \
    listings/tests/test_task_015_operational_resolution.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
git diff --check
git diff --cached --check
```

The dedicated suite, compatibility suites, and full suite must pass. Migration
drift must report `No changes detected` after the one generated migration is
present.

Final validation must inspect the generated migration and actual PostgreSQL
schema, verify all marker transitions through both direct resolution and the
TASK_015 command, confirm frozen artifact hashes, and confirm no unrelated file
is staged.

No TASK_016 implementation is approved until this specification and its frozen
acceptance module receive explicit human approval.
