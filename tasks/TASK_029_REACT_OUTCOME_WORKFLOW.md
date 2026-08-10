# TASK_029 - React Outcome workflow

## 1. Objective

Expose the TASK_028 governed Outcome domain through the existing React product
interface: a route reachable from a specific DealFlag that lets a user inspect
the current lifecycle state and drive the five governed operations
(`skip`, `record_purchase`, `record_sale`, `correct_purchase`, `correct_sale`)
exactly as the backend already permits them.

TASK_029 is the second and final planned implementation task of Phase 8. It
owns the React workflow only. Aggregate realised-margin reporting is
explicitly excluded from Phase 8 (`docs/08_PLANNING.md` Section 14) and is not
reopened here.

## 2. Authority and existing behavior

This task follows:

- `CLAUDE.md`;
- `docs/08_PLANNING.md`, Sections 8 and 16 in particular;
- TASK_028, whose API, service contract, and response shapes are consumed
  exactly and not renegotiated;
- TASK_026, whose React architecture, routing conventions, CSRF flow, and
  frozen frontend test style this task extends rather than replaces.

### 2.1 What already exists and is reused unchanged

Inspection of the current frontend confirms all of the following exist and
are authoritative precedent:

- `frontend/src/App.tsx` - route table, `MemoryRouter`-compatible, a
  `NotFoundPage` catch-all, and a persistent header/nav;
- `frontend/src/pages/ReviewDetailPage.tsx` - the closest existing analogue:
  a single-resource page with `loading` / `success` / `forbidden` / `missing`
  / `error` states, a separate `operation` state for in-page mutations
  (`idle` / `submitting` / `error`, with `message`, `reload`, and
  `fieldErrors`), and buttons disabled while `operation.status === 'submitting'`;
- `frontend/src/pages/DealFeedPage.tsx` - each `DealCard` already renders one
  navigation `<Link>` per deal (`Review or correct SKU`) built from
  `deal.listing.id`; the same card already has `deal.id`, the DealFlag primary
  key, available with no payload change;
- `frontend/src/api/client.ts` - `bootstrapCsrf`, `currentCsrfToken`,
  `clearCsrfToken`, the `ReviewApiError` shape (`status`, `code`, `detail`,
  `errors`), and the `reviewGet` / `unsafeJson` internal request helpers that
  implement the existing 403-clears-token and same-origin JSON conventions;
- `frontend/src/formatting/decimal.ts` - `formatMoneyDecimal`, which already
  renders `null` as `"Unavailable"` and preserves a leading sign, so negative
  Decimal strings display correctly with no new logic;
- `frontend/src/formatting/time.ts` - `formatManilaTimestamp`, which renders a
  UTC instant string in Asia/Manila using a fixed-timezone `Intl.DateTimeFormat`,
  and `formatDateOnly` for bucketed dates; neither performs Manila-local ->
  UTC conversion, which this task must add;
- `frontend/src/components/AsyncStates.tsx` - `AccessRequiredState` (a full
  page-level 403 state with a login link) and `RequestFailureState` (a retry
  affordance for a failed initial load); and
- `frontend/src/components/ReviewEvidence.tsx` - the `<section
  aria-label="...">` + `<dl>/<dt>/<dd>` pattern that gives each evidence block
  an accessible ARIA `region`, reused for Outcome's read-only fields.

No new architecture is invented. No frontend form library exists in
`frontend/package.json` and none is added.

## 3. Frozen artifacts and implementation boundary

### 3.1 HARDEN artifacts

- `tasks/TASK_029_REACT_OUTCOME_WORKFLOW.md`
- `frontend/src/__tests__/task_029_react_outcome_workflow.test.tsx`

After owner approval neither may be modified to make implementation pass. A
genuine contradiction stops implementation for owner correction.

### 3.2 Authorized IMPLEMENT files

- `frontend/src/pages/OutcomeWorkflowPage.tsx` (new)
- `frontend/src/pages/OutcomeWorkflowPage.module.css` (new)
- `frontend/src/api/client.ts`
- `frontend/src/api/types.ts`
- `frontend/src/formatting/time.ts`
- `frontend/src/App.tsx`
- `frontend/src/pages/DealFeedPage.tsx`

`frontend/src/formatting/time.ts` is added to the "likely surfaces" list in
`docs/08_PLANNING.md` Section 16 because inspection shows the existing file
only renders UTC -> Manila for display; the Manila-local input -> explicit-offset
UTC conversion this task needs belongs beside it, not duplicated in a new
module or inlined in the page component.

No backend file, no model, no migration, no DealFlag serializer change, and no
prior frozen frontend test is in scope. `DealFeedPage.tsx` may only gain one
navigation link inside the existing `DealCard`; no other change to that file
is authorized.

## 4. Frozen backend contract consumed exactly

Verified against the committed TASK_028 code
(`outcomes/outcome_services.py`, `api/serializers.py`, `api/views.py`,
`api/urls.py`) and its frozen tests, not assumed:

```text
GET  /api/v1/deal-flags/<int:pk>/outcome/
POST /api/v1/deal-flags/<int:pk>/outcome/skip/
POST /api/v1/deal-flags/<int:pk>/outcome/record-purchase/
POST /api/v1/deal-flags/<int:pk>/outcome/record-sale/
POST /api/v1/deal-flags/<int:pk>/outcome/correct-purchase/
POST /api/v1/deal-flags/<int:pk>/outcome/correct-sale/
```

The read response, exactly:

```json
{
  "deal_flag_id": 12,
  "outcome_id": null,
  "lifecycle_state": "untracked",
  "acted": null,
  "skip_reason": null,
  "bought_at": null,
  "bought_price": null,
  "sold_at": null,
  "sold_price": null,
  "days_held": null,
  "realised_margin": null
}
```

A mutation response is the same object plus `operation`, one of `skip`,
`record_purchase`, `record_sale`, `correct_purchase`, `correct_sale`.

`lifecycle_state` is exactly one of `untracked`, `skipped`, `open`, `closed`.
TASK_029 does not invent a fifth value. A 409 `invalid_outcome_state` response
is an operational error about a persisted row that matches none of the four
states - it is never rendered as a lifecycle and never given a UI state string
of its own inside the vocabulary.

Request bodies, exactly:

```text
skip              {"skip_reason": "..."}
record-purchase   {"bought_at": "...", "bought_price": "..."}
record-sale       {"sold_at": "...", "sold_price": "..."}
correct-purchase  {"bought_at": "...", "bought_price": "..."}
correct-sale      {"sold_at": "...", "sold_price": "..."}
```

Money is always a JSON string. Timestamps require an explicit offset. Status
mapping: 200 success; 400 invalid request (`code: "invalid_request"`, an
`errors` object); 403 permission/CSRF; 404 `deal_flag_not_found` /
`outcome_not_found`; 409 `outcome_already_exists` / `ineligible_outcome_state`
/ `invalid_outcome_state`; 405/415 unreachable through correct client usage.

### 4.1 Frozen boundaries this task does not cross

- `/api/v1/outcomes/` remains unavailable;
- `/api/v1/deal-flags/` keeps its exact frozen field set
  (`id, sku, listing, baseline_pricepoint, score, reason, flagged_at`) - no
  Outcome field is added to it, and no test may assume one;
- Outcome state is fetched only when a user enters the workflow for one
  specific DealFlag - no per-card fetch across the deal feed; and
- no aggregate or reporting endpoint is added or assumed.

A `DealFlag`'s primary key (`deal.id`), already present in the existing feed
payload, is sufficient to link to the workflow. No backend change is required
to reach it.

## 5. HARDEN decision 1 - route and entry point

**Route:** `/deals/:dealFlagId/outcome`, component `OutcomeWorkflowPage`,
mounted in `App.tsx` alongside the existing routes. The path segment mirrors
the API's own nesting (`/api/v1/deal-flags/<pk>/outcome/`) and the existing
`:skuId` / `:listingId` param-naming convention.

**Entry point:** `DealCard` in `DealFeedPage.tsx` gains one additional
paragraph immediately after the existing "Review or correct SKU" link:

```tsx
<p>
  <Link to={`/deals/${deal.id}/outcome`}>Track outcome</Link>
</p>
```

This is the only change authorized to that file. No per-card Outcome fetch is
introduced - the link is built from `deal.id` alone.

**Back-navigation:** unlike `ReviewDetailPage`, which navigates away after a
successful decision because the item leaves the review queue, an Outcome is a
single resource with a multi-step lifecycle a user may return to across
several visits (skip today, record a purchase next week, record a sale a
month later). A successful mutation therefore keeps the user on
`OutcomeWorkflowPage`, updating in place from the server response, per
Section 8. A `Back to deal feed` link (`<Link to="/deals">`) is provided for
deliberate navigation, matching `NotFoundPage`'s existing `Return to deals`
convention in spirit.

## 6. HARDEN decision 2 - lifecycle-specific UI

No fifth UI state, no persisted status field, and no client-side lifecycle
derivation - `lifecycle_state` is rendered and gated exactly as the server
supplies it.

### 6.1 Untracked

Displayed: a statement that no Outcome has been recorded yet.

Exposed, as two independent sections, both visible simultaneously (the user
picks one):

- **Skip** - a `skip_reason` text input and submit button; and
- **Record purchase** - the purchase form (Section 8).

### 6.2 Skipped

Displayed: the skipped state and the exact `skip_reason` text.

Exposed: **Record purchase** only - the identical purchase form as
Section 6.1, submitting to `record_purchase`. This is the approved
Skipped -> Open transition (TASK_028 Section 10.2); it is a recorded decision
change, not repair, and no `unskip` action exists or is implied.

### 6.3 Open

Displayed, in one evidence region:

- purchase timestamp (Manila) and purchase price;
- realised margin, labelled distinctly as not yet realised (Section 6.5); and
- days held, labelled distinctly as not yet available (Section 6.5).

Exposed, as two independent sections:

- **Record sale**; and
- **Correct purchase**, pre-filled from the current `bought_at` /
  `bought_price`.

### 6.4 Closed

Displayed, in one evidence region: purchase evidence, sale evidence, days
held, and realised margin - all from the server response.

Exposed, as two independent sections:

- **Correct purchase**, pre-filled from the current `bought_at` /
  `bought_price`; and
- **Correct sale**, pre-filled from the current `sold_at` / `sold_price`.

`Record sale` is not offered again once Closed.

### 6.5 days_held and realised_margin wording

`days_held = null` (Open) renders exactly:

```text
Not yet available (no sale recorded)
```

`days_held` present (Closed, including the same-Manila-day `0` case) renders
exactly:

```text
{days_held} day(s) held
```

so `0 day(s) held` is unambiguously a real value, never confusable with the
Open state's "not yet available" wording. This directly answers
`docs/08_PLANNING.md` Section 18 item 2: the label states the convention
plainly enough that `0` cannot be misread as missing data.

`realised_margin` reuses `formatMoneyDecimal` for its value in both states
(it already renders `null` as `"Unavailable"` and preserves a leading `-`).
The surrounding label differs by state to carry the "not yet realised"
meaning without inventing a second formatter:

```text
Open:   <dt>Realised margin (not yet realised)</dt><dd>Unavailable</dd>
Closed: <dt>Realised margin</dt><dd>{formatMoneyDecimal(realised_margin)}</dd>
```

A negative Closed `realised_margin` renders through the same path with no
special case, no clamping, and no color or sign-based styling - no existing
design convention assigns business meaning to sign or color anywhere in this
codebase, so none is introduced here.

## 7. HARDEN decision 3 - form behavior

Five forms exist in total, gated by lifecycle state per Section 6, sharing two
shapes:

| Form | Fields | Used by |
|---|---|---|
| Skip | `skip_reason` (text) | Untracked |
| Purchase | `bought_at` (datetime-local), `bought_price` (text) | Untracked, Skipped (`record_purchase`); Open, Closed (`correct_purchase`) |
| Sale | `sold_at` (datetime-local), `sold_price` (text) | Open (`record_sale`); Closed (`correct_sale`) |

The purchase and sale forms are each implemented once and reused for their
record/correct pair - the field shape is identical (TASK_028 Section 12.4);
only the target operation and, for corrections, the pre-filled default values
differ. No generic Outcome edit form exists: each rendered form always maps to
exactly one named operation, never a field-level PATCH.

No frontend form library is added. Plain controlled `<input>` elements and
native HTML `required` validation are used, matching every existing form in
this codebase (`ReviewDetailPage`'s SKU search and alias checkbox).

Money inputs are `<input type="text" inputMode="decimal">`, never
`type="number"`, so `.value` is always read as a string (Section 9).
Correction forms are controlled components whose default value is derived
from the current `outcome` state and re-derived after every successful
mutation, so a correction form always reflects the latest authoritative
server value rather than the just-submitted one.

## 8. HARDEN decision 4 - timestamp UX

Backend timestamps require an explicit offset (TASK_028 Section 8.1). The
existing `formatManilaTimestamp` only renders UTC -> Manila for display; there
is no existing Manila-local input pattern to follow, so this task adds one to
`frontend/src/formatting/time.ts`, not a new module.

**What the user enters:** an `<input type="datetime-local">`, interpreted as
Asia/Manila wall-clock time - never the browser's local timezone, which can
differ from Manila. Its native value format is always `YYYY-MM-DDTHH:mm`
(minute granularity, no `step` attribute is set).

**Conversion to the request:**

```typescript
const MANILA_UTC_OFFSET_MINUTES = 8 * 60; // Asia/Manila has no DST.

export function manilaLocalInputToUtcInstant(localValue: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(localValue);
  if (!match) {
    return null;
  }
  const [, year, month, day, hour, minute] = match;
  const utcMillis = Date.UTC(
    Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute),
  ) - MANILA_UTC_OFFSET_MINUTES * 60 * 1000;
  const utc = new Date(utcMillis);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${utc.getUTCFullYear()}-${pad(utc.getUTCMonth() + 1)}-${pad(utc.getUTCDate())}`
    + `T${pad(utc.getUTCHours())}:${pad(utc.getUTCMinutes())}:${pad(utc.getUTCSeconds())}Z`;
}
```

This produces a `Z`-suffixed instant with no fractional seconds, matching what
DRF's own `DateTimeField` produces when microseconds are zero (Python's
`datetime.isoformat()` omits them) - the exact wire format every TASK_028
fixture, demo record, and frozen test already uses, so a value round-trips
byte-for-byte rather than gaining a spurious `.000` a reader would need to
explain. `toISOString()` is deliberately not used for this reason: it always
appends milliseconds. The conversion is pure arithmetic on the fixed +08:00
offset, reading only `Date`'s *UTC* getters; it never reads a local-timezone
getter and never depends on the browser's configured timezone, satisfying the
"deliberately preserve Manila semantics" requirement exactly.

A `null` return (malformed or empty input, reachable if `datetime-local`
support is absent and a browser falls back to plain text) is a local
validation failure: the request is not sent, and the field's native
`required`/`aria-invalid` state surfaces it. This does not duplicate server
validation - it only prevents sending a value that cannot be parsed into a
timestamp at all.

**Pre-filling a correction form from a returned UTC instant:**

```typescript
export function utcInstantToManilaLocalInput(value: UTCDateTimeString | null): string {
  if (value === null) {
    return '';
  }
  const utcMillis = Date.parse(value);
  if (Number.isNaN(utcMillis)) {
    return '';
  }
  const manilaMillis = utcMillis + MANILA_UTC_OFFSET_MINUTES * 60 * 1000;
  const manila = new Date(manilaMillis);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${manila.getUTCFullYear()}-${pad(manila.getUTCMonth() + 1)}-${pad(manila.getUTCDate())}`
    + `T${pad(manila.getUTCHours())}:${pad(manila.getUTCMinutes())}`;
}
```

Reading the *UTC* getters off a `Date` that has already been shifted by the
fixed Manila offset is the same "don't touch the browser's local timezone"
technique in reverse, and is deterministic under any host timezone the test
runner or a deployed browser happens to use.

**Display of a returned timestamp:** unchanged - the existing
`formatManilaTimestamp` renders the stored UTC instant in Asia/Manila.

## 9. HARDEN decision 5 - Decimal handling

No float path, anywhere:

- money inputs are `<input type="text" inputMode="decimal">`; `.value` is
  read and sent as-is;
- `parseFloat`, `Number(...)`, and arithmetic on a JS number are never applied
  to a money value, request-bound or response-bound;
- a light client-side syntax check, `/^\d+(\.\d{1,2})?$/`, gates submission
  for immediate feedback and to save an obviously-doomed round trip - it is
  not the authority. The server independently validates finiteness,
  non-negativity, and precision (TASK_028 Section 8.2) regardless of what the
  client already checked; a value that passes the client check can still be
  rejected by the server, and the UI must display that 400 correctly (Section
  10);
- `formatMoneyDecimal` is reused unchanged for every money display, including
  `realised_margin`; and
- `realised_margin` is never computed, estimated, or cross-checked by the
  browser. The returned string is displayed exactly as served, including when
  negative.

## 10. HARDEN decision 6 - error behavior

Every state below reuses existing components or the existing
`operation`-state shape from `ReviewDetailPage`; no new error-presentation
pattern is invented.

| Condition | Surfaced as |
|---|---|
| 403, from the initial GET or any mutation | Whole-page `AccessRequiredState` (existing component) |
| 404 `deal_flag_not_found`, initial GET | Dedicated "DealFlag not found" page state (mirrors `ReviewDetailPage`'s `missing` state) |
| 409 `invalid_outcome_state`, initial GET or any mutation | Dedicated whole-page state - not a lifecycle, no retry button (retrying reads the same broken row again); shows the server `detail` and a link back to the deal feed |
| 400 validation, any mutation | Inline `operation` error: server `detail` plus per-field `errors`, form stays visible and populated, matches `ReviewDetailPage`'s `fieldErrors` rendering |
| 404 `outcome_not_found` / 409 `outcome_already_exists` / 409 `ineligible_outcome_state`, any mutation | Inline `operation` error with server `detail` and a "Reload outcome" button (`reload: true`, mirrors `ReviewDetailPage`'s stale-state reload button) - state changed elsewhere; re-fetching resolves it |
| Network / malformed / 5xx, initial GET | Existing `RequestFailureState` with retry |
| Network / malformed / 5xx, any mutation | Inline generic `operation` error, no reload implied |

The server's own `detail` string is displayed directly rather than remapped
into new prose. TASK_028's conflict-matrix details
(`tasks/TASK_028_GOVERNED_OUTCOME_SERVICES_AND_API.md` Section 13) are already
short, stable, and user-appropriate; remapping them would only add a second,
parallel copy of the same information with no product value. This is a
deliberate departure from `ReviewDetailPage`'s custom-prose style, made
because the underlying strings differ in quality, not because the pattern
itself is wrong.

Raw tracebacks or unstructured 500 bodies are never rendered - only `detail`
when present, otherwise a fixed generic message
("Outcome operation could not be completed.").

405/415 are not given dedicated UI handling or a frozen test: no code path in
`OutcomeWorkflowPage` can produce a request that triggers either through
correct use of the page.

## 11. HARDEN decision 7 - CSRF and session

Reused exactly as `ReviewDetailPage` uses them: `bootstrapCsrf()` is called
once on mount, before the initial `getOutcomeState` read (mirroring
`ReviewDetailPage`'s unconditional bootstrap, not `ReviewQueuePage`'s
conditional one - there is no post-mutation-navigation case here, since
mutations do not navigate away). Every mutation obtains its token via the
existing `currentCsrfToken()` fallback. A 403 on any request clears the cached
token via the existing `clearCsrfToken()` path inside the shared request
helpers, so the next attempt re-bootstraps. No new authentication mechanism,
no JWT.

## 12. HARDEN decision 8 - loading and request races

- **Initial read:** a `loading` page state, matching `ReviewDetailPage`'s
  `<p role="status">Loading ...</p>` convention, with an `AbortController`
  cancelling the in-flight request on unmount or on `dealFlagId` change,
  mirroring the existing pattern exactly.
- **Mutation pending:** a single shared `operation.status === 'submitting'`
  gates every action button on the page - not just the one being submitted -
  identical to `ReviewDetailPage`'s single `operation` state disabling both
  its buttons together. This is what prevents a duplicate submit: the button
  that was clicked and every other action button are disabled for the
  duration of that one request.
- **Successful mutation:** the returned `OutcomeOperationResult` becomes the
  new `outcome` state directly - the UI is never recomputed from an
  assumption when the server already returned the answer. A short,
  operation-specific success message is shown (Section 13).
- **Server response is authoritative throughout:** no optimistic UI update
  ever renders a lifecycle transition, a margin, or a `days_held` value before
  the server confirms it.

## 13. Success messages

Exact and frozen, one per operation, deliberately matching the existing
`outcomes/admin.py` `_run_operation` success-message wording so the product
language is consistent across the governed admin and React surfaces:

```text
skip              Deal flag marked skipped.
record_purchase   Purchase recorded.
record_sale       Sale recorded.
correct_purchase  Purchase evidence corrected.
correct_sale      Sale evidence corrected.
```

## 14. HARDEN decision 9 - permissions

The frontend never infers a permission from `lifecycle_state` or from any
other client-side signal. A 403 from any request - initial read or any
mutation - is handled solely by rendering the existing `AccessRequiredState`;
no operation button is conditionally hidden based on a guess about the
current user's grants.

## 15. HARDEN decision 10 - negative margin

Explicitly and separately covered by the frozen tests (Section 18): a Closed
Outcome whose `realised_margin` is negative renders through the unmodified
`formatMoneyDecimal` path with the same visual treatment as a positive value -
no clamping to zero, no hidden sign, no color-coding, matching Section 6.5.

## 16. HARDEN decision 11 - TASK_027 demo compatibility

No demo-specific branching exists anywhere in `OutcomeWorkflowPage` or the new
client functions. A TASK_027 demo `DealFlag` (external ID prefix
`pricewatchph_demo_v1:`) is addressed, fetched, and mutated through the exact
same route and API calls as any other `DealFlag`; the frontend has no
knowledge of `pricewatchph_demo_v1`, demo SKUs, or the `manual_capture`
Source. A demo `DealFlag` with no Outcome enters the ordinary `untracked`
workflow like any other.

## 17. API client additions

`frontend/src/api/types.ts` gains:

```typescript
export type OutcomeLifecycleState = 'untracked' | 'skipped' | 'open' | 'closed';

export interface OutcomeState {
  deal_flag_id: number;
  outcome_id: number | null;
  lifecycle_state: OutcomeLifecycleState;
  acted: boolean | null;
  skip_reason: string | null;
  bought_at: UTCDateTimeString | null;
  bought_price: DecimalString | null;
  sold_at: UTCDateTimeString | null;
  sold_price: DecimalString | null;
  days_held: number | null;
  realised_margin: DecimalString | null;
}

export type OutcomeOperationName =
  | 'skip'
  | 'record_purchase'
  | 'record_sale'
  | 'correct_purchase'
  | 'correct_sale';

export interface OutcomeOperationResult extends OutcomeState {
  operation: OutcomeOperationName;
}
```

`frontend/src/api/client.ts` gains a new error class, `OutcomeApiError`,
structurally identical to the existing `ReviewApiError` (`status`, `code`,
`detail`, `errors`) but declared separately rather than reused. TASK_028
itself established one parallel error hierarchy per domain on the backend
(`OutcomePermissionDenied` etc. alongside, not reusing, `ReviewPermissionDenied`
etc.) precisely so a caller catching one domain's errors never silently also
catches the other's; the frontend mirrors that same domain separation. Two
small private helpers, `outcomeGet` and `outcomeUnsafeJson`, mirror the
existing `reviewGet` / `unsafeJson` internals (same-origin credentials,
403-clears-token, JSON parse-or-`OutcomeApiError`) without modifying the
existing review-scoped helpers, keeping this task's blast radius on
`client.ts` to pure additions.

Six new exported functions, all `Promise`-returning, all money/timestamp
parameters typed `string`:

```typescript
getOutcomeState(dealFlagId: number | string, signal?: AbortSignal): Promise<OutcomeState>
skipOutcome(dealFlagId: number, skipReason: string): Promise<OutcomeOperationResult>
recordPurchase(dealFlagId: number, boughtAt: string, boughtPrice: string): Promise<OutcomeOperationResult>
recordSale(dealFlagId: number, soldAt: string, soldPrice: string): Promise<OutcomeOperationResult>
correctPurchase(dealFlagId: number, boughtAt: string, boughtPrice: string): Promise<OutcomeOperationResult>
correctSale(dealFlagId: number, soldAt: string, soldPrice: string): Promise<OutcomeOperationResult>
```

Each mutation function sends exactly the request body shape in Section 4 - no
extra field, no `days_held`, no `realised_margin`, no `lifecycle_state`.

## 18. Frozen acceptance criteria

The authoritative executable artifact is:

```text
frontend/src/__tests__/task_029_react_outcome_workflow.test.tsx
```

It freezes, at minimum: the exact route resolving; the deal feed link
navigating to it; the initial GET and its `loading` -> rendered transition;
correct rendering and exposed actions for all four lifecycle states,
including the Skipped `skip_reason` display and the Skipped -> Open
transition; `record_sale` from Open; `correct_purchase` from both Open and
Closed; `correct_sale` from Closed; that `record_sale` is never offered once
Closed; `realised_margin` and `days_held` rendered exactly from the server
response for both the Open-unavailable and Closed cases, including a negative
margin rendering correctly and unclamped; Manila-local timestamp entry
converting to an explicit-offset request and a returned UTC instant
displaying in Manila; money remaining string-based end to end with no
`parseFloat`/`Number`/arithmetic conversion, both in requests and in display;
CSRF bootstrap and reuse; a successful mutation updating the page from the
returned representation with the exact frozen success message; every action
button disabled while a mutation is pending; the 400/403/404/409
`invalid_outcome_state`/generic error states of Section 10; no assumption that
`/api/v1/deal-flags/` carries Outcome data; no per-card Outcome fetch from the
deal feed; and that the existing `/deals`, `/reviews`, and `/skus/:id` routes
remain reachable.

## 19. Expected failing HARDEN baseline

At HARDEN time `OutcomeWorkflowPage`, the route, the `DealFeedPage` link, and
every new `api/client.ts` / `api/types.ts` / `formatting/time.ts` export do
not exist, so contract tests fail. A test that only exercises already-existing
behavior (for example, that `/deals`, `/reviews`, or `/skus/:id` still render)
should already pass.

A failure caused by an incorrect assumption in this specification is a
contradiction to report, not a reason to change the test or invent production
behavior beyond what is specified.

## 20. Explicit non-goals

TASK_029 does not include or scaffold: backend Outcome changes of any kind;
new API routes; a `DealFlag` serializer change; a generic Outcome CRUD
endpoint or UI; aggregate realised-margin reporting, an ROI dashboard, or
cohort analytics; alerts, Telegram, or Phase 7 work of any kind; TipidPC, new
ingestion sources, or external network access; pricing, resolver, or
entity-resolution changes; schema or migration changes; JWT, Celery, Redis, or
a broker; browser-side `realised_margin` computation; per-card Outcome fetches
across the deal feed; automatic Outcome creation from any code path;
demo-specific branching; and any redesign of the existing Phase 6 deal, SKU,
or review surfaces beyond the one authorized navigation link.

## 21. Implementation validation

```text
npm ci
npm test
npm run lint
npm run build
docker compose exec web pytest -v tests/test_task_028_governed_outcome_services_and_api.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py check
```

The backend commands exist to prove TASK_029 changed no backend behavior, not
because TASK_029 owns backend validation - no backend file is authorized for
this task (Section 3.2).

Manual verification should additionally load `/deals`, follow `Track outcome`
into the workflow for at least one real (non-demo) DealFlag and one TASK_027
demo DealFlag, and drive a `skip` -> `record_purchase` -> `record_sale` ->
`correct_sale` sequence against a real backend, confirming the displayed
`realised_margin` and `days_held` match what a direct API call reports.

## 22. Stop conditions

Implementation stops and reports rather than improvising if: the TASK_028 API
response shape does not match Section 4 against the real running backend; a
frozen TASK_024 or TASK_026 frontend assertion breaks from the one authorized
`DealFeedPage.tsx` link or the new route; or achieving any frozen behavior in
Section 18 turns out to require a backend change.

No implementation begins until this specification and its frozen acceptance
module receive explicit owner approval.
