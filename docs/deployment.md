# Deployment Guide

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

REPO_REVIEW_ALLOW_LOCAL_TARGETS=false
REPO_REVIEW_RATE_LIMIT_PER_MINUTE=30
REPO_REVIEW_MAX_FILES_LIMIT=1000
REPO_REVIEW_MAX_FILE_SIZE_LIMIT=1000000
```

Do not commit `.env`.

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
