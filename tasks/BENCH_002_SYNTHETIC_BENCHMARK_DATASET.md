# BENCH_002: Synthetic Benchmark Dataset and Quality Harness

## Status

HARDEN candidate for owner review. No BENCH_002 implementation exists in this
task state. This contract and its acceptance test must be owner approved and
frozen before implementation starts.

BENCH_001 is authoritative and immutable. Its contract and acceptance test must
remain byte-exact throughout BENCH_002.

## Release boundary

BENCH_002 measures the release whose authoritative ancestor is
`ab0646e9fcb4c3c5d1f567a46848a3a98dbda9a5`. Benchmark support code must remain
outside production runtime modules. No production runtime file may change.

If the benchmark cannot operate through the release's existing models,
commands, and public behavior, stop and report the production limitation. Do
not repair or adapt production behavior in BENCH_002.

This task creates deterministic benchmark-only catalogue evidence, raw listing
evidence, external labels, semantic-audit material, and resolution metrics. No measured portfolio benchmark run is part of BENCH_002. The 10,000 observation
headline dataset must not be generated, and neither may the 100,000, 500,000,
or 1,000,000 observation datasets.

API load benchmarking, scaled backup/restore, public or external data,
production distribution claims, and adversarial exact duplicates are out of
scope. No backup, restore, or destructive cleanup is authorized.

## Future implementation paths

Implementation is limited to these benchmark-only paths unless an owner-approved
test correction requires another benchmark-only path:

- `benchmarks/__init__.py`
- `benchmarks/catalogue.py`
- `benchmarks/fixtures/catalogue_v1.json`
- `benchmarks/generator.py`
- `benchmarks/audit.py`
- `benchmarks/loader.py`
- `benchmarks/metrics.py`

The frozen acceptance test is
`tests/test_bench_002_synthetic_benchmark_dataset.py`. Generated label sidecars
and audit exports are run artifacts, not committed fixtures.

## Catalogue fixture

`benchmarks/fixtures/catalogue_v1.json` is UTF-8 JSON with a final newline. The
exact bytes and SHA-256 become a pre-measurement owner review gate. Exact SKU
rows, names, aliases, and their semantic suitability must be approved before
any measured portfolio benchmark run.

The top-level object has exactly these fields:

| Field | Type | Frozen value |
| --- | --- | --- |
| `schema_version` | string | `benchmark_catalogue.v1` |
| `fixture_version` | string | `1.0.0` |
| `catalogue_kind` | string | `synthetic_benchmark_only` |
| `sku_count` | integer | `120` |
| `category_counts` | object | exact counts below |
| `alias_policy` | object | exact policy below |
| `skus` | array | exactly 120 SKU objects |

`category_counts` is exactly:

```json
{
  "gpu": 30,
  "cpu": 25,
  "ram": 20,
  "mobo": 20,
  "monitor": 15,
  "peripheral": 10
}
```

Each SKU object has exactly these fields:

| Field | Type | Constraint |
| --- | --- | --- |
| `natural_key` | string | globally unique `bench_<category>_<three digits>` |
| `category` | string | one release `Sku` category from the frozen counts |
| `brand` | string | fictional, non-empty |
| `model` | string | fictional, non-empty |
| `variant` | string | fictional or empty |
| `launch_msrp` | string | positive Decimal text with exactly two fractional digits |
| `launch_date` | string | ISO `YYYY-MM-DD` date |
| `family_token` | string | fictional shared family identifier |
| `ambiguity_group` | string | stable group identifier |
| `aliases` | array | exactly two alias objects |

The tuple `(brand, model, variant)` is globally unique. Each category contains
SKUs both with and without variants and at least one numeric model. Real vendor
names and copied vendor catalogues are forbidden. The fixture must preserve
plausible structural variation without claiming to model Philippine marketplace
frequency or commercial reality.

There are exactly 24 ambiguity groups of five SKUs. Every member of a group has
the same category and `family_token`. Variant and model differentiators make
unique A/B/C titles and intentionally non-unique D titles possible.

### Alias policy

`alias_policy` is exactly:

```json
{
  "aliases_per_sku": 2,
  "source_of_truth": "seed",
  "generated_evaluation_titles_may_be_added": false
}
```

Each alias object is exactly:

```json
{
  "alias_text": "string",
  "source_of_truth": "seed"
}
```

The first alias is the space-joined non-empty `brand`, `model`, and `variant`.
The second is a fixture-authored, human-reviewable structural alternate. It is
not derived from generated evaluation titles and contains no marketplace-noise
phrases. All 240 aliases must be globally unique after the production
`normalise_title` function. Both aliases are installed as release `SkuAlias`
rows with `source_of_truth="seed"` before title generation. Generation cannot
write or mutate aliases.

## Catalogue interface

`benchmarks.catalogue.load_catalogue(path)` parses and validates the exact
fixture and returns an immutable catalogue value with:

- `skus`: ordered immutable SKU values exposing every fixture SKU field;
- `sha256`: lowercase SHA-256 of the exact fixture bytes.

Each loaded alias exposes `alias_text` and `source_of_truth` attributes.
`benchmarks.catalogue.install_catalogue(catalogue)` inserts the 120 release
`Sku` rows and 240 `SkuAlias` rows without changing release models or resolver
code. Installation fails on incompatible pre-existing natural identities; it
does not silently rewrite catalogue data.

## Generator identity and named streams

The constants are exact:

```text
GENERATOR_VERSION = "1.0.0"
MASTER_SEED = 20260829
SELLER_COHORT_SIZE = 4096
```

Generation identity consists of generator version, master seed, exact catalogue
SHA-256, explicit Manila as-of day, zero-based observation index, and named
component stream. A component value is derived independently with SHA-256 over
an unambiguous length-delimited UTF-8 framing of those values plus the component
name. A component must not consume mutable global random state. Adding a new
component therefore cannot shift existing fields.

`iter_observations(count, catalogue, as_of_day)` returns an iterator in ascending
observation-index order. With identical identity inputs it is byte-for-byte and
value-for-value deterministic. Its first N values equal the first N values of
every larger run with the same inputs. Changing the as-of day changes the
generated output.

`seller_handle(index)` accepts indices `0..4095` and returns exactly
`benchmark_seller_<four decimal digits>`. Generator selection is restricted to
that exact 4,096-handle cohort. A handle contains no label information.

## Generated observation schema

Each iterator value has two immutable attributes: `production` and `label`.
Only `production` may be passed to the raw loader or production code.

`production` is a dataclass with exactly these fields:

| Field | Type | Rule |
| --- | --- | --- |
| `raw_title` | string | generated marketplace title only |
| `raw_price_text` | string | source-style text representing `raw_price` |
| `raw_price` | Decimal | never float |
| `url` | string | synthetic `.invalid` URL with no label value |
| `seller_handle` | string | member of the frozen cohort |
| `fetched_at` | aware datetime | UTC |
| `occurred_at` | aware datetime or null | UTC when present |
| `external_id` | string | synthetic listing identity with no label value |
| `payload` | object | exact payload below |

The production payload is exactly:

```json
{
  "stated_condition": "new | like_new | used | for_parts",
  "stated_price_kind": "asking"
}
```

No field name or value for expected key, candidate keys, difficulty,
transformations, generation digest, observation key, or latent source may occur
in production data.

`label` is an immutable internal value with:

- `observation_index`: zero-based integer;
- `observation_key`: deterministic lowercase 64-hex identity;
- `difficulty`: `A`, `B`, `C`, or `D`;
- `expected_sku_key`: natural key for A/B/C, null for D;
- `candidate_sku_keys`: one-element tuple equal to the expected key for A/B/C,
  or at least two plausible keys for D;
- `transformations`: non-empty ordered tuple of applied transformation names;
- `generation_digest`: deterministic lowercase 64-hex digest.

Any latent SKU chosen to construct a D title is generation internals only. It
is neither an expected answer nor production data.

## Difficulty construction

Difficulty is assigned by observation index, not by production resolver output.
Indices cycle A, B, C, D in that order. Counts are therefore exactly 25 percent
at every frozen scale point, all of which are divisible by four.

- A uses an exact frozen alias or only case, punctuation, and whitespace changes
  that the release normalisation treats equivalently.
- B applies modest realistic lexical changes while retaining a single supported
  fixture identity. Examples include modest sales phrasing, a known fixture
  shorthand, or omission of a redundant manufacturer token. The produced title
  is not inserted as an alias.
- C combines substantial but realistic reordering, omission, and noise while
  retaining the family and variant differentiator needed for exactly one
  supported fixture identity. The produced title is not inserted as an alias.
- D retains shared group tokens while omitting the differentiators required to
  choose one member. `candidate_sku_keys` contains all and only the plausible
  members selected by fixture semantics, at least two from one category and
  ambiguity group.

Difficulty and candidates are established from frozen fixture semantics and
named generator rules. Production resolver output is never an input to labels.

## Listing repetition policy

Each consecutive block of ten observations contains nine new listing identities
and one repeated snapshot. Consecutive groups of four ten-observation blocks
form a 40-observation superblock. The designated repeat difficulty rotates A,
B, C, D across those four blocks, based on the zero-based ten-block ordinal
modulo four.

Within each ten-observation block, the named `repeat_position` stream chooses
one eligible observation of the designated difficulty that has an earlier new
identity available in the same block. It does not use one globally fixed repeat
index. A separate named stream chooses an identity introduced earlier in that
block. The repeated snapshot preserves that generated listing's underlying
catalogue context and external identity, uses a distinct `fetched_at`, and may
reflect a later title representation, price, or condition.

Every complete 40-observation superblock therefore contains exactly 36 new
listing identities and four repeated snapshots, with exactly one repeat each in
A, B, C, and D. Because the rule is block-local and uses named deterministic
streams, prefix stability is preserved.

At every frozen scale point this is exactly 90 percent distinct external
identities and 10 percent repeated snapshots. At 10,000, 100,000, 500,000, and
1,000,000 observations, repeat counts are exactly equal across A/B/C/D. For a
tiny correctness prefix that is not a multiple of 40, the maximum difference
between per-class repeat counts is one. No normal-workload pair may share the
exact `(source, external_id, fetched_at)` tuple. Exact duplicates are not
generated in BENCH_002.

## Pricing and time rules

Money construction uses integer minor units converted to `Decimal`; float is
forbidden. Timestamps are generated as aware Manila civil times and converted
to UTC for production fields. Observations are chronological and preserve a
meaningful `occurred_at`/`fetched_at` distinction.

Generation includes uneven SKU frequency, all four conditions, ordinary price
variation, and controlled high and low outliers. These are deterministic test
patterns, not empirical distribution claims.

At the 1,000-record correctness scale, `pricing_support_summary(records)`
returns exactly one exercised `used` SKU per category. Each summary object has:

```text
category: release category string
sku_key: benchmark natural key
condition: "used"
historical_asking_count: integer at least 5
current_candidate_count: integer at least 1
```

The selected SKUs occur in the records. Historical evidence has a Manila date
before the explicit as-of day, and current candidates occur on that day.

## External label sidecar

`write_label_sidecar(stream, records, catalogue_sha256, as_of_day)` writes
newline-delimited UTF-8 JSON. Labels are never written to production database
fields. The first line is exactly this header schema:

```json
{
  "record_type": "header",
  "schema_version": "benchmark_labels.v1",
  "generator_version": "1.0.0",
  "master_seed": 20260829,
  "catalogue_sha256": "<lowercase 64-hex>",
  "as_of_day": "YYYY-MM-DD",
  "observation_count": 0
}
```

`observation_count` is the actual number of following records. Each subsequent
line has exactly these fields:

| Field | Type |
| --- | --- |
| `record_type` | literal `observation` |
| `observation_index` | integer |
| `observation_key` | lowercase 64-hex string |
| `production_fingerprint` | lowercase 64-hex string |
| `difficulty` | `A`, `B`, `C`, or `D` |
| `expected_sku_key` | string or null |
| `candidate_sku_keys` | ordered JSON array of strings |
| `transformations` | ordered JSON array of strings |
| `generation_digest` | lowercase 64-hex string |

`production_fingerprint` is a persisted production-locator fingerprint. It is
reproducible from ordinary release fields after loading and does not cover the
whole generated production record.

`production_locator_fingerprint(source_name, external_id, fetched_at)` first
requires an aware `fetched_at`, converts it to UTC, and formats it with exactly
six fractional digits as `YYYY-MM-DDTHH:MM:SS.ffffffZ`. It then constructs this
exact four-field object:

```json
{
  "external_id": "<production external ID>",
  "fetched_at": "<canonical UTC timestamp>",
  "schema_version": "benchmark_production_locator.v1",
  "source_name": "manual_capture"
}
```

The canonical bytes are UTF-8 JSON produced with lexicographically sorted keys,
no insignificant whitespace, and JSON escaping. In Python terms, the framing
is `json.dumps(locator, ensure_ascii=False, sort_keys=True,
separators=(",", ":"), allow_nan=False).encode("utf-8")`. The fingerprint is
the lowercase hexadecimal SHA-256 of those exact bytes.

For example, `external_id="listing-42"` and
`fetched_at=2026-08-29T01:02:03.456789Z` serialize exactly as:

```text
{"external_id":"listing-42","fetched_at":"2026-08-29T01:02:03.456789Z","schema_version":"benchmark_production_locator.v1","source_name":"manual_capture"}
```

The locator excludes raw seller handle, pseudonymised seller, labels,
difficulty, catalogue natural key, database primary key, and insertion order.
Repeated snapshots have different fingerprints because their canonical
`fetched_at` values differ. No additional sidecar field is required.

The sidecar remains external to all production resolver inputs, including
title, payload, URL, external ID, seller, Source, SkuAlias, and every database
field visible to resolver logic.

## Deterministic semantic audit

`select_semantic_audit(records, catalogue, selector)` uses generator version,
master seed, catalogue SHA-256, the explicit selector, difficulty, and
observation identity as named selection inputs. It ranks the first 1,000
correctness records independently inside each class and returns the lowest 25
per class in stable rank order.

The returned object has exactly:

```text
review_status: "pending_owner_review"
selector: supplied selector
entries: exactly 100 entry objects
```

Each entry has exactly:

```text
generated_title
difficulty
expected_sku_key
candidate_sku_keys
transformations
catalogue_context
```

There are exactly 25 A, 25 B, 25 C, and 25 D entries. Catalogue context contains
only the human-readable catalogue facts needed to judge the expected or
candidate keys. The function cannot emit `passed` or `approved`. Owner review
is a separate pre-measurement gate.

## Benchmark raw loader boundary

`load_raw_observations(observations, chunk_size=1000)` accepts an iterable of
production records only. It has no label parameter. It creates immutable
`RawListing` evidence through existing release models in controlled chunks.

The loader:

1. uses the existing `manual_capture` Source, because the release only treats
   that source's `stated_price_kind="asking"` value as an asking price;
2. maps the exact production fields to `RawListing` without label enrichment;
3. pseudonymises `seller_handle` with the release HMAC-SHA256 pseudonymisation
   function before persistence;
4. preserves Decimal prices, raw text, UTC instants, URL, external identity,
   and the exact two-key payload;
5. creates no `Listing`, `PricePoint`, `DealFlag`, `Sku`, or `SkuAlias` row;
6. never updates a `RawListing` and never changes production ingestion code;
7. rejects invalid chunk sizes, malformed records, or an exact uniqueness
   conflict rather than silently changing identity.

Catalogue installation is a separate explicit step. After loading, the existing
release `resolve_listings` management command must be able to process the raw
rows. Resolution must not add aliases. Pricing is not run by this loader test.

The loader result is an immutable value with exactly these public attributes:

```text
loaded_count: integer
source_name: "manual_capture"
timing_label: "benchmark_raw_load"
```

Its elapsed time may be logged separately, but it must never be described as
production ingestion throughput.

## Real database output extraction

`extract_resolution_outputs(labels, catalogue)` is a benchmark-only function in
`benchmarks.metrics`. It consumes the external sidecar observation objects and
the frozen loaded catalogue, then reads the actual post-`resolve_listings`
database state. It never writes production data.

The benchmark runs in a fresh isolated database. The extractor queries all
`RawListing` rows whose Source is `manual_capture`, follows each row's actual
one-to-one `Listing`, and recomputes the frozen production-locator fingerprint
from persisted `source.name`, `external_id`, and `fetched_at`.

The extractor validates before returning output:

1. label `observation_key` values are unique;
2. label `production_fingerprint` values are unique;
3. persisted production fingerprints are unique;
4. every sidecar fingerprint has exactly one persisted `RawListing -> Listing`;
5. every queried persisted row has exactly one sidecar fingerprint;
6. no expected, duplicate, missing, or extra correlation exists;
7. every non-null persisted `Listing.sku` maps to exactly one frozen catalogue
   natural key by `(brand, model, variant)`.

Any violation raises `ValueError`. This includes an unresolved database row
that has no derived `Listing` after the resolver command. Correlation uses no
database insertion order, RawListing or Listing primary-key/index equivalence,
external ID alone, expected key, candidate key, difficulty, or latent source.
Repeated external IDs remain distinct because `fetched_at` is part of the
fingerprint.

For each sidecar observation, in sidecar order, the extractor returns exactly:

```text
observation_key: copied external observation identity
returned_sku_key: natural key derived from actual Listing.sku, or null
resolution_method: actual persisted Listing.resolution_method
review_required: actual release queue predicate
```

The actual release queue predicate is exactly
`Listing.sku_id is None and Listing.reviewed_unresolved_at is None`, matching
the release review scope. It is not inferred from expected labels or benchmark
difficulty.

## Resolution metric input and output

`evaluate_resolution(labels, outputs)` joins the two inputs one-to-one by
`observation_key` and rejects missing, duplicate, or extra keys.

Each input label is either an exact sidecar observation object or its metric
projection containing `observation_key`, `difficulty`, `expected_sku_key`, and
`candidate_sku_keys`. Other exact sidecar metadata does not affect scoring.
Each production output contains:

```text
observation_key: string
returned_sku_key: string or null
resolution_method: string
review_required: boolean
```

`resolution_method="human_confirmed"` is never automatic. Any other non-null
returned key is automatic. An automatic answer on D is always incorrect and
unsafe, including when it equals a candidate key.

The result has exactly these top-level fields:

```text
schema_version: "resolution_quality.v1"
counts: count object
rates: rate object
by_difficulty: object with exactly A, B, C, D
```

The count object has exactly:

```text
eligible_observation_count
ambiguous_observation_count
automatic_resolution_count_all
automatic_resolution_count_eligible
correct_automatic_resolution_count
incorrect_automatic_resolution_count
correct_abstention_count
unnecessary_abstention_count
unsafe_forced_resolution_count
review_required_count
```

Every rate value has exactly:

```json
{
  "numerator": 0,
  "denominator": 0,
  "value": "N/A"
}
```

Non-zero-denominator `value` is a Decimal-derived string rounded to exactly six
fractional digits. A zero denominator renders `N/A`, never zero. The rate object
has exactly these names and definitions:

| Rate | Numerator | Denominator |
| --- | --- | --- |
| `resolution_coverage` | automatic eligible | eligible |
| `correct_resolution_coverage` | correct automatic | eligible |
| `resolution_precision` | correct automatic | automatic all |
| `correct_abstention_rate` | correct abstention | ambiguous |
| `unnecessary_abstention_rate` | unnecessary abstention | eligible |
| `unsafe_forced_resolution_rate` | unsafe forced | ambiguous |
| `unsafe_resolution_rate` | incorrect automatic | automatic all |
| `review_required_rate` | review required | all observations |

`by_difficulty` maps each literal A/B/C/D to the same exact `counts` and `rates`
shape computed on that subset. Aggregate counts and the hand-verifiable cases
in the frozen acceptance test are authoritative if prose interpretation differs.

## Small-scale correctness validation

Only 8, 40, 100, and 1,000-record datasets may be produced during BENCH_002.
They are correctness fixtures, not portfolio benchmark results. The frozen
acceptance test must prove:

- exact catalogue schema, composition, ambiguity structure, and alias freeze;
- generator identity, determinism, prefix stability, and as-of-day sensitivity;
- exact A/B/C/D proportions where applicable;
- exact 90/10 repetition, one repeat per class in every complete 40-observation
  superblock, at most one per-class imbalance in shorter prefixes, and no exact
  normal-workload duplicate;
- exact seller cohort behavior;
- Decimal money and UTC production timestamps;
- historical and current pricing support for one used SKU per category;
- absence of label leakage;
- exact sidecar, production-locator fingerprint, and semantic-audit schemas;
- metric calculations against hand-verified examples, including D safety,
  human-confirmation exclusion, and zero-denominator `N/A`;
- PostgreSQL loading of raw evidence only, followed by operation of the release
  resolver without alias or pricing side effects;
- one-to-one extraction of real persisted resolver results through external
  locator fingerprints, independent of database insertion order, including
  repeated external identities and real review-queue semantics;
- evaluation of those real extracted outputs against the generated external
  labels without requiring any target quality percentage.

PostgreSQL validation must use a new benchmark-specific isolated Compose project
identity. It must not use a default project identity or any TASK_035 resource.

## Acceptance and stop conditions

The acceptance file collects 15 tests. Before implementation, only the
BENCH_001 byte-integrity test and this specification-boundary test are expected
to pass. The remaining 13 tests must fail because the future catalogue fixture
and benchmark modules do not exist. That red state is intentional and must be
reported, not repaired during HARDEN.

After HARDEN owner approval, implementation must make the frozen tests pass
without editing them. If a frozen test is wrong, stop and report it. Before the
task may be committed, run the complete repository validation required by
`CLAUDE.md` in an isolated benchmark Compose project.

No measured run may begin until the exact catalogue fixture SHA-256 and the
100-title semantic audit receive explicit owner approval.
