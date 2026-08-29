# BENCH_001: PriceWatchPH Portfolio Benchmark Contract

BENCH_001 contract version: `1.0.0`

## 1. Authority and purpose

This contract is based explicitly on PriceWatchPH release:

`ab0646e9fcb4c3c5d1f567a46848a3a98dbda9a5`

The implementation branch is `benchmark/portfolio-evaluation`. Benchmark
implementation and every measured result must remain traceable to the release
above, this contract version, and the eventual benchmark implementation commit.

The purpose is to define a reproducible, evidence-bearing evaluation of the
existing PriceWatchPH system. The benchmark measures scale, command-boundary
processing, resolution quality and abstention, API reads, PostgreSQL storage,
backup and verified restore, and integrity behavior. It is not a product
feature and is not authorization to change production behavior.

BENCH_001 contains only the contract and its frozen static acceptance tests. It
does not implement a generator, loader, benchmark runner, scaled restore runner,
or report renderer. It does not execute a benchmark or establish any measured
result.

## 2. Existing-system boundary

Headline processing measurements must use the existing release entry points:

1. `python manage.py resolve_listings`
2. `python manage.py price_listings`

`resolve_listings` performs normalization, exact-alias resolution, and derived
`Listing` creation or refresh. `price_listings` builds eligible current-day
rolling `PricePoint` evidence and scores listings into `DealFlag` evidence.

The release has no production batch importer. The general CLI importer accepts
one `manual_capture` JSON object. A benchmark-only bulk fixture loader is
therefore a data-preparation boundary, not a production ingestion boundary.

The release resolver is frozen as observed:

- whole-title `SkuAlias.normalised_text` equality after production title
  normalization;
- `exact_alias` with confidence `1.0000` when an alias exists;
- `unresolved` with confidence `0.0000` otherwise;
- no implemented fuzzy, token, semantic, or probabilistic resolver.

High precision with conservative abstention is a valid outcome. Automatic
coverage is not a success gate. No production resolver, threshold, alias,
review, pricing, API, scheduler, model, migration, constraint, or trigger may be
changed to improve a benchmark result.

## 3. Primary portfolio metrics

The likely headline metrics, only after they are measured, are ordered as:

1. largest successfully processed deterministic synthetic dataset;
2. existing-production processing time for the two command boundaries;
3. observations processed per second;
4. scaling behavior across frozen dataset sizes;
5. representative API p50 and p95 latency;
6. API error rate;
7. PostgreSQL database and relation sizes;
8. backup artifact size and backup duration;
9. restore duration;
10. total verified recovery duration; and
11. integrity and adversarial behavior.

Resolution precision, coverage, abstention, unsafe resolution, and review load
remain required quality and safety dimensions. They are not prerequisites for
an impressive manual-review-reduction claim.

Every reported metric must identify its exact workload, scale, repetition,
machine context, timing boundary, and denominator. No target value is frozen.

## 4. Scale contract

The initial scale points are:

- 10,000 observations;
- 100,000 observations;
- 500,000 observations; and
- 1,000,000 observations.

The 1,000,000 run is an attempted scale point, not a promised capability or an
acceptance criterion. A failure, timeout, resource exhaustion, or material
degradation remains visible in the final scaling curve and result manifests.

The harness must accept arbitrary positive observation counts. If 1,000,000
completes cleanly, later 2,000,000 or 5,000,000 runs may extend the same
deterministic sequence without changing generator logic, catalogue composition,
difficulty proportions, commands, or metrics.

Each successful scale point must eventually have at least three independent
fresh-database measured repetitions. Reports show the median and the full range.
All failed repetitions remain listed with their terminal state and available
diagnostics. The best repetition must never be selected as the representative
result.

The frozen headline full-run safety timeouts are:

| Observation count | Timeout |
| ---: | ---: |
| 10,000 | 15 minutes |
| 100,000 | 45 minutes |
| 500,000 | 2 hours |
| 1,000,000 | 4 hours |

Crossing the applicable limit produces terminal state `timed_out`. The timeout
and completed stages must remain visible in every result view. Generator logic,
workload, production command behavior, and difficulty composition must not be
modified merely to turn a timeout into a success. Implementation may expose
the limits as explicit configuration, but the frozen headline values above
must not be modified for the initial benchmark.

## 5. Resource preflight contract

Every run performs an isolated and auditable resource preflight before creating
or loading benchmark data. The minimum free-disk safety floors are:

| Observation count | Minimum free disk |
| ---: | ---: |
| 10,000 | 8 GiB |
| 100,000 | 12 GiB |
| 500,000 | 20 GiB |
| 1,000,000 | 30 GiB |

The Docker runtime must additionally have at least 4 GiB of memory available
for benchmark execution. These are safety floors, not forecasts or claims about
actual consumption.

If any preflight fails, the run must not begin. Its terminal state is
`not_attempted`, and the result records the failed preflight requirement and
observed value. A safety floor must not be lowered silently or on a per-run
basis to obtain a result. Preflight logic remains separate from generation and
processing so its inputs, comparisons, and failure behavior are reviewable.

## 6. Result manifest contract

Every measured result has one small, machine-readable manifest. Required fields
are:

- `release_sha`;
- `contract_version`;
- `implementation_sha`;
- `generator_version`;
- `master_seed`;
- `observation_count`;
- `catalogue_sha256`;
- `catalogue_sku_count`;
- `catalogue_category_distribution`;
- `difficulty_distribution`;
- `manila_as_of_day`;
- `python_version`;
- `postgresql_version`;
- `postgresql_image` including immutable image identity where available;
- `docker_version`;
- `compose_version`;
- `machine_cpu`;
- `machine_memory`;
- `operating_system`;
- `repetition`;
- run start and end instants in UTC;
- per-stage status, duration, processed count, and failure detail;
- pre-processing and final row counts and sizes; and
- artifact schema version.

Machine CPU must disclose the model and logical CPU count. Machine memory must
disclose total installed memory. Operating system must disclose name, version,
and architecture. Performance claims without this context are invalid.

The manifest must distinguish `succeeded`, `failed`, `timed_out`, and
`not_attempted`. Missing values remain null with an explanation. They are never
replaced with zero.

## 7. Result retention contract

The repository may eventually retain and commit only:

- small machine-readable result manifests;
- aggregate CSV or JSON summaries;
- the final Markdown benchmark report; and
- small generated charts used by that report.

The following must remain ignored and must not be committed:

- generated datasets;
- label sidecars;
- PostgreSQL dumps;
- checksum sidecars associated with dump artifacts;
- databases and volumes;
- raw API request logs; and
- verbose temporary benchmark logs.

Large local evidence may remain until owner result review is complete. Later
removal must use benchmark-safe exact-resource or exact-file cleanup with proven
targets. Large generated evidence must not be committed merely to make the
repository appear more substantial.

## 8. Catalogue and label-isolation contract

The synthetic evaluation uses a deterministic benchmark-only catalogue fixture.
It is not the production catalogue and must never be described as production
catalogue data. The release's two fictional demo SKUs may validate the harness
but are insufficient for the portfolio quality benchmark.

The initial synthetic fixture contains exactly 120 fictional benchmark SKUs:

| Category | SKU count |
| --- | ---: |
| GPU | 30 |
| CPU | 25 |
| RAM | 20 |
| Motherboard (`mobo`) | 20 |
| Monitor | 15 |
| Peripheral | 10 |
| **Total** | **120** |

Brands, models, and variants are fictional benchmark identities. This balanced
catalogue design is not actual Philippine market composition. No Kaggle, public, or external catalogue content is used in the synthetic phase.

The fixture must disclose:

- catalogue schema version;
- SKU count;
- category composition;
- alias count and provenance classification;
- stable natural keys;
- source and review status; and
- SHA-256 of the exact fixture bytes.

Every result manifest records the fixture SHA-256 and SKU count. Fixture changes
create a new catalogue version and are not comparable under the old version.

BENCH_002 may create the exact fixture and its implementation tests. The exact
fixture requires owner review before any measured portfolio benchmark run. That
review covers fixture contents, schema and version, category counts, alias
counts, provenance, and SHA-256. Measured execution against an unreviewed fixture is prohibited. Any modification after approval requires a new fixture version and SHA-256, followed by renewed owner review.

Expected labels and generation metadata stay outside production resolver input.
The production database receives only ordinary production fields required to
exercise the pipeline. Expected SKU, ambiguity candidate sets, generation seed,
difficulty, and transformation set must not leak through `payload`, URL,
external ID, seller, title annotations, or another resolver-visible field.

Generated evaluation titles must not be inserted into `SkuAlias` before
inference. The alias fixture is frozen before title generation. Review actions
that could create evaluation aliases are not part of the measured inference
run.

For classes A, B, and C, metadata records one expected benchmark SKU natural
key. For class D, the expected SKU is null, the expected decision is abstention,
and metadata records at least two plausible candidate keys. A latent generator
source SKU is not the correct inference label for an ambiguous title.

Synthetic benchmark catalogue data is distinct from later public or external
data. External listings or catalogues require a separate versioned phase,
license and provenance review, field-leakage assessment, and metrics justified
by the labels actually available. No public or external data is required or
downloaded by BENCH_001.

## 9. Deterministic generation contract

The generator must be streaming and deterministic. Its output is a stable
function of at least generator version, master seed, observation index,
catalogue bytes, and explicit Manila as-of day.

The initial synthetic identity is frozen as:

- `generator_version = "1.0.0"`; and
- `master_seed = 20260829`.

These values remain fixed for the initial synthetic benchmark. A later approved
version must change `generator_version` when generation semantics or output
meaning changes. Every manifest records both values.

Independent random decisions must use named deterministic streams or an
equivalent counter-based derivation. Adding a later decision must not silently
perturb unrelated generated fields. For any shared generator version, seed,
catalogue, and as-of day, the smaller scale dataset must be an exact prefix of
the larger scale dataset.

Normal generation uses exactly 90% unique listing identities and 10% repeated snapshots of existing synthetic listing identities at each frozen scale. Prefix
construction must preserve this split exactly at the four frozen scale points.
Repeated snapshots keep their existing synthetic identity but use distinct fetched instants and remain valid under the release uniqueness schema.

An exact duplicate source/external ID/fetched instant combination is reserved for adversarial tests and must not occur in normal generation. The initial
synthetic seller cohort contains exactly 4,096 sellers. Seller identifiers are
fictional and deterministic, and they pass through the approved benchmark
privacy or pseudonymisation path wherever that path is exercised. The 90/10
split and seller-pool size are workload controls and are not claimed to describe real marketplace behavior.

The generated workload must preserve useful pricing and operational structure:

- uneven SKU frequency;
- multiple categories and conditions;
- unique listings and repeated observations;
- chronological observations;
- occurred/fetched timestamp distinctions;
- deterministic synthetic seller cohorts through the privacy model;
- Decimal prices with ordinary variation and controlled outliers;
- enough pre-as-of asking-price evidence for intentionally exercised
  SKU-condition baselines; and
- current-day candidates for scoring.

All money uses `Decimal`. Timestamps are aware and stored in UTC. Manila is the
explicit aggregation-day boundary. Generator assumptions are disclosed and are
not represented as measured Philippine marketplace distributions.

## 10. Difficulty contract

Every observation belongs to one frozen difficulty class:

- **A, explicit/easy:** an exact alias or a normalization-equivalent title;
- **B, moderately noisy:** modest lexical noise but one intended SKU for a
  competent reviewer;
- **C, hard but resolvable:** substantial realistic noise while one intended
  SKU remains defensible; or
- **D, intentionally ambiguous:** at least two plausible SKUs and no unique
  expected automatic answer.

The frozen distribution is:

- A = 25%;
- B = 25%;
- C = 25%; and
- D = 25%.

This is a balanced evaluation distribution selected for diagnostic comparability. It is not claimed to represent real marketplace prevalence.
Deterministic prefix stability must preserve the 25/25/25/25 proportions as
exactly as practical and exactly at every frozen scale point.

Classes B and C remain uniquely labelled even when the existing exact resolver
abstains. That abstention is safe but unnecessary under the controlled label.
An automatic answer on D is unsafe, even if it happens to match the latent SKU
used to generate the title.

Difficulty proportions are frozen with the generator version before measured
runs. Overall metrics disclose those proportions and never imply that they are
real marketplace prevalence. All quality results include per-class A/B/C/D
metrics so the chosen synthetic mix cannot conceal behavior.

Transformations must remain realistic. They may include case, punctuation,
whitespace, abbreviations, known brand wording, model shorthand, manufacturer
omission, VRAM wording, condition phrases, rush, used/no-issue/complete-box
phrases, unit-only or GPU-only phrases, swap language, irrelevant seller or
price language, repeated tokens, and reordered tokens. Meaningless corruption
introduced solely to lower scores is prohibited.

## 11. Difficulty semantic audit gate

Before any measured portfolio run, the owner reviews a deterministic audit
sample of exactly 100 generated titles:

- 25 from A;
- 25 from B;
- 25 from C; and
- 25 from D.

Sample selection is a stable function of generator version, master seed,
catalogue fixture SHA-256, and an audit-purpose selector. The audit checks:

- A is an exact alias or production-normalization equivalent;
- B remains uniquely attributable to its expected SKU despite modest noise;
- C remains uniquely attributable to its expected SKU despite substantial but
  realistic noise; and
- D genuinely permits at least two plausible benchmark SKUs and has no
  defensible unique automatic answer.

This gate validates generator-label validity, not resolver correctness. The
reviewer does not use resolver output to decide whether a generated label was
well formed.

If a classification defect is found, measured rows must not be relabelled after
observing resolver results. BENCH_002 must correct the generator or difficulty rules before measured execution. If output semantics change, it must increment `generator_version`, regenerate the deterministic 100-title audit sample, and
repeat owner review. Measured portfolio runs must not begin until the audit
passes.

## 12. Pipeline timing contract

The benchmark records separate monotonic wall-clock timings for:

- `generation`;
- `benchmark_raw_load`;
- `resolve_listings`;
- `price_listings`;
- `API workload`;
- `backup`;
- `restore`; and
- `verification`.

Primary existing-production processing time is:

`resolve_listings + price_listings`

Its throughput is observations processed divided by that combined duration,
with the processed-count definition disclosed. Resolution throughput and
pricing throughput may additionally use their own command counts and durations.

`generation` begins before the first generated observation and ends after the
external label stream is durably closed. `benchmark_raw_load` begins before the
first benchmark raw write and ends after the final intended load transaction
commits. Each command timing begins immediately before process invocation and
ends after its exit status and output are captured.

The loader is always named `benchmark_raw_load`. Its rate is benchmark fixture
loading throughput. It must not be labelled production ingestion throughput or
combined invisibly with command processing.

If a smaller corpus is sent through `ingest_manual_capture()` or the
`manual_capture` management-command boundary, that result is reported
separately as genuine manual-capture ingestion performance. It does not replace
the scale loader or inherit the scale loader's claim.

Command-boundary measurements are authoritative for headline processing. A
diagnostic runner may not replace production commands in headline metrics.

## 13. Resolution quality contract

Define the labelled sets:

- E = all uniquely resolvable A, B, and C observations.
- D = all intentionally ambiguous observations with no unique expected SKU.
- N = E union D, all evaluated observations.

An automatic resolution is a non-null SKU returned by an automatic production
method. On the inspected release this is `exact_alias`; the definition remains
explicit so a future implementation cannot silently count human confirmation.

Counts are:

```text
eligible_observation_count = |E|
ambiguous_observation_count = |D|

automatic_resolution_count_all
  = count(automatic result in N)

automatic_resolution_count_eligible
  = count(automatic result in E)

correct_automatic_resolution_count
  = count(automatic result in E where returned SKU = expected SKU)

incorrect_automatic_resolution_count
  = count(
      automatic result in E where returned SKU != expected SKU
      OR automatic result in D
    )

correct_abstention_count
  = count(no automatic result in D)

unnecessary_abstention_count
  = count(no automatic result in E)

unsafe_forced_resolution_count
  = count(automatic result in D)

review_required_count
  = count(production review-queue state in N)
```

Rates are:

```text
resolution_coverage
  = automatic_resolution_count_eligible / |E|

correct_resolution_coverage
  = correct_automatic_resolution_count / |E|

resolution_precision
  = correct_automatic_resolution_count
    / automatic_resolution_count_all

correct_abstention_rate
  = correct_abstention_count / |D|

unnecessary_abstention_rate
  = unnecessary_abstention_count / |E|

unsafe_forced_resolution_rate
  = unsafe_forced_resolution_count / |D|

unsafe_resolution_rate
  = incorrect_automatic_resolution_count
    / automatic_resolution_count_all

review_required_rate
  = review_required_count / |N|
```

The resolution coverage denominator is E. The precision denominator includes
all automatic resolutions, including an unsafe automatic answer on D. An
ambiguous automatic answer is incorrect and unsafe. It cannot increase a
favorable numerator.

Any zero-denominator ratio renders as `N/A`, never zero. Reports include counts,
denominators, and per-class A/B/C/D metrics. F1 is not a primary headline
because it obscures the safety value of abstention and the cost of unsafe forced
resolution.

Synthetic resolution results describe only the controlled labelled synthetic
benchmark. They are not production accuracy or real-world resolution accuracy.

## 14. Scale-run sequence

Every scale repetition follows this order:

1. establish a fresh benchmark PostgreSQL project and database;
2. load the same frozen benchmark catalogue;
3. generate the requested deterministic dataset prefix;
4. load benchmark raw observations through `benchmark_raw_load`;
5. capture pre-processing counts and database sizes;
6. run `resolve_listings`;
7. run `price_listings`;
8. calculate quality metrics externally from isolated labels;
9. run the representative API workload;
10. run the unchanged `pg_backup.sh` backup path;
11. run the benchmark-only scaled verified restore;
12. capture final counts and database sizes;
13. preserve the small result manifest and approved small summaries; and
14. clean up only proven benchmark-specific resources.

The production system has no active/latest-observation abstraction. Reports
must distinguish raw rows stored, observations loaded, raw rows processed by
the resolution command, pricing candidates evaluated, observations eligible
for baseline calculation, and current-day candidates. Database capacity is not
the same as one-command batch capacity.

No failed stage is skipped to manufacture a complete row of results. Later
stages become `not_attempted` with the prior failure recorded.

## 15. API workload contract

Representative release read routes are:

- `GET /api/v1/deal-flags/`;
- `GET /api/v1/skus/<id>/`;
- `GET /api/v1/skus/<sku_id>/price-points/?condition=<condition>`; and
- `GET /api/v1/reviews/listings/`.

Business read routes use the release's session authentication, staff state, and
model permissions. Session establishment is outside measured request timing.
Anonymous authorization behavior is a correctness check, not a business-read
latency headline.

For every representative endpoint and scale, the initial headline matrix is:

- 100 warmup requests, excluded from latency statistics;
- 2,000 measured requests at concurrency 1; and
- 2,000 measured requests at concurrency 8.

Session establishment is outside measured timing. Connection reuse is required
as already specified so repeated connection setup does not replace application
read behavior. Concurrency 32 is not part of the initial headline benchmark. It
may later run as a separately identified saturation experiment, but it cannot
replace or be combined invisibly with the frozen concurrency 1 and 8 results.

Every API result records endpoint/workload identity, dataset scale, warmup
count, measured request count, concurrency, connection-reuse policy, p50, p95,
optional p99, error count, error rate, workload wall time, and requests per
second. Warmup requests are excluded. Endpoint results remain separate; a mixed
workload must disclose fixed weights.

The release Gunicorn configuration and application behavior remain unchanged.
Caching may not be added or enabled solely for the benchmark.

## 16. PostgreSQL scale and size contract

At minimum, each successful measurement captures:

- application table row counts;
- `pg_database_size()`;
- `pg_total_relation_size()` for core Source, Sku, SkuAlias, RawListing,
  Listing, PricePoint, and DealFlag relations;
- index-inclusive relation sizes where distinct;
- PricePoint and DealFlag counts; and
- unresolved and review-required counts.

Size collection points are before existing-production processing and after the
pipeline. Backup artifact size is separate from live database size. All units
are explicit bytes plus a human-readable rendering.

## 17. Backup and restore safety contract

The repository's actual `pg_backup.sh` remains unchanged for benchmark purposes
unless a separate production bug is discovered, approved, and handled outside
benchmark work. The scaled benchmark invokes that exact script and records its
reported artifact identity.

The existing TASK_037 driver creates and restores its own small fixed source
fixture. It cannot honestly establish scaled recovery for the benchmark
database. Later work may add a benchmark-only scaled restore runner, but it must
preserve the TASK_037 safety model and gain frozen tests before execution.

Required properties are:

- exact, internally known source and target identities;
- a dedicated benchmark Compose project distinct from every active/default
  project;
- an empty restore target receiving schema only from the dump;
- the exact PostgreSQL 16 tooling identity used by the release;
- exact dump and SHA-256 sidecar validation before restore;
- `pg_restore --no-owner --no-privileges --exit-on-error`;
- exact resource ownership proof before any cleanup authorization;
- re-proof immediately before cleanup;
- removal only by exact verified container, network, and volume identifiers;
- uncertain cleanup means preserve resources, report failure, and stop; and
- fail closed at every identity, artifact, restore, verification, and cleanup
  boundary.

The runner must never target TASK_035, the old/default active project, an
unrelated Docker volume, or an inherited ambiguous project identity. The
following operations are expressly prohibited:

- `docker compose down -v` against benchmark or shared/default resources;
- wildcard volume deletion;
- `docker system prune` or another prune command; and
- broad label cleanup or guessed-name cleanup.

Before the scaled runner exists, frozen tests must prove resource targeting,
identity rejection, failure behavior, artifact validation, restore flags,
verification sequencing, and fail-closed exact cleanup.

Measured recovery timings are separate:

- backup duration;
- artifact size;
- checksum/structure validation duration where separately measured;
- restore duration from `pg_restore` invocation to successful exit;
- post-restore verification duration; and
- total verified recovery duration from pre-restore artifact validation through
  final successful restored-database verification.

Post-restore verification must compare the restored database to a source
snapshot captured before backup. Row counts alone are insufficient. The scaled
path requires full streamed deterministic content verification for every application table in both source and restored databases.

Every digest uses deterministic ordering and canonical serialization
appropriate to each field type. Every empty application table receives an
explicit deterministic empty-table digest and comparison result. Source counts,
snapshots, and digests are captured before backup and never reconstructed from
the restored database.

Verification additionally covers full migration state, schema, foreign keys,
unique constraints, check constraints, indexes, sequences, required PostgreSQL
triggers, active enforcement behavior, exact Decimal preservation, exact
timestamps, and null-versus-empty JSON distinctions where relevant.

The tiny TASK_037 restore remains a safety regression drill. It must not be
reported as the scaled restore result.

## 18. Adversarial and integrity contract

The adversarial benchmark is qualitative and structural. It does not produce a
vanity rejection percentage. Every case reports:

- case ID;
- input category;
- accepted, rejected, or reviewed disposition;
- row-count delta by affected relation;
- enforcement layer: parser, form, serializer, service, model, database
  constraint, foreign key, unique constraint, or trigger;
- exception, constraint, or trigger identity where applicable; and
- whether invalid evidence contaminated pricing state.

The frozen case categories are:

| Case family | Required behavior under evaluation |
| --- | --- |
| Malformed manual JSON | Application parser rejects without a raw row. |
| Missing, unknown, blank, or wrong-type manual fields | Application validation rejects without a raw row. |
| Malformed or non-representable raw price text | Raw fact may be accepted with `raw_price=NULL`; it must not silently become numeric evidence. |
| Negative or oversized direct numeric price | Existing field/database enforcement rejects it. |
| Missing required database relationship | Existing not-null or foreign-key enforcement rejects it. |
| Exact duplicate source/external ID/fetched instant | Existing uniqueness enforcement rejects it. |
| Same external ID at a distinct fetched instant | Accepted as a distinct observation under current schema. |
| Invalid condition, resolution, price-kind, or trade-side vocabulary | Existing database checks reject invalid derived state. |
| Repeated resolution | One-to-one Listing identity remains; no duplicate derived observation appears. |
| Repeated pricing | Sealed unique PricePoint and DealFlag identities remain. |
| RawListing update/delete through model | Application immutability guard rejects it. |
| RawListing update/delete below the model | PostgreSQL immutability trigger rejects it. |
| PricePoint or DealFlag mutation/delete | Model and PostgreSQL immutability boundaries reject it. |
| Invalid direct relationship | PostgreSQL foreign-key enforcement rejects it. |
| Intentionally ambiguous SKU title | It is measured as safe review routing or unsafe automatic resolution. |
| Human-confirmed listing re-resolution | The existing human-authoritative decision remains unchanged. |

No application or database enforcement may be weakened for benchmark
convenience. A deliberately accepted incomplete raw fact is not classified as
rejected; the report must explain its safe downstream effect.

## 19. Prohibited benchmark gaming

The benchmark must not:

- insert generated evaluation titles as aliases before inference;
- leak expected SKU or ambiguity labels through payload, URL, external ID,
  seller, title decoration, or another production input;
- select only easy exact aliases;
- change difficulty class proportions after inspecting results;
- tune resolver behavior on the evaluation corpus; tuning resolver behavior
  against evaluation results is prohibited;
- disable or bypass constraints or triggers;
- bypass production commands for headline processing metrics; bypassing production commands invalidates the headline result;
- report only the best repetition;
- omit failed scale points or failed repetitions;
- call benchmark bulk fixture loading production ingestion;
- present a tiny TASK_037 restore as a scaled restore;
- use expected labels while resolving or pricing;
- pre-create derived Listing, PricePoint, or DealFlag results;
- combine timings without disclosing boundaries;
- silently reuse a warm or previously processed database as a fresh run; or
- claim controlled synthetic results are real-world production results.

The catalogue, generator, master seed, class distribution, metric code, and
claim language are frozen before measured runs. Any material change increments
a version and invalidates direct comparison unless both versions are reported.

## 20. Portfolio claim language

Approved descriptions include:

- "synthetic marketplace-style listing observations";
- "controlled labelled synthetic benchmark";
- "benchmark catalogue";
- "existing-production processing commands"; and
- "verified PostgreSQL 16 restore of the scaled synthetic benchmark database."

Claims disclose scale, timing boundary, dataset type, machine context, and
whether a scale point succeeded, failed, or degraded.

Unless separately supported by later external evidence, the following are
prohibited or misleading:

- "Philippine marketplace listings" when the rows are synthetic;
- "real listings";
- "production accuracy";
- "real-world resolution accuracy";
- "supports 1M users";
- "production ingestion throughput" for `benchmark_raw_load`; and
- a claim that synthetic catalogue behavior describes the Philippine market.

Resolver quality wording must pair precision with coverage, abstention, unsafe
resolution, and review-required context. Largest-scale wording must retain
failed/degraded scale points in the accompanying results.

## 21. External-data boundary

External or public data is a later, separately approved phase. Selection must
consider license, provenance, stable version/checksum, original non-normalized
titles, hardware/electronics relevance, prices and currency, available labels,
timestamps/repetition, PII, and label leakage.

Valid metrics depend on labels:

- Exact trustworthy SKU labels may support SKU precision, coverage, abstention,
  unsafe resolution, and review-rate metrics.
- Brand/category-only labels do not support SKU precision. They may support
  field-level consistency, throughput, review rate, and a separate blinded
  human-labelled sample.
- Unlabelled data supports realism, throughput, failure behavior, and blinded
  audit only. It does not support resolution precision.

Synthetic data supplies controlled ground truth and deterministic scale.
External data may later test realism and generalization. Neither may be
presented as the other.

## 22. Implementation and review gates

BENCH_002 implementation may begin only after final owner approval of this
contract and its frozen tests. It must start with approved failing acceptance
tests and remain within one approved task at a time.

No unresolved owner decision blocks BENCH_002 implementation. BENCH_002 may
create the exact fictional catalogue fixture, deterministic generator, and
their tests within the frozen totals and policies. Exact fixture contents,
aliases, provenance, schema/version, and digest remain a pre-measurement owner
review gate, not a pre-implementation blocker. The deterministic 100-title
semantic audit is also a pre-measurement gate.

BENCH_002 may make explicit implementation choices that do not alter the frozen
methodology, such as field serialization mechanics and isolated internal module
boundaries. A choice that changes catalogue composition, difficulty meaning or
distribution, generator identity, listing/seller policy, headline API matrix,
timeouts, preflight floors, retention, or verification depth requires a later
owner-approved contract version.

No performance threshold, quality percentage, successful 1,000,000 outcome, or
resume claim is approved by this contract.

## 23. BENCH_001 artifact boundary

Allowed BENCH_001 changed paths are exactly:

- `tasks/BENCH_001_PORTFOLIO_BENCHMARK_CONTRACT.md`; and
- `tests/test_bench_001_portfolio_benchmark_contract.py`.

No production runtime file may change. BENCH_001 creates no benchmark dataset,
catalogue fixture, result, dump, checksum, Docker resource, database, or external
download. It stages, commits, and pushes nothing during the owner-review pass.
