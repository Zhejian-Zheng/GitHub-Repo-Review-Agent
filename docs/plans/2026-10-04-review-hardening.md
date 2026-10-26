# Review hardening

Scope: fix all seven findings from the project audit, preserving the existing LangChain rebuild.

- [x] Scanner: accurate inventory/limits, avoid sample-based absence claims; malformed manifests isolated.
- [x] Data: redact sensitive content before tools, prompts, traces and rendered reports.
- [x] Execution: clone timeout, bounded backlog/user quotas, killable total deadlines, result retention.
- [x] Persistence: atomic claim/lease, periodic recovery, bounded retry, safe completion failures, shutdown.
- [x] Agent: bounded file listing/search/line reads; structured findings with verifiable evidence.
- [x] UI: real progress, abort/timeouts/retry/token refresh, browser regression tests.
- [x] Verification: full Python tests/coverage/lint, frontend tests/build, optional live-provider smoke test.

Parallel ownership: scan_fixes owns scanner/analyzer and snapshot model; job_reliability owns web/history/clone/migrations; frontend_tests owns frontend and frontend CI steps; parent owns tools/redaction/schema/agent and integration/docs.

Use test-first regression checks. No deployment, commits or pushes required. Existing feature branch reused because the changes depend on its uncommitted rebuild.


Langfuse extension: optional pinned SDK, one trace per AI review (including repair), model/tool callbacks, full content omission, fault isolation and bounded flush. CI installs the tracing extra so real SDK tests run.

Final local verification: 309 Python tests, 308 passed and one opt-in live-provider test skipped; 96% combined coverage (95% required); Ruff and Python compilation passed. Frontend: 6 unit tests, 3 browser scenarios in installed Chrome, production build passed. Real Langfuse SDK tests use an offline exporter. Local Langfuse credentials are absent, so remote authentication/delivery was not verified. Supabase migration and cross-worker behavior require staging verification; no live database or Docker runtime was used.

Deployment prerequisite: apply `supabase/migrations/20261004_review_job_leases.sql` before the backend update. Recovery is at least once and may duplicate history after an interrupted completion. See `docs/deployment.md` and `docs/langfuse.md`.
