# PriceWatchPH

PriceWatchPH is a PostgreSQL-backed market-intelligence platform for
secondhand PC hardware in the Philippines. It turns raw listing observations
into canonical product records, historical price evidence, reviewable entity
resolution, persisted deal signals, and tracked outcomes through an auditable
data pipeline.

This is an independent portfolio project with a production-oriented runtime.
It is not currently offered as a public live service.

## What it does

- Preserves source observations as immutable raw evidence.
- Resolves listing titles against a canonical SKU catalogue with deterministic,
  exact-alias matching.
- Sends uncertain results to a human review workflow instead of forcing a match.
- Builds sealed daily price evidence and persists unusually low asking prices
  as deal flags.
- Tracks purchase, sale, skip, and correction outcomes with an audit trail.
- Runs downstream processing on an operator-supplied cron schedule.
- Delivers opt-in Telegram alerts when externally configured.
- Creates PostgreSQL backups and exercises an isolated verified restore drill.

## Why I built it

Secondhand hardware pricing is noisy. Titles are inconsistent, products with
similar names are easy to confuse, and a low asking price is not meaningful
without trustworthy historical context. PriceWatchPH explores how conservative
entity resolution, immutable evidence, and reviewable decisions can turn those
observations into useful market intelligence without hiding uncertainty.

## Architecture and data flow

```text
Source -> RawListing -> Listing -> SKU -> PricePoint -> DealFlag
                                                   |-> Outcome
                                                   |-> AlertDelivery
```

`RawListing` is the immutable evidence boundary. `Listing`, `PricePoint`,
`DealFlag`, `Outcome`, and `AlertDelivery` are derived or operational records
that retain links back to the evidence and decisions that produced them.

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Django 5.2, Django REST Framework |
| Data | PostgreSQL 16 |
| Frontend | React 19, TypeScript, Vite |
| Runtime | Docker Compose, Gunicorn, WhiteNoise, cron |
| Validation | pytest-django, Vitest, Oxlint |

## Engineering highlights

- PostgreSQL-only persistence, including database-enforced immutability for
  `RawListing`, `PricePoint`, and `DealFlag` evidence.
- `Decimal` monetary values throughout the application and pricing pipeline.
- Keyed seller pseudonymization before immutable observations are stored.
- Conservative exact-alias resolution with no fuzzy or probabilistic fallback.
- Human-confirmed resolutions are protected from automated overwrite.
- Manila-calendar pricing semantics over UTC-stored timestamps.
- A persistent scheduler lock prevents overlapping pipeline runs.
- Audited outcome transitions and opt-in, at-most-once Telegram delivery.
- PostgreSQL custom-format backups plus an isolated restore-verification drill.

## Benchmark results

PriceWatchPH was exercised with a deterministic, controlled synthetic workload
from 10,000 to 1,000,000 observations. These are marketplace-style test records,
not real Philippine listings and not evidence of production accuracy.

| Workload | Successful repetitions | Production processing | Throughput |
|---:|---:|---:|---:|
| 10K | 3 | 20.24 s median | 494 obs/s median |
| 100K | 1 | 202.14 s | 495 obs/s |
| 500K | 1 | 877.91 s | 570 obs/s |
| 1M | 1 | 1,931.19 s | 518 obs/s |

At 1M observations, the resolver produced 250,000 correct automatic matches,
zero incorrect automatic matches, and zero unsafe forced matches. Its automatic
resolution precision was 100%, while coverage over the 750,000 intentionally
resolvable observations was 33.33%. The remaining cases were conservatively
sent for review. This is not a claim of 100% overall matching accuracy.

The largest clean run sustained approximately 518 observations per second
through the existing production `resolve_listings` and `price_listings` command
boundaries. See [Benchmark results and methodology](docs/BENCHMARKS.md) for
timing definitions, machine context, quality metrics, failures discovered, and
links to the machine-readable manifests.

## Quick start

This evaluation path uses a fresh, disposable database and leaves the scheduler
and Telegram alerts off.

```sh
git clone https://github.com/FredrickGorospe/PriceWatchPH.git
cd PriceWatchPH
cp .env.example .env
# Replace POSTGRES_PASSWORD, DJANGO_SECRET_KEY, and DJANGO_SELLER_PSEUDONYM_KEY.
docker compose up -d --build db migrate web
docker compose exec web python manage.py createsuperuser
```

Sign in at <http://localhost:8000/auth/login/>. To exercise the complete UI and
pipeline, set `PRICEWATCHPH_ENABLE_DEMO_DATA=1` in `.env`, then run:

```sh
docker compose up -d --force-recreate web
docker compose exec web python manage.py bootstrap_demo_data
```

Open <http://localhost:8000/deals>. Set `PRICEWATCHPH_ENABLE_DEMO_DATA=0` and
recreate `web` when finished. The demo is deterministic fictional data, not
marketplace evidence. For configuration rules, UI routes, ingestion limits,
scheduler operation, alerts, and backup safety, use the
[User and Operator Guide](docs/USER_GUIDE.md).

## Current limitations

- The repository has no public live deployment or included HTTPS/TLS ingress.
- Automated marketplace acquisition and importers are not implemented.
- The approved normal manual input paths do not independently provide all
  metadata required to create fresh pricing-eligible asking observations.
- Exact-alias resolution is intentionally conservative and sends unmatched
  titles to review.
- Telegram delivery requires external bot, chat, activation, and public-origin
  configuration.
- The repository verifies isolated scratch restores but does not implement a
  procedure for restoring a production backup into the active database.
- Facebook Marketplace is permanently excluded from source scope.

## Documentation

- [User and Operator Guide](docs/USER_GUIDE.md)
- [Benchmark results and methodology](docs/BENCHMARKS.md)
- [Source governance](SOURCES.md)

## Validation

Backend checks run against PostgreSQL. SQLite is not supported, including for
tests.

```sh
docker compose exec web pytest -v
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations --check --dry-run
cd frontend && npm ci && npm run check
```

## Project status

PriceWatchPH is an independent portfolio project with a production-oriented
Docker runtime, reproducible benchmark evidence, and documented operating
boundaries. A real public deployment, TLS ingress, automated source
acquisition, and a production recovery procedure remain outside the current
repository state.
