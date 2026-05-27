# GitHub Repo Review Agent

A lightweight repository review agent that analyzes project structure, dependency files, source code, tests, CI configuration, and security hygiene to generate architecture summaries, risk reports, and actionable GitHub issue suggestions.

The MVP is intentionally small and reproducible: it runs without an LLM API key, produces structured JSON, and renders a Markdown report. When enabled, the optional AI layer turns the deterministic scan into a concise architecture summary, risk explanation, next-step plan, and resume-ready project pitch.

## Features

- Scans local repositories or public GitHub URLs.
- Detects source languages, dependency manifests, test files, docs, CI workflows, and common framework signals.
- Flags project hygiene risks such as missing tests, missing CI, missing license, missing dependency manifests, and possible hard-coded secrets.
- Generates a Markdown review report and optional JSON output.
- Includes a custom `RepoReviewAgent` that uses a traceable tool-calling loop.
- Adds an optional AI review section through OpenAI or local Ollama.
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

Analyze another local repository:

```bash
repo-review ../some-project --output review-report.md
```

Analyze a GitHub repository:

```bash
repo-review https://github.com/owner/repo --output review-report.md
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
  agent.py      # Custom tool-calling agent orchestration layer
  analyzer.py   # Rule-based review logic
  cli.py        # Command-line interface
  llm.py        # Optional OpenAI and Ollama AI review layer
  models.py     # Structured report data models
  report.py     # Markdown and JSON report rendering
  scanner.py    # Repository scanning and file classification
tests/          # Unit tests
.github/        # CI workflow
```

## Resume Talking Points

- Built a lightweight code review agent with structured outputs and deterministic analysis.
- Implemented a custom tool-calling agent loop for repository scanning, file inspection, risk classification, report generation, and optional LLM-based review synthesis.
- Added security checks for secret-like values and project hygiene checks for tests, CI, dependency manifests, and licensing.
- Designed a hybrid architecture that works offline by default and can use OpenAI or Ollama when model reasoning is available.

## Roadmap

- Add GitHub issue creation with a dry-run mode.
- Add dependency vulnerability checks.
- Add pull request comment mode for GitHub Actions.
- Add a small FastAPI service and web UI.

## License

This project is licensed under the MIT License.
