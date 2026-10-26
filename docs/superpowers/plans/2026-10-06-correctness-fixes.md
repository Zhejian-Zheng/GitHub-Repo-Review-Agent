# Correctness fixes implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task. Track steps here.

**Goal:** Fix the five reproduced correctness issues and verify database failure/concurrency behavior.

**Architecture:** Keep public entry points compatible. Introduce a single safe persistence projection and transactional Supabase RPC; make policy trust explicit before scanning. This implements the defect-repair stage of the approved larger architecture design; wholesale frontend/module relocation remains a separate stage.

**Tech Stack:** Python, unittest, LangChain, FastAPI, PostgreSQL/Supabase, existing React tests.

**Spec:** `docs/superpowers/specs/2026-10-06-industrial-architecture-design.md`

## Global constraints

- Preserve existing uncommitted work and public CLI/HTTP/MCP behavior except documented safety corrections.
- Do not publish, deploy, or apply migrations to a remote database.
- Run real PostgreSQL tests locally; HTTP mocks cannot prove transaction semantics.
- Keep finding fingerprints stable; raw findings mean pre-policy, still redacted at export.

## Review focus

- Target Ruff configuration enables fix/fix-only or disables rules: source unchanged and trusted diagnostics remain visible.
- A retried transaction has committed but response was lost: same operation produces one run.
- Two workers save a repository for the first time: one repository and serialized comparison baselines.
- Cancellation/expired lease races a save: no stale-worker history or result publication.
- Secret-like strings in raw findings, diff, AI, Markdown and database errors: no public/persistence leak.

## Task 1: Read-only linter boundary and safe API errors

Files: `linters.py`, `web.py`, `tests/test_correctness_fixes.py`, `tests/test_linters.py`.

- [x] Add real Ruff fixture with fix enabled; assert byte identity and an F401 finding; add unavailable/invalid-output tests and safe history error route tests. Observe RED.
- [x] Force isolated, non-fixing Ruff execution; surface unavailability as an informational tool-status finding. Centralize storage error translation to safe 503 while retaining validation 400/422 and missing 404.
- [x] Run focused regressions and existing linter/API tests; record GREEN.

## Task 2: Explicit repository-policy trust and retained evidence

Files: `config.py`, `service.py`, `review_tools.py`, `agent.py`, `cli.py`, `models.py`, adapter constructors and policy tests.

Interfaces: `run_review(..., trust_repository_config: bool = False)`; `load_review_config` remains the strict parser; `ReviewReport.raw_findings` and `policy_decisions` retain audit provenance.

- [x] Add tests showing an untrusted ignore-all/disabled policy cannot hide files or findings; trusted explicit config works; repeat policy application retains originals and counts once; fingerprints survive severity changes. Observe RED.
- [x] Default all review entry points to ignoring untrusted root policy; `--trust-repository-config` or explicit local `--config` grants trust; pass even empty selected config to avoid agent fallback loading.
- [x] Retain pre-policy canonical findings and per-finding decision/source; serialize redacted; verify report/PR/feedback compatibility.

## Task 3: Atomic, idempotent history persistence

Files: new `persistence.py`, `history.py`, new `20261006_atomic_history.sql`, history tests and PostgreSQL integration suite.

Interfaces: `save_report(..., operation_id: str | None = None)`; RPC `save_review_history(p_payload jsonb, p_operation uuid, p_job uuid default null, p_lease text default null, p_result jsonb default null) returns jsonb`.

- [x] Test one redacted write payload, no fallback on RPC failure and same operation ID on retry. Add real database rollback, same-key retry/conflict, concurrent first-save, owner isolation, feedback and comparison tests. Observe RED.
- [x] Build one redacted snapshot with stable fingerprints. In RPC lock operation + repository, enforce idempotency digest, upsert repository, derive comparison and feedback, write all records in one transaction.
- [x] Add optional lease-fenced job completion in the same transaction. Reject cancelled, mismatched or expired leases; allow exact already-committed retry.
- [x] Replace old multi-request save path, keeping reads and result shape compatible. Remove superseded write helpers and adapt tests that pinned old request order to verify the new contract.

## Task 4: Connect durable jobs and verification

Files: `web.py`, `job_runtime.py`, `history.py`, worker regression tests, CI and documentation.

- [x] Add worker tests verifying a durable history job defers publication to the atomic parent completion, while ordinary/non-durable saves retain their behavior. Observe RED.
- [x] Pass durable context to the isolated worker; return safe pending-history data for parent transaction. Stable job ID is the operation ID; lease fencing protects final commit.
- [x] Verify all five fixes with full backend tests, coverage, frontend unit/browser/build and isolated PostgreSQL concurrency tests; add repeatable database CI job and migration instructions.
- [x] Update audit with fix/test evidence and clearly distinguish completed repairs from remaining broader architecture changes.

## Execution ledger

- Ruling: execute fixes in this session following the user's explicit approval and instruction to repair; no additional approval for the same work. Preserve existing changes without bulk commits.
- Ruling: focus this plan on the five findings the user asked to fix. The approved spec's broader frontend split, dependency locks and full layer migration are not represented as completed by this repair.

- Completed 2026-10-08: backend 448 tests (447 passed, 1 opt-in provider test skipped), 96% coverage; PostgreSQL 10 tests; frontend 7 unit and 6 browser tests plus production build. Ruff, compile and dependency checks passed.
- Independent review identified two additional boundary bugs: redacted AI findings acquired duplicate fingerprints on restore, and completion errors leaked SQL details into job errors. Both were reproduced in failing tests and fixed before the final full backend run.
- Local PostgreSQL 16 was installed for verification; only temporary test clusters were started and stopped. No hosted database migration, deployment, commit or push was performed by this task.
