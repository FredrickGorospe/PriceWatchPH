# TASK_010 — Codex project-reviewer bootstrap

## Goal

Provide a reusable project-scoped Codex reviewer for the PriceWatchPH
implementation workflow.

## Scope

This is a non-schema tooling task. Its implementation change is limited to
`.codex/agents/reviewer.toml`; TASK_007, application code, migrations, hooks,
MCP configuration, and existing agent instructions are out of scope.

## Reviewer contract

1. Review read-only and never implement, edit, stage, commit, reset, check out,
   clean, or move Git refs.
2. Receive no implementation rationale. Task-specific evidence is intentionally
   limited to the applicable frozen task specification and `git diff --cached`.
3. Apply repository `AGENTS.md` rules and review every acceptance criterion.
4. Treat weakened, skipped, xfailed, narrowed, vacuous, bypassed, or
   test-special-cased acceptance coverage as blockers.
5. When relevant, check schema and migration correctness, transactionality,
   permissions, security, data integrity, and undocumented assumptions.
6. Lead with actionable blockers and omit style-only noise.
7. State explicitly when evidence cannot independently prove a claim.
8. Do not claim strict input isolation merely because the prompt requests it.
9. Do not use MCP unless a future task explicitly requires it.
10. Do not inspect unrelated workspace files to reconstruct implementation
    reasoning.

## Acceptance criteria

1. The project agent uses the supported standalone custom-agent TOML schema,
   `gpt-5.6-terra`, high reasoning effort, and a read-only sandbox default.
2. Permission tests record effective behavior under read-only and full-access
   parent modes without modifying the real repository.
3. Isolation testing distinguishes fresh conversation context from filesystem
   read access and does not overstate either guarantee.
4. A disposable fixture proves the reviewer finds a correctness blocker and a
   weakened-test pattern, avoids style-only noise, and does not edit the fixture.
5. MCP inheritance or availability is reported truthfully; no unsupported
   disabling configuration is invented.
6. A fresh generic read-only bootstrap reviewer approves this task's staged
   task file and agent configuration before commit.
7. The complete pytest suite passes and
   `makemigrations --check --dry-run` reports no changes.

## Standing workflow

Invoke the reviewer from a fresh subagent with only the frozen task contents and
`git diff --cached`. Select a read-only parent permission mode before spawning
when the harness permits it. Treat filesystem evidence isolation as
prompt-disciplined unless a prepared scratch bundle provides a stricter boundary.

## Validation record

Validated with `codex-cli 0.147.0` on 2026-08-07:

- The standalone TOML parsed successfully, and strict-config Codex sessions
  loaded and spawned the project agent as `reviewer` using a fresh child context.
- Under a read-only parent, the reviewer reported effective `read-only` sandbox
  and `never` approval modes. It read the supplied bundle and an unrelated
  scratch file, proving filesystem reads are not restricted to the bundle. It
  saw no MCP tools. Its standing instructions refused write, edit, and staging
  probes before sandbox evaluation; the disposable Git fixture remained clean.
- Under a danger-full-access parent, the reviewer reported effective
  unrestricted filesystem access and `never` approvals: the live parent override
  superseded the custom `sandbox_mode`. Generic MCP infrastructure was visible,
  but no specific MCP app tool was exposed or used. The reviewer again refused
  every write and staging probe at the instruction layer, and the fixture
  remained clean.
- Conversation context was fresh and contained no implementation rationale.
  Filesystem evidence isolation is not enforced; it remains prompt-disciplined.
- Against a disposable staged fixture, the reviewer identified the incorrect
  addition implementation and the weakened exact-value assertion, explicitly
  dismissed an irrelevant README punctuation change, and left the fixture
  unchanged.
- `docker compose exec -T web pytest -v` completed with 86 passed in 0.75s.
- `docker compose exec -T web python manage.py makemigrations --check --dry-run`
  exited successfully with `No changes detected`.
