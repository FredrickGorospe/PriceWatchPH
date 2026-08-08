# TASK_018 — Add human-confirmed alias curation and catalogue guardrails

## 1. Goal

Complete the Phase 4 catalogue-curation boundary by extending TASK_017's
constrained Listing confirmation workflow with one explicit, optional alias
decision and by preventing normal Django-admin deletion or mutation from
silently invalidating catalogue evidence or existing derived results.

TASK_018 does not change automatic matching. It creates curated alias evidence
only when an authorized human confirms a Listing to an existing canonical SKU
and explicitly requests the alias. Other Listings use that alias only on a
later explicit TASK_015 resolver run.

## 2. Authoritative context

This task follows:

- `CLAUDE.md`;
- `docs/04_PLANNING.md`;
- TASK_014's conservative `normalise_title()` and exact-alias-only resolver;
- TASK_015's explicit rerunnable resolution command;
- TASK_016's reviewed-unresolved state and machine-result transitions; and
- TASK_017's constrained Listing review, human confirmation, permissions,
  audit behavior, and minimum human-confirmed SKU deletion guard.

Repository facts frozen by earlier tasks remain authoritative:

- `RawListing` is immutable at Django and PostgreSQL levels;
- one mutable derived `Listing` exists per `RawListing`;
- automatic resolution emits only `exact_alias` or `unresolved`;
- automatic reruns never overwrite a `human_confirmed` Listing;
- `Sku` and `SkuAlias` are human-curated catalogue data;
- `SkuAlias.normalised_text` is globally unique;
- `SkuAlias.sku` uses `CASCADE`, `Listing.sku` uses nullable `SET_NULL`, and
  `PricePoint.sku` uses `PROTECT`; and
- Django admin is the UI through Phase 5.

Synthetic acceptance fixtures prove deterministic workflow behavior only.
They do not measure catalogue quality or market resolution accuracy.

## 3. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_018_ALIAS_CURATION_AND_CATALOGUE_GUARDRAILS.md`
- `listings/tests/test_task_018_alias_curation.py`

After owner approval, neither artifact may be modified to make implementation
pass. If a frozen test contradicts the authoritative repository state,
implementation must stop and report the conflict.

### IMPLEMENT files allowed

- `listings/admin.py`
- `catalogue/admin.py`

No model, migration, resolver, management command, template, ingestion
component, existing frozen artifact, planning document, dependency, Docker
file, or tooling file is in scope.

## 4. Explicit alias opt-in

TASK_017's normal Listing change form remains the human SKU confirmation and
correction surface. TASK_018 adds one non-model Boolean field named:

```text
create_alias
```

It is optional and unchecked by default. An ordinary confirmation without it
creates no alias.

When an authorized user submits it as true with a valid selected existing SKU,
the requested alias is derived only from the immutable source observation:

```text
SkuAlias.sku = selected confirmed SKU
SkuAlias.alias_text = Listing.raw_listing.raw_title
SkuAlias.normalised_text = normalise_title(Listing.raw_listing.raw_title)
SkuAlias.source_of_truth = "human_confirmed"
```

`alias_text` preserves the exact decoded source title. Normalization must call
TASK_014's existing `normalise_title()`; TASK_018 must not duplicate or alter
that algorithm. Arbitrary submitted `alias_text`, `normalised_text`, SKU, or
`source_of_truth` alias fields are ignored and cannot become persisted alias
state.

The selected SKU remains required by TASK_017. TASK_018 never creates a SKU,
never derives canonical launch facts, and never creates an alias outside an
explicit successful confirmation.

## 5. Duplicate and conflict behavior

Alias handling is determined by the globally unique normalized title:

1. If no alias has that `normalised_text`, create exactly one alias with the
   values in Section 4.
2. If an alias with that `normalised_text` already points to the selected SKU,
   treat the request as idempotent. Do not create or rewrite an alias; the
   Listing confirmation may proceed.
3. If an alias with that `normalised_text` points to a different SKU, reject
   the alias request as a form validation conflict. Do not repoint or modify
   the existing alias and do not persist the Listing confirmation.

After a conflict, the human may resubmit the same SKU confirmation with
`create_alias` false. That confirms the Listing without changing the conflicting
global alias. Alias repointing is not a TASK_018 operation.

Validation must also remain safe under concurrent uniqueness enforcement. A
database conflict or unexpected alias persistence failure propagates and rolls
back the complete operation; it must not leave a partial Listing confirmation.

## 6. Atomicity and admin audit

The following form one transaction:

- TASK_017's Listing confirmation/correction update;
- optional alias validation and creation or idempotent lookup; and
- Django's normal Listing admin `LogEntry`.

Structural validation and permission checks happen before persistence where
possible. If alias persistence or admin audit logging raises unexpectedly, the
Listing, alias table, and audit log remain exactly as they were before the
request. Exceptions are not swallowed and no repair-by-deletion of immutable
source data is attempted.

TASK_018 does not add a custom audit model. Alias creation is part of the
logged Listing confirmation transaction.

## 7. Permissions

TASK_018 uses Django staff status and built-in model permissions:

- Listing view/change permissions retain their TASK_017 meaning;
- confirmation without alias requires Listing change permission only;
- requesting `create_alias` additionally requires `SkuAlias` add permission;
- viewing catalogue aliases requires `SkuAlias` view permission;
- any allowed alias deletion requires `SkuAlias` delete permission; and
- any allowed SKU deletion requires `Sku` delete permission plus all guardrails
  in Section 9.

A user who can confirm Listings but lacks `SkuAlias` add permission receives a
permission denial when requesting alias creation, and neither confirmation nor
alias is persisted. Forged POST fields cannot create arbitrary aliases or
repoint existing aliases.

No custom role, reviewer model, or permission is added.

## 8. Constrained SkuAlias administration

`SkuAlias` remains inspectable in Django admin but is not generic CRUD:

- generic add is disabled; human-confirmed aliases enter only through the
  Listing confirmation workflow;
- generic change is disabled, preventing edits to alias text, normalized text,
  target SKU, or source of truth and preventing silent repointing;
- individual and bulk deletion are available only with built-in delete
  permission and only when the alias is not currently the evidence for a
  machine-derived exact-alias Listing; and
- the changelist and read-only object evidence remain available to users with
  view permission.

An alias currently supports a Listing exactly when all are true:

```text
Listing.resolution_method == "exact_alias"
Listing.sku_id == SkuAlias.sku_id
normalise_title(Listing.raw_listing.raw_title) == SkuAlias.normalised_text
```

Deleting such an alias would leave a persisted `exact_alias` result without
its stated evidence until another command happened to run, so normal admin
must block individual and bulk deletion. A mixed bulk deletion containing one
protected alias deletes none of the selected aliases.

An alias with no such dependent machine-derived Listing is genuinely safe to
delete through normal admin. A human-confirmed Listing does not depend on an
alias for its persisted decision and does not by itself block alias deletion.
Deleting an allowed alias never invokes the resolver; future and currently
unresolved rows simply no longer match it.

No generic alias correction or repointing operation is introduced. A safe
unused alias may be deleted, and a later explicit Listing confirmation may
create different curated evidence.

## 9. SKU catalogue deletion guardrails

TASK_017's protection for a SKU referenced by a `human_confirmed` Listing is
preserved and broadened according to the actual relationships:

- any `Listing` reference blocks normal-admin SKU deletion, regardless of
  resolution method, because `SET_NULL` would otherwise leave the persisted
  resolution method/confidence describing a removed target;
- any `SkuAlias` reference blocks normal-admin SKU deletion, because `CASCADE`
  would otherwise silently erase curated matching evidence;
- existing `PROTECT` references such as `PricePoint.sku` continue to block via
  Django/database behavior; and
- a SKU with none of those references remains deletable by a user with the
  built-in delete permission.

The same policy applies to individual, bulk, and forged/direct normal-admin
deletion requests. A mixed bulk request containing one protected SKU deletes
none of the selected SKUs.

TASK_018 does not change any foreign key or add a database constraint. These
are constrained normal-admin mutation rules; out-of-band data repair and a
future schema redesign are not silently introduced.

## 10. Resolver interaction

Alias creation does not invoke `resolve_raw_listing()`, TASK_015, a signal,
background work, or scheduler behavior.

Immediately after confirmation with alias creation:

- the source Listing is `human_confirmed` and remains protected;
- other Listings remain exactly as they were; and
- exactly one curated alias exists for the normalized title.

On a later explicit `python manage.py resolve_listings` invocation, other
machine-derived Listings with the same normalized title may resolve by the
normal TASK_014 exact-alias path. They receive `exact_alias` and confidence
`1.0000`; no fuzzy result is emitted. The source human-confirmed Listing remains
unchanged.

## 11. Existing behavior preserved

TASK_018 must preserve:

- RawListing application and PostgreSQL immutability;
- one Listing per RawListing;
- nullable truthful price, condition, and provenance fields from TASK_013;
- TASK_014 normalization, exact-alias matching, unresolved semantics,
  confidence values, and human-confirmed early return;
- TASK_015 explicit operational reruns;
- TASK_016 reviewed-unresolved marker transitions;
- TASK_017 queue, evidence, POST-only reviewed-unresolved action, SKU-only
  confirmation semantics, protected fields, admin audit, and permission
  boundaries;
- historical `fuzzy_match` compatibility without emitting new fuzzy results;
- no automatic SKU or alias creation; and
- no fabricated catalogue, source, price, condition, provenance, or confidence
  fact.

The alias opt-in must preserve RawListing and all Listing fields outside the
five TASK_017 human-confirmation fields. In particular it does not change
condition, price, observed time, location, price kind, or trade side.

## 12. Frozen acceptance criteria

The frozen module `listings/tests/test_task_018_alias_curation.py` contains
synthetic behavior tests for:

### Alias opt-in and fidelity

1. confirmation without opt-in creates no alias;
2. the confirmation form exposes only required `sku` plus optional unchecked
   `create_alias`;
3. opt-in creates exactly one alias using the selected existing SKU, exact raw
   title, TASK_014 normalized text, and `human_confirmed` source of truth;
4. forged alias fields cannot change derived alias values;
5. opt-in never creates a SKU and preserves immutable/raw and Listing source
   facts.

### Duplicate, conflict, transaction, and permission behavior

6. a same-normalized-text alias already targeting the selected SKU is
   idempotent and unchanged;
7. a different-SKU conflict returns validation failure and leaves Listing,
   alias, and audit state unchanged;
8. the administrator can retry that confirmation without alias creation;
9. an unexpected alias persistence failure rolls back confirmation;
10. audit logging failure occurs after the optional alias is present in the
    transaction and rolls back both Listing and alias;
11. alias opt-in requires SkuAlias add permission and denial persists nothing;
12. Listing change permission alone still permits confirmation without alias;
13. arbitrary submitted alias fields cannot create or repoint a second alias.

### Constrained alias admin

14. alias generic add is disabled;
15. alias generic change/repointing is blocked while view evidence remains
    available;
16. a genuinely unused alias is individually deletable with permission;
17. an alias supporting a current exact-alias Listing cannot be individually
    deleted;
18. protected alias deletion cannot be bypassed through bulk action;
19. a mixed safe/protected bulk alias deletion deletes neither;
20. an unrelated exact-alias Listing does not falsely block safe deletion; and
21. a user without SkuAlias delete permission cannot delete a safe alias.

### Catalogue deletion guardrails

22. TASK_017's human-confirmed SKU guard remains effective;
23. any machine-derived Listing reference blocks SKU deletion;
24. any alias reference blocks SKU deletion before cascade;
25. protected SKU deletion cannot be bypassed by a mixed bulk action;
26. existing PricePoint protection remains effective; and
27. a truly unreferenced SKU remains deletable.

### Resolver interaction and boundaries

28. alias creation does not automatically resolve a second Listing;
29. a later explicit TASK_015 rerun resolves that second Listing by exact alias
    without changing the human-confirmed source Listing or emitting fuzzy;
30. no unexpected RawListing, condition, downstream pricing/outcome/scheduler,
    SKU, or extra-alias state is written; and
31. TASK_018 requires no model or migration change.

The old frozen TASK_013 through TASK_017 suites remain compatibility authority
and must pass unchanged.

## 13. Validation

After implementation, from the repository root:

```text
docker compose exec web pytest -v listings/tests/test_task_018_alias_curation.py
docker compose exec web pytest -v \
  listings/tests/test_task_013_honest_incomplete_listings.py \
  listings/tests/test_task_014_deterministic_resolver.py \
  listings/tests/test_task_015_operational_resolution.py \
  listings/tests/test_task_016_reviewed_unresolved_state.py \
  listings/tests/test_task_017_constrained_review.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
git diff --check
git diff --cached --check
```

Validation must additionally inspect the exact staged diff, confirm that no
migration exists for TASK_018, verify frozen artifact hashes, and confirm that
unrelated working-tree files remain unstaged.

## 14. Reviewer and validator expectations

Static review owns:

- frozen test/spec integrity;
- permission, form, mutation, and transaction boundaries;
- alias fidelity, normalization reuse, idempotency, and conflict behavior;
- exact alias and SKU deletion guard logic, including bulk actions;
- no silent repointing, automatic resolution, or catalogue invention;
- RawListing and TASK_013 through TASK_017 compatibility;
- scope and absence of schema or unrelated changes; and
- non-vacuous tests without skips, xfails, or test-specific production paths.

Runtime validation owns actual PostgreSQL test execution, transaction rollback,
admin permission and deletion behavior, full-suite compatibility, migration
drift, and exact staged-snapshot validation. Runtime logs are not repository
artifacts and are not required in the staged diff.

## 15. Explicit non-goals

TASK_018 does not include:

- fuzzy or heuristic matching;
- alias repointing or generic alias editing;
- automatic alias or SKU creation;
- production catalogue seed data;
- inline SKU creation;
- condition editing or inference;
- resolver auto-invocation, signals, background work, cron, or scheduling;
- a custom review, assignment, snooze, escalation, or audit model;
- schema changes, migrations, or foreign-key redesign;
- a non-admin frontend;
- pricing baselines, `DealFlag`, outcome changes, or scoring;
- TASK_008 bookkeeping or source health;
- ingestion changes or new sources;
- external APIs, web search, scraping, embeddings, or LLM inference; or
- unrelated catalogue refactoring.
