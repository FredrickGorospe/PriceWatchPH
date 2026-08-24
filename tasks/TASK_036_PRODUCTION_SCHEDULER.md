# TASK_036 - Production scheduler

## 1. Goal

Add one unattended production scheduler service that runs the existing
downstream market-data pipeline in this order:

```text
resolve_listings -> price_listings -> send_deal_alerts
```

The scheduler owns timing, ordering, overlap exclusion, process lifecycle, and
operational output only. The three existing Django management commands remain
the authoritative business operations. TASK_036 adds no ingestion, pricing,
resolution, or alert-delivery business logic.

This is a HIGH-risk task because it is the first component that invokes the
alert command without an operator present. The frozen contract therefore
prioritizes fail-closed command selection, fail-fast stage ordering, visible
failure, and preservation of TASK_032's at-most-once alert semantics.

## 2. Authority and checkpoint

HARDEN was performed in the independent `PriceWatchPH-task036` worktree at:

```text
d780fe9d68f9bb9227a73a4a4d5fea74e8c77cff
TASK_034: add production application runtime
```

TASK_035's uncommitted Caddy work is deliberately absent and is not a
dependency.

Authority inspected for this contract:

- `CLAUDE.md`, especially the fixed cron plus Django-management-command
  architecture, the Postgres-only rule, and the broker prohibition;
- `docs/09_PLANNING.md`, especially Sections 3.5, 5, 6, 7, 8, 9, and 10;
- TASK_034's migration service, application image, and restart contracts;
- TASK_030's immutable, unique `AlertDelivery` claim;
- TASK_031's opt-in alert configuration, activation timestamp, payload, and
  Telegram adapter;
- TASK_032's eligibility, claim-before-send, no-retry/no-resend, command
  output, and exit behavior;
- the production implementations of `resolve_listings`, `price_listings`, and
  `send_deal_alerts`;
- `ingest`, which remains stdin-driven and manual;
- the current `Dockerfile`, `docker-entrypoint.sh`, `docker-compose.yml`,
  `.env.example`, `config/settings.py`, and relevant frozen tests.

No model or schema need was found. A migration would contradict this task.

## 3. Evidence and mechanism choice

### 3.1 Current image facts

The final application image is `python:3.12.13-slim-bookworm`. It contains the
application and its Django commands but does not contain cron. The existing
entrypoint runs `collectstatic` and then `exec "$@"`; it does not schedule or
migrate. TASK_034's peer `migrate` service is the only release-migration owner.

### 3.2 Options considered

**A small timing loop** would avoid installing cron, but it would replace the
repository's explicit cron architecture with custom timing and signal logic.
There is no evidence that this divergence is needed.

**Debian Vixie cron** supports foreground mode, but a direct container
experiment against the exact Bookworm base proved that its jobs do not inherit
an arbitrary environment variable passed to the daemon. Using it would require
copying the Django and Telegram environment into a cron/PAM-specific file.
That is rejected because it duplicates secrets and widens their file surface.

**BusyBox `crond`** is the selected timer. The Bookworm `busybox-static`
package provides `/usr/bin/busybox`; its `crond -f` mode stays in the
foreground and `-L` sends daemon logs to a chosen file. An empirical container
test proved that a cron child receives an arbitrary environment variable from
the container without copying it into the crontab. This preserves the
application environment source shared with `web`.

**Successor integration amendment (TASK_037).** TASK_036 originally froze
TASK_034's literal `env_file: .env` application-environment convention.
TASK_037 later introduced the Compose-only `PRICEWATCHPH_APP_ENV_FILE`
selector for `db`, `migrate`, and `web`. Because `scheduler` is an application
peer of `web`, it must continue sharing the same application environment source
and therefore inherits `${PRICEWATCHPH_APP_ENV_FILE:-.env}`. The default
remains `.env`. This changes no scheduler timing, pipeline, alert, locking, or
process semantics.

BusyBox `crond` alone did not exit inside a three-second Docker stop grace
period when it was PID 1. The Bookworm `tini` package is therefore required.
With `/usr/bin/tini -g -- /usr/bin/busybox crond ...` as PID 1, empirical tests
showed Docker stop completing in approximately 0.11 seconds both while idle
and while a cron-launched Python child was sleeping. Tini reaps children and
forwards signals to the cron process group; BusyBox terminates its active job
when the foreground daemon is terminated.

Primary references checked during HARDEN:

- BusyBox `crond` options: <https://busybox.net/downloads/BusyBox.html>
- Tini signal forwarding and `-g`: <https://github.com/krallin/tini>
- Compose dependency, environment, and restart semantics:
  <https://docs.docker.com/reference/compose-file/services/>
- Debian cron foreground/log behavior:
  <https://manpages.debian.org/bookworm/cron/cron.8.en.html>

### 3.3 Final mechanism

The application image installs only `busybox-static` and `tini` in its final
stage. One root-level `production_scheduler.py` artifact owns both fixed modes:

```text
python /app/production_scheduler.py --serve
python /app/production_scheduler.py --run-pipeline
```

Because this script is launched directly rather than through `manage.py` or
WSGI, it performs the standard fixed Django bootstrap before importing
`django.conf.settings`:

```python
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.conf import settings
```

`DJANGO_SETTINGS_MODULE` is a repository literal, not operator configuration,
and is not added to `.env.example`. `--serve` then reads timing through
`settings.SCHEDULER_CRON`, validates it, writes the root BusyBox crontab, and
replaces itself with Tini plus foreground `crond`. The crontab invokes only the
script's fixed `--run-pipeline` mode. `--run-pipeline` obtains the overlap lock
and invokes the three existing Django commands as child processes.

There is no generic command-runner option and no command name is accepted from
the environment, command line, crontab, or Compose configuration.

## 4. Production file boundary

### HARDEN artifacts frozen now

- `tasks/TASK_036_PRODUCTION_SCHEDULER.md`
- `tests/test_task_036_production_scheduler.py`

### IMPLEMENT production files allowed after owner approval

- `Dockerfile` - install `busybox-static` and `tini` in the final application
  image, with the existing apt cleanup pattern;
- `docker-compose.yml` - add the scheduler service and its lock volume;
- `.env.example` - declare the mandatory schedule setting with a deliberately
  invalid placeholder;
- `config/settings.py` - read the schedule setting so TASK_001's exact
  `.env.example` symmetry remains true;
- `production_scheduler.py` (new) - schedule validation/rendering, foreground
  daemon exec, overlap lock, and fixed ordered command launcher.

No other production file is authorized. In particular, TASK_036 does not
change any existing management command, alert module, model, migration,
frontend file, Caddy file, requirements file, entrypoint, or prior frozen
test. If implementation needs another file, it stops for owner review.

## 5. Compose service contract

`docker-compose.yml` adds exactly one `scheduler` service with these
properties:

- it uses the same `build` contract and resulting application image as `web`;
- it uses the same application environment source as `web`,
  `${PRICEWATCHPH_APP_ENV_FILE:-.env}`, whose default remains `.env`;
- its command is the fixed list form
  `/usr/local/bin/python /app/production_scheduler.py --serve`;
- it has no published port, `expose`, healthcheck, custom network, profile, or
  externally selectable management command;
- it depends on `db: service_healthy` and
  `migrate: service_completed_successfully`;
- it has `restart: unless-stopped`;
- it explicitly receives `TZ=UTC`;
- it requires non-empty `PRICEWATCHPH_SCHEDULER_CRON` through Compose's
  `${VARIABLE:?message}` interpolation, with no default;
- it mounts a dedicated named `scheduler_lock` volume at
  `/run/pricewatchph-scheduler`;
- the same named volume is declared at the Compose top level.

`unless-stopped` is intentional. It restores the timer after a host restart or
daemon crash, while respecting an explicit operator stop. A scheduled job's
nonzero exit does not terminate `crond`, so a business-stage failure does not
create a container restart loop. The next ordinary cadence runs normally.

The migration dependency is mandatory. The scheduler never runs `migrate`
itself and cannot begin before TASK_034's migration service has completed
successfully.

## 6. Schedule configuration

The one setting is:

```text
PRICEWATCHPH_SCHEDULER_CRON
```

Exact production timing remains a deployment decision because the repository
contains no evidence about acquisition volume or desired alert latency. No
frequency is invented in TASK_036.

`.env.example` contains:

```text
PRICEWATCHPH_SCHEDULER_CRON=change_me
```

`change_me` is intentionally invalid. Compose rejects absence/empty input and
the scheduler rejects the placeholder and malformed input before starting
`crond`. `config/settings.py` reads the same key as `SCHEDULER_CRON`, defaulting
to an empty string for non-scheduler application processes. This preserves
TASK_031's repository-wide rule that `config/settings.py` is the sole reader of
`PRICEWATCHPH_SCHEDULER_CRON`. The scheduler script reads the Django setting and
owns its validation. Its only direct `os.environ` operation is the fixed
`DJANGO_SETTINGS_MODULE` bootstrap in Section 3.3; it never obtains the
schedule value from the environment itself.

The accepted timing grammar is intentionally narrower than general cron:

- exactly five whitespace-separated fields;
- minute: `*`, an integer `0..59`, or `*/N` where `N` is `1..59`;
- hour: `*`, an integer `0..23`, or `*/N` where `N` is `1..23`;
- day-of-month, month, and day-of-week: exactly `*`.

This supports every minute, fixed minute within each hour, minute/hour
intervals, and one fixed daily UTC time. Lists, ranges, names, macros,
calendar-specific schedules, extra fields, control characters, comments,
quotes, shell metacharacters, and newlines are rejected. The accepted value is
rendered as timing fields only; it can never add or replace the fixed command.

Invalid input prints a concise setting-name error to stderr and exits nonzero.
It never starts `crond` and never falls back to another cadence.

## 7. Timezone

Scheduler cadence and job-local time are interpreted in UTC. Compose's
`scheduler.environment.TZ=UTC` is the single authoritative timezone mechanism.
HARDEN established that BusyBox cron children inherit the daemon/container
environment. The crontab contains no `TZ` or `CRON_TZ` assignment, because
BusyBox `crond` does not support arbitrary crontab environment assignments.
This does not rely on the base image's incidental timezone.

The choice does not change application bucketing. `price_listings` continues
to select the current calendar day using the existing immutable
`AGGREGATION_TIME_ZONE = "Asia/Manila"` rule, independently of the UTC cadence.
Stored timestamps remain UTC and display timezone remains separate.

## 8. Generated crontab and secrets

`--serve` writes `/var/spool/cron/crontabs/root` with mode `0600`. The directory
is created with owner-only access where the package has not created it. Its
semantic content is:

```text
SHELL=/bin/sh
PATH=/usr/local/bin:/usr/bin:/bin
HOME=/app
<validated timing> /usr/local/bin/python /app/production_scheduler.py --run-pipeline >>/proc/1/fd/1 2>>/proc/1/fd/2
```

Only timing is variable. The command and redirections are literals supplied by
the repository. No setting or environment value other than the validated
timing fields is written.

Telegram credentials, database credentials, Django secrets, activation time,
and all other application configuration remain solely in the scheduler
container environment inherited from the application environment selector
`${PRICEWATCHPH_APP_ENV_FILE:-.env}` shared with `web`; its default remains
`.env`. BusyBox passes that environment to the child. The crontab contains no
secret name or value, and the scheduler does not print environment mappings.

## 9. Process and signal lifecycle

The existing application entrypoint first runs `collectstatic`, then `exec`s
the scheduler command. `production_scheduler.py --serve` validates and writes
the crontab, then uses `os.execv` with absolute executable paths to become:

```text
/usr/bin/tini -g -- /usr/bin/busybox crond -f -l 8 \
  -L /dev/stdout -c /var/spool/cron/crontabs
```

Tini is PID 1. `crond` remains in the foreground. `-g` forwards termination to
the cron process group; the tested Tini/BusyBox combination stops both the
daemon and an active cron child promptly. Tini reaps cron children. No
interactive shell, shell profile, relative executable lookup, or daemonized
orphan is assumed.

The generated job uses absolute Python and script paths. The script uses
`/app` as the subprocess working directory and invokes `/app/manage.py`.
Application environment is inherited unchanged; the script does not construct
an alternate environment.

Failure to create the crontab, locate the fixed binaries, or exec the daemon is
fatal and visible. Compose then applies `unless-stopped`.

## 10. Overlap prevention

`production_scheduler.py --run-pipeline` opens the fixed lock file:

```text
/run/pricewatchph-scheduler/pipeline.lock
```

with owner-only creation permissions and obtains Linux `fcntl.flock` with
`LOCK_EX | LOCK_NB` before launching any stage. The descriptor remains open
for the entire three-stage pipeline. It is released by `finally`/descriptor
close on success or failure, and by the kernel if the process is killed.

The path is on the Compose `scheduler_lock` named volume. This prevents
overlap between cron ticks in one scheduler container and between accidental
same-host scheduler replicas sharing that volume. HARDEN proved the latter
with two disposable containers mounting one named volume: the holder acquired
the lock and the contender's nonblocking call returned `EAGAIN` (`errno 11`).
The proof resources were then removed. The Phase 9 architecture is one Compose
host; cross-host scheduling is out of scope.

If the lock is already held, the second invocation launches no management
command, writes exactly:

```text
Scheduler pipeline skipped: another run is active.
```

to stdout, and exits 0. A normal overlap is an observable no-op, not a business
failure and not something cron should retry.

Any other lock open/acquisition error propagates and exits nonzero. The
scheduler must never continue unlocked.

## 11. Fixed pipeline and ordering

The only child command vectors are, in order:

```text
/usr/local/bin/python /app/manage.py resolve_listings
/usr/local/bin/python /app/manage.py price_listings
/usr/local/bin/python /app/manage.py send_deal_alerts
```

The launcher may use its own `sys.executable` for the first element because it
is entered through `/usr/local/bin/python`; every remaining argument above is
fixed. It uses `subprocess` list arguments with `shell=False`, inherits stdout,
stderr, and environment, and uses `/app` as cwd.

The ordered pipeline is required instead of three independent schedules:

1. resolution must finish before pricing so the pricing worklist sees current
   derived Listing state;
2. pricing must finish before alerts so `send_deal_alerts` sees DealFlags from
   the current pricing pass;
3. resolution failure blocks pricing and alerts;
4. pricing failure blocks alerts;
5. alert failure is the final stage and makes the pipeline nonzero.

No new business transaction spans the commands. Each management command keeps
its existing transaction boundaries and semantics.

The scheduler never invokes `ingest`, `bootstrap_demo_data`, personal capture,
frontend tooling, backups, Caddy, Telegram, or any management command supplied
by an operator. It does not import alert transport/orchestration internals.

## 12. Stage output and failure semantics

Before each stage, stdout receives:

```text
Scheduler stage starting: <command>
```

After a zero exit, stdout receives:

```text
Scheduler stage complete: <command>
```

After a nonzero exit, stderr receives:

```text
Scheduler stage failed: <command> exit_status=<N>
```

The pipeline exits with that stage's status and launches no later stage. There
is no retry inside the run. When all three stages succeed, stdout receives:

```text
Scheduler pipeline complete.
```

All writes are flushed so ordering survives redirected, non-interactive
execution. Each child inherits the same stdout/stderr, preserving existing
command output. In particular, `price_listings` retains its summary and
`send_deal_alerts` retains its disabled/completion summary and `CommandError`
message. The scheduler wrapper prints no listing, seller, URL, token, chat id,
or raw exception body.

The crontab redirects job stdout and stderr to PID 1's corresponding file
descriptors, while `crond` logs to `/dev/stdout`. Stage identity and the exact
nonzero status are therefore visible in `docker compose logs scheduler`.
Cron mail, syslog, and a separate monitoring stack are not assumed.

One failed job does not kill the timer. `crond` stays alive and the next normal
cadence gets a fresh pipeline invocation after the lock is released. There is
no immediate retry or backoff loop.

## 13. Alert safety and first production run

The final stage invokes the unchanged `send_deal_alerts` command with no
arguments. That preserves all TASK_032 behavior:

- disabled alerts print their exact visible no-op and exit 0;
- invalid enabled configuration raises `CommandError` before any claim;
- only DealFlags at or after the existing inclusive activation cutoff are
  eligible;
- each successful payload is claimed before Telegram I/O;
- existing pending, sent, and failed claims are never retried or resent;
- delivery failure is persisted once and produces a nonzero command exit;
- unexpected exceptions propagate and leave the existing diagnosable pending
  claim behavior;
- the scheduler never calls Telegram or queries `AlertDelivery` itself.

Starting the scheduler does not enable alerts and does not select an activation
timestamp. With `PRICEWATCHPH_ENABLE_ALERTS=0`, every scheduled pipeline still
resolves and prices, then the alert stage is the existing successful visible
no-op. Alert credentials may remain unset in that state.

The safe first-deploy sequence is operational, not new code:

1. deploy and migrate with alerts disabled;
2. start the scheduler and verify successful resolve/price plus the disabled
   alert line in scheduler logs;
3. set `PRICEWATCHPH_ALERT_ACTIVATION_AT` to the owner-chosen go-live instant;
4. set valid Telegram token/chat id and public base URL;
5. only then set `PRICEWATCHPH_ENABLE_ALERTS=1` and recreate the affected
   application containers so they receive the environment;
6. verify the first enabled run considers no pre-activation DealFlag.

TASK_036 creates no second cutoff, no inferred "now", and no backfill switch.
The real values and exact cadence remain TASK_038 deployment decisions.

If `send_deal_alerts` reports a delivery failure, the pipeline is nonzero but
the next cadence still runs. TASK_032's durable claim means the failed
DealFlag is skipped permanently; the next run can process only other eligible,
unclaimed flags. The scheduler adds no resend behavior.

## 14. Frozen acceptance tests

`tests/test_task_036_production_scheduler.py` freezes the following behavioral
and security properties:

- scheduler Compose service, application-image reuse, migration/database
  dependencies, restart policy, no ingress, explicit UTC, and lock volume;
- required schedule interpolation with no default, `.env.example`/settings
  symmetry, narrow accepted cadence grammar, and fail-loud invalid input;
- secret-free fixed crontab rendering and fixed `--run-pipeline` command;
- availability of BusyBox and Tini in the built runtime;
- exact three-command order using list argv, no shell, no custom environment,
  and fixed working directory;
- arbitrary command environment values have no effect;
- fail-fast behavior and propagation of the failed stage's status;
- one attempt per stage, no retry/resend flags, and a later ordinary run
  remains possible;
- nonblocking overlap skip before any command plus lock release after failure;
- exact concise wrapper output and child output inheritance;
- no direct Telegram/alert implementation imports and no embedded secret
  identifiers in scheduler artifacts;
- absence of a scheduler model/migration surface.

The tests do not assert comments, YAML key ordering, shell whitespace, an exact
production frequency, or TASK_035 topology.

## 15. IMPLEMENT runtime validation still required

Some container-runtime properties cannot be established hermetically from a
pytest process running inside `web`. IMPLEMENT must additionally prove:

1. a clean application image build installs the two selected packages;
2. `docker compose config` succeeds with a valid schedule and fails for
   absent/empty schedule input;
3. invalid grammar makes the scheduler container fail visibly before `crond`;
4. the generated root crontab is `0600`, contains only fixed non-secret
   settings/command plus validated timing, and contains no environment secret;
5. an actual cron child inherits `TZ=UTC`, observes UTC local time, and receives
   an arbitrary marker from Compose environment without a scheduler-specific
   environment file; neither `TZ` nor `CRON_TZ` appears in the crontab;
6. direct `--serve` startup with no pre-set `DJANGO_SETTINGS_MODULE` installs
   the fixed `config.settings` bootstrap, loads `settings.SCHEDULER_CRON`, and
   reaches schedule validation; Tini is PID 1, BusyBox `crond` is its child in
   foreground mode, and a cron job uses `/app` plus the expected
   Python/manage.py paths;
7. `docker stop` terminates an idle scheduler and an active job cleanly within
   the configured grace period;
8. two forced concurrent pipeline invocations produce one active run and one
   exact overlap no-op, including through the shared named volume;
9. a controlled stage failure appears with stage name/status in
   `docker compose logs scheduler`, blocks later stages, leaves `crond` alive,
   and permits the next cadence;
10. a killed daemon is restored by `unless-stopped`, while an explicit stop is
    respected;
11. alerts-disabled scheduling performs no Telegram request and the first
    enabled smoke uses a fresh activation cutoff with no historical backfill;
12. TASK_032, resolution, and pricing compatibility suites remain green;
13. `makemigrations --check --dry-run` and `manage.py check` remain clean.

No live Telegram request is required unless the owner explicitly authorizes
real deployment credentials during TASK_038.

## 16. Explicit non-goals

No automated ingestion, `ingest`, `bootstrap_demo_data`, seller/personal
capture, frontend operation, backup, Caddy operation, static serving change,
schema, model, migration, Celery, Redis, broker, queue, Kubernetes, systemd,
Airflow, generic workflow framework, monitoring stack, cron mail, retry,
resend, force-send, alert semantic change, second activation setting, schedule
default, custom network, or cross-host scheduler coordination.

## 17. Stop conditions

IMPLEMENT stops and reports rather than improvising if:

- the exact final image cannot provide BusyBox `crond` and Tini as specified;
- cron children do not inherit the Compose application environment;
- Tini cannot stop both the daemon and an active job cleanly;
- the shared file lock does not exclude concurrent same-host invocations;
- schedule validation can be bypassed into extra crontab fields/commands;
- existing commands cannot be invoked unchanged in the frozen order;
- migration ownership must be duplicated;
- alert activation or at-most-once semantics would need to change;
- any model, migration, dependency framework, extra production file, or
  TASK_035 change appears necessary.

## 18. Validation workflow

HARDEN runs only the new red module plus the three focused compatibility
modules:

```text
docker compose exec web pytest -v tests/test_task_036_production_scheduler.py
docker compose exec web pytest -v tests/test_task_032_alert_send_orchestration_and_command.py
docker compose exec web pytest -v listings/tests/test_task_015_operational_resolution.py
docker compose exec web pytest -v pricing/tests/test_task_022_operational_pricing.py
```

No full suite is run during HARDEN. After owner approval the required workflow
remains:

```text
IMPLEMENT -> independent REVIEW -> independent VALIDATE -> COMMIT
```
