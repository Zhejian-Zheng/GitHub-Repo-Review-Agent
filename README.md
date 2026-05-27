# GitHub Repo Review Agent

A lightweight repository review agent that analyzes project structure, dependency files, source code, tests, CI configuration, and security hygiene to generate architecture summaries, risk reports, and actionable GitHub issue suggestions.

The MVP is intentionally small and reproducible: it runs without an LLM API key, produces structured JSON, and renders a Markdown report. When enabled, the optional AI layer turns the deterministic scan into a concise architecture summary, risk explanation, next-step plan, and resume-ready project pitch.

## Features

- Scans local repositories or public GitHub URLs.
- Detects source languages, dependency manifests, test files, docs, CI workflows, and common framework signals.
- Flags project hygiene risks such as missing tests, missing CI, missing license, missing dependency manifests, and possible hard-coded secrets.
- Generates a Markdown review report and optional JSON output.
- Includes a custom `RepoReviewAgent` that uses a traceable tool-calling loop.
- Includes an OpenAI Responses API function-calling agent where the model calls repository tools.
- Adds an optional AI review section through OpenAI or local Ollama.
- Creates GitHub issue drafts, can create GitHub issues, and can post pull request comments.
- Provides optional Docker, FastAPI, and MCP server entry points.
- Includes unit tests and a GitHub Actions workflow.

## Quick Start

```bash
git clone https://github.com/<your-username>/GitHub-Repo-Review-Agent.git
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

## Web API

Install optional web dependencies:

```bash
python -m pip install -e ".[web]"
repo-review-web
```

Review through the HTTP API:

```bash
curl -X POST http://localhost:8000/review \
  -H "Content-Type: application/json" \
  -d '{"target": ".", "mode": "agent", "ai_provider": "none"}'
```

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

## Example Output

The generated report includes:

- Executive summary
- Repository metrics
- Framework and tooling signals
- Agent Trace for tool-calling runs
- Optional AI Review output
- Findings with severity, evidence, and recommendations
- GitHub issue backlog suggestions

## Project Structure

```text
src/repo_review_agent/
  agent.py      # Custom tool-calling agent orchestration layer
  analyzer.py   # Rule-based review logic
  cli.py        # Command-line interface
  function_agent.py # OpenAI function-calling agent
  github.py     # GitHub issues and PR comments
  llm.py        # Optional OpenAI and Ollama AI review layer
  mcp_server.py # MCP tools for AI coding assistants
  models.py     # Structured report data models
  report.py     # Markdown and JSON report rendering
  scanner.py    # Repository scanning and file classification
  web.py        # FastAPI app and minimal web UI
tests/          # Unit tests
.github/        # CI workflow
```

## Resume Talking Points

- Built a lightweight code review agent with structured outputs and deterministic analysis.
- Implemented a custom tool-calling agent loop and an OpenAI function-calling agent for repository scanning, file inspection, risk classification, report generation, and optional LLM-based review synthesis.
- Added security checks for secret-like values and project hygiene checks for tests, CI, dependency manifests, and licensing.
- Integrated GitHub issue dry-runs, issue creation, PR comments, Docker, FastAPI, and MCP tools while keeping the base CLI offline-friendly.

## Roadmap

- Add GitHub Actions PR annotation mode.
- Add richer repository dependency vulnerability checks.
- Add screenshots and a captured real AI report after running with OpenAI or a local Ollama model.

## License

This project is licensed under the MIT License.
