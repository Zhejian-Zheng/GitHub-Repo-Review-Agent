# GitHub Repo Review Agent

Put in a repository. Get back a structured engineering review.

GitHub Repo Review Agent is a lightweight developer tool that turns a local repository or public GitHub URL into an architecture summary, project health report, and actionable issue backlog. It combines deterministic repository analysis with an optional AI synthesis layer, so the core review still works without an LLM API key.

The product is designed for portfolio reviews, project handoffs, technical due diligence, and fast first-pass audits of unfamiliar codebases.

## Product Snapshot

- **Input**: local repository path or public GitHub repository URL.
- **Output**: Markdown report, structured JSON, optional GitHub issue drafts, and optional PR comment.
- **Review depth**: source structure, dependency manifests, tests, CI, docs, Docker hardening, secret-like values, framework signals, and evidence file paths.
- **AI layer**: optional OpenAI, OpenRouter, or local Ollama synthesis with stable JSON sections.
- **Interfaces**: CLI, React web UI, FastAPI endpoint, Docker workflow, GitHub integration, and MCP server.

## Product Capabilities

- Scans local repositories or public GitHub URLs.
- Detects source languages, dependency manifests, test files, docs, CI workflows, and common framework signals.
- Flags project hygiene risks with evidence file paths, including missing tests, shallow test breadth, missing CI, weak CI checks, missing lockfiles, incomplete README guidance, Docker runtime hardening gaps, and possible hard-coded secrets.
- Generates a Markdown review report and optional JSON output.
- Supports English and Simplified Chinese report output.
- Includes a custom `RepoReviewAgent` that uses a traceable tool-calling loop.
- Includes an OpenAI Responses API function-calling agent where the model calls repository tools.
- Adds an optional AI review section through OpenAI, OpenRouter, or local Ollama.
- Creates GitHub issue drafts, can create GitHub issues, and can post pull request comments.
- Provides optional Docker, FastAPI, and MCP server entry points.
- Includes production deployment examples for Docker Compose, Nginx, HTTPS, and public demo controls.
- Includes unit tests and a GitHub Actions workflow.

## What the Report Gives You

- **Executive summary**: a quick read on the repository's primary language, dependency surface, tests, CI, and framework signals.
- **Architecture signals**: detected frameworks and tooling with file-backed evidence.
- **Findings**: prioritized risks with severity, category, evidence text, evidence file paths, and concrete recommendations.
- **Agent trace**: visible tool-calling steps for agent runs, including scan, inspect, analyze, and AI synthesis stages.
- **AI review**: optional structured sections for architecture summary, top risks, project highlights, and next steps.
- **Issue backlog**: ready-to-use issue suggestions for actionable findings.

## How It Works

1. The scanner maps files, languages, dependency manifests, docs, tests, CI files, and operational config.
2. The analyzer applies deterministic review rules and attaches evidence file paths to every finding.
3. The agent can inspect key files and preserve a trace of its tool calls.
4. The optional AI layer receives the structured scan result and returns stable JSON sections.
5. The renderer produces Markdown, JSON, web UI cards, GitHub issue drafts, and MCP responses.

## Architecture

```mermaid
flowchart LR
    User["User"] --> UI["React + Tailwind Web UI"]
    UI --> API["FastAPI /review API"]
    API --> Agent["RepoReviewAgent"]
    Agent --> Scan["scan_repository tool"]
    Agent --> Inspect["inspect_file tool"]
    Agent --> Analyze["analyze_repository tool"]
    Analyze --> Report["Markdown + JSON report"]
    Agent --> LLM["AI review synthesis"]
    LLM --> Providers["OpenAI / OpenRouter / Ollama"]
    API --> Report
    Report --> UI
    MCP["MCP Server"] --> Agent
    GitHub["GitHub Issues / PR Comments"] --> Report
```

The web UI includes a static demo mode, so the frontend can be shown on static hosting such as GitHub Pages even when the FastAPI backend is not deployed.

## Quick Start

```bash
git clone https://github.com/Zhejian-Zheng/GitHub-Repo-Review-Agent.git
cd GitHub-Repo-Review-Agent
python -m pip install -e .
```

Analyze the current repository:

```bash
repo-review . --output review-report.md --json review-report.json
```

Run without installing the package:

```bash
PYTHONPATH=src python -m repo_review_agent.cli . --output review-report.md
```

Run the custom agent loop:

```bash
PYTHONPATH=src python -m repo_review_agent.cli . --agent --output review-report.md --json review-report.json
```

The agent records each step in the generated report:

```text
Thought -> Action/tool -> Observation
scan_repository -> inspect_file -> analyze_repository -> finalize_report
```

Run the OpenAI function-calling agent:

```bash
export OPENAI_API_KEY="your_api_key_here"
PYTHONPATH=src python -m repo_review_agent.cli . --function-calling --output review-report.md
```

Analyze another local repository:

```bash
repo-review ../some-project --output review-report.md
```

Analyze a GitHub repository:

```bash
repo-review https://github.com/owner/repo --output review-report.md
```

Generate a Simplified Chinese report:

```bash
repo-review . --agent --report-language zh-CN --output review-report.zh.md
```

Preview GitHub issues from findings:

```bash
repo-review https://github.com/owner/repo --agent --github-issues dry-run
```

Create GitHub issues:

```bash
export GITHUB_TOKEN="your_github_token"
repo-review https://github.com/owner/repo --agent --github-issues create
```

Preview a pull request comment:

```bash
repo-review https://github.com/owner/repo --agent --github-pr-comment 12
```

Post a pull request comment:

```bash
export GITHUB_TOKEN="your_github_token"
repo-review https://github.com/owner/repo --agent --github-pr-comment 12 --github-pr-comment-mode create
```

Enable the OpenAI AI layer:

```bash
export OPENAI_API_KEY="your_api_key_here"
repo-review . --ai-provider openai --output review-report.md
```

Run the custom agent with OpenAI synthesis:

```bash
repo-review . --agent --ai-provider openai --output review-report.md
```

Use a specific OpenAI model:

```bash
repo-review . --ai-provider openai --ai-model gpt-5-mini --output review-report.md
```

Enable OpenRouter:

```bash
export OPENROUTER_API_KEY="your_openrouter_key"
repo-review . --ai-provider openrouter --ai-model openrouter/auto --output review-report.md
```

Enable the local Ollama AI layer:

```bash
ollama pull llama3.2
repo-review . --ai-provider ollama --ai-model llama3.2 --output review-report.md
```

By default, AI provider errors are written into the report instead of failing the whole scan. Use `--fail-on-ai-error` when you want CI or automation to stop on model failures.

## Docker

Build and run the CLI against the current repository:

```bash
docker build -t repo-review-agent .
docker run --rm -v "$PWD:/workspace:ro" -v "$PWD/reports:/reports" repo-review-agent /workspace --agent --output /reports/review-report.md
```

Run the default compose review job:

```bash
docker compose up --build repo-review
```

Run the web UI:

```bash
docker compose --profile web up --build web
```

Then open `http://localhost:8000` and enter `/workspace` as the target when using Docker Compose.

Run the production-style web service locally:

```bash
cp .env.example .env
docker compose -f docker-compose.prod.yml up -d --build web
```

For VPS deployment with Nginx and HTTPS, see [Deployment Guide](docs/deployment.md).

## Web API

Install optional web dependencies:

```bash
python -m pip install -e ".[web]"
repo-review-web
```

The web UI is built with React, Vite, and Tailwind CSS. It lets users enter a GitHub repository URL, choose the report language, generate a Markdown report, then copy, download, or close the generated report.

For static hosting demos, use the `Demo` button in the frontend. It renders a built-in sample report without calling the backend, which is useful for GitHub Pages or portfolio previews.

## GitHub Pages Static Demo

This repository includes a GitHub Pages workflow that deploys the React frontend as a static portfolio demo. The static demo can show the built-in sample report through `Demo`, but live repository analysis still requires the FastAPI backend.

To enable it:

1. Push the repository to GitHub.
2. Open `Settings -> Pages`.
3. Set the source to `GitHub Actions`.
4. Run the `GitHub Pages Demo` workflow or push to `main`.

The workflow builds `frontend/dist` with the correct GitHub Pages base path.

Run the React frontend in development mode:

```bash
repo-review-web
cd frontend
npm install
npm run dev
```

Then open `http://localhost:5173`. Vite proxies `/review` to the FastAPI backend on `http://localhost:8000`.

Build the React frontend and serve it from FastAPI:

```bash
cd frontend
npm install
npm run build
cd ..
repo-review-web
```

Then open `http://localhost:8000`.

Review through the HTTP API:

```bash
curl -X POST http://localhost:8000/review \
  -H "Content-Type: application/json" \
  -d '{"target": ".", "mode": "agent", "ai_provider": "openrouter", "ai_model": "openrouter/auto", "report_language": "zh-CN"}'
```

For public demos, set `REPO_REVIEW_ALLOW_LOCAL_TARGETS=false` and `REPO_REVIEW_RATE_LIMIT_PER_MINUTE=10` so visitors can only review GitHub URLs and cannot spam the endpoint.

## MCP Server

Install optional MCP dependencies:

```bash
python -m pip install -e ".[mcp]"
repo-review-mcp
```

The MCP server exposes:

- `review_repository`
- `generate_issue_backlog`
- `summarize_architecture`

Run tests:

```bash
python -m unittest discover -s tests
```

## Product Demo

Generated report examples:

- [Agent report](docs/example-report.md)
- [AI demo report with Ollama](docs/ai-demo-report.md)

Each generated report includes:

- Executive summary
- Repository metrics
- Framework and tooling signals
- Agent Trace for tool-calling runs
- Optional AI Review output
- Findings with severity, evidence, evidence file paths, and recommendations
- GitHub issue backlog suggestions

The static frontend demo can be deployed to GitHub Pages and still show the full reporting experience through the built-in sample report. Live repository analysis requires the FastAPI backend.

## Project Structure

```text
src/repo_review_agent/
  agent.py      # Custom tool-calling agent orchestration layer
  analyzer.py   # Rule-based review logic
  cli.py        # Command-line interface
  function_agent.py # OpenAI function-calling agent
  github.py     # GitHub issues and PR comments
  i18n.py       # English and Simplified Chinese report localization
  llm.py        # Optional OpenAI, OpenRouter, and Ollama AI review layer
  mcp_server.py # MCP tools for AI coding assistants
  models.py     # Structured report data models
  report.py     # Markdown and JSON report rendering
  security.py   # Public web API safety controls
  scanner.py    # Repository scanning and file classification
  web.py        # FastAPI app and React static asset serving
tests/          # Unit tests
.github/        # CI workflow
deploy/         # Nginx and deployment examples
frontend/       # React + Tailwind CSS frontend
```

## Project Highlights

- **Offline-first review core**: the scanner and deterministic analyzer work without an API key, so the product can still generate useful reports in local, CI, or restricted environments.
- **Evidence-backed findings**: each finding includes evidence text and relevant file paths, making the report easier to verify and turn into engineering tasks.
- **Traceable agent workflow**: agent runs expose their tool calls, so users can see how the review moved from scan to inspection to final report.
- **Flexible AI synthesis**: OpenAI, OpenRouter, and Ollama can be used to add richer architecture and risk summaries without changing the deterministic review contract.
- **Multiple delivery surfaces**: the same report model powers the CLI, web UI, GitHub issue generation, PR comments, MCP tools, and API responses.

## Product Positioning

Short description:

```text
GitHub Repo Review Agent helps developers understand an unfamiliar repository quickly by combining file-backed static analysis, traceable agent steps, and optional AI synthesis into one shareable review report.
```

Strong use cases:

- Reviewing a project before a handoff or onboarding session.
- Creating a quick portfolio-quality explanation of what a repository does.
- Turning repository hygiene gaps into GitHub issue drafts.
- Comparing project readiness across tests, CI, docs, dependencies, and deployment signals.
- Giving AI coding assistants a structured repository review tool through MCP.

## Roadmap

- Add GitHub Actions PR annotation mode.
- Add richer repository dependency vulnerability checks.
- Add screenshots of the web UI and sample report.

## License

This project is licensed under the MIT License.
