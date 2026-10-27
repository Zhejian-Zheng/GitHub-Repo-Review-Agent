# Demo Runbook

Use this checklist when preparing a Supabase-backed portfolio or product demo. The recommended hosted path is Render for the FastAPI backend and GitHub Pages for the static frontend.

## 1. Apply the Database Schema

For both new and existing Supabase projects, apply **all** SQL files in
`supabase/migrations/` in filename order through
`20261023_inventory_rule_coverage.sql`. The initial migration bootstraps a new
project; later migrations add the required job, atomic-history and question RPCs.
`supabase/schema.sql` alone is a legacy bootstrap and cannot run the current backend.
See [atomic history](atomic-history.md) for local database verification.

Then run:

```text
supabase/verify_history_schema.sql
```

Every verification row should return `status = pass`.

## 2. Configure Auth

In Supabase Auth settings:

- Keep the Email provider enabled.
- Add the local frontend URL to allowed redirect URLs, for example `http://localhost:8000`.
- Add the Vite development URL, `http://localhost:5173`.
- Add the deployed frontend URL before sharing a public demo.

## 3. Configure Environment Variables

Set server-side values:

```bash
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_ANON_KEY="your_public_anon_key"
export SUPABASE_SERVICE_ROLE_KEY="your_service_role_key"
export REPO_REVIEW_REQUIRE_AUTH=true
export REPO_REVIEW_ALLOW_LOCAL_TARGETS=false
export REPO_REVIEW_CORS_ORIGINS="https://zhejian-zheng.github.io"
```

Set frontend build values:

```bash
export VITE_SUPABASE_URL="$SUPABASE_URL"
export VITE_SUPABASE_ANON_KEY="$SUPABASE_ANON_KEY"
export VITE_API_BASE_URL="https://github-repo-review-agent-api.onrender.com"
```

For private API clients, set `REPO_REVIEW_API_TOKEN` on the server and send it in
`X-Repo-Review-Token`. Do not embed a private token in `VITE_REPO_REVIEW_API_TOKEN`:
Vite build values are readable in the shipped browser bundle. A public browser demo
should require Supabase login (`REPO_REVIEW_REQUIRE_AUTH=true`); a bundled shared
token cannot restrict access to its users.

## 4. Run the Readiness Check

```bash
repo-review-demo-check
```

Use this local-only variant before credentials are available:

```bash
repo-review-demo-check --skip-supabase
```

Warnings are acceptable while iterating locally. Failures should be fixed before recording screenshots or sharing a demo link.

## 5. Build and Run the Web Demo

For the hosted demo, deploy the backend from `render.yaml`, then set these GitHub repository variables before running the `GitHub Pages Demo` workflow:

```text
REPO_REVIEW_API_BASE_URL=https://github-repo-review-agent-api.onrender.com
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your_public_anon_key
```

For a local demo:

```bash
cd frontend
npm install
npm run build
cd ..
repo-review-web
```

Open `http://localhost:8000`.

## 6. End-to-End Acceptance Flow

1. Sign up or sign in.
2. Submit a public GitHub URL, for example:

```text
https://github.com/Zhejian-Zheng/GitHub-Repo-Review-Agent
```

3. Enable history saving in the UI.
4. Wait for the job to complete.
5. Open the saved project detail view.
6. Confirm the page shows the latest score, top risks, historical runs, and trend data.
7. Run the same repository again and confirm the diff counts move from `new` toward `existing`.

## 7. Demo Assets to Capture

Capture these for the README or portfolio page:

- Signed-out landing or demo state.
- Signed-in review form.
- Completed review report.
- Project detail page with history and score trend.
- Supabase ERD or schema verification output.
