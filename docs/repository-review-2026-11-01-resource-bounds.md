# Resource bounds and review lifecycle follow-up

Branch: `improve/resource-bounds-followup`, based on main after PR #3. The existing
`70f2c94` cherry-pick preserves Ruff identity, AI context budgeting, multi-file
question evidence and report-instance isolation; see the [follow-up audit](repository-review-2026-10-27-followup.md).

## Implemented boundaries

| Boundary | Default | Breach behavior |
| --- | --- | --- |
| Cloned checkout plus `.git` objects | `REPO_REVIEW_CLONE_MAX_BYTES=512000000` apparent bytes | Fail closed during and after clone: kill process group, reject acquisition, remove temp dir; unreadable metadata also rejects |
| Retained inventory | `REPO_REVIEW_MAX_INVENTORY_FILES=10000` regular files | Stop collection, set `inventory_complete=False`, mark `.` as uninspected remainder |
| Traversal | `REPO_REVIEW_MAX_WALK_ENTRIES=50000` entries | Includes ignored entries, links and directories; partial scan or failed acquisition |
| JSON POST/PUT/PATCH ingress | 256,000 bytes | 413 before parsing; oversized Content-Length reads no body, absent/dishonest lengths are checked incrementally |
| Report field | Existing 200,000 serialized bytes | Existing 422 semantic check remains |
| Credential HTTP responses | Auth 64,000; history/GitHub 8,000,000 bytes | Typed bounded-read error mapped to a safe service error; HTTP error bodies discarded |
| Worker output / progress | 4,000,000 / 64,000 bytes | Reject oversize, clean process group and workspace |
| Cancellation monitors | Eight slots per supervisor process | Blocked polls retain slots until returning; saturation rejects new monitored work; cleanup joins for at most 0.2 seconds |

The walker uses bounded `scandir` buffering before sorting. It does not call
`os.walk` or build a second unbounded top-level listing. Selection remains
sorted/deterministic within the admitted inventory; metadata priority and content
`max_files` / `max_file_size` still apply. On a traversal breach, counts describe
only observed entries; `skipped_files` is not an estimate of the unknown remainder.
Incomplete coverage cannot certify absent findings as resolved.

The `improve/clone-peak-disk` follow-up stacks on PR #4
(`improve/resource-bounds-followup`). Clone admission is now checked **during**
download/checkout, at 0.2-second intervals between scans, and again after Git
completes. Reaching the byte limit or exceeding the entry limit fails closed:
the clone process group is killed and reaped before its temporary checkout is
removed. Timeout and probe failures also stop the clone and clean up. Live scans
tolerate entries disappearing during Git's renames/unlinks; other metadata errors
reject acquisition, and the post-clone scan remains strict.
Filesystem/container disk quotas remain defense-in-depth against growth between
probes and during a scan. The sum includes `.git` and uses apparent sizes without
following symlinks, not filesystem allocation accounting. Clone diagnostics do
not accumulate in in-memory pipes. Defaults remain 512,000,000 clone bytes and
10,000 retained inventory files; no new environment variable is required.
Socket timeouts and byte caps do not constitute a total deadline for standalone
HTTP calls; isolated web workers retain their total execution deadline.

The review hook owns every asynchronous continuation with its controller. Reset,
new submission, report close and Demo replacement invalidate the old controller.
Refresh errors pass through guarded catch/finally; stale submission, poll, auth
and finalizer callbacks cannot alter the new run. Cancellation uses its own
abort signal, so stopping tracking still permits cancelling the backend job.

## Evidence and remaining work

Regression tests first failed on unbounded acquisition/inventory/response/output
and ingress behavior. Six browser hook regressions first failed on the original
lifecycle, then passed with controller guards. Browser tests use real React hooks
and local dependency doubles that deliberately settle after abort; normal UI
flows additionally use the existing mocked-HTTP browser suite.

The first full backend run exposed two existing telemetry tests failing during
HTTPX client construction: the inherited SOCKS proxy requires the optional
`socksio` package. Offline reruns use `NO_PROXY='*'`; both affected tests then pass.
No dependency change is needed. Outbound git/gh commands use the supplied proxy.

Semantic adjudication remains Open; see [evaluation status](evaluation.md#adjudication-status-2026-11-01).
Composition/storage ports and a generated current schema snapshot remain Open.
`schema.sql` is legacy; use the migration chain and verification SQL. This change
adds no migration; the included cherry-pick retains its existing Ruff migration.
No production database, paid model or deployment is exercised.
