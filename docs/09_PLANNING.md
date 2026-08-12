# Phase 9 Planning — Production deployment

## 1. Status, authority, and sequencing

Phase 8 (`docs/08_PLANNING.md`) and Phase 7 (`docs/07_PLANNING.md`) are both
complete and committed. Phase 9 is next.

`docs/ROADMAP.md` scopes Phase 9 as *"Production Docker, Caddy, HTTPS,
backups"*. This document derives what those four words actually mean for **this**
repository rather than expanding them into generic DevOps work. Where the
roadmap and the committed repository disagree, the repository wins.

### 1.1 Roadmap divergence recorded, not silently absorbed

Roadmap Phases 1 (*"eBay client + RawListing ingestion"*) and 2 (*"Deploy
ingestion somewhere always-on"*) were **never completed as written**. The
repository shipped Phases 3–8 on manual ingestion only:

- `ingestion/management/commands/ingest.py` exposes exactly one importer,
  `manual_capture`, reading UTF-8 from stdin;
- no eBay, TipidPC, Carousell, or retailer client exists in production code;
- `docs/07_PLANNING.md` §3.4 records this explicitly: *"There is no outbound
  HTTP anywhere in the repository yet"* (true until TASK_031's Telegram
  adapter);
- `docs/08_PLANNING.md` §1.1 records the consequence: alerts were deferred
  *"because automated acquisition is not yet live"*.

This is **not** a Phase 9 blocker, and Phase 9 does not absorb it. Automated
acquisition is gated on a governance step no engineering task can perform:
`SOURCES.md` lists eBay, TipidPC, Carousell, and retailer prices as **UNDER
REVIEW** with `UNVERIFIED` terms, and states *"No `UNVERIFIED` field may be
filled in by an LLM."* `CLAUDE.md` independently holds TipidPC as a permission
candidate only, and Facebook Marketplace as permanently excluded.

The two **APPROVED** sources — `personal_records` and manual paste-a-listing
capture — are both manual and already supported. `personal_records` is
**forward-only**: `docs/01_PLANNING.md` §0.1 records explicitly that it is
*"forward-captured buy/sell records, entered manually … no such backfill
exists or will exist"*, and TASK_007 (`tasks/TASK_007_PERSONAL_RECORDS_TRADE_LOG.md`)
implements it as a dedicated Django admin form that writes directly into
`RawListing`/`Swap` — *"no file, no import, no external format."* There is no
historical 2018-present dataset and no external source file; `SOURCES.md` §2's
own heading (*"My own 2018–present buy/sell records"*) is stale relative to
this already-recorded correction and is not modified in this pass (§3.7 notes
it as planning drift). Deployment is useful today regardless, and is in any
case a prerequisite for roadmap Phase 2, so Phase 9 first is the correct
ordering regardless of when automated ingestion is unblocked.

## 2. Phase goal

Make PriceWatch PH continuously and safely reachable on the public internet,
running its downstream processing and alerting on a schedule, with data that
can be recovered.

**This is not automated market acquisition.** §1.1 establishes that
acquisition remains manual (`personal_records`, `manual_capture`) and is
governance-blocked, not a Phase 9 concern. What Phase 9 makes unattended is
what happens *after* data has entered the system: resolution, pricing, and
alerting on whatever was captured.

Concretely, at the end of Phase 9:

- the application runs under a production WSGI server behind TLS, not
  `runserver`;
- `resolve_listings`, `price_listings`, and `send_deal_alerts` run on a
  schedule without a human at a terminal — acquisition itself remains manual;
- the database and the secrets required to interpret it can be restored, and
  that restore has been *demonstrated*, not merely configured;
- no existing guarantee — Postgres-only, environment-only secrets, immutable
  RawListing, privacy boundaries, at-most-once alerts — is weakened to get
  there.

## 3. Confirmed repository facts

Established by inspection at `9dacf01`, not assumed.

### 3.1 The application is not production-served

`docker-compose.yml` runs `command: python manage.py runserver 0.0.0.0:8000`
and publishes `8000:8000`. `requirements.txt` contains **no** WSGI server —
Django, DRF, whitenoise, psycopg, pytest, pytest-django, PyYAML. `runserver`
is multithreaded by default in Django 5.2 (confirmed against this
repository's installed Django — `runserver --nothreading` is the flag that
*disables* threading, so threaded is the default), auto-reloading, and —
regardless of its threading model — Django's own documentation is explicit
that it is a development convenience, not a production server: it lacks
process management, worker scaling, and the hardening a production WSGI
server provides.

### 3.2 No production security settings exist

`config/settings.py` contains **none** of `SECURE_PROXY_SSL_HEADER`,
`CSRF_TRUSTED_ORIGINS`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
`SECURE_HSTS_SECONDS`, or `SECURE_SSL_REDIRECT`. This matters more here than in
a token-authenticated API: the React frontend is same-origin and
**session + CSRF** authenticated (TASK_026), so cookie and origin handling are
load-bearing for the whole authenticated surface.

`SECRET_KEY`, `SELLER_PSEUDONYM_KEY`, `DEBUG`, and `ALLOWED_HOSTS` already come
from the environment with fail-loudly semantics. That part needs no change.

### 3.3 Statics are already solved — which narrows Caddy's job

TASK_026 §18 settled WhiteNoise as *"same-process WSGI static serving without
adding Caddy or another service"*, with `WhiteNoiseMiddleware` after
`SecurityMiddleware` and `CompressedStaticFilesStorage`. `docker-entrypoint.sh`
already runs `collectstatic --noinput`. The React bundle is served by
`config.views.spa_index` under a regex fallback that excludes `api|admin|auth|static`.

TASK_026 anticipated this phase precisely: *"Phase 9 may later put Caddy and
HTTPS in front without changing the same-origin route contract."*

**Consequence: Caddy's scope is TLS termination and reverse proxy only.** It
does not serve static files, does not own routing, and must not change the
same-origin contract. Any Phase 9 design that moves static serving into Caddy is
re-opening a settled decision without cause.

### 3.4 Deployment migrations are unowned

`docker-entrypoint.sh` runs `collectstatic` and then `exec "$@"`. It does not
migrate — TASK_026 states this deliberately: *"The entrypoint does not migrate,
seed, ingest, price, or schedule work."* That was correct for Phase 6. For a
deployed system, applying migrations at release time becomes a Phase 9
responsibility that no component currently owns.

### 3.5 There is no scheduler

`docker-compose.yml` declares exactly two services, `db` and `web`. There is no
cron container and no crontab, despite `docs/ROADMAP.md`'s architecture naming
*"Scheduler (cron, own container)"*. `docs/07_PLANNING.md` §3.8 recorded the
same gap.

Four commands exist and are candidates for scheduling:
`ingest` (stdin-driven, manual — not schedulable as-is), `resolve_listings`,
`price_listings`, and `send_deal_alerts`.

### 3.6 Phase 7 explicitly deferred concrete items to Phase 9

`docs/07_PLANNING.md` §14 is an authoritative hand-off list. Phase 9 owns: the
cron container, crontab entry and schedule frequency; the real Telegram bot
token and chat id; the real activation timestamp; the real deployed application
URL; enabling alerts in production; operational monitoring of scheduled runs;
and any live smoke test against the real Bot API.

### 3.7 A usable backup is a recovery set, not a single dump

`config/settings.py` documents `SELLER_PSEUDONYM_KEY` as unrotatable and
*"Backup-critical for the life of the database"* — tokens derived from it live
in immutable `RawListing` rows, so a database restored without the original key
silently loses repeat-counterparty linkage. The requirement is a **complete
recovery set**, not a single artifact:

1. the PostgreSQL data must be recoverable;
2. the original `SELLER_PSEUDONYM_KEY` must independently be recoverable;
3. restore verification must demonstrate that restored data remains
   interpretable with that preserved key.

This does **not** mean the key must be physically stored inside or beside the
`pg_dump` output — co-locating a database dump with the key that unlocks its
sensitive content would concentrate risk rather than reduce it. Exactly how
the key is stored and recovered independently of the dump is TASK_037/owner
decision territory (§8), not settled here.

**On `SOURCES.md` §2's file-handling requirement:** that section states *"the
source file itself still holds plaintext names … its storage, access, and
backup handling must be decided before phase 9."* Repository inspection
(§1.1) establishes that no such file exists under the current, already-shipped
TASK_007 design — `personal_records` data is entered through a live admin form
and pseudonymised on write, the same as any other `RawListing` row. That
clause in `SOURCES.md` describes a superseded design and is stale wording
left over from before TASK_007 shipped; it is recorded here as planning
drift, not corrected in this pass (`SOURCES.md` is not in this task's
authorized scope), and it creates **no separate Phase 9 obligation** beyond
the ordinary two-item recovery set above, which already covers every
`RawListing` row including `personal_records`'.

### 3.8 Demo data is already production-safe

`bootstrap_demo_data` is gated behind `PRICEWATCHPH_ENABLE_DEMO_DATA == "1"`,
default off, with no `DEBUG` or hostname heuristic (TASK_027 §4). No Phase 9
work is required to keep it out of production — only the discipline of not
setting the flag. It is called out here so it is a recorded decision rather than
an oversight.

### 3.9 The production image ships test dependencies

The single `requirements.txt` installed into the runtime image includes
`pytest` and `pytest-django`. Minor, but it enlarges the production image and
its dependency surface for no runtime benefit.

## 4. Non-goals

Phase 9 does not own and must not scaffold:

- Kubernetes, Terraform, Ansible, service meshes, or any orchestration beyond
  Docker Compose on one host;
- Redis, Celery, or any broker — forbidden by `CLAUDE.md` regardless;
- observability stacks (Prometheus/Grafana/Sentry/ELK), APM, or log shipping;
- CDN, autoscaling, load balancing, multi-node, or blue-green infrastructure;
- automated ingestion clients, source ToS research, or scraping (§1.1);
- aggregate realised-margin reporting or analytics — still excluded, per
  `docs/08_PLANNING.md` §14;
- README, case study, or test-suite consolidation — that is roadmap Phase 10;
- schema changes, new models, or migrations authored for deployment
  convenience;
- moving static serving into Caddy (§3.3);
- any weakening of Postgres-only, environment-only secrets, immutable
  RawListing, pseudonymisation, privacy boundaries, or at-most-once alert
  semantics.

## 5. Architecture

The target is deliberately small: **one Linux host, one Docker Compose
project.**

```text
            internet
               │  443 / 80
        ┌──────▼───────┐
        │    caddy     │  TLS termination + reverse proxy only
        └──────┬───────┘  (automatic certificate management)
               │  http, private compose network
        ┌──────▼───────┐
        │     web      │  gunicorn → Django (WhiteNoise serves statics)
        └──────┬───────┘  no published host port
               │
        ┌──────▼───────┐        ┌──────────────┐
        │      db      │        │  scheduler   │  cron → manage.py commands
        │ postgres 16  │◄───────┤              │
        └──────┬───────┘        └──────────────┘
               │
        ┌──────▼───────┐
        │   backups    │  pg_dump + verified restore
        └──────────────┘
```

Four services where there are now two. `web` stops publishing a host port —
Caddy becomes the only ingress. The scheduler runs the same image as `web` so
it shares code, settings, and the database, differing only in command.

## 6. Risks

1. **Silent proxy misconfiguration.** If Django does not trust Caddy's
   `X-Forwarded-Proto`, it may build `http://` URLs, mis-set secure cookies, or
   reject CSRF from the HTTPS origin. The failure is often partial and
   authentication-shaped, not an obvious 500.
2. **Duplicate irreversible sends.** The scheduler is the first component that
   can invoke `send_deal_alerts` unattended. TASK_030's unique claim and
   TASK_032's at-most-once orchestration make this safe *per DealFlag*, but an
   overlapping-run or misconfigured-cutoff mistake at first deploy could alert
   on a backlog.
3. **First-deploy alert activation.** `PRICEWATCHPH_ALERT_ACTIVATION_AT` set to
   a past instant would make the first scheduled run alert on every historical
   DealFlag at once. Phase 7 Decision C exists precisely to prevent this; Phase 9
   must set the value correctly.
4. **Backups that cannot be restored.** A `pg_dump` on a timer with no restore
   drill is a false sense of safety, and a database recovered without its
   companion `SELLER_PSEUDONYM_KEY` is unusable for counterparty linkage
   (§3.7) — the two must be recoverable together even though they need not be
   stored together.
5. **Migrations at release.** An unmigrated or half-migrated deploy against a
   live database is a correctness and availability risk.
6. **Secret exposure.** Phase 9 introduces the first real credentials —
   Telegram token, production `SECRET_KEY`, database password, backup
   destination credentials. `CLAUDE.md` requires environment-only, never
   committed.

## 7. Settled decisions

- **Docker Compose on a single host.** The repository is already Compose-shaped
  and single-tenant; nothing in it justifies orchestration.
- **Caddy for TLS + proxy only**, because WhiteNoise already owns statics
  (§3.3). Caddy is chosen over nginx because automatic certificate management
  removes an entire class of manual renewal work, and the roadmap already names
  it.
- **Gunicorn** as the WSGI server — the mainstream, dependency-light choice for
  a synchronous Django app. No ASGI: the codebase is entirely synchronous.
- **The scheduler runs the application image**, not a bespoke one, so scheduled
  commands execute against identical code and settings.
- **In the final architecture, `web` is not published to the host — Caddy is
  the only ingress.** That cutover happens in TASK_035, alongside Caddy's
  introduction (§9); TASK_034 keeps the port published so the runtime task
  stays independently testable before Caddy exists.
- **Alerts remain disabled until deliberately enabled** in production
  (`PRICEWATCHPH_ENABLE_ALERTS=1`), matching the opt-in default.
- **No aggregate reporting**, no README work — those belong to later phases.

## 8. Genuine unknowns — owner decisions

These are **not** inferable from the repository and must not be invented:

1. **Hosting target** — provider, host size, region.
2. **Domain name** and DNS control (needed for `ALLOWED_HOSTS`,
   `CSRF_TRUSTED_ORIGINS`, `PRICEWATCHPH_PUBLIC_BASE_URL`, and certificate
   issuance).
3. **Backup destination and retention** — where dumps go, how long they are
   kept, and how the destination's own credentials are held.
4. **Schedule frequencies** for `resolve_listings`, `price_listings`, and
   `send_deal_alerts`.
5. **Telegram production bot and chat**, and the activation cutoff instant.
6. **Whether a live Telegram smoke test is performed** against the real bot as
   part of deployment validation.

(A "first-party records file handling" decision appeared in an earlier draft
of this plan. §3.7 establishes there is no such file under the shipped
TASK_007 design, so it is not a genuine open decision and is removed rather
than carried forward as an unknown.)

None of these blocks TASK_034 (§9), which is mechanism-only.

## 9. Task breakdown

Five tasks. Each has a clean ownership boundary and can be validated
independently.

### TASK_034 — Production application runtime

**Scope.** Add gunicorn; replace `runserver` in the web service; add the
production security settings of §3.2; own migration application at release;
add restart policy.

**Ingress is deliberately out of scope here.** The web service **keeps
publishing its port**, exactly as it does today under `runserver` — TASK_034
only swaps what serves that port. Direct host exposure is removed in TASK_035,
together with Caddy's introduction, not here. Reasoning: TASK_034 and TASK_035
are sequential (TASK_035 depends on TASK_034), so if TASK_034 removed the
published port before Caddy existed, the application would be **completely
unreachable from the host** for the entire span between the two tasks —
including during TASK_034's own review and manual validation, which needs to
exercise session login, the admin, and the API against the real gunicorn
process. Publishing the port through TASK_034 costs nothing (it is the
repository's current behavior, not a new exposure) and keeps that window
testable; the end architecture is unchanged — Caddy is still the only
production ingress once TASK_035 lands (§5, §7).

HARDEN must leave open, and establish from repository evidence rather than
from this document:

- the exact gunicorn invocation (worker/thread model, count) — no
  host-capacity assumption is made here;
- whether the §3.2 proxy/security settings should be architectural constants
  (fixed by this being "the" production deployment) or environment-configurable
  — this plan does not mandate one environment variable per Django setting;
- the release-migration mechanism, and specifically how it cannot race if the
  container restarts or is scaled to more than one instance;
- how local Compose usability is preserved alongside the new production
  behavior (§8 does not settle host/domain values, so local development must
  keep working without them);
- which `manage.py check --deploy` warnings are contractual blockers for this
  repository versus signals requiring a documented, deliberate decision.

Deferred, not rejected: splitting test dependencies (`pytest`,
`pytest-django`) out of the runtime image (§3.9) is real but minor and has no
production-correctness or security justification found during inspection.
Keeping TASK_034's surface to what running Django safely in production
actually requires; this can be revisited later if evidence justifies it.

**Dependencies.** None. This is the first task and is entirely mechanism —
no domain, host, or credential value is required, only the environment
variables that carry them.

**Risk tier: HIGH.** It changes the externally exposed security boundary
(cookies, CSRF origins, proxy trust) for a session-authenticated application,
and it takes ownership of migration application against a live database. Both
are explicitly non-downgradeable categories.

**Workflow.** HARDEN → frozen tests/contract → owner artifact review →
IMPLEMENT → REVIEW → VALIDATE → COMMIT.

**Gates.** Frozen acceptance tests for the settings contract (proxy header,
trusted origins, secure cookies, HSTS behaviour under both enabled and
disabled TLS configuration); full backend suite, because `config/settings.py`
is imported by every test; `makemigrations --check --dry-run`; `manage.py
check --deploy` as an additional signal.

### TASK_035 — Caddy reverse proxy, HTTPS, and ingress cutover

**Scope.** A `caddy` service, a `Caddyfile`, certificate storage volume, the
proxy contract TASK_034's Django settings expect, **and removing `web`'s
published host port** so Caddy becomes the only ingress. TLS termination and
proxying only — no static serving, no routing changes.

**Dependencies.** TASK_034 (Django must already trust the forwarded protocol
before a proxy is put in front of it, and must already be reachable to prove
Caddy proxies to it correctly before the direct path is removed).

**Risk tier: MEDIUM.** It is the public security boundary, which argues for
HIGH — but the artifact is a small declarative config whose critical property
(real certificate issuance, real TLS) is verifiable only against a live domain,
not in pytest. Frozen-test ceremony would be theatre here. The testable half of
the boundary — that Django trusts the proxy correctly — is TASK_034's, where it
is tested properly.

**Workflow.** Short contract/plan → IMPLEMENT → targeted tests → REVIEW →
COMMIT, with **mandatory manual verification** against a real domain: valid
certificate, HTTP→HTTPS redirect, admin and API reachable, session login works
over TLS, and the web service unreachable except through Caddy.

**Gates.** Targeted config assertions; manual TLS verification; `manage.py
check --deploy`. No full suite — no Python behavior changes.

### TASK_036 — Scheduler

**Scope.** A `scheduler` service running the application image under cron,
invoking `resolve_listings`, `price_listings`, and `send_deal_alerts`. Owns
overlap safety, failure visibility, and the first-run activation-cutoff
sequencing.

**Dependencies.** TASK_034 (shared image and settings).

**Risk tier: HIGH.** This is the first component that can trigger irreversible
outbound sends unattended — explicitly a non-downgradeable category. The
at-most-once guarantee is already enforced in the database, but scheduling is
where backlog-alerting and overlapping-run mistakes would originate.

**Workflow.** HARDEN → frozen tests/contract → owner artifact review →
IMPLEMENT → REVIEW → VALIDATE → COMMIT.

**Gates.** Frozen tests for whatever scheduling behavior is testable in
Python (command wiring, failure/exit-status propagation, and that no scheduled
path bypasses TASK_032's claim); full backend suite; explicit verification that
a first run with a correctly-set activation cutoff alerts on nothing
historical.

### TASK_037 — Backup and verified restore

**Scope.** Scheduled `pg_dump`, a defined retention and destination, an
independent recovery path for `SELLER_PSEUDONYM_KEY` alongside the data it
unlocks (§3.7), and — the substance of the task — a **restore that has
actually been performed and verified**, not merely scripted.

**Dependencies.** TASK_034 (stable runtime and volumes).

**Risk tier: HIGH.** Backup and restore is explicitly non-downgradeable, and a
restore procedure exercises destructive database behavior. A backup believed
good but never restored is worse than none, because it removes urgency.

**Workflow.** HARDEN → frozen tests/contract → owner artifact review →
IMPLEMENT → REVIEW → VALIDATE → COMMIT.

**Gates.** A demonstrated restore into a scratch database, verified by row
counts and by a pseudonymised-linkage spot check proving the restored data is
interpretable with the preserved key; confirmation that no dump or key is
committed; full backend suite unaffected.

### TASK_038 — First-deploy runbook and production validation

**Scope.** The ordered first-deploy procedure (secrets, migrate, collectstatic,
certificate issuance, superuser, activation cutoff, enabling alerts last),
rollback/recovery steps, and the one-time production validation — optionally
including the live Telegram smoke test `docs/07_PLANNING.md` §14 assigns here.

**Dependencies.** TASK_034–037.

**Risk tier: MEDIUM.** The artifact is documentation, which alone would be LOW —
but executing it enables real outbound sends and touches real credentials for
the first time, and getting the sequencing wrong (alerts enabled before the
cutoff is set) has irreversible consequences.

**Workflow.** Short contract/plan → IMPLEMENT → targeted validation → REVIEW →
COMMIT.

**Gates.** The runbook is executed end-to-end at least once; `manage.py check
--deploy` clean in production configuration; alerts confirmed disabled until
deliberately enabled.

## 10. Dependency order

```text
TASK_034 (runtime)
   ├── TASK_035 (Caddy/HTTPS)
   ├── TASK_036 (scheduler)
   └── TASK_037 (backup/restore)
                └── TASK_038 (runbook + validation)
```

TASK_035, 036, and 037 are independent of one another and may be executed in
any order after TASK_034. TASK_038 is last by definition.

## 11. Phase completion criteria

Phase 9 is complete when all of the following hold:

1. the application is publicly reachable over HTTPS with a valid certificate,
   served by gunicorn behind Caddy, with the web service not directly exposed;
2. `manage.py check --deploy` is clean under production configuration;
3. session login, the deal feed, the review queue, the Outcome workflow, and
   the admin all work over TLS;
4. migrations are applied by a defined release step, not by hand;
5. `resolve_listings`, `price_listings`, and `send_deal_alerts` run on a
   schedule without human intervention, and a failed scheduled run is
   visible (acquisition itself remains manual — §1.1, §2);
6. alerts are correctly configured with an activation cutoff that does not
   backfill, and remain opt-in;
7. a database restore has been **performed and verified**, including
   demonstrating that `SELLER_PSEUDONYM_KEY` was independently recovered and
   the restored data remains interpretable with it;
8. no secret is committed, and no prior guarantee (Postgres-only,
   environment-only secrets, immutable RawListing, privacy, at-most-once
   alerts) has been weakened;
9. the full backend suite remains green.

Roadmap Phase 10 (test suite, README, case study) follows. Automated ingestion
(roadmap Phases 1–2) remains a separate track gated on the `SOURCES.md`
governance step described in §1.1.
