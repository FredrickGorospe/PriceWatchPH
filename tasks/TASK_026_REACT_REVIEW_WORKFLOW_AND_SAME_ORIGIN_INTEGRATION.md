# TASK_026 - Add the React review workflow and same-origin integration

## 1. Objective

Complete Phase 6 by adding the dedicated Listing-review read projection, the
React review and correction workflow, Django session/CSRF entry points, and one
same-origin serving boundary for the built React application, Django admin,
authentication, static files, and the existing DRF API.

TASK_026 consumes the TASK_025 mutation services and endpoints without
reinterpreting them. It adds no pricing, resolution, ingestion, or schema
behavior.

## 2. Authority and current state

This task follows:

- `CLAUDE.md`, `docs/ROADMAP.md`, and `docs/06_PLANNING.md`;
- TASK_016 through TASK_018 review and alias behavior;
- TASK_023's session-authenticated derived read API;
- TASK_024's React deal/SKU experience and frozen frontend toolchain; and
- TASK_025's shared review services and operation-oriented mutation API.

TASK_023 through TASK_025 remain authoritative. TASK_026 may add the narrow
read, frontend, authentication, and serving behavior below but may not weaken
or replace an existing contract.

## 3. Frozen artifacts and implementation boundary

### 3.1 HARDEN artifacts

After owner approval these files are frozen:

- `tasks/TASK_026_REACT_REVIEW_WORKFLOW_AND_SAME_ORIGIN_INTEGRATION.md`;
- `tests/test_task_026_react_review_workflow_and_same_origin_integration.py`;
  and
- `frontend/src/__tests__/task_026_react_review_workflow_and_same_origin_integration.test.tsx`.

They must not be edited during implementation. A contradiction stops the task
for owner correction.

### 3.2 Authorized IMPLEMENT files

Implementation may create or modify only:

- `requirements.txt`;
- `.dockerignore`;
- `Dockerfile`;
- `docker-entrypoint.sh`;
- `config/settings.py`;
- `config/urls.py`;
- `config/views.py`;
- `api/serializers.py`;
- `api/views.py`;
- `api/urls.py`;
- `templates/registration/login.html`;
- `frontend/vite.config.ts`; and
- `frontend/src/**`, excluding both frozen frontend acceptance tests.

No model, migration, admin, review service, resolver, pricing service,
management command, ingestion, outcome, dependency lockfile, prior task/test,
or planning file is authorized. The existing frontend dependency graph and
`package-lock.json` remain unchanged.

## 4. Owned scope

TASK_026 owns only:

1. the review queue and review detail read API;
2. a constrained search on the existing SKU list;
3. the React review, confirmation, correction, and alias opt-in workflow;
4. same-origin CSRF acquisition and unsafe request headers;
5. mounted Django login and logout;
6. the built React bundle, collected static files, and admin static assets;
7. SPA fallback with protected Django namespaces; and
8. final integrated Phase 6 regression coverage.

## 5. Explicit non-goals

TASK_026 does not add or change:

- Listing resolution, pricing, scoring, PricePoint, or DealFlag behavior;
- ingestion, sources, scheduling, alerts, outcomes, or realised margins;
- SKU creation or generic catalogue, Listing, alias, or RawListing CRUD;
- seller, payload, or generic RawListing exposure;
- fuzzy suggestions, automatic ranking, bulk review, undo, or browser-side
  normalization authority;
- client-side authoritative Decimal, pricing, or state-transition logic;
- JWT, token authentication, local-storage credentials, CORS, or CSRF
  exemptions;
- public anonymous evidence access;
- frontend preferences, favourites, dismissals, or a custom audit model;
- Caddy, HTTPS, backups, cloud deployment, or Phase 7+ work; or
- synthetic production data or ingestion work to populate empty screens.

Facebook Marketplace remains permanently excluded.

## 6. Review read API routes

Add exactly these safe read routes under the existing `api-v1` namespace:

| Name | Method | Path | Purpose |
| --- | --- | --- | --- |
| `api-v1:review-listing-list` | GET | `/api/v1/reviews/listings/` | Unresolved review queue |
| `api-v1:review-listing-detail` | GET | `/api/v1/reviews/listings/<pk>/` | Review evidence for any existing Listing |

The existing TASK_025 mutation routes remain unchanged:

```text
POST /api/v1/reviews/listings/<pk>/mark-reviewed-unresolved/
POST /api/v1/reviews/listings/<pk>/confirm-sku/
```

The list and detail routes are GET-only. They do not create a generic
RawListing, Listing, SKU, or alias endpoint.

## 7. Review read permissions

Both review reads require:

```text
authenticated
AND active
AND staff
AND listings.change_listing
```

No `view_listing`, `view_rawlisting`, `view_source`, `view_sku`, or custom
review permission is required. TASK_026 intentionally uses the stricter
`listings.change_listing` requirement for this product-facing React review API
because every reader of this evidence surface is an operator authorized to
make review decisions. This does not change the earlier Phase 4 Django-admin
contract that distinguishes queue viewing from mutation/correction. SKU search
remains independently gated by the existing `catalogue.view_sku` permission.

Anonymous, inactive, non-staff, and permission-missing requests return 403.
An authorized missing review detail returns exactly:

```json
{
  "code": "listing_not_found",
  "detail": "Listing not found."
}
```

with HTTP 404.

## 8. Queue predicate, ordering, and pagination

The queue predicate is exactly:

```text
Listing.sku IS NULL
AND Listing.reviewed_unresolved_at IS NULL
```

Do not filter by resolution method. Historical fuzzy rows and integrity states
such as a null-SKU `exact_alias` or `human_confirmed` row remain visible with
their persisted method and confidence so a human can repair them.

Ordering is oldest evidence first:

```text
COALESCE(RawListing.occurred_at, RawListing.fetched_at) ASC,
Listing.pk ASC
```

The list uses the existing fixed page-number pagination:

```text
page parameter: page
page size: 25
client-selectable page size: none
```

Its envelope remains `count`, `next`, `previous`, and `results`. An empty queue
returns HTTP 200 with an empty page.

## 9. Review evidence representation

Each list result and detail response has exactly:

```text
id
raw_evidence
derived_listing
current_sku
```

`id` is the Listing primary key.

### 9.1 Raw evidence

`raw_evidence` has exactly:

```text
raw_title
normalised_title
raw_price_text
source
url
occurred_at
fetched_at
```

`normalised_title` is computed read-only with the committed
`listings.normalisation.normalise_title(raw_title)` function. `source` has
exactly:

```text
id
name
```

It does not expose Source base URL, terms, rate limit, or health state.

The projection never exposes RawListing primary key, `raw_price`, seller,
payload, external ID, or a mutable RawListing operation.

### 9.2 Derived Listing evidence

`derived_listing` has exactly:

```text
price
condition
location
resolution_method
resolution_confidence
resolved_at
reviewed_unresolved_at
observed_at
price_kind
trade_side
```

Decimal values remain strings at model precision. Nullable persisted facts
remain JSON null. Timestamps are UTC ISO-8601 instants with `Z` and are never
converted to Manila in the API.

### 9.3 Current curated SKU

`current_sku` is null when the Listing has no SKU. Otherwise it has exactly:

```text
id
brand
model
variant
category
```

The detail route is valid for any existing Listing, including an already
confirmed Listing. That is the read surface for explicit corrections. Queue
membership remains narrower and is not changed by detail access.

## 10. SKU selection contract

The existing paginated `GET /api/v1/skus/` route remains the SKU-choice source.
TASK_026 adds one optional query parameter rather than a new endpoint:

```text
q=<search text>
```

When omitted, TASK_023 behavior and ordering are unchanged. When present:

- leading and trailing whitespace is removed;
- the remaining query must contain 2 through 100 characters;
- matching is case-insensitive substring matching against `brand`, `model`,
  or `variant`;
- results retain canonical `brand`, `model`, `variant`, `id` ordering; and
- the existing 25-row page envelope and `catalogue.view_sku` permission apply.

An invalid present query returns HTTP 400 with a `q` field error. Search does
not rank, suggest, create, mutate, or inspect aliases.

The React selector does not load the whole catalogue. It submits an explicit
search, presents paginated results, and records the selected existing SKU ID.

## 11. CSRF bootstrap contract

Add exactly:

| Name | Method | Path |
| --- | --- | --- |
| `api-v1:session-csrf` | GET | `/api/v1/session/csrf/` |

The endpoint is available without authentication because a Django CSRF token
is not authorization and is useful before login. It returns exactly:

```json
{"csrf_token": "<Django masked CSRF token>"}
```

It calls Django's supported token mechanism, sets/refreshed the same-origin
`csrftoken` cookie, uses `Cache-Control: no-store`, and supports GET only. It
does not expose a session identifier, credential, secret, user profile, or
permission list.

The endpoint is not CSRF-exempt. With Django CSRF enforcement active, an
unsafe POST without a valid CSRF token is rejected with HTTP 403 before method
dispatch. An unsafe POST carrying a valid token reaches this GET-only view and
returns HTTP 405.

The React review workflow obtains a fresh token on entry before enabling an
unsafe action. A logout action obtains one on demand when no in-memory token is
available. Tokens remain in memory only. They are not hardcoded or written to
localStorage or sessionStorage.

Every unsafe fetch uses:

```text
credentials: same-origin
Content-Type: application/json
X-CSRFToken: <bootstrap token>
```

Mutation bodies remain the exact TASK_025 JSON shapes. A 403 clears protected
review evidence and the in-memory token and shows the combined session/access
state; a later retry must bootstrap again.

## 12. Django login and logout

Add server-owned routes:

```text
GET|POST /auth/login/   name=login
POST     /auth/logout/  name=logout
```

`/auth/login/` uses Django's `LoginView` and a minimal server-rendered
`registration/login.html` template. It includes Django CSRF protection, the
standard username/password form, visible errors, and a hidden safe `next`
value when supplied.

Successful login redirects to a same-origin `next` path when Django accepts it;
otherwise it redirects to `/deals`. External `next` URLs are never followed.

`/auth/logout/` uses Django's POST-only `LogoutView`, remains CSRF-protected,
and redirects to `/auth/login/`. GET returns 405. React posts to it with the
same CSRF header contract and then navigates the browser to `/auth/login/`.

The React access-required state links primarily to:

```text
/auth/login/?next=<current React product path>
```

TASK_024's frozen deal/SKU 403 test still requires its existing secondary
`Django admin sign-in` link to `/admin/login/`. That compatibility link remains,
but users no longer depend on admin because the mounted product login is the
primary sign-in route.

## 13. React routes and navigation

Preserve TASK_024 routes and add:

```text
/reviews             unresolved review queue
/reviews/:listingId  review evidence and decision page
```

The singular `/review` remains an in-app not-found path, preserving the frozen
TASK_024 assertion. Primary navigation adds `Review`. Deal cards add a focused
link to `/reviews/<listing.id>` so an already-resolved deal Listing can be
confirmed again or corrected. No general all-Listings collection is added.

Unknown product paths still render the React in-app not-found experience.

## 14. React review queue

`/reviews` loads the first review page and preserves server order. It displays
each result with visibly separate regions labelled:

- `Raw source evidence`;
- `Derived listing state`; and
- `Current curated SKU`.

Queue cards show only fields from the frozen review projection. Seller and
payload never appear. Each card links to `/reviews/<id>`.

Pagination follows API-provided same-origin links only when their path remains
`/api/v1/reviews/listings/`. Previous/next replace the page rather than append
or reorder it. The UI sends no `page_size` or client ordering.

States are distinct:

- `Loading review queue...`;
- `No listings are waiting for review.`;
- access/session required on 403;
- retryable `Review queue could not be loaded.` for server/network/malformed
  responses; and
- ordinary page navigation without retained stale evidence after a 403.

Empty state controls never invoke resolution, ingestion, or pricing.

## 15. Review detail and SKU choice UX

`/reviews/:listingId` displays the same three evidence regions and adds a
fourth region labelled `Curated SKU choice`.

The SKU chooser:

- displays the current SKU honestly when present;
- has a labelled search field and explicit search button;
- does not search until at least two non-whitespace characters are submitted;
- consumes only the existing paginated SKU list with `q`;
- permits selecting exactly one existing SKU; and
- does not create SKUs, inspect aliases, or infer suggestions.

An already-confirmed Listing may be reconfirmed to the current SKU or corrected
to a different result. An unresolved Listing requires a selected SKU before
confirmation.

The optional checkbox is initially unchecked and is labelled to make clear that
it requests an exact alias from the immutable raw title. Alias text is displayed
but not editable. The browser sends only `sku_id` and `create_alias`; it never
sends alias text or normalized text.

## 16. Mutation integration and success behavior

The UI calls the exact TASK_025 endpoints and does not reproduce eligibility,
locking, alias, audit, or transition rules.

### 16.1 Mark reviewed unresolved

The action is presented only for a null-SKU row whose displayed persisted
method is `unresolved` or historical `fuzzy_match`. The request body is exactly
`{}`. This display guard improves UX only; the service remains authoritative.

Success shows `Listing marked reviewed unresolved.` and returns to `/reviews`,
which reloads the queue.

### 16.2 Confirm or correct SKU

The request body is exactly:

```json
{
  "sku_id": 17,
  "create_alias": false
}
```

Success shows `SKU confirmed.` when alias status is `not_requested`,
`SKU confirmed and exact alias created.` for `created`, or
`SKU confirmed; the exact alias already existed.` for `already_exists`, then
returns to and reloads `/reviews`.

## 17. Frontend error behavior

The UI interprets operation responses without inventing domain outcomes:

- 400 `invalid_request`: show field-keyed validation feedback and preserve the
  current evidence and choice;
- 403: clear protected evidence/token and show `Access required` with the
  product login link and permission guidance;
- 404 `listing_not_found`: show `Review listing not found.`;
- 404 `sku_not_found`: show `Selected SKU no longer exists.`, clear that
  selection, and permit a new search;
- 409 `ineligible_review_state`: show that the Listing changed and offer to
  reload current evidence;
- 409 `alias_conflict`: explain that the normalized title belongs to another
  SKU and permit retry with alias creation unchecked;
- 415, 500, malformed JSON, or network failure: show a retryable operation
  failure without claiming a mutation succeeded.

The browser never treats a failed or unknown response as success and never
optimistically writes authoritative Listing or alias state.

## 18. Built frontend and static serving

### 18.1 Dependency decision

Add the bounded backend dependency:

```text
whitenoise>=6.12,<6.13
```

WhiteNoise 6.12.0 was the current stable release checked during HARDEN on
2026-08-09. It provides same-process WSGI static serving without adding Caddy
or another service. References:

- `https://whitenoise.readthedocs.io/en/stable/`
- `https://pypi.org/project/whitenoise/`

Place `WhiteNoiseMiddleware` immediately after Django's
`SecurityMiddleware`. Use `CompressedStaticFilesStorage`, not manifest
renaming, because Vite's built `index.html` already references content-hashed
asset filenames directly.

### 18.2 Static paths

Runtime `STATIC_URL` is `/static/`. Add:

```text
STATIC_ROOT = BASE_DIR / "staticfiles"
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
```

When the generated dist directory exists, register it with a `frontend`
staticfiles prefix. A production Vite build uses:

```text
base: /static/frontend/
```

so a built asset at `frontend/dist/assets/<hash>.js` is served as
`/static/frontend/assets/<hash>.js`. The generated output remains ignored and
uncommitted.

The Vite development server instead resolves its base as `/`, preserving
root-level source routes such as `/deals`, `/skus/<id>`, `/reviews`, and
`/reviews/<id>`. The contract is behavioral and does not require one particular
`vite.config.ts` branching technique.

### 18.3 Docker build and collection

The application image becomes a multi-stage build:

1. pinned Node `24.18.0` installs from the existing lockfile with `npm ci`;
2. `npm run build` creates `frontend/dist/`;
3. the existing pinned Python image installs backend requirements;
4. the source and built dist are copied into the final image; and
5. a small entrypoint runs `collectstatic --noinput` using runtime environment
   settings before executing the supplied container command.

The entrypoint does not migrate, seed, ingest, price, or schedule work.
`.dockerignore` excludes local node modules, dist, coverage, and Vite cache so
only the builder's output enters the image.

This makes the Phase 6 application self-contained. Phase 9 may later put Caddy
and HTTPS in front without changing the same-origin route contract.

## 19. Admin static-resolution finding

The reported admin CSS failure is not caused by an incorrect emitted URL.
Repository inspection proved:

- source setting `STATIC_URL = "static/"` is normalized by Django at runtime
  to `/static/`;
- `/admin/login/` emits absolute `/static/admin/...` stylesheet links;
- `DJANGO_DEBUG=0` is the documented local default; and
- with `DEBUG=False`, the current development server returns 404 for those
  files, which Vite faithfully proxies.

TASK_026 fixes the actual cause by collecting Django admin and Vite assets and
serving them through WhiteNoise under `/static/`. It does not rely on turning
DEBUG on or on Vite owning Django assets.

Development remains coherent:

- Vite serves the React source application at port 5173;
- the Vite development base remains `/`;
- `/api`, `/admin`, `/auth`, and `/static` proxy without rewriting to Django;
- WhiteNoise serves proxied collected admin/static assets with DEBUG false; and
- relative fetches retain same-origin browser credentials.

## 20. SPA serving and namespace protection

Django serves the generated `frontend/dist/index.html` for direct GET/HEAD
navigations to:

```text
/
/deals
/skus/<id>
/reviews
/reviews/<id>
unknown product paths
```

The React router owns the final in-app match and not-found experience. The SPA
view returns a clear HTTP 503 when the built index is absent instead of serving
a partial or fabricated page.

The fallback explicitly excludes every path beginning with:

```text
/api/
/admin/
/auth/
/static/
```

Known and unknown paths in those namespaces remain Django/API/auth/static
responses and never return React `index.html`. URL ordering alone is not the
only protection; the fallback pattern itself excludes the prefixes.

## 21. Existing TASK_024 behavior preserved

TASK_026 preserves:

- `/` redirecting client-side to `/deals`;
- `/deals` and `/skus/:skuId`;
- server DealFlag order and complete PricePoint pagination;
- Decimal-string authority and presentation-only chart conversion;
- Asia/Manila instant formatting and non-shifted date-only formatting;
- honest empty, loading, access, missing, and failure states;
- no pricing or resolver invocation from HTTP or React;
- no RawListing traversal outside the review projection; and
- the exact existing frontend package and lockfile contract.

## 22. Testing and tooling decision

Use the existing deterministic split:

- PostgreSQL-backed Django/DRF tests for review projection, permissions,
  ordering, auth, CSRF, namespace routing, and static serving; and
- Vitest, jsdom, React Testing Library, and user-event for review rendering,
  fetch contracts, interaction states, and TASK_024 regression.

Do not add Playwright. The required same-origin boundaries are server URL and
HTTP contracts exercised by Django integration tests, while browser fetch and
UI behavior are deterministic in the already-frozen jsdom stack. Playwright
would add a browser binary, package changes, Docker orchestration, and timing
failure modes without proving an additional authoritative domain property.

Implementation validation still runs a real production frontend build. The
clean built index and asset URLs are then exercised through Django and
WhiteNoise integration tests.

## 23. Acceptance coverage

The frozen Python suite covers:

- exact review read and CSRF routes;
- queue predicate, ordering, pagination, fields, Decimal/time behavior, and
  RawListing exclusions;
- exact any-Listing detail projection, privacy exclusions, and current-SKU
  correction evidence;
- active staff/change permission on both list and detail, plus exact 403/404
  behavior;
- constrained and deterministically ordered SKU search while preserving
  TASK_023 behavior, including the 100/101-character boundary;
- CSRF cookie/token bootstrap, an untrusted POST rejected with 403, and a
  valid-token POST reaching GET-only method handling with 405;
- Django login, safe next, logout, redirects, and CSRF enforcement;
- built SPA direct navigation, protected namespaces, and HTTP 503 when the
  built index is absent;
- absolute admin static URLs and WhiteNoise-served collected admin/frontend
  assets with DEBUG false;
- root-based Vite development routes, the `/auth` development proxy, and the
  `/static/frontend/` production build base;
- Docker multi-stage build/collection boundary; and
- no migration.

The frozen frontend suite covers:

- review queue rendering and raw/derived/curated evidence separation;
- queue pagination and honest empty/access/failure states;
- detail route, SKU search, confirmation, correction, and alias opt-in;
- exact CSRF bootstrap, headers, credentials, methods, and JSON bodies;
- CSRF invalidation and re-bootstrap after a mutation 403;
- mark-reviewed-unresolved success;
- 400, 403, both 404 codes, both 409 codes, server, and network behavior;
- logout integration and browser navigation to `/auth/login/`;
- review links from navigation and deals; and
- preservation of existing deal, SKU, and singular `/review` behavior.

Tests use roles, labels, visible messages, response shapes, and network calls.
They do not freeze CSS classes or private component decomposition.

## 24. Expected failing baseline

Before implementation:

- review list/detail and CSRF routes do not exist;
- the SKU list ignores `q`;
- `/auth/login/` and `/auth/logout/` do not exist;
- Django has no SPA fallback or built/static integration;
- WhiteNoise is absent;
- Vite does not proxy `/auth` or build for `/static/frontend/`; and
- React has no plural review route or workflow.

Both frozen suites must collect. The Python suite fails explicit missing route,
configuration, and behavior assertions. The Vitest suite runs with the existing
installed TASK_024 toolchain and fails because `/reviews` still reaches the
in-app not-found state, not because of a missing package or test setup error.

## 25. Validation requirements

Implementation must finish with:

1. exact frozen artifact hashes;
2. `npm ci`, `npm run lint`, `npm test`, and `npm run build`;
3. TASK_026 Python and frontend frozen suites;
4. TASK_023, TASK_024, and TASK_025 compatibility suites;
5. relevant TASK_016 through TASK_018 compatibility;
6. the full PostgreSQL suite;
7. `python manage.py makemigrations --check --dry-run`;
8. Django's system check;
9. a clean container build proving the frontend stage and static collection;
10. exact staged-scope and unrelated-working-tree checks; and
11. independent review and clean-snapshot validation.

No generated `frontend/dist`, `frontend/node_modules`, `staticfiles`, coverage,
or cache output may be staged.

## 26. Schema disposition and stop conditions

No schema or migration is required. Existing Listing, RawListing, Source, SKU,
session, permission, and LogEntry state represents the full contract.

Stop for owner correction if implementation requires:

- a model, migration, index, or stored frontend state;
- a change to TASK_016 through TASK_025 semantics or frozen tests;
- production behavior outside the authorized files;
- a RawListing field beyond the frozen review projection;
- a frontend dependency or lockfile change;
- a CSRF, authentication, or permission bypass;
- pricing, resolution, ingestion, or outcome invocation; or
- a permanent cross-origin or new-service architecture.

No unresolved contract question remains for TASK_026 implementation after
owner approval.
