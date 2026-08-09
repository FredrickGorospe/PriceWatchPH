# TASK_024 - Add the React deal and SKU experience

## 1. Objective

Create the first React and TypeScript product surface for PriceWatch PH. The
application presents the persisted DealFlag feed and canonical SKU pricing
history exposed by TASK_023. It owns browser navigation, presentation,
non-authoritative chart geometry, and honest loading, empty, permission, and
error states.

TASK_024 does not change the backend. Its dependency direction is:

```text
persisted PricePoint and DealFlag evidence
    -> frozen TASK_023 read API
    -> TASK_024 React presentation
```

The browser never calculates, scores, writes, backfills, resolves, or reviews
pricing evidence.

## 2. Authority and dependencies

This task follows:

- committed `CLAUDE.md` constraints;
- owner-approved `docs/06_PLANNING.md`, especially Capability B;
- TASK_013 through TASK_022 derived and pricing evidence contracts; and
- frozen TASK_023 API specification, tests, routes, permissions, ordering,
  pagination, serialization, and RawListing boundary.

TASK_024 consumes TASK_023 without widening or reshaping it. No backend gap was
found during HARDEN.

## 3. Frozen artifacts and implementation boundary

### 3.1 HARDEN artifacts

These artifacts are frozen after owner approval:

- `tasks/TASK_024_REACT_DEAL_AND_SKU_EXPERIENCE.md`
- `tests/test_task_024_react_deal_and_sku_experience.py`
- `frontend/src/__tests__/task_024_react_deal_and_sku_experience.test.tsx`

They must not be edited to make implementation pass. A contradiction stops the
task for owner correction.

### 3.2 Authorized IMPLEMENT files

Implementation may create or modify only:

- `.gitignore`, limited to generated frontend paths;
- `frontend/.nvmrc`;
- `frontend/package.json`;
- `frontend/package-lock.json`;
- `frontend/index.html`;
- `frontend/tsconfig.json`;
- `frontend/tsconfig.app.json`;
- `frontend/tsconfig.node.json`;
- `frontend/vite.config.ts`; and
- `frontend/src/**`, excluding the frozen acceptance test.

No Django, DRF, model, migration, admin, resolver, pricing, ingestion,
management-command, template, Docker, Compose, prior task, prior test, or
planning file is authorized. Final Django bundle serving and SPA fallback are
owned by Capability D.

## 4. Explicit non-goals

TASK_024 does not own:

- review queues, RawListing review evidence, confirmation, correction,
  reviewed-unresolved, or alias actions;
- review routes, review mutations, CSRF write integration, or shared Phase 4
  services;
- custom login/logout APIs or mounted general Django authentication routes;
- generic catalogue CRUD, Listing collections or mutations, or Outcome work;
- manual capture, personal trade logging, ingestion, new sources, or alerts;
- pricing invocation, baseline construction, score calculation, statistical
  recomputation, or fabricated production evidence;
- dashboard KPI aggregates, client persistence, preferences, favourites, or
  dismissed-deal state;
- CORS, JWT, token authentication, or cross-origin production architecture;
- Django static serving, SPA fallback, Caddy, HTTPS, backups, or final
  deployment integration;
- public or anonymous product pages; or
- schema changes, migrations, seed data, or production fixtures.

## 5. Toolchain decision

### 5.1 Build tool: Vite

Use Vite 8 with the official React plugin and a TypeScript application.

Focused comparison performed on 2026-08-09:

- Vite has an official React TypeScript template, a scoped development proxy,
  a fast development server, typed configuration, and a static production
  build. Vitest shares its transform/configuration model.
- A full-stack React framework would duplicate Django server responsibilities
  and complicate the later same-origin boundary.
- Parcel could produce a static bundle but gives this repository no advantage
  over Vite's explicit proxy and directly compatible test runner.

Authoritative references checked:

- `https://vite.dev/guide/`
- `https://vite.dev/config/server-options.html#server-proxy`
- `https://vite.dev/releases`
- `https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts`

Do not use an unreleased Vite build or an experimental React template.

### 5.2 Package manager: npm

Use npm only. `frontend/package-lock.json` is committed and authoritative.
Implementation creates it with npm 11.16 and all validation installs use
`npm ci`, not an unpinned alternative resolver. No yarn, pnpm, Bun, or second
lockfile is allowed.

`frontend/package.json` includes:

```json
{
  "private": true,
  "type": "module",
  "packageManager": "npm@11.16.0",
  "engines": {
    "node": "24.18.x",
    "npm": "11.16.x"
  }
}
```

Node 24.18.0 LTS is the reproducible project runtime recorded in
`frontend/.nvmrc`. TASK_024 validates this one LTS runtime only.

### 5.3 Dependency strategy

Package ranges are bounded to the current compatible major, while the
committed lockfile freezes the exact resolved graph. The minimum range entries
approved during HARDEN are:

Runtime:

```json
{
  "react": "^19.2.8",
  "react-dom": "^19.2.8",
  "react-is": "^19.2.8",
  "react-router": "^8.3.0",
  "recharts": "^3.10.1"
}
```

Development:

```json
{
  "@testing-library/dom": "^10.4.1",
  "@testing-library/jest-dom": "^7.0.0",
  "@testing-library/react": "^16.3.2",
  "@testing-library/user-event": "^14.6.1",
  "@types/node": "^24.13.3",
  "@types/react": "^19.2.17",
  "@types/react-dom": "^19.2.3",
  "@vitejs/plugin-react": "^6.0.4",
  "jsdom": "^30.0.1",
  "oxlint": "^1.76.0",
  "typescript": "~6.0.2",
  "vite": "^8.1.5",
  "vitest": "^4.1.10"
}
```

React, React DOM, and `react-is` resolve to the same React release in the
lockfile. Stable releases only are permitted. React's current stable major is
19 and its stable channel follows semantic versioning. TypeScript 6 is retained
because it is the current official Vite React TypeScript template line checked
during HARDEN; TASK_024 does not adopt a newer compiler independently of that
tested toolchain.

No request library, state library, runtime schema library, arbitrary-precision
arithmetic package, CSS framework, component system, or date library is needed.

## 6. Frontend directory boundary

The application lives entirely under `frontend/`:

```text
frontend/
    .nvmrc
    package.json
    package-lock.json
    index.html
    tsconfig.json
    tsconfig.app.json
    tsconfig.node.json
    vite.config.ts
    src/
        main.tsx
        App.tsx
        api/
            client.ts
            types.ts
        charts/
            priceHistory.ts
            PriceHistoryChart.tsx
        components/
        formatting/
            decimal.ts
            sku.ts
            time.ts
        pages/
            DealFeedPage.tsx
            SkuDetailPage.tsx
        styles/
        test/
            setup.ts
        __tests__/
            task_024_react_deal_and_sku_experience.test.tsx
```

Equivalent component/CSS filenames inside the authorized families are allowed
when the frozen imports and user-visible behavior remain stable. React source
must not be scattered through Django templates or static directories.

Generated `frontend/node_modules/`, `frontend/dist/`, coverage, and Vite cache
paths are ignored. `frontend/dist/` is never committed.

## 7. Development and production boundaries

### 7.1 Development proxy

Vite serves the browser application on `http://localhost:5173` with
`strictPort: true`. Its development-only proxy preserves paths and forwards:

```text
/api/    -> http://localhost:8000
/admin/  -> http://localhost:8000
/static/ -> http://localhost:8000
```

The proxy target may be overridden only by a non-secret development environment
value with the same default. It does not rewrite paths, enable permissive CORS,
or change authentication headers. Browser calls remain relative and
same-origin. Django session cookies therefore accompany proxied API calls.

`/admin/` is proxied so the existing Django admin login can establish a session
during TASK_024 development. `/static/` is proxied only for admin assets. No
general auth route is mounted in this task.

### 7.2 Production build

`npm run build` runs TypeScript project checking before `vite build` and emits
static assets to `frontend/dist/`. A clean `npm ci`, test run, and production
build must succeed. TASK_024 proves the bundle is buildable and does not commit
the output.

TASK_024 does not make Django serve that bundle and does not add a fallback.
Capability D will integrate the same-origin built assets while reserving API,
admin, and authentication prefixes.

## 8. Application shell and routes

Use React Router in declarative browser mode. The shell contains the
`PriceWatch PH` product identity and a `Deals` navigation link.

TASK_024 owns exactly:

```text
/             redirect to /deals
/deals        DealFlag landing feed
/skus/:skuId  canonical SKU detail and complete persisted history
/*            in-app not-found state
```

There is no review, outcome, capture, settings, login, logout, dashboard, or
generic catalogue route. The client does not claim `/api/`, `/admin/`, or a
future Django authentication prefix. Final direct-load SPA fallback is deferred
to Capability D; TASK_024 routes work through Vite development fallback and
client navigation.

## 9. Authentication and permission experience

TASK_024 has no independent current-user or login API. Existing Django admin
login is sufficient to create a development session.

TASK_023 deliberately returns HTTP 403 for anonymous, inactive, non-staff, and
permission-missing users. The frontend cannot distinguish those cases and must
not pretend it can. Any 403 renders one combined `Access required` state that:

- says an active staff session and the resource's view permissions are needed;
- links to the existing `/admin/login/` page for sign-in; and
- tells an already signed-in user to request access or reload after permissions
  change.

No protected evidence from a previous successful request remains visible after
a 403. A 404 is a missing-resource state, not a permission state. Other HTTP and
network failures render a retryable request-failure state.

Capability D owns mounted general login/logout integration and final return
paths.

## 10. API client boundary

Use native `fetch` behind a small typed module. Expose only these TASK_024 reads:

```text
GET /api/v1/deal-flags/
GET /api/v1/skus/<pk>/
GET /api/v1/skus/<sku_pk>/price-points/
GET /api/v1/skus/<sku_pk>/price-points/?condition=<approved value>
```

TASK_024 does not need the standalone Listing detail because DealFlag already
embeds its approved Listing evidence.

Every request:

- uses a relative same-origin URL and `credentials: "same-origin"`;
- is GET-only and sends no body or CSRF header;
- follows only API-provided pagination URLs whose origin is the current origin
  and whose path stays within the expected endpoint;
- distinguishes 403, 404, other non-success status, malformed response, abort,
  and network failure; and
- does not retry automatically or generate a generic SDK.

No API call targets RawListing, review, outcome, mutation, pricing service, or
management-command paths.

## 11. TypeScript wire contracts

Types mirror the exact TASK_023 JSON allowlists. Use semantic aliases:

```typescript
type DecimalString = string;
type ISODateString = string;
type UTCDateTimeString = string;
```

`DecimalString` fields are never typed as `number`. Nullable fields are explicit
unions with `null`, including Listing facts and all legacy PricePoint audit
metadata. Date-only strings and timestamp strings remain conceptually distinct.

The client defines typed `Sku`, `SkuSummary`, `Listing`, `PricePoint`,
`DealFlag`, and `Page<T>` interfaces containing only TASK_023 fields. It does
not define or assume RawListing, Source, seller, payload, URL provenance, or
review fields.

Runtime schema validation is not added. HTTP status and basic JSON container
shape checks give honest request failures; the frozen server tests remain the
authoritative wire-shape contract.

## 12. Shared display rules

### 12.1 SKU identity

Canonical display identity is the trimmed, single-space join of `brand`,
`model`, and non-empty `variant`, in that order. Category is separate secondary
metadata. Empty variant produces no dangling separator and no fabricated label.
Do not add a backend `display_name`.

Known category and condition codes receive human-readable labels. A nullable
condition displays `Unknown condition`; it is not inferred.

### 12.2 Decimal presentation

Server Decimal strings are authoritative. Money display inserts thousands
separators using string operations and prefixes the Philippine peso symbol. It
does not parse through `Number`, `parseFloat`, or another binary-float path.
The original fractional digits are retained:

```text
"15500.00"   -> "₱15,500.00"
"1500.2500"  -> "₱1,500.2500"
```

Scores, confidence, counts, table values, labels, and tooltip evidence use the
original server strings. Null displays `Unavailable` or the more specific
unknown label frozen by the surrounding field.

JavaScript `Number` conversion is allowed only in a chart adapter that creates
coordinates for `median`, `p25`, and `p75`. Every chart point retains the source
PricePoint so accessible tables and custom tooltips render its original strings.
No numeric chart value is written back, promoted to evidence, or used to derive
another statistic.

No quartile, MAD, median, baseline, deal score, ranking, currency conversion, or
other pricing calculation exists in the browser.

### 12.3 Manila timestamp and date-only display

Timestamp strings are parsed as instants and formatted with
`Intl.DateTimeFormat` using the explicit `Asia/Manila` time zone. The stable
display form is:

```text
09 Aug 2026, 1:06:07 PM (Asia/Manila)
```

Date-only fields, especially `PricePoint.day`, are already calendar dates.
They are formatted by splitting the `YYYY-MM-DD` text and mapping the month.
They are never passed to `Date`, treated as UTC midnight, or shifted across a
calendar boundary. Launch date and PricePoint window date fields use the same
date-only rule.

## 13. Deal feed contract

`/deals` requests the first frozen DealFlag page and preserves the API result
order. It never sorts or ranks by score, price, or another client value.

Each deal article displays:

- canonical SKU identity linked to `/skus/<baseline SKU id>`;
- category;
- Listing asking price or `Unavailable`;
- Listing condition or `Unknown condition`;
- persisted DealFlag score exactly as received;
- arbitrary reason exactly as received;
- baseline day, median, MAD or `Unavailable`, and sample count;
- Listing observation time or `Unavailable`; and
- DealFlag time.

The SKU link always uses `dealFlag.sku`, which TASK_023 derives from
`baseline_pricepoint.sku`; it is not rebuilt from mutable Listing state.

The feed uses previous/next buttons and replaces the visible page. It follows
the API-provided links, does not send `page_size`, and displays the total count
and current item range. Buttons are disabled when the corresponding API link is
null. A page change has its own loading state and never appends or silently
reorders pages.

States are distinct:

- initial/page loading: `Loading persisted deals...`;
- successful empty page: `No persisted deal flags are available.`;
- 403: the shared access-required state;
- network or other server failure: `Deal feed could not be loaded.` plus Retry.

No empty-state control invokes pricing or creates test data.

## 14. SKU detail and complete history contract

`/skus/:skuId` loads the canonical SKU and its PricePoint history.

Catalogue facts displayed:

- canonical identity;
- category;
- launch MSRP using the string-safe money formatter; and
- launch date using the date-only formatter.

History provides a condition selector with exactly:

```text
All conditions
New
Like new
Used
For parts
```

All conditions omits the query parameter. The other values use the exact
TASK_023 vocabulary. A condition change discards the previous history request,
starts again from the first page, and does not change the SKU detail request.

### 14.1 Complete-history pagination

The chart must not claim the first server page is the full series. For the
selected condition, the client automatically follows each TASK_023 `next` link
until null, then renders one complete history view. Pages are concatenated in
server order without client sorting or aggregation.

While any page remains, show `Loading complete price history...` and do not
render a partial chart as complete. If any page fails, discard the partial
series and show `Price history could not be loaded.` plus Retry. A successful
result states how many persisted points were loaded.

This bounded sequential approach is preferred to infinite scroll because the
dataset is modest and a complete time series has clearer meaning. No arbitrary
client page cap is introduced. Pagination links are origin/path validated and
repeated links are rejected as malformed rather than looped forever.

### 14.2 Chart and evidence

Use a responsive Recharts composed chart:

- x axis: server `PricePoint.day` labels;
- primary line: persisted median;
- range band: persisted p25 through p75;
- separate labelled series per represented condition when `All conditions` is
  selected;
- no interpolation that invents points; and
- animation disabled when it obscures evidence or conflicts with reduced
  motion.

Recharts was selected over Chart.js and visx after a focused comparison:

- Recharts 3 is actively maintained, typed, declarative React/SVG, responsive,
  and directly supports ranged areas and lines.
- Chart.js uses canvas, whose content requires extra accessibility work and is
  not itself screen-reader accessible.
- visx offers lower-level primitives but would require more bespoke scales,
  range, tooltip, and responsive behavior than this modest chart needs.

References checked:

- `https://recharts.github.io/en-US/api/`
- `https://recharts.github.io/en-US/api/ResponsiveContainer/`
- `https://www.chartjs.org/docs/latest/general/accessibility.html`
- `https://visx.airbnb.tech/`

The chart is supplemental and labelled as presentation-only. An adjacent
semantic table is the authoritative accessible evidence and displays, for each
PricePoint:

- day and condition;
- median, p25, and p75;
- sample count and MAD;
- window start and end;
- calculation time; and
- calculation-contract version.

Custom tooltips also use original strings. Null legacy audit fields display
`Unavailable`; they are never synthesized.

An empty completed history shows `No persisted price history is available for
this selection.` It is different from loading or request failure.

## 15. Styling and accessibility

Use semantic HTML, a small global token/layout stylesheet, and CSS Modules for
component/page styles. Do not add Tailwind, CSS-in-JS, a component kit, a design
system, icon package, or remote font dependency.

The interface must be intentionally product-quality and responsive with:

- readable evidence hierarchy and tabular numerals;
- keyboard-operable links, buttons, and selector;
- visible focus styles;
- status text announced with suitable live/status semantics;
- sufficient text/background contrast;
- responsive cards and an overflow-safe evidence table; and
- chart text/table alternatives that do not rely only on colour.

## 16. Frontend testing strategy

Use Vitest with jsdom, React Testing Library, `@testing-library/jest-dom`, and
`@testing-library/user-event`. Tests interact through roles, labels, links, and
visible state rather than component internals. No Playwright or full browser E2E
stack is introduced; Capability D owns integrated same-origin regression.

The frozen TypeScript suite covers:

- route shell and deal landing behavior;
- exact deal evidence, API order, SKU navigation, and pagination;
- loading, empty, 403, 404, network/server failure, and retry behavior;
- SKU identity and catalogue display;
- all-page PricePoint loading and condition filtering;
- median and p25/p75 chart/table evidence;
- null legacy metadata;
- Decimal string authority and presentation-only chart conversion;
- explicit Manila instant formatting and non-shifted date-only formatting;
- same-origin GET-only calls to the approved TASK_023 endpoints; and
- absence of review routes, mutations, pricing invocation, and RawListing
  assumptions in exercised behavior.

The Python repository tests freeze package, lockfile, proxy, generated-output,
and source-layout boundaries without requiring Node inside the Django image.

## 17. Expected failing baseline

HARDEN creates the task and two acceptance-test artifacts only. It does not
create `frontend/package.json`, source implementation, Vite configuration,
lockfile, or install dependencies.

Before implementation:

```text
docker compose exec web pytest -q \
    tests/test_task_024_react_deal_and_sku_experience.py
```

collects normally and fails explicit missing-frontend contract assertions. It
does not import Node packages or crash because package metadata is absent.

The frozen TypeScript test is structurally runnable after implementation adds
the approved package metadata and runs `npm ci`. It then runs through:

```text
cd frontend
npm test
```

It is not invoked during the pre-implementation baseline because HARDEN does
not install the test runner. This split is intentional.

## 18. Validation requirements

Implementation must finish with:

1. exact frozen artifact hashes;
2. `npm ci` from `frontend/` using the committed lockfile;
3. `npm run lint`;
4. `npm test`;
5. `npm run build`;
6. the TASK_024 Python repository tests;
7. frozen TASK_023 API tests;
8. relevant Phase 3 through Phase 5 compatibility tests;
9. the full PostgreSQL Django suite;
10. `python manage.py makemigrations --check --dry-run`;
11. Django's system check; and
12. staged-snapshot review and validation under the repository workflow.

Generated build output must remain ignored and unstaged. The frozen TASK_024
tests must not be modified during implementation.

## 19. No-migration expectation

TASK_024 needs no model or schema change and permits no migration. Frontend
presentation state is in-memory only. If implementation appears to require
backend persistence, stop for owner review.

## 20. STOP conditions

Stop rather than improvise if:

- a frozen TASK_024 test contradicts TASK_023 or the approved Phase 6 plan;
- TASK_023 cannot supply the approved read experience without a backend change;
- implementation requires a Django, API, model, migration, Docker, Compose, or
  other out-of-scope file;
- the chosen stable package ranges cannot resolve together on the approved
  Node/npm runtime;
- complete PricePoint history cannot be obtained honestly from frozen
  pagination;
- a response would require RawListing evidence, pricing computation, or a
  mutation; or
- an authentication distinction requires information TASK_023 intentionally
  does not expose.

## 21. Deferred work

Capability C owns shared review services and operation-oriented mutation APIs.
Capability D owns the React review UI, dedicated RawListing review projection,
CSRF-protected review actions, mounted Django login/logout integration, final
SPA fallback, built-bundle serving, Docker integration, and integrated
same-origin regression.

No Capability C or D file, route, UI, service, or test is scaffolded here.
