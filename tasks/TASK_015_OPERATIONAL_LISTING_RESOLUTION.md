# TASK_015 — Operational Listing resolution command

## 1. Goal

Provide the smallest operational entry point that applies the committed
TASK_014 resolver to every existing immutable `RawListing`:

```text
python manage.py resolve_listings
```

The command makes deterministic v1 resolution runnable as an ordinary Django
management command. It owns batch invocation only. All title normalization,
alias matching, provenance derivation, rerun behavior, and human-confirmed
protection remain owned by `listings.resolver.resolve_raw_listing()`.

TASK_015 completes the operational Phase 3 boundary approved after TASK_014. It
does not add scheduling, run bookkeeping, review workflow, or new resolution
logic.

## 2. Authoritative context

This task follows:

- `CLAUDE.md`;
- `docs/03_PLANNING.md`;
- TASK_013's honest incomplete `Listing` schema; and
- TASK_014's deterministic normalization and one-row resolver contract.

The repository already provides:

- an immutable `RawListing` model;
- a one-to-one `Listing.raw_listing` relationship;
- nullable price, condition, provenance, and SKU fields for honest incomplete
  derivations;
- exact `SkuAlias.normalised_text` resolution;
- rerunnable machine-derived Listing behavior;
- protection for `human_confirmed` Listings; and
- normal Django management-command discovery through installed applications.

TASK_015 requires no model or migration change.

## 3. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_015_OPERATIONAL_LISTING_RESOLUTION.md`
- `listings/tests/test_task_015_operational_resolution.py`

After approval, neither frozen artifact may be modified to make implementation
pass. A contradictory or incorrect frozen test stops implementation for human
review.

### IMPLEMENT files allowed

- `listings/management/__init__.py`
- `listings/management/commands/__init__.py`
- `listings/management/commands/resolve_listings.py`

No existing resolver, normalizer, model, migration, ingestion path, frozen
test, planning document, admin surface, dependency, or tooling file is in
scope.

## 4. Command contract

TASK_015 adds exactly:

```text
python manage.py resolve_listings
```

The command:

- requires no positional arguments;
- provides no source, date, status, unresolved-only, or other selector;
- reads no stdin and prompts for no interactive input;
- performs no network access; and
- uses Django's ordinary command exit behavior.

Successful execution requires no stable stdout or stderr payload. Existing
repository command conventions do not require a count, so v1 remains silent
apart from framework-level output selected by Django itself. Persistent or
scheduler-facing reporting is explicitly outside TASK_015.

## 5. Selection and deterministic order

Every invocation selects every existing `RawListing`, including observations
that already have a `Listing`.

Rows are processed in ascending `RawListing.pk` order. Primary-key ordering is
an operational determinism rule, not a claim that primary keys encode source
event chronology.

The command is deliberately rerunnable rather than restricted to observations
without a Listing. This is required because TASK_014 permits:

- unresolved rows to become `exact_alias` after curated alias additions;
- machine-resolved rows to change after alias repointing or removal;
- unchanged machine-derived rows to remain untouched; and
- `human_confirmed` rows to remain authoritative.

The command does not maintain a cursor, watermark, last-run timestamp, or
processed flag.

## 6. Resolver delegation

For each selected row, the command calls the existing:

```python
listings.resolver.resolve_raw_listing(raw_listing)
```

The command must not duplicate or replace any TASK_014 behavior. In
particular, it does not:

- normalize titles itself;
- query or interpret aliases itself;
- assign SKU, condition, confidence, price kind, or trade side itself;
- create or update a Listing directly;
- create `Sku` or `SkuAlias` rows; or
- special-case `human_confirmed` rows itself.

Those decisions remain centralized in the resolver so direct and operational
invocation cannot drift apart.

## 7. Transaction and failure semantics

One command invocation is one outer database transaction covering the complete
ordered batch.

TASK_014's per-row atomic resolver calls may nest inside that outer transaction.
If every row resolves successfully, all resulting creates or updates commit
together.

If any resolver call raises an unexpected exception:

- the exception is not swallowed or converted into success;
- Django command execution exits unsuccessfully through normal exception
  behavior; and
- every Listing create or update made by that command invocation is rolled
  back, including changes made for earlier rows in the ordered batch.

Pre-existing database state from before the invocation remains intact. The
command must not attempt to repair failure by deleting or rewriting immutable
RawListing rows.

TASK_015 defines no retry, partial-success, rejection, or continue-on-error
semantics.

## 8. Preserved behavior and boundaries

Operational invocation preserves all TASK_013 and TASK_014 guarantees:

- `RawListing` is never updated or deleted;
- one and only one current `Listing` may exist per `RawListing`;
- nullable price and condition remain honest representations of missing facts;
- ordinary alias misses remain `unresolved` with confidence `0.0000`;
- exact aliases remain `exact_alias` with confidence `1.0000`;
- no ordinary miss is relabelled as `fuzzy_match`;
- machine-derived rows are rerunnable;
- unchanged reruns preserve `resolved_at`;
- human-confirmed Listings are never overwritten automatically; and
- no catalogue, pricing, outcome, ingestion, source-health, or swap state is
  created or updated beyond the Listing changes performed by TASK_014.

The command does not update `Source.last_successful_fetch`. That field and any
run-level health interpretation remain deferred with TASK_008.

## 9. Acceptance criteria — frozen

The authoritative acceptance module is:

```text
listings/tests/test_task_015_operational_resolution.py
```

It uses only hand-authored synthetic observations, SKUs, and aliases. These
tests prove command and transaction behavior only; they do not measure or claim
Philippine market resolution accuracy.

### Command and delegation

- `test_command_is_registered_and_handles_an_empty_database`
- `test_command_delegates_every_rawlisting_in_primary_key_order`
- `test_unprocessed_rawlistings_receive_task_014_listings`

### Reruns

- `test_existing_machine_listings_are_reconsidered_on_rerun`
- `test_unchanged_command_rerun_preserves_listing_and_resolved_at`
- `test_command_preserves_human_confirmed_listing`

### Integrity and failure

- `test_command_never_mutates_rawlistings`
- `test_command_creates_no_catalogue_downstream_or_bookkeeping_state`
- `test_batch_failure_rolls_back_earlier_listing_creates_and_updates`
- `test_unexpected_resolver_exception_is_not_swallowed`

The command-specific negative tests import and patch the real TASK_015 command
module. They cannot pass merely because Django reports `Unknown command`.

## 10. Explicit non-goals

TASK_015 does not include or scaffold:

- model or migration changes;
- persistent run history, counters, summaries, or rejection records;
- TASK_008 or `Source.last_successful_fetch` updates;
- scheduler, cron, deployment, or health-check configuration;
- retry, parallel, background-worker, broker, or partial-success behavior;
- filtering by source, date, status, resolution method, or any other selector;
- fuzzy or heuristic matching;
- confidence calibration;
- production catalogue or alias seed data;
- automatic `Sku` or `SkuAlias` creation;
- Phase 4 review or human-confirmation UI;
- pricing baselines, `PricePoint`, `DealFlag`, or `Outcome` work;
- ingestion changes or new sources;
- external APIs, web search, scraping, or LLM inference; or
- changes to TASK_014 normalization or resolver behavior.

## 11. Implementation and validation requirements

Implementation must remain within the three command-package files listed in
Section 3. The command uses one outer `transaction.atomic()` boundary, iterates
`RawListing.objects.order_by("pk")`, and delegates each row to the imported
TASK_014 `resolve_raw_listing` function.

No output format is frozen. No implementation branch may detect test-only
conditions.

Because source is baked into the Docker image, rebuild and recreate the web
service when required, then run:

```text
docker compose exec web pytest -v listings/tests/test_task_015_operational_resolution.py
docker compose exec web pytest -v listings/tests/test_task_014_deterministic_resolver.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
git diff --check
git diff --cached --check
```

Final validation must additionally confirm:

- the frozen TASK_015 task and test hashes are unchanged;
- no migration or model change exists;
- existing TASK_013 and TASK_014 tests remain green;
- RawListing application and PostgreSQL immutability remain enforced;
- no float or `FloatField` money path exists;
- no automatic catalogue or downstream writes occur;
- `Source.last_successful_fetch` remains untouched; and
- unrelated working-tree changes remain unstaged and byte-identical.

No implementation is approved until this specification and its frozen test
module receive explicit human approval.
