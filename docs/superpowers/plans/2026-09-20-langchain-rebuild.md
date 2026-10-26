# LangChain Rebuild Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Track progress below.

**Goal:** Replace custom agent loops and provider HTTP code with a tested LangChain runtime across existing entry points.

**Architecture:** Per-run repository sessions expose shared LangChain tools. A LangGraph workflow prepares an offline report; LangChain create_agent optionally enriches it with tools and validated structured output. A shared service routes CLI and Web requests; MCP uses the same agent.

**Tech Stack:** Python >=3.10, LangChain 1.x, LangGraph 1.x, Pydantic 2, optional LangChain provider integrations, unittest, Ruff.

**Spec:** ../specs/2026-09-20-langchain-rebuild-design.md (approved by user).

## Global Constraints

- Preserve offline review, existing report contracts, bilingual output, legacy flags and provider environment variables.
- Remove duplicated custom execution and HTTP code; keep independent scanner/analyzer, auth, history and GitHub integration.
- No paid model requests in automated tests. Keep coverage threshold at 95%.
- Use the approved scope to finish implementation in this session; no additional design approval is needed.

## Review Focus

- Concurrent runs must not share repository state or leak one user's source into another report.
- Malformed tool arguments and symlink escapes must not read outside the scan scope.
- Model/tool budgets, malformed final output and provider failures must not produce a generated status.
- Provider API key, base URL, timeout and output length must survive migration without secret disclosure.
- Legacy modes must use the new engine, including linter options and language propagation.

## Task 1: Model configuration and structured synthesis

Files: create `provider.py`, `review_schema.py`, `tests/test_provider.py`; edit `llm.py`, `tests/test_llm.py`, `pyproject.toml`.
Interfaces: `create_chat_model(provider, model, timeout, max_output_tokens, ollama_url) -> BaseChatModel`; `ReviewSections` Pydantic model; existing `add_ai_review` signature retained.

- [x] Write provider configuration and real fake-model synthesis tests; confirm failure before implementation.
- [x] Add bounded 1.x dependencies and provider extras. Replace manual transport with provider integrations, safe errors and a shared four-section schema.
- [x] Preserve historical report parsing functions for persisted reports, while validating newly generated output strictly and allowing one bounded repair.
- [x] Run `python -m unittest discover -s tests -p 'test_provider.py'` and `test_llm.py`; verify timeout, key, unsupported-provider and malformed-output behavior.

Core validation assertion:
```python
self.assertEqual(add_ai_review(report, provider='ollama').ai_review.status, 'generated')
with self.assertRaises(AIProviderError):
    add_ai_review(report, provider='unknown')
```

## Task 2: Shared tools and framework execution

Files: create `review_tools.py`; rewrite `agent.py`, `function_agent.py`; migrate `tests/test_agent.py`, `tests/test_function_agent.py`; add test fake model utilities.
Interfaces: `ReviewSession(root, max_files, max_file_size, language, run_linters)` owns tools and report; `RepoReviewAgent.run(Path) -> ReviewReport` remains public; legacy adapters delegate to this agent.

- [x] Write tests that require framework metadata, safe bounded tools and model-driven calls; observe failures.
- [x] Implement typed tools with per-run state, locking, trace, safe path and read limits; wrap deterministic preparation in LangGraph.
- [x] Use `create_agent(..., response_format=ToolStrategy(ReviewSections))` with model/tool limits and bounded recursion; preserve the prepared report on non-strict AI failures.
- [x] Test real graph execution using a scripted LangChain model: tool call, invalid arguments, output repair, missing structured output, budget exhaustion, repeated/concurrent runs and legacy provider labels.

Core behavior assertion:
```python
self.assertEqual(report.metrics['agent_framework'], 'langchain')
self.assertIn('inspect_file', [step.tool for step in report.agent_trace])
self.assertEqual(report.ai_review.sections['risks'], ['Evidence-bound risk.'])
```

## Task 3: Entry points and compatibility

Files: create `service.py`; edit `cli.py`, `web.py`, related entry-point tests, and frontend copy if applicable.
Interface: `run_review(root, mode, ...existing options) -> ReviewReport` centralizes dispatch, direct synthesis and failure policy.

- [x] Add service behavior tests before implementation, including direct/agent/legacy modes and lint propagation.
- [x] Route CLI and Web through the service, retaining compatibility classes and flags; keep MCP on the shared agent.
- [x] Replace old internal mocks with service or model-boundary tests; run full unittest suite and resolve regressions.

## Task 4: Documentation, installation and final verification

Files: README, deployment instructions, environment example, implementation checklist, CI if needed.

- [x] Document LangChain architecture, extras, model tool support, offline mode, error/budget behavior and legacy aliases.
- [x] Run Ruff, coverage unittest suite, coverage report (>=95%), compileall, frontend build and a CLI smoke review producing JSON/Markdown.
- [x] Validate optional provider integration construction without network. Verify Python 3.10 dependency resolution if runtime allows.
- [x] Request an independent final code review per executing-plans; fix material findings with regression tests and rerun affected checks.
- [x] Record exact results and remaining real-provider/deployment verification limits in the final delivery.

## Execution Record

- Baseline branch: d7a1bee; working branch: codex/langchain-rebuild.
- Implementation stays in the current checkout on an isolated branch; no second worktree or publication is needed.
- Pre-flight: schema and model factory feed synthesis and agent; shared session feeds offline and model paths; service consumes the unchanged report contract.


## Completion and validation

- Task 1 complete: LangChain provider factory and schema-backed synthesis replaced manual HTTP implementations. Provider configuration, missing integrations/keys, invalid output repair and error redaction tested.
- Task 2 complete: LangGraph offline preparation and real `create_agent` execution tested with scripted LangChain models, including invalid calls, malformed final output, budget exhaustion and concurrent run isolation.
- Task 3 complete: CLI, HTTP and MCP use the shared review service. Legacy flags/classes remain thin adapters. Linter and language options reach the common implementation.
- Task 4 complete: dependency extras, both deployment paths, environment example, README and architecture documentation updated.
- Final test command: `COVERAGE_FILE=/tmp/repo-review-langchain.coverage .venv/bin/coverage run -m unittest discover -s tests` — 241 tests passed.
- Coverage report: 96%, with the original 95% minimum retained.
- Ruff, compileall and `git diff --check` passed. Editable installation and `pip check` passed.
- Frontend: `npm ci` and `npm run build` passed. Existing lockfile audit reports 6 dependency advisories (1 low, 1 moderate, 4 high); frontend dependency upgrades were not part of the agent migration.
- Actual CLI offline runs generated English and Chinese Markdown/JSON, with LangChain metadata and 8 traced tool steps.
- Real MCP 1.30.0 registration exposes all three public tools. Added a real-package test after detecting that unconstrained MCP 2.x no longer exposes the existing FastMCP API; extras now require MCP <2.
- Python 3.10 support is retained and all selected LangChain package metadata declares >=3.10. Local execution used Python 3.14; a separate 3.10 runtime was unavailable.
- No paid/live provider call was made. Provider configuration and execution paths were verified with local model doubles and real framework execution. Docker executable was unavailable, so image build/runtime remains unverified.

## Independent review resolution

- Important: aliases to `.env` or excluded directories could bypass read scope. Fixed by validating the resolved target against scanned file membership and sensitive names. Regression tests failed before the fix and passed afterward.
- OpenRouter legacy header aliases restored with documented primary-variable precedence. Treated as compatibility work rather than deferred polish; regression tested.
- Malformed path resolution now returns a bounded, recoverable tool error. Treated as part of the promised malformed-argument behavior; regression tested.
- Ordinary source text remains available to the selected model as required for tool-driven review. This migration does not introduce a general source-secret redaction engine.
- No review findings are deferred. The code remains available for review on local branch `codex/langchain-rebuild`.
