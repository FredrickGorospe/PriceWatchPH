# TASK_030 — AlertDelivery persistence and the unique claim

## 1. Goal

Establish the persistence substrate for Phase 7 alerts: exactly one durable
`AlertDelivery` claim per `DealFlag`, whose **identity cannot move**, whose
**row cannot be removed**, and whose lifecycle is a **database-enforced one-way
transition** `pending → sent | failed`.

The row is the durable claim. Because `docs/07_PLANNING.md` §4 makes the
*absence* of a row the eligibility condition, a claim that could be deleted or
reassigned would silently reopen a DealFlag for a second irreversible Telegram
send. Preventing that at the database layer — not in future application code —
is this task's core deliverable.

This task is **persistence only**. It contains no networking, no Telegram, no
configuration, no eligibility query, no command, and no admin registration.

## 2. Authority and dependencies

This task follows:

- `CLAUDE.md`;
- `docs/07_PLANNING.md` (committed at `ae403b8`), owner-approved, authoritative
  for every Phase 7 product decision. Sections 3.1, 3.10, 4, 7, and 16 bind
  this task directly;
- TASK_004 (`outcomes/tests/test_task_004_outcomes.py`), the repository's
  precedent for a frozen schema-acceptance test;
- TASK_019 (`pricing/tests/test_task_019_pricing_evidence.py` and
  `pricing/migrations/0002_auditable_pricing_evidence.py`), the precedent for
  freezing exact field metadata, constraint names, and **PostgreSQL trigger
  guards that survive ORM bypasses**;
- TASK_028, the precedent for a PostgreSQL concurrency proof
  (`@pytest.mark.django_db(transaction=True)` + `threading.Barrier`).

### 2.1 Approved Phase 7 semantics this task must support

From `docs/07_PLANNING.md` §7:

- **at-most-once send attempt per DealFlag**;
- exactly one logical `AlertDelivery` per `DealFlag`;
- lifecycle `pending → sent` or `pending → failed`;
- the row **is** the durable claim, written before any network I/O;
- the **absence** of a row is what later makes a DealFlag alert-eligible;
- **any** existing row — `pending`, `sent`, or `failed` — means no future
  normal send attempt.

TASK_030 makes these representable, database-enforced, and **tamper-resistant**.
TASK_032 implements the orchestration that relies on them.

## 3. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_030_ALERT_DELIVERY_PERSISTENCE.md`
- `tests/test_task_030_alert_delivery_persistence.py`

Test placement follows existing precedent: the root `tests/` package already
hosts TASK_028's outcomes-app tests and TASK_027's ingestion tests. Because
TASK_030 introduces a new app that does not exist at HARDEN time, placing the
frozen tests here avoids creating any production package during HARDEN.

### IMPLEMENT files allowed — after owner approval

- `alerts/__init__.py` (new)
- `alerts/apps.py` (new)
- `alerts/models.py` (new)
- `alerts/migrations/__init__.py` (new)
- `alerts/migrations/0001_initial.py` (new)
- `config/settings.py` — **only** to append `"alerts"` to `INSTALLED_APPS`

Nothing else. Specifically **not** authorized: `alerts/admin.py` (TASK_033),
`.env.example`, any existing model, any existing migration, any frontend file,
any Phase 7 environment variable.

## 4. Exact schema contract

### 4.1 App and model placement

A new Django app, `alerts`, registered in `INSTALLED_APPS` after `"outcomes"`,
matching the existing domain-app ordering. `AppConfig` follows the established
one-class form used by every app in this repository
(`default_auto_field = "django.db.models.BigAutoField"`, `name = "alerts"`).

The model is `alerts.models.AlertDelivery`.

### 4.2 Status vocabulary

Module-level choices, matching the repository convention established by
`CONDITION_CHOICES`, `RESOLUTION_METHOD_CHOICES`, `PRICE_KIND_CHOICES`, and
`CATEGORY_CHOICES`:

```python
ALERT_DELIVERY_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("sent", "Sent"),
    ("failed", "Failed"),
]
```

Exactly three values. `sent` — never `delivered` — per `docs/07_PLANNING.md`
Decision G: it records that the Bot API accepted the message, not that a human
received or read it.

### 4.3 Fields

| Field | Type | Null | Purpose under the approved plan |
|---|---|---|---|
| `deal_flag` | `OneToOneField(DealFlag, on_delete=PROTECT, related_name="alert_delivery")` | no | The claim's identity. Immutable after insert (§7). |
| `status` | `CharField(max_length=20, choices=ALERT_DELIVERY_STATUS_CHOICES)` | no | The lifecycle state. Always `pending` at insert. |
| `claimed_at` | `DateTimeField()` | no | When the claim was written, before network I/O. Immutable after insert (§7). Required by plan §11 to diagnose a stuck `pending` row and by §12's "was this claimed, when". |
| `terminal_at` | `DateTimeField(null=True, blank=True)` | yes | When the row reached `sent`/`failed`. Null exactly while `pending`. Never earlier than `claimed_at` (§6). |
| `failure_detail` | `TextField(null=True, blank=True)` | yes | Sanitized, application-owned failure information, required by plan §10.3, which forbids persisting the request URL or raw transport exception text. Non-null and non-empty exactly when `failed`. |

`max_length=20` on `status` matches `Listing.condition` and `Sku.category`.
`claimed_at` takes **no** `auto_now_add` and **no** default, matching
`DealFlag.flagged_at`, which its writing service sets explicitly.

`null=True, blank=True` on `terminal_at` and `failure_detail` describes only
what the *column* permits. The persisted-state invariants are owned by the
database constraints in §6 and the trigger in §7 — never by Django's `blank`,
which is form-layer validation and is bypassed entirely by `objects.create()`,
`QuerySet.update()`, and raw SQL.

### 4.4 Fields deliberately excluded

Per `docs/07_PLANNING.md` §2, §8, and §16, and stated here so their absence is
frozen rather than accidental: no attempt count, no retry count, no
`next_retry_at`, no cooldown timestamp, no channel field, no recipient field,
no Telegram message id, no payload snapshot, no metadata JSON, no generic
notification type, and no separate `AlertAttempt` model.

A Telegram message id is excluded because no approved v1 behavior reads one:
Decision I forbids resend, Decision H forbids retry, and Decision G defines
`sent` by the response being successful, not by retaining its identifier.

## 5. Uniqueness and concurrency contract

**The database allows at most one `AlertDelivery` for a given `DealFlag`.**

Enforced by `OneToOneField`, which Django implements as a `UNIQUE` column
constraint — a database guarantee, not model or form validation. This follows
the exact precedent of `Outcome.deal_flag` (`docs/07_PLANNING.md` §3.10), and
repository inspection surfaced no reason to prefer a separate explicit
`UniqueConstraint`.

A second insert for the same DealFlag must raise `IntegrityError`, including
when two threads race with real transactions. The frozen concurrency test
proves exactly one durable winner and exactly one persisted row.

### 5.1 Uniqueness alone is not the guarantee

`UNIQUE` prevents a **second simultaneous** claim. It does **not** prevent the
existing claim from being deleted or from having its `deal_flag_id` reassigned
to another row — and either operation leaves the original DealFlag with no row,
which under the approved eligibility rule (`docs/07_PLANNING.md` §4) makes it
claimable and sendable again.

The durable at-most-once substrate therefore requires **both**:

1. `UNIQUE` on `deal_flag` — no second concurrent claim; and
2. the lifecycle/delete guard in §7 — the existing claim cannot be moved or
   removed, so eligibility can never reopen.

Neither property is sufficient alone. This corrects an earlier draft of this
specification, which froze only (1) and explicitly stated that no delete guard
or trigger should exist — a gap that would have left the at-most-once claim
unenforced against `QuerySet.delete()`, raw SQL, and `deal_flag_id`
reassignment.

**Scope boundary:** TASK_030 proves the database properties. TASK_032 later
proves they yield exactly one external adapter invocation, and that the claim is
committed before any network I/O. No network concept appears in TASK_030.

## 6. Declarative state invariants

Four `CheckConstraint`s, named with the repository's
`<modelname>_<description>` convention:

1. **`alertdelivery_status_in_vocabulary`** — `status` is one of the three
   approved values, expressed as
   `Q(status__in=[c[0] for c in ALERT_DELIVERY_STATUS_CHOICES])`, matching
   `listing_condition_in_vocabulary`.

2. **`alertdelivery_terminal_at_matches_status`** — `terminal_at` is null if
   and only if `status` is `pending`. A `pending` row with a terminal
   timestamp, and a `sent`/`failed` row without one, are both unstorable.

3. **`alertdelivery_failure_detail_matches_status`** — `failure_detail` is
   non-null and non-empty if and only if `status` is `failed`. A `pending` or
   `sent` row carrying *any* `failure_detail` — empty string included — and a
   `failed` row with null or empty detail, are all unstorable. Mirrors the
   existing `outcome_skip_reason_required_when_not_acted` shape.

4. **`alertdelivery_terminal_at_not_before_claimed_at`** — when `terminal_at`
   is non-null it is `>= claimed_at`. A terminal event cannot predate the claim
   it terminates. Equality is valid: a claim and its terminal record can land
   within the same clock tick. Expressed as
   `Q(terminal_at__isnull=True) | Q(terminal_at__gte=F("claimed_at"))`,
   following the `pricepoint_window_bounds_ordered` precedent for an ordering
   constraint between two columns.

A `CheckConstraint` sees only one row version and cannot compare `OLD` to `NEW`,
so none of these can express a *transition* rule or prevent `DELETE`. That is
the trigger's job (§7).

## 7. One-way lifecycle, claim identity, and deletion

### 7.1 What must be enforced

`AlertDelivery` is **not immutable**. It is *mutable for exactly one
transition*, with claim identity and terminal history protected:

**INSERT** — a row may only be created as `status = 'pending'`. Direct creation
as `sent` or `failed` is not part of the approved lifecycle and is rejected. The
claim is always written pending, before any future network I/O. (The §6
constraints already force `terminal_at` and `failure_detail` to be null when
`status = 'pending'`, so the insert rule needs no separate null checks.)

**UPDATE** — permitted only when *all* hold:

- the previous `status` is `pending`;
- the new `status` is `sent` or `failed`;
- `deal_flag_id` is unchanged;
- `claimed_at` is unchanged.

Everything else is rejected, which covers: `sent → pending`, `sent → failed`,
`failed → pending`, `failed → sent`, any rewrite of `terminal_at` or
`failure_detail` on a row that is already terminal, any `pending → pending`
no-op update, and any reassignment of the claim to a different DealFlag.

**DELETE** — never permitted, at any status. Deleting the row would leave the
DealFlag with no claim and reopen it under the approved eligibility rule,
destroying the at-most-once guarantee.

### 7.2 Mechanism — a purpose-built PostgreSQL trigger

Ordinary constraints cannot compare row versions or block `DELETE`, so this is
frozen as a PostgreSQL trigger installed by the migration, following the
TASK_019 precedent in `pricing/migrations/0002_auditable_pricing_evidence.py`.

This is **not** a blanket TASK_019-style immutability trigger. Such a trigger
blocks every `UPDATE` and would make the approved `pending → sent | failed`
transition impossible. The guard below is purpose-built.

Naming follows the established `<app>_<table>_task<NNN>_<purpose>` form:

- function: `alerts_alertdelivery_task030_enforce_lifecycle()`
- trigger: `alerts_alertdelivery_task030_lifecycle_guard`,
  `BEFORE INSERT OR UPDATE OR DELETE ... FOR EACH ROW`

Semantics, in order:

```text
DELETE  -> always RAISE EXCEPTION
INSERT  -> RAISE EXCEPTION unless NEW.status = 'pending'
UPDATE  -> RAISE EXCEPTION if OLD.deal_flag_id IS DISTINCT FROM NEW.deal_flag_id
           RAISE EXCEPTION if OLD.claimed_at   IS DISTINCT FROM NEW.claimed_at
           RAISE EXCEPTION if OLD.status <> 'pending'
           RAISE EXCEPTION if NEW.status NOT IN ('sent', 'failed')
           otherwise permit
```

Messages follow TASK_019's readable style (`RAISE EXCEPTION '... : % ...',
TG_OP` / the offending value). A bare `RAISE EXCEPTION` carries SQLSTATE
`P0001`, which Django surfaces as `django.db.utils.ProgrammingError` — the same
exception TASK_019's frozen tests assert. Constraint violations (§6) surface as
`IntegrityError`. The frozen tests distinguish the two deliberately.

`RunSQL` supplies `reverse_sql` that drops the trigger then the function, using
`IF EXISTS`, exactly as `DROP_IMMUTABILITY_TRIGGERS_SQL` does.

**Verified safe against test teardown.** A row-level `BEFORE DELETE` trigger
does not fire on `TRUNCATE`, which is what pytest-django uses to reset the
database after `@pytest.mark.django_db(transaction=True)` tests. This is not an
assumption: `pricing_dealflag` already carries an always-raise DELETE trigger
from TASK_019, and TASK_028's transactional concurrency test creates DealFlags
and passes in the current green baseline.

### 7.3 Model-level guard

Following the TASK_019 precedent — where `DealFlag` and `PricePoint` carry both
a database trigger and a model-level override that raises a readable
`ValidationError` — `AlertDelivery.delete()` raises `ValidationError` so an ORM
caller gets a clear message rather than a raw database error.

The model does **not** receive a blanket `save()` override: the approved
transition must remain possible through ordinary ORM `save()`, and the trigger
already enforces the transition rules against every path, including the ones a
model method cannot see. The database guard is mandatory; the model guard is
ergonomics only.

### 7.4 Superseded reasoning

An earlier draft of this specification argued that reverting a terminal row to
`pending` was harmless "because a row reverted to pending still exists and still
blocks every future send". That reasoning was unsound: it assumed the row could
not be deleted or reassigned, which nothing in that draft enforced. With §7.1's
guard the row genuinely cannot be removed or moved, and the one-way lifecycle is
enforced directly rather than argued around.

## 8. Deletion and protection contract

Two **separate** guarantees, easily confused:

1. **`AlertDelivery.deal_flag` uses `on_delete=PROTECT`.** This governs what
   happens to *this row* if the referenced `DealFlag` were deleted, and matches
   every foreign key in `pricing/models.py`, `listings/models.py`, and
   `outcomes/models.py`.

   *Honest note on testability:* TASK_019 installed triggers
   (`pricing_dealflag_task019_immutable`) rejecting `UPDATE` and `DELETE` on
   `pricing_dealflag`, and `DealFlag.delete()` additionally raises
   `ValidationError`. No code path can delete a `DealFlag`, so `PROTECT` is
   **structurally unreachable at runtime**; a test provoking `ProtectedError`
   would exercise TASK_019's trigger, not this declaration. The frozen test
   therefore asserts the declaration
   (`field.remote_field.on_delete is PROTECT`), exactly as
   `test_dealflag_retains_foreign_key_and_frozen_constraints` does.

2. **`AlertDelivery` itself is undeletable after creation** (§7.1), enforced by
   the trigger against `QuerySet.delete()` and raw SQL, and by the model guard
   for ORM ergonomics. This exists for a different reason: not referential
   integrity, but because destroying the durable claim would reopen the DealFlag
   and break at-most-once.

TASK_030 changes no existing model. `DealFlag` immutability, `PricePoint`
immutability, and `Outcome` are untouched.

## 9. Migration contract

One migration, `alerts/migrations/0001_initial.py`, matching the repository's
`0001_initial.py` naming for a new app (`outcomes`, `pricing`, `listings`).

It creates the `AlertDelivery` table with its unique `deal_flag` column and all
four check constraints, then installs the §7.2 lifecycle guard via
`migrations.RunSQL(CREATE_..., reverse_sql=DROP_...)`, following the TASK_019
migration's structure.

It contains **no data migration** — in particular, **no backlog-suppression
rows**, which `docs/07_PLANNING.md` Decision C explicitly rejects. It modifies
no existing migration.

`makemigrations --check --dry-run` must report no changes after implementation:
migration state and model state must match exactly.

## 10. Acceptance criteria — frozen

The authoritative executable artifact is
`tests/test_task_030_alert_delivery_persistence.py`.

It freezes, at minimum:

**Schema**
- the model is importable from `alerts.models` and the app is installed;
- `deal_flag` is a `OneToOneField` to `DealFlag` with `on_delete=PROTECT` and
  `related_name="alert_delivery"`;
- exact field metadata for `status`, `claimed_at`, `terminal_at`, and
  `failure_detail`, including null/blank/default;
- the status vocabulary is exactly `pending`, `sent`, `failed`;
- the four constraint names exist.

**Claim creation**
- a new row is storable as `pending` and round-trips;
- direct creation as `sent` is rejected;
- direct creation as `failed` is rejected.

**One claim per DealFlag**
- a second row for the same DealFlag raises `IntegrityError`;
- a DealFlag whose claim has been driven to `sent` through the approved
  transition still rejects a second claim;
- the same for a claim driven to `failed`;
- distinct DealFlags each get their own claim;
- two concurrent threads produce exactly one durable winner and one row.

**Claim identity is immutable**
- `deal_flag_id` cannot be reassigned to another DealFlag, proven through a
  bypass path (`QuerySet.update()` / raw SQL), not only model validation;
- `claimed_at` cannot be changed.

**One-way lifecycle**
- `pending → sent` persists;
- `pending → failed` with sanitized detail persists;
- `sent → pending`, `sent → failed`, `failed → pending`, `failed → sent` are all
  rejected;
- terminal evidence cannot be rewritten while remaining in the same terminal
  status.

**Deletion**
- `QuerySet.delete()` is rejected;
- raw SQL `DELETE` is rejected;
- the model-level `delete()` guard raises a readable `ValidationError`;
- deleting a claim cannot reopen its DealFlag.

**Timestamp chronology**
- `terminal_at == claimed_at` is valid;
- `terminal_at > claimed_at` is valid;
- `terminal_at < claimed_at` is rejected by the database.

**Failure-detail null semantics**
- for `pending` and `sent`, both `""` and non-empty text are rejected;
- for `failed`, null and `""` are rejected and sanitized non-empty text is
  accepted.

**Scope**
- no retry/attempt-history field exists on the model;
- no recipient, channel, or generic-notification field or model exists;
- no second model exists in the app;
- `DealFlag` and `Outcome` relationships remain intact and unmodified.

## 11. Explicit non-goals

TASK_030 does not include or scaffold: any network call; Telegram anything; any
environment variable, setting, or `.env.example` change beyond adding `"alerts"`
to `INSTALLED_APPS`; the activation cutoff; the public application base URL; the
enable flag; payload construction; the eligibility query; the
`send_deal_alerts` command; claim/send orchestration; admin registration
(TASK_033); retry, resend, attempt history, or cooldown of any kind; a recipient
or channel abstraction; any change to `DealFlag`, `PricePoint`, `Outcome`, or
any existing migration; and any frontend work.

## 12. Validation

HARDEN baseline (implementation absent — failures expected and intentional):

```text
docker compose exec web pytest -v tests/test_task_030_alert_delivery_persistence.py
```

After implementation:

```text
docker compose exec web pytest -v tests/test_task_030_alert_delivery_persistence.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py check
```

A full backend run is justified because this task adds a migration and changes
`INSTALLED_APPS`, which every test in the suite loads
(`docs/07_PLANNING.md` §19). No frontend validation applies: TASK_030 has no
frontend scope.

## 13. Stop conditions

Implementation stops and reports rather than improvising if: the §7.2 trigger
cannot express the one-way lifecycle safely on the real PostgreSQL 16 schema; a
frozen TASK_004, TASK_019, or TASK_028 assertion breaks from the new app,
migration, or trigger; the DELETE guard interferes with test-database teardown
in a way §7.2's verification did not predict; or any frozen behavior in Section
10 turns out to require changing an existing model, an existing migration, or
Phase 7 configuration that TASK_031 owns.

No implementation begins until this specification and its frozen acceptance
module receive explicit owner approval.
