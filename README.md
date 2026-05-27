# GitHub Repo Review Agent

A lightweight repository review agent that analyzes project structure, dependency files, source code, tests, CI configuration, and security hygiene to generate architecture summaries, risk reports, and actionable GitHub issue suggestions.

The current MVP is intentionally small and reproducible: it runs without an LLM API key, produces structured JSON, and renders a Markdown report. That gives the project a reliable engineering core before adding optional OpenAI, Ollama, or LangGraph-based reasoning.

## Features

- Scans local repositories or public GitHub URLs.
- Detects source languages, dependency manifests, test files, docs, CI workflows, and common framework signals.
- Flags project hygiene risks such as missing tests, missing CI, missing license, missing dependency manifests, and possible hard-coded secrets.
- Generates a Markdown review report and optional JSON output.
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

Analyze another local repository:

```bash
repo-review ../some-project --output review-report.md
```

Analyze a GitHub repository:

```bash
repo-review https://github.com/owner/repo --output review-report.md
```

Run tests:

```bash
python -m unittest discover -s tests
```

## Example Output

The generated report includes:

- Executive summary
- Repository metrics
- Framework and tooling signals
- Findings with severity, evidence, and recommendations
- GitHub issue backlog suggestions

## Project Structure

```text
src/repo_review_agent/
  analyzer.py   # Rule-based review logic
  cli.py        # Command-line interface
  models.py     # Structured report data models
  report.py     # Markdown and JSON report rendering
  scanner.py    # Repository scanning and file classification
tests/          # Unit tests
.github/        # CI workflow
```

## Resume Talking Points

- Built a lightweight code review agent with structured outputs and deterministic analysis.
- Implemented repository scanning, framework detection, risk classification, and report generation.
- Added security checks for secret-like values and project hygiene checks for tests, CI, dependency manifests, and licensing.
- Designed the project so an LLM provider can be added later without making the base tool dependent on paid API keys.

## Roadmap

- Add optional LLM summaries through OpenAI or Ollama.
- Add GitHub issue creation with a dry-run mode.
- Add dependency vulnerability checks.
- Add pull request comment mode for GitHub Actions.
- Add a small FastAPI service and web UI.

## License

This project is licensed under the MIT License.
