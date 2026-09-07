# PriceWatchPH benchmarks

## Purpose and scope

The BENCH_003 pipeline benchmark measures how the existing PriceWatchPH
production resolution and pricing commands behave as a deterministic workload
grows. It also measures resolver quality, PostgreSQL storage, and the benchmark
harness itself without changing production resolver or pricing behavior.

All observations, catalogue entries, URLs, sellers, prices, and labels in this
benchmark are controlled synthetic test data. They resemble marketplace input
shapes but are not real Philippine listings, production traffic, or evidence of
real-world accuracy.

## Results

`Production processing` is exactly:

```text
resolve_listings duration + price_listings duration
```

Throughput is observation count divided by that production-processing time. It
does not include synthetic generation, benchmark-only raw loading, quality
extraction, API requests, backup, or restore.

| Workload | Repetitions | Generation | Raw load | Resolve | Price | Production processing | Throughput | Quality extraction |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10K | 3 | 0.782 s median | 0.607 s median | 16.814 s median | 3.447 s median | 20.243 s median | 494.003 obs/s median | 0.477 s median |
| 100K | 1 | 7.976 s | 6.440 s | 170.113 s | 32.030 s | 202.143 s | 494.700 obs/s | 7.109 s |
| 500K | 1 | 39.921 s | 37.612 s | 732.081 s | 145.826 s | 877.906 s | 569.537 obs/s | 100.352 s |
| 1M | 1 | 72.953 s | 65.338 s | 1,613.655 s | 317.531 s | 1,931.186 s | 517.817 obs/s | 49.837 s |

The 10K production-processing range was 19.486 to 24.159 seconds, and its
throughput range was 413.922 to 513.177 observations per second. The 100K,
500K, and 1M rows each represent one clean measured repetition, not medians.
No performance trend beyond these controlled measurements is claimed.

## Resolution quality

Every scale used equal 25% A/B/C/D difficulty classes. A was compatible with
the frozen exact-alias resolver; B and C remained uniquely labelled but
introduced lexical changes not present in the alias catalogue; D was
intentionally ambiguous. Labels remained outside production-visible fields.

The successful runs produced the same aggregate rates. At 1M observations:

| Measure | Count or rate |
|---|---:|
| Synthetic observations | 1,000,000 |
| Labelled resolvable observations (A/B/C) | 750,000 |
| Intentionally ambiguous observations (D) | 250,000 |
| Correct automatic resolutions | 250,000 |
| Incorrect automatic resolutions | 0 |
| Review-required observations | 750,000 |
| Unsafe forced resolutions | 0 |
| Automatic-resolution precision | 100.000000% |
| Correct-resolution coverage over A/B/C | 33.333300% |
| Review-required rate | 75.000000% |
| Correct abstention rate for D | 100.000000% |

The 100% figure is precision among automatic matches, not overall matching
accuracy. Conservative abstention is an intentional property of the production
resolver.

## Controlled environment

The headline manifests record the same local machine and runtime family:

- Apple M2, 8 logical CPUs, 8 GiB host memory;
- macOS 26.3.1 on arm64;
- Docker memory available to the benchmark: 4.30 GiB;
- Python 3.12.13;
- PostgreSQL 16.14 using `postgres:16.14-bookworm`;
- generator version 1.0.0 and master seed `20260829`; and
- 120 fictional benchmark-only SKUs with 240 frozen aliases.

Each scale used a fresh PostgreSQL database and a quiescent Docker runtime. The
runner enforced Docker-memory, free-disk, timeout, and Manila-midnight safety
preflights. The 500K and 1M runs required enough remaining time before the next
Manila midnight to cover their full frozen timeout.

## Methodology summary

1. Install the frozen synthetic catalogue.
2. Generate deterministic production records and a separate label sidecar.
3. Load only production-visible fields into immutable `RawListing` rows through
   the benchmark fixture boundary.
4. Run the unchanged production commands `resolve_listings` and
   `price_listings`.
5. Correlate persisted outputs with external labels and aggregate
   `resolution_quality.v1` metrics.
6. Capture initial, pre-processing, and final PostgreSQL row counts and sizes.
7. Validate and write the machine-readable manifest.

`benchmark_raw_load` is fixture preparation because the production application
has no bulk importer. API, backup, and restore measurement were outside the
owner-approved BENCH_003 execution scope.

The frozen contracts are available in
[BENCH_001](../tasks/BENCH_001_PORTFOLIO_BENCHMARK_CONTRACT.md) and
[BENCH_002](../tasks/BENCH_002_SYNTHETIC_BENCHMARK_DATASET.md).

## Failures found during scaling

The benchmark retained failures instead of selecting only favorable runs:

- The first 500K attempt crossed a Manila calendar-day boundary during its long
  resolve stage. Pricing consequently evaluated 156,957 of 500,000 listings and
  produced no price points. That run is retained as diagnostic evidence and is
  excluded from the headline table. The runner now rejects a run before
  generation unless the time remaining before Manila midnight is strictly
  greater than the full scale timeout.
- The first 1M attempt completed generation, loading, resolution, and pricing,
  then its benchmark-only quality extractor was OOM-killed with exit code 137.
  Because stage timings were lost, no successful manifest was fabricated. The
  small [failure diagnostic](../benchmark-results/bench003-1m-repetition-1-measured/failure-diagnostic.json)
  remains with explicit null timings.
- Quality extraction was changed to bounded-memory streaming with PostgreSQL
  temporary-table correlation. A later accidental quadratic anti-join was
  removed by indexing and analyzing both temporary tables before correlation.
  The final clean 1M extraction completed in 49.837 seconds without changing
  production behavior or metric definitions.

## Machine-readable evidence

- 10K: [repetition 1](../benchmark-results/bench003-repetition-1-measured/manifest.json),
  [repetition 2](../benchmark-results/bench003-repetition-2-measured/manifest.json),
  [repetition 3](../benchmark-results/bench003-repetition-3-measured/manifest.json)
- 100K: [repetition 1](../benchmark-results/bench003-100k-repetition-1-measured/manifest.json)
- 500K: [corrected repetition 1](../benchmark-results/bench003-500k-repetition-1-corrected-measured/manifest.json)
- 500K rejected diagnostic run: [manifest](../benchmark-results/bench003-500k-repetition-1-measured/manifest.json)
- 1M: [final clean repetition 1](../benchmark-results/bench003-1m-repetition-1-measured/manifest.json)
- Initial 10K preflight failure: [not-attempted manifest](../benchmark-results/bench003-repetition-1/manifest.json)

Only small manifests and diagnostics are committed. Generated NDJSON datasets,
label sidecars, PostgreSQL databases, dumps, and verbose logs are not public
repository artifacts.
