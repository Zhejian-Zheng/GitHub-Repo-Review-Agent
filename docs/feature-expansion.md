# Review feature expansion

The CLI, shared runtime and web application now cover the requested feature set. Setup references:

| Capability | Interface |
| --- | --- |
| Unified rule/AI findings and owner feedback | Report JSON, history API/UI, issue drafts and PR gating; [lifecycle guide](finding-lifecycle.md) |
| Quality evaluations and Langfuse scores | `repo-review-evaluate`; [evaluation guide](evaluation.md) |
| Known dependency advisories | `--vulnerability-scan`, API/UI checkbox; [supported formats and limits](vulnerabilities.md) |
| Incremental inspection and PR annotations | `repo-review --changed-files-json pr-files.json`; `repo-review-pr-bot --changed-files-json ... --annotation-mode dry-run`; [PR guide](finding-lifecycle.md) |
| Cancel a submitted job | Signed-in owner: `POST /review/jobs/{job_id}/cancel`; UI Cancel review |
| Per-user daily admissions | `REPO_REVIEW_DAILY_JOB_LIMIT`, default 100 UTC-day admissions; reviews and AI questions share this quota |
| Per-review model budget | `--ai-token-budget`, API `ai_token_budget`, UI budget field |
| Project policy | Root `.repo-review.json` or CLI `--config`; [configuration guide](project-config.md) |
| Report questions | `POST /review/questions`, UI question form |

Model budgets use conservative reservations for serialized input and configured output allowance before each call. They are not provider billing guarantees. Providers can tokenize differently, and missing actual usage is reported as unavailable. Format repair and agent tool rounds share the same budget. Budget failure retains the deterministic report in normal review mode; strict modes raise. Daily quotas count admissions, including cancelled jobs and admitted AI questions that later fail; they are not monetary balances. Memory quotas reset after application restart; durable quotas use the database.

Cancelling a queued job prevents its execution. Cancelling a running job persists a terminal state, clears its lease and signals the isolated process group through a monitor. Completion/error writes cannot replace cancelled state. A database outage can delay observing durable cancellation; the independent total deadline still applies. Guest visitors can stop tracking; cancellation requires a verifiable signed-in owner. Cancelled work may already have saved history before cancellation arrives, so cancellation is not a rollback of all side effects.

Report questions can use a completed owned `job_id` or a bounded report object. AI questions require authentication and share the daily quota. Reports and questions are untrusted data, and returned citation IDs must exist in the supplied evidence collection. This checks citation membership, not the truth of a client-supplied report or the model's interpretation. Provider `none` returns relevant report excerpts without a model call. No question tool reopens the repository or verifies fixes.

For incremental review, changed files are prioritized in the bounded content sample and initial inspection; repository-wide inventory/hygiene signals remain available. Prompt context includes filenames and validated added-line ranges, never raw patch text. This prioritizes attention; it does not guarantee inspection of every changed file or perform dependency-impact analysis. Reports generated through the shared service record the current commit and whether the working tree is dirty. PR annotation creation rejects known dirty or mismatched source metadata.

Apply, in order, the existing migrations, `20261004_review_job_leases.sql`, `20261005_finding_lifecycle.sql`, `20261005_job_controls.sql`, and `20261006_atomic_history.sql` before deploying this backend. See [atomic history](atomic-history.md) for the transaction, retry and local database test workflow. The job-controls migration adds cancelled status, atomic daily admissions and question admission RPCs. The atomic-history migration adds transactional history saves and durable job completion. These changes require staging database verification. No live migration, GitHub Check creation or deployment is performed by local tests.
