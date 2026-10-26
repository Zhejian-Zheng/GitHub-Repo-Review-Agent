# Improvement review after feature expansion

The requested features are implemented. These are the next separate improvements identified from the resulting code and integration checks, rather than unfinished items in that scope.

1. **Transactional persistence: implemented 2026-10-08.** One RPC now saves history and durable completion with an operation receipt and lease fencing. Real PostgreSQL tests cover rollback, concurrency and lost-response retries. Apply the new migration before deployment; see [atomic history](atomic-history.md).
2. **Repository trust boundary: implemented 2026-10-08.** Root policy is ignored by default and requires explicit local trust; reports retain raw findings and policy provenance. A configurable organization-wide policy layer is a separate future extension.
3. **Semantic quality labels beyond exact quotations.** The evaluator can prove that a quote exists, but cannot prove that the claimed defect is real. Grow the dataset with hand-reviewed code defects, clean counterexamples, prompt-injection cases, renamed files and regressions; compare precision and recall across repeated model runs.
4. **Change-impact context.** Incremental review prioritizes changed files but does not follow imports, call sites or package dependencies automatically. Add language-specific dependency edges and a bounded neighborhood, with a visible evidence-coverage measure for large PRs.
5. **Provider-aware accounting.** Conservative byte reservations intentionally stop early and actual usage may be absent. Add supported-provider token counting, measured usage history and model-specific budgets, keeping unknown costs explicit. Monetary quotas need a price snapshot and reservation/reconciliation ledger rather than treating tokens as money.
6. **Dependency remediation detail.** OSV batch lookup yields advisory IDs, not authoritative severity/fixed ranges. Add bounded advisory-detail retrieval with caching and distinguish available fixes from upgrades that still require compatibility testing. Extend supported formats to uv, Poetry, pnpm and Cargo only with precise lock-version parsers.
7. **Portable findings export.** Add SARIF output so rule and AI findings with exact locations can be used by existing security/code-scanning tools. Preserve source, confidence and feedback instead of flattening all results into text.

Next recommended work: complete the broader module-boundary refactor and extend semantic quality datasets. These strengthen the reliability of the new functions before expanding language and dependency coverage.
