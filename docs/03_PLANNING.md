# 03 — Planning: Phase 3

Planning artefact only. This document defines Phase 3's entity-resolution
contract; it does not implement the resolver, change the schema, create a
migration, or establish frozen acceptance tests.

It follows `CLAUDE.md`, `docs/ROADMAP.md`, `docs/00_PLANNING.md`, the committed
TASK_005–TASK_007 contracts, and the current models. Where earlier planning
describes a state that the approved ingestion paths cannot represent honestly,
Section 11 records the narrow Phase-3 correction rather than rewriting the
historical planning documents.

---

## 0. Phase status and numbering

Phase 1 is complete for the currently approved source model:

- TASK_005 established provenance, observation timestamps, price-kind and
  trade-side fields, payload retention, and seller pseudonymisation.
- TASK_006 writes one immutable `RawListing` per `manual_capture` command
  invocation.
- TASK_007 writes forward-only personal buy, sell, and swap observations under
  `personal_records` through Django admin.

TASK_008 is deferred. Neither approved source is scheduled: `manual_capture`
is explicitly human-triggered and `personal_records` is admin entry. Until an
approved automated source exists, scheduler-facing summaries,
`Source.last_successful_fetch` health semantics, batch-run bookkeeping, and
cron deployment would describe a system that is not currently operated.

This file is `03_PLANNING.md` because planning filenames follow roadmap phase
numbers. Phase 2 deployment/scheduling is deferred rather than renumbered.

The current local development database has separately been observed to be
behind committed migrations and to contain no `RawListing` rows. That is a
local runtime and corpus-readiness fact, not a repository product gap. It does
not block TASK_013 hardening or PostgreSQL test-driven implementation, and
applying migrations is not a product task.

---

## 1. Goal and governing transformation

Phase 3 derives a reproducible, correctable interpretation from every immutable
source observation:

```text
immutable RawListing
    ->
mutable derived Listing
    ->
canonical human-curated Sku when safely resolvable
```

The v1 resolver is deterministic and local. It may normalize a title for
matching, consume curated aliases, copy source facts, and create or update the
one derived `Listing` associated with a `RawListing`.

It must not:

- edit or delete `RawListing`;
- invent a canonical `Sku` or alias;
- infer a price, condition, trade side, or price kind without source evidence;
- perform fuzzy assignment before a separately approved and empirically
  calibrated matcher exists;
- use web search, scraping, an LLM/API, embeddings, or another external lookup;
- compute pricing baselines or deal scores; or
- absorb Phase 4 review UI or deferred TASK_008 scheduling concerns.

An unresolved observation remains useful derived state. The resolver records
uncertainty explicitly rather than guessing a SKU or dropping the observation.

---

## 2. Catalogue and alias ownership

`Sku` is human-curated canonical data. Automatic resolution consumes the
catalogue but never creates `Sku` rows. This prevents source typos, incomplete
titles, and ambiguous variants from becoming canonical product identities.

`SkuAlias` is curated resolution evidence:

- each `normalised_text` is globally unique;
- each alias points to exactly one canonical `Sku`;
- aliases may come from seed data or a future explicit human confirmation;
- the automatic resolver may consume aliases but may not create aliases from
  guesses; and
- exact alias matching outranks any future heuristic or fuzzy mechanism.

Phase 3 does not define a seed catalogue or seed alias corpus. Those require
separate approved evidence. Phase 4 may later allow a human confirmation to
create a `human_confirmed` alias for subsequent exact matching.

---

## 3. Persistence and component boundaries

### 3.1 RawListing

`RawListing` remains the authoritative source observation and remains immutable
at both the Django and PostgreSQL layers. Resolution reads it; resolution never
repairs, enriches, deletes, or otherwise modifies it.

The resolver must preserve the distinction between source facts and derived
facts. A later catalogue or resolver improvement is expressed by re-deriving
the associated `Listing`, not by rewriting the observation.

### 3.2 Listing

`Listing` is mutable derived state. Its existing one-to-one relationship with
`RawListing` enforces at most one current derivation per observation, preventing
one observation from entering later pricing work more than once.

The resolver may:

- create the `Listing` on first derivation;
- update machine-derived fields when a rerun produces a materially different
  result; and
- leave an unchanged machine-derived result untouched.

A `human_confirmed` Listing is authoritative and must not be overwritten by an
automatic rerun. Phase 3 does not implement the human workflow that produces
that state.

### 3.3 Downstream boundary

Phase 3 writes no `PricePoint`, `DealFlag`, or `Outcome` rows and performs no
baseline, plausibility, deal, or realised-margin calculation. Those components
consume derived facts in later phases.

---

## 4. Immediate schema prerequisite — TASK_013

The current `Listing` schema requires values that approved ingestion paths do
not always know. The resolver must represent incomplete source evidence
honestly before it can be implemented.

The immediate next task is:

```text
TASK_013 — Allow honest incomplete Listing derivations
```

TASK_013 contains exactly three schema changes.

### 4.1 Listing.price becomes nullable

Retain:

```python
DecimalField(max_digits=12, decimal_places=2)
```

and retain non-negative enforcement for every non-NULL value.

`RawListing.raw_price` legitimately permits NULL when an observation has
truthful but unparseable source price text. Resolution copies that NULL. It
must not fabricate zero, invent a price, or discard the observation.

### 4.2 Listing.condition becomes nullable

Retain the existing vocabulary for every non-NULL value:

- `new`
- `like_new`
- `used`
- `for_parts`

TASK_006 supplies no condition fact, and TASK_007 permits absent condition
evidence. The resolver must not default missing condition to `used` or infer it
from a title in v1.

### 4.3 Listing.resolution_method gains unresolved

Add:

```python
("unresolved", "Unresolved")
```

to both the Django choices and the database vocabulary constraint. Retain all
existing values:

- `exact_alias`
- `fuzzy_match`
- `human_confirmed`
- `unresolved`

`fuzzy_match` remains available for a future matcher that genuinely executes
that mechanism. New v1 output must not claim `fuzzy_match` when no fuzzy
matching occurred.

TASK_013 must not add a cross-field constraint forbidding
`sku=NULL, resolution_method="fuzzy_match"`. Frozen TASK_004 tests already
construct that historical valid state. Expanding the vocabulary preserves
those tests while making new resolver output semantically honest.

No data backfill is required.

### 4.4 Fields TASK_013 does not change

- `resolved_at` stays non-null. It records when the current derivation was
  produced, including an unresolved derivation.
- `observed_at` stays nullable at schema level for frozen-test compatibility,
  although the resolver must populate it.
- `price_kind` stays nullable because `manual_capture` does not classify every
  captured price honestly.
- `trade_side` stays nullable.
- `location` retains the existing empty-string absence convention.

TASK_013 does not implement normalization or resolution. It does not change
ingestion, create a catalogue, tighten `observed_at` or `price_kind`, implement
fuzzy matching, add review UI, perform pricing work, or revive TASK_008.

---

## 5. Deterministic title normalization v1

Normalization exists only as a derived matching representation.
`RawListing.raw_title` remains byte-for-byte outside the resolver's write
surface.

The v1 normalization pipeline is deliberately conservative:

1. Apply Unicode NFKC normalization.
2. Apply Unicode case-folding.
3. Convert punctuation and separators into token boundaries.
4. Collapse derived whitespace.
5. Preserve every alphanumeric token and its order.

V1 does not:

- strip price-looking fragments;
- remove generic or noise words;
- remove brand terms, capacities, or generation numbers;
- remove or simplify variant tokens;
- split letter/digit runs; or
- add domain-specific fuzzy normalization without representative evidence.

This conservatism protects discriminating information such as `Ti`, `Super`,
`XT`, `XTX`, GB capacity, generation numbers, mobile/laptop suffixes, and
board-partner or product-line variants such as OC, Gaming, Ventus, and TUF.

The same deterministic normalization must govern alias creation and alias
lookup. Otherwise apparently identical strings could be persisted under a form
the resolver can never reproduce.

---

## 6. V1 matching and resolution states

V1 performs exact normalized alias lookup only.

### Exact curated alias

If the normalized title exactly equals one curated
`SkuAlias.normalised_text`:

```python
sku = alias.sku
resolution_method = "exact_alias"
resolution_confidence = Decimal("1.0000")
```

The confidence means exact identity with curated evidence, not a statistical
market-accuracy claim.

### Unresolved

If no exact alias exists:

```python
sku = None
resolution_method = "unresolved"
resolution_confidence = Decimal("0.0000")
```

This state says that no approved matching mechanism established a canonical
SKU. It does not mean a fuzzy matcher ran and rejected a candidate.

### Human confirmed

A future Phase 4 confirmation may produce:

```python
sku = confirmed_sku
resolution_method = "human_confirmed"
resolution_confidence = Decimal("1.0000")
```

Automatic resolution must preserve that result.

### Future fuzzy matching

`fuzzy_match` may be written only by a future resolver that actually executes
an approved fuzzy method. Its confidence must be calibrated from independently
human-labelled, representative evidence rather than assigned as an arbitrary
percentage. Until that contract exists, a non-exact title remains
`unresolved`.

---

## 7. Source-fact propagation

Resolution copies source facts; it does not manufacture them.

| Listing field | V1 derivation |
|---|---|
| `raw_listing` | The immutable observation being derived. |
| `sku` | Exact curated alias target, otherwise NULL. |
| `price` | `RawListing.raw_price`, including NULL. |
| `observed_at` | `RawListing.occurred_at` when present, otherwise `RawListing.fetched_at`. |
| `condition` | Explicit approved source-payload fact when present, otherwise NULL. |
| `location` | Explicit source evidence when available, otherwise the existing empty-string absence convention. |
| `price_kind` | Explicit source provenance fact when present, otherwise NULL. |
| `trade_side` | Explicit stated trade side when present, otherwise NULL. |
| `resolved_at` | The time the current derivation was produced. |

Condition extraction from title text is outside v1. An ambiguous or absent
condition remains NULL.

For `personal_records`, `stated_trade_side` is authoritative when present and
is copied to `trade_side`. When the source fact establishes a completed trade,
`price_kind` is `realised`.

For `manual_capture`, the approved input contract currently supplies no
condition, trade side, or fact that classifies every price as asking or
realised. Those derived fields therefore remain NULL.

The implementation should consume explicit payload/provenance facts rather
than make source-name checks its only semantic evidence. If the current
persisted facts prove insufficient to perform an approved mapping, work stops
for contract correction instead of inventing data.

---

## 8. Rerun and correction semantics

Resolution is re-runnable because `RawListing` is immutable and `Listing` is
the current mutable derivation.

For each `RawListing`:

1. No existing Listing: create the one derived Listing.
2. Existing machine-derived Listing with the same result: perform no
   unnecessary write and leave `resolved_at` unchanged.
3. Existing machine-derived Listing with a changed result: update the derived
   fields and set `resolved_at` to the new derivation time.
4. Existing `human_confirmed` Listing: skip automatic replacement.

Both unresolved and exact machine-derived rows may be reconsidered. A newly
curated alias may promote `unresolved` to `exact_alias`; removing or repointing
an alias may change a prior machine-derived result on rerun.

The complete future review queue is identified primarily by `sku IS NULL`, not
only by `resolution_method="unresolved"`. This preserves the frozen historical
`sku=NULL, fuzzy_match` state and the existing `SET_NULL` behavior if a linked
SKU is removed. New v1 unresolved writes still use the explicit `unresolved`
method.

Human confirmation remains authoritative until a future human workflow
explicitly changes it.

---

## 9. Correctness fixtures and empirical evaluation

Deterministic contract correctness and market-resolution accuracy are separate
questions.

### 9.1 Frozen acceptance fixtures

A later HARDEN pass may use a small hand-authored synthetic corpus to freeze:

- Unicode normalization, case-folding, punctuation boundaries, and whitespace;
- exact alias matches and misses;
- preservation of Ti, Super, XT, XTX, capacities, generation numbers,
  mobile suffixes, and board-partner/product variants;
- NULL price propagation;
- present and absent condition evidence;
- trade provenance propagation;
- create, unchanged-rerun, changed-rerun, and unresolved-promotion behavior;
  and
- preservation of human-confirmed Listings.

Those fixtures prove only that the implementation follows the deterministic
contract. They do not estimate production accuracy.

### 9.2 Later empirical corpus

Any accuracy evaluation requires a real approved-source corpus independently
labelled by a human with:

- canonical SKU or unresolved; and
- condition where the evidence makes it knowable.

Any published accuracy claim must include sample size, collection period,
source mix, sampling method, labelling method, resolver version,
auto-resolution precision, coverage/unresolved rate, and condition accuracy
only where ground truth is knowable.

No accuracy percentage may be claimed from synthetic fixtures alone. No new
source is scraped or collected merely to support Phase 3 planning.

---

## 10. Phase boundaries and task order

### Phase 4

Phase 3 creates resolved and unresolved derived states. Phase 4 owns the
dedicated Django-admin review workflow, human correction, and any explicit
alias creation resulting from confirmation. The review UI is not pulled into
Phase 3 without a later concrete dependency.

Django admin remains the UI through Phase 5.

### Deferred TASK_008

Phase 3 does not define or implement:

- `Source.last_successful_fetch` semantics;
- scheduler contracts or cron deployment;
- batch ingestion or run summaries; or
- rows-read, rows-written, or rows-rejected bookkeeping.

TASK_008 remains deferred until an approved automated source gives those
concepts honest operational meaning.

### Immediate order

Only the immediate dependency is fixed:

1. HARDEN and implement TASK_013's three schema corrections.
2. After TASK_013, use the corrected schema to harden the smallest deterministic
   normalization/resolution task supported by then-current repository evidence.

No additional task ID or detailed implementation contract is frozen here.

---

## 11. Phase-3 planning corrections

For Phase 3 work, this document supersedes only these materially stale
assumptions in earlier planning:

1. An unresolved row must not use `fuzzy_match` when no fuzzy matcher ran. New
   v1 output uses `unresolved` with confidence `0.0000`.
2. `Listing.price` cannot remain required when truthful approved observations
   may have `RawListing.raw_price=NULL`.
3. `Listing.condition` cannot remain required when approved ingestion permits
   missing condition evidence.
4. `price_kind` cannot immediately become non-null for every source because
   `manual_capture` currently lacks enough evidence for universal
   classification.

All other historical planning remains historical context. This document does
not rewrite `docs/00_PLANNING.md`, `docs/01_PLANNING.md`, or
`docs/ROADMAP.md`.

---

## 12. TASK_013 completion boundary

TASK_013 is complete only when its separately approved frozen tests establish
the three schema changes, existing TASK_004 semantics remain valid, PostgreSQL
constraints express the expanded honest states, and the repository-wide
validation required by `CLAUDE.md` is clean:

```text
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
```

This section records the future validation boundary only. No TASK_013 test,
model change, or migration is part of this planning artefact.
