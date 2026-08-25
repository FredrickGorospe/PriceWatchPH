# TASK_037 — PostgreSQL backup and verified restore

## 1. Goal

Give PriceWatch PH a PostgreSQL-native backup mechanism and — the substance of
the task — a **restore that is actually performed and verified** into an
isolated scratch target, proving the restored database is still usable with the
independently recovered original `SELLER_PSEUDONYM_KEY`.

A backup believed good but never restored is worse than none, because it
removes urgency (`docs/09_PLANNING.md` §9, TASK_037).

## 2. Authority and dependencies

- `CLAUDE.md` — Postgres 16 only, money always Decimal, environment-only
  secrets, `RawListing` immutable after write;
- `docs/09_PLANNING.md` (owner-approved) — §3.7 (the recovery set), §6 risk 4,
  §8.3 (destination/retention are owner decisions), §9 TASK_037, §11 item 7;
- TASK_034 (`d780fe9`) — the runtime and Compose shape this task extends;
- TASK_001's frozen `.env.example` ↔ `config/settings.py` symmetry test
  (`tests/test_task_001_bootstrap.py`) — a hard constraint on new variables,
  see §6.3;
- inspected at `d780fe9`: `docker-compose.yml`, `Dockerfile`,
  `docker-entrypoint.sh`, `config/settings.py`, `ingestion/pseudonymise.py`,
  `ingestion/admin.py` (TASK_007 write path), `ingestion/models.py`,
  `ingestion/migrations/0002_rawlisting_immutability_trigger.py`,
  `pricing/migrations/0002_auditable_pricing_evidence.py`,
  `alerts/migrations/0001_initial.py`, `ingestion/demo_data.py`.

At its original checkpoint, TASK_037 was **independent of TASK_035 (Caddy)
and TASK_036 (scheduler)** and referenced neither task's then-unmerged changes.
The successor amendments in §14 preserve that history while delegating later
cross-task ownership explicitly.

### 2.1 Post-incident contract correction

The first real TASK_037 drill exposed two unsafe assumptions in the original
frozen contract. Inactive-profile backup interpolation failed while Compose was
loading the model, and the subsequent project-wide cleanup removed the active
`pricewatchph` resources, including `pricewatchph_postgres_data`. The exact
historical reason an explicit drill project apparently resolved to active
resources remains **UNKNOWN** and is not reconstructed here.

This amendment replaces the disproven mechanisms with stronger invariants. All
profile-only interpolation is inactive-safe, with required backup connection
values checked by `pg_backup.sh` at execution time. Destructive cleanup never
uses Compose project teardown: it re-proves exact scratch ownership immediately
before deletion and may remove only the exact verified scratch container,
default network, and dedicated scratch volume. Failed proof preserves resources.
This is not a relaxation of the product requirement. Cleanup may destroy only
disposable drill resources and must never address an active application resource.

### 2.2 Post-incident drill backup-runner isolation amendment

A later controlled drill proved a second Compose boundary fact. Direct
disposable Django runners migrated and populated the source scratch database
without changing drill-resource ownership. The subsequent invocation of the
repository's full Compose `backup` service under the drill project materialised
an unrelated `task037-drill-*_postgres_data` volume. The immediate ownership
proof detected two project volumes instead of the single dedicated
`task037_scratch_data` volume and failed closed. The active `pricewatchph`
database, TASK_036 resources, and frontend-redesign resources survived, and no
broad cleanup was attempted.

This runtime evidence proves that the production Compose backup service and the
mandatory isolated restore drill require distinct invocation boundaries. The
production operator interface remains the real profile-gated Compose `backup`
service. The drill instead runs the exact same real `pg_backup.sh` and PostgreSQL
tooling through the isolated disposable backup runner frozen in §11.1.1. The
one-scratch-volume invariant is not weakened.

## 3. Verified facts — established by inspection and live PostgreSQL 16 experiment

Everything in this section was reproduced during HARDEN against
`postgres:16.14-bookworm` in **disposable scratch containers with synthetic
data**. No backup of any real PriceWatch PH database was taken.

### 3.1 The schema carries four PL/pgSQL triggers that a restore must preserve

Created by `migrations.RunSQL`, not by Django constraints, so they are database
objects whose survival is a real restore question:

| Table | Trigger | Fires |
|---|---|---|
| `ingestion_rawlisting` | `rawlisting_immutable` | BEFORE UPDATE OR DELETE |
| `pricing_pricepoint` | `pricing_pricepoint_task019_immutable` | BEFORE UPDATE OR DELETE |
| `pricing_dealflag` | `pricing_dealflag_task019_immutable` | BEFORE UPDATE OR DELETE |
| `alerts_alertdelivery` | `alerts_alertdelivery_task030_lifecycle_guard` | **BEFORE INSERT** OR UPDATE OR DELETE |

### 3.2 The AlertDelivery guard would break a naive restore — and does not, for a verifiable reason

`alerts_alertdelivery_task030_lifecycle_guard` raises on any INSERT whose
status is not `pending`. Confirmed live:

```
INSERT INTO alerts_alertdelivery (status, ...) VALUES ('sent', ...);
ERROR:  AlertDelivery must be created pending, not: sent
```

Any legitimately `sent`/`failed` row therefore **cannot be re-inserted while
that trigger exists**. The reason a restore nonetheless succeeds is
`pg_dump`'s section model, which was verified rather than assumed:

```
$ pg_dump -Fc … && pg_restore --list dump
…  TABLE public alerts_alertdelivery
…  TABLE DATA public alerts_alertdelivery          <-- data first
…  CONSTRAINT public … _pkey
…  TRIGGER public alerts_alertdelivery … guard     <-- trigger last

$ pg_dump --section=pre-data  | grep -c 'CREATE TRIGGER'   ->  0
$ pg_dump --section=data      | grep -c 'CREATE TRIGGER'   ->  0
$ pg_dump --section=post-data | grep -c 'CREATE TRIGGER'   ->  1
```

And end-to-end into a second scratch database:

```
pg_restore: processing data for table "public.alerts_alertdelivery"
pg_restore: creating TRIGGER "public.alerts_alertdelivery … guard"
restore exit = 0 ;  restored row = (1, 'sent')
```

Triggers live in **post-data**, created *after* `TABLE DATA`. Data therefore
loads while no trigger exists, and the guard is (re)armed afterwards —
confirmed active in the restored database, which again rejects a fresh
terminal-status INSERT.

**Consequence:** no `--disable-triggers` is needed (it would require superuser
and is not used), and no `--data-only` restore may ever be adopted — a
data-only restore into a pre-existing schema *would* hit the armed guard and
fail. This is a frozen constraint, not a preference.

### 3.3 `pg_dump -f` silently destroys an existing artifact

```
$ echo 'PRECIOUS-LAST-KNOWN-GOOD' > existing.dump
$ pg_dump … -Fc -f existing.dump   ->  exit 0, file overwritten
```
A backup mechanism that simply passes `-f` at a computed path can therefore
destroy the last known-good dump on a name collision. §6.2 refuses instead.

### 3.4 Default dump permissions are world-readable

```
$ pg_dump … -Fc -f perm.dump    ->  -rw-r--r--   (0644)
$ ( umask 077; pg_dump … )      ->  -rw-------   (0600)
```
The dump contains every pseudonym token, price, and personal record in the
database, so 0644 is a real defect. `umask 077` is frozen (§10).

### 3.5 A truncated custom-format dump is structurally detectable

```
$ head -c 400 good.dump > truncated.dump
$ pg_restore --list truncated.dump
pg_restore: error: could not read from input file: end of file   (exit 1)
```
This is a decisive, non-folkloric advantage of the custom format over plain
SQL: incompleteness is detectable from the artifact's own structure, before any
checksum and before any destructive action. Plain SQL truncation is not.

### 3.6 Client/server versions match exactly in the project's own image

```
$ docker run --rm postgres:16.14-bookworm sh -c 'pg_dump --version; postgres --version'
pg_dump (PostgreSQL) 16.14 (Debian 16.14-1.pgdg12+1)
postgres (PostgreSQL) 16.14 (Debian 16.14-1.pgdg12+1)
```
The application image (`python:3.12.13-slim-bookworm` + `psycopg[binary]`) has
**no** `pg_dump`/`pg_restore` binary — `psycopg` is a driver, not the client
tools. Installing them there would introduce a second, independently-drifting
PostgreSQL client. §5 uses the `db` service's own image instead.

### 3.7 Compose profiles genuinely exclude a service from `docker compose up`

Verified on the installed engine (`docker compose version` → `5.3.1`):

```
services:  always_on ;  backup (profiles: ["backup"])
$ docker compose config --services                  ->  always_on
$ docker compose --profile backup config --services ->  always_on, backup
```
This is the mechanism that keeps the backup and restore-scratch services from
ever starting during ordinary operation (§7.4).

Profiles gate **service activation, not YAML interpolation**. Compose resolves
variables for inactive profile services while parsing the project. Therefore
neither profile-gated service may require its activation-only values during
ordinary model loading. The scratch password and the backup service's
`PGDATABASE`, `PGUSER`, and `PGPASSWORD` use optional empty interpolation
defaults. `pg_restore_verify.sh` supplies a non-empty random scratch password
when it activates the drill. `pg_backup.sh` independently rejects every missing
or empty required PG connection variable before artifact creation or `pg_dump`.
PostgreSQL trust authentication is still forbidden.

### 3.8 Pseudonymisation is one-way, deterministic, and keyed

`ingestion/pseudonymise.py`:

```python
def pseudonymise(value: str) -> str:
    key = settings.SELLER_PSEUDONYM_KEY.encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()
```

- **HMAC-SHA256 — irreversible.** A stored pseudonym can never be turned back
  into a counterparty name. TASK_037 claims no reversibility anywhere.
- **Deterministic** — the same key and input always yield the same token. This
  is the *only* property that makes any key-continuity verification possible
  (§9).
- **Keyed and unrotatable** — `config/settings.py` records it as
  *"Backup-critical for the life of the database"*; tokens live in immutable
  `RawListing` rows.
- **Plaintext is never stored.** TASK_007's `_write_personal_trade` computes
  `seller = pseudonymise(counterparty)` and writes only the token;
  `redact_payload` replaces `payload["seller"]` with the identical token.
- **The key is nowhere in the database.** No model field holds it, so it is
  categorically absent from any `pg_dump` output.

### 3.9 Demo data provides no continuity fixture

`bootstrap_demo_data` writes `seller=""` (empty string, never pseudonymised)
and `ingestion/demo_data.py` contains no counterparty value at all. The
pseudonym-continuity check therefore **cannot** be built on demo data; the
drill must create its own deterministic fixture through the real
`pseudonymise()` code path (§9.2).

### 3.10 Other schema facts relevant to restore fidelity

- 20 public tables; no PostgreSQL extension is created by any migration.
- Money is `numeric(12,2)` (`ingestion_rawlisting.raw_price`,
  `listings_listing.price`, `outcomes_outcome.*`, `catalogue_sku.launch_msrp`,
  `ingestion_swap.cash_adjustment`), with `numeric(14,4)`/`numeric(18,4)` for
  pricing statistics and `numeric(5,4)` for resolution confidence — exact
  scale is part of what a restore must preserve, per `CLAUDE.md`'s
  Decimal-only rule.
- `python manage.py migrate --check` exits 0 against a fully-migrated database
  and applies nothing — a read-only migration-consistency probe suitable for
  post-restore verification (§8).

## 4. Backup format — settled: `pg_dump` custom format (`-Fc`), single file

| Criterion | custom (`-Fc`) | plain SQL | directory (`-Fd`) |
|---|---|---|---|
| Incompleteness detectable from the artifact | **Yes** (§3.5) | No | Yes |
| Compression built in | **Yes** | No | Yes |
| Restore tool | `pg_restore` (selective, `--exit-on-error`) | `psql` | `pg_restore` |
| Ownership remap for scratch restore | **`--no-owner`** | manual editing | `--no-owner` |
| Single dump file to pair with one checksum | **Yes** | Yes | No (a directory) |
| Parallel dump/restore | no | no | yes (`-j`) |

**Custom format is chosen.** It is the only option that combines structural
self-validation (§3.5), built-in compression, `pg_restore`'s ownership
remapping for a scratch target, and a *single* dump file, which keeps the
publication protocol in §6.2 to one dump plus one checksum sidecar.
Directory format's only real advantage is parallelism, which this
single-host, modest-sized database does not need and which would complicate
publication across many files. Plain SQL's only advantage is human readability,
paid for by losing the incompleteness detection that matters most here.

**Explicitly forbidden as the primary mechanism:** copying
`/var/lib/postgresql/data`, or copying/snapshotting the `postgres_data` Docker
volume. A file-level copy of a *running* cluster is not a
database-consistent backup, and a volume copy is not a logical backup — it
cannot be restored into a differently-versioned or differently-named cluster
and cannot be partially inspected. These are not equivalent to a logical dump
and must not be presented as one.

## 5. PostgreSQL tooling and version strategy — settled

The production backup service, the isolated drill backup runner, and scratch
restore run `pg_dump`/`pg_restore` from **`postgres:16.14-bookworm` — the exact
image tag the `db` service uses**. Client and server versions are therefore
identical by construction (§3.6), matching the repository's existing "resolved
patch tag, never a floating tag" convention.

- No PostgreSQL client is added to the application image (§3.6). The
  `Dockerfile` is **not** modified.
- No new Python package is added; `requirements.txt` is **not** modified.
- If `db`'s image tag is ever bumped, the production backup service,
  `restore_scratch`, and the drill backup runner's tooling identity must move in
  the same change. Tests freeze the service-tag equality and the runner's exact
  derivation from that PostgreSQL image contract.

## 6. Production backup execution architecture — settled

### 6.1 Production mechanism: one profile-gated, one-shot Compose service

A `backup` service (`profiles: ["backup"]`, `restart: "no"`) running a fixed
script. No permanent backup daemon: nothing in Phase 9 requires a
long-running process, and a daemon would add an unsupervised writer to the
database for no benefit. Unattended invocation is a host-scheduler/TASK_038
concern (§13).

This service is the operator-facing production backup mechanism and remains
invoked as `docker compose --profile backup run --rm backup` (§13). The
mandatory restore drill must not invoke this service through its drill Compose
project; §11.1.1 freezes the isolated runner that executes the same real
`pg_backup.sh` without loading the full Compose model as a runnable project.

```yaml
  backup:
    image: postgres:16.14-bookworm
    profiles: ["backup"]
    depends_on:
      db:
        condition: service_healthy
    restart: "no"
    environment:
      PGHOST: db
      PGPORT: "5432"
      PGDATABASE: ${POSTGRES_DB:-}
      PGUSER: ${POSTGRES_USER:-}
      PGPASSWORD: ${POSTGRES_PASSWORD:-}
    volumes:
      - ./pg_backup.sh:/usr/local/bin/pg_backup.sh:ro
      - ${PRICEWATCHPH_BACKUP_DIR:-./backups}:/backups
    command: ["/usr/local/bin/pg_backup.sh"]
```

Deliberate details:

- **No `env_file: - .env`.** Least privilege: the backup container receives
  only the five `PG*` connection variables and therefore never sees
  `DJANGO_SELLER_PSEUDONYM_KEY` or `DJANGO_SECRET_KEY`. This is the single
  most important structural property of the backup service, and it is frozen.
- **`PGPASSWORD` as an environment variable, never a command-line argument**,
  so the password cannot appear in `ps` output.
- **Inactive-safe interpolation.** `PGDATABASE`, `PGUSER`, and `PGPASSWORD` may
  resolve empty while the backup profile is inactive, so ordinary Compose model
  loading never requires backup credentials. When the service actually runs,
  `pg_backup.sh` must reject missing or empty `PGHOST`, `PGPORT`, `PGDATABASE`,
  `PGUSER`, or `PGPASSWORD` before creating an artifact or invoking `pg_dump`.
  The failure is nonzero, names only the missing variable, and never prints a
  secret value.
- **The script is mounted read-only and invoked by fixed path.** `command` is
  an exec-form array. No environment variable is ever interpolated into a
  shell command, so there is no arbitrary-command-execution seam.

### 6.2 `pg_backup.sh` — required semantics

Repository root, beside the existing `docker-entrypoint.sh` (the established
convention; no new directory is invented).

```sh
#!/bin/sh
set -eu
for REQUIRED_PG_VAR in PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD; do
    if [ -z "$(printenv "$REQUIRED_PG_VAR")" ]; then
        printf '%s must be set and non-empty\n' "$REQUIRED_PG_VAR" >&2
        exit 2
    fi
done
umask 077                                   # §3.4: 0600, not 0644
ARTIFACT="pricewatchph-$(date -u +%Y%m%dT%H%M%SZ).dump"
DUMP_TMP="/backups/.${ARTIFACT}.partial"
DIGEST_TMP="/backups/.${ARTIFACT}.sha256.partial"
FINAL="/backups/${ARTIFACT}"
CHECKSUM="${FINAL}.sha256"
[ ! -e "$FINAL" ] && [ ! -e "$CHECKSUM" ] || exit 3
pg_dump -Fc -f "$DUMP_TMP"
pg_restore --list "$DUMP_TMP" >/dev/null
DIGEST="$(sha256sum "$DUMP_TMP" | cut -d ' ' -f 1)"
printf '%s  %s\n' "$DIGEST" "$ARTIFACT" > "$DIGEST_TMP"
mv "$DUMP_TMP" "$FINAL"
mv "$DIGEST_TMP" "$CHECKSUM"
(cd /backups && sha256sum -c "${ARTIFACT}.sha256")
printf 'BACKUP_ARTIFACT=%s\n' "$ARTIFACT"
```

The sample fixes semantics, not a byte-for-byte implementation. The required
execution and publication protocol is:

1. **Validate all five required PG variables first.** Missing and empty values
   fail nonzero before artifact creation or `pg_dump`, without printing values.
2. **`umask 077` before artifact creation**, so neither the dump nor the
   checksum is ever world-readable, even transiently.
3. **Refuse if either final path exists**. Exit `3` before dumping; never
   replace either member of an existing pair.
4. **Create both members under dot-prefixed `.partial` names**. Validate the
   dump with `pg_restore --list`, calculate its SHA-256, and write a strict
   one-line sidecar naming the final dump basename.
5. **Publish by two renames**: dump first, checksum second. Each same-filesystem
   rename is atomic, but the two-file pair is not atomic as a unit and must
   never be described that way.
6. **Re-verify the final pair**, then emit exactly one machine-readable success
   record, `BACKUP_ARTIFACT=<basename>`, and exit 0. The success record is
   emitted only after both final regular files exist, the checksum names that
   exact basename and verifies, and `pg_restore --list` succeeds.

Failure behavior is deliberately honest. Any failure exits nonzero and may
leave `.partial` files, an orphan final dump, or an invalid/incomplete final
pair depending on which filesystem operation failed. No cleanup or rollback is
claimed. Such files are diagnostic remnants, not successful backups. The
restore drill accepts only a complete, strict, verified `.dump` +
`.dump.sha256` pair and rejects every orphan, `.partial`, malformed sidecar,
checksum mismatch, or structurally invalid dump.

The final `BACKUP_ARTIFACT=` line is also the hand-off between backup and drill.
`pg_restore_verify.sh` captures exactly that line from the backup invocation,
requires exactly one match, validates the basename against
`^pricewatchph-[0-9]{8}T[0-9]{6}Z\.dump$`, and uses only that exact pair. It
must not select by mtime, `ls -t`, `find`, wildcard expansion, or a concept of
"latest".

### 6.3 No new `.env.example` key — a hard TASK_001 constraint

TASK_001's frozen symmetry test asserts **both** directions: every
`os.environ` key read in `config/settings.py` appears in `.env.example`, *and*
every `.env.example` key is read by `config/settings.py`.
`PRICEWATCHPH_BACKUP_DIR`, `PRICEWATCHPH_RESTORE_SCRATCH_PASSWORD`, and
`PRICEWATCHPH_APP_ENV_FILE` are consumed by **Compose interpolation**, never by
`config/settings.py`. Adding any of them to `.env.example` would therefore
**break** a frozen test.

They are consequently documented here and in §17 only, and must **not** be
added to `.env.example`. `config/settings.py` is not modified by this task —
Django reads nothing new. A frozen test asserts `.env.example` is unchanged.

## 7. Destination abstraction — settled, with an honest boundary

### 7.1 A host bind mount, defaulting to `./backups`

`${PRICEWATCHPH_BACKUP_DIR:-./backups}:/backups`. The container always writes
to the fixed path `/backups`; where that lands on the host is the one
configurable knob. No provider is invented — **no S3, Backblaze, Google Drive,
Dropbox, rsync host, or paid vendor appears anywhere in this task**, because
`docs/09_PLANNING.md` §8.3 leaves the destination an open owner decision.

### 7.2 Why not a named Docker volume

A named volume would satisfy "not ephemeral container-only storage", but it is
worse here on the property that matters: an operator cannot readily copy it
off-host, inspect it, or hand it to a provider agent without another container.
A host directory is directly visible to whatever off-host mechanism the owner
later chooses, which is exactly the seam this task must leave open.

### 7.3 What same-host storage does and does not protect against — stated plainly

Three distinct things, deliberately not conflated:

1. **Backup creation** — TASK_037's scope. A consistent, verified, restorable
   logical dump exists on the host.
2. **Durable off-host storage** — **not implemented by TASK_037.** A dump in
   `./backups` on the application host protects against database corruption, a
   bad migration, an accidental deletion, and a dropped table. It does **not**
   protect against loss of the host, loss of its disk, or a
   host-wide compromise, because the only copy lives on the machine at risk.
3. **Full disaster-recovery readiness** — **not claimed.** That additionally
   requires an off-host destination, its own credentials, tested restore on
   replacement hardware, and a documented RPO/RTO, none of which exist yet.

TASK_037 therefore delivers a *verified backup and restore mechanism*, not
disaster-recovery readiness, and the specification must not be read as
claiming otherwise. Closing item 2 is the owner's destination decision (§19).

### 7.4 Artifacts must never be committed

`.gitignore` gains `/backups/`, `*.dump`, and `*.dump.sha256`. It currently has
no dump/backup pattern at all, so without this a dump written to the default
`./backups` inside the working tree could be committed — directly violating
`docs/09_PLANNING.md` §9's "confirmation that no dump or key is committed".

## 8. Retention — settled: deliberately deferred, no deletion implemented

TASK_037 implements **no automatic deletion**. No `rm`, no `find -delete`, no
pruning of `/backups` appears in either script.

- `docs/09_PLANNING.md` §8.3 records retention as an open owner decision; a
  duration invented here (7 days, 30 days) would be exactly the fabrication
  this task must avoid.
- Deletion is destructive and irreversible, and a backup component is the
  worst possible place to debut an unproven `rm` against a directory holding
  the only copies of the database.
- Nothing in Phase 9's completion criteria requires pruning; criterion 7
  requires a *performed and verified restore*.
- The refuse-if-exists rule (§6.2) means the backup mechanism never destroys
  an existing artifact either, so unbounded growth is the only failure mode —
  visible, non-destructive, and an operator's to resolve.

Frozen as a test: neither script contains a deletion of anything under the
backup directory. Retention is a NON-BLOCKING deployment decision (§19), to be
implemented by the destination/provider or a TASK_038 operator procedure.

## 9. `SELLER_PSEUDONYM_KEY` — recovery contract and honest verification

### 9.1 Invariants

1. **The key is not in the dump.** It lives only in the environment
   (`config/settings.py` reads `DJANGO_SELLER_PSEUDONYM_KEY`); no model field
   stores it (§3.8), so no `pg_dump` output can contain it.
2. **The key is not written into any backup artifact**, and no script echoes,
   copies, or derives a file from it.
3. **The key is not stored beside the dump by default.** The backup container
   is never even given it (§6.1) — co-locating the dump with the key that
   unlocks its sensitive content would concentrate risk
   (`docs/09_PLANNING.md` §3.7).
4. **Restore explicitly requires the operator to recover the ORIGINAL key
   independently**, from their own secret store, as a distinct recovery step.
5. **Losing the key is unrecoverable and permanent.** Pseudonymisation is
   one-way (§3.8): the counterparty plaintext is nowhere in the system. A
   database restored under a different key keeps every stored token intact and
   still *readable*, but all **future** tokens stop matching past ones, so
   repeat-counterparty linkage silently breaks forever. The key cannot be
   rotated, re-derived, or brute-forced back.

### 9.2 What can honestly be verified — and what cannot

**Cannot:** decrypt or reverse any stored pseudonym; prove from the database
alone that a supplied key is the original. There is **no key fingerprint
stored anywhere**, and TASK_037 must not add one — that would require a schema
change this task explicitly does not own.

**Can:** exploit determinism. Given a known plaintext input and the token that
the original key produced for it, recomputing
`HMAC-SHA256(candidate_key, input)` and comparing to the stored token
distinguishes the original key from any other with overwhelming practical
certainty.

Two honest verification paths, both frozen:

- **In the drill (§11):** the fixture writes a `RawListing` whose `seller` is
  `pseudonymise("<synthetic counterparty sentinel>")` under the original key,
  through the real code path. After restore, the drill recomputes the HMAC
  with the operator-supplied key and asserts byte-for-byte equality with the
  restored `seller`, and additionally asserts a deliberately wrong key does
  **not** match — so the check is proven key-sensitive rather than
  vacuously true.
- **For real production data (operator procedure):** production seller
  plaintexts are never stored, and demo data has none (§3.9), so continuity
  cannot be checked against arbitrary production rows. The operator therefore
  retains a **continuity canary**: one synthetic, non-PII sentinel string and
  the token it produced under the original key, recorded at backup time
  alongside their key-recovery notes (not beside the dump). Restore
  verification recomputes the canary token with the recovered key.

**Honest limits, stated rather than glossed:**

- This proves the recovered key *reproduces the same token*, i.e. equality up
  to HMAC-SHA256's collision/second-preimage resistance. It is overwhelming
  practical evidence, not a formal uniqueness proof.
- A recorded `(plaintext → token)` pair is an offline brute-force oracle
  against the key. It is safe only because the key is expected to be
  high-entropy, and the canary pair must be treated as sensitive material, not
  published. It must never be a real counterparty name.
- Nothing here is encryption; nothing here makes a lost key recoverable.

### 9.3 Key-free linkage check

One linkage property needs no key at all: a TASK_007 **swap** writes the
*same* seller token to both `RawListing` rows
(`ingestion/admin.py::_write_personal_trade`). That equality — two distinct
immutable rows sharing one token, joined through `ingestion_swap` — is exactly
the repeat-counterparty linkage §3.7 is about, and its survival is verified
directly.

## 10. Backup confidentiality — what is and is not claimed

Frozen requirements: `umask 077` → 0600 dump and checksum (§3.4); no
credential in any artifact name; `PGPASSWORD` via environment, never argv; no
dump contents written to stdout/stderr; no seller, counterparty, source, price,
or row value in success output — a successful run reports only the artifact
name, byte size, and duration; no secret literal in either script.

**Not claimed: encryption at rest.** The dump is **unencrypted**. It contains
every pseudonym token, price, personal trade record, and session/auth row in
the database, and anyone who can read the file can read all of it. Filesystem
permissions and host access control are the only protections TASK_037
provides.

Encryption is deliberately excluded rather than half-implemented: it demands a
key-management decision (where the backup encryption key lives, how it is
recovered, who holds it) that would create a *second* backup-critical
unrotatable secret with exactly the §3.7 problem — and doing it wrong produces
dumps that cannot be decrypted when needed, which is worse than an
unencrypted dump whose exposure is understood. It is a NON-BLOCKING
deployment decision tied to the destination choice (§19).

## 11. Scratch restore architecture and the destructive boundary

### 11.1 Sequence

```
snapshot active application DB (counts + exact migration state)
   -> start one isolated PostgreSQL 16 scratch cluster
   -> create pricewatch_backup_source_scratch and pricewatch_restore_scratch
   -> migrate and populate deterministic fixtures in SOURCE scratch only
   -> capture the exact source snapshot required by §12
   -> run the real pg_backup.sh against SOURCE scratch in the isolated drill backup runner
   -> capture its exact BACKUP_ARTIFACT=<basename> success record
   -> require and verify that exact .dump + .dump.sha256 pair
   -> pg_restore --no-owner --no-privileges --exit-on-error into TARGET scratch
   -> run §12 verification without migrating TARGET
   -> snapshot active application DB again and require exact equality
   -> report success/failure
   -> re-prove exact scratch ownership
   -> remove only the exact verified scratch container, network, and volume
```

### 11.1.1 Production service versus isolated drill backup runner

The production mechanism remains the profile-gated Compose `backup` service in
§6 and the operator command in §13. The mandatory restore drill must never run
that service through the drill Compose project: loading the full repository
Compose model as a runnable drill project was empirically proven to materialise
the unrelated `postgres_data` volume.

The drill still performs a **real PostgreSQL backup**. It must execute the
repository's actual `pg_backup.sh`, not a copy, reimplementation, mock, or
simplified substitute, in a direct disposable Docker backup runner with this
frozen contract:

For deterministic source review of this high-risk boundary,
`pg_restore_verify.sh` must isolate the direct runner in one top-level
`run_drill_backup()` shell function. That internal function is an audit
boundary, not a new operator interface: it contains exactly one direct
`docker run`, no nested function or heredoc, and only the explicit long-form
Docker options required by the contract below.

1. use the exact PostgreSQL image/tooling identity frozen in §5, matching the
   `db`, production `backup`, and `restore_scratch` PostgreSQL 16 image contract;
2. execute the repository's actual `pg_backup.sh`;
3. mount that script read-only at its production path,
   `/usr/local/bin/pg_backup.sh`;
4. bind-mount the configured backup directory read-write at `/backups`;
5. receive exactly `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and
   `PGPASSWORD`, with no `env_file` or additional application setting/secret;
6. point those variables only at `pricewatch_backup_source_scratch` in the
   isolated scratch cluster;
7. join only the already ownership-verified drill default network by its exact
   verified identifier;
8. publish no port;
9. carry no Compose drill-project identity or Compose project label;
10. create or retain no persistent Docker volume;
11. never mount or address `postgres_data` or `task037_scratch_data`;
12. use `--rm` or an equivalently exact disposable-container lifecycle;
13. pass `PGPASSWORD` through container environment only, never in argv;
14. capture stdout from the real `pg_backup.sh` and continue to require exactly
    one `BACKUP_ARTIFACT=<basename>` success record;
15. preserve every existing strict-basename, complete-pair, 0600-permission,
    checksum, `pg_restore --list`, and orphan/partial/malformed rejection;
16. re-run exact drill-resource ownership proof immediately before launching
    the backup runner;
17. re-run exact drill-resource ownership proof immediately after it exits;
18. fail closed before artifact handling or restore if either boundary proof
    fails or ownership changes; and
19. explicitly account for every data-volume path declared by the PostgreSQL
    image and prove after exit that the runner retained no new persistent Docker
    volume. `--rm` alone is not accepted as that proof.

The runner must prevent image-declared volume paths from becoming persistent
Docker volumes and must compare an authoritative persistent-volume inventory
across its execution. Any uncertain image-volume behavior, changed inventory,
or inability to attribute and prove the runner's storage boundary is a nonzero,
fail-closed drill result. It must not be worked around by weakening the
one-project-volume ownership proof or by broadening cleanup.

This drill never backs up the operator's active development database. It uses
one disposable PostgreSQL cluster with two databases:

- `pricewatch_backup_source_scratch`: migrated and populated with deterministic
  source fixtures through the real Django models/services and database
  constraints, then read by the isolated drill backup runner executing the real
  `pg_backup.sh`;
- `pricewatch_restore_scratch`: created empty and populated only by
  `pg_restore` from that exact artifact pair.

Using two databases in one isolated cluster keeps server version, role and
cluster settings identical while still making source-versus-restored
comparisons direct. It also prevents owner-review validation from depending on
whatever data happens to be in the active application database.

### 11.2 The isolated target

```yaml
  restore_scratch:
    image: postgres:16.14-bookworm
    profiles: ["restore-verify"]
    restart: "no"
    environment:
      POSTGRES_DB: postgres
      POSTGRES_USER: restore_scratch
      POSTGRES_PASSWORD: ${PRICEWATCHPH_RESTORE_SCRATCH_PASSWORD:-}
    volumes:
      - ${PRICEWATCHPH_BACKUP_DIR:-./backups}:/backups:ro
      - task037_scratch_data:/var/lib/postgresql/data

volumes:
  task037_scratch_data:
```

`pg_restore_verify.sh` runs **on the host** as an operator/drill script: it
generates the ephemeral scratch password, uses a drill-only Compose project,
brings the scratch service up, creates both fixed database names, migrates and
populates only the source database, runs the isolated §11.1.1 backup runner
against that source, captures the exact artifact basename emitted by the real
`pg_backup.sh`, verifies that exact pair, invokes the restore *inside the scratch
container*, runs the §12 verification, then re-proves and removes only the exact
verified scratch resources. The host script is therefore not mounted into any
container.

The restore itself executes inside the scratch container, whose environment
contains only scratch connection variables:

```
docker compose exec restore_scratch \
  pg_restore -U restore_scratch -d pricewatch_restore_scratch \
             --no-owner --no-privileges --exit-on-error /backups/<artifact>
```

- A **distinct disposable container** with its own database name, its own role,
  and one Compose-declared `task037_scratch_data` volume mounted at
  `/var/lib/postgresql/data`, never the `db` service or the `postgres_data`
  volume. It is the only Docker volume attached to `restore_scratch`; its drill
  project and `task037_scratch_data` Compose labels are independently provable.
- **No published port**, so the restored copy is not reachable from the host.
- The backup directory is mounted **read-only** here, so restore verification
  can never mutate or delete a backup artifact.
- Compose uses an optional empty interpolation default so inactive scratch
  configuration never makes ordinary application commands require a drill
  secret (§3.7). `pg_restore_verify.sh` always generates and supplies a fresh,
  non-empty random value before activating the profile. No literal is
  committed and `POSTGRES_HOST_AUTH_METHOD=trust` is forbidden.

### 11.3 What structurally prevents restoring over the active database

Five independent layers, none of which is a comment or operator memory:

1. **The target is fixed and not parameterisable.** The mandatory drill takes
   no host, port, database, user, connection string, or target option. Its
   restore target is the literal `restore_scratch` /
   `pricewatch_restore_scratch` identity. The artifact is not guessed or
   supplied as a target-like argument: the script creates a source backup and
   captures the exact basename from `BACKUP_ARTIFACT=`. If a future manual
   artifact mode is added, it may accept only one strictly validated basename
   matching §6.2; it must not accept paths or any database connection value.
2. **The restoring process is never given production credentials.** The
   `pg_restore` invocation runs inside the `restore_scratch` container, whose
   environment holds only the scratch role and its ephemeral password;
   `POSTGRES_PASSWORD` is never placed there and is never passed to the
   restore step. A misdirected `pg_restore` therefore cannot authenticate
   against `db` even though both are on the same network. Absence of
   credentials at the point of use is the strongest guard available. (The
   host-side orchestrator can of course read `.env` — it reads
   `POSTGRES_HOST`/`POSTGRES_DB` for the guard in layer 3 — but it never
   forwards those values into the restore step, which is the property that
   matters.)
3. **Explicit identity guards.** The script requires the disposable Compose
   project, scratch service identity, source name
   `pricewatch_backup_source_scratch`, and target name
   `pricewatch_restore_scratch`. It aborts if the restore target equals either
   the active application database or the source scratch database.
4. **Profile gating.** `profiles: ["restore-verify"]` means the scratch
   service never starts during `docker compose up` (verified, §3.7), so a
   restore target does not even exist during normal operation.
5. **Format discipline.** The exact complete artifact pair is restored into a
   *freshly created empty target*; `--create` is not used (it would carry the
   source database name and owner), and `--clean`/`--data-only` are forbidden —
   `--clean` would drop objects in whatever database it were pointed at, which
   is precisely the catastrophe this section exists to prevent.

### 11.4 Restore details settled

- **Ownership/roles:** the dump records owner `${POSTGRES_USER}`, which does
  not exist in the scratch cluster; `--no-owner --no-privileges` remaps to the
  scratch role (verified working in HARDEN).
- **Database creation:** the container bootstraps only the administrative
  `postgres` database. The host orchestrator creates the two fixed databases
  explicitly. Django migrations and fixtures run only against
  `pricewatch_backup_source_scratch`; `pricewatch_restore_scratch` remains
  empty until the restore.
- **Extensions:** none exist (§3.10), so none need restoring.
- **Schema, constraints, indexes, triggers:** all restored from the dump's
  pre-data and post-data sections; verified present *and armed* afterwards
  (§12).
- **Migration table:** `django_migrations` is restored as data. Verification
  is read-only (`migrate --check`); see the prohibition below.
- **Interrupted restore:** `--exit-on-error` makes `pg_restore` stop at the
  first error rather than continue and report success over a partial restore.
  A failed drill exits nonzero and never reports success. Diagnostic command
  output and logs remain available to the operator. EXIT cleanup attempts the
  exact-resource procedure below on success and failure. If ownership cannot be
  re-proven, resources are deliberately preserved rather than risking active
  application data.
- **Cleanup:** no Compose project-wide teardown is permitted. Cleanup may
  remove only the exact container ID, network ID, and dedicated scratch-volume
  name whose ownership was re-proven immediately before deletion. It never
  targets the active application's Compose project or `postgres_data` volume.

### 11.5 Exact-resource cleanup safety boundary: post-incident frozen contract

Cleanup authorization starts false. The scratch startup command must return
successfully, then ownership of the created drill resources must be proven; only
after that complete proof may cleanup become armed. Installing an EXIT trap
earlier is allowed only while its destructive authorization remains false.

Every armed EXIT cleanup must:

1. clear every previously verified destructive container, network, and volume
   value before proof begins;
2. regenerate no project or resource identity and instead re-run ownership
   proof against live Docker metadata;
3. require a drill project identity distinct from the active project and
   matching the fixed `task037-drill-*` form;
4. require exactly one project-labeled container and require its full ID to be
   the Compose-resolved `restore_scratch` container ID;
5. verify that container's exact Compose project and service labels;
6. require exactly one attached network, require its full ID to equal the sole
   project-labeled network ID, and verify the expected project and `default`
   network labels;
7. require exactly one attached Docker volume, require its exact name to equal
   the sole project-labeled volume name, and verify the expected project and
   `task037_scratch_data` volume labels;
8. populate destructive identifiers only after all identity, cardinality,
   attachment, and label checks have succeeded; and
9. remove only those exact verified identifiers.

`docker compose down`, project-wide teardown, prune operations, label-filtered
removal, and deletion derived from guessed project/resource names are forbidden.
If any proof fails, cleanup performs no destructive removal, preserves the
resources, emits a clear error, and returns nonzero. If an exact removal fails,
cleanup stops, returns nonzero, and performs no broader fallback. Leaked scratch
resources are safer than cleanup whose destructive target is uncertain.

**Prohibited:** running `manage.py migrate` (applying migrations) against the
restored database as part of verification. That would paper over an
incomplete backup by rebuilding what the dump failed to carry. The backup must
represent the committed state it was taken from, so verification uses only the
read-only `migrate --check`.

## 12. Restore verification criteria — frozen

Row counts alone are insufficient. Before `pg_backup.sh` runs, the drill emits
one canonical JSON source snapshot from
`pricewatch_backup_source_scratch`. It includes full ordered migration state
and per-app heads, representative row counts, selectors and exact values for
all field-level assertions, the exact money string, payload sentinels, and all
fixture seller tokens. The integration tests compare the restored target to
that source snapshot, never to values re-read from the restored database and
never to a hardcoded count. Snapshot production must fail if any required
fixture or section is absent.

**Connectivity and consistency**
1. A PostgreSQL connection to the restored database succeeds and reports
   server major version 16.
2. `manage.py migrate --check` exits 0 against the restored database — no
   unapplied migrations, so its migration state matches the codebase.
3. `django_migrations` is non-empty; its full ordered `(app, name)` state and
   its per-app head both exactly match the source snapshot.

**Structure**
4. All 20 expected public tables are present.
5. All four triggers of §3.1 exist in the restored database, by name.
6. Each immutability trigger is **armed, not merely present**: an `UPDATE` on a
   restored `ingestion_rawlisting`, `pricing_pricepoint`, and
   `pricing_dealflag` row each raises; a `DELETE` on `alerts_alertdelivery`
   raises; and a direct terminal-status `INSERT` into `alerts_alertdelivery`
   raises. (Executed inside transactions that are rolled back.)
7. Key constraints survive and reject violations:
   `rawlisting_source_external_id_fetched_at_unique`,
   `rawlisting_raw_price_non_negative`, and `dealflag_listing_unique`.
8. Money columns retain exact type and scale — `numeric(12,2)` for prices
   (§3.10) — and the named fixture's restored price compares exactly equal to
   the source snapshot via `Decimal(source_string)`, with no float anywhere in
   the check.

**Data**
9. Representative row counts agree with the source snapshot for
   `sources_source`, `catalogue_sku`, `catalogue_skualias`,
   `ingestion_rawlisting`, `ingestion_swap`, `listings_listing`,
   `pricing_pricepoint`, `pricing_dealflag`, `outcomes_outcome`, and
   `alerts_alertdelivery`.
10. Every named fixture `RawListing` survives field-exact against the source
    snapshot: `raw_title`,
    `raw_price_text`, `raw_price`, `url`, `fetched_at`, `occurred_at`,
    `external_id`, and `payload`. Two deterministic fixture rows are mandatory:
    one has SQL `NULL` payload and one has JSON `{}`; both source values and
    both restored values are asserted, so this check cannot pass vacuously.
11. `Listing → RawListing` and `Listing → Sku` relationships resolve, with no
    orphaned foreign key.
12. Named `PricePoint`, `DealFlag`, `Outcome`, and `AlertDelivery` fixture rows
    survive with representative field values exactly equal to the source
    snapshot, including an `AlertDelivery` row in a terminal (`sent`) state —
    the case §3.2 proves is the hard one.
13. `personal_records` forward-only rows survive: the `sources_source` row
    named `personal_records` exists, the named `RawListing` has the exact
    non-null `occurred_at` from the source snapshot, and the named
    `ingestion_swap` pairing still joins its two immutable sides.

**Pseudonymisation**
14. Every deterministic fixture `seller` token is byte-for-byte identical to
    the source snapshot, selected by fixture row identity rather than inferred
    from another restored row.
15. Deterministic continuity: `HMAC-SHA256(original_key, sentinel)` equals the
    restored `seller` token for the fixture row — and a wrong key does not
    match, proving the check is key-sensitive (§9.2).
16. Key-free swap linkage: both sides of the restored swap still share one
    identical token (§9.3).
17. No counterparty plaintext appears anywhere in the restored fixture row.

**Non-interference**
18. The active application database is untouched: independently captured
    before/after snapshots contain the same non-empty representative row-count
    map and the same full ordered `django_migrations` state. The drill's
    structural inability to reach it (§11.3) is the primary guarantee; this is
    the empirical confirmation.

## 13. Scheduling boundary

TASK_037 adds **no scheduler** and does **not** touch TASK_036's scheduler,
its service, or its crontab. It exposes exactly one fixed, non-interactive
command with a stable exit contract, suitable for a host cron/systemd timer or
a TASK_038 runbook step:

```
docker compose --profile backup run --rm backup
```

Exit 0 = both final files exist as a complete, structurally validated,
checksum-valid pair and the exact `BACKUP_ARTIFACT=<basename>` success record
was emitted. Exit `3` = either final path already existed and nothing was
overwritten. Any other nonzero exit = backup failure; `.partial` files, an
orphan dump, or an invalid/incomplete final pair may remain and must be rejected
by restore. Choosing a frequency is a NON-BLOCKING deployment decision (§19).

## 14. Files

### HARDEN artifacts — frozen before implementation

- `tasks/TASK_037_BACKUP_AND_VERIFIED_RESTORE.md` (this file)
- `tests/test_task_037_backup_and_verified_restore.py`

### IMPLEMENT files allowed — after owner approval

- `docker-compose.yml` — add the `backup` and `restore_scratch` services. At
  the TASK_037 checkpoint, the only permitted existing-service change was
  replacing literal `.env` with `${PRICEWATCHPH_APP_ENV_FILE:-.env}` for the
  `db`, `migrate`, and `web` `env_file` entries, so a drill in a separate
  worktree could explicitly select the active application's environment file
  for read-only non-interference snapshots. Their image/build behavior,
  commands, dependencies, ports, restart policy, and database volume remained
  unchanged.
- `pg_backup.sh` (new, repository root)
- `pg_restore_verify.sh` (new, repository root)
- `.gitignore` — add `/backups/`, `*.dump`, `*.dump.sha256`

**Not authorized:** `Dockerfile` (§3.6/§5 — no client tools in the app image),
`config/settings.py` (Django reads nothing new), `.env.example` (§6.3 — would
break TASK_001's frozen symmetry test), `requirements.txt`, any model, any
migration, any frontend file, TASK_036's scheduler, any Caddy artifact, any
previously frozen test module, `CLAUDE.md`, `docs/*`.

**No schema change and no migration is expected or authorized.** Repository
inspection surfaced no evidence that one is needed; §9.2 records the one place
a schema change might have been tempting (a key fingerprint) and rejects it.

### TASK_037A successor amendment — frozen before TASK_037A implementation

TASK_037A supersedes only TASK_037's historical `db.env_file` allowance. The
database service must not load the application environment file. Its
`environment` mapping contains exactly these existing Compose-interpolated
variables:

```yaml
POSTGRES_DB: ${POSTGRES_DB:-}
POSTGRES_USER: ${POSTGRES_USER:-}
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-}
```

`migrate` and `web` retain
`env_file: ["${PRICEWATCHPH_APP_ENV_FILE:-.env}"]`; TASK_036 independently
freezes the same application-environment source for `scheduler`. This
successor amendment adds no environment variable or deployment mechanism and
changes no TASK_037 backup service, restore-scratch service, backup/restore
script, exact-resource cleanup rule, restore isolation boundary, image,
volume, health check, or restart behavior.

TASK_037's original compatibility test also recorded the inherited TASK_034
runtime topology because TASK_035 had not yet been integrated: `web` published
host port 8000, Gunicorn used the loopback-only forwarded-IP allowlist, and no
`caddy` service existed. TASK_035 later becomes the sole authority for public
ingress. During TASK_037A integration, TASK_035 therefore supersedes only
TASK_037's inherited assertions about `web` host-port publication, Gunicorn's
exact forwarded-IP allowlist, Caddy presence, and the exact `web` key set that
encoded that topology. TASK_037 neither replaces those assertions with
TASK_035 requirements nor owns their successor values.

TASK_037 continues to freeze the `db`, `migrate`, and non-ingress `web`
compatibility properties required below, plus every backup, restore,
exact-resource cleanup, isolation, continuity, artifact, and non-interference
invariant in this contract. This ingress-ownership delegation changes no
TASK_037 production behavior.

## 15. Acceptance criteria — frozen

`tests/test_task_037_backup_and_verified_restore.py` is the authoritative
artifact. It has two explicitly separated halves, because a real restore
cannot honestly be proven inside an ordinary in-container pytest run: the
application image contains no `pg_dump`/`pg_restore` (§3.6), and mocking them
would prove nothing about recovery.

**A. Static/contract tests — always run.** The `db` service has no `env_file`
and receives exactly `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`
through same-named Compose interpolation; application secrets cannot enter
that service through a blanket environment file. `migrate` and `web` retain
the application environment selector and their database dependency semantics.
The exact `web` ingress keys, port publication, Gunicorn forwarded-IP value,
and Caddy presence are deliberately delegated to TASK_034/TASK_035. Both
TASK_037 services exist and are
profile-gated; both use the `db` service's exact image tag; inactive backup
interpolation may resolve empty, while `pg_backup.sh` rejects every missing or
empty required PG connection value before artifact creation or `pg_dump`; the
production backup service carries no `env_file` and no Django secret or
pseudonym key in its environment; its stable operator interface remains
`docker compose --profile backup run --rm backup`; the restore drill contains
no Compose-service backup invocation and instead uses a direct disposable
runner that executes the actual `pg_backup.sh` in the exact PostgreSQL image
contract, mounts the script read-only at its production path and `/backups`
read-write, receives only the five scratch `PG*` values, uses only the exact
verified drill network, publishes no port, carries no Compose project label,
and mounts neither named data volume; `PGPASSWORD` never appears in argv; the
runner is surrounded by exact ownership proofs, explicitly handles the
PostgreSQL image's declared data-volume behavior, and proves it retained no new
persistent Docker volume; the destination remains a configurable bind mount,
not container-only storage; the scratch service is distinct from `db`,
unpublished, mounts the backup directory read-only, owns only its declared
`task037_scratch_data` Docker volume, and takes a password generated by the
drill while remaining parseable without that scratch-only variable;
`pg_backup.sh` sets `umask 077`, refuses either
pre-existing final path, creates dump and checksum under `.partial` names,
validates structure, publishes both files without claiming pair-level
atomicity, verifies the final pair, and emits success only afterwards; UTC
artifact naming carries no secret; `pg_restore_verify.sh` accepts no database
target argument, creates and captures the exact backup basename, rejects every
orphan/incomplete/malformed pair, and never selects by mtime, wildcard, or
"latest"; it verifies checksum and structure before restoring, uses
`--no-owner --no-privileges --exit-on-error`, never
uses `--clean`, `--data-only`, or `--create`, guards the scratch sentinel
name, and never runs `manage.py migrate` to apply migrations; neither script
deletes anything under the backup directory; neither script contains a secret
literal; no data-directory or volume copying appears anywhere; `.gitignore`
covers dump artifacts; `.env.example` is unchanged; no model or migration is
added; the pseudonym key is absent from every backup/restore code path; cleanup
is armed only after startup and complete ownership proof; every proof clears
stale identifiers and proves exact cardinality, attachment, and Compose labels;
destruction uses only the exact verified container ID, network ID, and scratch
volume name; and no Compose-wide or broader destructive fallback exists. It
also proves, in pure Python against `ingestion.pseudonymise`, that the
continuity method is sound and key-sensitive, and that a wrong key fails.

**B. Mandatory integration restore drill — skipped unless explicitly
enabled.** Guarded by `PRICEWATCHPH_T037_SCRATCH_*` plus canonical source and
active-before/after JSON snapshots that `pg_restore_verify.sh` provides; it
refuses to run at all unless the target database is the scratch sentinel. When
enabled it connects to a genuinely restored target and asserts every criterion
of §12 directly against the isolated source snapshot. **`pg_dump` and
`pg_restore` are never mocked anywhere in this module.**

## 16. Mandatory restore drill

TASK_037 is **not** complete when a backup command exists. Before commit, the
implementation must perform a real restore into an isolated scratch
PostgreSQL 16 cluster with the two fixed databases from §11.1. It must prove:
only the source scratch database is migrated and populated; the isolated drill
backup runner executes the real `pg_backup.sh` and creates a real backup against
that source without changing exact drill ownership or retaining a persistent
Docker volume; the exact emitted artifact pair exists
with 0600 permissions; checksum and `pg_restore --list` validate; every orphan
or incomplete form is rejected; the target starts empty and receives no
migration before restore; the restore succeeds; every §12 criterion passes
against the pre-backup source snapshot; pseudonym continuity passes honestly
against the original key and fails against a wrong one; the active application
database's non-empty row counts and exact migration state match before and
after; and a trap re-proves ownership and removes only exact verified scratch
resources without addressing the active Compose project.

No public host, real domain, or provider account is required — local
disposable PostgreSQL 16 is sufficient, which is itself evidence the design is
correct. The independent validator should repeat the drill from a fresh clone.

## 17. Compose interpolation variables (documented here, not in `.env.example`)

| Variable | Consumer | Default | Purpose |
|---|---|---|---|
| `PRICEWATCHPH_BACKUP_DIR` | Compose bind mount | `./backups` | Host destination directory |
| `PRICEWATCHPH_RESTORE_SCRATCH_PASSWORD` | Compose `restore_scratch` env | empty while inactive | Ephemeral, non-empty per-drill credential generated and supplied by `pg_restore_verify.sh` |
| `PRICEWATCHPH_APP_ENV_FILE` | Application service `env_file` (`migrate`, `web`, and the TASK_036 scheduler) | `.env` | Explicitly select the active application's environment file when the drill runs from a separate worktree |

None is read by `config/settings.py`; per §6.3 none may be added to
`.env.example`.

## 18. Validation

HARDEN baseline (implementation absent — failures expected):

```
docker compose exec web pytest -v tests/test_task_037_backup_and_verified_restore.py
```

Compatibility subset (must stay green):

```
docker compose exec web pytest -v ingestion/tests/test_task_005_provenance.py \
  ingestion/tests/test_task_007_trade_logging.py \
  ingestion/tests/test_task_003_ingestion.py \
  tests/test_task_030_alert_delivery_persistence.py
docker compose exec web python manage.py makemigrations --check --dry-run
```

Compose profile/interpolation checks (must stay green without exporting backup
connection values or a scratch password, and without adding Compose-only
variables to `.env.example`):

```
env -u POSTGRES_DB -u POSTGRES_USER -u POSTGRES_PASSWORD \
    -u PRICEWATCHPH_RESTORE_SCRATCH_PASSWORD docker compose config
env -u POSTGRES_DB -u POSTGRES_USER -u POSTGRES_PASSWORD \
    -u PRICEWATCHPH_RESTORE_SCRATCH_PASSWORD docker compose config --services
```

The second output must exclude both profile-gated services. If Compose
interpolation behavior is uncertain, first reproduce it with a minimal
temporary Compose file containing one always-on service and one profiled
service. That experiment is diagnostic only and is not committed.

The full backend suite is deliberately **not** run during HARDEN. It is
required before commit, per `docs/09_PLANNING.md` §9's "full backend suite
unaffected".

## 19. Owner decisions

### BLOCKING — required before implementation

**None.** Every mechanism above is settled by repository evidence or verified
PostgreSQL 16/Compose behavior. The task is deliberately parameterised so that
no destination, retention, schedule, or encryption decision blocks it.

### NON-BLOCKING — deployment decisions, parameterised and deferrable

1. **Off-host destination** — where `PRICEWATCHPH_BACKUP_DIR` is synced to and
   how that destination's own credentials are held. Until decided, §7.3 item 2
   remains open and disaster recovery is **not** achieved.
2. **Retention duration and mechanism** — §8; no deletion is implemented.
3. **Backup frequency** — §13; the command is host-scheduler ready.
4. **Backup encryption at rest** — §10; requires its own key-management
   decision, and is coupled to decision 1.
5. **Where the original `SELLER_PSEUDONYM_KEY` and the continuity canary are
   held** — §9; must be independent of the dump, and is the operator's secret
   store, not this repository's.
6. **Host backup directory path** on the eventual production host.

## 20. Stop conditions

Implementation stops and reports rather than improvising if: `pg_dump`'s
section ordering no longer places triggers in post-data (§3.2), since the
whole restore path depends on it; the installed Compose engine stops honouring
profile exclusion (§3.7); satisfying the destination contract appears to
require a new `config/settings.py` variable or an `.env.example` key (§6.3);
verifying pseudonym continuity appears to require a schema change (§9.2); or
the drill cannot reach a scratch target without production credentials
(§11.3); or the exact PostgreSQL tooling cannot run the real `pg_backup.sh`
without creating or retaining an unproven persistent Docker volume (§11.1.1).
