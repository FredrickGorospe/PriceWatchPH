# TASK_025 - Add shared review services and mutation API

## 1. Objective

Extract the two approved Phase 4 Listing review decisions into one shared
application-service boundary and expose them through narrow, session-authenticated
DRF mutation endpoints. Django admin and DRF become adapters over the same
transactional behavior.

TASK_025 owns Phase 6 Capability C only. It does not add the React review queue,
review evidence reads, authentication pages, bundle integration, or SPA fallback.

## 2. Authority and existing behavior

This task follows:

- `CLAUDE.md` and `docs/ROADMAP.md`;
- `docs/06_PLANNING.md`, especially Sections 9, 10, and 13 through 15;
- TASK_016's durable `reviewed_unresolved_at` state;
- TASK_017's constrained review transitions, permissions, row lock, and audit;
- TASK_018's explicit alias opt-in, normalization, conflicts, and atomicity;
- TASK_023's DRF session-authentication and derived-read contracts; and
- TASK_024's read-only frontend API boundary.

The repository already proves these facts:

- review mutation requires an authenticated, active staff user with
  `listings.change_listing`;
- alias opt-in additionally requires `catalogue.add_skualias`;
- confirmation without alias needs no catalogue permission beyond Listing
  change permission;
- a reviewed-unresolved decision changes only `reviewed_unresolved_at`;
- confirmation or correction changes only the five approved decision fields;
- alias text comes only from immutable `RawListing.raw_title` and normalization
  calls the committed `normalise_title()` function;
- `SkuAlias.normalised_text` is globally unique;
- the existing admin operations are atomic with one Listing change `LogEntry`;
  and
- no TASK_025 schema change is needed.

## 3. Frozen artifacts and implementation boundary

### 3.1 HARDEN artifacts

After owner approval these files are frozen:

- `tasks/TASK_025_SHARED_REVIEW_SERVICES_AND_MUTATION_API.md`; and
- `tests/test_task_025_shared_review_services_and_mutation_api.py`.

They must not be edited during implementation. A contradiction stops the task
for owner correction.

### 3.2 Authorized IMPLEMENT files

Implementation may create or modify only:

- `listings/review_services.py`;
- `listings/admin.py`;
- `api/serializers.py`;
- `api/views.py`; and
- `api/urls.py`.

No model, migration, settings, frontend, template, resolver, management command,
Docker, dependency, prior task/test, or planning file is authorized.

## 4. Shared service contract

Create `listings.review_services` as the sole authority for review mutations.
It exposes exactly:

```python
mark_reviewed_unresolved(
    *, actor, listing_id: int, audit_writer=None
) -> ReviewOperationResult

confirm_listing_sku(
    *, actor, listing_id: int, sku_id: int, create_alias: bool = False,
    audit_writer=None
) -> ReviewOperationResult
```

`audit_writer`, when supplied by the admin adapter, is called as:

```python
audit_writer(listing, change_message)
```

The service still owns when that callback runs: once, after the mutation and
optional alias work, inside the same transaction. When no callback is supplied,
the service writes the equivalent `LogEntry` itself for the acting user.

`ReviewOperationResult` is an immutable result containing:

- `operation`;
- `listing_id`;
- `sku_id`;
- `resolution_method`;
- `resolution_confidence`;
- `resolved_at`;
- `reviewed_unresolved_at`;
- `alias_status`; and
- `alias_id`.

Approved `operation` values are `mark_reviewed_unresolved` and `confirm_sku`.
Approved `alias_status` values are `not_requested`, `created`, and
`already_exists`. The reviewed-unresolved result uses `not_requested` and a
null `alias_id`.

The module owns typed service errors with stable `code` and `detail` values:

- `ReviewPermissionDenied`;
- `ReviewNotFound`; and
- `ReviewConflict`.

Unexpected database and audit failures propagate after transaction rollback.

## 5. Permissions

Both services enforce authorization themselves. Adapters may reject earlier for
better feedback, but cannot weaken the shared check.

The actor must be:

```text
authenticated
AND active
AND staff
AND has listings.change_listing
```

When `create_alias` is true, the actor must additionally have:

```text
catalogue.add_skualias
```

No `view_listing`, `view_sku`, or custom review permission is required for a
mutation. This preserves TASK_017 and TASK_018, where Listing change permission
alone authorizes confirmation without alias.

Permission failure raises:

```text
code = permission_denied
detail = Active staff status and required permissions are required.
```

It writes no Listing, alias, or audit state.

## 6. Transaction, locking, and concurrent state

Each service performs one `transaction.atomic()` operation and acquires the
target Listing with PostgreSQL `SELECT ... FOR UPDATE`. Permission and basic
input checks may run first, but mutable Listing eligibility is checked only
after the lock is acquired.

Confirmation also resolves the selected existing SKU inside the operation.
Missing objects use:

```text
listing_not_found / Listing not found.
sku_not_found / SKU not found.
```

Concurrent review requests are serialized by the Listing row lock:

- reviewed-unresolved re-checks its eligibility against the newly locked row;
- if a competing decision made it ineligible, the later request returns an
  `ineligible_review_state` conflict and changes nothing;
- confirmation is an explicit correction operation for any existing Listing,
  so two valid confirmations serialize and the later explicit request applies
  to the latest row and creates its own audit entry; and
- no optimistic version field is invented. The approved schema and admin form
  have no version token.

Concurrent alias creation relies on the existing unique
`SkuAlias.normalised_text` constraint. An integrity race is handled within a
savepoint, then re-read:

- the selected-SKU winner is `already_exists` and may proceed;
- a different-SKU winner becomes `alias_conflict`; and
- no broken transaction or partial Listing update remains.

No arbitrary retry count, advisory lock, new index, or schema field is added.

## 7. Reviewed-unresolved operation

Eligibility remains exactly the approved TASK_017 predicate:

```text
Listing.sku IS NULL
AND Listing.resolution_method IN (unresolved, fuzzy_match)
```

`fuzzy_match` is historical compatibility only. No task emits a new fuzzy
result.

Success changes exactly:

```text
reviewed_unresolved_at = timezone.now()
```

It preserves the SKU null, resolution method and confidence, `resolved_at`, all
Listing evidence, and the RawListing relationship and contents. It creates no
alias and invokes no resolver.

Because the approved eligibility predicate does not test the marker, a direct
repeat request remains a new successful review decision. It refreshes the
marker and creates exactly one new audit entry. The row is nevertheless absent
from the default queue after the first success because queue membership also
requires `reviewed_unresolved_at IS NULL`.

An ineligible locked row raises:

```text
code = ineligible_review_state
detail = Listing is not eligible to be marked reviewed unresolved.
```

## 8. Confirmation and correction operation

The selected SKU must already exist. Success changes exactly:

```text
Listing.sku = selected SKU
Listing.resolution_method = human_confirmed
Listing.resolution_confidence = Decimal("1.0000")
Listing.resolved_at = timezone.now()
Listing.reviewed_unresolved_at = NULL
```

It preserves RawListing, price, condition, location, observed time, price kind,
and trade side. It never creates a SKU or invokes the resolver.

Confirmation may operate on an unresolved, historical fuzzy, exact-alias, or
already human-confirmed Listing. Reconfirming the same SKU and correcting to a
different existing SKU both refresh `resolved_at` and create one audit entry.
This preserves the explicit all-listings correction surface from TASK_017.

## 9. Optional alias contract

`create_alias` is a strict Boolean transport value and defaults to false only
when omitted from the confirmation JSON body. No truthy strings or integers are
accepted by the API.

When false, no alias query may change catalogue state and `alias_status` is
`not_requested`.

When true, values are derived only as follows:

```text
sku = selected SKU
alias_text = Listing.raw_listing.raw_title
normalised_text = normalise_title(Listing.raw_listing.raw_title)
source_of_truth = human_confirmed
```

Outcomes by normalized title:

| Existing alias | Outcome | Listing decision |
|---|---|---|
| none | create one, `created` | succeeds |
| same selected SKU | preserve it, `already_exists` | succeeds |
| different SKU | `alias_conflict` | rolls back |

The conflict is:

```text
code = alias_conflict
detail = The normalized title is already an alias for a different SKU.
```

No alias is repointed or rewritten. Alias failure and audit failure roll back
the complete Listing and alias operation. Other Listings are not resolved
automatically.

## 10. Audit contract

Every successful operation creates exactly one Django admin `LogEntry` with:

- `user_id` equal to the acting user;
- Listing content type;
- `object_id` equal to the Listing primary key as text;
- `object_repr` equal to `str(listing)` after the decision;
- `action_flag = CHANGE`; and
- one exact change message.

Messages are:

```text
Marked reviewed unresolved.
Confirmed or corrected SKU.
```

Alias creation is part of the confirmation decision and does not create a
second alias audit entry. Rejected or rolled-back operations create no entry.

The admin adapter supplies its normal `log_change` behavior as the service
audit writer so the frozen TASK_017/TASK_018 rollback tests remain authoritative.
It suppresses only the later duplicate ModelAdmin log hook for a successfully
service-routed confirmation. Existing unrelated admin logging is unchanged.

## 11. Admin adapter contract

The existing admin form, URLs, evidence, queue, messages, redirects, and exact
`sku` plus `create_alias` fields remain operational.

Both admin review paths call the functions through the shared module object:

```python
from listings import review_services
```

The admin adapter performs form and presentation work only. It does not retain
an independent state-transition, alias, permission, locking, transaction, or
audit implementation.

## 12. Mutation API

Add exactly two operation routes:

```text
POST /api/v1/reviews/listings/<int:pk>/mark-reviewed-unresolved/
POST /api/v1/reviews/listings/<int:pk>/confirm-sku/
```

Names are:

```text
api-v1:review-mark-reviewed-unresolved
api-v1:review-confirm-sku
```

Only `POST` is allowed. The endpoints use `JSONParser`, existing DRF
`SessionAuthentication`, and same-origin Django CSRF protection. They expose no
GET collection/detail, PATCH, PUT, DELETE, generic Listing mutation, alias
mutation, review queue, or RawListing endpoint.

The reviewed-unresolved body must be exactly an empty JSON object.

The confirmation body is:

```json
{
  "sku_id": 17,
  "create_alias": false
}
```

`sku_id` is required and must be a positive integer. `create_alias` may be
omitted and then means false. Unknown fields, non-Boolean alias values, missing
SKU, arrays, and non-object JSON are invalid.

## 13. API responses and errors

Reviewed-unresolved success returns HTTP 200:

```json
{
  "operation": "mark_reviewed_unresolved",
  "listing_id": 23,
  "reviewed_unresolved_at": "2026-08-09T01:02:03Z"
}
```

Confirmation success returns HTTP 200:

```json
{
  "operation": "confirm_sku",
  "listing_id": 23,
  "sku_id": 17,
  "resolution_method": "human_confirmed",
  "resolution_confidence": "1.0000",
  "resolved_at": "2026-08-09T01:02:03Z",
  "reviewed_unresolved_at": null,
  "alias_status": "not_requested"
}
```

Timestamps are UTC ISO-8601 instants and Decimal confidence remains a string.
Responses contain no RawListing field.

Status mapping is:

| Condition | Status |
|---|---:|
| success | 200 |
| malformed JSON or invalid/extra fields | 400 |
| anonymous, inactive, non-staff, permission denial, or CSRF failure | 403 |
| missing Listing or selected SKU | 404 |
| ineligible reviewed-unresolved state or alias conflict | 409 |
| unsupported method | 405 |
| non-JSON media type | 415 |
| unexpected failure | 500 |

Service-owned 404 and 409 responses are exact `code` plus `detail` objects
using the values in this specification. Serializer validation returns
`code = invalid_request`, `detail = Request validation failed.`, and an
`errors` object keyed by the invalid transport field. Framework-level CSRF,
parse, authentication, and method failures retain DRF's safe `detail` response;
tests freeze their status and absence of writes rather than unstable wording.

## 14. Authentication and CSRF

Unsafe requests require the existing Django session and CSRF token. No endpoint
is CSRF-exempt. A normal same-origin client must first obtain a Django CSRF
cookie, then send its value in `X-CSRFToken` with session credentials.

Authentication, active/staff status, and permissions are independent gates.
Every failure returns 403 without revealing protected review evidence or
retaining a partial mutation. No JWT, CORS, custom token, or login API is added.

## 15. RawListing and adjacent-domain boundary

The service may traverse the target Listing's RawListing only to read
`raw_title` for an explicit alias request. It never writes RawListing.

TASK_025 creates or changes no:

- RawListing;
- Source health fact;
- SKU;
- unrelated alias;
- PricePoint or DealFlag;
- Outcome or Swap;
- resolver result for another Listing;
- ingestion or run bookkeeping; or
- frontend state.

The mutation API does not expose seller, payload, source evidence, URL, or raw
title. Capability D owns the dedicated review evidence projection and queue UI.

## 16. Compatibility and no-migration conclusion

TASK_025 preserves every frozen TASK_016 through TASK_018 acceptance test and
all TASK_023 read routes, representations, permissions, ordering, filters, and
unsafe-method behavior outside the two new named routes. TASK_024's approved
read calls remain unchanged.

The existing Listing, SkuAlias, auth permission, and LogEntry schemas represent
the complete contract. No model or migration change is required or authorized.

## 17. Frozen acceptance criteria

The frozen module is:

```text
tests/test_task_025_shared_review_services_and_mutation_api.py
```

It uses PostgreSQL and synthetic records only. It freezes:

- the shared module, service signatures/results/errors, and exact routes;
- both admin and DRF calling the same module functions;
- reviewed-unresolved eligibility, repeated decisions, queue transition,
  preservation, locking, and conflict behavior;
- confirmation, correction, field preservation, and Decimal semantics;
- alias opt-in, fidelity, same-SKU idempotency, conflicts, permissions, and
  rollback;
- authenticated active staff and exact built-in permission boundaries;
- session CSRF enforcement and JSON-only operation endpoints;
- HTTP success envelopes and 400/403/404/409/405/415 distinctions;
- exactly one service-owned Listing `LogEntry` and zero on failure;
- RawListing immutability and absence of pricing, resolver, ingestion, outcome,
  or generic mutation effects;
- TASK_023 route preservation; and
- no model or migration change.

No skip, xfail, SQLite path, test-only production branch, or live market data is
allowed.

## 18. Expected failing HARDEN baseline

HARDEN creates this specification and frozen test only. Before implementation,
the TASK_025 suite collects normally and fails explicit assertions that
`listings.review_services` and the two operation routes do not yet exist.

The failure is the approved red baseline. It is not permission to edit the
frozen tests during implementation.

## 19. Implementation validation

After owner approval, implementation must finish with:

1. exact frozen hashes;
2. all TASK_025 tests passing on PostgreSQL 16;
3. unchanged TASK_016 through TASK_018 suites;
4. unchanged TASK_023 suite;
5. the full PostgreSQL suite;
6. `makemigrations --check --dry-run` reporting no changes;
7. Django's system check clean;
8. no frontend build change; and
9. exact staged-snapshot review and validation.

## 20. Stop conditions

Stop for owner correction if implementation requires a model, migration,
settings, frontend, template, resolver, management-command, Docker, dependency,
or other out-of-scope change; if the frozen tests contradict TASK_016 through
TASK_018 or TASK_023; or if admin and DRF cannot share this service without
changing an approved Phase 4 behavior.
