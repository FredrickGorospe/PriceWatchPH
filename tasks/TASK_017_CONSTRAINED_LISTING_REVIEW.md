# TASK_017 — Add constrained Listing review and human confirmation

## 1. Goal

Add the Phase 4 Django-admin workflow for reviewing derived `Listing` rows
without turning `Listing` or immutable `RawListing` evidence into generic CRUD.

Authorized staff can:

- inspect the durable unresolved queue and complete source evidence;
- mark an eligible machine-unresolved Listing reviewed without claiming a SKU;
- confirm or correct one Listing to one existing canonical `Sku`; and
- use the existing catalogue admin without being able to delete a `Sku` that
  is referenced by a human-confirmed Listing.

TASK_017 adds no model field, migration, catalogue data, alias write, resolver
heuristic, or downstream pricing behavior.

## 2. Authoritative context

This task follows:

- `CLAUDE.md`;
- `docs/04_PLANNING.md`;
- TASK_013's honest nullable Listing facts and explicit `unresolved` method;
- TASK_014's deterministic exact-alias resolver and human-confirmed early
  return;
- TASK_015's operational rerun command; and
- TASK_016's durable `reviewed_unresolved_at` field and transition behavior.

The current repository establishes:

- PostgreSQL 16 as the only supported database, including tests;
- immutable `RawListing` source observations;
- one mutable derived `Listing` per `RawListing`;
- automatic outputs limited to `exact_alias` and `unresolved`;
- historical schema compatibility for `fuzzy_match`;
- no automatic `Sku` or `SkuAlias` creation;
- `human_confirmed` Listings protected from TASK_014 and TASK_015 reruns; and
- Django admin as the UI through Phase 5.

## 3. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_017_CONSTRAINED_LISTING_REVIEW.md`
- `listings/tests/test_task_017_constrained_review.py`

After owner approval, neither artifact may be modified to make implementation
pass. If a frozen test contradicts the authoritative repository state,
implementation must stop and report the conflict.

### IMPLEMENT files allowed

- `listings/admin.py`
- `catalogue/admin.py`
- `listings/templates/admin/listings/listing/change_form.html`

No model, migration, resolver, management command, ingestion component,
existing frozen artifact, planning document, dependency, Docker file, or
tooling file is in scope.

## 4. Admin interface boundary

TASK_017 replaces the current generic `Listing` registration with one explicit
`ListingAdmin`. It also replaces the generic `Sku` registration only as needed
for the minimum deletion guard in Section 11. `SkuAlias` administration is not
changed in this task.

The constrained Listing surface consists of:

1. the default unresolved review queue;
2. a read-only evidence page using the Listing change URL;
3. a required existing-SKU selector on that page for confirmation/correction;
   and
4. a separate POST-only reviewed-unresolved operation for one eligible object.

The reviewed-unresolved URL is named:

```text
admin:listings_listing_mark_reviewed_unresolved
```

It accepts the Listing primary key and is linked from the Listing change page
only when the object is eligible. The operation is never a bulk admin action.

The normal Listing change form is the confirmation/correction form. Its only
editable model field is `sku`, and that field is required. All other Listing
and RawListing evidence is excluded from form input and displayed read-only.
Unexpected submitted keys are ignored rather than becoming a generic write
path.

## 5. Primary review queue

The default Listing changelist contains exactly:

```text
sku IS NULL
AND reviewed_unresolved_at IS NULL
```

The predicate is intentionally independent of `resolution_method`. It includes:

- current `unresolved` rows;
- historical `sku=NULL + fuzzy_match` rows; and
- integrity exceptions such as `sku=NULL + exact_alias` or
  `sku=NULL + human_confirmed`.

Integrity exceptions remain visible so a human can select a replacement SKU,
but Section 8 forbids marking them reviewed-unresolved.

Default ordering is the immutable source-observation timestamp:

```text
COALESCE(RawListing.occurred_at, RawListing.fetched_at)
```

ascending, followed by Listing primary key ascending as the stable tie-breaker.
This uses the same observation precedence as TASK_014 without trusting a
possibly-null historical derived `observed_at` value.

The changelist exposes an explicit `review_scope=all` filter choice so
authorized users can reach non-queue machine matches and human-confirmed rows
for explicit correction. This is access, not a second machine classifier.
Source and resolution-method filters and search over stored title/identifiers
may be added without changing queue semantics.

## 6. Read-only evidence

A user with Listing view permission can inspect the change page. Where values
exist, it presents:

### RawListing evidence

- primary key and external identifier;
- exact `raw_title`;
- TASK_014 `normalise_title(raw_title)` output;
- exact `raw_price_text` and parsed `raw_price`;
- source;
- URL;
- already-pseudonymized seller;
- `fetched_at` and `occurred_at`; and
- retained redacted payload.

The workflow does not attempt to recover plaintext seller identity. No
RawListing field is editable.

### Listing evidence

- current SKU and its canonical brand, model, variant, and category;
- condition;
- resolution method and confidence;
- `resolved_at` and `reviewed_unresolved_at`;
- `observed_at`;
- price and location;
- price kind; and
- trade side.

Condition and all provenance/derived fields remain read-only. TASK_017 is an
entity-confirmation workflow, not a condition-correction workflow.

## 7. Generic Listing mutation restrictions

- Listing add permission is always disabled.
- Listing delete permission is always disabled.
- the admin exposes no bulk Listing action;
- the only editable form field is required `sku`;
- `raw_listing`, price, condition, location, observation/provenance fields,
  resolution bookkeeping, and review marker are protected from form input;
- forged POST values for protected fields cannot mutate them; and
- a user without the built-in Listing change permission cannot invoke either
  review mutation.

View permission remains sufficient to inspect queue candidates and evidence.
Staff status and Django's built-in model permissions are the only role system;
TASK_017 adds no custom role or permission model.

## 8. Reviewed-but-unresolved operation

The per-object POST operation is eligible only when:

```text
Listing.sku IS NULL
AND Listing.resolution_method IN (unresolved, fuzzy_match)
```

`fuzzy_match` is accepted only for historical compatibility. TASK_017 creates
no fuzzy result.

A successful operation changes exactly:

```text
reviewed_unresolved_at = timezone.now()
```

It preserves exactly:

- `raw_listing`;
- `sku=NULL`;
- resolution method and confidence;
- `resolved_at`;
- price;
- condition;
- location;
- `observed_at`;
- price kind; and
- trade side.

The operation rejects, without persistence:

- every `human_confirmed` Listing;
- every `exact_alias` Listing;
- every Listing with a non-null SKU; and
- users without Listing change permission.

In particular it must never bless or manufacture:

```text
sku = NULL
resolution_method = human_confirmed
resolution_confidence = 1.0000
```

Forged form keys do not broaden the one-field operation. The operation does
not invoke the resolver or create an alias. It records one normal Django admin
change `LogEntry` for the acting user.

## 9. Human SKU confirmation and correction

The normal Listing change POST requires selection of one existing `Sku`.
Successful confirmation sets exactly the following decision fields:

```text
Listing.sku = selected existing SKU
Listing.resolution_method = "human_confirmed"
Listing.resolution_confidence = Decimal("1.0000")
Listing.resolved_at = timezone.now()
Listing.reviewed_unresolved_at = NULL
```

It preserves:

- the `raw_listing` relationship;
- price;
- condition;
- location;
- `observed_at`;
- price kind; and
- trade side.

No missing value is defaulted or inferred. No condition is edited. The form
does not create an inline SKU: the chosen object must already exist.

An authorized human may later correct a human-confirmed Listing to a different
existing SKU. The row remains `human_confirmed` with confidence `1.0000`,
`resolved_at` is refreshed, and the review marker is cleared. The normal
Django change-form path creates the normal admin audit entry.

A blank or nonexistent SKU is invalid. A forged attempt to clear the SKU of a
human-confirmed Listing is rejected without changing the row.

TASK_014 direct reruns and TASK_015 operational reruns must continue to return
without modifying a human-confirmed Listing.

## 10. Transaction and audit behavior

Confirmation uses Django 5.2's normal admin change-form POST boundary, which
wraps the complete write, related-form save, and `LogEntry` creation in one
database transaction. TASK_017 must not add a non-atomic side channel around
that boundary.

The reviewed-unresolved POST similarly updates the locked Listing and writes
its normal admin `LogEntry` in one transaction.

Structural validation and permission checks occur before persistence.
Unexpected exceptions are not swallowed. An exception during confirmation or
audit leaves the Listing unchanged and no partial confirmation committed.

TASK_017 adds no custom review-history, reviewer foreign key, or audit model.

## 11. Minimum human-confirmed SKU deletion guard

The existing `Listing.sku` foreign key uses `SET_NULL`. TASK_017 does not
redesign that schema, but normal Django admin must not delete a `Sku` referenced
by any Listing whose `resolution_method` is `human_confirmed`.

The guard applies to:

- individual Sku deletion;
- Django's bulk delete-selected action; and
- direct or forged requests through those normal admin endpoints.

A protected delete is refused and leaves both the Sku and Listing unchanged.
A Sku with no human-confirmed Listing reference remains deletable when the
ordinary existing Django permissions and relationships permit it.

This is intentionally not the broader catalogue policy. TASK_018 owns alias
mutation, alias deletion, and broader Sku/SkuAlias reference guardrails.

## 12. Preserved invariants and boundaries

TASK_017 must preserve:

- RawListing application and PostgreSQL immutability;
- one Listing per RawListing;
- nullable price and condition from TASK_013;
- the `unresolved`, `exact_alias`, `human_confirmed`, and historical
  `fuzzy_match` vocabulary;
- TASK_014 automatic resolution and marker transitions;
- TASK_015 all-row operational reruns;
- TASK_016 reviewed-unresolved marker behavior;
- human-confirmed automatic protection;
- no automatic Sku or SkuAlias creation; and
- exact Decimal confidence values without any float path.

Review operations create no `SkuAlias`, `PricePoint`, `DealFlag`, `Outcome`,
`Swap`, source-health, scheduler, or run-bookkeeping state.

No schema change or migration is required.

## 13. Acceptance criteria — frozen

The approved acceptance module is:

- `listings/tests/test_task_017_constrained_review.py`

It uses synthetic catalogue and source observations only. Those fixtures prove
deterministic workflow behavior and make no market-accuracy claim.

The frozen tests cover:

### Queue and evidence

- exact default queue membership, including historical and integrity states;
- exclusion of already-reviewed unresolved rows;
- source-observation ordering and Listing-PK tie-break;
- explicit all-listings correction access;
- view-only evidence access;
- complete immutable RawListing, normalized-title, Listing, and canonical-SKU
  evidence; and
- a one-field required-SKU mutation form.

### Generic admin restrictions

- Listing add and delete are blocked;
- no bulk Listing actions exist;
- protected fields are excluded from mutation;
- forged protected values do not persist; and
- staff/model permission boundaries cannot be bypassed.

### Reviewed-unresolved

- `unresolved` and historical `fuzzy_match` eligibility;
- POST-only mutation behavior, with GET performing no Listing or audit write;
- no action-link exposure for null-SKU `exact_alias` or `human_confirmed`
  integrity exceptions;
- exact one-field timestamp mutation;
- preservation of method, confidence, `resolved_at`, and source facts;
- rejection of `human_confirmed`, `exact_alias`, and non-null-SKU rows;
- permission enforcement;
- no forged-field bypass; and
- normal admin audit logging in the same transaction, including rollback of
  the marker update when audit logging raises unexpectedly.

### Human confirmation

- selection of an existing required SKU;
- exact human method/confidence/timestamp/marker semantics;
- preservation of condition and provenance facts;
- explicit correction from one confirmed SKU to another;
- rejection of blank/nonexistent SKU and forged clearing;
- permission enforcement;
- transaction rollback when audit fails;
- normal admin audit logging;
- TASK_014 and TASK_015 preservation; and
- no automatic Sku/SkuAlias creation.

### Catalogue guard and boundaries

- individual and bulk deletion refusal for a human-confirmed referenced SKU;
- continued deletion of an unrelated safe SKU;
- RawListing immutability through review operations;
- no alias, downstream pricing/outcome, source-health, or scheduler writes; and
- no model/migration drift.

## 14. Explicit non-goals

TASK_017 does not implement:

- alias creation, repointing, or mutation policy;
- broad Sku/SkuAlias deletion policy;
- inline SKU creation;
- condition editing or title-based condition inference;
- fuzzy/heuristic matching or resolver recommendations;
- bulk human confirmation;
- custom review models, statuses, assignments, snoozes, or escalation;
- non-admin UI or frontend framework;
- pricing, baselines, DealFlag, or outcome changes;
- TASK_008, scheduling, cron, source health, or run bookkeeping;
- ingestion changes or new sources;
- external APIs, web search, scraping, embeddings, or LLMs; or
- production catalogue/alias seed data.

## 15. Validation

Implementation must validate, in order:

```text
docker compose exec web pytest -v listings/tests/test_task_017_constrained_review.py

docker compose exec web pytest -v \
  listings/tests/test_task_013_honest_incomplete_listings.py \
  listings/tests/test_task_014_deterministic_resolver.py \
  listings/tests/test_task_015_operational_resolution.py \
  listings/tests/test_task_016_reviewed_unresolved_state.py

docker compose exec web pytest -v

docker compose exec web python manage.py makemigrations --check --dry-run

git diff --check
git diff --cached --check
```

The migration command must report `No changes detected`. The final staged
snapshot must contain only the frozen TASK_017 artifacts and the three allowed
implementation paths from Section 3. `CLAUDE.md`, `docs/01_PLANNING.md`, prior
tasks/tests, models, migrations, resolver code, management commands, and all
unrelated work remain untouched and unstaged.
