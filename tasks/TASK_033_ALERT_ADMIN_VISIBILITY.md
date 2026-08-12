# TASK_033 — Alert admin visibility

## 1. Goal

Register `AlertDelivery` in the Django admin, read-only, so an operator can
answer *"was this deal flag claimed, when, did it send, and did it fail"* — and
so a stuck `pending` row becomes visible.

This is the last task of Phase 7. It adds no behavior, no network call, no
schema, and no mutation path.

## 2. Authority and risk tier

- `docs/07_PLANNING.md` (committed at `ae403b8`), §1, §11, §12, §16–§19;
- `pricing/admin.py` — `ReadOnlyEvidenceAdmin` (TASK_019/TASK_022), the
  directly applicable in-repo convention this task reuses rather than
  reinvents;
- `pricing/tests/test_task_019_pricing_evidence.py` and
  `pricing/tests/test_task_022_operational_pricing.py` — the admin test style
  §19 names as precedent;
- TASK_030 (`9e60fac`) remains authoritative for `AlertDelivery` schema and
  lifecycle; TASK_031 (`8f61a1c`) for Telegram/config/payload/transport;
  TASK_032 (`3698d0f`, `d4022a3`) for send orchestration and the command.

**Risk tier: LOW**, per `docs/07_PLANNING.md` §17, and confirmed by inspection:

- the surface cannot mutate `AlertDelivery` — TASK_030's PostgreSQL lifecycle
  trigger rejects every `UPDATE` that is not `pending → sent|failed` and every
  `DELETE` outright, at the database layer, independently of admin permissions;
- it exposes no secret — the bot token and chat id live only in
  `django.conf.settings`, never on the model;
- it exposes no `RawListing`/`Source` evidence — `AlertDelivery` has no such
  field, and this task adds no related-object traversal that would reach one.

It would be HIGH only if it added a mutation, resend, or retry path. §12
forbids exactly that, so it does not.

Per §18, TASK_033's workflow is **IMPLEMENT → targeted validation → review diff
→ COMMIT**, with gates *"targeted admin-registration test; `manage.py check`
clean"*. §17 adds that TASK_033 *"must not inherit HIGH-tier ceremony because
its siblings are HIGH"*, and §19 that it *"does not justify a full suite"*.
This task deliberately has **no frozen acceptance-test module** and no
independent reviewer/validator agent.

## 3. Files

### IMPLEMENT files allowed

- `alerts/admin.py` (new)
- `tests/test_task_033_alert_admin_visibility.py` (new — targeted, not frozen)
- `tasks/TASK_033_ALERT_ADMIN_VISIBILITY.md` (this file)

Nothing else. Specifically **not** authorized: `alerts/models.py`,
`alerts/migrations/*`, `alerts/config.py`, `alerts/delivery.py`,
`alerts/telegram.py`, `alerts/orchestration.py`,
`alerts/management/commands/send_deal_alerts.py`, `config/settings.py`,
`.env.example`, `requirements.txt`, any existing model, any migration, any
frontend file, any previously frozen artifact, `CLAUDE.md`,
`docs/01_PLANNING.md`.

**No migration.** Admin registration is not a schema change;
`makemigrations --check --dry-run` must stay clean.

## 4. Admin contract

`alerts/admin.py` registers `AlertDelivery` using the same read-only shape
`pricing/admin.py` established. §15.1 classifies the exact list/readonly
configuration as an implementation detail resolved against repository
conventions, not an owner product decision, so the convention is followed
rather than re-litigated.

**Read-only, enforced four ways** (matching `ReadOnlyEvidenceAdmin`):

- `actions = None` — no bulk actions;
- `get_readonly_fields()` returns every concrete field;
- `has_add_permission()` → `False`;
- `has_change_permission()` → `False`;
- `has_delete_permission()` → `False`.

`has_view_permission()` is left at Django's default so a permitted staff user
can read the changelist — the entire point of the task.

**`list_display`** — the five persisted fields, in model declaration order, so
the changelist answers the §12 question directly:

```text
("deal_flag", "status", "claimed_at", "terminal_at", "failure_detail")
```

**`list_filter`** — `("status",)`. Status is the diagnostic axis: it is what
makes a stuck `pending` row findable among `sent` and `failed` ones (§11, §12).
The three-value vocabulary is fixed by TASK_030, so this filter cannot grow
unbounded.

**`ordering`** — `("-claimed_at", "pk")`, mirroring `DealFlagAdmin`'s
`("-flagged_at", "pk")`: most recent claim first, with the primary key as a
deterministic tie-break.

**`list_select_related`** — `("deal_flag",)`. `list_display` renders
`deal_flag`, which would otherwise issue one query per row. It deliberately
stops at `deal_flag` and does **not** traverse to `listing`, `sku`,
`raw_listing`, or `source`: Phase 7's privacy boundary keeps `RawListing`/
`Source` evidence out of the alert path entirely (§10 of TASK_031's contract,
and TASK_032's query-boundary rule), and nothing in the changelist needs them.

**No `search_fields`** — the changelist is small, bounded by the activation
cutoff, and `status` filtering plus recency ordering already answers the
diagnostic question. Adding search would invite a text query across
`failure_detail` for no stated need.

**No custom admin action, view, URL, or template.** §12: *"No admin action that
triggers or resends a send"* — that would be a second, less-auditable
invocation path alongside `send_deal_alerts`.

## 5. Targeted validation

Per §18. `tests/test_task_033_alert_admin_visibility.py` covers:

- `AlertDelivery` is registered in `admin.site`;
- the view-only permission contract: view `True`; add/change/delete `False`;
  `get_actions()` empty; every concrete field read-only — following
  `test_pricing_admin_contract_is_view_only`;
- the changelist configuration above;
- a real changelist render returns 200 and shows a `pending` row, so a stuck
  claim is genuinely visible — following
  `test_existing_pricing_evidence_is_viewable_in_admin`;
- the add and delete admin URLs are blocked;
- no resend/retry/send action or custom admin URL exists;
- the rendered changelist leaks no secret (bot token, chat id) and no
  `RawListing`/`Source` evidence;
- rendering the changelist invokes no alert service — no Telegram send, no
  orchestration run — following
  `test_admin_evidence_render_never_invokes_pricing_services`;
- TASK_030's schema and TASK_032's orchestration remain untouched.

Commands:

```text
docker compose exec web pytest -v tests/test_task_033_alert_admin_visibility.py
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations --check --dry-run
```

§19: a full-suite run is **not** justified by this task. It is run only if the
targeted gates surface something unexpected.

## 6. Explicit non-goals

No resend, retry, force, or claim deletion. No lifecycle mutation of any kind.
No custom admin action, view, URL, or template. No recipient/subscription
model. No secret or configuration display. No `RawListing`/`Source` exposure.
No frontend work. No change to `AlertDelivery`, its migration, TASK_031's
modules, TASK_032's orchestration or command, settings, or `.env.example`. No
new dependency.

## 7. Stop conditions

Stop and report rather than improvising if: admin registration appears to
require a schema or migration change; the read-only contract cannot be
expressed with the existing `ReadOnlyEvidenceAdmin` shape; or making a stuck
`pending` row visible appears to require exposing a secret or `RawListing`/
`Source` evidence.
