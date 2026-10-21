# Review reliability fixes

> **For agentic workers:** Use superpowers:executing-plans for inline implementation and a final independent review.

**Goal:** Fix the five reproduced defects in the additional improvement audit.
**Architecture:** Record conservative checker coverage, separate absent findings into resolved/unverified, and retain unverified history across runs. Keep lint scope in the scanner and guard frontend state by request identity.
**Tech Stack:** Python, PostgreSQL, React, unittest, Playwright.
**Spec:** docs/additional-improvements-2026-10-08.md

## Constraints and rulings

- Continue on the existing non-main working branch; preserve the audit document.
- User authorized these concrete fixes; implement without another plan approval.
- No live service/database modifications. Add a forward SQL migration and verify in a disposable database.
- Preserve API compatibility by adding optional fields. Old reports without coverage cannot establish resolution.
- AI omission alone cannot prove resolution. Changed policy, disabled tools, truncated input and failed reads must remain unverified.

## Review focus

- Repeated partial scans must retain older unverified findings.
- Deleted files and genuinely fixed rules must still resolve when coverage establishes it.
- Ruff must not inspect fixtures, ignored paths or unsampled files, including when no Python file is sampled.
- Slow responses and logout must not overwrite current project selection.
- Cache expiry and capacity must hold under concurrent writes.

## Tasks

- [x] 1. Add regression tests for JS/JSX test naming, real Ruff scope, and auth cache expiry/capacity; observe failures, implement and rerun.
- [x] 2. Add partial/fixed/deleted/disabled checker/policy/legacy comparison tests. Introduce shared coverage decisions, unverified PR results and comments.
- [x] 3. Add real database regressions for partial → partial → fixed and reappearance. Add migration, retain unknown findings in diff_json, expose counts and UI state.
- [x] 4. Add browser regression for reversed project responses and logout. Add request cancellation and identity guards to detail/feedback refreshes.
- [x] 5. Run backend coverage/lint/evaluation, temporary PostgreSQL integration, frontend unit/browser/build. Perform independent review and resolve substantive findings. Update audit with outcomes.

## Progress

- Initial baseline: 448 backend tests (one live-provider skip), 7 frontend tests and 6 Chrome flows passed in preceding audit.
- Completed 2026-10-09: 465 backend tests (464 passed, one live-provider skip), 96% coverage, 13 disposable PostgreSQL integration tests, 7 frontend unit tests, 10 Chrome browser flows, production build, Ruff, compilation and local evaluation passed.
- Independent review findings addressed with regressions: excluded symlinks cannot establish deletion or clean OSV coverage; blank/truncated reads and malformed manifests cannot establish recheck; Docker inspection no longer exits after its first finding; `.pyi` files remain linted; concurrent feedback mutations do not cancel each other.
- SQL/Python resolution parity verified, including incomplete OSV inventories. No live service or database changes; deployment requires the new forward migration.
