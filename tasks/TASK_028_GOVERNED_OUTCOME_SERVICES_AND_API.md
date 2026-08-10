# TASK_028 - Governed Outcome services and API

## 1. Objective

Establish the authoritative governed write path for `Outcome`: one shared domain
service module, a nested DealFlag Outcome read/mutation API, and a governed
Django-admin fallback that replaces the current unrestricted registration.

TASK_028 is the first implementation task of roadmap Phase 8, which the owner is
executing before Phase 7. It owns no frontend behavior; the React workflow is
TASK_029.

## 2. Authority and existing behavior

This task follows:

- `CLAUDE.md`;
- `docs/08_PLANNING.md`, the approved Phase 8 planning artifact;
- TASK_004, which created the Outcome schema, its constraints, and the
  `realised_margin` generated column;
- TASK_023, whose frozen API tests bind two non-negotiable constraints;
- TASK_025, whose shared-service, permission, locking, conflict, and audit
  pattern this task reuses; and
- TASK_027, whose deterministic demo corpus must remain unaffected.

### 2.1 The gap being closed

`outcomes/admin.py` is currently a bare `admin.site.register(Outcome)`. Any
staff user holding the default `outcomes` permissions can already add, change,
and delete Outcome rows with no lifecycle validation, no field restriction, and
no governed audit. Outcome has no service module, no API, and no frontend.

TASK_028 therefore does not "activate an inert model". It replaces an
ungoverned mutation surface with a governed one.

## 3. Frozen artifacts and implementation boundary

### 3.1 HARDEN artifacts

- `tasks/TASK_028_GOVERNED_OUTCOME_SERVICES_AND_API.md`
- `tests/test_task_028_governed_outcome_services_and_api.py`

After owner approval neither may be modified to make implementation pass. A
genuine contradiction stops implementation for owner correction.

### 3.2 Authorized IMPLEMENT files

- `outcomes/outcome_services.py` (new)
- `outcomes/admin.py`
- `api/serializers.py`
- `api/views.py`
- `api/urls.py`

No model, migration, pricing service, resolver, ingestion importer, prior task
specification, prior frozen test, or frontend file is in scope. `pricing/admin.py`
is deliberately excluded; see Section 11.2.

## 4. Existing schema, verified

Inspection of `outcomes/models.py` and migrations `0001_initial` and
`0002_initial` confirms the fields and constraints TASK_028 builds on:

- `deal_flag` - `OneToOneField(DealFlag, on_delete=PROTECT, related_name="outcome")`;
- `acted` - non-nullable boolean;
- `skip_reason` - `TextField(null=True, blank=True)`;
- `bought_at`, `sold_at` - `DateTimeField(null=True, blank=True)`;
- `bought_price`, `sold_price` - `DecimalField(max_digits=12, decimal_places=2, null=True)`;
- `days_held` - `PositiveIntegerField(null=True, blank=True)`, a plain column;
- `realised_margin` - `GeneratedField(db_persist=True)` computing
  `sold_price - bought_price`;
- `outcome_skip_reason_required_when_not_acted` -
  `acted=True OR (skip_reason IS NOT NULL AND skip_reason != '')`; and
- `outcome_days_held_non_negative`.

The schema is sufficient. **No migration is expected, and
`makemigrations --check --dry-run` must report no changes.**

### 4.1 realised_margin is database-authoritative

TASK_004 Decision 1 verified that Postgres rejects a direct write and that
Django silently drops a caller-supplied value. TASK_028 must never accept it as
request input, compute it in Python, overwrite it, or treat an
application-computed value as authoritative. After every mutation the service
re-reads the persisted value from the database and returns that.

### 4.2 Money non-negativity precedent

Every money and quantity constraint in this repository is non-negative
(`raw_price >= 0`, `listing.price >= 0`, `launch_msrp >= 0`, `mad >= 0`,
`n_listings >= 0`, `days_held >= 0`). Only the non-money `Source.rate_limit` is
strictly positive. `ingestion.manual_capture._parse_price` likewise accepts
`0` and rejects negatives.

TASK_028 follows that precedent exactly: **`bought_price` and `sold_price` of
`0` are valid; negatives are rejected.** No strictly-positive rule is invented.

The JSON representation of money is a transport concern, not a schema or
service one; it is specified in Section 8.1.

## 5. Lifecycle contract

No persisted status field is added. The four states are read from existing
columns:

| State | Representation |
|---|---|
| Untracked | no Outcome row exists for the DealFlag |
| Skipped | `acted=False`, non-empty `skip_reason`, all four money/time fields NULL, `days_held` NULL, `realised_margin` NULL |
| Open | `acted=True`, `bought_at` and `bought_price` set, `sold_at` and `sold_price` NULL, `days_held` NULL, `realised_margin` NULL |
| Closed | `acted=True`, all four money/time fields set, `days_held` derived, `realised_margin` DB-generated |

Permitted transitions:

```text
Untracked -> Skipped   (skip)
Untracked -> Open      (record_purchase)
Skipped   -> Open      (record_purchase)
Open      -> Closed    (record_sale)
```

`correct_purchase` and `correct_sale` change evidence within a state and never
move between states. Nothing returns to Untracked; Phase 8 has no deletion
lifecycle.

`acted=True` without recorded purchase evidence is forbidden at the service
level even though the database permits it.

The derived `lifecycle_state` string is computed at read time and is never
persisted and never accepted as input. Its exact values are `untracked`,
`skipped`, `open`, and `closed`.

### 5.1 Invalid persisted state

The database schema is deliberately more permissive than the Phase 8 lifecycle.
Inspection of the live Postgres schema confirms Outcome carries only two check
constraints - `days_held >= 0` and
`outcome_skip_reason_required_when_not_acted`. **Nothing links `bought_at` to
`bought_price`, `sold_at` to `sold_price`, or `acted` to purchase evidence.**

Because Outcome has until now been exposed through unrestricted Django admin
(Section 2.1), rows may already exist that satisfy every database constraint yet
match none of the four approved lifecycle states. These are **invalid persisted
state**, and TASK_028 defines behavior rather than letting implementation guess.

A persisted Outcome that does not match exactly one approved lifecycle state is
invalid. Verified DB-valid but lifecycle-invalid shapes include:

| Case | Shape |
|---|---|
| A | `acted=True` with no valid purchase pair (`bought_at` and `bought_price` both NULL) |
| B | `acted=False` with a valid `skip_reason` **and** purchase or sale evidence present |
| C | a partial purchase pair - exactly one of `bought_at` / `bought_price` set |
| D | a partial sale pair - exactly one of `sold_at` / `sold_price` set |
| E | sale evidence present with no purchase evidence |

All of them produce one stable conflict:

```text
OutcomeConflict
code   = invalid_outcome_state
detail = Outcome is in an invalid persisted state and must be corrected manually.
status = 409
```

The service must **detect it, fail loudly, and stop**. It must never normalize,
repair, complete, or mutate such a row, and must write no audit entry.

`get_outcome_state()` encountering an invalid row raises the same conflict. It
must **not** project an `"invalid"` lifecycle state: the four approved values
remain the complete vocabulary, and an unreadable row is an operational fault to
surface, not a fifth state to render.

Every mutation validates persisted lifecycle state **after acquiring the row
lock and before modifying anything**, so a row that became invalid concurrently
is still caught.

Repairing such a row is deliberately outside TASK_028. No API or admin path
edits it; correction is a manual database or future-task concern.

## 6. Shared service contract

Create `outcomes.outcome_services` as the sole authority for Outcome reads and
mutations. It exposes exactly:

```python
get_outcome_state(*, actor, deal_flag_id: int) -> OutcomeState

skip(
    *, actor, deal_flag_id: int, skip_reason: str, audit_writer=None
) -> OutcomeOperationResult

record_purchase(
    *, actor, deal_flag_id: int, bought_at, bought_price, audit_writer=None
) -> OutcomeOperationResult

record_sale(
    *, actor, deal_flag_id: int, sold_at, sold_price, audit_writer=None
) -> OutcomeOperationResult

correct_purchase(
    *, actor, deal_flag_id: int, bought_at, bought_price, audit_writer=None
) -> OutcomeOperationResult

correct_sale(
    *, actor, deal_flag_id: int, sold_at, sold_price, audit_writer=None
) -> OutcomeOperationResult
```

`bought_price` and `sold_price` are `Decimal`. `bought_at` and `sold_at` are
aware `datetime` instants.

### 6.1 Result objects

`OutcomeState` and `OutcomeOperationResult` are immutable and carry:

- `deal_flag_id`;
- `outcome_id`, null when untracked;
- `lifecycle_state`;
- `acted`, null when untracked;
- `skip_reason`;
- `bought_at`, `bought_price`;
- `sold_at`, `sold_price`;
- `days_held`; and
- `realised_margin`, read back from the database.

`OutcomeOperationResult` additionally carries `operation`, whose approved values
are `skip`, `record_purchase`, `record_sale`, `correct_purchase`, and
`correct_sale`.

### 6.2 Audit writer

When the admin adapter supplies `audit_writer`, the service calls it exactly
once, after the mutation, inside the same transaction:

```python
audit_writer(outcome, change_message, action_flag)
```

`action_flag` is Django's `ADDITION` or `CHANGE`. When no callback is supplied
the service writes the equivalent `LogEntry` itself for the acting user.

### 6.3 Typed errors

The module owns typed errors with stable `code` and `detail`:

- `OutcomePermissionDenied`;
- `OutcomeNotFound`;
- `OutcomeConflict`; and
- `OutcomeValidationError`.

`OutcomeValidationError` covers service-level input rules that hold regardless
of caller - the Section 8 skip-reason, price, timestamp, and
sale-before-purchase rules. It exists because the service, not the serializer,
is the authority: the admin adapter and any future caller must be rejected by
the same checks, and a serializer-only rule would leave the service callable
with invalid values. It carries `code = invalid_request` and maps to HTTP 400.

Unexpected database and audit failures propagate after transaction rollback.

## 7. Permissions

Every operation, including the read, requires the actor to be:

```text
authenticated AND active AND staff AND has pricing.view_dealflag
```

In addition:

| Operation | Additional permission |
|---|---|
| `get_outcome_state` | `outcomes.view_outcome` |
| `skip` | `outcomes.add_outcome` |
| `record_purchase` | `outcomes.add_outcome` |
| `record_sale` | `outcomes.change_outcome` |
| `correct_purchase` | `outcomes.change_outcome` |
| `correct_sale` | `outcomes.change_outcome` |

`record_purchase` requires `outcomes.add_outcome` for **both** of its paths,
including `Skipped -> Open`. The permission follows the domain operation, not
the SQL verb, so the transition is unreachable with `change_outcome` alone.

`pricing.view_dealflag` is a floor on every operation because an Outcome is
evidence about a specific DealFlag and has no meaning apart from it.

The permission check runs **before** the DealFlag is resolved, so an actor
lacking `pricing.view_dealflag` always receives `permission_denied` and can
never distinguish an existing DealFlag from a missing one through these
endpoints.

Permission failure raises:

```text
code = permission_denied
detail = Active staff status and required permissions are required.
```

It writes no Outcome and no audit state.

### 7.1 Permission-cache refresh

Following the behavior committed in `review_services._require_permissions`, the
service clears `_perm_cache`, `_user_perm_cache`, and `_group_perm_cache` on the
actor before checking, so a grant or revocation made after an earlier decision
in the same request or process is observed. This is frozen here as externally
observable contract behavior, tested through a revoked permission rather than by
asserting a private helper name.

`delete_outcome` is deliberately unused. Phase 8 exposes no deletion workflow.

## 8. Validation

Validation is split across two layers with a deliberate, unambiguous boundary.
The shared service receives **typed domain values** and knows nothing about JSON.

### 8.1 Transport-adapter responsibility

The API views and the admin adapter own representation and parsing. They must
reject bad representations and produce typed inputs before calling the service:

- money arrives as a JSON **string**; a JSON number, boolean, or null is
  invalid. TASK_006 froze this rule for `manual_capture`
  (`test_json_numeric_price_writes_nothing`) because a JSON number reaches the
  parser as a float, and TASK_028 keeps the float path closed the same way;
- timestamps arrive as ISO-8601 strings carrying an **explicit UTC offset**. A
  naive string is invalid: these are user-entered transaction times, and
  silently assuming a timezone would corrupt the Manila-day derivation of
  `days_held`;
- unknown top-level keys are rejected through the committed
  `StrictRequestSerializer` behavior. `days_held`, `realised_margin`, `acted`,
  `lifecycle_state`, `outcome_id`, and `deal_flag_id` are never inputs and are
  unknown fields wherever supplied; and
- required fields are present.

The API uses the committed `StrictRequestSerializer` and `UTCDateTimeField`
conventions. The admin adapter may use Django forms or equivalent parsing, but
must arrive at the same typed values. Transport failures map to HTTP 400 with
`code = invalid_request`.

### 8.2 Shared-service responsibility

The service receives `Decimal` prices and aware `datetime` instants and enforces
domain rules that must hold for **every** caller, raising
`OutcomeValidationError`:

- a price is a `Decimal`;
- the `Decimal` is finite - `NaN` and infinities are rejected;
- a price is non-negative. Every money constraint in this repository is `>= 0`
  and `manual_capture._parse_price` accepts `0`, so **`0` is valid** and no
  strictly-positive rule is invented (Section 4.2);
- a price fits `DecimalField(max_digits=12, decimal_places=2)` - at most two
  decimal places and ten integral digits;
- timestamps are timezone-aware `datetime` values; a naive datetime is rejected;
- `skip_reason` is a string that is non-empty after stripping, and is persisted
  stripped; and
- `sold_at` is not earlier than `bought_at`, compared as instants, using the
  persisted counterpart where the request supplies only one side. This is
  rejected before the database can emit a raw
  `outcome_days_held_non_negative` violation.

The service is never told, and never asks, whether a `Decimal` originated from a
JSON string. Serializers are never the sole authority for a domain rule: a rule
enforced only in a serializer would leave the service callable with invalid
values by the admin adapter or any future caller.

## 9. days_held

`days_held` is application-derived and never client-supplied:

```text
days_held = (manila_day(sold_at) - manila_day(bought_at)).days
```

using the existing `pricing.bucketing.manila_day` helper rather than duplicating
timezone logic. Manila calendar days keep the holding period consistent with the
pricing-day boundary the rest of the system uses.

- same Manila calendar day yields `0`;
- the next Manila calendar day yields `1`; and
- a negative result is unreachable because Section 8.4 rejects the input first.

It is recomputed on `record_sale`, on `correct_sale`, and on `correct_purchase`
when the Outcome is Closed. On `correct_purchase` against an Open Outcome it
remains NULL.

`outcomes` already depends on `pricing` through the DealFlag foreign key, so no
new dependency direction is introduced.

## 10. Operations

### 10.1 skip

Allowed only `Untracked -> Skipped`. Creates the Outcome with `acted=False`, the
stripped `skip_reason`, and all four money/time fields NULL. Audit: one
`ADDITION`.

### 10.2 record_purchase

Two explicit paths.

**`Untracked -> Open`.** Creates the Outcome with `acted=True`, `bought_at` and
`bought_price` set, `skip_reason` NULL, sale fields NULL, `days_held` NULL, and
`realised_margin` NULL through the generated column's own null arithmetic.
Audit: one `ADDITION`.

**`Skipped -> Open`.** Updates the existing Outcome in place: `acted=True`,
`skip_reason` cleared to NULL, purchase evidence set, sale fields still NULL,
`days_held` NULL, `realised_margin` NULL. Audit: one `CHANGE`.

This is an explicit, audited, user-initiated change of a real-world decision. It
is not repair and must not be implemented as reconciling drift. The
`outcome_skip_reason_required_when_not_acted` constraint holds throughout
because `acted` becomes true in the same write that clears `skip_reason`.

`record_purchase` conflicts against an Open or Closed Outcome, so a second
purchase recording can never silently overwrite acquisition evidence.
`correct_purchase` is the operation for that.

No separate `unskip` operation exists; a bare unskip could produce the
`acted=True`-without-acquisition state Section 5 forbids.

### 10.3 record_sale

Allowed only `Open -> Closed`. Sets sale evidence, derives `days_held`, never
writes `realised_margin`, and re-reads the generated margin after persistence.
Audit: one `CHANGE`.

### 10.4 correct_purchase

Allowed `Open -> Open` and `Closed -> Closed`. Replaces the purchase pair only.
When Closed, `days_held` is recomputed from the corrected `bought_at`. Sale
evidence is unchanged. The generated margin updates naturally from the persisted
prices. Conflicts against Skipped. Audit: one `CHANGE`.

### 10.5 correct_sale

Allowed only `Closed -> Closed`. Replaces the sale pair only, recomputes
`days_held`, leaves purchase evidence unchanged, and lets the generated margin
update naturally. Audit: one `CHANGE`.

## 11. Django admin

### 11.1 Generic surface

`OutcomeAdmin` replaces the bare registration and disables generic mutation
entirely, reusing the committed read-only evidence pattern from
`pricing/admin.py`:

- `has_add_permission`, `has_change_permission`, and `has_delete_permission`
  return False;
- `actions` is None;
- every model field is read-only; and
- a useful changelist remains for operator inspection, following the existing
  `list_display` / `list_filter` / `list_select_related` conventions.

### 11.2 Chosen governed mechanism

**Dedicated intermediate admin views registered on `OutcomeAdmin.get_urls()`,
keyed by DealFlag primary key, plus one governed untracked worklist view.**

This is the mechanism the HARDEN pass settles on, and the reasoning is recorded
because `docs/08_PLANNING.md` Section 18.1 left it open:

1. **It solves the untracked-entry problem.** An Outcome changelist cannot
   expose `skip` or `record_purchase` for a DealFlag that has no Outcome row.
   Keying the views by `deal_flag_id` rather than `outcome_id`, and adding a
   worklist of DealFlags without an Outcome, gives the operator a real entry
   point for both creating operations.
2. **It structurally eliminates duplicate audit entries.** TASK_025 needed a
   `_listing_review_service_log_pending` flag because `ListingAdmin.save_model`
   sits inside ModelAdmin's change-form flow, where ModelAdmin logs *after*
   `save_model` returns. Custom `get_urls()` views have no such automatic
   logging hook, so no suppression flag is required and the single-LogEntry
   requirement cannot be violated by a framework hook. This is the decisive
   argument for this design over a service-delegating `ModelForm`.
3. **It reuses a committed precedent.** `ListingAdmin.mark_reviewed_unresolved_view`
   already establishes the exact shape: `get_urls()` plus
   `admin_site.admin_view()`, POST-only, one service call with an
   `audit_writer`, then `message_user` and a redirect.
4. **It keeps TASK_028 inside its authorized files.** All admin work lives in
   `outcomes/admin.py`. `pricing/admin.py` is not modified, and no
   `pricing -> outcomes` import is introduced.

Registered admin URL names:

```text
admin:outcomes_outcome_untracked
admin:outcomes_outcome_skip
admin:outcomes_outcome_record_purchase
admin:outcomes_outcome_record_sale
admin:outcomes_outcome_correct_purchase
admin:outcomes_outcome_correct_sale
```

The worklist view is GET-only. The five operation views are POST-only and return
405 for any other method. Each takes `deal_flag_id`.

Each operation view calls the matching shared service function with an
`audit_writer` that dispatches to the ModelAdmin's own `log_addition` or
`log_change` for the **Outcome** object, so the entry carries the Outcome
content type. Service errors map to `PermissionDenied`, `Http404`, and a
warning message plus redirect for conflicts, exactly as
`mark_reviewed_unresolved_view` does.

The admin adapter performs presentation work only. It retains no independent
lifecycle, permission, locking, transaction, or audit implementation.

## 12. API

### 12.1 Routes

Nested under the owning DealFlag, because TASK_023 freezes `/api/v1/outcomes/`
as unavailable and because an Outcome has no identity independent of its
DealFlag:

```text
GET  /api/v1/deal-flags/<int:pk>/outcome/
POST /api/v1/deal-flags/<int:pk>/outcome/skip/
POST /api/v1/deal-flags/<int:pk>/outcome/record-purchase/
POST /api/v1/deal-flags/<int:pk>/outcome/record-sale/
POST /api/v1/deal-flags/<int:pk>/outcome/correct-purchase/
POST /api/v1/deal-flags/<int:pk>/outcome/correct-sale/
```

Names:

```text
api-v1:dealflag-outcome-detail
api-v1:dealflag-outcome-skip
api-v1:dealflag-outcome-record-purchase
api-v1:dealflag-outcome-record-sale
api-v1:dealflag-outcome-correct-purchase
api-v1:dealflag-outcome-correct-sale
```

The detail route allows GET only; the operation routes allow POST only. They use
`JSONParser`, existing DRF `SessionAuthentication`, and same-origin Django CSRF
protection. No endpoint is CSRF-exempt.

There is no Outcome list, generic create, PATCH, PUT, DELETE, or aggregate or
reporting endpoint. `/api/v1/outcomes/` continues to raise `Resolver404` and
return 404, and the `/api/v1/deal-flags/` payload keeps its exact frozen field
set.

### 12.2 GET behavior for an untracked DealFlag

**A GET against a DealFlag with no Outcome returns HTTP 200 with
`lifecycle_state = "untracked"` and null Outcome fields. It does not return
404.**

This is a HARDEN-level contract decision, and the reasoning is:

- the addressed resource is the DealFlag's *outcome state*, not the Outcome row,
  and every DealFlag always has one of the four states;
- `untracked` is a first-class approved lifecycle state in
  `docs/08_PLANNING.md` Section 4, not an absence — that document also describes
  TASK_027's demo flags as "ordinary untracked DealFlags";
- TASK_029 must render the untracked state and offer Skip and Record Purchase
  from it, so returning 404 would force the client to treat a normal expected
  state as an error; and
- it keeps 404 meaning exactly one thing on these endpoints — the DealFlag does
  not exist — which preserves the Section 7 property that permission failures
  are indistinguishable from missing rows.

404 is therefore reserved for a missing DealFlag on the detail route, and for a
missing Outcome on the three operations that require one to exist.

### 12.3 Representation

The detail response is exactly:

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

A mutation response is the same object plus `operation`, for example:

```json
{
  "operation": "record_sale",
  "deal_flag_id": 12,
  "outcome_id": 5,
  "lifecycle_state": "closed",
  "acted": true,
  "skip_reason": null,
  "bought_at": "2026-06-15T04:00:00Z",
  "bought_price": "12500.00",
  "sold_at": "2026-06-16T04:00:00Z",
  "sold_price": "14000.00",
  "days_held": 1,
  "realised_margin": "1500.00"
}
```

Timestamps are UTC ISO-8601 instants through the committed `UTCDateTimeField`.
Every money value is a string. `days_held` is an integer. No RawListing field,
Listing field, SKU field, or pricing evidence appears; those remain owned by the
existing DealFlag and Listing APIs.

### 12.4 Request bodies

```text
skip              {"skip_reason": "..."}
record-purchase   {"bought_at": "...", "bought_price": "..."}
record-sale       {"sold_at": "...", "sold_price": "..."}
correct-purchase  {"bought_at": "...", "bought_price": "..."}
correct-sale      {"sold_at": "...", "sold_price": "..."}
```

All listed fields are required. Unknown fields are invalid.

### 12.5 Status mapping

| Condition | Status |
|---|---:|
| success | 200 |
| malformed JSON, invalid or extra fields, sale before purchase | 400 |
| anonymous, inactive, non-staff, permission denial, or CSRF failure | 403 |
| missing DealFlag, or missing Outcome where required | 404 |
| lifecycle conflict | 409 |
| unsupported method | 405 |
| non-JSON media type | 415 |
| unexpected failure | 500 |

Service-owned 404 and 409 responses are exact `code` plus `detail` objects.
Serializer validation returns `code = invalid_request`,
`detail = Request validation failed.`, and an `errors` object keyed by the
invalid transport field. Framework-level CSRF, parse, authentication, and method
failures retain DRF's response; tests freeze status and absence of writes rather
than wording.

## 13. Conflict matrix

Stable codes, frozen:

| Situation | Code | Status |
|---|---|---:|
| DealFlag does not exist | `deal_flag_not_found` | 404 |
| `record_sale`, `correct_purchase`, or `correct_sale` with no Outcome | `outcome_not_found` | 404 |
| `skip` when any Outcome exists | `outcome_already_exists` | 409 |
| `record_purchase` against Open | `outcome_already_exists` | 409 |
| `record_purchase` against Closed | `outcome_already_exists` | 409 |
| `record_sale` against Skipped | `ineligible_outcome_state` | 409 |
| `record_sale` against Closed | `ineligible_outcome_state` | 409 |
| `correct_purchase` against Skipped | `ineligible_outcome_state` | 409 |
| `correct_sale` against Skipped | `ineligible_outcome_state` | 409 |
| `correct_sale` against Open | `ineligible_outcome_state` | 409 |
| any read or mutation against an invalid persisted row (Section 5.1) | `invalid_outcome_state` | 409 |

`record_purchase` against a Skipped Outcome is **not** a conflict; it is the
governed transition of Section 10.2.

Details:

```text
deal_flag_not_found      / Deal flag not found.
outcome_not_found        / Outcome not found.
outcome_already_exists   / An outcome already exists for this deal flag.
ineligible_outcome_state / Outcome is not in an eligible state for this operation.
invalid_outcome_state    / Outcome is in an invalid persisted state and must be corrected manually.
```

No operation silently repairs conflicting state, and no mutation changes
lifecycle state as a side effect.

## 14. Transaction, locking, and concurrency

Each operation performs one `transaction.atomic()`. Permission and request
validation may run first. The service then resolves the DealFlag and acquires
the existing Outcome with PostgreSQL `SELECT ... FOR UPDATE`. **Lifecycle
eligibility is re-checked only after the lock is acquired**, so two concurrent
mutations serialize and the later one sees the committed state.

### 14.1 Savepoint-safe creation race

Two concurrent requests may race to create the one Outcome for a DealFlag. The
`OneToOneField` uniqueness is the final database guard.

Catching `IntegrityError` inside the sole outer atomic block and continuing is
**not acceptable**: the transaction is already marked for rollback, so any
further query raises `TransactionManagementError` instead of producing the
intended conflict.

The creating path must therefore wrap only the insert in an **inner savepoint**
- a nested `transaction.atomic()` - catch the uniqueness violation there, and
then convert it into the stable conflict, re-reading the winning row as needed.
This is exactly the precedent `review_services._create_or_reuse_alias`
establishes, whose comment records that the savepoint "keeps a uniqueness race
from breaking the outer decision".

The frozen tests prove both that the race becomes a stable 409 rather than a
500, and that the surrounding transaction remains usable afterward.

No optimistic-version column, advisory lock, retry count, index, or schema field
is added.

## 15. Audit contract

Every successful operation creates exactly one Django admin `LogEntry` with:

- `user_id` equal to the acting user;
- the **Outcome** content type;
- `object_id` equal to the Outcome primary key as text;
- `object_repr` equal to `str(outcome)` after the decision;
- the action flag below; and
- the exact change message below.

| Operation | Action flag | Change message |
|---|---|---|
| `skip` | `ADDITION` | `Skipped deal flag.` |
| `record_purchase`, Untracked to Open | `ADDITION` | `Recorded purchase.` |
| `record_purchase`, Skipped to Open | `CHANGE` | `Recorded purchase after previously skipping.` |
| `record_sale` | `CHANGE` | `Recorded sale.` |
| `correct_purchase` | `CHANGE` | `Corrected purchase evidence.` |
| `correct_sale` | `CHANGE` | `Corrected sale evidence.` |

These messages are **exact and frozen**, and the acceptance module asserts them
verbatim. This follows the established repository precedent: TASK_025 froze
`Marked reviewed unresolved.` and `Confirmed or corrected SKU.` in its
specification and enforces both strings in its frozen tests. The audit trail is
the only durable record of a mutable Outcome (Section 4.3 of
`docs/08_PLANNING.md`), so its wording carries real product value rather than
being incidental.

The two `record_purchase` paths are deliberately distinguishable, so the audit
trail shows plainly that a previously skipped DealFlag was later acted on.

Rejected or rolled-back operations create no entry. Admin and API must each
produce exactly one entry per decision, never zero and never two.

## 16. TASK_027 and adjacent-domain boundary

No TASK_028 code path creates an Outcome automatically. Outcomes exist only
because an actor invoked `skip` or `record_purchase`. Immediately after
`bootstrap_demo_data`:

```text
Outcome.objects.count() == 0
```

must still hold. Demo DealFlags are ordinary untracked DealFlags and may later
receive an Outcome only through explicit user action. No demo-specific branching
is added, and TASK_027's behavior, specification, and frozen tests are untouched.

TASK_028 creates or changes no RawListing, Listing, Sku, SkuAlias, Source,
PricePoint, DealFlag, or Swap state. Reads of DealFlag are permitted; writes are
not. Pricing remains authoritative only through `price_listings`.

## 17. Frozen acceptance criteria

The authoritative executable artifact is:

```text
tests/test_task_028_governed_outcome_services_and_api.py
```

It freezes: the four lifecycle states and permitted transitions; **invalid
persisted state detection on both read and every mutation, with no repair and no
audit**; all five operations including both `record_purchase` paths and their
distinct action flags; the **transport-versus-service validation split** of
Section 8, with JSON-representation rules proven at the transport layer and
typed-`Decimal`/aware-`datetime` domain rules proven by calling the service
directly; the non-negative and zero-valid money rule; UTC storage; Manila
`days_held` including the same-day zero case; sale-before-purchase rejection;
negative realised margin; `realised_margin` as non-writable and
database-sourced; correction recomputation; the full permission matrix including
the `pricing.view_dealflag` floor and permission-cache refresh; missing-DealFlag
404 on **every** operation; the conflict matrix; the status mapping including
405 and 415; **session CSRF enforcement on a real mutation endpoint, both
rejected without a token and accepted with one**; nested route names;
`/api/v1/outcomes/` remaining 404; the unchanged DealFlag feed field set; one
LogEntry per success and zero per failure with **exact change messages**;
governed admin views performing **all five** domain operations with the correct
persisted state, action flag, and message; unavailable generic admin
add/change/delete; the untracked admin entry point; the savepoint-safe creation
race; TASK_027 bootstrap producing zero Outcomes; and the absence of any schema
change.

## 18. Expected failing HARDEN baseline

At HARDEN time `outcomes/outcome_services.py`, the API routes, and the governed
admin do not exist, so contract tests fail. Preservation and compatibility
assertions - the frozen TASK_023 constraints, the existing Outcome schema and
constraint behavior, TASK_027's zero-Outcome bootstrap, and the no-migration
check - must already pass.

A failure caused by an incorrect assumption in this specification is a
contradiction to report, not a reason to change the repository.

## 19. Implementation validation

```text
docker compose exec web pytest -v tests/test_task_028_governed_outcome_services_and_api.py
docker compose exec web pytest -v tests/test_task_023_drf_foundation_and_read_api.py tests/test_task_025_shared_review_services_and_mutation_api.py tests/test_task_026_react_review_workflow_and_same_origin_integration.py tests/test_task_027_deterministic_demo_data_bootstrap.py outcomes/tests/test_task_004_outcomes.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py check
```

The existing frontend test, lint, and production-build commands must also run
even though TASK_028 changes no frontend file.

Manual PostgreSQL 16 validation must exercise all four lifecycle states, the
skipped-to-open transition including the cleared `skip_reason` and its `CHANGE`
entry, a negative realised margin, an open position with NULL margin, a same-day
flip yielding `days_held = 0`, a correction that recomputes `days_held`, a
rejected second `record_purchase` against an open position, and confirmation
that a TASK_027 demo DealFlag remains untracked until a user acts on it.

## 20. Explicit non-goals

TASK_028 does not include or scaffold: TASK_029 React work; alerts, Telegram, or
notifications; TipidPC, new sources, scraping, or external network access;
pricing formula, resolver, or entity-resolution changes; schema changes or
migrations; JWT, Celery, Redis, brokers, or background workers; generic Outcome
CRUD; any Outcome deletion workflow; portfolio analytics, ROI dashboards,
aggregate realised-margin reporting, or reporting endpoints; browser-side margin
calculation; or modifications to prior task specifications or frozen tests.

## 21. Stop conditions

Implementation stops and reports rather than improvising if: the Outcome schema
materially contradicts this contract; a frozen TASK_023, TASK_025, or TASK_027
assertion cannot hold; the single-LogEntry requirement proves impossible under
the Section 11.2 mechanism; or a migration turns out to be genuinely
unavoidable.

No implementation begins until this specification and its frozen acceptance
module receive explicit owner approval.
