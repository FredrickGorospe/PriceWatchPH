# Phase 8 Planning - Outcome tracking and realised margin

## 1. Status, authority, and sequencing

This document defines the Phase 8 boundary after completion of the product UI
and API in Phase 6 and the deterministic development corpus in TASK_027. It is
a planning artifact only. It does not create a task contract, acceptance tests,
production behavior, a migration, or an implementation.

All committed task specifications from TASK_001 through TASK_027 remain
authoritative. The two implementation tasks in Sections 15 and 16 are planning
units. Each must still receive its own HARDEN pass and owner-approved failing
acceptance tests before any implementation begins.

### 1.1 Execution order

The owner has decided to execute roadmap Phase 8 before roadmap Phase 7:

```text
Phase 8 - Outcome tracking and realised margin   (this document)
Phase 7 - Alerts                                 (later, docs/07_PLANNING.md)
```

Outcome tracking is part of the core PriceWatch PH value proposition and
activates an already-committed domain model without introducing a new external
dependency. Alerts are deferred because automated acquisition is not yet live,
so their immediate product value is lower while they would introduce outbound
API, secret-management, and delivery-semantics work.

This is an execution-order decision only. `docs/ROADMAP.md` phase numbering is
not renumbered, and this document does not edit it.

## 2. Phase 8 objective

Phase 8 turns PriceWatch PH from a system that identifies candidate deals into
one that records whether acting on them produced realised value. It preserves an
auditable chain:

```text
DealFlag / Listing evidence
    -> recorded decision (act or skip)
    -> recorded acquisition
    -> recorded disposition
    -> DB-generated realised margin
```

Phase 8 delivers the recording workflow and per-Outcome realised-margin display.
It does not deliver aggregate reporting.

The Phase 6 pricing rule is unchanged and unaffected. `price_listings` remains
the only producer of PricePoint and DealFlag evidence. HTTP requests and browser
code consume Outcome and pricing results and never compute them.

## 3. Repository facts established by inspection

These were verified against the repository at commit `9c520a1`, not assumed.

### 3.1 The Outcome model already exists and is committed

`outcomes/models.py` and migrations `0001_initial` and `0002_initial` define
Outcome with these fields:

| Field | Type | Notes |
|---|---|---|
| `deal_flag` | `OneToOneField(DealFlag, PROTECT, related_name="outcome")` | one Outcome per DealFlag, enforced by the database |
| `acted` | `BooleanField` | not nullable |
| `skip_reason` | `TextField(null=True, blank=True)` | |
| `bought_at` | `DateTimeField(null=True, blank=True)` | |
| `bought_price` | `DecimalField(max_digits=12, decimal_places=2, null=True)` | |
| `sold_at` | `DateTimeField(null=True, blank=True)` | |
| `sold_price` | `DecimalField(max_digits=12, decimal_places=2, null=True)` | |
| `days_held` | `PositiveIntegerField(null=True, blank=True)` | plain column, deliberately not generated |
| `realised_margin` | `GeneratedField(db_persist=True)` | `sold_price - bought_price` |

Database constraints actually present:

- `outcome_skip_reason_required_when_not_acted` -
  `acted=True OR (skip_reason IS NOT NULL AND skip_reason != '')`
- `outcome_days_held_non_negative` - explicit `days_held >= 0`, plus a second
  Postgres-generated inline check from `PositiveIntegerField` itself, as TASK_004
  documented in its "Correction found during implementation" note.

### 3.2 realised_margin is database-authoritative

TASK_004 Decision 1 verified against this repository's running stack that:

- Postgres 16 supports only `STORED` generated columns, so `db_persist=True` is
  the only valid choice;
- the expression correctly yields `NULL` when either price is `NULL`, so the
  open-position and skipped cases need no special handling;
- Postgres itself rejects a direct write
  (`column "realised_margin" can only be updated to DEFAULT`); and
- Django silently drops a caller-supplied value rather than erroring.

Consequence for Phase 8: no application or browser code may ever supply,
recompute, or reinterpret `realised_margin`. It is read-only everywhere.

### 3.3 Outcome is the one intentionally mutable derived model

`RawListing`, `PricePoint`, and `DealFlag` each override `save()`/`delete()` to
raise on mutation. Outcome does not, and that asymmetry is deliberate: an open
position must later become a closed position. Phase 8 therefore obtains its
integrity guarantees from governed operations and audit records, not from
immutability.

### 3.4 Outcome is not inert - it has an ungoverned mutation surface

`outcomes/admin.py` is a bare `admin.site.register(Outcome)`. Any staff user
holding the default `outcomes` permissions can already add, change, and delete
Outcome rows with no field restrictions, no lifecycle enforcement, and no
governed audit. This contrasts with `pricing/admin.py`, where PricePoint and
DealFlag sit behind a deliberate `ReadOnlyEvidenceAdmin`.

Phase 8 is therefore not "activating an inert model". It replaces an unguarded
surface with a governed one, which is a net reduction in mutation risk.

### 3.5 Money columns lack non-negative database checks

Only `days_held` carries a non-negative check. `bought_price` and `sold_price`
do not, so negative prices are database-legal. `realised_margin` is signed by
design, because losses are the most informative rows and must be storable
(TASK_004 Decision 1). Validation of purchase and sale prices is therefore an
application-service responsibility, recorded in Section 10.5.

### 3.6 Outcome has no API or frontend presence

There is no Outcome serializer, view, route, service module, API client
function, or React surface. Phase 8 introduces the first of each.

### 3.7 Frozen API constraints that bind this phase

Two frozen TASK_023 assertions constrain the design and must not be modified,
per `CLAUDE.md` ("If a test is wrong, stop and say so - do not edit it"):

1. **`/api/v1/outcomes/` must remain unavailable.**
   `test_no_generic_or_out_of_scope_api_routes` parametrizes
   `/api/v1/listings/`, `/api/v1/price-points/`, `/api/v1/raw-listings/`,
   `/api/v1/sku-aliases/`, and `/api/v1/outcomes/`, asserting each raises
   `Resolver404` and returns HTTP 404. This is a guardrail against generic model
   CRUD, consistent with `docs/06_PLANNING.md` Section 21 question 4.

2. **The `/api/v1/deal-flags/` payload shape is exact.**
   `test_dealflag_feed_has_exact_nested_derived_evidence_and_legacy_reason`
   asserts `set(result) == DEALFLAG_FIELDS`, where `DEALFLAG_FIELDS` is
   `{id, sku, listing, baseline_pricepoint, score, reason, flagged_at}`. No
   Outcome key may be added to the deal feed payload.

Route-stability assertions in TASK_023 and TASK_026 are inclusive - they assert
that named routes resolve to specific paths - so adding new, differently-named
routes is safe provided the forbidden paths above stay unavailable.

### 3.8 TASK_025 established the mutation pattern to follow

`listings/review_services.py` is the precedent: a shared service module with a
frozen result dataclass, a three-way error taxonomy
(`ReviewPermissionDenied` / `ReviewNotFound` / `ReviewConflict`), permission
re-checking with cache invalidation, `transaction.atomic()` with
`select_for_update`, an injectable `audit_writer`, and exactly one `LogEntry`
per successful decision. Both the DRF views and Django admin call it, so one
decision produces one audited mutation regardless of caller.

Phase 8 follows this pattern rather than building generic CRUD.

## 4. Lifecycle-state semantics

Phase 8 introduces **no status field**. All four states are expressed by the
existing columns and the existing check constraint:

| State | Representation |
|---|---|
| **Untracked** | no Outcome row exists for the DealFlag |
| **Skipped** | `acted=False`, `skip_reason` non-empty, all four money/time fields `NULL` |
| **Open position** | `acted=True`, `bought_at` and `bought_price` set, `sold_at` and `sold_price` `NULL`, `days_held` `NULL`, `realised_margin` `NULL` by SQL null arithmetic |
| **Closed position** | `acted=True`, all four money/time fields set, `days_held` derived, `realised_margin` DB-generated |

A read-only `lifecycle_state` string may be **computed at read time** from these
columns for presentation. It is a derived projection, never a persisted column,
and never an input to any mutation.

The permitted transitions are:

```text
Untracked -> Skipped          (skip)
Untracked -> Open position    (record_purchase)
Skipped   -> Open position    (record_purchase)
Open      -> Closed position  (record_sale)
```

Skipped is therefore a reversible decision, not a terminal state: a user may
later act on a DealFlag they previously skipped. No transition returns to
Untracked, because Phase 8 has no deletion lifecycle. Nothing transitions out of
Closed. `correct_purchase` and `correct_sale` change evidence within a state and
never move between states.

### 4.1 acted=True requires recorded acquisition

The database permits `acted=True` with `NULL` purchase fields. Application
policy forbids creating that state: an "intent to pursue" record carries no
evidence value and would make the open-position definition ambiguous. The
service must reject it. This is a stricter application policy layered over a
permissive schema, the same discipline TASK_006 applied when narrowing the
`manual_capture` input contract.

## 5. Authoritative service responsibilities

Phase 8 introduces `outcomes/outcome_services.py`, structurally mirroring
`listings/review_services.py`.

### 5.1 Domain operations

Exactly five governed operations. Each corresponds to one real-world event.

| Operation | Precondition | Effect |
|---|---|---|
| `skip` | untracked | creates `acted=False` + `skip_reason` |
| `record_purchase` | untracked **or** skipped | records `acted=True` + `bought_at` + `bought_price`; see Section 5.2 |
| `record_sale` | open position | sets `sold_at` + `sold_price`, derives `days_held` |
| `correct_purchase` | open or closed position | replaces `bought_at` + `bought_price` only |
| `correct_sale` | closed position | replaces `sold_at` + `sold_price` only |

Correction operations modify only their own transaction pair. `correct_purchase`
must recompute `days_held` when sale data is already present. `correct_sale`
must always recompute `days_held`. Neither may flip `acted`, write or clear
`skip_reason`, or move an Outcome between lifecycle states - a skipped Outcome
leaves that state only through `record_purchase`, never through a correction.

### 5.2 record_purchase and the skipped-to-open transition

A skip is a recorded decision, not a permanent verdict. A user may later decide
to act on a DealFlag they previously skipped, so `record_purchase` accepts two
preconditions and behaves differently in each.

**Untracked to open position.** No Outcome exists. The operation creates one
with `acted=True`, `bought_at`, and `bought_price` set, `skip_reason` absent per
the existing model contract, sale fields `NULL`, `days_held` `NULL`, and
`realised_margin` `NULL` through the generated column's own null arithmetic.
Audit: exactly one `ADDITION` entry.

**Skipped to open position.** An Outcome exists in the skipped state. The
operation updates it in place: `acted=True`, `skip_reason` cleared,
`bought_at` and `bought_price` recorded, sale fields remaining `NULL`,
`days_held` `NULL`, `realised_margin` `NULL`. Audit: exactly one `CHANGE`
entry, distinguishable in its change message from the creation case.

This is an explicit, audited, user-initiated change of a real-world decision.
It is **not** repair, and the plan must not be implemented or described as
reconciling drift: the service acts only because the user asked it to, and the
prior skip remains visible in the audit trail.

The `outcome_skip_reason_required_when_not_acted` constraint is satisfied
throughout, because `acted` becomes `True` in the same statement that clears
`skip_reason`.

`record_purchase` still fails with an explicit lifecycle conflict against an
open or closed Outcome, so a second purchase recording can never silently
overwrite existing acquisition evidence. Correcting a recorded purchase is what
`correct_purchase` is for.

No separate `unskip` operation is introduced. Nothing in the schema or the
committed constraints requires one, and a bare unskip would be able to produce
the `acted=True`-without-acquisition state that Section 4.1 forbids.

### 5.3 Service contract shape

- A frozen result dataclass, `OutcomeOperationResult`, carrying the operation
  name, `deal_flag_id`, `outcome_id`, the persisted field values, the derived
  `lifecycle_state`, and `realised_margin` as read back from the database.
- An error taxonomy mirroring TASK_025: `OutcomePermissionDenied`,
  `OutcomeNotFound`, `OutcomeConflict`, each carrying a stable `code` and
  `detail`.
- An injectable `audit_writer`, so admin and API produce one entry each.
- `realised_margin` must be re-read from the database after every mutation
  rather than computed, since the generated column is the only authority.

## 6. API design and route constraints

### 6.1 Routes

Operations nest under the owning DealFlag. This honors the frozen
`/api/v1/outcomes/` prohibition and expresses the real domain fact that an
Outcome has no identity independent of its DealFlag.

```text
GET  /api/v1/deal-flags/<int:pk>/outcome/
POST /api/v1/deal-flags/<int:pk>/outcome/skip/
POST /api/v1/deal-flags/<int:pk>/outcome/record-purchase/
POST /api/v1/deal-flags/<int:pk>/outcome/record-sale/
POST /api/v1/deal-flags/<int:pk>/outcome/correct-purchase/
POST /api/v1/deal-flags/<int:pk>/outcome/correct-sale/
```

Proposed route names, following the existing `api-v1:` convention:
`dealflag-outcome-detail`, `dealflag-outcome-skip`,
`dealflag-outcome-record-purchase`, `dealflag-outcome-record-sale`,
`dealflag-outcome-correct-purchase`, `dealflag-outcome-correct-sale`.

This matches the committed operation-oriented style already used by
`/api/v1/reviews/listings/<pk>/mark-reviewed-unresolved/` and
`/api/v1/reviews/listings/<pk>/confirm-sku/`: kebab-case operation segments,
trailing slash, `<int:pk>`, POST-only mutations.

Exact paths and names remain a HARDEN decision. The binding requirements are the
nested domain-specific design, the absence of any generic list/create/update/
delete endpoint, and the continued 404 of `/api/v1/outcomes/`.

### 6.2 What the API must not do

- must not add fields to `/api/v1/deal-flags/` (Section 3.7 item 2);
- must not introduce a reporting or aggregate endpoint, and specifically must
  not invent one to work around the frozen DealFlag payload;
- must not expose generic Outcome CRUD or a deletion route; and
- must not accept `days_held`, `realised_margin`, `acted`, or `lifecycle_state`
  as client input.

### 6.3 Request and response discipline

Requests use the committed `StrictRequestSerializer` behavior: unknown top-level
keys are rejected. Money arrives and leaves as Decimal strings; timestamps leave
as UTC through the committed `UTCDateTimeField`. Responses follow the TASK_025
operation-response shape rather than a model representation.

### 6.4 Deal-feed integration boundary

The deal feed payload is frozen and per-card Outcome fetches are forbidden as an
N+1 pattern. For Phase 8, Outcome state is loaded when the user enters the
specific DealFlag Outcome workflow. The deal feed itself is unchanged.

## 7. Admin behavior

The current bare `admin.site.register(Outcome)` (Section 3.4) is replaced with a
governed surface that reaches the same service functions the API uses.

Binding requirements:

- generic Outcome add is disabled - Outcomes are created only through `skip` or
  `record_purchase`;
- generic delete and bulk actions are disabled, matching the Phase 8 non-goal on
  deletion lifecycle;
- `realised_margin`, `days_held`, `acted`, and `deal_flag` are never directly
  editable;
- every mutation routes through `outcomes/outcome_services.py`, with identical
  permissions (Section 9), lifecycle validation (Sections 4 and 5), and conflict
  behavior (Section 10.2) to the API; and
- a useful read-only changelist remains for operator inspection, following the
  `list_display` / `list_filter` / `list_select_related` conventions already used
  in `pricing/admin.py`.

### 7.1 The untracked-DealFlag gap

An Outcome changelist can only expose operations for rows that already exist. It
therefore cannot, on its own, offer `skip` or `record_purchase` for an
**untracked** DealFlag, which is precisely where both creating operations begin.

Admin must consequently provide a governed entry point for untracked DealFlags
as well as for existing Outcomes:

| Starting state | Operations admin must expose |
|---|---|
| Untracked DealFlag | `skip`, `record_purchase` |
| Existing Outcome | `record_sale`, `correct_purchase`, `correct_sale`, and `record_purchase` where the Outcome is skipped |

The mechanism is deliberately not settled here - it is a TASK_028 HARDEN
inspection question, recorded in Section 18.1. Candidate mechanisms include
DealFlag admin actions, dedicated intermediate admin views, constrained
service-delegating admin forms, or another repository-consistent approach.

Whichever is chosen must satisfy all of the following:

- it calls the exact same shared service functions the API calls;
- it never exposes unrestricted generic Outcome CRUD;
- it does not let Django admin write its own automatic second `LogEntry`
  alongside the service's entry;
- it produces exactly one audit entry per successful domain operation; and
- it enforces the same permissions and lifecycle validation as the API.

The governing rule is TASK_025's: admin and API must reach identical domain
enforcement and produce one audit entry each.

## 8. React workflow

React is the primary Phase 8 product surface. Django admin is the operator
fallback.

The workflow is reached from a specific DealFlag and covers: viewing current
Outcome state including `realised_margin`; skipping with a reason; recording a
purchase; recording a sale; and correcting purchase or sale evidence.

Because a skip is reversible (Section 5.2), the skipped state must present
`record_purchase` as an available action rather than as a dead end, and must
make clear that acting on a previously skipped flag is a recorded decision
change rather than an undo.

Frontend rules:

- Decimal strings are preserved end to end and never parsed to float; the
  existing `formatMoneyDecimal` helper already enforces this;
- timestamps display through the existing Manila formatting helpers, while the
  wire format stays UTC;
- `realised_margin` is displayed exactly as served and never computed in the
  browser, including for the negative-margin case;
- CSRF uses the existing `bootstrapCsrf` / `currentCsrfToken` flow with the
  established 403 token-clearing behavior; and
- loading, permission-denied, not-found, validation, and conflict states are all
  represented, reusing the existing `AsyncStates` components where they fit.

## 9. Permissions

Phase 8 reuses the committed authenticated-staff session architecture. No JWT.
The default model permissions confirmed present are `view_outcome`,
`add_outcome`, `change_outcome`, and `delete_outcome`.

**Every Outcome operation requires `pricing.view_dealflag`**, in addition to its
own Outcome permission. An Outcome is evidence about a specific DealFlag and has
no meaning apart from it, so a user who may not see the parent flag must not be
able to read or change its Outcome - nor to infer the flag's existence from a
404-versus-409 difference.

| Operation | Required model permissions |
|---|---|
| read Outcome state | `pricing.view_dealflag`, `outcomes.view_outcome` |
| skip | `pricing.view_dealflag`, `outcomes.add_outcome` |
| record purchase | `pricing.view_dealflag`, `outcomes.add_outcome` |
| record sale | `pricing.view_dealflag`, `outcomes.change_outcome` |
| correct purchase | `pricing.view_dealflag`, `outcomes.change_outcome` |
| correct sale | `pricing.view_dealflag`, `outcomes.change_outcome` |

`record_purchase` requires `outcomes.add_outcome` for **both** of its
preconditions - the untracked-to-open creation and the skipped-to-open
transition of Section 5.2. The permission follows the operation, not the SQL
verb underneath it, so a caller cannot reach the transition with
`change_outcome` alone.

Every operation additionally requires an authenticated, active, staff user.

`delete_outcome` is deliberately unused: Phase 8 exposes no deletion workflow.

Enforcement lives in the shared service layer, not only in the DRF view, so the
admin caller receives identical enforcement. The service must invalidate
`_perm_cache`, `_user_perm_cache`, and `_group_perm_cache` before checking, so a
grant or revocation made after an earlier decision is observed - the behavior
already committed in `review_services._require_permissions`.

## 10. Integrity, concurrency, and conflict semantics

### 10.1 Transactions and locking

Each operation runs inside one `transaction.atomic()`. The service resolves the
DealFlag, then locks the Outcome row with `select_for_update` where one exists,
following `review_services._locked_listing`. No partial success is permitted.

### 10.2 Conflicts

Uniqueness is already guaranteed by the `OneToOneField`. The create path must
catch `IntegrityError` from a concurrent winner and convert it into an explicit
conflict rather than a 500, the pattern `_create_or_reuse_alias` established.
Section 10.3 constrains how that catch must be written.

| Situation | Code | HTTP |
|---|---|---|
| DealFlag does not exist | `deal_flag_not_found` | 404 |
| no Outcome exists on a read or correction | `outcome_not_found` | 404 |
| skip when an Outcome already exists | `outcome_already_exists` | 409 |
| record-purchase against an open or closed Outcome | `outcome_already_exists` | 409 |
| record-sale on a skipped or already-closed Outcome | `ineligible_outcome_state` | 409 |
| correct-purchase on a skipped Outcome | `ineligible_outcome_state` | 409 |
| correct-sale on an Outcome that is not closed | `ineligible_outcome_state` | 409 |
| permission failure | `permission_denied` | 403 |
| validation failure | `invalid_request` | 400 |

`record_purchase` against a **skipped** Outcome is not a conflict - it is the
governed transition of Section 5.2. Every other repeated-creation case remains a
conflict.

No operation silently repairs conflicting state, and no mutation changes
lifecycle state as a side effect. A skipped Outcome becomes purchased only
through an explicit `record_purchase` call that the user initiated; a closed
Outcome is never re-sold; and an open or closed Outcome never has its
acquisition evidence overwritten by a second `record_purchase`.

### 10.3 Savepoint-safe create-race handling

Returning a stable 409 is not sufficient on its own. In Django, an
`IntegrityError` raised inside an open transaction marks that transaction as
needing rollback, so catching it and then continuing to query or write on the
same connection raises `TransactionManagementError` instead of producing the
intended conflict response.

TASK_028 HARDEN must therefore freeze the concurrency pattern so that the
uniqueness race is caught inside an **inner savepoint** - a nested
`transaction.atomic()` block wrapping only the create - before the failure is
converted into `outcome_already_exists`. This is exactly the precedent
`review_services._create_or_reuse_alias` already sets, where the savepoint
comment records that it "keeps a uniqueness race from breaking the outer
decision".

The frozen acceptance tests should cover the case where the losing writer still
returns a clean 409 and the surrounding transaction remains usable, rather than
only asserting the status code.

This is a code-structure constraint. It introduces no schema change, no
optimistic-version column, and no additional locking beyond Section 10.1.

### 10.4 No optimistic versioning

Inspection found no evidence that optimistic version fields are needed. The tool
is single-operator, the operations are named and single-purpose rather than a
general PATCH, and row locking plus explicit lifecycle preconditions already make
outcomes deterministic. Adding a version column would require a migration that
Section 14 rules out. This is a decision, not a deferral.

### 10.5 Application-level validation

Because the database does not check them (Section 3.5), the service validates:

- `bought_price` and `sold_price` are non-negative and within
  `max_digits=12, decimal_places=2`;
- `skip_reason` is non-empty after stripping, matching the check constraint's
  intent rather than relying on the database to reject it; and
- `sold_at` is not earlier than `bought_at`.

The last item is load-bearing rather than cosmetic. A sale earlier than its
purchase would produce a negative `days_held` and be rejected by
`outcome_days_held_non_negative` as a raw `IntegrityError`. The service must
reject it first with a clean, stable error.

## 11. Timezone, Decimal, realised_margin, and days_held rules

### 11.1 Timestamps

`bought_at` and `sold_at` are **user-entered transaction times** - when the trade
actually happened - not server write times. This mirrors the committed semantics
of `RawListing.occurred_at` as distinct from `fetched_at`. Storage stays UTC per
`CLAUDE.md`; Asia/Manila remains display and calendar-boundary semantics only.

### 11.2 days_held

Derived by the service, never accepted from any client:

```text
days_held = manila_day(sold_at) - manila_day(bought_at)   # in whole days
```

`pricing.bucketing.manila_day` is the existing helper and must be reused rather
than duplicating timezone logic. Using Manila calendar days keeps holding period
consistent with the pricing-day boundary the rest of the system already uses.
A same-day purchase and sale yields `days_held = 0`.

`outcomes` already depends on `pricing` through the DealFlag foreign key, so this
introduces no new dependency direction.

`days_held` must be recomputed on `record_sale`, on `correct_sale`, and on
`correct_purchase` whenever sale data is already present.

### 11.3 Decimal

Money is Decimal end to end. `bought_price` and `sold_price` are entered and
stored as Decimal, serialized with `coerce_to_string=True` at
`max_digits=12, decimal_places=2`, and rendered from the served string. No float
appears in any layer.

### 11.4 realised_margin

Gross only:

```text
realised_margin = sold_price - bought_price
```

No fees, shipping, transport, meetup costs, or taxes. Net-margin adjustment
would require additional columns and a migration, and is deferred to a future
product decision rather than smuggled into Phase 8.

`realised_margin` is never supplied, never recomputed, and never validated
against an application-side calculation. It is read back from the database and
displayed.

## 12. Auditability and corrections

Outcome is mutable by design (Section 3.3), so auditability comes from records
rather than immutability.

Every successful mutation writes exactly one `LogEntry` inside the same
transaction, following `review_services._write_audit`:

| Operation | Action flag |
|---|---|
| skip | `ADDITION` |
| record purchase, untracked to open | `ADDITION` |
| record purchase, skipped to open | `CHANGE` |
| record sale | `CHANGE` |
| correct purchase | `CHANGE` |
| correct sale | `CHANGE` |

The action flag follows what actually happened to the row: `record_purchase`
writes `ADDITION` when it creates an Outcome and `CHANGE` when it transitions an
existing skipped one. Both cases must carry a change message that distinguishes
them, so the audit trail shows plainly that a previously skipped DealFlag was
later acted on and by whom.

Each entry targets the Outcome content type with a change message naming the
operation. A failed operation writes no entry, because the transaction rolls
back. Admin and API must produce one entry, never zero and never two - the
duplication risk TASK_025 called out and tested for both callers.

Corrections and the skipped-to-open transition are first-class audited
operations, not a generic edit surface. The audit trail, not field immutability,
is what makes a corrected price or a reversed skip defensible.

## 13. Interaction with TASK_027 demo data

TASK_027 requires no special case, and this falls out of the design rather than
being engineered around.

No Phase 8 code path creates an Outcome automatically. Outcomes exist only
because a user performed `skip` or `record_purchase`. Therefore, immediately
after `bootstrap_demo_data`:

```text
Outcome.objects.count() == 0
```

remains true, satisfying the frozen assertions in
`test_bootstrap_creates_no_outcome_and_pricing_replays_are_noops` and
`test_unchanged_second_run_is_an_exact_persisted_noop`.

TASK_027's demo DealFlags are ordinary untracked DealFlags. A user may later
record a genuine Outcome against one through the normal workflow, which is
correct: the demo corpus exists precisely to exercise the real pipeline. Phase 8
must not add demo-specific branching, and must not modify TASK_027 behavior,
its specification, or its frozen tests.

TASK_027's `_database_snapshot` helper enumerates Outcome's concrete fields
dynamically, so it tolerates schema evolution - but Section 14 rules out schema
change regardless.

## 14. Explicit non-goals

Phase 8 does not own and must not scaffold:

- alerts, Telegram, notifications, or any Phase 7 behavior;
- TipidPC, new ingestion sources, source research, scraping, or any external
  network access;
- pricing formula, threshold, baseline-window, resolver, normalization, or
  entity-resolution changes;
- schema changes or migrations - none is required, and a
  `makemigrations --check` diff is a signal that something was changed without
  justification;
- JWT, Celery, Redis, brokers, or background workers;
- browser-side authoritative pricing or margin computation;
- Outcome tracking for listings that never produced a DealFlag;
- generic Outcome list, create, update, or delete endpoints;
- any Outcome deletion lifecycle;
- portfolio analytics, ROI dashboards, cohort analysis, or aggregate
  realised-margin reporting;
- reporting endpoints created only to work around frozen API shapes;
- optimistic-version columns; and
- modifications to prior task specifications or frozen tests.

Aggregate reporting may be reconsidered later, once real Outcome data exists to
report on. Per-Outcome realised-margin display belongs to TASK_029.

## 15. TASK_028 - Governed Outcome services and API

**Purpose.** Establish the authoritative Outcome domain service, the nested
DealFlag Outcome read and mutation API, and the governed Django-admin fallback
that replaces the current bare registration.

**Likely surfaces.** `outcomes/outcome_services.py` (new), `outcomes/admin.py`,
`api/serializers.py`, `api/views.py`, `api/urls.py`, and a new frozen backend
acceptance module.

**Major acceptance behaviors.**

- the four lifecycle states of Section 4 and the permitted transitions between
  them, expressed without any status field;
- `acted=True` with no purchase evidence is rejected by the service;
- five governed operations with the preconditions in Section 5.1;
- `record_purchase` covers both the untracked-to-open creation and the
  skipped-to-open transition of Section 5.2, clearing `skip_reason` in the
  latter, while still conflicting against an open or closed Outcome so
  acquisition evidence is never silently overwritten;
- `days_held` service-derived on Manila days, recomputed on every relevant
  correction, and rejected if client-supplied;
- `realised_margin` never written and never accepted as input, and read back
  from the database after each mutation;
- application-level validation of prices, skip reason, and sale-after-purchase
  ordering, including a clean error instead of a raw `IntegrityError`;
- the permission matrix of Section 9 enforced in the service, including
  `pricing.view_dealflag` on every operation, verified for both the API and
  admin callers;
- transaction, locking, and the conflict matrix of Section 10.2;
- savepoint-safe create-race handling per Section 10.3, asserted by a test in
  which the losing writer receives a clean 409 and the surrounding transaction
  remains usable;
- a governed admin surface covering untracked DealFlags as well as existing
  Outcomes, per Section 7.1, with no generic Outcome CRUD and no duplicate
  admin-generated LogEntry;
- exactly one LogEntry per successful mutation, per Section 12, for both
  callers, with the correct action flag for each `record_purchase` case;
- Decimal-as-string and UTC serialization discipline;
- `/api/v1/outcomes/` still raises `Resolver404` and returns 404;
- `DEALFLAG_FIELDS` and the `/api/v1/deal-flags/` payload are unchanged; and
- `makemigrations --check --dry-run` reports no changes.

**Dependencies.** None beyond the committed state at `9c520a1`.

## 16. TASK_029 - React Outcome workflow

**Purpose.** Expose the governed Outcome workflow through the existing React
product interface.

**Likely surfaces.** `frontend/src/api/client.ts`, `frontend/src/api/types.ts`,
a new Outcome page or panel under `frontend/src/pages/`, `frontend/src/App.tsx`
routing, associated CSS modules, and a new frozen frontend acceptance module.

**Major acceptance behaviors.**

- the Outcome workflow is reachable from a specific DealFlag;
- skip, record purchase, record sale, correct purchase, and correct sale are all
  drivable from the UI;
- a skipped Outcome offers `record_purchase`, and driving it transitions the
  flag to an open position;
- current lifecycle state and `realised_margin` are displayed read-only,
  including the negative-margin case;
- Decimal strings survive end to end with no float conversion;
- timestamps display in Manila while the wire format stays UTC;
- CSRF and session integration reuse the committed bootstrap and retry flow;
- loading, permission-denied, not-found, validation, and conflict states are
  each represented; and
- existing Phase 6 deal, SKU, and review surfaces remain unchanged, and the
  `/api/v1/deal-flags/` payload is not extended.

**Dependencies.** TASK_028.

## 17. Validation strategy

Every Phase 8 task ends with the `CLAUDE.md` validation gate plus the frontend
gates established in Phase 6, all against PostgreSQL 16:

```text
docker compose exec web pytest -v <task acceptance module>
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py check
npm ci && npm test && npm run lint && npm run build
```

Compatibility suites that must stay green, and the reason each matters here:

- `tests/test_task_023_drf_foundation_and_read_api.py` - the forbidden-route and
  `DEALFLAG_FIELDS` assertions are the two hard constraints on this phase;
- `tests/test_task_025_shared_review_services_and_mutation_api.py` and
  `tests/test_task_026_*.py` - route stability and the shared-service and audit
  precedent;
- `tests/test_task_027_deterministic_demo_data_bootstrap.py` - the
  `outcomes: 0` assertions; and
- `outcomes/tests/test_task_004_outcomes.py` - the original schema contract,
  including generated-column and constraint behavior.

Manual PostgreSQL 16 validation must additionally exercise all four lifecycle
states, the skipped-to-open transition including the cleared `skip_reason` and
its `CHANGE` audit entry, a negative realised margin, an open position with
`NULL` margin, a same-day flip yielding `days_held = 0`, a correction that
recomputes `days_held`, a rejected second `record_purchase` against an open
position, and confirmation that a demo DealFlag from TASK_027 remains untracked
until a user acts on it.

## 18. Remaining genuine Unknowns

Inspection resolved the questions raised during the Phase 8 assessment, and the
owner has since settled deal-feed integration, `acted=True` semantics, gross
margin, Manila-day `days_held`, the correction model, the skipped-to-open
transition, and the `pricing.view_dealflag` permission floor. Two implementation
questions remain genuinely open and are inputs to the TASK_028 HARDEN pass
rather than blockers to this plan:

1. **Admin governed mutation mechanics.** Section 7 requires admin to reach the
   same service functions the API uses, for **both** untracked DealFlags and
   existing Outcomes, but deliberately does not settle the mechanism. An Outcome
   changelist cannot expose `skip` or `record_purchase` for a DealFlag that has
   no Outcome yet (Section 7.1), so some additional entry point is required.

   TASK_028 HARDEN must inspect and settle how admin exposes:

   - for an untracked DealFlag: `skip` and `record_purchase`, without enabling
     generic Outcome model creation; and
   - for an existing Outcome: `record_sale`, `correct_purchase`, `correct_sale`,
     and `record_purchase` where the Outcome is skipped.

   Candidate mechanisms include DealFlag admin actions, dedicated or
   intermediate admin views, constrained service-delegating admin forms, or
   another repository-consistent approach. Whichever is selected must call the
   same shared service functions as the API, never expose unrestricted generic
   Outcome CRUD, avoid Django admin's own automatic second LogEntry, produce
   exactly one audit entry per successful domain operation, and enforce the same
   permissions and lifecycle validation as the API.

   The deciding factor is which mechanism produces a single clean LogEntry
   without a competing admin-generated entry - the duplication risk TASK_025
   identified and tested for both callers. This should be settled by inspection
   during HARDEN, not guessed here.

2. **`days_held` inclusivity convention.** Manila-day subtraction yields an
   exclusive count, so a same-day flip is `0` and an overnight hold is `1`. The
   owner has approved the same-day-equals-zero case explicitly, which fixes the
   convention; what remains is confirming that the eventual UI label states the
   convention plainly enough that a reader cannot misread `0` as missing data.
   This is a presentation decision for TASK_029, not a domain question.

No unknown identified during inspection blocks TASK_028 HARDEN.
