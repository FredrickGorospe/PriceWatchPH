# TASK_037B: Administrator login throttling

## 1. Goal and threat model

Reduce automated credential guessing against administrator-managed Django
accounts before public deployment. An unauthenticated internet client can
currently submit unlimited passwords to both password-authentication views:

- `/admin/login/`; and
- `/auth/login/`.

The second route is in scope because it uses the same Django authentication
backend and session as the admin route. Limiting only `/admin/login/` would
leave `/auth/login/` as a direct bypass for guessing a staff account.

The control must slow repeated online guesses from one client address, share
state across Gunicorn workers, survive application-container restarts, avoid
disclosing whether a username exists, and recover automatically. It is not
intended to stop a distributed botnet with a large supply of source addresses
or an attacker who already controls a valid account.

## 2. Inspected repository facts

HARDEN inspected `phase9/integration` at
`160350035f4d8eb1f2f2feb68d39db93ad2575b7`. The worktree was clean.

- The declared runtime is Python 3.12 and `Django>=5.2,<5.3`. The existing
  deployment-style container has Django 5.2.17.
- `config/urls.py` mounts Django's unmodified admin login at `/admin/login/`
  and `django.contrib.auth.views.LoginView` at `/auth/login/`.
- Both routes call Django's normal `authenticate()` flow. There is no custom
  authentication backend, login form, login middleware, registration route,
  MFA, CAPTCHA, or current throttling dependency.
- Django session authentication remains the only DRF authentication method.
- The current middleware is Django's normal security, session, CSRF,
  authentication, messages, and clickjacking stack plus WhiteNoise.
- TASK_034 gates proxy scheme trust, HTTPS redirect, and Secure cookies behind
  `DJANGO_BEHIND_HTTPS_PROXY=1`. With the gate off, local direct HTTP remains
  valid.
- TASK_035 is not integrated. Its approved Caddy contract makes Caddy the
  only public ingress, has no upstream proxy/CDN, and relies on Caddy's default
  behavior of replacing untrusted `X-Forwarded-*` values before proxying.
- TASK_037 provides PostgreSQL backup and verified restore. TASK_037A narrows
  admin permissions and database-service secrets but does not change login.
- The runtime has PostgreSQL 16 and no shared cache. A local-memory cache would
  be isolated per Gunicorn worker and lost on restart.
- Existing tests cover the admin login page, the separate `/auth/login/`
  CSRF/login/logout flow, anonymous redirects to `/admin/login/`, and
  authenticated admin permissions. None covers repeated password failures.

## 3. Design investigation and decision

### 3.1 Django/application layer: selected

Use `django-axes` 8.3 with its PostgreSQL database handler and its supported
`django-ipware` integration. Axes observes Django's authentication signals,
blocks through an authentication backend, and formats lockout responses in
middleware. That places the control at the boundary that knows whether a
password attempt failed or succeeded and covers both repository login views.

As of HARDEN, django-axes 8.3.1 is the current PyPI release, is classified as
production/stable, explicitly supports Django 5.2 and Python 3.12, and tests
Django 5.2 in its upstream matrix:

- https://pypi.org/project/django-axes/8.3.1/
- https://django-axes.readthedocs.io/en/stable/2_installation.html
- https://github.com/jazzband/django-axes/blob/8.3.1/pyproject.toml

The database handler is selected instead of a cache handler. PostgreSQL is
already required, gives all Gunicorn workers one state store, and persists
attempts across application-process and application-container restarts. Axes
uses database transactions, row locking, and database-side increments for
attempt updates. A narrow burst can still overshoot the threshold when new
username rows are created concurrently, but workers do not maintain divergent
or restart-local counters. That residual race is acceptable for this
single-host, low-volume admin surface and must be covered by a later load test
rather than represented as a perfect global request gate.

### 3.2 Caddy/ingress layer: rejected

TASK_035 uses the official Caddy image and the standard `reverse_proxy`
directive. Caddy's standard distribution has no authentication-aware rate
limiter. Adding one would require a custom image/module or an additional
service. Ingress request limiting also cannot distinguish a failed login from
a successful login, reset after success, or naturally share Django's account
and recovery semantics. Its state and restart behavior would depend on the
selected non-standard module. It is the wrong owner for this control.

### 3.3 Home-grown Django counter or database-cache limiter: rejected

A custom model/middleware/backend could implement the same boundary, but it
would duplicate credential-failure signaling, transactional counting,
cool-off cleanup, proxy address parsing, recovery commands, and lockout
responses. `django-ratelimit` would still need a cross-worker cache and custom
login-success reset logic. Redis, Memcached, Celery, and a message broker are
not justified. The maintained package is smaller and safer than a bespoke
security mechanism here.

## 4. Exact protected scope

Throttle password authentication through:

- `admin:login` at `/admin/login/`; and
- `login` at `/auth/login/`.

Axes remains on the Django authentication backend so both routes share the
same counter. There are no other password-authentication endpoints in the
inspected repository. Existing session-authenticated API requests do not
submit passwords and must not consume failure counts. Logout, password change,
authenticated admin pages, authorization failures, and CSRF failures must not
consume failure counts.

Do not set `AXES_ONLY_ADMIN_SITE=True`: that would leave `/auth/login/` as a
credential-guessing bypass.

## 5. Throttling key and denial-of-service tradeoff

Use one lockout dimension:

```python
AXES_LOCKOUT_PARAMETERS = ["ip_address"]
```

IP-only tracking means changing the submitted username does not bypass the
limit and does not reveal whether an account exists. It also avoids a
username-only lockout that any unauthenticated attacker could use to disable a
known administrator account from arbitrary rotating addresses.

The accepted tradeoff is that distinct people behind one NAT address share a
counter. PriceWatch PH is a single-host application with administrator-managed
accounts and no public registration, so that availability cost is lower than
the account-lockout risk of an IP-or-username rule. Distinct client addresses,
including IPv4 and IPv6 addresses, remain independent. Distributed guessing
from many addresses is residual risk and is not a reason to add account
lockout, CAPTCHA, Redis, or a Caddy plugin in this task.

## 6. Failure threshold, window, reset, and response

Use the following fixed production policy:

```python
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_USE_ATTEMPT_EXPIRATION = True
AXES_RESET_ON_SUCCESS = True
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = False
AXES_HTTP_RESPONSE_CODE = 429
AXES_COOLOFF_MESSAGE = "Too many login attempts. Please try again later."
```

The first four invalid attempts from an address receive the login view's
normal generic invalid-credential response. The fifth invalid attempt reaches
the limit and receives HTTP 429 with the generic body above. Further attempts
from that address receive the same response until the 15-minute cool-off
expires or an operator resets the address. Attempts made while already
throttled do not extend the cool-off, limiting attacker-triggered denial of
service. Stable django-axes 8.3.1 does not emit a `Retry-After` header; this
task does not add a custom response hook solely to manufacture one.

A successful password login before lockout clears failed attempts for that
source address. Once an address is locked, valid credentials are also blocked
until cool-off or operator reset; accepting a password while throttled would
make the control bypassable. A successful login by any administrator-managed
account on an address resets that IP-only counter. This is a deliberate
consequence of choosing IP-only rather than account lockout.

The 5-attempt, 15-minute policy is the maintained package's documented
rolling-window example and is conservative for this low-volume administrator
surface. No owner-supplied traffic baseline exists, but the choice has a
stronger basis than an invented project-specific number and automatic
recovery bounds its availability cost. No further owner decision is required
for HARDEN approval.

The 429 body is identical for existing, nonexistent, staff, and non-staff
usernames and must not echo the submitted username. Existing Django forms
must retain their generic invalid-credential behavior below the threshold.

## 7. Client address trust

Install Axes with its supported `ipware` extra. Client-IP lookup is coupled to
the existing `BEHIND_HTTPS_PROXY` setting derived from
`DJANGO_BEHIND_HTTPS_PROXY`:

```python
AXES_IPWARE_PROXY_ORDER = "left-most"
AXES_IPWARE_PROXY_COUNT = 0
AXES_IPWARE_META_PRECEDENCE_ORDER = (
    ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")
    if BEHIND_HTTPS_PROXY
    else ("REMOTE_ADDR",)
)
```

`AXES_IPWARE_PROXY_COUNT = 0` is intentional. In TASK_035's direct-Caddy
topology, Caddy is the socket peer and writes the client as the single value in
`X-Forwarded-For`; Caddy itself is not another value in that header. An
isolated HARDEN check against django-axes 8.3.1, django-ipware 7.0.1, and
python-ipware 3.0.0 confirmed that a count of 1 rejects that valid single-value
header, while a count of 0 resolves both IPv4 and IPv6 values. The header is
trusted only when the existing proxy gate is enabled.

Before TASK_035 is integrated, the normal local setting keeps the gate off.
Axes therefore uses only `REMOTE_ADDR`, ignores client-supplied
`X-Forwarded-For`, and works over plain HTTP. After TASK_035, Caddy is the only
public path to Gunicorn and its documented defaults ignore incoming spoofed
`X-Forwarded-For`, `X-Forwarded-Proto`, and `X-Forwarded-Host` values and set
trusted values for the upstream:

- https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#defaults
- https://django-axes.readthedocs.io/en/stable/4_configuration.html#configuring-reverse-proxies

If a CDN, load balancer, second reverse proxy, untrusted Compose-network peer,
or direct public Gunicorn route is later introduced, this trust and count must
be redesigned before deployment. TASK_037B does not change Caddy or Gunicorn.

## 8. Persistence, workers, restart, and recovery

Explicitly use:

```python
AXES_HANDLER = "axes.handlers.database.AxesDatabaseHandler"
AXES_DISABLE_ACCESS_LOG = True
AXES_ENABLE_ACCESS_FAILURE_LOG = False
AXES_ENABLE_ADMIN = False
AXES_SENSITIVE_PARAMETERS = ["username", "ip_address"]
```

Only active failure state needed for throttling is stored. Successful access
logs, permanent per-failure logs, and the Axes admin UI are disabled to reduce
retained authentication metadata and avoid expanding the admin surface. Axes
must continue masking usernames, IP fields, and passwords in the bounded
request data attached to active attempt rows. PostgreSQL state is shared by all
Gunicorn workers and survives `web` restart/recreation. It also falls under
TASK_037's existing whole-database backup and restore without script changes.
Restoring an older database can restore then-valid throttle rows; the
15-minute expiry and operator reset make that bounded.

The database handler adds reads and a small transactional write to each failed
password attempt. A large distributed attack can therefore consume database
capacity and create rows even though each individual address is throttled.
This task is brute-force hardening, not volumetric DDoS protection. For the
project's expected low-volume admin surface, the shared and restart-persistent
correctness is worth that cost. Monitoring changes are outside this task.

Legitimate recovery is automatic after 15 minutes. An operator with command
access can recover sooner with:

```text
python manage.py axes_reset_ip <client-ip>
```

The operator must use the address Axes recorded. This command deletes only
matching throttle attempts. It does not reset passwords, unlock a username,
create an account, change permissions, or require direct database editing.

## 9. Dependency and migration contract

Add one direct requirement using the repository's next-major ceiling style:

```text
django-axes[ipware]>=8.3.1,<9
```

At HARDEN time this resolves django-axes 8.3.1, django-ipware 7.0.1, and
python-ipware 3.0.0. The extra is the upstream-supported client-IP integration.

Adding `axes` to `INSTALLED_APPS` introduces third-party Axes migrations and
PostgreSQL tables. No PriceWatch PH model or local migration file is allowed.
The existing one-shot `migrate` service applies the third-party migrations
before `web` starts. The application database role must retain its existing
ability to read and update those tables. No cache, Redis, new service, new
volume, or Docker topology change is required.

## 10. Frozen HARDEN artifacts and later implementation boundary

These files are frozen after owner approval and must not be changed during
implementation:

- `tasks/TASK_037B_ADMIN_LOGIN_THROTTLING.md`
- `tests/test_task_037b_admin_login_throttling.py`

Later implementation may modify only these production files:

- `requirements.txt`
- `config/settings.py`

The settings change must add `axes` to `INSTALLED_APPS`, place
`axes.backends.AxesStandaloneBackend` before Django's existing
`ModelBackend`, append `axes.middleware.AxesMiddleware` as the last
middleware, and configure the exact policy in this contract.

Stop and return to the owner if implementation requires a PriceWatch PH model
or migration, custom authentication backend, custom login view/form/template,
new Python module, environment variable, Caddy or Compose edit, Dockerfile
edit, API/frontend edit, account-provisioning change, or modification to any
existing frozen task/test.

## 11. Compatibility requirements and non-goals

Implementation must preserve:

- PostgreSQL 16, Python 3.12, Django 5.2, and session authentication;
- administrator-managed accounts and no public registration;
- existing CSRF, permission, active-user, staff-user, and superuser semantics;
- TASK_037A's custom admin permissions and database secret isolation;
- TASK_034's local HTTP and security-setting gate;
- TASK_035's staged Caddy topology and header contract without integrating it;
- TASK_036 scheduler behavior and TASK_037 backup/restore behavior;
- frontend, API authentication/permissions, RawListing immutability, and
  existing authenticated admin behavior.

Explicit non-goals are MFA, CAPTCHA, password-policy redesign, account
provisioning, public signup, username-based account lockout, HSTS, Caddy rate
limiting, distributed-botnet prevention, Redis, Celery, a message broker,
TASK_038, TASK_035 integration, and frontend redesign.

## 12. Frozen acceptance criteria

The frozen tests prove meaningful behavior:

1. the maintained dependency and exact application integration are present;
2. four invalid attempts behave normally and the fifth returns generic HTTP
   429;
3. changing usernames and alternating between `/admin/login/` and
   `/auth/login/` does not bypass the IP counter;
4. successful authentication below the limit resets that address's failures;
5. a throttled response is identical for an existing and nonexistent user;
6. distinct client addresses are not coupled;
7. direct/local HTTP ignores spoofed forwarded addresses and still throttles;
8. proxy mode distinguishes trusted Caddy-forwarded IPv4 and IPv6 clients;
9. the operator reset command restores access for one throttled address; and
10. authenticated admin access, session authentication, and the absence of a
    signup route remain unchanged.

The tests intentionally do not assert Axes private model structure, log text,
HTML styling, middleware implementation internals, or Caddy configuration.

## 13. Expected failing HARDEN baseline

Before implementation, the module collects normally. Configuration and
dependency assertions fail because Axes is absent. Behavioral cases fail
because the fifth and later invalid requests still return the normal HTTP 200
login form instead of HTTP 429, username changes and the second login route
bypass no counter, and no reset command exists. Compatibility-only cases can
pass, demonstrating that the red baseline is specific to missing throttling.

The targeted baseline command is:

```text
docker compose run --rm --no-deps -e PYTHONDONTWRITEBYTECODE=1 \
  -v <repository>:/app web \
  pytest -p no:cacheprovider -v \
  tests/test_task_037b_admin_login_throttling.py
```

## 14. Implementation validation plan

After owner approval and implementation:

1. run the frozen TASK_037B module;
2. run relevant TASK_023, TASK_026, TASK_034, TASK_035 when integrated, and
   TASK_037A authentication/deployment compatibility tests;
3. run `python manage.py check` and `python manage.py check --deploy` under
   local and proxy-gated settings; only the already accepted HSTS warning may
   remain in the production-like deploy check;
4. run `python manage.py makemigrations --check --dry-run` and confirm no
   PriceWatch PH migration is generated;
5. run the full PostgreSQL test suite;
6. exercise concurrent invalid attempts through at least two Gunicorn workers
   and confirm shared database state converges on a lockout, documenting any
   bounded threshold overshoot;
7. after TASK_035 is integrated, verify on the live domain that Caddy-forwarded
   IPv4/IPv6 addresses are distinguished and forged inbound forwarded headers
   cannot rotate the throttle key; and
8. finish with the repository-required commands from the root:

```text
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
```

TASK_037B is not complete until all applicable gates are clean. It does not
claim the finding is closed during HARDEN.
