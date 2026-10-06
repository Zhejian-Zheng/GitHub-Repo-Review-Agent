# Finding lifecycle and PR annotations

Apply `supabase/migrations/20261005_finding_lifecycle.sql` after the existing migrations in a staging Supabase project before deploying this backend. It adds finding location/source fields, retains the original AI finding records, and adds owner-scoped feedback. No live database migration is performed by the local implementation. Check an owned project can save a scan and feedback, then scan again: raw evidence remains, while ignored or false-positive findings no longer reduce its effective score. Confirmed findings remain actionable. UTC expiry restores actionability at the expiry instant. Historical saved scores are snapshots; project detail also returns a score calculated with current feedback.

The canonical report collection merges rule and verified AI findings; fingerprint de-duplication prevents AI findings being doubled when a JSON report is loaded again. AI fingerprints include the exact evidence but omit line numbers so moving unchanged code does not reset feedback. Changing the quoted evidence creates a new finding. Rule fingerprints retain the existing format unless a stable rule ID is supplied, which is included alongside the title to distinguish multiple affected targets.

PR report comparison still accepts complete head/base report JSON. Incremental comparison additionally accepts a JSON array from GitHub's [PR files endpoint](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files). File-specific findings are scoped to changed files; repository rules without a file remain visible. Removed files can resolve baseline findings; renamed files preserve existing findings by comparing baseline locations at their new paths. Missing/binary/truncated patches have no verifiable added-line evidence and produce no annotations.

Generate the head report from its checked-out commit, prioritizing the PR's changed files during agent inspection:

```sh
repo-review ./head --agent --changed-files-json pr-files.json --json head.json
repo-review-pr-bot --report-json head.json --baseline-json base.json \
  --changed-files-json pr-files.json --annotation-mode dry-run --comment-mode dry-run
```

`--annotation-mode create --github-repo owner/repo --head-sha <exact-head-commit>` explicitly creates a completed Check run. The token must have Checks write permission supported by GitHub's [Checks API](https://docs.github.com/en/rest/checks/runs#create-a-check-run). Annotations retain the original verified evidence and clip locations to added head lines, splitting spans at unchanged context. Quoted evidence may include surrounding context; annotation locations identify only added lines. Requests contain at most 50 annotations each; further batches append via the update endpoint. Use the PR's exact 40-character head SHA and reports generated from that commit. Create mode rejects a different `metrics.source_commit_sha` or a dirty source snapshot before posting a comment or check. Older reports without source metadata rely on the caller to supply the correct snapshot. This implementation has been tested with mocked HTTP boundaries; it has not published a live check or applied a live migration.

`GitHubClient.list_pull_request_files` paginates the API and fails at its 3000-file cap rather than silently claiming a complete diff. Callers should supply the files array directly when they already fetched PR metadata. Reading that API requires a token through this client; dry-run annotation construction needs no network or token.
