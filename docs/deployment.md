# Deployment Guide

## Recommended Hosted Demo

For a lightweight public portfolio demo, use:

```text
GitHub Pages static frontend -> Render FastAPI backend -> Supabase Auth + history tables
```

This repository includes:

- `render.yaml` for a Render Blueprint web service.
- `deploy/render.Dockerfile` for the FastAPI backend container.
- `.github/workflows/pages.yml` for the GitHub Pages frontend.
- `frontend/.env.production.example` for static-hosting environment variables.

Follow [Hosted Demo: Render + GitHub Pages](hosted-demo.md) for the full setup.

Key production values:

```bash
REPO_REVIEW_ALLOW_LOCAL_TARGETS=false
REPO_REVIEW_REQUIRE_AUTH=true
REPO_REVIEW_CORS_ORIGINS=https://zhejian-zheng.github.io
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_public_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

For GitHub Pages repository variables:

```text
REPO_REVIEW_API_BASE_URL=https://github-repo-review-agent-api.onrender.com
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your_public_anon_key
```

## VPS Deployment

This guide describes a small production-style deployment for the web UI:

```text
Browser -> Nginx HTTPS -> FastAPI app on Docker -> OpenRouter/OpenAI/Ollama
```

The recommended target for a portfolio demo is a Hong Kong, Singapore, Japan, or Korea VPS running Ubuntu.

## 1. Prepare the Server

Install Docker, Docker Compose, Nginx, and Certbot:

```bash
apt update && apt upgrade -y
apt install -y git curl nginx certbot python3-certbot-nginx
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin
```

Open ports `22`, `80`, and `443` in your cloud firewall.

## 2. Clone the Project

```bash
cd /opt
git clone https://github.com/Zhejian-Zheng/GitHub-Repo-Review-Agent.git
cd GitHub-Repo-Review-Agent
```

## 3. Configure Environment Variables

Create `.env` from the example:

```bash
cp .env.example .env
nano .env
```

For a public demo, use values like:

```bash
OPENROUTER_API_KEY=your_new_openrouter_key
OPENROUTER_MODEL=openrouter/auto
OPENROUTER_APP_TITLE=GitHub Repo Review Agent

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_public_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your_public_anon_key

REPO_REVIEW_REQUIRE_AUTH=true
REPO_REVIEW_ALLOW_LOCAL_TARGETS=false
REPO_REVIEW_RATE_LIMIT_PER_MINUTE=30
REPO_REVIEW_MAX_FILES_LIMIT=1000
REPO_REVIEW_MAX_FILE_SIZE_LIMIT=1000000
```

Do not commit `.env`.

Before sharing the demo, run:

```bash
repo-review-demo-check
```

If this reports a Supabase schema failure, apply `supabase/schema.sql` or the latest migration, then run `supabase/verify_history_schema.sql` in the Supabase SQL Editor.

## 4. Run the App

```bash
docker compose -f docker-compose.prod.yml up -d --build web
docker compose -f docker-compose.prod.yml logs -f web
```

The container listens on `127.0.0.1:8000`, so it is reachable only through Nginx.

## 5. Configure Nginx

Copy the example config:

```bash
cp deploy/nginx.conf.example /etc/nginx/sites-available/repo-review
nano /etc/nginx/sites-available/repo-review
```

Replace `repo-review.example.com` with your domain, then enable it:

```bash
ln -s /etc/nginx/sites-available/repo-review /etc/nginx/sites-enabled/repo-review
nginx -t
systemctl reload nginx
```

## 6. Enable HTTPS

```bash
certbot --nginx -d repo-review.example.com
```

Then open:

```text
https://repo-review.example.com
```

## 7. Update the Deployment

```bash
cd /opt/GitHub-Repo-Review-Agent
git pull
docker compose -f docker-compose.prod.yml up -d --build web
```

## Public Demo Safety

For public demos, keep these controls enabled:

- `REPO_REVIEW_ALLOW_LOCAL_TARGETS=false` so visitors can only review GitHub URLs.
- `REPO_REVIEW_RATE_LIMIT_PER_MINUTE=30` or lower to reduce accidental abuse.
- Keep API keys only in `.env` on the server.
- Prefer a low-cost provider model such as `openrouter/auto` or a capped OpenRouter model.

If you want a private demo, set `REPO_REVIEW_API_TOKEN` and call the API with:

```bash
curl -H "Authorization: Bearer your_token" https://repo-review.example.com/review
```

## LangChain provider dependencies

The application uses LangChain 1.x and LangGraph 1.x. Both Docker images install the `all` extra, including OpenAI/OpenRouter, Anthropic and Ollama integrations. For a manual deployment install `python -m pip install -e ".[web,openai]"` or `.[all]` before enabling a provider. Rules-only runs still work without model credentials. Agent mode requires a model that supports tools; provider failures appear in the AI status while the baseline report remains available.


## Bounded jobs and recovery

Apply `supabase/migrations/20261004_review_job_leases.sql` **before deploying this backend** to an existing Supabase project. This migration adds atomic admission, claims, leases and fenced completion. Without Supabase, the queue is bounded but jobs do not survive a process restart.

The backend checks queued and expired leases every two seconds. A crashed job can be retried up to three times. Execution is at least once: a crash after history persistence and before job completion can produce duplicate history entries. Apply the migration in a staging database and verify two workers cannot claim the same lease before production rollout; local tests mock the database protocol.

| Variable | Default | Meaning |
| --- | --- | --- |
| `REPO_REVIEW_JOB_MAX_PENDING` | `20` | Pending job admission limit |
| `REPO_REVIEW_JOB_PER_USER_LIMIT` | `2` | Active jobs per user; anonymous requests share a bucket |
| `REPO_REVIEW_JOB_TIMEOUT` | `600` | Total execution deadline in seconds |
| `REPO_REVIEW_CLONE_TIMEOUT` | `120` | Git clone deadline in seconds |
| `REPO_REVIEW_JOB_RESULT_TTL` | `86400` | Job result retention in seconds |

Review work runs in a subprocess. On POSIX systems the deadline kills the process group, including Git and linter children. Worker count remains per application instance; database admission and user quotas are shared. The UI shows actual queued, cloning, analysis and AI phases. Stopping tracking cancels browser polling; it does not cancel a submitted backend job. A page reload can resume tracking without submitting again.

Optional Langfuse tracing setup is documented in [Langfuse](langfuse.md).
