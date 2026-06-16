# Implementation Checklist

This project is intended to demonstrate a lightweight but realistic AI agent engineering workflow.

## Completed

- Project skeleton with README, MIT license, packaging metadata, tests, and CI.
- Repository scanner for source files, dependency manifests, docs, tests, and CI.
- Deterministic analyzer for project hygiene, delivery, testing, and security findings.
- Markdown and JSON report generation.
- Optional OpenAI and Ollama AI review synthesis.
- Custom `RepoReviewAgent` with traceable `Thought -> Action/tool -> Observation` steps.
- OpenAI Responses API function-calling agent where the model calls repository tools.
- GitHub issue draft generation, issue creation, and PR comment support.
- GitHub Actions PR bot for base-vs-head review, sticky new-risk PR comments, scheduled main scans, and high-risk CI blocking.
- Dockerfile and Docker Compose workflow.
- Optional FastAPI API and minimal web UI.
- Optional MCP server exposing repository review tools.
- Real AI demo report generated with local Ollama `llama3.2`.
- Evaluation fixtures and golden report tests for representative healthy and risky repositories.
- Additional deterministic rules for floating dependency versions, broad GitHub Actions permissions, and unpinned Docker base images.
- Shared prompt-tuning guidance and few-shot JSON examples for AI review synthesis and ChatGPT agent output.
- Supabase/Postgres history schema plus CLI persistence for review runs, health scores, and new/existing/resolved finding diffs.
- Supabase email/password login for the web UI, expiring-session refresh, backend JWT verification, and per-user authenticated history persistence.
- Supabase schema migrations, per-user repository uniqueness, owner cascade cleanup, and owner history query indexes.
- Signed-in project detail view with latest score, top risks, AI summary, issue backlog, historical scans, and score trend.
- In-memory asynchronous web review jobs with submit/status endpoints and frontend polling.
- Backend History API for authenticated repository lists and project details, replacing direct browser-to-Supabase history reads.
- Supabase-backed demo readiness command, schema verification SQL, and browser demo runbook.
- Hosted demo deployment path with Render backend blueprint, GitHub Pages frontend variables, CORS support, and live demo README guidance.

## Resume Summary

Built a hybrid AI repository review agent that combines deterministic static analysis, a custom tool-calling agent loop, OpenAI function calling, optional LLM synthesis, GitHub workflow integration, Dockerized execution, a FastAPI interface, and MCP tools for AI coding assistant integration.

## Remaining Nice-to-Haves

- Add dependency vulnerability checks.
- Web review jobs can persist to Supabase with `REPO_REVIEW_JOB_STORE=supabase`; use Redis/RQ or Celery later if the app needs dedicated workers, retries, or multi-instance queue coordination.
- Add line-level GitHub Checks annotations for findings with precise file paths.
- Add screenshots of the web UI and sample report.
- Add screenshots of the hosted web UI after the public demo is deployed.
- Expand the evaluation fixture set across more stacks such as Django, Next.js, Go services, and monorepos.
