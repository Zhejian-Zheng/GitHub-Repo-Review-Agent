# Atomic history persistence

Updated 2026-10-08. History saves now require `supabase/migrations/20261006_atomic_history.sql`, applied **after** migrations 001–004, `20261004_review_job_leases.sql`, `20261005_finding_lifecycle.sql` and `20261005_job_controls.sql`. Run migrations before deploying this version. No remote migration has been applied by this task.

`SupabaseHistoryStore.save_report` sends one safe payload to `save_review_history`. A transaction writes the repository, run, findings, AI result and operation receipt. Failed writes leave no partially completed report. Concurrent saves of the same repository are serialized for a consistent comparison baseline; existing owner-scoped unique indexes protect repository creation.

`operation_id` is an optional UUID for programmatic retry. Reuse it with exactly the same report payload when retrying after a lost response. A conflicting payload or owner is rejected. An omitted ID creates a new review operation. The operation receipts are retained so retries remain deduplicated; manual retention policies must account for that guarantee.

Durable jobs use their job UUID as the operation ID. The isolated worker prepares the result; the supervisor submits history and job completion together. The transaction checks the current lease, its expiry, cancellation and owner. Exact retries after a committed response was lost return the existing receipt. Computation/model calls may repeat after a crash; only persisted effects are deduplicated.

Stored task results contain the structured report with committed feedback. The HTTP adapter renders Markdown from that report at read time so ignored/false-positive findings do not appear in an obsolete backlog. The run's `report_markdown` is the redacted pre-feedback review artifact; `report_json` and structured findings/feedback are the authoritative data for effective presentation.

All newly written report fields use a shared redacted projection, including raw findings, diffs (derived from those findings), AI data and Markdown. This does not retroactively sanitize records created by older versions. Existing deployment data should be reviewed separately before exposing historical records.

There is no fallback to the old multi-write persistence path if the RPC is missing. Roll back application code only to a version compatible with the retained data; do not remove the new receipt table while clients may retry an operation. No destructive cleanup is part of the migration.

## Local database tests

Install PostgreSQL 16 and `pip install -e '.[database-test]'`, then run:

```sh
PG_BINDIR=/path/to/postgresql/bin python scripts/test_postgres.py
```

On Homebrew, the script defaults to `/opt/homebrew/opt/postgresql@16/bin`. It creates a temporary cluster, applies all migrations, runs transaction tests and stops the cluster in a `finally` block. It does not start a login service or use the Homebrew default cluster.

For an already provisioned **disposable** database, set `REPO_REVIEW_TEST_DATABASE_URL` and run `python -m unittest discover -s tests/integration -v`. The database name must end in `_test`. The tests truncate their tables: never supply a production connection. CI uses its own PostgreSQL 16 service and runs the same suite.

The local harness supplies minimal Supabase auth roles/schema for testing PostgreSQL transaction and RLS behavior. It does not emulate the hosted Supabase gateway or test production credentials.
