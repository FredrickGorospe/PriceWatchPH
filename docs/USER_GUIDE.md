# PriceWatchPH User and Operator Guide

This guide explains how to run and use the PriceWatchPH application in this
repository. It is grounded in the current Docker Compose, Django, React, and
PostgreSQL implementation.

PriceWatchPH records Philippine PC-component price observations, resolves
listing titles to a canonical SKU catalogue, builds sealed price evidence,
flags unusually low asking prices, and records what happened after a flag.

> **Current deployment status:** the repository contains a production-oriented
> Gunicorn and Docker Compose runtime, but no public HTTPS/TLS ingress. It does
> not claim a live public service. Run it locally or behind an independently
> reviewed trusted reverse proxy. Do not expose port 8000 directly to the
> public internet.

## Quick start for first-time evaluation

Use this path only with a fresh, disposable development database. It starts
the minimum application services and leaves the scheduler and Telegram alerts
off. Do not use a database that contains real observations.

1. Copy the environment template and edit `.env`:

   ```sh
   cp .env.example .env
   ```

   Replace `POSTGRES_PASSWORD`, `DJANGO_SECRET_KEY`, and
   `DJANGO_SELLER_PSEUDONYM_KEY`. Keep `DJANGO_DEBUG=0`,
   `DJANGO_BEHIND_HTTPS_PROXY=0`, `PRICEWATCHPH_ENABLE_ALERTS=0`, and
   `PRICEWATCHPH_ENABLE_DEMO_DATA=0` for the initial start. This evaluation
   path does not start `scheduler`, so do not invent a scheduler cadence. The
   copied nonempty placeholder must be replaced before Section 14's scheduler
   workflow is used.

2. Build and start only PostgreSQL, migrations, and the web application:

   ```sh
   docker compose up -d --build db migrate web
   docker compose ps
   ```

3. Create an administrator, then sign in at
   <http://localhost:8000/auth/login/>:

   ```sh
   docker compose exec web python manage.py createsuperuser
   ```

4. In `.env`, set `PRICEWATCHPH_ENABLE_DEMO_DATA=1`. Recreate only the web
   service so it receives the new setting, then load the deterministic demo:

   ```sh
   docker compose up -d --force-recreate web
   docker compose exec web python manage.py bootstrap_demo_data
   ```

5. Explore the product:

   - <http://localhost:8000/deals> shows persisted demo DealFlags;
   - <http://localhost:8000/reviews> contains the unresolved demo listing;
   - follow a deal's SKU link to see its sealed price history; and
   - select **Track outcome** on a deal to exercise the untracked outcome
     workflow.

6. When evaluation is finished, set `PRICEWATCHPH_ENABLE_DEMO_DATA=0` and
   recreate `web` again:

   ```sh
   docker compose up -d --force-recreate web
   ```

   Disabling the command does not remove the demo rows. That is why this flow
   requires a dedicated disposable database. No destructive cleanup command
   is included here.

> **Why demo data is recommended for evaluation:** the current approved normal
> input paths do not independently provide complete asking-price evidence.
> `manual_capture` accepts title, price, URL, seller, and external ID, but no
> condition, occurrence time, or asking-price classification. Personal trade
> entry can supply a condition and always supplies a trade side, but is
> deliberately classified as realised evidence, not a live asking price. The
> deterministic bootstrap adds explicitly labelled fictional observations with
> controlled condition and
> asking-price metadata, then uses the production resolver and pricing services
> to populate the complete UI. It is synthetic demonstration data, never real
> Philippine marketplace evidence.

## Contents

1. [What is available](#1-what-is-available)
2. [Requirements](#2-requirements)
3. [Initial setup](#3-initial-setup)
4. [Starting and checking the application](#4-starting-and-checking-the-application)
5. [Accounts, authentication, and permissions](#5-accounts-authentication-and-permissions)
6. [How the data flows](#6-how-the-data-flows)
7. [Managing sources and the catalogue](#7-managing-sources-and-the-catalogue)
8. [Ingesting observations](#8-ingesting-observations)
9. [Resolving listings](#9-resolving-listings)
10. [Reviewing unresolved or incorrect listings](#10-reviewing-unresolved-or-incorrect-listings)
11. [Building price evidence and deal flags](#11-building-price-evidence-and-deal-flags)
12. [Using the web interface](#12-using-the-web-interface)
13. [Using the API](#13-using-the-api)
14. [Running the scheduler](#14-running-the-scheduler)
15. [Configuring Telegram alerts](#15-configuring-telegram-alerts)
16. [Backups and verified restore](#16-backups-and-verified-restore)
17. [Stopping and restarting](#17-stopping-and-restarting)
18. [Troubleshooting](#18-troubleshooting)
19. [Development, demo, and benchmark data](#19-development-demo-and-benchmark-data)
20. [Current limitations](#20-current-limitations)
21. [Quick reference](#21-quick-reference)

## 1. What is available

| Capability | Current access | Status |
|---|---|---|
| Canonical SKU and source administration | Django admin | Implemented |
| Paste one listing observation | CLI, JSON on standard input | Implemented for the approved `manual_capture` source |
| Log a personal buy, sale, or swap | Django admin | Implemented for the approved `personal_records` source |
| Automated marketplace collection | None | Not implemented |
| Resolve observations to SKUs | CLI or scheduler | Exact normalized alias matching only |
| Review or correct a resolution | React UI, Django admin, or API | Implemented with staff/model permissions |
| Build daily price evidence and deal flags | CLI or scheduler | Implemented; uses Manila calendar days |
| Inspect deals and price history | React UI, Django admin, or API | Implemented |
| Record purchase, sale, skip, and corrections | React UI or API; limited Django admin adapter | Implemented and audited |
| Telegram alert delivery | CLI or scheduler | Implemented but disabled until explicitly configured |
| Scheduled processing | Docker Compose `scheduler` service | Implemented; cadence is operator-supplied in UTC |
| Database backup | Docker Compose `backup` profile | Implemented |
| Isolated real restore drill | Host script | Implemented for synthetic scratch data |
| Restore a production backup into production | None | No operator procedure is implemented |
| Public HTTPS deployment | None | Pending external deployment configuration |

Only `personal_records` and `manual_capture` are approved and seeded as
operational sources. eBay, TipidPC, Carousell PH, and retailer collection are
still under review and have no importer. Facebook Marketplace is permanently
excluded. See [SOURCES.md](../SOURCES.md).

## 2. Requirements

For the normal containerized application you need:

- Docker Engine with Docker Compose support;
- enough local disk for Docker images and the PostgreSQL volume;
- a browser for the React interface and Django admin; and
- a local copy of this repository.

The images pin Python 3.12.13, PostgreSQL 16.14, and Node 24.18.0. Host Python,
PostgreSQL, and Node are not required for ordinary Docker operation.

For frontend hot-reload development outside the application image, use the
versions declared by `frontend/.nvmrc` and `frontend/package.json`: Node
24.18.x and npm 11.16.x.

## 3. Initial setup

Run all commands from the repository root.

### 3.1 Create local configuration

```sh
cp .env.example .env
```

Edit `.env` before starting. It is ignored by Git and must never be committed.
At minimum, replace the database password, Django secret key, and seller
pseudonym key. Replace the scheduler placeholder before starting the full
default stack; the minimum quick-start path deliberately excludes that service.

| Variable | Purpose and operating rule |
|---|---|
| `POSTGRES_DB` | PostgreSQL database name. The example uses `pricewatch`. |
| `POSTGRES_USER` | PostgreSQL role used by the application. |
| `POSTGRES_PASSWORD` | Database password. Replace `change_me`. |
| `POSTGRES_HOST` | Keep `db` for the supplied Compose topology. |
| `POSTGRES_PORT` | Keep `5432` for the supplied Compose topology. |
| `DJANGO_SECRET_KEY` | Required Django secret. Replace `change_me`. |
| `DJANGO_DEBUG` | Literal `1` enables debug mode; keep `0` for deployment-style use. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated Host header allowlist. Local example: `localhost,127.0.0.1`. |
| `DJANGO_BEHIND_HTTPS_PROXY` | Keep `0` for direct local HTTP. Use `1` only behind a trusted HTTPS-terminating proxy that controls forwarded headers. |
| `DJANGO_DISPLAY_TIME_ZONE` | Display timezone. The example and intended UI timezone are `Asia/Manila`. |
| `DJANGO_SELLER_PSEUDONYM_KEY` | Required secret used to pseudonymize counterparties. Replace `change_me`. Do not rotate it for an existing database: rotation breaks historical linkage. Store a recovery copy separately from database backups. |
| `PRICEWATCHPH_ENABLE_DEMO_DATA` | Literal `1` permits the synthetic demo bootstrap. Keep `0` for normal operation. |
| `PRICEWATCHPH_ENABLE_ALERTS` | Literal `1` enables Telegram delivery. Keep `0` until Section 15 is complete. |
| `PRICEWATCHPH_TELEGRAM_BOT_TOKEN` | Required only when alerts are enabled. |
| `PRICEWATCHPH_TELEGRAM_CHAT_ID` | Required only when alerts are enabled. |
| `PRICEWATCHPH_ALERT_ACTIVATION_AT` | Earliest eligible DealFlag instant, as ISO 8601 with an explicit offset. Required only when alerts are enabled. |
| `PRICEWATCHPH_PUBLIC_BASE_URL` | `http://` or `https://` origin used in alert links, with no path/query/fragment. Required only when alerts are enabled. An HTTPS value requires `DJANGO_BEHIND_HTTPS_PROXY=1`. |
| `PRICEWATCHPH_SCHEDULER_CRON` | Required five-field UTC schedule. `change_me` is deliberately invalid and must be replaced. |

The scheduler accepts a deliberately narrow cron grammar. Minute and hour may
be `*`, one in-range integer, or `*/N`; the final three fields must each be
`*`. Lists, ranges, names, macros, extra fields, and shell syntax are rejected.
For example, `0 * * * *` means once an hour at minute zero, in UTC. Choose a
cadence appropriate for the deployment; the repository does not prescribe
one.

Three Compose-only variables are not in `.env.example`:

| Variable | Default | Use |
|---|---|---|
| `PRICEWATCHPH_BACKUP_DIR` | `./backups` | Host directory mounted into backup and restore-drill containers. |
| `PRICEWATCHPH_RESTORE_SCRATCH_PASSWORD` | Empty while inactive | Supplied automatically by the restore drill. Do not configure it for normal operation. |
| `PRICEWATCHPH_APP_ENV_FILE` | `.env` | Selects the application environment file for `migrate`, `web`, and `scheduler`. |

### 3.2 Build and start

```sh
docker compose build
docker compose up -d
```

The `migrate` service applies migrations once after PostgreSQL becomes
healthy. The `web` and `scheduler` services wait for it to succeed. The image
also builds the React application and collects static files before starting
each application process.

### 3.3 Create the first administrator

```sh
docker compose exec web python manage.py createsuperuser
```

There is no public signup. A superuser is the simplest local operator account.
For narrower production accounts, create staff users and assign only the
model permissions described in Section 5.

## 4. Starting and checking the application

Start or reconcile the configured services:

```sh
docker compose up -d
```

Inspect service state and recent logs:

```sh
docker compose ps
docker compose logs --tail=100 db migrate web scheduler
```

Expected topology:

- `db`: PostgreSQL 16.14 with persistent `postgres_data`;
- `migrate`: a one-shot migration service that should exit successfully;
- `web`: Gunicorn on <http://localhost:8000>;
- `scheduler`: BusyBox cron supervised by Tini, using persistent overlap lock
  storage.

Useful application checks:

```sh
docker compose exec web python manage.py check
docker compose exec web python manage.py showmigrations
```

Open:

- application: <http://localhost:8000/deals>
- application login: <http://localhost:8000/auth/login/>
- Django admin: <http://localhost:8000/admin/>

The root route `/` redirects in the React client to `/deals`.

### Optional frontend hot reload

Keep the Docker backend on port 8000, then run:

```sh
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api`, `/admin`, `/auth`, and
`/static` to `http://localhost:8000`. Override that backend only when needed:

```sh
VITE_DJANGO_PROXY_TARGET=http://localhost:8000 npm run dev
```

## 5. Accounts, authentication, and permissions

PriceWatchPH uses Django-managed accounts, session authentication, and CSRF
protection. Both `/auth/login/` and `/admin/login/` create the same type of
session. There is no signup, token-authentication, or password API.

Application/API access requires an authenticated, active staff account plus
the relevant Django model permissions. A superuser has all permissions.

| Workflow | Required permissions |
|---|---|
| View SKU list/detail | `catalogue.view_sku` |
| View Listing detail | `listings.view_listing` |
| View SKU price history | `catalogue.view_sku`, `pricing.view_pricepoint` |
| View deal feed | `catalogue.view_sku`, `listings.view_listing`, `pricing.view_pricepoint`, `pricing.view_dealflag` |
| View review queue/detail and confirm/mark unresolved | `listings.change_listing` |
| Search SKUs while reviewing | `catalogue.view_sku` |
| Create an alias while confirming | `listings.change_listing`, `catalogue.add_skualias` |
| View outcome state | `pricing.view_dealflag`, `outcomes.view_outcome` |
| Skip or record an initial purchase | `pricing.view_dealflag`, `outcomes.add_outcome` |
| Record a sale or correct purchase/sale evidence | `pricing.view_dealflag`, `outcomes.change_outcome` |
| Log a personal trade | `ingestion.add_rawlisting` |

Assign users/groups through **Admin → Authentication and Authorization**.
Setting `is_staff` without the model permissions is not enough for protected
application operations.

### Login throttling

Five invalid password attempts from one client IP trigger HTTP 429 for 15
minutes across both login routes. A successful login before lockout resets the
IP's count. A valid password is also blocked during an active lockout.

To clear one known client address early:

```sh
docker compose exec web python manage.py axes_reset_ip 192.0.2.10
```

Use the exact address recorded by the application. This command clears only
that throttle state; it does not alter the account or password.

## 6. How the data flows

```text
Source
  -> immutable RawListing
  -> derived Listing
  -> canonical Sku (when resolved)
  -> sealed daily PricePoint evidence
  -> immutable DealFlag (when the score crosses the threshold)
  -> governed Outcome and optional durable AlertDelivery
```

| Record | Meaning | Important behavior |
|---|---|---|
| `Source` | Provenance and governance record | Migrations seed only `personal_records` and `manual_capture`. |
| `RawListing` | Verbatim source observation | Immutable after insertion at both application and PostgreSQL boundaries. Seller data is pseudonymized before write. |
| `Listing` | Current derived interpretation | One per RawListing. May be refreshed by the resolver unless a human has confirmed the SKU. |
| `Sku` | Canonical product identity | Unique brand/model/variant plus category and launch facts. |
| `SkuAlias` | Exact normalized title → SKU evidence | Seeded or human-confirmed. Admin display is read-only; review can create it. |
| `PricePoint` | Daily per-SKU/condition price statistics | Sealed after creation. Built from trusted prior asking-price evidence. |
| `DealFlag` | Persisted underpricing signal | Immutable and tied to the exact PricePoint used. |
| `Outcome` | Skip, purchase, sale, and realized result | Mutated only through governed services/API/admin actions with audit entries. |
| `AlertDelivery` | At-most-once Telegram claim/result | `pending`, `sent`, or `failed`; never resend an existing claim. |

Timestamps are stored in UTC. The UI displays Asia/Manila. PricePoint days and
holding-day calculations use Manila calendar boundaries.

## 7. Managing sources and the catalogue

### Source governance

Migrations seed `personal_records` and `manual_capture`. Inspect their records
under **Admin → Sources → Sources**, but treat [SOURCES.md](../SOURCES.md) as
the governance record. A source appearing in that file as **UNDER REVIEW** is
not approved merely because an administrator can create a database row for
it. Do not create an importer or collect from it without a separately approved
source decision.

`rate_limit` is a positive automated-fetch limit when one exists; null means
there is no automated cadence to describe. Both approved manual sources use
null. A Source referenced by immutable RawListings is protected from ordinary
deletion.

### SKU catalogue

Open **Admin → Catalogue → Skus** to add or edit canonical products. Enter:

- brand;
- model;
- optional variant;
- category (`GPU`, `CPU`, `RAM`, `Motherboard`, `Monitor`, or `Peripheral`);
- non-negative launch MSRP; and
- launch date.

The brand/model/variant tuple is unique. Search for an existing SKU before
creating one. Catalogue deletion is deliberately constrained when listings or
aliases depend on a SKU.

### Aliases

Automatic resolution is exact alias matching after title normalization. The
normal operator path for adding an alias is:

1. open a listing in `/reviews/<listing-id>` or the Listing admin;
2. select the correct existing SKU;
3. select **Create exact alias from the immutable raw title**; and
4. confirm.

Alias creation requires `catalogue.add_skualias`. A normalized title can point
to only one SKU. If it already points elsewhere, the operation stops with an
alias conflict. The alias admin is evidence-only: it does not offer add or
edit forms.

Creating an alias does not automatically rerun resolution for other rows.
Run `resolve_listings` afterward to apply it to other matching observations.

## 8. Ingesting observations

### 8.1 Generic manual capture from JSON

The only CLI importer is `manual_capture`. It reads exactly one UTF-8 JSON
object from standard input.

```sh
printf '%s\n' '{"title":"Fictional RTX 4070 listing","price":"24500.00","url":"https://example.invalid/listings/fictional-001","seller":"Fictional Seller","external_id":"fictional-001"}' \
  | docker compose exec -T web python manage.py ingest manual_capture
```

`title` and `price` are required strings. `url`, `seller`, and `external_id`
are optional strings. Unknown fields are rejected. A price in plain digits
with optional comma grouping and up to two decimal places is stored as a
Decimal; other nonblank price text is preserved with a null parsed price.

The seller value is pseudonymized before it reaches `RawListing.seller` or the
stored payload. Use a fictional value when testing. Do not put secrets or
unneeded personal data in any field.

Current limitation: this input has no condition, occurrence timestamp, or
asking/realized price classification. Its derived Listing is therefore not by
itself eligible for current pricing evidence or deal scoring. Do not describe
this command as a complete marketplace acquisition pipeline.

### 8.2 Log a personal trade in Django admin

Open **Admin → Ingestion → Raw listings**, then select **Log a personal
trade**. The direct route is:

```text
/admin/ingestion/rawlisting/log-personal-trade/
```

Choose **Buy**, **Sell**, or **Swap**. Enter the Manila calendar date,
condition, amounts, and optional counterparty. A buy/sell creates one immutable
RawListing. A swap atomically creates a given and received RawListing plus a
Swap record, so one side cannot be left behind.

Personal trades are classified as realized prices. They are historical trade
evidence, not live asking-price observations. Counterparties are pseudonymized
on write. The raw listing admin intentionally has no generic add, edit, object
detail, or delete operation.

### 8.3 What is not available

There is no scheduled ingestion stage and no eBay, TipidPC, Carousell, retailer,
or other remote collector. The scheduler begins at resolution. Facebook
Marketplace is not a future source for this project.

## 9. Resolving listings

Run resolution after adding observations or aliases:

```sh
docker compose exec web python manage.py resolve_listings
```

The command processes every RawListing in primary-key order and creates or
refreshes its one Listing. It:

- normalizes the raw title;
- looks for one exact `SkuAlias.normalised_text` match;
- records `exact_alias` with confidence `1.0000` and the matched SKU, or
  `unresolved` with confidence `0.0000` and no SKU;
- carries parsed price and trusted row-level metadata into the Listing; and
- uses source occurrence time when present, otherwise fetch time, as the
  observation instant.

The current resolver does not perform fuzzy or machine-learning matching.
Human-confirmed SKU decisions are authoritative and are not overwritten by a
later resolver run. Re-running is otherwise safe and deterministic for the
same persisted inputs and aliases.

## 10. Reviewing unresolved or incorrect listings

### React workflow

1. Open `/reviews`.
2. Select a row to inspect immutable raw evidence and the derived Listing.
3. Search the existing SKU catalogue using at least two characters.
4. Select the correct SKU and confirm it, optionally creating an exact alias.
5. If a genuinely unresolved row has no defensible SKU, select **Mark reviewed
   unresolved**.

The queue contains only rows with no SKU and no prior reviewed-unresolved
timestamp. A resolved deal links back to its review detail so an authorized
operator can correct the assigned SKU.

### Django admin workflow

Open **Admin → Listings → Listings**. The default list is the active review
queue; use the **All listings** review-scope filter to see every Listing. The
change form exposes raw evidence but permits only the governed SKU decision,
optional alias creation, and eligible reviewed-unresolved action.

Human confirmation writes:

- the selected SKU;
- `human_confirmed`;
- confidence `1.0000`;
- a new resolution timestamp; and
- an admin audit log entry.

It does not rewrite the immutable RawListing. Marking a row reviewed unresolved
also writes an audit entry and removes it from the default queue.

## 11. Building price evidence and deal flags

Run the production pricing command for the current Manila day:

```sh
docker compose exec web python manage.py price_listings
```

You may explicitly replay a current or past Manila day:

```sh
docker compose exec web python manage.py price_listings --day 2026-08-15
```

Future days are rejected. For a past day, the command scores against already
persisted PricePoints only; it does not backfill missing PricePoints. Only the
current Manila day builds new PricePoints.

### PricePoint eligibility

For each SKU/condition identity observed on the current Manila day, the
command looks at the preceding 90 Manila calendar days, excluding the current
day. Eligible evidence must have:

- a resolved SKU, price, condition, and observation time;
- `price_kind="asking"`;
- `exact_alias` or `human_confirmed` resolution; and
- confidence exactly `1.0000`.

It stores median, p25, p75, MAD, sample count, window bounds, calculation time,
and contract version. The PricePoint is immutable and a rerun reuses it.

### DealFlag eligibility

A Listing is scored only when it is trusted asking-price evidence and has a
same-day PricePoint. That PricePoint must have at least five observations and
a positive MAD. A DealFlag is created when the asking price is at least three
MAD below the median (`score <= -3.0000`). The flag and baseline reference are
immutable and a Listing can have at most one DealFlag.

The command prints its selected Manila day, number of snapshot identities, and
number of listings evaluated. A successful run can legitimately produce zero
PricePoints or DealFlags when the eligibility rules are not met.

## 12. Using the web interface

| Route | Purpose |
|---|---|
| `/` | Client redirect to `/deals`. |
| `/deals` | Paginated persisted DealFlag feed with price, baseline, score, reason, and evidence. |
| `/deals/<deal-flag-id>/outcome` | Skip, purchase, sale, and correction workflow. |
| `/skus/<sku-id>` | Canonical SKU facts and complete PricePoint history, filterable by condition. |
| `/reviews` | Paginated unresolved review queue. |
| `/reviews/<listing-id>` | Evidence, SKU search/confirmation, alias option, and reviewed-unresolved action. |
| `/auth/login/` | Application session login. |
| `/admin/` | Django administration. |

The deal feed does not calculate signals in the browser. It displays persisted
DealFlags and the sealed PricePoint each flag cites. Times shown in the UI are
converted to Asia/Manila.

### Outcome lifecycle

From a deal card, select **Track outcome**:

- **untracked**: record a purchase or skip with a reason;
- **skipped**: the skip is recorded, but an operator may later record a
  purchase as an audited decision change;
- **open**: purchase exists; record a sale or correct purchase evidence;
- **closed**: purchase and sale exist; correct either evidence record.

Prices are Decimal values with at most two decimal places. Transaction times
are entered in the UI as Manila local time and sent as explicit-offset
instants. A sale cannot precede its purchase. `days_held` uses Manila dates,
and realized margin is generated by PostgreSQL as sale price minus purchase
price.

The Outcome admin changelist is read-only evidence. Its governed untracked
worklist at `/admin/outcomes/outcome/untracked/` can skip a flag or record an
initial purchase. The backend also registers POST-only admin adapters for all
five lifecycle operations, but the current admin has no complete linked form
workflow for tracked outcomes. Use the React page or API for the full operator
workflow instead of constructing admin POST requests manually.

## 13. Using the API

All endpoints are under `/api/v1/` and use the browser's Django session. There
is no token API. Read responses use page-number pagination with 25 rows per
page where applicable. Decimal values are JSON strings and instants are UTC
ISO 8601 values.

### Read endpoints

| Method and path | Purpose |
|---|---|
| `GET /api/v1/skus/` | Paginated SKU list. Optional `q` must contain 2–100 characters after trimming surrounding whitespace. |
| `GET /api/v1/skus/<id>/` | One SKU. |
| `GET /api/v1/skus/<id>/price-points/` | Paginated PricePoint history. Optional `condition`: `new`, `like_new`, `used`, or `for_parts`. |
| `GET /api/v1/listings/<id>/` | One derived Listing. |
| `GET /api/v1/deal-flags/` | DealFlags ordered newest first. |
| `GET /api/v1/reviews/listings/` | Active unresolved review queue. |
| `GET /api/v1/reviews/listings/<id>/` | Review evidence for any Listing. |
| `GET /api/v1/deal-flags/<id>/outcome/` | Current outcome lifecycle and evidence. |

### Mutation endpoints

| Method and path | JSON body |
|---|---|
| `POST /api/v1/reviews/listings/<id>/mark-reviewed-unresolved/` | `{}` |
| `POST /api/v1/reviews/listings/<id>/confirm-sku/` | `{"sku_id": 123, "create_alias": false}` |
| `POST /api/v1/deal-flags/<id>/outcome/skip/` | `{"skip_reason": "Fictional example: listing unavailable"}` |
| `POST /api/v1/deal-flags/<id>/outcome/record-purchase/` | `{"bought_at": "2026-08-15T02:30:00+08:00", "bought_price": "21000.00"}` |
| `POST /api/v1/deal-flags/<id>/outcome/record-sale/` | `{"sold_at": "2026-08-20T11:00:00+08:00", "sold_price": "23500.00"}` |
| `POST /api/v1/deal-flags/<id>/outcome/correct-purchase/` | Same fields as record-purchase. |
| `POST /api/v1/deal-flags/<id>/outcome/correct-sale/` | Same fields as record-sale. |

Unknown JSON fields are rejected. IDs and booleans must be JSON numbers and
booleans respectively. Money must be a JSON string, never a JSON number.
Transaction timestamps must include an explicit UTC offset.

For a non-browser same-origin client, first authenticate with Django and retain
the session cookie. Before an unsafe request, call:

```text
GET /api/v1/session/csrf/
```

Send the returned token as `X-CSRFToken` together with the same session cookie.
The React client performs this flow automatically. Refer to
`api/urls.py`, `api/serializers.py`, and `api/permissions.py` for the exact
public contract.

## 14. Running the scheduler

The Compose `scheduler` service is the production automation mechanism. Its
fixed pipeline is:

```text
resolve_listings -> price_listings -> send_deal_alerts
```

It does not ingest observations, bootstrap data, perform backups, or invoke
arbitrary commands. Its schedule is interpreted in UTC; pricing still selects
the current Manila day independently.

After setting a valid `PRICEWATCHPH_SCHEDULER_CRON`, start it with the rest of
the application:

```sh
docker compose up -d scheduler
docker compose logs --tail=100 scheduler
```

Each run logs the start and completion of every stage. A failed stage returns
nonzero and blocks later stages in that run. The cron daemon stays alive and
the next ordinary cadence may run; there is no immediate retry.

One nonblocking file lock covers the complete pipeline. If another run holds
it, the new invocation does no work, exits successfully, and logs:

```text
Scheduler pipeline skipped: another run is active.
```

The lock lives in the persistent `scheduler_lock` volume so accidental
same-host replicas share it. Do not delete that volume casually.

## 15. Configuring Telegram alerts

Alerts are opt-in and off by default. With
`PRICEWATCHPH_ENABLE_ALERTS=0`, `send_deal_alerts` prints a visible no-op,
requires no Telegram configuration, and exits successfully.

Use this activation sequence:

1. Start and migrate with alerts disabled.
2. Verify the scheduler completes resolution and pricing and logs the disabled
   alert message.
3. Choose a go-live instant and set `PRICEWATCHPH_ALERT_ACTIVATION_AT` with an
   explicit offset, for example `2026-08-15T00:00:00+08:00`.
4. Set the Telegram bot token, chat ID, and public base origin.
5. If the origin is HTTPS, configure a trusted terminating proxy first and set
   `DJANGO_BEHIND_HTTPS_PROXY=1`. The repository does not supply that proxy.
6. Set `PRICEWATCHPH_ENABLE_ALERTS=1`.
7. Recreate the application containers that consume `.env`:

```sh
docker compose up -d --force-recreate web scheduler
docker compose logs --tail=100 scheduler
```

You can invoke the same stage manually:

```sh
docker compose exec web python manage.py send_deal_alerts
```

Only DealFlags at or after the inclusive activation instant and without an
AlertDelivery claim are candidates. The service validates the payload before
claiming, commits one durable claim before network I/O, then records `sent` or
`failed`.

> **At-most-once warning:** an existing `pending`, `sent`, or `failed` claim is
> never retried or resent. A failed delivery makes the command nonzero but the
> next scheduler run will consider only other unclaimed flags. Inspect
> **Admin → Alerts → Alert deliveries** for status and sanitized failure text.

## 16. Backups and verified restore

Database backups are PostgreSQL custom-format dumps. They contain sensitive
application data and are ignored by Git.

### 16.1 Create a backup of the active database

By default, output goes to `./backups`. To use another host directory, set
`PRICEWATCHPH_BACKUP_DIR` for the Compose invocation.

```sh
docker compose --profile backup run --rm backup
```

On success, the command prints one record such as:

```text
BACKUP_ARTIFACT=pricewatchph-20260815T020304Z.dump
```

It writes two mode-0600 files:

```text
pricewatchph-<UTC timestamp>.dump
pricewatchph-<UTC timestamp>.dump.sha256
```

The script first writes `.partial` files, checks the dump with
`pg_restore --list`, calculates SHA-256, publishes the dump and sidecar, then
rechecks the final pair. It refuses to overwrite either final filename.
Nonzero status means the backup is not approved; partial, orphaned, or invalid
files may remain and must not be treated as recoverable evidence.

The repository does not implement retention, off-host copying, or encryption.
A local dump alone is not disaster recovery. Arrange protected off-host
storage, retention, encryption, and monitoring outside this repository. Keep
the original `DJANGO_SELLER_PSEUDONYM_KEY` separately; it is intentionally not
embedded in the dump or backup script.

### 16.2 Run the isolated restore drill

With the active `db` and `web` services running and an application image
available, run:

```sh
./pg_restore_verify.sh
```

This is a real PostgreSQL backup-and-restore drill, but it does **not** restore
the active database or select an existing production dump. It:

- snapshots active application row counts and migration state read-only;
- creates a uniquely named, isolated PostgreSQL 16 scratch project;
- migrates and populates a synthetic source database;
- runs the real `pg_backup.sh` against that scratch database;
- verifies the exact dump/checksum pair;
- restores into a separate empty scratch database;
- checks schema, constraints, representative data, Decimal values,
  pseudonym-key continuity, and active-database non-interference; and
- removes only the exactly verified scratch container, network, and volume.

The generated drill dump and checksum remain in the configured backup
directory. The script deliberately refuses broad cleanup. If it cannot prove
exact scratch ownership, it preserves resources and reports the problem.

> **Restore boundary:** this repository has no command or runbook for replacing
> the active application database with a production dump. Do not improvise
> with `pg_restore --clean`, volume copying, `docker compose down -v`, or direct
> changes to the live database. Production recovery needs a separately
> approved maintenance procedure and verified target identity.

For the complete safety contract, see
[TASK_037](../tasks/TASK_037_BACKUP_AND_VERIFIED_RESTORE.md).

## 17. Stopping and restarting

Stop application containers without removing them:

```sh
docker compose stop
```

Start them again with their existing configuration:

```sh
docker compose up -d
```

After changing `.env` or the image, reconcile/recreate through Compose:

```sh
docker compose up -d --build
```

Restart one service when its configuration has not changed:

```sh
docker compose restart web
```

The PostgreSQL data survives ordinary container restart, `docker compose
stop`, and ordinary `docker compose down` because it resides in the named
`postgres_data` volume. The scheduler lock likewise resides in
`scheduler_lock`.

> **Do not use `docker compose down -v`.** It deletes named volumes, including
> the application database. Do not run Docker prune commands or delete volumes
> by name as routine troubleshooting. Verify ownership and obtain an approved,
> recoverable plan before deleting persistent state.

Prefer `docker compose stop` when the goal is only to pause the application.

## 18. Troubleshooting

### Database unavailable

**Symptom:** `web`, `migrate`, or `scheduler` waits, exits, or logs a PostgreSQL
connection error.

**Likely cause:** `db` is not healthy, credentials differ between Compose and
the application environment, or the persistent database was initialized with
different credentials.

**Safe checks:**

```sh
docker compose ps
docker compose logs --tail=100 db migrate web scheduler
docker compose exec db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

**Safe action:** correct `.env` without deleting the volume, then run `docker
compose up -d`. Do not solve a credential mismatch by deleting
`postgres_data`; that discards the database.

### Migrations pending or failed

**Symptom:** `migrate` exits nonzero, or application queries refer to missing
tables/columns.

**Safe checks:**

```sh
docker compose logs --tail=200 migrate
docker compose exec web python manage.py showmigrations
docker compose exec web python manage.py makemigrations --check --dry-run
```

**Safe action:** fix the reported configuration or migration problem, then run
the existing migration service again:

```sh
docker compose run --rm migrate
docker compose up -d web scheduler
```

Do not create an ad hoc migration merely to silence an operational error.

### Login or authorization problems

**Symptom:** login fails, HTTP 429 appears, or the SPA reports a restricted
account.

**Likely cause:** invalid credentials, the five-attempt IP throttle, inactive
or non-staff account, or missing model permissions.

**Safe checks:** wait 15 minutes after a lockout; verify the user and groups in
Django admin; compare required permissions in Section 5.

**Safe action:** reset one confirmed IP with `axes_reset_ip`, or correct the
account's staff/permission assignments through admin. Do not disable the
authentication backend or throttle.

### Listings remain unresolved

**Symptom:** rows stay in `/reviews` after `resolve_listings`.

**Likely cause:** no exact normalized alias exists. Fuzzy matching is not
implemented.

**Safe check:** inspect the raw and normalized title in review detail and
search the canonical catalogue.

**Safe action:** human-confirm the correct existing SKU and optionally create
an exact alias, then rerun `resolve_listings` for other matching rows. Do not
guess an SKU solely to empty the queue.

### No PricePoints

**Symptom:** `price_listings` succeeds with zero snapshot identities or no new
price evidence.

**Likely cause:** no current-day resolved SKU/condition identity, no eligible
asking-price observations in the preceding 90 days, null condition/price, or
an explicit past-day replay.

**Safe checks:** inspect Listing fields and existing PricePoints in admin;
confirm the command's printed Manila day; review the eligibility list in
Section 11.

**Safe action:** correct upstream catalogue/review/data-entry gaps through the
governed workflows, then run the current-day command. Do not edit sealed
PricePoints or fabricate asking-price classifications.

### No DealFlags

**Symptom:** PricePoints exist but `/deals` is empty.

**Likely cause:** no current worklist Listing has a usable same-day baseline,
the baseline has fewer than five observations or zero MAD, or no score is at
or below `-3.0000`.

**Safe checks:** inspect PricePoint `n_listings`, `mad`, day, and the Listing's
SKU/condition/price kind/resolution confidence in admin.

**Safe action:** no action is required when the evidence simply finds no deal.
Correct only proven upstream data errors; do not tune the threshold or mutate
evidence to produce a flag.

### Scheduler overlap or stage failure

**Symptom:** logs say another run is active, or a stage fails and later stages
do not run.

**Safe check:**

```sh
docker compose logs --tail=200 scheduler
```

**Safe action:** an overlap skip is expected and needs no repair. For a real
stage failure, fix that command's reported cause and allow the next cadence or
invoke the stage manually. Do not remove the lock file or lock volume while a
run may be active.

### Alerts disabled or misconfigured

**Symptom:** logs say alerts are disabled, or the command names a missing or
invalid setting.

**Safe check:** compare `.env` with Section 15 without printing secrets to
logs or chat. Inspect AlertDelivery state in admin.

**Safe action:** keep alerts disabled until all four delivery values and any
HTTPS proxy dependency are valid, then recreate `web` and `scheduler`. Do not
manually delete failed/pending claims to force a resend.

### Backup failure

**Symptom:** backup exits nonzero or leaves `.partial`, orphaned, or mismatched
files.

**Likely cause:** missing database variables, unwritable/full destination,
existing timestamp collision, failed `pg_dump`, or failed validation.

**Safe checks:** read command output, inspect free space and exact pair names,
and keep the suspect files isolated.

**Safe action:** correct credentials/destination capacity or permissions and
create a new backup. Never relabel an incomplete pair as valid and never use
broad wildcard deletion in the backup directory.

### Restore-drill failure

**Symptom:** `pg_restore_verify.sh` exits nonzero or reports that ownership
could not be proven.

**Safe checks:** preserve its output and inspect only the uniquely named
`task037-drill-*` resources. Confirm active `db` and `web` still run.

**Safe action:** stop and investigate the exact failed proof. The script may
intentionally preserve scratch resources rather than risk deleting unrelated
state. Do not substitute `docker compose down`, prune, or volume deletion.

## 19. Development, demo, and benchmark data

Three modes must remain distinct.

### Normal operation

Use approved manual sources, operator-curated catalogue data, the production
resolver/pricer, and governed review/outcome actions. No remote acquisition is
currently automated.

### Deterministic demo bootstrap

The demo corpus is fictional development data for exercising the complete UI.
Enable it only in a disposable or explicitly designated development database:

1. set `PRICEWATCHPH_ENABLE_DEMO_DATA=1` in `.env`;
2. recreate `web` so it receives the changed environment; and
3. run the command.

```sh
docker compose up -d --force-recreate web
docker compose exec web python manage.py bootstrap_demo_data
```

The command is deterministic and conflict-detecting. It creates labelled demo
SKUs, aliases, observations, Listings, PricePoints, DealFlags, and an unresolved
review example through production-authoritative services. It is not real
marketplace evidence and must not be mixed into a database presented as
production observations. Return the flag to `0` and recreate `web` after use.

### Synthetic benchmark tooling

`benchmarks/`, `benchmark-results/`, and BENCH_001/BENCH_002/BENCH_003 evaluate
the portfolio pipeline with controlled labelled synthetic datasets. Benchmark
rows and timing manifests are test evidence, not application input, real
market data, a demo bootstrap, an API feature, or a production backup.

Do not load benchmark datasets into the normal application database or cite
their synthetic prices as observed Philippine marketplace prices. See the
benchmark task files for methodology rather than using this operator guide to
run a benchmark.

## 20. Current limitations

- Public HTTPS/TLS ingress and a live deployment are not included. The current
  Compose file publishes Gunicorn on host port 8000.
- Enabling HTTPS settings assumes a separately controlled trusted proxy. The
  repository contains no Caddy or equivalent service.
- There is no automated acquisition adapter or scheduled ingestion. Only the
  two approved manual sources are operational.
- Generic manual capture cannot supply condition or asking-price classification,
  so it cannot independently feed the complete pricing pipeline.
- Resolution is conservative exact normalized alias matching. Fuzzy or
  probabilistic resolution is not implemented; ambiguous rows need review.
- Pricing creates new PricePoints only for the current Manila day. Explicit
  past-day runs score against existing evidence and do not backfill it.
- Telegram alerts require external bot/chat configuration and a valid public
  origin. Delivery is intentionally at-most-once with no resend workflow.
- Backup creation and an isolated synthetic restore drill exist, but production
  restore, off-host storage, retention, encryption, and backup scheduling are
  deployment responsibilities not implemented here.
- The application has administrator-managed accounts only. It has no public
  registration, token API, MFA, or CAPTCHA.

For roadmap context, see [docs/09_PLANNING.md](09_PLANNING.md) and the individual
approved task contracts under `tasks/`.

## 21. Quick reference

| Task | Command or route | Notes |
|---|---|---|
| Build | `docker compose build` | Builds Python app and React bundle. |
| Start | `docker compose up -d` | Requires a valid scheduler cron value. Runs one-shot migrations. |
| Status | `docker compose ps` | `migrate` should have exited successfully. |
| Logs | `docker compose logs --tail=100 db migrate web scheduler` | No secrets should be printed. |
| Stop safely | `docker compose stop` | Preserves containers and named volumes. |
| Start stopped services | `docker compose up -d` | Reconciles the configured services without deleting volumes. |
| Reconcile/rebuild | `docker compose up -d --build` | Use after source/image changes. |
| Migrations | `docker compose run --rm migrate` | Applies existing migrations. |
| Create administrator | `docker compose exec web python manage.py createsuperuser` | No public signup exists. |
| System check | `docker compose exec web python manage.py check` | Django configuration check. |
| Migration drift check | `docker compose exec web python manage.py makemigrations --check --dry-run` | Must not create files. |
| Backend tests | `docker compose exec web pytest -v` | PostgreSQL only; never substitute SQLite. |
| Frontend checks | `cd frontend && npm ci && npm run check` | Lint, unit tests, production build. |
| Manual listing ingest | `docker compose exec -T web python manage.py ingest manual_capture` | Reads one JSON object from stdin. See Section 8. |
| Personal trade | `/admin/ingestion/rawlisting/log-personal-trade/` | Requires `ingestion.add_rawlisting`. |
| Resolve | `docker compose exec web python manage.py resolve_listings` | Exact aliases; preserves human decisions. |
| Review | `/reviews` | Staff/model permissions required. |
| Price current day | `docker compose exec web python manage.py price_listings` | Manila day and prior 90-day window. |
| Price replay | `docker compose exec web python manage.py price_listings --day YYYY-MM-DD` | Past-day scoring only; no PricePoint backfill. |
| Deals | `/deals` | Persisted signals only. |
| Price history | `/skus/<sku-id>` | Filterable by condition. |
| Outcomes | `/deals/<deal-flag-id>/outcome` | Skip, purchase, sale, corrections. |
| Scheduler logs | `docker compose logs --tail=200 scheduler` | Fixed resolve → price → alert pipeline. |
| Send alerts now | `docker compose exec web python manage.py send_deal_alerts` | Obeys enable flag, activation cutoff, and at-most-once claims. |
| Reset login throttle IP | `docker compose exec web python manage.py axes_reset_ip <client-ip>` | Clears only that IP's active attempts. |
| Backup | `docker compose --profile backup run --rm backup` | Writes validated dump/checksum pair. |
| Isolated restore drill | `./pg_restore_verify.sh` | Real scratch restore of synthetic fixtures; never restores production. |

Never use SQLite, floating-point money, direct RawListing edits, broad Docker
cleanup, or Facebook Marketplace data in this project.
