# 01 — Planning: Phase 1

Planning artefact only. No code exists as a result of this document. Everything
here is derived from `CLAUDE.md`, `docs/ROADMAP.md`, `docs/00_PLANNING.md`, and
the models committed in TASK_002–TASK_004; anything not derivable from those is
in Section 4, not asserted here.

---

## 0. What changed since 00_PLANNING

### 0.1 eBay is out

`docs/00_PLANNING.md` §5 carried an eBay Unknown whose resolution was deferred
to phase 1. It has been resolved: **eBay cannot supply Philippine used-market
prices at any access tier.** The eBay Buy APIs support sixteen marketplaces and
the Philippines is not among them; `www.ebay.ph` redirects to `www.ebay.com`.
The Marketplace Insights API — the only remaining surface carrying sold-price
history — is a Limited Release that is closed to new users and, separately, does
not cover PH. The Browse API returns active listings only. The Finding API,
which once exposed `findCompletedItems`, was decommissioned in February 2025.

Independently, the eBay API License Agreement prohibits retaining listing data
after it stops being publicly available, deriving average selling price per
category without written permission, and using eBay content to model prices —
which is to say it prohibits `RawListing` immutability, `PricePoint`, and
`DealFlag` respectively.

The full finding, with quoted clauses, belongs in `docs/SOURCES.md` §1 and is
recorded there by a human, per that document's rule that no `UNVERIFIED` field
may be filled in by an LLM. **This document does not restate the terms as
verified fact; it records only that phase 1 has no eBay component.**

`ebay_client`, named in `docs/ROADMAP.md`'s architecture and in
`docs/00_PLANNING.md` §1, is permanently out of scope. No stub, no placeholder,
no module.

### 0.2 Phase 1's source is first-party data

`docs/ROADMAP.md` scopes phase 1 as "eBay client + RawListing ingestion +
management command". With the eBay client gone, the phase keeps its shape —
ingestion writing `RawListing`, driven by a management command — and changes its
sources to the two already marked `APPROVED` in `docs/SOURCES.md`:

- **`personal_records`** — the 2018–present buy/sell records, entered manually
  (`SOURCES.md` §2).
- **`manual_capture`** — paste-a-listing capture (`SOURCES.md` §6).

Both already exist as `Source` rows, seeded by
`sources/migrations/0002_seed_approved_sources.py` with `rate_limit=None`.
Neither has any external terms of service, so phase 1 begins with no outstanding
governance question — which is the main reason this direction was chosen over
scraping a source whose terms are silent on automation.

**A note on the roadmap's sub-module list.** `docs/ROADMAP.md` names four
ingestion sub-modules: `ebay_client`, `tipidpc_scraper`, `manual_capture`,
`retailer_prices`. `personal_records` is not among them, yet it is an approved
source in `SOURCES.md` and a seeded row in the database. This document treats
the roadmap's list as non-exhaustive and adds `personal_records` as a documented
extension. That is recorded here rather than done silently.

### 0.3 Unknowns from 00_PLANNING §5 that TASK_002–004 already closed

`docs/00_PLANNING.md` §5 listed these as open. They were decided during
implementation and are settled; this document treats them as fact and does not
reopen them.

| §5 Unknown | Resolution as committed |
|---|---|
| `RawListing.raw_price` nullability | Option (a). `raw_price_text` always populated verbatim; `raw_price` nullable Decimal, NULL when unparseable — `ingestion/models.py` |
| Condition vocabulary | `new`, `like_new`, `used`, `for_parts` — `listings/models.py` |
| PricePoint's "daily" boundary | The date after converting `fetched_at` to Asia/Manila, not UTC. Enforced by aggregation code in phase 5, not by the column — `pricing/models.py` |
| Deal score scale | Signed Decimal in units of the baseline's median absolute deviation; negative means below baseline — `pricing/models.py` |
| `Outcome.bought_at` / `sold_at` | Four fields, not two: `bought_at`, `bought_price`, `sold_at`, `sold_price`, with `realised_margin` a persisted `GeneratedField` — `outcomes/models.py` |
| Django 5.2 `CheckConstraint` signature | `condition=`, not `check=` |
| Whether a restricted app role is reproducible in tests | Not attempted; immutability is the Option B trigger plus Option A save/delete guards, per 00_PLANNING §3 |

**Currency** also resolves, and resolves to nothing needing doing.
`docs/00_PLANNING.md` §5 said the currency question "falls out of the eBay
marketplace question above" — it does. With eBay out, every remaining in-scope
source quotes PHP. No currency column, no FX rate source, no rate-at-time-of-
fetch. The money field lists in 00_PLANNING §2 stand unchanged.

One field named in 00_PLANNING §2 is still absent by deliberate deferral:
`Source.is_active`, explicitly placed out of scope by TASK_002 on the grounds
that no source is paused yet. Phase 1 does not need it either — see §4.

---

## 1. Component boundaries

Phase 1 builds inside the **Ingestion** component defined in
`docs/00_PLANNING.md` §1. That component's boundary is unchanged and still
governs: ingestion reads `Source` and whatever the source provides, writes
`RawListing` rows and updates `Source.last_successful_fetch`, and is not
responsible for resolving titles to SKUs, cleaning titles, inferring condition,
judging prices, or ever returning to a row it has written.

What follows subdivides that component for phase 1. As in 00_PLANNING, the part
that matters for each is the last sentence — what it may not do.

### The `ingest` management command

Owns the entire interface between the scheduler and the rest of the system. It
parses arguments, selects exactly one importer, hands it an input, and turns the
result into a process exit code and log output. Per 00_PLANNING §1 the
scheduler's whole interface is "invoke this management command with these
arguments" plus the exit code and whatever the command logged, so this command
*is* that contract and nothing else may become part of it.

It is explicitly **not** responsible for: parsing any source's format itself,
knowing what a `RawListing` field means, resolving anything to a SKU, computing
any aggregate, retrying on failure, holding state between invocations, running
more than one importer per invocation, or discovering which sources exist by any
means other than the argument it was given. It is not a dispatcher that grows
into a scheduler — `CLAUDE.md` forbids a broker, and a command that loops over
all sources is the first step toward becoming one.

### The `manual_capture` importer

Owns turning a captured listing — a title, a price string, and whatever context
was captured with it — into `RawListing` rows under the seeded `manual_capture`
source. It owns the parse of the price string into a Decimal, and owns deciding
that a price string is unparseable, which is a real outcome rather than an
error: `raw_price_text` keeps the verbatim string and `raw_price` is NULL.

It is explicitly **not** responsible for: normalising or casing `raw_title`,
inferring condition or location, judging whether a price is plausible, writing
`Listing`, or rejecting a row because the title looks unresolvable. A capture
that cannot be resolved later is still a true observation now.

### The `personal_records` importer

Owns turning the 2018–present buy/sell file into `RawListing` rows under the
seeded `personal_records` source. It owns the mapping from a transaction record
to price observations, including the `fetched_at` question in §4.

It carries the same negative list as `manual_capture`, plus one specific to it:
**it must not write `Outcome` rows**, and must not populate `bought_price` or
`sold_price` anywhere. Its input looks like outcome data and the temptation to
short-circuit phase 8 is real, but `Outcome` hangs off `DealFlag` — it records
what was done about a flag this system raised. A 2019 purchase made before this
system existed was never flagged and has no `DealFlag` to point at. Writing it
into `Outcome` would fabricate evidence of the system's own performance, which
is precisely the credibility that `docs/ROADMAP.md` says the table exists to
establish.

### Deferred, with no scaffolding

`tipidpc_scraper` and `retailer_prices` remain unbuilt and unstubbed. `SOURCES.md`
§3, §4 and §5 all remain `UNDER REVIEW`; no source whose governance status is
unresolved gets a module, a `Source` row, or a placeholder. `ebay_client` is
permanently out of scope per §0.1.

---

## 2. What phase 1 does not touch

Stated positively so the task files can point at it.

- `Listing`, `PricePoint`, `DealFlag`, `Outcome` — **no phase-1 task writes a row
  into any of them.** They are written by phases 3, 5 and 8; phase 1 writes
  `RawListing` and nothing downstream.

  One narrow exception, and it is about *columns*, not rows: TASK_005 adds
  `observed_at`, `price_kind` and `trade_side` to `Listing` and corrects a
  comment on `PricePoint`. Those columns exist so that phases 3 and 5 can stay
  inside their own boundaries — see §4.2 and §4.3 — and nothing in phase 1
  populates them. `DealFlag` and `Outcome` are untouched entirely.
- `Sku` and `SkuAlias` — phase 1 creates neither. Ingestion that invents SKUs is
  the failure 00_PLANNING §1 explicitly forbids.
- Any normalisation of `raw_title`.
- The cron container. Phase 1 delivers a command that cron *could* call; whether
  anything schedules it is phase 2, and §4 questions whether phase 2 still
  applies to these sources at all.
- DRF and any HTTP surface. No API before phase 6.
- The Django admin beyond what TASK_003 already registered.

---

## 3. Phase-1 task breakdown

Four tasks. `CLAUDE.md` permits planning at most four ahead, and this is exactly
four; anything beyond TASK_008 depends on what the first real import produces —
in particular on how messy the captured titles turn out to be, which is not
knowable before there is data.

Each task ends with the two commands from `CLAUDE.md`, both clean:

    docker compose exec web pytest -v
    docker compose exec web python manage.py makemigrations --check --dry-run

**TASK_005 is the only task in this phase that may produce a migration** — two of
them (`ingestion/0003`, `listings/0002`). TASK_006–008 write rows, not schema, so
for those the original rule still holds: if `makemigrations --check` is not
clean, something has changed a model that the task had no business changing.

Note that `--check` asserts no *unmigrated* model change remains, not that no
migration exists; it exits zero once TASK_005's migrations are generated and
committed.

### TASK_005 — provenance fields, payload retention, and seller pseudonymisation

*Goal:* the schema and write-path primitives that the importers need in order to
write immutable rows safely and once. Detailed in
`tasks/TASK_005_PROVENANCE_PSEUDONYMISATION.md`, which is hardened.

*Files:* `ingestion/models.py`, `listings/models.py`, `pricing/models.py`
(comment only), `config/settings.py`, `.env.example`, three helper modules
(`ingestion/pseudonymise.py`, `ingestion/timeparse.py`, `pricing/bucketing.py`),
two migrations, and four test modules.

*Question the acceptance tests must answer:* **does a counterparty name survive
nowhere in a persisted row — neither in `seller` nor inside `payload`, both
carrying the identical token from one keyed-HMAC function; does the key fail
loudly at settings load rather than defaulting; does side-qualifying
`external_id` let both sides of a same-day transaction persist while still
rejecting a true duplicate; and do the two sides bucket to distinct Manila days
where import-time stamping would have collapsed them into one?**

This task exists because it changes `RawListing` and `Listing`, which TASK_003
and TASK_004 already shipped. It is a new migration layered on reviewed history,
**not** a correction to it — neither of those tasks is reopened, and none of
their test modules is edited.

### TASK_006 — the `ingest` command and the `manual_capture` importer

*Goal:* one management command exists, it dispatches to exactly one importer,
and a captured listing lands in `RawListing` as a faithful record — including
when its price cannot be parsed.

*Files:* `ingestion/management/__init__.py`,
`ingestion/management/commands/__init__.py`,
`ingestion/management/commands/ingest.py`, an importer module under
`ingestion/`, and `ingestion/tests/test_task_006_*.py`. No model file, no
migration.

*Question the acceptance tests must answer:* **does the command write
`RawListing` rows against the seeded `manual_capture` source; does an
unparseable price survive as verbatim `raw_price_text` with `raw_price` NULL
rather than being dropped or defaulted to zero; does the command complete
without throttling or erroring when `Source.rate_limit` is NULL; and does a
malformed input produce zero rows and a non-zero exit code rather than a partial
import?**

Two of those deserve their reason stated. The NULL `rate_limit` case is not
incidental: `sources/models.py` defines NULL as "no automated fetching cadence
exists to describe", explicitly not "unlimited", and an importer that reads the
field naively will either crash or invent a delay. The all-or-nothing case
matters because `RawListing` is immutable — a partial import cannot be rolled
back by deleting the rows it wrote.

### TASK_007 — the `personal_records` historical import

*Goal:* seven years of buy/sell history land as `RawListing` rows with the
correct observation dates, and re-running the import is a no-op.

*Files:* an importer module under `ingestion/`, a registration in
`ingest.py`'s dispatch, and `ingestion/tests/test_task_007_*.py`.

*Question the acceptance tests must answer:* **does each imported transaction
produce two rows — a buy side and a sell side, each with its own `occurred_at`
and a side-qualified `external_id` — while `fetched_at` records the import run
rather than the transaction; do records spanning 2018 to the present therefore
fall into distinct Manila day buckets instead of collapsing into one; is every
counterparty name pseudonymised before write, in both `seller` and `payload`;
and does a second run of the same unchanged file insert exactly zero new rows?**

The bucketing half is the whole point. If historical records are stamped with
import time, every price from 2018 onward shares one Manila `day`, the
`(sku, condition, day)` unique constraint permits exactly one `PricePoint` for
all of it, and the historical baseline this source exists to provide is destroyed
at the moment of import — silently and irreversibly, since the rows cannot be
edited. TASK_005 supplies the mechanism that prevents this (`occurred_at`,
`observed_at`, `manila_day`); this task is where it has to actually be used.

Note the field split, since it is easy to get backwards: **`fetched_at` is the
import run, `occurred_at` is the 2019 transaction.** Both facts are kept because
a price recalled in 2026 about a 2019 trade is weaker evidence than one observed
contemporaneously, and collapsing them would make the two indistinguishable
forever.

### TASK_008 — run bookkeeping and the scheduler contract

*Goal:* a run reports what it did, in a form the scheduler component can consume
and a human can audit.

*Files:* `ingest.py` and possibly a small reporting helper under `ingestion/`,
plus `ingestion/tests/test_task_008_*.py`. `sources/models.py` is not modified —
`last_successful_fetch` already exists.

*Question the acceptance tests must answer:* **does a successful run advance
`Source.last_successful_fetch` to the run's completion time, does a failed run
leave it untouched, and does the command emit a per-run summary of rows read,
rows written, and rows rejected with the reason for each rejection?**

`last_successful_fetch` is nullable precisely because "never succeeded" is a
real state that must not be papered over (00_PLANNING §2). A failed run that
advances it converts a real state into a lie, and because the field is the only
persistent record of ingestion health, nothing downstream can detect it.

---

## 4. Unknowns

Everything above that rests on something not yet decided. Each entry says what
would resolve it, or — where an entry is now closed — what was decided and where
the decision lives.

### 4.1 Is a buy/sell transaction one `RawListing` or two? — **DECIDED: two**

Buy side and sell side each become a `RawListing`, because each is independently
a true statement about what something traded for. The double-counting risk is
real but is a *phase-5 policy* question, not a reason to discard an observation
at ingest: `Listing.trade_side` (`buy` / `sell`, NULL for asking prices) makes
the two distinguishable, so phase 5 can exclude realised sells from a baseline
that judges buying opportunities rather than folding this project's own trading
margin into it.

Consequence that is not obvious: two rows share a `record_id`, so `external_id`
must be **side-qualified** (`"{record_id}:buy"` / `":sell"`). Without the suffix
the two sides differ only by `occurred_at`, and a transaction that flipped on the
same day collides on `(source, external_id, fetched_at)` — the second side
rejected as a false duplicate. See TASK_005 Decision 7; the constraint-level
tests proving the suffix is both necessary and sufficient are frozen there.

### 4.2 Do realised prices belong in the same baseline as asking prices? — **DECIDED: the schema can express the difference; the policy stays phase 5's**

Realised prices sit below asking prices by roughly the negotiating margin, so
mixing them shifts a baseline by an amount that depends on the mix ratio — which
drifts as sources come online. That is a phase-5 judgement, but it can only be
*made* if the schema records the distinction, so the field lands now.

**`Listing.price_kind`** (`asking` / `realised`), with `choices` plus a
`CheckConstraint`, per this repo's established vocabulary pattern.

It is on `Listing` and not `RawListing` for a boundary reason rather than a
stylistic one: phase 5 reads `Listing` and `Sku` only, so a discriminator it must
branch on has to live there. It is not on `Source` because the property is
row-level — `manual_capture` can capture a live listing (asking) *and* a "sold
for ₱X" forum post (realised), and a source-level flag would force exactly the
source-name check this was meant to prevent.

Paired with `trade_side` from §4.1 under the constraint
`trade_side IS NULL OR price_kind = 'realised'` — nothing has traded on an asking
price. The converse is deliberately not enforced: a "sold for ₱X" capture is
realised with an unknown side.

Both fields are **nullable**, which was forced rather than chosen: 11 shipped
`Listing.objects.create(...)` call sites in TASK_004's frozen tests pass neither,
and `CLAUDE.md` forbids editing a frozen test. A default would be worse than NULL
— defaulting `price_kind` to `asking` would silently mislabel every realised
price. A phase-3 task tightens both to `NOT NULL` once a resolver populates them.
See TASK_005 Decision 1.

### 4.3 What is `fetched_at` for a historical record? — **DECIDED: both facts, two fields**

`fetched_at` stays literally true — the import run — and a new nullable
`RawListing.occurred_at` carries what the source stated about when the priced
event happened. `00_PLANNING.md` §2 anticipated exactly this when it said
`fetched_at` is "not the listing's posting time, which is a different fact".

Stamping `fetched_at` with 2019 was the zero-migration option and was rejected
because it is false, and because it would make a price *recalled in 2026* about a
2019 trade indistinguishable from one *observed in 2019* — in an immutable table,
for a project whose stated purpose is evidence.

A third field follows, and it closes a bug that predates this question:
**`Listing.observed_at`**, written by the resolver as
`COALESCE(occurred_at, fetched_at)`. `PricePoint.day` derives from it. Before
this, `day` was documented as deriving from `fetched_at` — which lives on
`RawListing`, a table the pricing engine is explicitly forbidden to read
(`00_PLANNING.md` §1). Phase 5 could not have computed its own bucket key without
violating its own boundary. See §2 above and TASK_005 Decision 2.

A bare date from a source is read as **Manila** midnight, and day-bucketing uses
`AGGREGATION_TIME_ZONE` — a third timezone setting, hardcoded rather than
environment-configurable, since changing it would silently rebucket all stored
history. `00_PLANNING.md` §5 called this out: "the aggregation boundary is a
third decision that neither setting makes."

### 4.4 The idempotency key for a file-based source

`RawListing`'s unique constraint is `(source, external_id, fetched_at)`, partial
on `external_id IS NOT NULL` (`ingestion/models.py`). File-based sources have no
natural external identifier, so one must be manufactured, and two options exist:

- **An explicit `record_id` column** you maintain in the file. Stable across
  edits, so correcting a typo in a title updates nothing (the row is immutable)
  but at least collides rather than duplicating.
- **A content hash** of the row. Requires no discipline from you, but changes
  the moment you fix any typo, which silently inserts a second row for the same
  observation instead of colliding — the exact failure the key exists to prevent.

**Partly decided.** The explicit `record_id` column is settled by implication:
TASK_005 freezes `"{record_id}:buy"` / `"{record_id}:sell"` as the `external_id`
convention (§4.1), which presupposes a stable record identifier the file carries.
A content hash cannot serve, for the reason above — it changes when you fix a
typo, inserting a duplicate instead of colliding.

What remains open is the sub-question below.

Related and worth deciding at the same time: because `fetched_at` is *part* of
the key, re-importing a record whose date was corrected inserts a duplicate
regardless of which option is chosen. Accept that, or add a narrower guard on
`(source, external_id)` alone?

### 4.5 The input file: schema, location, producer

Not defined anywhere in `CLAUDE.md`, `docs/ROADMAP.md` or `docs/00_PLANNING.md`
— 00_PLANNING §5 flagged this for both `manual_capture` and `retailer_prices`
and it is still open. Needed: the format (CSV is assumed above but not decided),
the column set, where the file lives, and whether it is committed to the repo,
mounted into the container, or kept outside both.

The last of those interacts with 4.6. *Resolution:* your answer.

**Blocking: this must be resolved before TASK_007's acceptance tests are
hardened.** TASK_005 pseudonymises what the importer writes to the database, but
it cannot protect a fact it never sees — the source file itself. Whatever this
resolves to determines whether the file is safe to read from at all in its
current form, so it cannot be silently skipped when TASK_007 starts.

### 4.6 Personal data in `RawListing.seller` — **DECIDED: keyed HMAC pseudonym at write**

No plaintext counterparty name ever enters the database. `seller` receives an
HMAC-SHA256 token under a secret key held in `DJANGO_SELLER_PSEUDONYM_KEY`. A
stable token per counterparty keeps repeat-counterparty analysis possible while
the name itself is never written to a row that cannot be redacted.

A bare SHA-256 was rejected: the space of Filipino names and forum handles is
small enough to brute-force, so an unkeyed digest is obfuscation rather than
pseudonymisation.

**The redactor and the column share one function.** The obvious implementation —
HMAC the `seller` column, store the verbatim source row in `payload` — defeats
the whole exercise, because the plaintext survives one column over in the same
immutable row. `redact_payload()` therefore calls the same `pseudonymise()`, so
the two tokens are identical by construction rather than by two code paths
agreeing today. Keys the redactor does not recognise pass through verbatim, which
makes its PII key list a security boundary. Frozen tests assert both the token
identity and the stronger property: the plaintext appears in **no** column of the
persisted row.

Two consequences worth carrying forward:

- **The key can never be rotated.** Tokens live in immutable rows, so rotation
  re-pseudonymises nothing already written and old/new tokens for the same
  counterparty stop matching — destroying the linkage that motivated choosing a
  pseudonym over simply omitting the field. It is permanent for the life of the
  database and **backup-critical**, alongside the data itself.
- It **fails loudly**: `os.environ["DJANGO_SELLER_PSEUDONYM_KEY"]`, matching
  `SECRET_KEY`'s pattern, never `.get()` with a default. A silently-defaulted
  pseudonymisation key produces tokens that look right and protect nothing.

Note this narrows but does not eliminate §4.5's exposure: the *source file* still
holds plaintext names, so where it lives remains a live question.

See TASK_005 Decisions 5 and 6.

### 4.7 Does phase 2 still make sense?

`docs/ROADMAP.md` phase 2 is "Deploy ingestion somewhere always-on", budgeted at
2–3 sessions. Neither phase-1 source is scheduled: both are human-triggered
imports. There is nothing for an always-on deployment to do until a source
exists that needs cron, and every such source is currently `UNDER REVIEW`.

Phase 2 may need to move behind whichever source is approved next, or to be
rescoped as "make the command deployable" without an always-on component.
*Resolution:* your call, and it does not block phase 1.

### 4.8 Where the difficult titles come from

Direction B's value to phase 3 (normalisation and entity resolution) rests on
having realistically messy raw titles. `personal_records` entries are likely
already clean — they were written by you, for you, in whatever shorthand you
use. `manual_capture` is therefore the only phase-1 source of genuine resolution
difficulty, and its volume is bounded by how much you paste by hand.

This is a stated risk rather than a question: phase 3 may reach its acceptance
criteria against a corpus too small and too clean to prove anything.
`docs/00_PLANNING.md` §5's "Volumes and quality figures" entry already requires
that no accuracy figure be published without a stated sample size; that rule
covers this, but the risk to phase 3's schedule is worth recording now.

### 4.9 Raw payload retention as JSONB — **DECIDED: adopted, redacted**

`RawListing.payload` stores the verbatim source row, with PII pseudonymised on
the way in per §4.6.

My earlier reasoning for deferring this was wrong and is corrected here rather
than quietly dropped. I argued that "a CSV row *is* the payload" so no phase-1
source forces the question. That missed the actual question, which is not whether
a payload exists but **whether every source-stated fact survives re-derivation**.
`Listing` is derived and mutable, so a wrong `price_kind` or a missing
`trade_side` is cheap to fix — *but only if the underlying fact still exists in
`RawListing`*. Immutability protects the rows you wrote; it does nothing for the
facts you declined to record. Without the payload, any field this schema failed
to anticipate is lost the moment the source file is edited or discarded.

NULL and `{}` stay distinguishable: NULL means "no payload recorded", `{}` means
"recorded and empty". `RawListing`'s job is not to conflate two facts.

The cost 00_PLANNING §5 flagged — that this is "a place for personal data to
accumulate" — is real and is what the redaction step exists to bound.

### 4.10 Carried forward, unchanged

- **`Source.is_active`.** Deferred by TASK_002. Phase 1 does not need it: both
  sources are active, and a human-triggered import is paused by not running it.
- **`AGENTS.md` byte-identical to `CLAUDE.md`.** 00_PLANNING §5's "Meta" entry.
  Still unresolved, still not acted on.
- **Volumes and quality figures.** All still **TBD** and still measured, not
  estimated. Phase 1's contribution: rows per source per import, counted from
  `RawListing` after the first real run.
