# Review feature expansion

User requested implementing all recommendations from the feature audit and another improvement review. Existing uncommitted LangChain hardening remains the base.

- [x] Canonical rule and AI findings, persistent feedback and effective score/issues/PR gating.
- [x] Offline labeled evaluations, numeric Langfuse scores, model comparisons and CI thresholds.
- [x] Opt-in bounded OSV dependency advisory checks.
- [x] PR changed-file/range filtering and explicit GitHub Checks annotations.
- [x] Owner-controlled backend cancellation, atomic daily admission quota, per-review model token reservations.
- [x] Bounded declarative project configuration for ignore paths, rule/category selection and severity.
- [x] Report follow-up answers with citations constrained to stored report evidence; authenticated AI access.
- [x] Frontend flows, full tests/coverage/lint/build and additional improvement review.

Ownership: finding_lifecycle owns canonical models/history/report/github/pr_bot and its migration; job_ui_features owns web/job_runtime/frontend and job-control migration; scan_fixes owns config/vulnerabilities/scanner/CLI flags; parent owns service/agent/tools, model budgets, evaluation, questions, MCP and integration/docs.

No deployment or external GitHub writes are part of this request. Database changes are supplied as migrations and require staging verification. Langfuse uploads aggregate numeric quality scores without source/label contents. Dependency scans disclose package names/versions to the public OSV API only when explicitly enabled. Token accounting reserves conservative input bytes and configured output limits; actual token counts remain unknown when the provider omits usage. Report questions use existing report quotations and cannot discover new callers or verify fixes.


Verification on 2026-10-06: 435 Python tests (434 pass, one optional live-provider test skipped), 97% combined coverage, Ruff/compilation/dependency checks passed. Bundled offline quality dataset passed required-title and forbidden-title gates; precision is intentionally unavailable for its partial labels. Frontend verification covers 7 polling/client tests, 6 browser flows and production build. A controlled live OSV query for public npm lodash 4.17.20 returned five advisories. Remote Langfuse delivery, live GitHub Checks creation and PostgreSQL migration/concurrency remain staging checks.

Integration regressions fixed: localized fingerprints/source evidence, feedback preservation in web/CLI/MCP exports, question quota RPC URL, malformed questions, npm/Python version validation, PR patch completeness/added-line splitting/renames/SHA provenance, default browser budget validity, selected follow-up budget forwarding, and cross-thread job identity for actual cancellation.

Usage: `docs/feature-expansion.md`. Further recommendations: `docs/next-improvements.md`.
