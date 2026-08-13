# TASK_034 — Production application runtime

## 1. Goal

Replace `runserver` with a real WSGI server, give migration application at
release a defined and race-safe mechanism, set an explicit Compose restart
policy, and introduce the narrowest production-security settings contract
this repository actually needs — without assuming Caddy, a real domain, or a
certificate exist yet.

This is the first of five Phase 9 tasks (`docs/09_PLANNING.md` §9–§10) and has
no dependency on the other four. It is mechanism-only: no hosting provider,
domain, real credential, or HSTS duration is chosen here (§8 below records
those as owner decisions still open).

**Correction pass note.** This revision corrects four confirmed defects found
during owner review of the first HARDEN pass: a false claim that Compose
`pre_start` init containers don't exist (§3.5, §7); an inconsistent restart
policy that would let `web` auto-restart while `db` stays down (§8); a frozen
test that would fail against a literal, correct implementation of this very
spec (§6, §11); and a proxy-trust analysis that covered only Django's layer
while ignoring Gunicorn's own forwarded-header trust (§5.1). Nothing in the
Scope, the security-settings shape, or the "keep the port published, HSTS
stays off, no `CSRF_TRUSTED_ORIGINS`" decisions changed — those were accepted
in the first pass and are preserved unless a section below says otherwise.

## 2. Authority and dependencies

- `CLAUDE.md` — Postgres 16 only, no Celery/Redis/broker, environment-only
  secrets, Django 5.2/DRF, no framework substitution;
- `docs/09_PLANNING.md` (committed at `fd1081c`), owner-approved — §3 (facts),
  §5 (architecture), §7 (settled decisions), §8 (owner unknowns — none block
  this task), §9 TASK_034 (scope and the five things HARDEN must establish
  from evidence rather than from that document);
- TASK_001's frozen `.env.example` ↔ `config/settings.py` symmetry test
  (`tests/test_task_001_bootstrap.py`), which any new environment variable
  must satisfy;
- TASK_026's WhiteNoise/same-origin static-serving contract
  (`tests/test_task_026_react_review_workflow_and_same_origin_integration.py`),
  which this task must not disturb;
- repository inspection at `fd1081c`: `docker-compose.yml`, `Dockerfile`,
  `docker-entrypoint.sh`, `requirements.txt`, `config/settings.py`,
  `config/wsgi.py`, `.env.example`;
- installed-engine and installed-package evidence gathered directly during
  this correction pass: `docker compose version` → `5.3.1`; `gunicorn`
  `26.0.0` (`pip show`/`gunicorn.config` inspected directly — see §3.4, §5.1).

### 2.1 Boundary with TASK_035

TASK_035 owns Caddy, certificate issuance, and removing the web service's
published host port. TASK_034 deliberately keeps that port published —
exactly as it is today under `runserver` — so the runtime this task
introduces stays reachable and independently testable (session login, admin,
API) before Caddy exists. TASK_034 introduces the *mechanism* a
Caddy-fronted deployment will need (§6) but ships it switched off, so
TASK_035 activates it with one environment change rather than reopening this
task's Django security-settings model. §5.1 pins Gunicorn's current
forwarded-header allowlist explicitly and records the independent trust
assumptions TASK_035 must satisfy once Caddy becomes the only path to
Gunicorn.

## 3. Verified external/framework contracts

Checked during HARDEN and this correction pass rather than recalled;
installed-package behavior and direct empirical experiments take precedence
over documentation prose, and documentation is re-verified rather than
trusted from memory or from a prior draft of this file.

### 3.1 Django 5.2 — `SECURE_PROXY_SSL_HEADER`

Docs: *"You should **only** set this setting if you control your proxy or
have some other guarantee that it sets/strips this header appropriately... If
you aren't careful, it's easy to introduce a security hole."* Default `None`.
When `None`, `request.is_secure()` is decided solely by whether the request
itself arrived over `https://` — a client-supplied `X-Forwarded-Proto` header
is inert **at the Django layer**. §5.1 covers the separate Gunicorn layer,
which decides `wsgi.url_scheme` — the value Django's own check is built on
top of — before Django ever runs.

### 3.2 Django 5.2 — `CSRF_TRUSTED_ORIGINS`

Docs: a list of trusted **origins** for unsafe cross-origin requests; needed
when the frontend origin differs from the API origin. This repository's
frontend is the same Django process serving the same origin (TASK_026); the
CSRF middleware's same-origin check compares the request's own
`scheme + Host` against the browser's `Origin`/`Referer`, which already
match for same-origin requests with no trusted-origins list. The setting
exists for the case this repository does not have. Default `[]`.

### 3.3 `manage.py check --deploy` — live baseline at `fd1081c`

```
security.W004  SECURE_HSTS_SECONDS not set
security.W008  SECURE_SSL_REDIRECT not set to True
security.W012  SESSION_COOKIE_SECURE not set to True
security.W016  CSRF_COOKIE_SECURE not set to True
```
No warning is raised for `SECURE_PROXY_SSL_HEADER` or `CSRF_TRUSTED_ORIGINS`
being absent — Django does not treat either absence as a deploy-check
defect, consistent with §3.1–3.2.

### 3.4 Gunicorn 26.0.0 — worker defaults (read from installed `gunicorn.config`)

- `workers` default: `1`. Docs describe a *"generally in the `2-4 x
  $(NUM_CORES)`"* range as a starting point, and note the setting's own
  built-in fallback: *"the value of the `WEB_CONCURRENCY` environment
  variable... If it is not defined, the default is 1."* No CPU/RAM figure for
  the eventual host exists anywhere in this repository or its planning docs
  (`docs/09_PLANNING.md` §8.1 lists hosting target as an open owner
  decision).
- `worker_class` default: `sync`. Adequate for this codebase — entirely
  synchronous Django/DRF, no ASGI, no long-lived connections.
- `threads` default: `1`; only takes effect under the `gthread` worker class.

### 3.5 Docker Compose 5.3.1 — migration-release mechanisms, re-verified

The first HARDEN pass asserted that Compose lifecycle hooks other than
`post_start`/`pre_stop` "do not exist." **That claim was false** and is
withdrawn. Verified directly against the current official reference
(`docs.docker.com/reference/compose-file/services/#pre_start`) and against
the installed `5.3.1` engine itself (schema acceptance + live behavior,
`docker compose config` and `docker compose up`, in a disposable
non-PriceWatchPH scratch project — no PriceWatchPH container, volume, or data
was touched):

> *"`pre_start` defines a sequence of init containers to run before the
> service container is started. Each step runs to completion, in declared
> order, and the service container only starts once every step has exited
> `0`. A non-zero exit fails the bring-up of the service and its
> dependents."* ... *"each `pre_start` step runs in its own ephemeral
> container, created after the service container is created but before it is
> started."* ... *"`per_replica: false`: Whether the step runs once for the
> service as a whole before any replica starts."* ... *"A `pre_start` step
> that has already succeeded for its current definition is not re-run on a
> subsequent `up`, nor when the service container restarts under its
> `restart` policy. A step runs again when its definition changes, when the
> previous run did not succeed, or when the service is recreated."*

The reference page's own example is `command: ["./manage.py", "migrate"]` —
this is an explicitly anticipated use.

`service_completed_successfully` (the peer one-shot service pattern used by
the previous HARDEN draft) remains equally real and current: *"specifies that
a dependency is expected to run to successful completion before starting a
dependent service."*

**Both mechanisms are real, current, and supported by the installed engine.**
§7 compares them against this repository's actual needs rather than assuming
either wins, backed by the empirical experiments below.

## 4. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_034_PRODUCTION_APPLICATION_RUNTIME.md` (this file)
- `tests/test_task_034_production_application_runtime.py`

### IMPLEMENT files allowed — after owner approval

- `docker-compose.yml` — `web.command`, `web.restart`, `web.depends_on`,
  `db.restart`; a new `migrate` service
- `requirements.txt` — one new line, `gunicorn`
- `config/settings.py` — `BEHIND_HTTPS_PROXY` and the four settings it gates
  (§6)
- `.env.example` — one new key, `DJANGO_BEHIND_HTTPS_PROXY`

Not authorized: `Dockerfile`, `docker-entrypoint.sh` (unchanged — no
`runserver` reference exists there today, and the `migrate` service reuses
the existing `collectstatic && exec "$@"` entrypoint as-is), any model, any
migration, any frontend file, `Caddyfile` or any Caddy artifact (TASK_035),
any previously frozen test module, `CLAUDE.md`, `docs/01_PLANNING.md`.

## 5. Gunicorn invocation — settled

```
command: gunicorn config.wsgi:application --bind 0.0.0.0:8000 --forwarded-allow-ips=127.0.0.1,::1
```

No `--workers` or `--threads` flag. Per §3.4, gunicorn's own default (`1`, or
`WEB_CONCURRENCY` if an operator later sets it in the real deployment's
environment) already does exactly what this task needs before a hosting
target exists: it does not pretend to know host capacity. `WEB_CONCURRENCY`
is gunicorn's own environment convention, read by gunicorn itself, never by
`config/settings.py` — it therefore adds **no** entry to `.env.example`
(TASK_001's symmetry test only scans `settings.py`) and is not a new
PriceWatch PH environment variable. **TASK_038 must set `WEB_CONCURRENCY` (or
an explicit `--workers`/`--threads` value) once the real host's CPU count is
known, and verify it under load** — that tuning has no evidence to rest on
today and is not invented here.

The published port (`8000:8000`) and bind address are unchanged from the
current `runserver` configuration; TASK_034 only swaps what serves the port
(§2.1).

### 5.1 Gunicorn's own forwarded-header trust — independent of Django's

Django's `SECURE_PROXY_SSL_HEADER` (§3.1) is not the only forwarded-scheme
trust configuration in the request path. Gunicorn independently decides
`wsgi.url_scheme` using its own settings, read directly from the installed
`gunicorn.config` module:

- `forwarded_allow_ips`, default `"127.0.0.1,::1"` (or the `FORWARDED_ALLOW_IPS`
  environment variable if set — gunicorn reads it itself, not through Django
  settings). *"Set to `*` to disable checking of front-end IPs."*
- `secure_scheme_headers`, default
  `{"X-FORWARDED-PROTOCOL": "ssl", "X-FORWARDED-PROTO": "https", "X-FORWARDED-SSL": "on"}`.
- Gunicorn's own docs warning: a header is only honored *"if the source IP is
  permitted by `forwarded_allow_ips`... **and** at least one request header
  matches"* — confirmed directly in `gunicorn/http/message.py`
  (`_peer_trusted_for_forwarded`): an untrusted peer address causes the
  secure-scheme headers to be ignored outright, before Django ever runs.

Gunicorn also reads `FORWARDED_ALLOW_IPS` from the environment when the
command line does not override it. Leaving this security-sensitive property
to both a package default and the absence of an operator override is not a
frozen production contract. TASK_034 therefore explicitly pins the analyzed
loopback-only value on the command line:

```
--forwarded-allow-ips=127.0.0.1,::1
```

Gunicorn's command-line setting takes precedence over its configuration
defaults and the environment-derived fallback, so this allowlist is
repository-controlled. TASK_034 does not set `FORWARDED_ALLOW_IPS` and does
not pin `secure_scheme_headers`; no evidence requires changing the latter.
The current topology was verified empirically:

```
docker run -d --rm --name pwph-nat-test -p 18000:8000 \
  -v "$PWD/debugapp.py:/tmp/debugapp.py" python:3.12.13-slim-bookworm \
  sh -c "pip install --quiet gunicorn==26.0.0 && \
         python -m gunicorn --bind 0.0.0.0:8000 debugapp:application --chdir /tmp"
# debugapp.py's application() returns wsgi.url_scheme and REMOTE_ADDR as plain text.

curl -s http://localhost:18000/                                   # scheme=http  remote_addr=192.168.65.1
curl -s -H "X-Forwarded-Proto: https" http://localhost:18000/     # scheme=http  remote_addr=192.168.65.1
```

A request sent from the real host machine, through the exact `-p
HOST:CONTAINER` publish mechanism `web` uses today, arrives at Gunicorn with
a peer address that is **Docker's own gateway/NAT address, never
`127.0.0.1`/`::1`.** Gunicorn's explicit allowlist therefore ignores the
spoofed `X-Forwarded-Proto: https` header unconditionally — not because of
the header value itself, but because this deployment's network topology never
presents a source address the configured allowlist trusts. The same
experiment repeated from a sibling container on the Compose network (rather
than the true host machine) gave the identical result
(`remote_addr=172.18.0.4`, `scheme=http` in both cases).

During TASK_034, Gunicorn's layer trusts forwarded scheme headers only from
the explicit loopback allowlist, which the published-port path does not
present, and Django's layer is off (`BEHIND_HTTPS_PROXY` defaults `False`,
§6). Neither layer can be spoofed into producing a false positive through
the current external path.

**Explicit non-goal:** `--forwarded-allow-ips=*` is not added. Gunicorn's own
documentation is explicit that this is unsafe unless *"you have ensured via
other means that only your authorized front-ends can access Gunicorn"* — true
once TASK_035 removes the published port and Caddy becomes the only path to
Gunicorn, not true today.

**Handoff to TASK_035.** Gunicorn has its own forwarded-header trust
configuration. Django's `SECURE_PROXY_SSL_HEADER` independently trusts the
configured request header; it does not delegate that decision to Gunicorn or
assume Gunicorn already validated the header. TASK_035 must ensure the final
Caddy topology satisfies both trust assumptions. In particular, Caddy must
strip any client-supplied `X-Forwarded-Proto` header and set its own value,
and Gunicorn must be reachable only through appropriately trusted internal
paths before `DJANGO_BEHIND_HTTPS_PROXY` is activated. The exact Caddy-facing
allowlist/topology decision belongs to TASK_035 and is not designed here.

## 6. Production security settings — settled

One new environment variable, one new settings gate:

| Environment variable | Django setting | Default |
|---|---|---|
| `DJANGO_BEHIND_HTTPS_PROXY` | `BEHIND_HTTPS_PROXY` | `"0"` → `False` |

Literal `"1"` enables it — matching `ENABLE_DEMO_DATA`/`ENABLE_ALERTS`'s
existing convention (no `DEBUG` or hostname heuristic). `DJANGO_` prefix
because this is a Django-core proxy/security concern, not an app feature flag
(matching `DJANGO_ALLOWED_HOSTS`/`DJANGO_DEBUG`, as opposed to the
`PRICEWATCHPH_` prefix TASK_031 used for app features).

```python
BEHIND_HTTPS_PROXY = os.environ.get("DJANGO_BEHIND_HTTPS_PROXY", "0") == "1"

if BEHIND_HTTPS_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
```

**`BEHIND_HTTPS_PROXY` itself is always defined** (a plain module-level
assignment, never conditional) — only the four settings it gates are
conditional. This matters for the frozen test's correctness (§11): when the
flag is `False`, those four names are simply **absent** from
`config/settings.py`'s module namespace, not present-and-equal-to-Django's-
default. A literal, correct implementation of the code above must not be
required to also restate `SECURE_PROXY_SSL_HEADER = None` etc. just to
satisfy a test — Django's own settings loader (`django.conf.Settings`)
already resolves an absent name to the real global default, and the frozen
test proves the *resolved* behavior that way rather than asserting the
module defines names it has no reason to define (§11).

`.env.example` ships `DJANGO_BEHIND_HTTPS_PROXY=0` — disabled, so local and
current Compose usage keeps working over plain HTTP with no domain, proxy, or
certificate, exactly as today (§9 local-compatibility requirement).

**Why these four, together, gated by one flag:** all four only make sense
once a real, controlling, header-stripping proxy exists (§3.1, §5.1).
Shipping them individually enabled today, before TASK_035, would either break
TASK_034's own direct-HTTP testability (`SECURE_SSL_REDIRECT`) or silently
break session login over plain HTTP (`SESSION_COOKIE_SECURE`/
`CSRF_COOKIE_SECURE` cookies would never be sent back by the browser). Gating
them together means TASK_035 activates the whole contract with one
environment change instead of four, and can never activate a partial,
inconsistent subset.

**Why `CSRF_TRUSTED_ORIGINS` is not introduced:** §3.2 — this repository has
no cross-origin topology for it to protect. Adding it would be inventory
theatre, not a real requirement, and `docs/09_PLANNING.md` §9 explicitly warns
against freezing it "just because it appeared in the Phase 9 inventory."

**Why `SECURE_HSTS_SECONDS` is not introduced, not even gated:** HSTS is
browser-cached and, unlike the other three, cannot be cleanly undone by
flipping a flag back — a client that has cached an HSTS max-age will keep
refusing plain HTTP for that long regardless of server-side changes. Setting
any positive duration before TLS exists and has been verified live would be
irreversible-in-practice on a mistake, and no duration has authority behind
it anywhere in this repository's planning documents. `SECURE_HSTS_SECONDS`
stays at Django's default (`0`, disabled) through TASK_034. Enabling it, with
a duration justified once a real certificate is live, is TASK_035/TASK_038's
decision, per `docs/09_PLANNING.md` §9's own framing of this exact choice.

### 6.1 The proxy-trust hazard, addressed at both layers

TASK_034's web service keeps its host port directly published (§2.1) with no
proxy in front of it yet. Two independent layers were checked, not one:

- **Gunicorn** (§5.1): its own `forwarded_allow_ips` default only trusts
  `127.0.0.1`/`::1`; TASK_034 pins that same allowlist explicitly, and
  empirically, no request arriving through the published port topology ever
  presents that peer address.
- **Django** (§3.1, this section): with `BEHIND_HTTPS_PROXY` at its default
  `False`, `SECURE_PROXY_SSL_HEADER` stays `None`, and the frozen test
  `test_direct_client_cannot_spoof_forwarded_proto_while_flag_is_disabled`
  proves a client-supplied `X-Forwarded-Proto: https` header over a plain
  connection is not treated as secure at this layer either.

Gunicorn and Django enforce independent trust configurations. TASK_034's
current external path cannot satisfy Gunicorn's explicit loopback allowlist,
while Django's header trust remains off. TASK_035 must make its final Caddy
topology satisfy both layers before activating
`DJANGO_BEHIND_HTTPS_PROXY=1`, matching Django's own precondition for the
setting (§3.1).

## 7. Migration release mechanism — settled

### 7.1 Mechanisms compared against this repository, not assumed

Both real, current Compose 5.3.1 mechanisms (§3.5) were evaluated against
this repository's actual and near-future needs — including TASK_036's
scheduler, which `docs/09_PLANNING.md` §5 already names as a future consumer
of the same application image and the same migrated schema.

| Property | `web.pre_start` | peer `migrate` service |
|---|---|---|
| Blocks dependent(s) on failure | Yes | Yes |
| Skips a genuine no-op re-run | Yes (documented + reproduced) | Yes (reproduced — see §7.2) |
| Reruns when the image changes | Yes (reproduced — §7.2) | Yes (reproduced — §7.2) |
| Survives an ordinary `restart` untouched | Yes (documented + reproduced) | Yes (reproduced — §7.2) |
| Handles a scaled/multi-replica service | Yes, natively (`per_replica: false`) | Yes, reproduced for cold scale-up (§7.2); reruns (safely, idempotently) when `up` must recreate any individual replica |
| Failed run's actual output is recoverable afterward | **No** — ephemeral hook container, destroyed on exit, not streamed by `docker compose up`/`logs` (reproduced — §7.2) | **Yes** — ordinary container, retained on exit, streamed live and via `docker compose logs migrate` (reproduced — §7.2) |
| Independently addressable by a second, future service (TASK_036's scheduler) | **No** — scoped to the one service that declares it; a second consumer would need its own duplicate `pre_start` block, reintroducing multiple independent components each deciding to run `migrate` | **Yes** — any sibling service depends on the same named service via `depends_on: migrate: condition: service_completed_successfully`, with no duplicated invocation |

The two properties that actually decide this, in order:

1. **Operator visibility/debuggability.** A failed migration under `pre_start`
   surfaces only as `service "web" pre_start[0] exited with code 7` on the
   CLI at the moment of `up` — the actual Django error/traceback is not
   recoverable, because the hook's container is ephemeral and destroyed
   immediately (confirmed twice: once via `docker logs <name>` on the
   just-exited hook container returning "No such container", and once by
   grepping `docker compose up`'s own captured output for the hook's own
   `echo` text, which never appears). The peer service keeps a normal,
   inspectable, `docker compose logs migrate`-recoverable container. For a
   single-operator project with no separate log aggregation
   (`docs/09_PLANNING.md` §4 excludes observability stacks), this is the
   only debugging surface a failed release has, and it must not be
   ephemeral.
2. **TASK_036's scheduler is a second, future dependent on the same
   precondition.** `docs/09_PLANNING.md` §5 and §9 (TASK_036) both describe
   the scheduler as running the same application image against the same
   database, invoking `resolve_listings`/`price_listings`/`send_deal_alerts`
   — all of which need the schema already migrated. A peer `migrate` service
   is a single, independently-addressable node both `web` today and
   `scheduler` tomorrow can depend on without either one owning or
   duplicating the migration invocation. `pre_start` cannot be shared this
   way without copying the same step onto a second service, which
   reintroduces the exact multiple-independent-migration-attempts risk this
   design exists to avoid — not hypothetically, but as two components each
   independently deciding "no prior success recorded, I'll run it" on first
   deploy.

`pre_start`'s genuine advantages — no separate service definition to keep in
sync with `web`'s image/env/volumes, and a native `per_replica: false` flag
for the scale-out case — are real but do not outweigh the two points above
for this repository. The peer service is kept.

### 7.2 Empirical verification (disposable scratch project, no PriceWatchPH container/volume/data touched)

All experiments used a throwaway `docker-compose.yml` under a scratch
directory, built from `alpine:3.20`, exercised with the installed `5.3.1`
engine, and torn down (`docker compose down -v`, `docker rmi`) after each run.

**Peer service reruns on a genuine image change, not on a no-op `up`:**
```
# release 1: build image (script echoes MIGRATE-V1 to a bind-mounted file), up -d
#   -> migrate container runs once, out.log: "MIGRATE-V1"
# same image, no rebuild, `docker compose up -d` again
#   -> migrate NOT recreated ("Container ... Running" for web; migrate untouched); out.log unchanged
# rebuild with new script content (MIGRATE-V2-NEW-MIGRATION), `docker compose up -d`
#   -> migrate IS recreated and reruns; out.log gains "MIGRATE-V2-NEW-MIGRATION"
```

**Ordinary restart does not touch it:**
```
docker compose restart web
# -> out.log unchanged; `docker compose ps -a` shows the migrate container's
#    Exited timestamp unchanged
```

**Cold multi-replica scale-up runs it exactly once:**
```
docker compose up -d --scale web=3
# -> exactly one migrate run before all three web replicas start; out.log
#    gains exactly one line
```

**Recovering one crashed replica reruns it (safely):**
```
docker kill <one-web-replica>
docker compose up -d --scale web=3
# -> migrate reran (a second line appended). Empirically, `migrate` reruns
#    whenever `docker compose up` needs to (re)create or (re)start any
#    container that depends on it — not narrowly "only on image change." It
#    does not rerun for the narrower `docker compose restart <service>`
#    command, which never touches other services. Every observed rerun is a
#    safe no-op: `manage.py migrate --noinput` against an already-current
#    schema does nothing.
```

**Failure surfaces and is debuggable (the deciding property, §7.1):**
```
# migrate command: "echo MIGRATE-FAILING-OUTPUT; exit 7"
docker compose up
# -> "migrate-1 | MIGRATE-FAILING-OUTPUT" streamed live; container retained
#    as Exited (7); `docker compose logs migrate` recovers the output
#    afterward. web never starts ("Container ... Created", never "Started").
# The equivalent pre_start failure produced only a bare
#    `service "web" pre_start[0] exited with code 7` line — the hook's own
#    "PRE-START-FAILING" output never appeared anywhere, and the hook
#    container ("admiring_swanson") was already destroyed
#    (`docker logs admiring_swanson` -> "No such container").
```

### 7.3 Settled shape

```yaml
migrate:
  build: .
  env_file:
    - .env
  depends_on:
    db:
      condition: service_healthy
  restart: "no"
  command: python manage.py migrate --noinput

web:
  build: .
  env_file:
    - .env
  depends_on:
    db:
      condition: service_healthy
    migrate:
      condition: service_completed_successfully
  ports:
    - "8000:8000"
  restart: unless-stopped
  command: gunicorn config.wsgi:application --bind 0.0.0.0:8000 --forwarded-allow-ips=127.0.0.1,::1
```

`migrate` reuses the existing `docker-entrypoint.sh` (`collectstatic
--noinput && exec "$@"`) unchanged — it collects static files it will never
serve, which costs a couple of seconds and touches nothing shared, in
exchange for not inventing a second entrypoint script for one command.

### 7.4 The exact release procedure that guarantees a new migration runs

**`docker compose build && docker compose up -d`** (equivalently, the
single-command form `docker compose up -d --build`). §7.2 proves this
precisely: rebuilding produces a new image, and `docker compose up`
recreates and reruns `migrate` whenever the image it would use has changed —
this was reproduced directly, not assumed. A bare `docker compose up -d`
against an *already-built, unchanged* image does not (and structurally
cannot) apply a migration that doesn't exist in that image yet — a release
is, by definition, a new image, so the build step is not optional tooling
advice, it is the mechanism.

**Semantics, by scenario (all reproduced in §7.2 except the first, which
follows directly from `depends_on` + `condition: service_healthy` already in
this file today):**

- **First deployment.** `db` becomes healthy → `migrate` runs `migrate
  --noinput` against an empty/base schema and exits `0` → `web` starts.
- **Ordinary web restart** (crash, `unless-stopped` recovery, or a manual
  `docker compose restart web`). Reproduced: this does not invoke `migrate`
  at all. No second, uncontrolled migration path is created by an ordinary
  restart.
- **Failed migration.** `migrate` exits non-zero. `service_completed_successfully`
  is not satisfied, so `web` is never created — reproduced: the release
  fails closed, and the failure's own output remains inspectable via
  `docker compose logs migrate` (§7.2), unlike the alternative mechanism.
- **Repeated deployment** (`docker compose build && up -d` after a code
  change). Reproduced: `migrate` reruns and applies whatever new migrations
  exist; Django's `migrate` is idempotent over already-applied migrations.
- **A no-op repeated release** (`up -d` with nothing changed). Reproduced:
  `migrate` is not touched at all.
- **A future second (or scaled) `web` instance.** Reproduced for a cold
  3-replica scale-up: `migrate` runs exactly once before any replica starts.
  Recovering one individually crashed replica later reruns `migrate` again
  (§7.2) — safely, since the command is idempotent; migrations are never run
  from inside a `web` container itself, so scaling or recovering `web`
  replicas cannot create *concurrent* `migrate` invocations racing each
  other, only sequential, idempotent reruns gated by the same
  `service_completed_successfully` condition.
- **TASK_036's future scheduler.** Can depend on the same named `migrate`
  service (`depends_on: migrate: condition: service_completed_successfully`)
  exactly as `web` does, with no duplicated migration invocation — the
  reason `pre_start` was not chosen (§7.1).
- **Web startup against an unapplied schema.** Structurally impossible while
  the `depends_on: migrate: condition: service_completed_successfully` gate
  holds — `web`'s container is never created until `migrate` has exited `0`.

No migration file is authored by this task; the mechanism only decides *when*
`migrate` runs, never *what* it applies.

## 8. Restart policy — settled

- **`web`: `unless-stopped`.** Restarts after a crash. Across a
  container-engine/host restart: if `web` was running (not deliberately
  stopped) when the engine went down, it comes back; if an operator had
  explicitly stopped it first, it stays stopped. `always` would resurrect it
  even in the latter case — verified against Docker's own restart-policy
  documentation: *"Always restart the container if it stops. If it's
  manually stopped, it's restarted only when Docker daemon restarts or the
  container itself is manually restarted"* (i.e. `always` does **not**
  fight an in-the-moment `docker compose stop` either — the two policies
  only diverge at the next daemon/host restart, not immediately after a
  manual stop). `unless-stopped` is the one that keeps a deliberately-stopped
  `web` stopped across that restart, matching "a single-host public
  application that should come back on its own, without overriding an
  operator's explicit stop."
- **`db`: `unless-stopped`, in scope for this task.** The first HARDEN draft
  left `db` at Compose's default (`"no"` — never restarts automatically),
  which was inconsistent with `web`'s own restart rationale: after a
  host/container-engine restart, `web` would attempt to come back while its
  database stayed down, defeating the reason `web` has a restart policy at
  all. `docs/09_PLANNING.md` does not name a separate task that owns `db`'s
  restart policy, and the host-restart goal that motivates `web`'s policy
  applies identically to `db` — there is no repository evidence for treating
  them differently. `db`'s restart policy is corrected to `unless-stopped`
  as part of this task's minimum single-host production runtime.
- **`migrate`: `"no"`, explicit.** A one-shot release step must not retry
  itself silently; a failed migration should surface as a stopped, inspectable
  container (§7.2) an operator investigates, not loop `on-failure`.

Regardless of restart policy, `docker compose down` always removes containers
outright — no restart policy overrides an explicit teardown.

## 9. Local development compatibility

With `.env.example`'s shipped default (`DJANGO_BEHIND_HTTPS_PROXY=0`),
`docker compose up` from a fresh clone needs no domain, no Caddy, and no
certificate: `web` serves plain HTTP on `localhost:8000` exactly as it does
today, and the only observable behavior change is that migrations are now
applied automatically by the `migrate` service instead of requiring a manual
`docker compose exec web python manage.py migrate`.

## 10. Explicit non-goals

Caddy, certificate issuance, removing the published host port, and adapting
Gunicorn's explicit forwarded-header trust to the final Caddy-fronted
topology (TASK_035, §5.1); cron/scheduler (TASK_036); backups/restore (TASK_037); production
Telegram credential values, hosting provider/domain selection, real HSTS
duration (owner/TASK_038); frontend changes; any schema change or migration
authored for deployment convenience; splitting `pytest`/`pytest-django` out
of the production image (`docs/09_PLANNING.md` §3.9 — real but minor,
deferred, no security or correctness justification found); picking a
concrete `--workers`/`WEB_CONCURRENCY` value (§5); `manage.py check
--deploy` "zero warnings" as a goal in itself — §3.3's four warnings are
expected and accepted at this task's boundary (no TLS exists yet to make any
of them safe to silence) rather than chased to zero.

## 11. Acceptance criteria — frozen

The authoritative artifact is
`tests/test_task_034_production_application_runtime.py`. It freezes, at
minimum:

**Runtime** — `runserver` appears nowhere in `docker-compose.yml`,
`Dockerfile`, or `docker-entrypoint.sh`; `web.command` runs `gunicorn` against
`config.wsgi:application` bound to `0.0.0.0:8000`; no `--workers`/`--threads`
flag is pinned; the published port `8000:8000` is preserved;
`requirements.txt` declares `gunicorn>=26.0.0,<27`; gunicorn can actually load
`config.wsgi:application` via `--check-config`.

**Gunicorn forwarded-header trust** — the compose `web.command` explicitly
sets `--forwarded-allow-ips=127.0.0.1,::1`, so neither Gunicorn's package
default nor an operator-supplied `FORWARDED_ALLOW_IPS` value controls the
allowlist; wildcard trust is absent and `secure_scheme_headers` remains
unpinned. A live, loopback-only Gunicorn subprocess runs with the same
explicit option and proves a request from the configured trusted peer has its
forwarded header honored, without asserting anything about this repository's
specific untrusted-peer topology (that is the empirical, non-pytest evidence
in §5.1).

**Migration release** — a `migrate` service exists, builds the same image as
`web`, runs `manage.py migrate --noinput`, depends on `db` being healthy, and
does not restart; `web` depends on both `db` (`service_healthy`) and
`migrate` (`service_completed_successfully`); no new migration file is
introduced (`makemigrations --check --dry-run` stays clean).

**Restart policy** — `web` and `db` are both `unless-stopped`; `migrate` is
`"no"`.

**Security settings** — `BEHIND_HTTPS_PROXY` defaults `False` and only the
literal `"1"` enables it; with the flag disabled, Django's *resolved*
`SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`,
and `CSRF_COOKIE_SECURE` settings — resolved via Django's own settings
loader, not by asserting `config/settings.py` restates each Django default
as a module attribute (§6) — equal Django's real defaults; with the flag
enabled, all four activate together; a client-supplied
`X-Forwarded-Proto: https` header is not trusted by Django's layer while
disabled and is trusted once the underlying Django setting is active;
`CSRF_TRUSTED_ORIGINS` and `SECURE_HSTS_SECONDS` are not introduced by this
task at all (absent from `config/settings.py`'s source, left at Django
defaults).

The frozen test removes the four conditionally-defined security-setting
names from `config.settings.__dict__` before every environment-sensitive
`importlib.reload()` and again during fixture teardown after restoring the
environment. This accounts for Python reload retaining a module dictionary
and makes enabled/disabled settings cases order-independent without forcing
production settings to restate Django defaults.

**Environment symmetry** — `.env.example` documents
`DJANGO_BEHIND_HTTPS_PROXY=0`; TASK_001's general bidirectional symmetry test
continues to pass.

**Compatibility** — WhiteNoise middleware ordering and the staticfiles
storage backend (TASK_026) are undisturbed; every configured database engine
remains `django.db.backends.postgresql`.

## 12. Validation

HARDEN baseline (implementation absent — failures expected):

```
docker compose exec web pytest -v tests/test_task_034_production_application_runtime.py
```

Also run at HARDEN time, unchanged and clean:

```
docker compose exec web pytest -v tests/test_task_001_bootstrap.py tests/test_task_005_settings.py tests/test_task_026_react_review_workflow_and_same_origin_integration.py
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py check
```

After implementation:

```
docker compose exec web pytest -v tests/test_task_034_production_application_runtime.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py check --deploy
```

A full backend run is justified after implementation: this task modifies
`config/settings.py`, which every test imports.

## 13. Stop conditions

Implementation stops and reports rather than improvising if: the installed
Compose engine does not actually honor `service_completed_successfully` or
the empirical reruns documented in §7.2 the way this file describes; gunicorn
cannot load `config.wsgi:application` for a reason unrelated to missing
production configuration; satisfying the four gated security settings
requires touching `CSRF_TRUSTED_ORIGINS` or a positive `SECURE_HSTS_SECONDS`
after all; preserving local Compose usability turns out to require a second
environment variable beyond `DJANGO_BEHIND_HTTPS_PROXY`; or Gunicorn's
explicit loopback-only `forwarded_allow_ips` turns out, on the actual target
host's Docker configuration, to present a trusted peer address for externally-arriving
traffic (e.g. a non-default network driver or `network_mode: host`) —
§5.1's safety argument is topology-specific and must be re-checked if the
container networking model changes.

## 14. Genuine remaining ambiguities

None material to TASK_034 itself. The three deliberately deferred,
evidence-backed decisions — the real `WEB_CONCURRENCY`/worker count (§5), the
real HSTS duration (§6), and the Caddy-facing adaptation of Gunicorn's
explicit `forwarded_allow_ips` (§5.1) — are owner/TASK_038 and TASK_035/038 decisions respectively,
not gaps in this task's contract.
