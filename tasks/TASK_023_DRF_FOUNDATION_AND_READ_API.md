# TASK_023 - Add the DRF foundation and derived read API

## 1. Objective

Establish the first Phase 6 HTTP boundary: a same-origin, session-authenticated
Django REST Framework API that presents persisted Sku, Listing, PricePoint, and
DealFlag evidence to the later React application.

TASK_023 is read-only. It consumes existing derived and pricing rows and never
calculates, backfills, resolves, reviews, or mutates them.

The governing dependency direction remains:

```text
price_listings
    -> persisted PricePoint and DealFlag evidence
    -> DRF read API
    -> future React/TypeScript application
```

## 2. Authority and dependencies

This task follows:

- committed `CLAUDE.md` constraints;
- committed `docs/06_PLANNING.md`, especially Sections 7 through 13 and 16
  through 19;
- TASK_013 through TASK_015 honest derived Listing and resolution behavior;
- TASK_016 through TASK_018 human review, permission, and catalogue behavior;
- TASK_019 immutable and legacy-compatible PricePoint/DealFlag evidence;
- TASK_020 deterministic rolling PricePoints;
- TASK_021 deterministic DealFlag scoring and legacy reason preservation; and
- TASK_022 operational pricing invocation.

No Phase 3 through Phase 5 contract is reopened. In particular, RawListing is
immutable, PricePoint and DealFlag remain sealed evidence, and `price_listings`
remains the only approved operational pricing orchestration.

## 3. Files

### 3.1 HARDEN artifacts frozen before implementation

- `tasks/TASK_023_DRF_FOUNDATION_AND_READ_API.md`
- `tests/test_task_023_drf_foundation_and_read_api.py`

After owner approval, neither frozen artifact may be changed to make
implementation pass. A contradiction or incorrect test stops implementation
for owner correction.

### 3.2 IMPLEMENT files allowed after approval

- `requirements.txt`
- `config/settings.py`
- `config/urls.py`
- `api/__init__.py`
- `api/pagination.py`
- `api/permissions.py`
- `api/serializers.py`
- `api/urls.py`
- `api/views.py`

Implementation may use fewer of the new `api` modules when a separation is not
needed. No model, migration, admin, resolver, pricing service, command,
ingestion, outcome, frontend, template, Docker, prior test, prior task, or
planning file is in scope.

## 4. Owned scope

TASK_023 owns:

- a bounded Django REST Framework dependency compatible with the locked Python
  3.12 and Django 5.2 stack;
- DRF installation and configuration;
- same-origin Django SessionAuthentication;
- an API permission boundary based on existing staff status and Django model
  view permissions;
- the versioned routes in Section 6;
- explicit derived-layer representations;
- Decimal, date, and timestamp serialization;
- deterministic ordering and bounded pagination; and
- read-only access to the persisted evidence needed by Capability B.

The dependency entry must use the repository's bounded-requirement convention.
The approved compatibility range is:

```text
djangorestframework>=3.17,<3.18
```

## 5. Explicit non-goals

TASK_023 does not own:

- React, TypeScript, Node, frontend tooling, frontend routes, or SPA fallback;
- mounted login/logout pages or a credential API;
- review-specific RawListing evidence or an unresolved review queue;
- review mutations or shared Phase 4 review-service extraction;
- generic CRUD, generic Listing PATCH, or SkuAlias CRUD;
- PricePoint or DealFlag create, update, or delete behavior;
- Outcome APIs;
- pricing, baseline, or deal-scoring computation;
- `price_listings`, `build_pricepoint()`, or `score_listing()` invocation;
- a dashboard or KPI aggregation;
- ingestion, source expansion, or test data presented as production data;
- cross-origin authentication, JWT, tokens, CORS, or CSRF exemptions;
- schema changes, migrations, indexes, or frontend state; or
- production static serving, Caddy, HTTPS, or backups.

## 6. API namespace and routes

The first frozen API uses the versioned namespace `api-v1` mounted at
`/api/v1/`. Versioning prevents later frozen frontend contracts from colliding
with a changed representation while keeping one small same-origin route tree.

TASK_023 exposes exactly these routes:

| Name | Method | Path | Purpose |
| --- | --- | --- | --- |
| `api-v1:sku-list` | GET | `/api/v1/skus/` | Bounded canonical SKU collection |
| `api-v1:sku-detail` | GET | `/api/v1/skus/<pk>/` | One canonical SKU |
| `api-v1:sku-pricepoint-list` | GET | `/api/v1/skus/<sku_pk>/price-points/` | Persisted history for one SKU |
| `api-v1:listing-detail` | GET | `/api/v1/listings/<pk>/` | One derived Listing |
| `api-v1:dealflag-list` | GET | `/api/v1/deal-flags/` | Newest-first deal feed |

No top-level Listing collection, top-level PricePoint collection, DealFlag
detail, SkuAlias route, Outcome route, RawListing route, action route, or router
generated CRUD surface is part of this task.

The `/api/v1/` tree is distinct from `/admin/`, future Django authentication
paths, and the future SPA fallback. Unknown paths below `/api/` return the
ordinary API/Django not-found response and must never fall through to the SPA.

## 7. Authentication and permission contract

### 7.1 Authentication

DRF uses only Django `SessionAuthentication`. It must not enable Basic, Token,
JWT, or another authenticator.

All TASK_023 endpoints require an active authenticated staff user. With only
SessionAuthentication, an anonymous request receives HTTP 403. An authenticated
non-staff user receives HTTP 403 even if that user holds the relevant model
permission. A staff user missing a required permission also receives HTTP 403.

SessionAuthentication retains DRF's normal Django CSRF enforcement for future
unsafe operations. TASK_023 adds no unsafe operation merely to exercise CSRF
and adds no CSRF exemption.

### 7.2 Resource-specific view permissions

Permissions use only Django's existing built-in model permissions:

| Endpoint | Required permissions, in addition to active staff status |
| --- | --- |
| SKU list/detail | `catalogue.view_sku` |
| Listing detail | `listings.view_listing` |
| SKU PricePoint history | `catalogue.view_sku` and `pricing.view_pricepoint` |
| DealFlag feed | `catalogue.view_sku`, `listings.view_listing`, `pricing.view_pricepoint`, and `pricing.view_dealflag` |

The composite DealFlag permission is intentional because each feed item embeds
approved evidence from all four model types. Partial permission does not
silently redact or reshape a response; it denies that endpoint with HTTP 403.
One resource's permission never grants an unrelated endpoint.

Authorized reads return HTTP 200. An authorized detail lookup for an absent
object returns HTTP 404.

## 8. Representation contract

Every representation uses an explicit allowlist. Serializer-wide automatic
field exposure is forbidden because a later model field must not silently
become public API.

### 8.1 Sku

SKU list items and details expose exactly:

```text
id
brand
model
variant
category
launch_msrp
launch_date
```

The DealFlag feed uses a smaller embedded SKU summary containing exactly:

```text
id
brand
model
variant
category
```

No alias or reverse relationship is exposed.

### 8.2 Listing

The Listing detail and embedded DealFlag Listing representation expose exactly:

```text
id
sku_id
price
condition
resolution_confidence
resolution_method
resolved_at
observed_at
price_kind
trade_side
```

`sku_id`, `price`, `condition`, `observed_at`, `price_kind`, and `trade_side`
remain null when the persisted Listing fact is null. No value is inferred.

`raw_listing_id`, location, `reviewed_unresolved_at`, and every RawListing fact
are excluded. Review-specific evidence belongs to a later capability.

### 8.3 PricePoint

Each PricePoint history item and embedded DealFlag baseline exposes exactly:

```text
id
sku_id
condition
day
median
p25
p75
n_listings
mad
window_start_day
window_end_day
calculated_at
calculation_contract_version
```

Legacy PricePoints preserve null for every absent audit field. The API does not
invent a MAD, window, timestamp, or version.

### 8.4 DealFlag

Each deal-feed item exposes exactly:

```text
id
sku
listing
baseline_pricepoint
score
reason
flagged_at
```

`sku` is the five-field summary of `baseline_pricepoint.sku`. It identifies the
canonical SKU of the sealed baseline evidence even if the mutable derived
Listing's current SKU later changes or becomes null.

`listing` and `baseline_pricepoint` use the exact representations above. The
reason is returned verbatim, including an arbitrary legacy value. It must not be
rewritten to `asking_price_mad_v1`.

## 9. Decimal, date, and timestamp contract

### 9.1 Decimal

Every authoritative Decimal crosses JSON as a string, never as a JSON number:

- `Sku.launch_msrp` and `Listing.price`: exactly two fractional places;
- PricePoint `median`, `p25`, `p75`, and non-null `mad`: exactly four
  fractional places;
- DealFlag `score`: exactly four fractional places; and
- Listing `resolution_confidence`: exactly four fractional places.

A nullable Decimal remains JSON null. Serializers must not pass these values
through binary floating point. DRF's Decimal-to-string behavior must be
configured and frozen rather than left to an accidental renderer default.

### 9.2 Dates

`Sku.launch_date`, `PricePoint.day`, and non-null window bounds are ISO
`YYYY-MM-DD` strings. A date is not serialized as a timestamp.

### 9.3 Timestamps

Non-null timestamps are timezone-aware ISO-8601 instants normalized to UTC with
the `Z` suffix. For example:

```text
2026-08-09T04:05:06Z
```

The API does not convert instants to Asia/Manila. Manila display formatting is
owned by React. Nullable timestamps remain JSON null; naive timestamp strings
are forbidden.

## 10. Collections, ordering, and pagination

The SKU list, SKU PricePoint history, and DealFlag feed use DRF page-number
pagination with:

```text
page query parameter: page
fixed page size: 25
client-selectable page size: none
```

Every successful page has exactly this envelope:

```json
{
  "count": 0,
  "next": null,
  "previous": null,
  "results": []
}
```

`count` is the total matching row count. `next` and `previous` use DRF's normal
absolute URL or null behavior. Empty collections return HTTP 200 with this
empty envelope.

Ordering is explicit and applied before pagination:

- SKUs: `brand`, `model`, `variant`, then `id`, all ascending;
- SKU PricePoints: `day`, `condition`, then `id`, all ascending for chart and
  history consumption; and
- DealFlags: `flagged_at` descending, then `id` ascending, matching the current
  read-only admin's stable same-time convention.

No collection relies on model or database-default ordering.

## 11. Filtering and search disposition

TASK_023 adds no general search, ordering parameter, or filter framework.

SKU history accepts one optional exact query parameter:

```text
condition=new|like_new|used|for_parts
```

When present, it restricts the already SKU-scoped PricePoint collection to that
existing condition vocabulary. An invalid condition returns HTTP 400 rather
than an empty result that could hide a client error.

The SKU collection and DealFlag feed have no filtering or search contract in
TASK_023. The bounded canonical SKU collection is sufficient for Capability B;
search needed by the later review selector is deferred to the capability that
owns that product decision.

## 12. Derived-layer and RawListing boundary

TASK_023 serializers and querysets may use only Sku, Listing, PricePoint, and
DealFlag fields and relationships approved above. They must never traverse
`Listing.raw_listing` to produce a response.

No TASK_023 response exposes:

- `raw_listing_id`;
- raw title or raw price text;
- Source identity;
- RawListing URL;
- seller or payload;
- RawListing occurred or fetched time; or
- another RawListing field or reverse relationship.

The exclusion is enforced through exact serializer field allowlists and frozen
response-key assertions. RawListing review evidence remains owned by Capability
D.

## 13. Read-only and immutable guarantees

Every exposed route supports safe reads only. POST, PUT, PATCH, and DELETE on an
existing TASK_023 collection or detail route return HTTP 405 for an authorized
user.

There is no generic Listing collection or mutation route, no generic router,
and no PricePoint or DealFlag mutation route. HTTP reads do not save, update, or
delete any represented row. Existing model and PostgreSQL immutability for
PricePoint and DealFlag remains unchanged and authoritative.

## 14. Query behavior

The deal feed must load its Listing, baseline PricePoint, and baseline SKU
relationships without one query per item. SKU history must scope directly by
the path SKU and must not load related objects per row merely to serialize
their IDs.

Use existing ORM relationship loading where justified. TASK_023 adds no index
or migration. Frozen tests focus on response behavior and do not set a brittle
global query-count number because session, permission-cache, and pagination
queries are legitimate and framework-version-sensitive. Review must still
reject an obvious N+1 implementation.

## 15. Pricing-computation separation

No TASK_023 HTTP module may import a pricing calculation function for use in a
read path. A request must not execute:

- `price_listings`;
- `build_pricepoint()`;
- `score_listing()`;
- baseline construction; or
- deal scoring.

Acceptance tests patch the existing pricing service entry points to fail if
called, exercise every pricing read collection, and verify PricePoint and
DealFlag row counts do not change. This behaviorally proves the exercised reads
do not execute or trigger pricing. A runtime test cannot prove that a dormant,
unused import does not exist, so the no-import boundary is additionally a
required staged-diff review check rather than a fragile source-string test.

## 16. Empty and legacy behavior

- Empty collections return the successful pagination envelope in Section 10.
- A missing detail object returns 404 only after authentication and permission
  checks succeed.
- Nullable Listing facts remain null.
- All-null legacy PricePoint audit metadata remains null.
- Arbitrary DealFlag reason text passes through unchanged.
- No read attempts to create data so an empty screen appears populated.

## 17. Acceptance test plan

The frozen test module covers:

- DRF dependency, installation, SessionAuthentication-only configuration, and
  Decimal-string configuration;
- exact namespace, paths, and route names;
- anonymous, non-staff, missing-permission, partial-permission, and authorized
  behavior;
- exact field allowlists for every representation;
- the absence of RawListing provenance;
- fixed Decimal types and precision, null preservation, ISO dates, and UTC
  timestamp strings;
- deterministic SKU, PricePoint, and DealFlag ordering;
- fixed page-number pagination and empty envelopes;
- the one approved condition filter and invalid-filter rejection;
- legacy PricePoint metadata and DealFlag reasons;
- method rejection and absence of generic mutation routes; and
- behavioral non-execution of the existing pricing services.

All database tests use PostgreSQL through pytest-django. No SQLite path is
introduced.

## 18. Expected failing baseline

Before implementation:

- `rest_framework` is absent from the dependency environment and
  `INSTALLED_APPS`;
- `REST_FRAMEWORK` configuration is absent;
- the `api-v1` namespace and every frozen route are absent; and
- no serializers or views exist.

The frozen module deliberately avoids importing DRF at collection time. The
baseline therefore collects normally and fails informatively on missing
dependency/configuration assertions and missing URL reversals rather than
crashing accidentally during test import.

## 19. Implementation and schema constraints

- Explicit code is preferred over a generic router or dynamic serializer
  factory.
- Serializers use explicit field lists and read-only fields.
- Views use SessionAuthentication and the frozen permission matrix.
- DRF settings must retain Django's CSRF behavior and Decimal strings.
- Querysets use deterministic ordering before pagination.
- No calculation service is called or imported for execution by a read path.
- No source fact is copied into a derived response merely for convenience.
- No production fixture, seed, or catalogue row is added.
- No migration is expected or permitted.

If implementation appears to require a model field, schema change, migration,
RawListing traversal, or another production file, stop for owner review.

## 20. Validation requirements

Implementation must finish with:

1. TASK_023 frozen acceptance tests;
2. relevant TASK_013 through TASK_022 compatibility tests;
3. the full PostgreSQL suite;
4. `python manage.py makemigrations --check --dry-run`;
5. Django's system check;
6. staged-diff and protected-working-tree checks; and
7. independent review and validation under the approved workflow.

The two known unrelated working-tree modifications must remain untouched,
unstaged, and uncommitted.

## 21. STOP conditions and remaining unknowns

Implementation must stop rather than improvise if:

- a frozen test contradicts the committed model or a Phase 3 through Phase 5
  contract;
- the approved DRF range cannot support Python 3.12 and Django 5.2;
- an exposed field would require RawListing traversal;
- the permission matrix cannot be expressed with existing staff status and
  built-in model permissions;
- an endpoint requires pricing execution to answer a read;
- a migration or new schema appears necessary; or
- the implementation needs to change a frozen artifact or a file outside the
  allowed list.

No genuine architectural question remains for TASK_023 HARDEN. Frontend
tooling, SPA integration, review APIs, and shared review services remain
deliberately deferred to their owning Phase 6 capabilities.
