# TASK_006 — `ingest` command and `manual_capture` importer

## 1. Goal

Provide the first scheduler-compatible ingestion entry point:

```text
python manage.py ingest manual_capture
```

One invocation reads one UTF-8 JSON object from standard input and writes one
faithful, immutable `RawListing` under the seeded `manual_capture` source. A
messy source price remains evidence: its exact text is stored even when it
cannot be represented as a Decimal.

TASK_006 establishes the command/importer boundary and one-record capture
contract only. TASK_008 owns successful-run bookkeeping, scheduler-facing
summaries, and updates to `Source.last_successful_fetch`.

## 2. Files

### Hardened artifacts created before implementation

- `tasks/TASK_006_MANUAL_CAPTURE_INGEST.md`
- `ingestion/tests/test_task_006_manual_capture.py`

The test module is frozen after owner approval. Implementation must make it
pass without modifying, skipping, xfail-marking, bypassing, or replacing it.
If a frozen test conflicts with authoritative repository state, implementation
stops and reports the conflict.

### Files the IMPLEMENT pass may create

- `ingestion/management/__init__.py`
- `ingestion/management/commands/__init__.py`
- `ingestion/management/commands/ingest.py`
- `ingestion/manual_capture.py`

No other production file is required or allowed. In particular, TASK_006 does
not modify a model and does not create a migration.

## 3. Dependencies already present

- `Source(name="manual_capture")` is seeded with `rate_limit=None`.
- `RawListing` already has `raw_title`, `raw_price_text`, nullable Decimal
  `raw_price`, `url`, `seller`, `fetched_at`, nullable `occurred_at`, nullable
  `external_id`, and nullable JSON `payload`.
- `RawListing` already has application and PostgreSQL trigger immutability.
- `ingestion.pseudonymise.pseudonymise()` and `redact_payload()` provide the
  only approved seller pseudonymization/redaction path.
- Django supplies `BaseCommand` and `CommandError`; no custom process-exit
  mechanism is needed.
- Python's standard library supplies JSON, Decimal, regular expressions, and
  transaction support; no new dependency is justified.

## 4. Authoritative external contract

### 4.1 Command and dispatch

The only TASK_006 invocation is:

```text
python manage.py ingest manual_capture
```

The command explicitly maps the `manual_capture` name to its importer. It does
not discover importers from `Source` rows, import paths, entry points, plugins,
or filesystem contents. One invocation selects exactly one importer.

The interface is ordinary stdin/stdout/stderr and process exit status. It has
no interactive prompt and no Codex-, Claude-, MCP-, or terminal-specific
behavior. It must work when invoked from an ordinary POSIX shell and remain
suitable for later cron or automation use without changing its input format.

### 4.2 Input transport and cardinality

The command reads exactly one UTF-8 JSON object from stdin. Trailing JSON data
or any trailing non-whitespace content is invalid. Trailing whitespace is
allowed.

There is no batch shape, file-input option, loop over sources, or interactive
fallback. One invocation represents one human-captured observation.

The command owns argument parsing, explicit importer selection, exit behavior,
and passing the stdin input to the selected importer. The importer owns its
JSON format, structural validation, price parsing, redaction, and RawListing
write.

### 4.3 Closed input schema

Required keys:

- `title`
- `price`

Optional keys:

- `url`
- `seller`
- `external_id`

No other top-level key is accepted. In particular, TASK_006 rejects
`occurred_at`, `location`, `context`, and every unknown field. Unknown fields
are not silently discarded or copied into payload.

### 4.4 Title

`title` must be a JSON string containing at least one non-whitespace
character. Validation may inspect `title.strip()` solely to decide whether it
is blank. Once accepted, the original decoded string is written unchanged to
`RawListing.raw_title` and retained unchanged in payload.

The importer must not trim, normalize, collapse whitespace, alter casing or
punctuation, normalize model names, or infer/remove condition wording.

### 4.5 Price text and Decimal grammar

`price` must be a JSON string containing at least one non-whitespace character.
A JSON number is structurally invalid, including when its mathematical value
would otherwise be representable. This prevents fractional JSON numbers from
entering Python as binary floats and preserves the source's exact textual
statement.

The exact decoded string is always written to `RawListing.raw_price_text` and
retained unchanged in payload.

For parsing only, surrounding whitespace may be ignored. The accepted Decimal
grammar is:

- unsigned base-10 integer digits;
- or integer digits using correctly grouped ASCII thousands commas;
- optionally followed by a decimal point and one or two fractional digits.

Examples that parse:

- `15500`
- `15500.00`
- `15,500`
- `15,500.50`

After comma removal the parser uses `Decimal` directly, never `float`. A parsed
candidate is stored only if it is finite, nonnegative, and exactly fits
`DecimalField(max_digits=12, decimal_places=2)` without rounding or truncation.

Every other nonblank string is a valid observation but has
`RawListing.raw_price=NULL`. This includes currency prefixes or symbols,
ranges, scientific notation, negative values, excessive fractional precision,
field overflow, malformed grouping, non-finite Decimal spellings, and prose
such as `PM for price`. Such values do not cause command failure and are never
coerced to zero.

### 4.6 Optional URL

When present, `url` must be a JSON string. It is stored and retained in payload
exactly as supplied. When absent, `RawListing.url` uses the existing empty-string
convention and payload has no `url` key.

### 4.7 Optional seller and privacy boundary

When absent or blank after a whitespace-only check, `seller` is treated as not
stated: `RawListing.seller` is `""` and payload has no `seller` key.

When nonblank, `seller` must be a JSON string. The importer uses the existing
`pseudonymise()` and `redact_payload()` path. `RawListing.seller` and
`payload["seller"]` contain the identical HMAC token, and the plaintext seller
appears nowhere in the persisted RawListing.

There is no second pseudonymizer, fallback digest, plaintext staging column, or
redactor redesign. The external contract accepts counterparty identity only in
the `seller` field. Arbitrary context is rejected because the existing
redactor is deliberately shallow and recognizes only top-level `seller`.

### 4.8 Optional external identifier

When present, `external_id` must be a JSON string containing at least one
non-whitespace character and no more than the current model field's 200
characters. Validation may inspect whitespace and length but stores the
accepted decoded string unchanged in both the column and payload.

When absent, `RawListing.external_id` is NULL. The importer does not manufacture
a content hash or derive an identifier from any other field. Repeating the same
capture without an external identifier is allowed to create another distinct
observation. TASK_006 does not claim idempotency and does not alter the existing
`(source, external_id, fetched_at)` partial uniqueness constraint.

### 4.9 Payload

Payload is the supplied accepted external object only:

- required `title` and `price` are retained exactly;
- supplied `url` and `external_id` are retained exactly;
- a nonblank supplied `seller` is retained only as its approved token;
- an absent or blank seller is omitted;
- absent optional keys are omitted;
- no unknown or arbitrary context key is accepted;
- generated `fetched_at` is not added.

### 4.10 Timestamps and source state

`fetched_at` is generated with Django's timezone-aware current time during the
ingestion operation. The caller cannot supply or backdate it.

`occurred_at` is not accepted and remains NULL. TASK_007's Manila trade-date
semantics are specific to personal trades and are not reused here.

The importer uses the seeded `manual_capture` Source. Its
`rate_limit=None` means no automated cadence exists; it must cause no sleep,
throttle, fabricated default, or failure.

Neither success nor failure updates `Source.last_successful_fetch`. TASK_008
owns that update and the associated run reporting contract.

## 5. Structural failure and atomicity

Structural failures include:

- malformed JSON;
- a top-level value other than an object;
- multiple JSON values or trailing non-whitespace content;
- a missing required key;
- a required or optional value of the wrong JSON type;
- blank/whitespace-only title or price;
- JSON numeric money;
- an unknown key;
- blank/whitespace-only supplied `external_id`;
- supplied `external_id` longer than 200 characters.

A structural failure raises Django `CommandError`, therefore producing a
nonzero CLI process exit through Django's normal `BaseCommand` behavior. It
writes zero RawListing rows. Validation completes before the write.

The one-record operation is enclosed in an atomic transaction. There are no
batch-level partial-success or per-row rejection semantics in TASK_006.

## 6. Frozen acceptance criteria

The executable frozen artifact is:

```text
ingestion/tests/test_task_006_manual_capture.py
```

Every test invokes the real Django command loader. Failure-path helpers reject
`Unknown command` explicitly, so the absent pre-implementation command cannot
make negative cases pass vacuously.

### Command interface

- `test_ingest_manual_capture_reads_exactly_one_stdin_json_object`
- `test_ingest_manual_capture_accepts_utf8_without_an_interactive_terminal`
- `test_importer_name_is_explicit_not_discovered_from_source_rows`
- `test_file_input_argument_is_not_accepted`

These freeze the explicit command/importer name, single stdin object, trailing
whitespace allowance, UTF-8 data, noninteractive operation, and prohibition on
database-driven importer discovery or a file-input mode.

### Structural validation and atomicity

- `test_malformed_json_raises_commanderror_and_writes_nothing`
- `test_non_object_json_writes_nothing`
- `test_trailing_second_json_value_writes_nothing`
- `test_missing_required_fields_write_nothing`
- `test_wrong_title_type_writes_nothing`
- `test_blank_or_whitespace_only_title_writes_nothing`
- `test_blank_or_whitespace_only_price_writes_nothing`
- `test_json_numeric_price_writes_nothing`
- `test_unknown_top_level_keys_write_nothing`
- `test_invalid_optional_field_types_write_nothing`
- `test_blank_supplied_external_id_writes_nothing`
- `test_external_id_longer_than_model_field_writes_nothing`

These freeze `CommandError`, nonzero return code, complete validation before
write, and zero rows for every structural failure class.

### RawListing fidelity

- `test_capture_writes_one_faithful_rawlisting`
- `test_absent_optional_fields_use_honest_empty_or_null_values`
- `test_repeated_capture_without_external_id_creates_distinct_observations`
- `test_null_rate_limit_completes_without_throttling`

These freeze exact text/URL/identifier/payload retention, ingestion-time
`fetched_at`, NULL `occurred_at`, honest optional defaults, no synthetic
identifier, repeated-observation semantics, and NULL-rate-limit behavior.

### Decimal-only money parsing

- `test_approved_price_grammar_parses_to_exact_decimal`
- `test_other_nonblank_price_text_succeeds_with_null_decimal`

Their parameter cases cover plain and grouped integers, one/two decimal
places, parsing-only surrounding whitespace, a float-precision sentinel,
currency markers, ranges, scientific notation, negative values, excessive
precision, overflow, malformed grouping, NaN, Infinity, and prose.

### Privacy

- `test_seller_column_and_payload_share_the_same_pseudonym`
- `test_plaintext_seller_appears_nowhere_in_persisted_rawlisting`
- `test_blank_seller_is_treated_as_absent`
- `test_context_is_rejected_before_write`
- `test_unknown_pii_bearing_key_is_rejected_before_write`

These freeze identical column/payload tokens, absence of plaintext seller,
blank-seller omission, the closed schema, and rejection of the input shapes
that would bypass the existing shallow redactor.

### Phase and integrity boundaries

- `test_capture_writes_no_downstream_or_swap_rows`
- `test_success_does_not_update_last_successful_fetch`
- `test_structural_failure_does_not_update_last_successful_fetch`
- `test_rawlisting_created_by_command_remains_database_immutable`

These freeze RawListing-only behavior, TASK_008 ownership of run bookkeeping,
and continued PostgreSQL trigger immutability for rows written by TASK_006.

## 7. Explicit non-goals

TASK_006 does not include or scaffold:

- model changes or migrations;
- changes to TASK_007 or its admin trade workflow;
- admin, form, or template changes;
- cron or scheduler deployment;
- updates to `last_successful_fetch`;
- TASK_008 run summaries or rejection reports;
- SKU/SkuAlias creation, entity resolution, or title normalization;
- condition or location inference;
- price plausibility judgments;
- `Listing`, `PricePoint`, `DealFlag`, `Outcome`, or `Swap` writes;
- arbitrary `context`, `occurred_at`, or `location` support;
- third-party ingestion, scraping, eBay, TipidPC, or retailer prices;
- dynamic importer/plugin discovery;
- privacy-helper redesign;
- new dependencies.

## 8. Implementation and review requirements

- Explicit over clever; every non-obvious decision receives a one-line reason.
- No test-only branch or behavior may detect pytest or frozen fixtures.
- No frozen test may be changed, skipped, xfailed, weakened, or replaced.
- Money never passes through `float`, including JSON decoding and intermediate
  parser values.
- RawListing remains immutable at application and PostgreSQL levels.
- All unrelated working-tree changes stay unstaged and untouched.
- Static review owns scope, security logic, test integrity, and contradictions.
- Runtime validation owns actual command execution, PostgreSQL behavior, and
  exact staged-snapshot guarantees.

## 9. Validation

After implementation, from the repository root:

```text
docker compose exec web pytest -v ingestion/tests/test_task_006_manual_capture.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
git diff --check
git diff --cached --check
```

Additionally validate the real shell command with stdin for a successful
capture and a structural failure, confirming success/nonzero exits and zero
failure writes. Verify on PostgreSQL 16 that the resulting row remains
immutable, the plaintext seller is absent, no float/FloatField money path was
introduced, `last_successful_fetch` is unchanged, and no migration exists.

Before final review, validate the exact staged snapshot and confirm the staged
set contains only TASK_006 artifacts and implementation files.
