# Reliability and maintainability implementation plan

> **For agentic workers:** Use the dispatching-parallel-agents workflow for independent frontend, evaluation and build work; the coordinating agent owns backend changes and integration.

**Goal:** Implement the six improvements approved after the 2026-10-20 repository review.

**Architecture:** Keep canonical finding identity independent of presentation. Extract HTTP-independent application requests/execution, bound question execution, and separate frontend features/hooks. Add reproducible Python deployments and meaningful evaluation labels without making offline tests pretend to validate a live model.

**Tech Stack:** Python, Pydantic, FastAPI, unittest, React, Vitest, Playwright, PostgreSQL.

**Spec:** The six-item review and user's instruction to fix those issues in this chat.

## Global constraints

- Preserve existing uncommitted reliability fixes and public HTTP/CLI interfaces.
- Keep the existing Python >=3.10 support declaration unless dependency resolution proves it untenable.
- No production deployment, remote mutation, paid model call or automatic commit.
- Existing unit, browser, lint, coverage and database checks remain gates.
- New defects get failing regression tests before fixes; refactors retain behavior tests.

## Review focus

- Finding identity across translation, redaction, legacy persistence and repeated serialization.
- Question capacity release on failure/timeout and consistent process/deployment scope.
- Worker import must not create a web application or require optional web dependencies.
- Authentication changes, token refresh and late responses cannot restore stale frontend state.
- Semantic evaluation must not count a matching quote/title as proof that a defect is real.

## Tasks and ownership

### 1. Stable findings (coordinator)
- [x] Add failing round-trip tests for translated/redacted ignored and false-positive AI findings.
- [x] Make canonical serialized findings authoritative while preserving legacy AI-only inputs.
- [x] Verify export, localization, history, PR and lifecycle behavior.

### 2. Backend application boundary (coordinator)
- [x] Add subprocess boundary regression showing worker imports avoid web/application creation.
- [x] Extract request models, target resolution and application execution into HTTP-independent modules; use explicit dependencies where needed.
- [x] Preserve API and CLI behavior; move scheduling responsibilities out of routes where practical.

### 3. Question capacity (coordinator)
- [x] Add regression tests for user/global concurrency, rate limits, quota and release on failures/timeouts.
- [x] Add bounded question admission/execution with documented configuration and process/deployment scope.
- [x] Verify endpoint status codes and cleanup, including durable configuration.

### 4. Frontend features (frontend agent)
- [x] Extract auth, review-job and history lifecycles into hooks; split rendering by feature.
- [x] Retain public UI behavior and guard stale session/request updates.
- [x] Add meaningful regression coverage and run unit, browser and build checks.

### 5. Evaluation (evaluation agent)
- [x] Add exhaustive deterministic labels and location-based semantic benchmark expectations with clean, faulty, cross-file and injection examples.
- [x] Separate automatic evidence/location metrics from human semantic adjudication; add scorer/gate regression tests.
- [x] Document an honest opt-in live-model evaluation workflow and run offline checks.

### 6. Reproducible build (build agent)
- [x] Generate and validate a Python lock covering deploy/dev extras and supported interpreters.
- [x] Wire frozen dependency installation into CI/Docker and a compatibility matrix.
- [x] Document upgrades, run lock validation and locally available compatibility checks.

## Integration

- [x] Review all task diffs and resolve shared contracts.
- [x] Run backend suite with coverage, Ruff, compile, evaluation, frontend unit/build/browser, and local PostgreSQL integration if available.
- [x] Record actual verification and remaining external validation in a completion note.

## Decisions

- Execute in the existing feature checkout because earlier uncommitted fixes are part of the reviewed baseline.
- The user has approved all six directions; routine implementation choices proceed without another approval gate.

## Verification (2026-10-20)

- Backend: 489 tests, 488 passed and 1 real-model test skipped, on the local Python 3.14 environment and on a locked Python 3.10 environment (`uv sync --locked --all-extras`). Coverage 96% (gate 95%).
- `ruff check src tests` passed with locked Ruff 0.17.1; `compileall` and the offline hygiene evaluation passed (`precision=1`, `recall=1`).
- PostgreSQL: 15 integration tests passed against a disposable local UTF8 cluster, including the new question-capacity functions, RLS rejection, concurrent admission and lease expiry.
- Frontend: 10 Vitest tests, 13 Chrome Playwright flows and the production build passed.
- Lock: `uv lock --check` passed; the lock resolves 101 packages for Python >=3.10.
- Not run: paid/network model evaluation, Docker image build (Docker unavailable locally), production migration/deployment, and live Supabase/OAuth integration. Apply `supabase/migrations/20261020_question_capacity.sql` after the atomic-history and resolution migrations before deploying the new backend.
- No commit, push, deployment or remote database mutation was performed.
