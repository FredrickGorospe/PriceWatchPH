# Phase 4 Planning — Human Review and Catalogue Curation

## 1. Status and authority

This document defines the Phase 4 product boundary after completion of:

- TASK_013 — honest incomplete `Listing` derivations;
- TASK_014 — deterministic exact-alias resolution; and
- TASK_015 — operational rerunnable resolution.

It supplements the historical roadmap and earlier planning documents where the
implemented Phase 3 contract is now more precise. It does not reopen TASK_008,
Phase 3 resolver behavior, or the immutability boundary around `RawListing`.

The durable reviewed-but-unresolved state proposed below remains subject to
owner approval. Alias, SKU, and condition-review boundaries reflect the owner
decisions made during this planning revision. Exact implementation contracts
must still be frozen in task specifications and acceptance tests before code is
written.

## 2. Phase 4 goal

Phase 4 adds a constrained Django-admin workflow for a human to inspect a
derived `Listing`, record a durable reviewed-but-unresolved outcome, confirm or
correct its canonical `Sku`, and optionally turn that explicit SKU decision
into a curated `SkuAlias` for future deterministic resolution.

The workflow must make source evidence visible without making source evidence
editable. It must preserve the distinction between:

- immutable source observations in `RawListing`;
- mutable machine-derived state in `Listing`;
- human-curated canonical catalogue data in `Sku` and `SkuAlias`; and
- explicit human decisions recorded as `human_confirmed` Listings.

Phase 4 is complete when authorized staff can safely resolve the review queue
and correct known machine-derived results without introducing guessed facts,
generic derived-state CRUD, or automatic catalogue creation.

## 3. Current-state baseline

### 3.1 Source observations

`RawListing` is the immutable record of what an approved source stated. It is
protected from update and deletion at both the Django and PostgreSQL layers.
Its existing Django admin remains read-only apart from the separate TASK_007
forward-capture workflow.

Relevant evidence includes:

- exact `raw_title`;
- parsed `raw_price` and exact `raw_price_text`;
- `source`;
- URL and pseudonymized seller;
- `fetched_at` and optional `occurred_at`; and
- retained, redacted payload/provenance.

Phase 4 must never edit or delete this evidence.

### 3.2 Derived Listings

TASK_014 creates or updates exactly one `Listing` per `RawListing` and records
either:

```text
exact alias:
    sku = matched curated SKU
    resolution_method = exact_alias
    resolution_confidence = 1.0000

no exact alias:
    sku = NULL
    resolution_method = unresolved
    resolution_confidence = 0.0000
```

TASK_013 permits price and condition to remain `NULL` when the source does not
provide trustworthy values. `price_kind` and `trade_side` likewise remain
nullable. Phase 4 must not fill any of those fields by default.

TASK_015 deliberately reconsiders every `RawListing`. TASK_014 updates only
machine-derived Listings and skips any Listing whose method is
`human_confirmed`.

### 3.3 Curated catalogue

`Sku` is canonical, human-curated catalogue data. Its required launch date and
launch MSRP cannot be truthfully derived from an arbitrary listing title.

`SkuAlias` is curated matching evidence. Its globally unique
`normalised_text` maps one normalized phrase to exactly one `Sku`. Valid
sources of truth are `seed` and `human_confirmed`.

The existing catalogue and Listing admin registrations are generic. Phase 4
must replace generic mutation of derived and alias state with the constrained
workflow below.

## 4. Component boundaries

### 4.1 Review workflow owns

The Phase 4 Django-admin workflow owns:

- selecting review candidates from existing Listings;
- presenting immutable source evidence and current derived state;
- selecting an existing curated `Sku` as a human decision;
- recording the confirmed SKU with `human_confirmed` method and confidence;
- recording that a human reviewed an unresolved Listing but could not safely
  select a SKU, without changing its resolution method or confidence;
- optionally creating one exact-title, human-confirmed alias from that same
  decision;
- validating alias conflicts before persistence;
- applying the confirmation and optional alias atomically; and
- recording the acting administrator through Django's existing admin log.

### 4.2 Review workflow must not own

Phase 4 must not:

- mutate or delete `RawListing`;
- automatically create `Sku` or `SkuAlias` rows;
- infer a SKU, condition, price, price kind, trade side, or location;
- edit source-derived price, timestamps, provenance, or trade facts;
- perform fuzzy or heuristic matching;
- calibrate intermediate confidence;
- run external lookups, web search, scraping, APIs, embeddings, or LLMs;
- seed a production catalogue;
- implement pricing baselines, `DealFlag`, or outcome behavior;
- implement TASK_008 bookkeeping, scheduling, cron, or source-health state;
- introduce a frontend framework; or
- duplicate TASK_014 normalization or resolver logic.

## 5. Review queue contract

### 5.1 Primary queue

The primary review queue must distinguish unresolved rows that have not yet had
a human review from those a human deliberately could not resolve. The proposed
queue is:

```text
Listing.sku IS NULL
AND Listing.reviewed_unresolved_at IS NULL
```

It intentionally includes:

- new `unresolved` Listings;
- historical `sku=NULL` Listings using an older method value such as
  `fuzzy_match`; and
- machine-derived Listings whose previously selected SKU was deleted and set
  to `NULL`.

The queue must not rely only on `resolution_method="unresolved"`, because doing
so would hide valid unresolved states already permitted by the schema.

A legacy or out-of-band `sku=NULL + human_confirmed` row also remains visible
under the queue predicate so an authorized human can select a replacement SKU.
It is an integrity exception, not an unresolved human decision. The "reviewed
but unresolved" action must reject it and must never manufacture or bless:

```text
sku = NULL
resolution_method = human_confirmed
resolution_confidence = 1.0000
```

The same action must reject a `sku=NULL + exact_alias` integrity exception
until TASK_015 converts it to the current unresolved machine result or a human
selects a replacement SKU. Hiding an inconsistent resolved method behind the
review marker would make the persisted evidence less honest.

The action is therefore available only when `sku=NULL` and the current method
is `unresolved` or the historical compatible `fuzzy_match` state.

The default queue ordering should be deterministic and operationally useful:
oldest source observation first, with Listing primary key as a stable tie
breaker. Filters may expose source and current resolution method. Search may
use raw title and exact identifiers already stored in the repository.

### 5.2 Correction access

A known incorrect machine-derived exact match has a non-null SKU and therefore
does not belong in the primary unresolved queue. Authorized staff must still be
able to open such a Listing from the constrained Listing admin and explicitly
correct it to another existing SKU.

This is not a second automatic review classifier. Phase 4 does not attempt to
identify bad exact matches or assign them a machine-generated review status.

### 5.3 No hidden lifecycle state

The current schema has no truthful way to distinguish:

- not yet reviewed and unresolved; from
- reviewed by a human and intentionally left unresolved.

Recording `human_confirmed` with `sku=NULL` would falsely claim a canonical
resolution, while changing `unresolved` or using `fuzzy_match` would falsify the
resolver evidence class. Leaving the row as only `sku=NULL` causes an endless
queue entry after a human has already exhausted the available evidence.

The smallest durable solution is one nullable field on `Listing`:

```text
reviewed_unresolved_at = DateTimeField(null=True, blank=True)
```

Its semantics are deliberately narrow:

- `NULL` while a `sku=NULL` Listing still needs human review;
- the current UTC confirmation time when a human explicitly marks the Listing
  reviewed but cannot safely select a SKU;
- ignored for queue membership while `sku` is non-null; and
- cleared when a later machine-derived state change makes a fresh unresolved
  review necessary, or when a human confirms a SKU.

The human action changes only `reviewed_unresolved_at`. It leaves `sku=NULL`
and preserves the existing `resolution_method`, `resolution_confidence`,
`resolved_at`, and every source-derived field. Django's admin log records the
actor; a second user foreign key is not required merely to derive the queue.

TASK_016 does not track catalogue versions or attempt to interpret an abstract
"material evidence change." It defines marker behavior only from the
machine-derived Listing result before and after `resolve_raw_listing()`:

| Before result | After result | `reviewed_unresolved_at` behavior |
| ------------- | ------------ | --------------------------------- |
| `unresolved` | `unresolved` | Preserve the existing value. |
| `unresolved` | `exact_alias` | Clear it. |
| `exact_alias` | `unresolved` | Clear it so the Listing requires fresh review. |
| `exact_alias` for SKU A | `exact_alias` for a different SKU B | Clear it. |
| `exact_alias` for SKU A | unchanged `exact_alias` for SKU A | Preserve the existing value, although it is irrelevant while `sku` is non-null. |
| `human_confirmed` | automatic resolver returns early | Preserve every field, including the marker. |

Historical `fuzzy_match` remains a valid machine-derived compatibility state.
TASK_014 does not emit it in v1, so a rerun will transition it to either
`unresolved` or `exact_alias`. TASK_016 hardening must freeze those historical
transitions explicitly; the marker is cleared because the machine result class
changes. It must not change the frozen validity of historical
`sku=NULL + fuzzy_match` rows or start emitting new fuzzy results.

This schema contract is **approval required** before TASK_016 hardening. It does
not redefine `unresolved`, `human_confirmed`, or `fuzzy_match` and preserves all
TASK_013 compatibility states.

## 6. Evidence presented to the reviewer

The review page must show these values as read-only evidence:

### 6.1 Raw source evidence

- exact `RawListing.raw_title`;
- derived normalized title produced by TASK_014's `normalise_title()` for
  comparison, without changing the raw title;
- exact `raw_price_text` and parsed `raw_price`;
- source identity;
- URL;
- pseudonymized seller;
- `fetched_at` and `occurred_at`;
- redacted payload; and
- RawListing primary/external identifiers where present.

The page must not attempt to recover or display plaintext seller identity.

### 6.2 Current derived evidence

- current SKU, if any;
- condition;
- resolution method and confidence;
- resolved and observed timestamps;
- price and location;
- price kind and trade side; and
- the current SKU's canonical brand, model, variant, and category where a SKU
  is already selected.

### 6.3 Catalogue evidence

The SKU selector must choose from existing canonical SKUs. Existing aliases for
the selected or current SKU should be inspectable without becoming editable in
the confirmation form.

Phase 4 does not promise ranking, recommendation, fuzzy search, or resolver
accuracy from this display. Ordinary Django admin lookup/search facilities may
be configured to make existing SKUs findable without changing resolution
semantics.

## 7. Human-confirmation contract

### 7.1 Confirm or correct an existing SKU

A successful human confirmation requires selection of one existing `Sku` and
sets exactly:

```text
Listing.sku = selected existing SKU
Listing.resolution_method = human_confirmed
Listing.resolution_confidence = Decimal("1.0000")
Listing.resolved_at = confirmation time
Listing.reviewed_unresolved_at = NULL
```

The confidence value represents the evidence class—an explicit human decision—
and is not a statistical accuracy claim.

Re-confirming a `human_confirmed` Listing to another existing SKU is an explicit
human correction and is allowed for authorized staff. It refreshes
`resolved_at` and produces an admin-log entry. Automatic resolver reruns remain
unable to make this change.

### 7.2 Condition remains outside entity confirmation

The Phase 4 Listing review workflow does not edit `Listing.condition`.
Entity `resolution_method="human_confirmed"` records a SKU decision only. The
current schema has no separate provenance or confirmation field for a human
condition correction, so combining the two decisions would make the evidence
ambiguous.

Existing nullable condition behavior remains unchanged. The review page may
display condition as read-only evidence, but must not infer, default, clear, or
overwrite it. A human condition-correction workflow requires a separately
designed contract later if product evidence establishes the need.

### 7.3 Fields preserved during confirmation

Human confirmation must preserve the current source-derived values of:

- `Listing.raw`;
- `price`;
- `condition`;
- `location`;
- `observed_at`;
- `price_kind`; and
- `trade_side`.

Those fields are outside the confirmation form. Missing values remain missing.

### 7.4 Atomicity and validation

Structural validation—including permissions, selected SKU, and optional alias
conflict checks—must complete before persistence. The Listing confirmation,
optional alias creation, and admin log record must be one atomic operation. A
conflict or unexpected exception must not leave a partially confirmed Listing
or partial alias.

## 8. Alias-curation contract

### 8.1 Explicit, integrated action

Alias creation is an optional, explicit action within a successful SKU
confirmation. It is unchecked by default. Confirming a Listing must not
silently create an alias.

When selected, the alias is constructed as:

```text
SkuAlias.sku = selected confirmed SKU
SkuAlias.alias_text = exact RawListing.raw_title
SkuAlias.normalised_text = normalise_title(RawListing.raw_title)
SkuAlias.source_of_truth = human_confirmed
```

This reuses the exact TASK_014 normalizer. The workflow must not implement a
different admin normalization rule.

### 8.2 Duplicate and conflict behavior

Because `normalised_text` is globally unique:

- no existing alias: create the human-confirmed alias;
- existing alias to the selected SKU: treat the alias request as idempotent and
  do not create a duplicate;
- existing alias to a different SKU: report a validation conflict and do not
  silently repoint it.

On a conflict, the administrator may return and confirm the Listing without
requesting alias creation. Repointing a global alias has effects beyond one
Listing and must not be hidden inside the confirmation action.

### 8.3 Alias correction and deletion

The review workflow never silently repoints an existing alias. Repointing, if
ever supported, requires a separate explicit human operation whose blast radius
is clear before confirmation.

`SkuAlias` deletion must be constrained wherever existing catalogue or Listing
references would make deletion unsafe or misleading. TASK_018 hardening must
inspect those relationships and freeze the exact add/change/delete permission
policy rather than this planning document inventing the implementation details.

Deleting, correcting, or adding an alias does not rewrite existing
machine-derived Listings immediately. TASK_015 must be run explicitly to
reconsider them. Human-confirmed Listings remain protected throughout.

## 9. Catalogue administration

### 9.1 SKU creation

The review form selects an existing SKU and does not create one inline. When a
canonical SKU is genuinely missing, an authorized curator creates it in the
separate `Sku` admin using the required canonical fields—including launch date
and Decimal launch MSRP—then returns to the Listing review.

This avoids deriving canonical data from an insufficient raw title. Phase 4
does not automate research or fill required SKU facts with placeholders.

### 9.2 SKU mutation and deletion

`Sku` remains human-curated catalogue data. Authorized catalogue users may add
and correct it through Django admin.

TASK_017 must establish one minimum deletion guardrail before the confirmation
workflow depends on the human-confirmed invariant: Django admin must refuse
individual and bulk deletion of any `Sku` referenced by a
`resolution_method="human_confirmed"` Listing. Otherwise the current `SET_NULL`
relationship could produce a human-confirmed row without its required SKU, and
TASK_014 would refuse to repair it automatically.

This is a normal-admin mutation guard, not a change to the existing foreign-key
schema in TASK_017. The constrained Listing form must likewise prevent forged
requests from clearing the SKU of a human-confirmed Listing.

Broader `Sku` and `SkuAlias` mutation/deletion policy remains TASK_018 work.
TASK_018 must inspect real Listings, aliases, and other references and freeze
the exact safe behavior rather than this document inventing it in advance.

No custom role model is needed. Django staff status and built-in model
permissions provide the authorization boundary:

- viewing the queue requires Listing view permission;
- confirming or correcting requires Listing change permission;
- creating an optional alias additionally requires SkuAlias add permission;
- creating or editing canonical SKUs requires the corresponding Sku permission;
  and
- any allowed catalogue deletion requires the corresponding explicit Django
  delete permission, the TASK_017 human-confirmed guard, and the later TASK_018
  guardrails.

TASK hardening must freeze the exact permission behavior before implementation.

## 10. Listing admin mutation boundary

Phase 4 must replace generic Listing CRUD with a constrained admin surface:

- Listing add is disabled;
- Listing delete is disabled;
- raw/source-derived and resolver bookkeeping fields are read-only;
- change is limited to the explicit confirmation/correction fields described
  above;
- there is no bulk confirmation action; and
- an unauthorized or forged request cannot update protected fields.

The Listing changelist provides the primary unresolved queue and access to
other Listings for explicit correction. It must not become a general editor for
derived provenance.

Django's existing admin `LogEntry` is sufficient to record who performed a
human confirmation or catalogue mutation. Phase 4 does not add a persistent
review-run or review-history model merely for UI convenience.

## 11. Review lifecycle and resolver interaction

The v1 lifecycle is:

1. TASK_015 delegates each immutable RawListing to TASK_014.
2. Exact curated alias hits become machine-derived `exact_alias` Listings.
3. Misses become `sku=NULL`; those without `reviewed_unresolved_at` enter the
   review queue.
4. A human inspects the source and derived evidence.
5. If the human cannot safely select a SKU, the workflow sets
   `reviewed_unresolved_at` without changing resolution evidence; unchanged
   reruns preserve it and keep the row out of the active queue.
6. If the human selects an existing canonical SKU, the workflow clears
   `reviewed_unresolved_at` and atomically records `human_confirmed` state.
7. In the later alias-curation task, the human may additionally request an
   explicit alias as part of that confirmation.
8. Later TASK_015 runs skip a human-confirmed Listing.
9. Other unresolved or machine-derived Listings may benefit from a new alias on
   the next explicit TASK_015 invocation.

Adding, deleting, or correcting an alias does not implicitly run the resolver.
Phase 4 adds no scheduler, background task, signal-driven bulk rewrite, or
source-health bookkeeping.

A human-confirmed mistake is corrected only by another explicit human action.
Automatic resolution must never reopen or overwrite it.

## 12. Schema impact assessment

Phase 4 requires one schema prerequisite before the review UI:

```text
Listing.reviewed_unresolved_at
    DateTimeField(null=True, blank=True)
```

This field is required for durable queue semantics, not UI convenience. It
prevents an explicitly reviewed unresolved Listing from reappearing forever
while leaving existing rows pending through the normal `NULL` value. No data
backfill is required.

TASK_016 must also update TASK_014's machine-rerun behavior for this current
state marker using only the explicit before/after result transitions in Section
5.3. It must not add catalogue versioning or a separate evidence-change
detector. Historical `fuzzy_match` transitions must be frozen during hardening.

The migration and resolver changes must not alter existing `sku`,
`resolution_method`, `resolution_confidence`, nullable fact fields, or
RawListing behavior. Historical `sku=NULL + fuzzy_match` remains valid and
enters the queue while the new marker is `NULL`.

No broader review model, status vocabulary, assignment field, reviewer foreign
key, or condition-confirmation schema is justified for v1. Django's admin log
continues to provide actor audit. Snoozed, assigned, or escalated workflow states
remain future product decisions.

## 13. Risks and invariants

### 13.1 Invariants

- `RawListing` remains immutable at Django and database levels.
- One and only one `Listing` relates to each `RawListing`.
- Human confirmation always selects an existing canonical SKU.
- Human confirmation always uses method `human_confirmed` and confidence
  `1.0000`.
- Human-reviewed unresolved state uses only `reviewed_unresolved_at`; it does
  not redefine the resolution method or confidence.
- Marker preservation or clearing follows only the explicit TASK_014
  before/after result transition table.
- Automatic reruns never overwrite human-confirmed state.
- A human-confirmed Listing always has a non-null existing SKU through the
  normal admin workflow.
- Reviewed-but-unresolved cannot be applied to a `human_confirmed` Listing and
  cannot be used to bless a null human-confirmed SKU.
- Missing source facts stay `NULL` or use their established empty-string
  convention.
- Alias normalization is identical to TASK_014 normalization.
- Alias creation is explicit and traces back to a human-confirmed decision.
- Global alias conflicts are never silently repointed.
- Money remains Decimal-only.
- No review action edits raw provenance or introduces downstream pricing state.

### 13.2 Principal risks

- Generic Listing admin editing could corrupt provenance or resolver metadata;
  it must be replaced by field-level restrictions.
- A globally unique alias assigned to the wrong SKU can misresolve many rows;
  alias creation must be opt-in and conflicts must be explicit.
- Human-confirmed rows are intentionally protected from automation; an explicit
  correction path is therefore necessary.
- Inline SKU creation would encourage invented launch facts; canonical creation
  remains a separate curated action.
- Deleting a SKU has wide effects through alias cascades and nullable Listing
  links; TASK_017 must first protect human-confirmed references and TASK_018
  must freeze the broader guardrails rather than rely on generic CRUD.
- Omitting durable reviewed-unresolved state would create an endless queue;
  TASK_016 must establish the marker and exact rerun transitions first.

## 14. Explicit non-goals

Phase 4 does not include:

- fuzzy or heuristic resolution;
- automatic SKU or alias creation;
- production catalogue or alias seed data;
- automatic external catalogue research;
- title-based condition inference;
- human condition correction within entity confirmation;
- statistical confidence calibration;
- bulk confirmation or bulk catalogue mutation;
- a custom review-history, assignment, or workflow-state model;
- a non-admin frontend or frontend framework;
- pricing baselines, deal scoring, or `DealFlag` work;
- outcome tracking changes;
- ingestion changes or new sources;
- TASK_008, source health, run bookkeeping, cron, or scheduling;
- resolver invocation triggered by an admin signal;
- web search, scraping, external APIs, embeddings, or LLM inference; or
- claims of market accuracy from synthetic tests.

## 15. Proposed task sequence

The task identifiers below are proposed planning order only. No contract or test
is frozen by this document.

### TASK_016 — Add durable reviewed-unresolved Listing state

Goal:

- add only nullable `Listing.reviewed_unresolved_at` and its minimal migration;
- preserve all TASK_013 resolution-method and compatibility semantics;
- update TASK_014 marker handling using the exact resolver-result transition
  table, including explicit historical `fuzzy_match` coverage; and
- freeze the resulting queue-state and rerun transitions before any admin UI is
  built.

Non-goals include admin review UI, reviewer assignment, general workflow state,
condition editing, alias work, and any resolver matching change.

### TASK_017 — Add constrained Listing review and human confirmation

Goal:

- replace generic Listing admin mutation with the durable unresolved queue and
  complete read-only evidence display;
- add an explicit "reviewed but unresolved" action that sets only the new
  marker and leaves resolution evidence unchanged;
- add an atomic confirmation/correction action selecting an existing SKU;
- enforce `human_confirmed`, `1.0000`, cleared review marker, and refreshed
  `resolved_at`;
- prevent individual, bulk, or forged normal-admin deletion/clearing of a SKU
  referenced by a human-confirmed Listing; and
- freeze permissions, protected fields, no add/delete behavior, admin logging,
  TASK_014/TASK_015 preservation, and RawListing immutability.

Condition remains read-only. Non-goals include alias creation, inline SKU
creation, bulk actions, automatic matching, and every Phase 5 pricing concern.

### TASK_018 — Add human-confirmed alias curation and catalogue guardrails

Goal:

- add the explicit opt-in alias action to successful review;
- reuse TASK_014 normalization;
- implement idempotent same-SKU behavior and blocking different-SKU conflicts;
- make confirmation plus optional alias atomic;
- constrain SkuAlias generic admin mutation;
- inspect real references and freeze the exact safe Sku/SkuAlias deletion
  policy; and
- prove how later TASK_015 reruns use the curated alias without overwriting
  human-confirmed Listings.

Non-goals include resolver auto-execution, alias repointing in the review form,
seed data, fuzzy matching, and schema changes.

Three small tasks are required because durable queue state is a schema and
resolver prerequisite for the UI, while higher-risk global alias mutation
remains separate from core confirmation. Do not add further Phase 4 tasks unless
hardening reveals a concrete dependency.

## 16. Human decisions required before hardening

One decision remains for owner approval:

1. **Durable reviewed-unresolved representation:** approve nullable
   `Listing.reviewed_unresolved_at`, the queue predicate
   `sku IS NULL AND reviewed_unresolved_at IS NULL`, and the TASK_016 rerun
   transition rules defined above.

The following boundaries are settled by the owner and are not open TASK_016
questions:

- condition remains unchanged and read-only during SKU confirmation;
- alias creation is explicit, opt-in, never automatic, and follows core review
  in TASK_018;
- alias conflicts block and never silently repoint;
- confirmation selects an existing SKU, while SKU creation remains separate
  curated catalogue administration; and
- catalogue deletion is constrained in principle, with the exact policy frozen
  from real reference behavior during TASK_018 hardening, after TASK_017 adds
  the minimum human-confirmed SKU guard.

TASK_016 may be hardened only after the remaining schema-state decision is
approved.

## 17. Phase 4 completion criteria

Phase 4 is complete when approved frozen tests and implementation demonstrate:

1. The primary admin queue shows every
   `sku IS NULL AND reviewed_unresolved_at IS NULL` Listing, including
   historical compatible states with a null marker.
2. Authorized reviewers can inspect complete immutable source evidence and
   current derived/catalogue evidence without editing it.
3. A reviewer can mark an unresolved Listing reviewed without altering its
   resolution method/confidence, and unchanged reruns do not requeue it.
4. Every TASK_014 before/after result transition preserves or clears the marker
   exactly as specified, including historical `fuzzy_match` inputs.
5. A reviewer can confirm or correct a Listing to an existing SKU using the
   exact human-confirmed field semantics.
6. Condition remains read-only and retains its existing nullable value.
7. Generic Listing add/delete and protected-field mutation are impossible.
8. Normal Django admin cannot delete or clear a SKU referenced by a
   human-confirmed Listing, including through bulk or forged requests.
9. Reviewed-but-unresolved rejects human-confirmed or inconsistent exact-alias
   rows with a null SKU rather than blessing them.
10. Human-confirmed results survive direct TASK_014 resolution and TASK_015
   operational reruns.
11. Optional alias creation is explicit, normalized by TASK_014 logic, atomic,
   idempotent for the same SKU, and rejects conflicting targets.
12. Catalogue and alias admin permissions enforce the approved mutation and
   deletion rules.
13. Alias changes affect other machine-derived Listings only after an explicit
   TASK_015 rerun; human-confirmed Listings remain unchanged.
14. No workflow path mutates RawListing, invents missing facts, creates an
    unapproved SKU, or writes pricing/review-run/scheduler state.
15. The only Phase 4 schema change is the approved TASK_016 marker, its
    nullability, and its explicit transition behavior.
16. The full PostgreSQL test suite and migration-drift validation remain clean.

## 18. Validation architecture

Each Phase 4 task must freeze acceptance tests before implementation. Synthetic
fixtures may establish deterministic workflow behavior but must not be used to
claim market resolution accuracy.

Validation must include, as applicable:

- Django admin authentication and model-permission checks;
- forged POST attempts against protected fields;
- confirmation and alias transaction rollback;
- reviewed-unresolved queue transitions and unchanged-rerun preservation;
- exact TASK_014 result-transition marker behavior, including historical
  `fuzzy_match` compatibility;
- individual, bulk, and forged SKU deletion/clearing attempts against
  human-confirmed Listings;
- RawListing application and PostgreSQL immutability;
- TASK_013 nullable/incomplete Listing compatibility;
- TASK_014 direct-rerun behavior;
- TASK_015 command-rerun behavior;
- alias uniqueness and conflict handling;
- no automatic SKU or alias creation;
- no downstream pricing or scheduler writes;
- the complete application test suite; and
- `makemigrations --check --dry-run`.

Runtime validation belongs to the independent validation phase. Static review
must verify the staged workflow, permission boundaries, test integrity, and
scope without demanding committed validation logs.
