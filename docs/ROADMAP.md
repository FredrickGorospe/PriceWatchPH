## Architecture

Scheduler (cron, own container)
↓ calls management commands
Ingestion — ebay_client, tipidpc_scraper, manual_capture, retailer_prices
↓ writes RawListing (immutable)
Normalisation + entity resolution — title → canonical SKU + condition
↓ writes Listing (FK to Sku)
Pricing engine — rolling baseline per (sku, condition) → residual → deal score
↓
Django app — dashboard, SKU pages, deal feed, review queue, outcome tracker

Data model:

- Sku — canonical component. brand, model, variant, category
  (gpu/cpu/ram/mobo/monitor/peripheral), launch_msrp, launch_date
- SkuAlias — messy strings mapping to a SKU. Direct descendant of the PulsoPH
  BrandAlias work
- Source — name, base URL, terms notes, rate limit, last successful fetch
- RawListing — immutable. raw_title, raw_price, url, seller, fetched_at, source
- Listing — resolved. FK to RawListing and Sku, Decimal price, condition, location,
  resolution_confidence, resolution_method
- PricePoint — daily aggregate per (sku, condition): median, p25, p75, n_listings
- DealFlag — listing, score, baseline used, reason, flagged_at
- Outcome — acted or not, bought_at, sold_at, days_held, realised_margin. Also log
  skipped flags and why. This table is what turns the project from a dashboard into
  evidence.

## Phases

| # | Phase | Sessions |
|---|---|---|
| 0 | Repo, CLAUDE.md, SOURCES.md, schema, Postgres in Compose | 2 |
| 1 | eBay client + RawListing ingestion + management command | 3–4 |
| 2 | Deploy ingestion somewhere always-on | 2–3 |
| 3 | Normalisation + entity resolution v1 | 4–6 |
| 4 | Manual review queue (Django admin) | 2 |
| 5 | Baseline pricing + deal scoring | 3–4 |
| 6 | React/TS frontend replacing admin surface | 3–4 |
| 7 | Alerts (Telegram is easier than email deliverability) | 1–2 |
| 8 | Outcome tracking + realised margin reporting | 2 |
| 9 | Production Docker, Caddy, HTTPS, backups | 3–4 |
| 10 | Test suite, README, written case study | 3–4 |
| 11 | Entity resolution v2 + model upgrade — optional | 4–6 |

Core total ~28–36 sessions excluding phase 11.

Risks: phase 3 is most likely to overrun, and that's a fine place to overspend since
it's the most interesting part. Phase 9 — first real deployment — always takes longer
than anyone expects; budget the full four sessions and don't schedule it before a
deadline.
