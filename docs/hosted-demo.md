# Hosted Demo: Render + GitHub Pages

This is the recommended lightweight hosted demo setup:

```text
GitHub Pages static frontend -> Render FastAPI backend -> Supabase Auth + history tables
```

The frontend can always show the built-in sample report through `Demo`. Signed-in users can run live repository reviews when the Render backend and Supabase settings are configured.

## 1. Prepare Supabase

1. Create a Supabase project.
2. Run `supabase/schema.sql` in the SQL Editor. For an existing project, run the migrations in `supabase/migrations`, including `003_review_jobs.sql`.
3. Run `supabase/verify_history_schema.sql`; every row should return `status = pass`.
4. In Auth settings, enable Email provider.
5. Open **Authentication -> URL Configuration**.
6. Set **Site URL** to your deployed frontend:

```text
https://zhejian-zheng.github.io/GitHub-Repo-Review-Agent/
```

7. Add redirect URLs:

```text
http://localhost:5173/
http://localhost:5173/**
https://zhejian-zheng.github.io/GitHub-Repo-Review-Agent/
https://zhejian-zheng.github.io/GitHub-Repo-Review-Agent/**
```

For a fork, replace the GitHub Pages URL with:

```text
https://<github-user>.github.io/<repo-name>/
```

## 2. Deploy the Backend on Render

The repository includes `render.yaml` and `deploy/render.Dockerfile`.

In Render:

1. Choose **New -> Blueprint**.
2. Connect this GitHub repository.
3. Render reads `render.yaml` and creates `github-repo-review-agent-api`.
4. Fill the prompted environment variables:

```text
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_public_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
REPO_REVIEW_CORS_ORIGINS=https://zhejian-zheng.github.io
REPO_REVIEW_JOB_STORE=supabase
OPENROUTER_API_KEY=optional_openrouter_key
OPENAI_API_KEY=optional_openai_key
```

Use only the origin for `REPO_REVIEW_CORS_ORIGINS`, not the full GitHub Pages path. For a fork, use `https://<github-user>.github.io`.

After deploy, copy the Render service URL, for example:

```text
https://github-repo-review-agent-api.onrender.com
```

Run the backend readiness check locally with the same environment values:

```bash
repo-review-demo-check
```

## 3. Deploy the Frontend on GitHub Pages

In GitHub:

1. Open `Settings -> Pages`.
2. Set source to **GitHub Actions**.
3. Open `Settings -> Secrets and variables -> Actions -> Variables`.
4. Add repository variables:

```text
REPO_REVIEW_API_BASE_URL=https://github-repo-review-agent-api.onrender.com
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your_public_anon_key
VITE_AUTH_REDIRECT_URL=https://zhejian-zheng.github.io/GitHub-Repo-Review-Agent/
```

5. Run the `GitHub Pages Demo` workflow or push to `main`.

The workflow injects those values into the Vite build. The deployed frontend URL for this repository is:

```text
https://zhejian-zheng.github.io/GitHub-Repo-Review-Agent/
```

## 4. Acceptance Test

1. Open the GitHub Pages URL.
2. Click `Continue as guest`.
3. Click `Demo`; a sample report should render without a backend account.
4. Return to sign-in, then sign up or sign in with Supabase email/password.
5. Submit a public GitHub repository URL.
6. Confirm the job completes and the report renders.
7. Confirm the project appears in authenticated history.
8. Open the project detail view and confirm score, findings, run history, and trend data appear.

## Demo Account

The safest public setup is self-service Supabase email/password sign-up plus the built-in `Demo` button. If you want a shared test account for portfolio reviewers, create it in Supabase Auth and share it outside the repository. Do not commit test credentials.
