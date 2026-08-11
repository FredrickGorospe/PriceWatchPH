# TASK_032 — Alert send orchestration and the scheduler command

## 1. Goal

Combine the TASK_030 durable claim and the TASK_031 payload/transport into the
one operation Phase 7 exists to produce: select the DealFlags that should be
alerted, claim each one exactly once, send it, and record the terminal result —
with the claim committed *before* the network call and never held open across
it.

This is the first orchestration in the repository that touches eligibility,
database concurrency, transaction boundaries, and an irreversible external side
effect in the same code path. Every ordering rule in Section 6 is load-bearing.

TASK_032 owns orchestration only. It re-uses TASK_030 and TASK_031 exactly and
duplicates neither.

## 2. Authority and dependencies

- `CLAUDE.md`;
- `docs/07_PLANNING.md` (committed at `ae403b8`), owner-approved. Sections 4, 5,
  8, 11, and 13 bind this task directly;
- TASK_030 (`9e60fac`) — `AlertDelivery`, its four CheckConstraints, and the
  PostgreSQL lifecycle trigger. **Authoritative for every state transition.**
  TASK_032 changes no schema, no constraint, no trigger, and adds no migration;
- TASK_031 (`8f61a1c`) — `alerts/config.py`, `alerts/delivery.py`,
  `alerts/telegram.py`. **Authoritative for configuration validation, payload
  construction, the `AlertSender` seam, and transport sanitization.** TASK_032
  calls them and reimplements nothing;
- `pricing/management/commands/price_listings.py` — the repository's
  management-command precedent (summary line shape, `CommandError` usage).
  Its `.order_by("pk")` worklist is **not** inherited as a requirement here;
  see Section 5;
- `outcomes/outcome_services.py` — the `AuditWriter` callable-injection
  precedent this task follows for its sender seam;
- TASK_028/TASK_030 concurrency tests — the
  `@pytest.mark.django_db(transaction=True)` + `threading.Barrier` precedent.

### 2.1 Owner decisions settled for this task

Four operational semantics were explicitly settled by the owner during HARDEN
because `docs/07_PLANNING.md` left them open:

1. **Disabled alerts** print exactly `Alerts disabled: no deal flags were
   considered.` and exit 0 — a visible successful no-op, so a scheduled run
   leaves an operational trace instead of being indistinguishable from a cron
   entry that never fired.
2. **The completion summary** is exactly
   `Alerts complete: candidates=N sent=N failed=N`.
3. **Configuration failure** raises `CommandError` (normal Django non-zero
   exit), before any claim exists.
4. **Unexpected exceptions propagate unchanged.** No broad catch. Only
   TASK_031's sanitized `AlertDeliveryError` becomes `failed`.

## 3. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_032_ALERT_SEND_ORCHESTRATION_AND_COMMAND.md`
- `tests/test_task_032_alert_send_orchestration_and_command.py`

### IMPLEMENT files allowed — after owner approval

- `alerts/orchestration.py` (new) — eligibility, claiming, transitions, summary
- `alerts/management/__init__.py` (new)
- `alerts/management/commands/__init__.py` (new)
- `alerts/management/commands/send_deal_alerts.py` (new)

Nothing else. Specifically **not** authorized: `alerts/models.py`,
`alerts/migrations/*`, `alerts/config.py`, `alerts/delivery.py`,
`alerts/telegram.py`, `alerts/admin.py` (TASK_033), `config/settings.py`,
`.env.example`, `requirements.txt`, any existing model, any migration, any
frontend file, any previously frozen artifact.

**No migration is expected.** If implementation appears to need a schema change,
that is a contradiction — stop and report rather than adding one.

## 4. Public contract

```python
# alerts/orchestration.py

@dataclass(frozen=True, slots=True)
class AlertRunSummary:
    candidates: int
    sent: int
    failed: int

def send_pending_deal_alerts(*, sender: AlertSender | None = None) -> AlertRunSummary: ...
```

`sender` defaults to TASK_031's `send_telegram_message`, bound at module level
in `alerts/orchestration.py` so it is patchable as
`alerts.orchestration.send_telegram_message` — the same frozen-seam technique
TASK_031 uses for `alerts.telegram.urlopen`, and the same
inject-a-callable-with-a-real-default shape as `outcome_services`'
`audit_writer`. No registry, no factory, no service locator.

`alerts/orchestration.py` likewise binds TASK_031's `build_alert_message` at
module level, so it is patchable as
`alerts.orchestration.build_alert_message`. This is a frozen testability seam
for the same reason `alerts.telegram.urlopen` is one: it lets an acceptance
test make payload construction fail for one specific candidate and observe
which candidates were attempted, which is the only way to prove the run
continues past an `AlertPayloadError` **without** assuming a processing order
that Section 5 deliberately does not freeze.

The claim insert goes through the ordinary model save path
(`AlertDelivery.objects.create(...)`), never `bulk_create` — per-candidate
claim-commit-send cannot be batched, and the concurrency test synchronises on
that save path.

`send_pending_deal_alerts()` is what the management command orchestrates; the
command owns only argument handling, the summary line, and the exit status.

## 5. Eligibility

A DealFlag is a candidate when **both** hold (`docs/07_PLANNING.md` §4, §5):

1. **no `AlertDelivery` row exists for it at all** — `pending`, `sent`, and
   `failed` all exclude it permanently; and
2. **`DealFlag.flagged_at >= activation_at`**, where `activation_at` is the
   UTC-normalized instant TASK_031's `load_alert_config()` already produced.

The boundary is **inclusive**: a DealFlag flagged at exactly the activation
instant *is* a candidate.

**Ordering: deliberately not frozen.** `docs/07_PLANNING.md` requires no
DealFlag processing order — every "order/ordering" statement in the committed
plan refers to the claim/commit/send *step* sequence (§7.3, "Claim ordering -
the correctness core") or to the "deterministic payload", never to the sequence
in which candidates are processed.

An earlier draft of this specification froze `.order_by("pk")` by inference from
the `price_listings` worklist precedent. Repository precedent may guide the
implementation's choice, but it is not authority to expand TASK_032's frozen
contract, so the requirement is withdrawn and is **not** replaced by a different
invented rule. Implementation may order candidates however it finds
appropriate; no acceptance test asserts a processing order, and every
multi-candidate test below is written to hold under any order.

**No per-run cap** (Decision D). Every candidate is processed.

**Query privacy:** the eligibility query and payload construction must never
touch `ingestion_rawlisting` or `sources_source`. Verified during HARDEN that
`DealFlag.objects.filter(alert_delivery__isnull=True, flagged_at__gte=…)`
joins only `pricing_dealflag` and `alerts_alertdelivery`. Any `select_related`
added for efficiency may cover `listing` and `listing__sku` only.

## 6. Ordering — the correctness core

```text
1. alerts_enabled()?           no  -> print the disabled line, exit 0, stop.
2. load_alert_config()             -> CommandError on failure. No claim exists yet.
3. select candidates               -> eligibility query (Section 5)
   for each selected candidate:    -> processing order unspecified (Section 5)
4.   build_alert_message()         -> AlertPayloadError skips this candidate
                                      without claiming it
5.   create the pending claim inside a short transaction
6.   COMMIT that transaction       -> before any network I/O
7.   call the sender               -> outside every transaction
8.   sender returned               -> pending -> sent
9.   AlertDeliveryError            -> pending -> failed, failure_detail = str(error)
```

Rules that fall out of this, each independently frozen by a test:

- **Steps 1–2 precede any claim.** A disabled run performs no eligibility query,
  creates no claim, and calls no sender. A configuration failure raises before
  any claim exists.
- **Step 4 precedes step 5.** A payload defect must not consume a DealFlag's one
  and only claim — TASK_030 forbids retry and resend, so a claim burned on an
  unsendable message is unrecoverable.
- **Step 6 precedes step 7, and no transaction is open during step 7.** The
  claim must be durably committed before Telegram can receive anything,
  otherwise two workers could both send. It must *not* remain open across the
  send, because holding a transaction across a 10-second external call creates
  contention without improving the guarantee.
- **Steps 8–9 are the only writes after the send**, and they use exactly the
  transition TASK_030's trigger permits: `status` and `terminal_at` (plus
  `failure_detail` when failing), never `deal_flag_id` or `claimed_at`.

## 7. Concurrency

Two concurrent workers that both observe the same DealFlag as eligible must
produce **exactly one `AlertDelivery` row and at most one sender invocation.**

A pre-check such as `if not AlertDelivery.objects.filter(...).exists(): create(...)`
is race-prone and insufficient: both workers can pass it before either inserts.
The authoritative conflict boundary is TASK_030's database uniqueness
(`OneToOneField` → `UNIQUE`). The claim insert must therefore be attempted and
its `IntegrityError` caught inside a savepoint-safe `transaction.atomic()`
block, exactly as TASK_028's
`test_concurrent_creation_race_yields_one_outcome_and_a_stable_conflict`
established — a bare `IntegrityError` catch leaves the surrounding transaction
unusable.

**The frozen test forces the race rather than hoping for it.** Synchronising the
two workers only before the run would let one finish its claim before the other
even selects candidates, so the conflict path might never execute and the test
would pass vacuously. The acceptance test therefore places a `threading.Barrier`
on the *actual insert path* — monkeypatching `AlertDelivery.save` to wait when
`self._state.adding` is true — following TASK_021's
`test_concurrent_qualification_converges_through_database_uniqueness`
precedent. Both workers are held at the insert boundary until both arrive, which
guarantees both selected the DealFlag as a candidate before either insert
completed. This is a test-only monkeypatch; no production testing hook exists.

**The loser skips the DealFlag and does not send.** It counts as a `candidate`
(it was selected before per-candidate processing) but as neither `sent` nor
`failed`, so a lost race never makes the command exit non-zero — losing a race
is normal operation, not a delivery failure.

No advisory locks, no Redis, no Celery, no queue, no global process lock.

## 8. Terminal transitions

On sender success: `status="sent"`, `terminal_at=<now>`, `failure_detail`
remains `NULL`.

On `AlertDeliveryError`: `status="failed"`, `terminal_at=<now>`,
`failure_detail=str(error)` — one of TASK_031's four frozen sanitized messages,
all non-empty, which satisfies TASK_030's
`alertdelivery_failure_detail_matches_status` constraint.

Both satisfy TASK_030's `alertdelivery_terminal_at_not_before_claimed_at`,
which is `terminal_at IS NULL OR terminal_at >= claimed_at`. **Equality is
valid** — TASK_030's own frozen
`test_terminal_at_equal_to_claimed_at_is_valid` pins that a claim and its
terminal record may land within the same clock tick. TASK_032 introduces no
stricter `>` requirement, and its assertions use `claimed_at <= terminal_at`
accordingly.

TASK_030 already freezes the trigger and constraint behavior; TASK_032's tests
prove the orchestration *uses* them correctly rather than re-proving them.

## 9. Unexpected exceptions

**Propagate unchanged. No broad catch.** Only `AlertDeliveryError` — TASK_031's
sanitized contract — becomes `failed`.

A raw Telegram, `urllib`, parser, database, or programming error is never
converted into persisted `failure_detail`. TASK_031 already converts every
transport and parsing condition it owns into `AlertDeliveryError`; anything that
escapes that contract is a genuine defect and must surface, not be recorded as
an ordinary delivery failure.

**Accepted consequence:** an unexpected exception after the claim commits leaves
that row `pending` permanently in v1. `docs/07_PLANNING.md` §11 already treats a
stuck `pending` row as the expected, diagnosable signature of a crash between
claim and terminal record. TASK_032 must not repair it through retries, resend,
broad exception conversion, or claim deletion.

## 10. The management command

`alerts/management/commands/send_deal_alerts.py`, invoked as
`python manage.py send_deal_alerts`. No arguments in v1 — no `--force`, no
`--limit`, no `--dry-run`.

**Disabled:** writes exactly

```text
Alerts disabled: no deal flags were considered.
```

to stdout and exits 0. No eligibility query, no claim, no sender call.

**Configuration failure:** `load_alert_config()`'s `AlertConfigurationError`
becomes a `CommandError` (normal Django non-zero exit, message on stderr),
raised before any claim exists. No separate stderr mechanism is invented.

**Completion:** writes exactly

```text
Alerts complete: candidates=N sent=N failed=N
```

where `candidates` is the number of eligible DealFlags selected for the run
before per-candidate processing, `sent` is the number of claims transitioned to
`sent`, and `failed` is the number transitioned to `failed` because the sender
raised `AlertDeliveryError`.

**Exit status:** 0 when `failed == 0`; non-zero when `failed > 0`. The summary
is written **first**, then the command raises `CommandError` with exactly:

```text
Alert delivery completed with failures.
```

so an operator always sees the counts, and cron sees a non-zero status
(`docs/07_PLANNING.md` §8). `CommandError` is the mechanism because it is this
repository's universal convention — no command writes to `stderr` directly —
and because owner Decision 3 endorses "normal Django `CommandError` behavior"
for the configuration case.

One failing candidate must not abort the remaining ones (§8).

## 11. Privacy

Neither command output nor persisted `failure_detail` may contain the bot
token, the Telegram destination, any Telegram URL, raw `urllib`/parser text,
Telegram's `description`, or any `RawListing`/`Source` evidence — no raw title,
no seller, no source URL. TASK_031 owns transport sanitization; TASK_032 must
not undo it by adding "helpful" diagnostics.

## 12. Acceptance criteria — frozen

The authoritative artifact is
`tests/test_task_032_alert_send_orchestration_and_command.py`. It freezes, at
minimum:

**Disabled** — exact line, exit 0, no eligibility query, no claim, no sender.

**Configuration** — `CommandError` before any claim; no claim row; no sender.

**Eligibility** — inclusive `>=` boundary pinned on both sides; flags before the
cutoff excluded; existing `pending`/`sent`/`failed` rows each exclude
permanently; every candidate processed exactly once under any order; no per-run
cap; the query touches neither `ingestion_rawlisting` nor `sources_source`.

**Payload preflight** — `AlertPayloadError` leaves the DealFlag unclaimed and
calls no sender, and the run continues.

**Happy path** — one claim, sender called once with the exact `AlertConfig` and
the exact TASK_031 message, `pending → sent`, `terminal_at` set,
`failure_detail` null.

**Transaction boundary** — at sender-invocation time the claim is already
visible from a *separate database connection* as `pending`, and the
orchestrator's own connection is not inside an atomic block.

**Concurrency** — two racing workers yield exactly one row and exactly one
sender call; the loser skips without sending and without counting a failure.

**Sender failure** — `pending → failed`, `terminal_at` set, `failure_detail` is
exactly the sanitized message, sender called once, no retry, and a later run
skips the DealFlag.

**Unexpected exception** — propagates unchanged; the row stays `pending` with
`terminal_at` and `failure_detail` null; nothing is converted.

**Command surface** — exact summary strings; exit 0 with no failures; non-zero
via `CommandError` when any failed; processing continues past a failure.

**Privacy** — no token, destination, URL, raw transport text, or RawListing
evidence in stdout, stderr, or `failure_detail`.

**Compatibility** — TASK_030's schema/constraints unchanged; TASK_031's modules
unmodified; no migration.

No test performs a real Telegram request; the sender is always injected.

## 13. Explicit non-goals

No retry, resend, `--force`, `--limit`, `--dry-run`, attempt history, cooldown,
or claim deletion. No admin (TASK_033). No second channel, recipient model, or
subscription. No advisory locks, Redis, Celery, or queue. No new dependency. No
change to `AlertDelivery`, its migration, TASK_031's modules, settings,
`.env.example`, any existing model, or any frontend file. No RawListing/Source
access anywhere in the alert path.

## 14. Validation

HARDEN baseline (implementation absent — failures expected):

```text
docker compose exec web pytest -v tests/test_task_032_alert_send_orchestration_and_command.py
```

After implementation:

```text
docker compose exec web pytest -v tests/test_task_032_alert_send_orchestration_and_command.py
docker compose exec web pytest -v
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py check
```

A full backend run is justified: TASK_032 adds a new app subpackage
(`alerts/management/`) and a command that Django's registry loads for every
test, and its eligibility query joins `pricing_dealflag`. No frontend
validation applies.

## 15. Stop conditions

Implementation stops and reports rather than improvising if: the claim/commit/
send ordering cannot be achieved without altering TASK_030 or TASK_031; the
concurrency guarantee cannot be proven without a schema change; a migration
appears necessary; TASK_031's `AlertSender` signature proves insufficient; or
any frozen behavior in Section 12 requires changing a previously frozen
artifact.

No implementation begins until this specification and its frozen acceptance
module receive explicit owner approval.
