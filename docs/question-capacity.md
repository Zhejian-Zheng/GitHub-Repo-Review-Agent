# Bounded report questions

AI questions now have independent admission limits and run in killable worker processes. Reviews keep their existing queue; question traffic cannot start unlimited model calls in HTTP threads. Login and report ownership checks still happen before admission. Offline (`provider: none`) questions do not consume model capacity or daily model-call quota.

| Setting | Default | Meaning |
| --- | --- | --- |
| `REPO_REVIEW_QUESTION_WORKERS` | 2 | Concurrent AI questions across the admission scope |
| `REPO_REVIEW_QUESTION_PER_USER_LIMIT` | 1 | Concurrent questions per signed-in user |
| `REPO_REVIEW_QUESTION_RATE_PER_MINUTE` | 10 | Admissions per user in a rolling minute, including completed calls |
| `REPO_REVIEW_QUESTION_TIMEOUT` | 45 | Total isolated execution deadline in seconds, including worker startup |

Capacity/rate exhaustion returns HTTP 429 before a model call. Questions and reviews continue to share the daily admission quota. Capacity is released in a `finally` block on success, provider failure, quota rejection or timeout. The process supervisor kills the worker at its execution deadline; a timeout returns HTTP 504. Browser question requests allow up to 120 seconds for admission, execution and response delivery; configure server deadlines with that in mind.

With the memory job store, limits are per application instance: use one API process for that deployment mode. With the Supabase job store, `20261020_question_capacity.sql` makes capacity and rate counters shared across API processes. Deploy that migration after existing migrations **before** deploying the new backend. The service role alone can acquire/release leases; clients cannot inspect or mutate the lease table. No new RPC means admission fails closed with a storage error.

A lease expires after the execution deadline plus 30 seconds. Process-group termination and the worker's own alarm bound execution if the API process crashes. A failed release cannot permanently retain capacity. Admission sweeps expired rate records; no question text or report contents are stored in this table. Keep the configured limits consistent across API replicas. The Windows fallback cannot promise POSIX process-group behavior.
