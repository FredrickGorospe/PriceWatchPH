# Phase 6 Planning - Product UI and API

## 1. Status and authority

This document defines the Phase 6 boundary after completion of deterministic
Listing resolution, human review and catalogue curation, and auditable pricing
and deal scoring in Phases 3 through 5. It is a planning artifact only. It does
not create a task contract, acceptance tests, production behavior, a migration,
or a frontend implementation.

The committed Phase 3 through Phase 5 task specifications remain authoritative.
The capability order in Section 19 is limited to four planning units. Each unit
must still receive its own HARDEN pass and owner-approved failing acceptance
tests before implementation.

## 2. Phase 6 objective

Phase 6 adds an authenticated product interface for inspecting persisted deal
and pricing evidence and carrying out the existing human Listing-review
workflow. The interface consists of a React/TypeScript application supported by
focused Django REST Framework contracts.

The governing pricing flow is one-way:

```text
price_listings management command
    -> persisted PricePoint and DealFlag evidence
    -> read-only DRF representations
    -> React/TypeScript presentation
```

HTTP requests consume pricing results. They do not produce, recompute, backfill,
or reinterpret them.

## 3. Product boundary

React replaces Django admin only where a dedicated operator workflow adds clear
product value:

- a newest-first deal-feed landing experience;
- SKU pricing, history, and detail views;
- the unresolved Listing review queue;
- human SKU confirmation and correction; and
- optional alias curation tied to a successful review decision.

Django admin remains the back-office interface for:

- manual capture and personal trade logging;
- catalogue maintenance;
- RawListing evidence administration;
- raw PricePoint and DealFlag evidence administration; and
- other CRUD that does not materially benefit from a dedicated frontend.

The initial audience is authenticated operator/staff users. Anonymous or public
portfolio access is deferred.

## 4. Explicit non-goals

Phase 6 does not own:

- a new pricing, scoring, normalization, or resolution algorithm;
- authoritative browser-side pricing or statistical calculations;
- historical PricePoint backfill or pricing invocation from HTTP requests;
- new ingestion sources, capture enhancements, or fabricated production data;
- scheduling, run bookkeeping, cron changes, Celery, Redis, or a broker;
- alerts or notifications;
- Outcome lifecycle or realised-margin reporting;
- production Caddy, HTTPS, backup, or final deployment work;
- generic model CRUD APIs, generic Listing PATCH, or generic SkuAlias CRUD;
- mutation endpoints for immutable PricePoint or DealFlag evidence;
- favorites, dismissed flags, dashboard preferences, or KPI aggregates;
- a new audit model, reviewer-identity field, speculative index, or other
  schema expansion; or
- replacement of every Django admin workflow.

Facebook Marketplace remains permanently excluded. PostgreSQL 16, Python 3.12,
Django 5.2, DRF, Decimal money, UTC storage, and Asia/Manila display remain
locked repository constraints.

## 5. Dependencies from Phases 3 through 5

### 5.1 Phase 3 outputs consumed

- TASK_013 permits honest missing Listing price, condition, and resolution
  facts rather than invented values.
- TASK_014 provides exactly one derived Listing per immutable RawListing, the
  existing `normalise_title()` function, exact curated-alias resolution, and
  explicit unresolved results.
- TASK_015 provides explicit, rerunnable operational resolution while
  protecting human-confirmed Listings.

Phase 6 presents these facts but does not run the resolver from a request or
change its semantics.

### 5.2 Phase 4 outputs consumed

- TASK_016 provides the durable `reviewed_unresolved_at` state.
- TASK_017 provides the constrained review queue, permission checks, row
  locking, transactional reviewed-unresolved and confirmation behavior, and
  Django LogEntry audit.
- TASK_018 provides explicit alias opt-in, same-SKU idempotency, global alias
  conflict handling, and catalogue deletion guardrails.

Phase 6 must preserve these contracts while moving their authoritative
application behavior out of admin-only code so both admin and DRF can call it.

### 5.3 Phase 5 outputs consumed

- TASK_019 provides immutable, auditable PricePoint and DealFlag storage,
  including honest legacy PricePoints with null audit metadata.
- TASK_020 provides sealed rolling PricePoints and their Decimal aggregate and
  audit evidence.
- TASK_021 provides persisted DealFlags with four-place scores and preserves
  arbitrary legacy reason values.
- TASK_022 provides the only approved operational pricing orchestration through
  `price_listings` and read-only pricing evidence administration.

DRF reads the persisted rows produced by these capabilities. Neither the API nor
React calls `build_pricepoint()`, `score_listing()`, or the management command.

## 6. Current repository starting state

The repository starts Phase 6 with:

- Django session, authentication, and CSRF middleware already enabled;
- Django users, groups, model permissions, and admin authentication;
- models and migrations for Sku, SkuAlias, RawListing, Listing, PricePoint,
  DealFlag, and Outcome;
- admin-based Phase 4 review behavior concentrated in ModelAdmin and form code;
- no reusable shared application service for review decisions;
- read-only PricePoint and DealFlag admin evidence;
- no DRF dependency or installed application configuration;
- no API serializers, views, routing, or API tests;
- no React, TypeScript, Node package, build, or frontend test scaffolding; and
- a Python-only application image and a Compose stack containing PostgreSQL and
  the Django web service.

The current approved production write paths do not yield a meaningful corpus of
baseline-eligible Listings. That is a data limitation, not an API or UI schema
requirement and not a blocker for Phase 6.

## 7. Frontend and backend architecture

The backend owns authentication, authorization, validation, persisted evidence,
review decisions, audit, and all authoritative Decimal and time semantics. DRF
exposes focused read representations and operation-oriented review commands.

The frontend owns navigation, presentation, interaction state, non-authoritative
chart geometry, and loading, error, permission, and empty states. It must not
become a second domain implementation.

React is a separately built TypeScript bundle. The build tool, package manager,
frontend directory layout, chart library, test runner, and exact Docker build
stages are deferred to the relevant HARDEN pass after compatibility checks.

## 8. Same-origin deployment boundary

The production architecture is:

```text
browser, one origin
    /api/...   -> Django and DRF
    /admin/... -> Django admin
    /...       -> built React application
```

A frontend development server may proxy API and Django authentication requests
to the Django service. This does not establish a cross-origin production
contract.

The SPA fallback must never consume `/api/` or `/admin/` paths. Mounted Django
authentication paths must also resolve to Django rather than the SPA. Exact
static-file serving, bundle manifest, fallback, Docker, and future Caddy
mechanics are implementation choices for HARDEN, not Phase 6 architecture.

## 9. Authentication and CSRF contract

Phase 6 uses Django sessions, Django CSRF protection, and the existing
users/groups/model-permission system. It introduces neither JWT nor a separate
cross-origin authentication design.

Login and logout use mounted Django authentication views and session cookies.
The exact routes and post-login destination are frozen later with the routing
work. Anonymous requests must not receive product or review data.

The React application must:

- send same-origin session credentials;
- obtain Django's CSRF token through an approved same-origin Django mechanism;
- send the token in Django's expected header on every unsafe request;
- never exempt a review operation from CSRF; and
- distinguish unauthenticated, unauthorized, validation, conflict, and server
  failures in its user-visible states.

The application is staff/operator-first. HARDEN must freeze the precise read
permission mapping. Review operations must at minimum preserve the existing
Listing change permission, and alias creation must additionally require the
existing SkuAlias add permission.

## 10. API layering rules

API contracts are narrow product contracts, not serialized database access.

- Pricing and deal reads query persisted Sku, Listing, PricePoint, and DealFlag
  state only.
- HTTP read paths must not import or invoke pricing calculation operations.
- PricePoint and DealFlag have no create, update, or delete endpoints.
- Pricing and deal serializers must not traverse RawListing.
- Review is the only approved API boundary that may traverse RawListing, and it
  does so through the projection in Section 13.
- Review writes are named operations, not generic model create/update/delete or
  Listing PATCH.
- Serializers and views may validate transport shape, but they must not
  duplicate the authoritative Phase 4 mutation rules.
- API adapters translate HTTP inputs and service results. Shared review
  application services own authoritative mutation behavior.

Bounded pagination is expected for growing deal, PricePoint-history, and review
collections. Exact endpoint paths, response envelopes, page sizes, supported
filters, search fields, and error representations remain for capability-level
HARDEN. They must stay within the product and evidence boundaries in this
document.

## 11. Decimal and time serialization

Authoritative Decimal values cross JSON boundaries as strings. This includes:

- Listing and catalogue money at their model-defined two-place precision;
- PricePoint median, p25, p75, and MAD at their model-defined four-place
  precision;
- DealFlag score at four places; and
- Listing resolution confidence at four places.

Serializers must preserve model precision and nulls. They must not coerce these
values through binary floating point. Legacy nullable PricePoint audit values
remain JSON null rather than being filled or inferred.

Timestamps cross the API as timezone-aware ISO-8601 instants. Storage remains
UTC. User-facing dates and times are formatted for Asia/Manila as a presentation
concern, without changing the instant.

React may convert Decimal strings to JavaScript numbers only for
non-authoritative visual geometry such as chart coordinates. Labels, tables,
tooltips that state evidence, displayed source values, and user decisions must
use the original server-provided strings. The browser does not recalculate
quartiles, MAD, baselines, or DealFlag scores.

## 12. Derived-layer and RawListing boundary

Deal-feed, pricing, SKU, and general Listing representations remain derived
layer contracts. Convenience is not a reason to expose source, seller, URL,
raw title, payload, or another RawListing field through them.

Approved derived representations may include confirmed model facts needed by
the product, such as:

- canonical SKU identity and catalogue display fields;
- Listing identity, asking price, condition, resolution evidence, and observed
  time;
- persisted PricePoint statistics and audit metadata; and
- persisted DealFlag score, reason, baseline relationship, and flagged time.

Exact projections must be frozen during HARDEN. They must represent missing and
legacy values honestly and must not infer RawListing provenance.

The Phase 4 review workflow is the sole approved RawListing exception because a
human cannot review a resolution without the immutable source evidence.

## 13. Review evidence projection

The review API exposes one dedicated projection rather than a general
RawListing serializer. Its RawListing evidence is limited initially to:

- `raw_title`;
- computed `normalised_title`, produced read-only by the committed
  `normalise_title(raw_title)` function;
- `raw_price_text`;
- Source identity through the existing `RawListing.source` relationship;
- `url`;
- `occurred_at`; and
- `fetched_at`.

The repository uses the British `normalise_title` spelling, so the API-facing
derived field should follow that convention unless HARDEN establishes a
consistent external naming policy. It is computed for comparison and is not a
stored RawListing field.

The initial projection excludes seller and payload. It must not create a
general source-evidence endpoint or allow RawListing mutation.

The same projection may contain the current derived Listing and selected
canonical SKU facts needed to make a review decision. Its exact derived field
list and SKU-choice representation are frozen during HARDEN. Raw evidence must
remain visibly distinct from derived and curated facts.

The primary queue predicate remains exactly:

```text
Listing.sku IS NULL
AND Listing.reviewed_unresolved_at IS NULL
```

Its ordering remains:

```text
COALESCE(RawListing.occurred_at, RawListing.fetched_at), then Listing.pk
```

This ordering query is an explicit review-only RawListing traversal and does not
weaken the pricing boundary.

## 14. Shared review-service architecture

Phase 6 extracts the two authoritative Phase 4 decisions into reusable
application services:

- mark an eligible Listing reviewed but unresolved; and
- confirm or correct a Listing to an existing SKU, optionally creating the
  exact-title human-confirmed alias.

Names and module layout are implementation details. The shared boundary must:

- accept the acting Django user and explicit operation inputs;
- enforce the existing permissions authoritatively;
- perform structural and current-state eligibility validation;
- enter one transaction and acquire the existing Listing row lock;
- re-check mutable state after locking;
- preserve all source-derived fields;
- apply only the frozen Phase 4 state transitions;
- preserve alias normalization, global conflict, permission, and same-SKU
  idempotency behavior; and
- record exactly one successful audit entry inside the same transaction.

For reviewed-unresolved, eligibility remains `sku IS NULL` with the currently
approved unresolved or historical fuzzy resolution method. A successful action
changes only `reviewed_unresolved_at` and preserves the remaining resolution and
source-derived evidence.

For confirmation or correction, the selected SKU must already exist. A
successful action sets `resolution_method` to `human_confirmed`, confidence to
`1.0000`, refreshes `resolved_at`, and clears `reviewed_unresolved_at`. Alias
creation is explicit opt-in only, uses the immutable raw title and committed
normalizer, requires add permission, rejects a conflicting SKU mapping, and
keeps approved same-SKU behavior idempotent.

Both ModelAdmin and DRF become adapters over these services. The admin surface
and frozen form behavior remain operational. Adapter-level validation may
improve feedback but cannot become an alternative source of domain rules.

## 15. Audit behavior

Django admin `LogEntry` remains the review audit mechanism. No Phase 6 audit
table or reviewer field is added.

The shared review application service owns creation of the successful LogEntry
because it also owns the transaction and mutation. This keeps the audit rule
identical for admin and API callers and prevents a committed mutation without
its audit record. Each successful reviewed-unresolved or confirmation/correction
operation creates exactly one corresponding LogEntry. Rejected or rolled-back
operations create none.

Admin and API adapters must not add a second successful entry for a
service-owned decision. HARDEN must freeze useful action messages and verify
that Django admin's normal logging hooks are bypassed or coordinated only for
these service-routed operations. Existing unrelated admin logging remains
unchanged.

## 16. Initial deal-feed and SKU product surface

### 16.1 Deal-feed landing experience

The application lands on a bounded, newest-first DealFlag feed. It presents
persisted evidence only and introduces no dashboard KPI aggregate.

The initial card or row may include approved derived facts such as:

- SKU identity and display name;
- Listing asking price and condition;
- persisted DealFlag score and reason;
- persisted baseline median and MAD; and
- observation and flag timing.

Source, seller, URL, raw title, and other RawListing provenance are excluded.
Legacy arbitrary reason text must be returned honestly rather than being
rewritten as `asking_price_mad_v1`. HARDEN must freeze deterministic tie-break
ordering, pagination, and any useful derived-only filters.

### 16.2 SKU detail and history

SKU detail presents canonical catalogue facts and persisted pricing history.
The primary trend is PricePoint median, with p25/p75 as the range. Sample size,
MAD, day, window bounds, calculation time, and calculation-contract version are
available as relevant audit evidence.

Legacy PricePoints with absent audit metadata display honest unknown or
unavailable states. Related Listing and DealFlag evidence may be exposed only
through the approved derived-layer contracts. Charts visualize server evidence
and never recompute it.

## 17. Empty-data behavior

Empty pricing data is a normal supported state:

- collection APIs return a successful empty representation rather than an
  invented result or pricing side effect;
- the deal feed explains that no persisted DealFlags are available;
- SKU history distinguishes no persisted history from request failure;
- no UI control fabricates evidence or invokes pricing computation; and
- deterministic PostgreSQL-backed test and development fixtures may exercise
  populated states without being presented as production market data.

Phase 6 does not add ingestion work merely to make its screens look populated.

## 18. Schema disposition

No Phase 6 migration is planned. Existing models can represent the approved
read surfaces, review decisions, permissions, and LogEntry audit.

Phase 6 must not add frontend state, favorites, dismissed flags, preferences,
custom audit records, reviewer identity, speculative indexes, or Outcome state.
If a capability HARDEN pass finds a genuine schema need, work stops for owner
review instead of silently adding a migration.

## 19. Four-capability task decomposition

These are planning capabilities, not assigned task identifiers.

### Capability A - DRF foundation and read API

Owns:

- installing and configuring DRF;
- authenticated session/CSRF and permission foundations;
- Decimal, timestamp, null, and legacy-metadata serialization contracts;
- justified pagination and filtering contracts; and
- derived-only read APIs for Sku, PricePoint, DealFlag, and approved Listing
  evidence.

It must not expose RawListing provenance through pricing APIs or invoke pricing
computation.

### Capability B - React deal and SKU experience

Owns:

- the React/TypeScript foundation and HARDEN-approved build/dev convention;
- the development proxy and authenticated application shell;
- the newest-first deal-feed landing experience;
- SKU detail, pricing history, and persisted PricePoint charts;
- loading, permission, error, and empty states; and
- Asia/Manila display formatting.

It performs no authoritative client-side pricing calculation.

### Capability C - Shared review services and mutation API

Owns:

- extracting the Phase 4 review operations into shared application services;
- preserving the unresolved queue behavior where appropriate;
- reviewed-unresolved and SKU confirmation/correction operations;
- explicit optional alias creation;
- permissions, locking, conflict behavior, atomicity, and LogEntry audit; and
- dedicated operation-oriented DRF mutation endpoints.

Django admin and DRF must call the same authoritative behavior.

### Capability D - React review workflow and same-origin integration

Owns:

- the unresolved review queue UI and dedicated review evidence projection;
- reviewed-unresolved and SKU confirmation/correction interactions;
- alias opt-in and permission, validation, conflict, and error states;
- mounted Django login/logout integration;
- SPA routing and fallback boundaries;
- built frontend bundle integration; and
- integrated regression coverage while keeping back-office admin workflows
  intact.

## 20. Principal risks and controls

- **Review-semantic drift:** extracting admin behavior could subtly change
  eligibility or state transitions. Freeze the existing cases first and route
  both adapters through one tested service.
- **Audit duplication or gaps:** Django admin hooks and API code could produce
  zero or two entries. Put mutation and one LogEntry in the shared transaction
  and test both callers.
- **CSRF/session integration errors:** a development proxy can hide production
  cookie mistakes. Test same-origin login, expiry, unsafe requests, and denied
  requests explicitly.
- **Decimal precision loss:** DRF or React defaults may coerce strings to binary
  floats. Freeze wire examples and preserve original strings for authoritative
  presentation.
- **RawListing leakage:** convenient ORM traversal could expand pricing APIs.
  Use explicit serializers/querysets and regression tests for excluded fields.
- **SPA route capture:** a broad fallback could swallow API, admin, or auth
  routes. Reserve Django prefixes before the fallback and test them.
- **Query growth:** deal, history, and queue views can introduce unbounded or
  N+1 queries. Use bounded pagination and capability-specific query budgets
  without speculative schema changes.
- **Empty production evidence:** populated fixtures can mask a poor empty-state
  experience. Treat empty API and UI behavior as first-class acceptance cases.
- **Toolchain/deployment coupling:** freezing package or static-serving choices
  too early could create avoidable Docker and Django friction. Select them only
  after the focused compatibility check in the owning HARDEN pass.

## 21. Genuine open questions for capability HARDEN

The architecture and product boundary are settled. These implementation-level
questions remain:

1. Which compatible React build tool, package manager, directory layout, test
   runner, and chart library best fit the existing Docker/Django repository?
2. What exact API paths, versioning convention, response envelopes, page sizes,
   filters, search fields, tie-break ordering, and stable error codes should the
   focused endpoints freeze?
3. Beyond the staff/session baseline, which existing model `view` permissions
   should gate each read surface, and how should the application shell represent
   partial permissions?
4. What exact derived fields belong in the deal, SKU, Listing, and review
   representations, and how should canonical SKU choices be searched or
   paginated without becoming generic catalogue CRUD?
5. Which same-origin CSRF bootstrap, mounted auth paths, post-login return flow,
   bundle manifest, static serving, and SPA fallback mechanics pass the focused
   compatibility check?
6. What exact LogEntry action messages and object representation should each
   shared operation record while preserving one entry for both admin and API?
7. What PostgreSQL-backed fixture and frontend integration strategy gives
   deterministic populated and empty states without fabricating production
   data?

These questions are inputs to the relevant HARDEN pass. They do not authorize a
fifth capability, a migration, upstream data work, or expansion of Phase 6.
