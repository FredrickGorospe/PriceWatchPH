# 00 — Planning

Planning artefact only. No code exists as a result of this document. Everything
here is derived from `CLAUDE.md` and `docs/ROADMAP.md`; anything not derivable
from those two files is in Section 5, not asserted here.

---

## 1. Component map

The architecture in `docs/ROADMAP.md` has five components. For each, the part that
matters most is the last sentence — what it is *not* allowed to do. Boundaries are
only real if the negative side is written down.

### Scheduler (cron, own container)

Owns *when* things run, and nothing about *what* they do. It reads the crontab and
the environment; it writes nothing to the database. Its entire interface to the rest
of the system is "invoke this management command with these arguments" plus the
process exit code and whatever the command logged. It is explicitly **not**
responsible for: knowing which sources exist, parsing anything, deciding whether a
run produced good data, retrying beyond whatever the cron entry itself specifies,
holding per-run state between invocations, or fanning work out to parallel workers.
It is not a queue and must never grow into one — `CLAUDE.md` forbids a broker, so
if a scheduling need cannot be expressed as "cron calls one command", the need is
wrong, not the constraint.

### Ingestion — `ebay_client`, `tipidpc_scraper`, `manual_capture`, `retailer_prices`

Owns contact with the outside world. It reads `Source` (for base URL, rate limit,
last successful fetch) and reads whatever the remote source returns; it writes
`RawListing` rows and updates `Source.last_successful_fetch`. Each sub-module owns
one source's transport, authentication, pagination, and rate limiting, and knows
nothing about the others. Its output is a faithful record of what a source said at
a moment in time. It is explicitly **not** responsible for: resolving a title to a
SKU, normalising or cleaning a title, inferring condition, judging whether a price
is good, deduplicating against previous days beyond a per-source idempotency key
that prevents inserting the same observation twice, or ever returning to a row it
has already written. A RawListing is a fact about a fetch, not a record it maintains.
Facebook Marketplace is permanently out of scope and no sub-module for it exists or
will be proposed.

### Normalisation + entity resolution

Owns the mapping from a messy `RawListing.raw_title` to a canonical `(Sku,
condition)` pair, together with an honest statement of how confident it is and by
what method it decided. It reads `RawListing`, `Sku`, and `SkuAlias`; it writes
`Listing` and, where a resolution is confirmed by a human, new `SkuAlias` rows so
the next occurrence resolves without help. It is explicitly **not** responsible for:
editing `RawListing` in any way (that is a hard constraint, not a preference),
scoring or pricing anything, inventing `Sku` rows for titles it cannot match —
unmatched or low-confidence titles are left for the review queue rather than
guessed into the catalogue — or hiding its uncertainty. A resolution it is unsure
about must be recorded as unsure, not silently dropped.

### Pricing engine

Owns the per-`(sku, condition)` rolling baseline, the residual of a listing against
that baseline, and the deal score derived from it. It reads `Listing` and `Sku`;
it writes `PricePoint` (the daily aggregate) and `DealFlag` (the per-listing
judgement, including which baseline it used and why it fired). It is explicitly
**not** responsible for: re-resolving listings or second-guessing entity resolution,
reading `RawListing` directly, notifying anyone about anything (alerts are phase 7
and live elsewhere), deciding whether a flag was acted on, or recomputing baselines
on demand during a web request. Every number it produces is written down with the
inputs that produced it, so a flag can be explained after the fact.

### Django app — dashboard, SKU pages, deal feed, review queue, outcome tracker

Owns presentation and human input. Until phase 6 this is the Django admin; there is
no frontend framework before then. It reads everything and writes exactly two kinds
of thing: human decisions in the review queue (confirming or correcting a
resolution, which in turn lets entity resolution create an alias) and `Outcome`
rows recording what was actually done about a flag, including the flags that were
deliberately skipped and why. It is explicitly **not** responsible for: fetching
from any source, computing baselines or scores at page-render time, mutating
`RawListing` (its admin registration for that model is read-only), or being the
place where business logic lives. If a page needs a number, the number was computed
by the pricing engine and stored.

---

## 2. Data model commentary

Two rules applied throughout, stated once here.

**Where a constraint is enforced.** Database-level for anything that must hold
regardless of how the row arrived: uniqueness, referential integrity, sign and range
checks on money, and one-row-per-period aggregates. These survive `bulk_create`,
`QuerySet.update()`, the admin, a migration, `psql`, and any future non-Django
writer, and they hold under concurrency where a Python check-then-insert races.
Python-level for anything that needs application context or a readable error before
it reaches the database: workflow rules ("a human must confirm before an alias is
created"), threshold policy, and controlled vocabularies as `choices` for form and
admin validation. Where both are cheap — a vocabulary is both `choices` and a
`CheckConstraint` — do both: `choices` gives the good error message, the constraint
gives the guarantee.

**Money.** Every money column is `DecimalField(max_digits=12, decimal_places=2)`,
mapping to Postgres `numeric(12, 2)`. Never `FloatField`, never a Python `float`
anywhere on the path to one of these columns. `decimal_places=2` because PHP settles
to centavos and no source in scope quotes a finer unit. `max_digits=12` leaves ten
integer digits, which is far beyond any PC component price in PHP; the headroom is
deliberate but the real reason for fixing one width across every money column is
uniformity — aggregates, joins, and comparisons between a listing price and a
baseline never need a cast or a rounding decision, and a reviewer never has to check
which column is which. `numeric` is variable-width in Postgres, so unused headroom
costs nothing in storage.

### Sku

| Field | Type | Why (non-obvious only) |
|---|---|---|
| `brand` | text | |
| `model` | text | |
| `variant` | text | The same model ships in materially different forms — VRAM size, cooler, OEM vs retail — and those trade at different prices. Without `variant`, one baseline averages across products that are not the same product. |
| `category` | text, choices: gpu/cpu/ram/mobo/monitor/peripheral | Fixed vocabulary from the roadmap. Category drives which normalisation rules apply and how the dashboard groups things. |
| `launch_msrp` | **Decimal(12, 2)** | A stable anchor that exists before any listing does. Lets a brand-new SKU be sanity-checked on day one, before there is enough data for a rolling baseline. |
| `launch_date` | date | Depreciation is the dominant term in used PC pricing; age is an input to any future baseline that is not purely empirical. |

| Constraint | Where | Why |
|---|---|---|
| `(brand, model, variant)` unique | **DB** | This is the SKU's identity. Ingestion and resolution will attempt concurrent creates; a Python existence check races. `variant` must be non-null empty-string rather than NULL so the unique index actually bites — NULLs do not collide in Postgres. |
| `launch_msrp >= 0` | **DB** | Cheap, and a negative MSRP is always a bug. |
| `category` in the vocabulary | **Both** | `choices` for the admin dropdown and the readable error; `CheckConstraint` so a data load cannot introduce a seventh category silently. |

### SkuAlias

Direct descendant of the PulsoPH BrandAlias work: the accumulated memory of the
entity resolver.

| Field | Type | Why (non-obvious only) |
|---|---|---|
| `sku` | FK → Sku | |
| `alias_text` | text | The messy string as it actually appeared. |
| `normalised_text` | text | The alias after the same normalisation applied to incoming titles. Matching happens on this column, not `alias_text`; storing it means matching is an index lookup rather than a function call per row, and it makes "why did this match" inspectable. |
| `source_of_truth` | text/choices | Whether the alias came from a human confirming a review-queue item or from a bulk seed. Human-confirmed aliases should outrank seeded ones, and mistakes need to be traceable to their origin. |
| `created_at` | timestamptz | |

| Constraint | Where | Why |
|---|---|---|
| `normalised_text` unique | **DB** | One messy string cannot mean two SKUs. If it genuinely does, that is a review-queue case, not two alias rows — and the DB should force that conversation rather than let the resolver pick arbitrarily. |
| Alias only created from a confirmed resolution | **Python** | This is a workflow rule about who approved what. The database cannot see "a human clicked confirm". |

### Source

| Field | Type | Why (non-obvious only) |
|---|---|---|
| `name` | text | |
| `base_url` | text | |
| `terms_notes` | text | What the source's ToS and robots.txt actually permit, recorded next to the code that acts on it. This is the field that keeps the project defensible; it is deliberately in the database and mirrored in `docs/SOURCES.md`, not only in a doc. |
| `rate_limit` | integer (+ unit) | Politeness is per-source configuration, not a constant buried in a client module. |
| `last_successful_fetch` | timestamptz, nullable | Nullable because a source that has never succeeded is a real state and must not be papered over with a default. Stored UTC. |
| `is_active` | boolean | A source can be paused without deleting its history. |

| Constraint | Where | Why |
|---|---|---|
| `name` unique | **DB** | It is the natural key used in management-command arguments and logs. |
| `rate_limit > 0` | **DB** | Zero or negative silently means "no limit", which is exactly the failure mode a rate limit exists to prevent. |
| Actually honouring the rate limit | **Python** | The database has no concept of request timing. Ingestion enforces it. |

### RawListing — immutable

| Field | Type | Why (non-obvious only) |
|---|---|---|
| `source` | FK → Source | |
| `raw_title` | text | Verbatim. Not trimmed, not cased, not cleaned. The whole point of this table is that it is what the source said. |
| `raw_price` | **Decimal(12, 2)** — see the open question below | |
| `url` | text | |
| `seller` | text | |
| `fetched_at` | timestamptz | The observation time, stored UTC. Not the listing's posting time, which is a different fact and may not be available. |
| `external_id` | text, nullable | The source's own identifier where one exists. This, with `source`, is the idempotency key that lets ingestion re-run without duplicating an observation. Nullable because a scraped source may not expose one. |

| Constraint | Where | Why |
|---|---|---|
| No UPDATE, no DELETE | **DB** — see Section 3 | A hard constraint in `CLAUDE.md`. Anything weaker than the database is a convention, and this is not a convention. |
| `(source, external_id, fetched_at)` unique where `external_id` is not null | **DB** | Idempotent re-runs. A partial unique index, because NULL `external_id` rows must be allowed to repeat. |
| `raw_price >= 0` | **DB** | |
| Never a float | **Python + repo hook** | Python-level because the danger is upstream of the column: a parser producing `float` then handing it to Decimal. The existing `warn-float-usage.sh` hook is part of this enforcement. |

**Open question carried into Section 5:** a raw price string can be unparseable
("PM for price", a range, a typo), and because the row is immutable it can never be
fixed afterwards. Two options, and I am not deciding between them here:
(a) `raw_price` nullable Decimal plus a verbatim `raw_price_text` column, so the
unparseable case is preserved and visible; (b) reject the row at ingestion, so
`raw_price` is non-null but observations are silently lost. Option (a) is more in
keeping with "RawListing is what the source said", but it makes every downstream
consumer handle NULL. This changes the field list above, so it is listed as an
unknown rather than assumed.

### Listing — resolved

| Field | Type | Why (non-obvious only) |
|---|---|---|
| `raw_listing` | FK → RawListing | The provenance link. Every resolved listing can be traced back to the exact observation it came from. |
| `sku` | FK → Sku, nullable | Nullable is the review queue: a listing that could not be resolved still exists and still needs to be looked at. |
| `price` | **Decimal(12, 2)** | |
| `condition` | text/choices | Part of the baseline key — used and new are different markets for the same SKU. |
| `location` | text | PH-specific: meetup geography materially affects whether a deal is actionable. |
| `resolution_confidence` | Decimal(5, 4) | Not money, so the money width does not apply. Bounded 0–1 with four decimal places, which is more resolution than any scoring method will meaningfully produce but costs nothing. Decimal rather than float purely so that no float appears in a model file at all — an easier rule to enforce than "float, but only here". |
| `resolution_method` | text/choices | Which mechanism matched: exact alias, fuzzy match, human confirmation. Without this, a bad batch of resolutions cannot be identified and re-run selectively. |
| `resolved_at` | timestamptz | Resolution logic will change; knowing which rows were produced by which era of the resolver is what makes a re-run possible. |

| Constraint | Where | Why |
|---|---|---|
| `raw_listing` unique (one Listing per RawListing) | **DB** | Otherwise the same observation can enter a baseline twice. |
| `price >= 0` | **DB** | |
| `0 <= resolution_confidence <= 1` | **DB** | A confidence outside the unit interval means the resolver is broken, and the check catches it at write time rather than in a chart. |
| `condition`, `resolution_method` vocabularies | **Both** | `choices` for admin, `CheckConstraint` for the guarantee. |
| Confidence threshold for auto-accept | **Python** | Policy, not integrity. It will be tuned, and tuning it must not require a migration. |

### PricePoint — daily aggregate per (sku, condition)

| Field | Type | Why (non-obvious only) |
|---|---|---|
| `sku` | FK → Sku | |
| `condition` | text/choices | |
| `day` | date | The aggregation bucket. Which calendar's day is an open question — see Section 5. |
| `median` | **Decimal(12, 2)** | Median rather than mean because scam listings and typo prices are common and unbounded on the low side. |
| `p25`, `p75` | **Decimal(12, 2)** | The spread is the point. A listing 20% under the median means nothing without knowing whether the interquartile range is 5% or 50% wide. |
| `n_listings` | integer | The honesty column. A median over three listings is not a baseline, and every consumer must be able to see that before trusting the number. |

| Constraint | Where | Why |
|---|---|---|
| `(sku, condition, day)` unique | **DB** | The table's identity. Recomputation must upsert, and a duplicate day would double-count in any rolling window. |
| `p25 <= median <= p75` | **DB** | An ordering violation means the aggregation code is wrong, and it is far cheaper to catch on write than to notice in a chart weeks later. |
| `n_listings >= 0` | **DB** | |
| Minimum `n_listings` before a baseline is usable | **Python** | Policy. A PricePoint computed from two listings is still a true record of those two listings; whether it is *usable* is the pricing engine's judgement and will be tuned. |

### DealFlag

| Field | Type | Why (non-obvious only) |
|---|---|---|
| `listing` | FK → Listing | |
| `score` | Decimal — scale deferred, see Section 5 | Not money. The scale and direction are a phase 5 decision; what is settled now is that it is Decimal, not float. |
| `baseline_pricepoint` | FK → PricePoint | *Which* baseline fired this flag. Without it, a flag is unexplainable the moment the baseline moves, and an unexplainable flag is worthless as evidence. |
| `reason` | text/choices | The rule that fired, in machine-readable form, so flags can be grouped by cause. |
| `flagged_at` | timestamptz | |

| Constraint | Where | Why |
|---|---|---|
| `(listing, baseline_pricepoint)` unique | **DB** | Re-running scoring must not produce duplicate flags for the same listing against the same baseline. |
| `baseline_pricepoint` not null | **DB** | A flag without its baseline is not auditable, and auditability is the reason this table exists rather than a boolean on Listing. |
| Score thresholds for flagging | **Python** | Policy, tuned constantly. |

### Outcome

The table the roadmap identifies as what turns this from a dashboard into evidence.
Skipped flags are recorded here too, with the reason — an honest record of the
decisions not taken is what makes the record of decisions taken credible.

| Field | Type | Why (non-obvious only) |
|---|---|---|
| `deal_flag` | FK → DealFlag | |
| `acted` | boolean | |
| `skip_reason` | text, nullable | Required when `acted` is false. The whole value of the table depends on this being filled in honestly. |
| `bought_at` / `sold_at` | see Section 5 | The roadmap lists these alongside `days_held`, which implies timestamps, but `realised_margin` needs prices as inputs and no other field supplies them. Almost certainly both a date and an amount are needed for each side; I am not inventing the field names here. |
| `days_held` | integer | Capital tied up is a real cost. Margin without holding period is not a return. |
| `realised_margin` | **Decimal(12, 2)**, **signed** | The only money column with no non-negative check: losses are the most informative rows in the table and must be storable. |

| Constraint | Where | Why |
|---|---|---|
| `deal_flag` unique | **DB** | One outcome per flag. |
| `acted = false` implies `skip_reason` is non-empty | **DB** | A `CheckConstraint` expressing the implication. Enforced in the database precisely because the temptation to skip this field is highest when the answer is embarrassing. |
| `days_held >= 0` | **DB** | |
| Consistency between the buy/sell fields and `realised_margin` | **Python** | Deferred until the buy/sell fields are settled; whether it can be a `GeneratedField` is an open question in Section 5. |

---

## 3. RawListing immutability

Three mechanisms. None is implemented as part of this document.

### Option A — Application level

Override `save()` to raise when the instance already has a primary key, override
`delete()` to raise, and register the model in the admin as read-only.

*What it prevents.* The realistic everyday mistake: someone loads a RawListing in a
shell or a management command, changes a field, and saves it. It fails immediately
with an error naming the constraint, which is the best possible developer
experience for the most likely error.

*What it does not prevent.* `QuerySet.update()`, `bulk_update()`, `raw()`, cursor
SQL, `manage.py dbshell`, `psql`, a data migration, the admin if someone
re-registers it, or any process that talks to the database without going through
this model class. That is a long list, and every item on it is reachable by accident.

*Friction.* Essentially zero, with one trap: the tests must assert both what it
catches *and* that it does not catch the bypass paths, or the test suite will read
as proof of a guarantee that does not exist.

### Option B — Database trigger

A `BEFORE UPDATE OR DELETE` trigger on the RawListing table that raises an
exception, added through a migration `RunSQL` with a working reverse operation.

*What it prevents.* Every path in Option A's "does not prevent" list. The rule
becomes a property of the table rather than of the Python code that usually
accesses it, so it holds for `psql`, for a future ingestion process written in
anything, and for a data migration written in a hurry.

*What it does not prevent.* Dropping or disabling the trigger; `TRUNCATE`, which
does not fire row-level triggers; `DROP TABLE`; a restore from a dump that omits
it. All of these are deliberate acts by someone with schema rights, which is a
different threat model from the accidental edit this constraint exists to stop.

*Friction.* Moderate and real. Raw SQL enters the migration history. Any legitimate
future schema change that needs to touch existing rows — a backfill of a new column
— requires a documented disable-and-re-enable step, and that step must exist before
it is needed rather than being improvised. Test teardown needs thought: if the
trigger blocks `DELETE`, fixtures that clean up by deleting rows will fail, so
either teardown goes through transaction rollback (which pytest-django does by
default) or the trigger's treatment of `DELETE` is an explicit decision. The error
surfaces as a database exception, which is less legible than a Python `ValueError`
unless it is caught and wrapped.

### Option C — Postgres permissions

Grant the application's database role `SELECT, INSERT` on the RawListing table and
revoke `UPDATE, DELETE`, with migrations run as a separate owner role.

*What it prevents.* Everything the application connection can attempt, by any means,
including raw SQL — the application literally lacks the capability rather than being
asked not to use it. This is the strongest of the three.

*What it does not prevent.* Anything performed as the owner or migration role, which
includes every migration and any admin task run with the wrong credentials to hand.

*Friction.* The highest of the three, and most of it is operational rather than
code. It requires a second role, a second connection configuration, migrations run
as a different user than the app, and — critically — the test database must
reproduce the same grants, or the guarantee is asserted but never exercised.
Whether pytest-django's database creation can reproduce a restricted-role setup
cleanly is something I have not verified; it is in Section 5.

### Recommendation

**Option B as the enforcement, Option A alongside it purely for error quality, and
Option C recorded as a phase 9 hardening step.**

The reason is a match between mechanism and threat. The failure this constraint
guards against is an accidental write from inside this codebase — a `.update()` in
a fix-up command, a helpful admin action, a hand-run `psql` correction during
debugging. Option A misses most of those paths. Option C catches all of them but
buys that with operational complexity that would be paid in phase 0, before there
is a single row to protect, and with a testing story I cannot yet confirm. Option B
catches every path that matters at the cost of some raw SQL and one documented
maintenance procedure, and it keeps the guarantee attached to the table so it
survives every future change of application code. Option A on top of it costs almost
nothing and converts an opaque database error into a readable one at the exact
moment a developer is confused.

Implement none of this now. The trigger belongs to the task that creates the
RawListing table, and its acceptance test is that a `QuerySet.update()` against an
existing row raises.

---

## 4. Phase 0 task breakdown

Phase 0 in the roadmap is: repo, `CLAUDE.md`, `SOURCES.md`, schema, Postgres in
Compose. `TASK_000` and `TASK_000b` are already committed, so these are the four
remaining. No breakdown of phase 1 or later appears here.

### TASK_001 — Postgres 16 and Django 5.2 boot under Compose

*Goal:* the project starts, and the test suite runs against a real Postgres 16
container with configuration read from environment variables.

*Files:* `docker-compose.yml`, `Dockerfile`, `requirements.txt` /
`requirements-dev.txt`, `pyproject.toml` or `pytest.ini`, `manage.py`,
`config/settings.py`, `config/urls.py`, `conftest.py`, and one test module.

*Question the acceptance tests must answer:* **does the application boot and the
test suite connect to Postgres 16 using only environment-supplied settings, with
`USE_TZ` true, storage in UTC, and the Asia/Manila display timezone present as a
separate setting that is not the storage timezone?**

### TASK_002 — `docs/SOURCES.md` and the `Source` model

*Goal:* every source the project intends to use is documented with its terms and
rate limit, and that record exists in the database as well as in prose.

*Files:* `docs/SOURCES.md`, `sources/models.py`, its migration, `sources/admin.py`,
`sources/tests/`.

*Question the acceptance tests must answer:* **can a Source be recorded with its
base URL, rate limit, terms notes, and a null `last_successful_fetch`, and does the
database reject a duplicate name and a non-positive rate limit?**

Pairing the document with the model is deliberate: it gives the prose a testable
anchor and puts the terms notes where the ingestion code will read them.

### TASK_003 — Catalogue and raw capture: `Sku`, `SkuAlias`, `RawListing`

*Goal:* the identity half of the schema exists, with its constraints at the database
level and immutability enforced on RawListing.

*Files:* `catalogue/models.py`, `ingestion/models.py`, migrations (including the
`RunSQL` trigger), `catalogue/admin.py`, `ingestion/admin.py`, tests for both.

*Question the acceptance tests must answer:* **do the uniqueness and money
constraints hold when written to directly at the database level, and does an
attempted UPDATE of an existing RawListing — including via `QuerySet.update()` —
fail?**

### TASK_004 — Derived schema: `Listing`, `PricePoint`, `DealFlag`, `Outcome`

*Goal:* the rest of the schema exists, so that phase 1 ingestion has somewhere to
land and phase 3 has somewhere to write.

*Files:* `catalogue/models.py` or a `listings/` module, `pricing/models.py`,
`outcomes/models.py`, migrations, admin registrations, tests.

*Question the acceptance tests must answer:* **does every money column round-trip as
`Decimal` at scale 2 without ever accepting a float, and does the database enforce
one PricePoint per `(sku, condition, day)` and reject an Outcome with `acted=false`
and no skip reason?**

Each task ends with the two commands from `CLAUDE.md`:

    docker compose exec web pytest -v
    docker compose exec web python manage.py makemigrations --check --dry-run

Both clean, or the task is not done.

---

## 5. Unknowns

Everything above that rests on something I do not actually know. This section is the
point of the document; each entry says what would resolve it.

**eBay API.** I do not know which API surface is currently available and appropriate
(the Browse API and the older Finding API are not interchangeable and one may be
retired), what the sandbox versus production keyset tiers grant, what the call
quotas are, whether client-credentials OAuth is sufficient or a user token is
required, whether a Philippines marketplace or site identifier exists at all or
whether PH listings must be reached as a location/shipping filter on another
marketplace, or what currency prices are returned in. I am not going to assert any
of these from memory. *Resolution:* read the current eBay developer documentation
and register a keyset, in phase 1. Several of these answers change the ingestion
design and one of them (currency) changes the schema.

**TipidPC.** I do not know what its robots.txt and terms of service permit, whether
listing pages require an authenticated session, or what request rate is acceptable.
*Resolution:* read robots.txt and the ToS directly and record the answer in
`docs/SOURCES.md` and in `Source.terms_notes` before any scraper code exists.

**`manual_capture` and `retailer_prices`.** Neither is defined in `CLAUDE.md` or
`docs/ROADMAP.md`. For `manual_capture` I do not know the input format or who
produces it. For `retailer_prices` I do not know which retailers, or — more
importantly — whether a retailer price is a `RawListing` at all or a separate
reference series that should not enter the used-market baseline. *Resolution:* your
answer, before phase 1.

**Currency.** I have assumed every price is PHP. If any source quotes USD, the
schema needs a currency column and an FX rate source with a rate-at-time-of-fetch,
which changes the field list in Section 2 for RawListing, Listing, and PricePoint.
*Resolution:* falls out of the eBay marketplace question above.

**`Outcome.bought_at` / `sold_at`.** The roadmap lists these next to `days_held`,
which reads as timestamps, but `realised_margin` needs purchase and sale amounts as
inputs and nothing else in the model supplies them. Most likely four fields are
needed rather than two. *Resolution:* your answer; it is a phase 8 model but it is
created in TASK_004.

**Condition vocabulary.** The exact allowed values are not specified anywhere. This
matters more than it looks: `condition` is part of the PricePoint key, so the
vocabulary determines how finely baselines are split and how thin each one gets.
*Resolution:* your answer, informed by what the sources actually emit — which is not
knowable until phase 1 data exists.

**PricePoint's "daily" boundary.** Storage is UTC and display is Asia/Manila, and
the aggregation boundary is a third decision that neither setting makes. A UTC day
splits a Manila evening across two buckets. *Resolution:* your answer; it should be
decided before TASK_004 because it determines whether `day` is derived from
`fetched_at` in UTC or after conversion.

**Deal score.** Scale, direction (is high good or bad), and whether it is bounded
are all phase 5 decisions, but the column is created in TASK_004, so a
representation has to be chosen before the semantics are. *Resolution:* either
decide the scale now, or accept that TASK_004 picks a wide Decimal and phase 5 may
need a migration.

**Raw payload retention.** Whether `RawListing` should also store the source's
complete response as JSONB alongside the parsed fields. It would make re-parsing
possible without re-fetching, which is valuable given the row is immutable — but it
is also a large storage commitment and a place for personal data to accumulate.
*Resolution:* your call, before TASK_003.

**`RawListing.raw_price` nullability.** The option (a) / option (b) question raised
in Section 2. *Resolution:* your call, before TASK_003.

**Django 5.2 specifics.** I am not certain of: whether `CheckConstraint` currently
takes `check=` or `condition=` (one of these was renamed in a recent 5.x and the
other is deprecated, and I do not want to write a document that teaches the wrong
one); whether `GeneratedField` is the right tool for `realised_margin` or
`days_held` and what its Postgres stored-versus-virtual limitations are; whether
`db_default` is appropriate anywhere here; and the exact exit-code and output
contract of `makemigrations --check --dry-run`. *Resolution:* the Django 5.2 release
notes and a scratch run inside TASK_001, before any of these appear in a model file.

**Postgres 16 and the test harness.** I have not verified: whether a trigger created
via `RunSQL` interacts cleanly with pytest-django's transactional test rollback;
whether the test database role can `CREATE EXTENSION` (relevant if fuzzy matching in
phase 3 wants `pg_trgm`, and if it cannot, the extension has to be baked into the
image or the approach changes); whether a partial unique index with a NULL-tolerant
`WHERE` clause behaves as I described for the RawListing idempotency key; and
whether a restricted application role (immutability Option C) can be reproduced
under `--create-db` at all. *Resolution:* small experiments during TASK_001, and
Option C's answer determines whether the phase 9 hardening step in Section 3 is
actually available.

**Whether DRF is needed in phase 0.** `CLAUDE.md` names DRF as part of the stack but
no API surface exists before phase 6. TASK_001 could install it and configure
nothing, or defer it entirely. *Resolution:* your preference. It affects only the
requirements file.

**Volumes and quality figures.** No measured number exists yet, so none appears in
this document. Listings ingested per day: **TBD** — filled in by running phase 1
ingestion for seven consecutive days and counting RawListing rows per source per
day. Entity-resolution accuracy: **TBD** — filled in by drawing a random sample of
raw titles, hand-labelling them, and scoring phase 3 output against that labelled
set, reporting the sample size alongside the figure. Catalogue size, flag precision,
and realised margin: **TBD** by the same principle. Nothing goes in a README or a
case study until it has been measured this way.

**Meta.** `AGENTS.md` is currently byte-identical to `CLAUDE.md`. I do not know
whether that duplication is intentional, whether it should become a symlink, or
whether the two are meant to diverge. Noted, not acted on.
