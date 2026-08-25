# TASK_037A — Pre-deployment audit remediation

## 1. Objective

Correct the three owner-selected findings from the read-only pre-deployment
audit without changing PriceWatch PH's architecture:

1. custom Django admin authorization boundaries;
2. fail-closed configuration for a public HTTPS origin; and
3. least-privilege PostgreSQL service environment propagation.

This task is inserted between TASK_037 and TASK_038. It does not start,
implement, or amend TASK_038. TASK_038 remains the final Phase 9 deployment
runbook and validation task defined by `docs/09_PLANNING.md`.

## 2. Authority and inspected repository facts

This contract follows `CLAUDE.md`, `docs/09_PLANNING.md`, and the existing
frozen behavior in TASK_007, TASK_028, TASK_034, TASK_035, TASK_036, and
TASK_037. The following facts were verified directly during HARDEN:

- `RawListingAdmin.log_personal_trade_view()` is registered through
  `admin_site.admin_view()`. That wrapper requires an authenticated active
  staff user, but the custom view does not check a RawListing creation
  permission before rendering or writing.
- The ordinary RawListing add/change/delete admin surfaces remain disabled.
  The built-in `ingestion.add_rawlisting` permission already exists and
  exactly describes the custom operation's write class; no new model or
  permission row is required.
- `OutcomeAdmin.untracked_worklist_view()` is also wrapped only by
  `admin_site.admin_view()` and queries `DealFlag` directly.
- The governed outcome service and API read boundary already requires both
  `pricing.view_dealflag` and `outcomes.view_outcome`. The admin worklist is
  another adapter over the same evidence and must not be weaker.
- `PRICEWATCHPH_PUBLIC_BASE_URL` is the existing canonical public origin.
  `DJANGO_BEHIND_HTTPS_PROXY=1` is the existing gate that enables
  `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT`,
  `SESSION_COOKIE_SECURE`, and `CSRF_COOKIE_SECURE` together.
- Local mode deliberately uses an HTTP origin with the proxy gate disabled.
  That behavior remains valid.
- The `db` service currently receives the complete application `.env` through
  `env_file`, including Django, Telegram, and seller-pseudonym secrets that
  PostgreSQL does not need.
- The PostgreSQL image needs only `POSTGRES_DB`, `POSTGRES_USER`, and
  `POSTGRES_PASSWORD` from the PriceWatch PH deployment environment.
- Compose cannot filter selected keys from an `env_file`. Least privilege
  therefore requires removing `db.env_file` and explicitly mapping only the
  three existing PostgreSQL variables. No new secret, environment-variable
  name, dependency, service, or file format is needed.

## 3. Frozen HARDEN artifacts

After owner approval, these two files are frozen and must not change during
implementation:

- `tasks/TASK_037A_PRE_DEPLOYMENT_AUDIT_REMEDIATION.md`
- `tests/test_task_037a_pre_deployment_audit_remediation.py`

If implementation exposes a contradiction in either artifact, stop and
return to the owner. Do not edit a frozen test to make implementation pass.

## 4. Authorized implementation boundary

After owner approval, implementation may modify only:

- `ingestion/admin.py`
- `outcomes/admin.py`
- `config/settings.py`
- `docker-compose.yml`

No model, migration, API, serializer, frontend, template, authentication
backend, account-provisioning flow, dependency, shell script, backup/restore
script, scheduler file, Caddyfile, existing task, existing test, planning
document, `.env.example`, or deployment runbook is authorized.

## 5. Personal-trade admin authorization

Both GET and POST access to
`admin:ingestion_rawlisting_log_personal_trade` require the existing built-in:

```text
ingestion.add_rawlisting
```

The existing active/authenticated/staff requirement supplied by
`admin_site.admin_view()` remains mandatory. A staff user without
`ingestion.add_rawlisting` receives HTTP 403:

- GET does not render the form;
- POST performs no `RawListing` or `Swap` write; and
- the response does not disclose whether submitted data would otherwise have
  been valid.

A staff user with `ingestion.add_rawlisting` retains access to the dedicated
trade form. This permission authorizes only the governed personal-trade side
channel. `RawListingAdmin.has_add_permission()` remains false, so Django's
generic RawListing add form remains unavailable. Change and delete remain
unavailable. No new custom permission or schema migration is introduced.

This task does not redesign trade validation, pseudonymisation, atomic swap
creation, immutability, or the existing redirect/message behavior after an
authorized successful write.

## 6. Outcome worklist authorization

GET access to `admin:outcomes_outcome_untracked` requires both existing
permissions:

```text
pricing.view_dealflag
AND outcomes.view_outcome
```

The conjunction matches `outcome_services.get_outcome_state()` and the DRF
outcome-read boundary. A staff user with neither permission or with only one
of the two receives HTTP 403 before the worklist query is rendered. A staff
user with both retains access.

The five custom outcome mutation views remain governed by their existing
service-layer permissions. This task does not change their lifecycle,
transaction, audit, error, or method behavior.

## 7. Fail-closed public HTTPS configuration

`PRICEWATCHPH_PUBLIC_BASE_URL` remains the canonical same-origin public URL.
When its scheme is `https`, settings initialization must fail with
`django.core.exceptions.ImproperlyConfigured` unless
`DJANGO_BEHIND_HTTPS_PROXY` is the literal string `1`.

The failure occurs before Django serves a request. It prevents an HTTPS Caddy
origin from running while Django leaves proxy recognition, HTTPS redirect,
and Secure session/CSRF cookies disabled.

When the origin is HTTPS and the gate is `1`, the existing four-setting
contract remains exact:

```text
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

An HTTP origin with the gate absent or disabled remains valid for local use.
Only the HTTPS-plus-disabled contradiction fails. This task does not add
`CSRF_TRUSTED_ORIGINS`, HSTS, a second origin variable, domain validation, a
new settings mode, or a new authentication mechanism.

This Django settings contract applies independently of whether TASK_035 has
already integrated Caddy. TASK_035 is the sole authority for Caddy presence
and public-ingress topology; TASK_037A neither requires Caddy to exist nor
creates, modifies, or integrates it. If a `caddy` service is present in the
consolidated source, TASK_037A preserves its least-privilege environment
boundary: it has no `env_file` and receives only
`PRICEWATCHPH_PUBLIC_BASE_URL`. If Caddy is absent, TASK_037A acceptance does
not fail solely because TASK_035 has not yet been integrated.

## 8. Database environment least privilege

The `db` service must not use `env_file`. Its explicit `environment` mapping
contains exactly:

```text
POSTGRES_DB
POSTGRES_USER
POSTGRES_PASSWORD
```

Each value is sourced from the existing same-named Compose variable. The
contract deliberately does not freeze `:?` versus `:-` interpolation syntax:
inactive-service interpolation and successor TASK_037 tooling must remain
safe, while PostgreSQL startup must still fail when its required values are
unusable.

No `DJANGO_*`, `PRICEWATCHPH_*`, Telegram, seller-pseudonym, or other
application secret may enter the `db` service environment. `migrate`, `web`,
and the Phase 9 scheduler remain application services and retain their shared
application environment source. If TASK_035's Caddy service is present, it
retains only its existing public-origin variable. The TASK_037 backup service
remains independently scoped and must not gain an application `env_file`.

No new `PRICEWATCHPH_DB_ENV_FILE`, Docker secret mechanism, service, managed
database, or separate architecture is introduced.

## 9. Compatibility requirements

Implementation must preserve:

- Django session authentication, CSRF, administrator-managed accounts, and no
  public registration;
- every existing API permission boundary;
- RawListing application and PostgreSQL immutability;
- personal-trade validation, pseudonymisation, and transaction behavior;
- Outcome lifecycle and audit behavior;
- local HTTP Compose usability;
- TASK_035's sole authority over Caddy and public ingress, whether or not it is
  integrated at this checkpoint;
- PostgreSQL 16, one-host Docker Compose, and environment-only secrets;
- TASK_036 scheduler environment equality with `web`; and
- TASK_037 inactive-safe backup interpolation, exact-resource restore cleanup,
  and `PRICEWATCHPH_APP_ENV_FILE` support for application services.

## 10. Frozen acceptance criteria

The frozen test module proves:

1. staff without `ingestion.add_rawlisting` receives 403 on both GET and POST
   of the personal-trade view;
2. denied personal-trade POST writes no `RawListing` or `Swap`;
3. staff with `ingestion.add_rawlisting` can use the dedicated form while the
   generic RawListing add surface remains governed by existing behavior;
4. the outcome worklist denies staff missing either required view permission;
5. the outcome worklist permits staff holding both required view permissions;
6. HTTPS public-origin settings initialization fails closed when the proxy
   gate is absent, `0`, or another non-authorizing value;
7. HTTPS plus the literal gate `1` resolves the complete existing secure
   proxy/cookie contract;
8. local HTTP plus a disabled gate remains valid;
9. `db.env_file` is absent and `db.environment` contains exactly the three
   PostgreSQL variables; and
10. application peers retain an application environment source and no new
    dependency, schema, migration, auth redesign, HSTS policy, or TASK_038
    behavior is introduced.

## 11. Expected failing HARDEN baseline

Before implementation, the frozen module must collect normally and fail on
the confirmed current behavior:

- unauthorized personal-trade GET and POST are accepted;
- the outcome worklist accepts staff without its model-view permissions;
- HTTPS settings initialization succeeds with the proxy gate disabled; and
- the database service still receives the complete `.env`.

Passing compatibility cases in the same module prove the red baseline is
specific rather than an import, fixture, or environment failure.

The targeted HARDEN command is:

```text
docker compose run --rm --no-deps -e PYTHONDONTWRITEBYTECODE=1 \
  -v <repository>:/app web \
  pytest -p no:cacheprovider -v \
  tests/test_task_037a_pre_deployment_audit_remediation.py
```

The implementation pass, not HARDEN, owns the full PostgreSQL suite,
`makemigrations --check --dry-run`, Django system checks, Compose validation,
review, and validator gates.

## 12. Risks and owner-review decisions

1. **Personal-trade permission.** This contract selects the existing
   `ingestion.add_rawlisting` permission. A purpose-specific custom permission
   would require model metadata and a migration, expanding scope without
   evidence. Owner approval of this artifact approves the built-in permission
   choice.
2. **Failure timing.** This contract selects fail-loudly settings
   initialization for an HTTPS/proxy contradiction, matching required-secret
   settings. A deploy-check-only warning could be ignored and would not meet
   the requested fail-closed behavior. Owner approval accepts startup failure
   as intentional.
3. **Compose variable source.** Removing `db.env_file` means PostgreSQL values
   must be available to Compose interpolation through the project `.env`, an
   explicit Compose `--env-file`, or the shell environment. The existing
   `PRICEWATCHPH_APP_ENV_FILE` selector continues to apply to application
   services, not `db`, because using it on `db` would reintroduce every
   application secret. The final TASK_038 runbook must document the chosen
   operator invocation; this task does not start or write that runbook.
4. **Integration order.** TASK_035 is staged but uncommitted, while TASK_036
   and TASK_037 are in the separate Phase 9 integration worktree. The eventual
   implementation must be applied to the consolidated Phase 9 source without
   weakening successor contracts. HARDEN does not merge or modify either
   worktree.

No other requirement or owner decision is introduced.

## 13. Stop conditions

Stop and return to the owner if implementation requires a new permission,
model, migration, dependency, authentication backend, environment-variable
name, secret file, service, Caddy change, frontend change, existing frozen
artifact edit, TASK_038 work, or weakening of TASK_036/TASK_037 successor
behavior.
