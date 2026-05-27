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
- Dockerfile and Docker Compose workflow.
- Optional FastAPI API and minimal web UI.
- Optional MCP server exposing repository review tools.

## Resume Summary

Built a hybrid AI repository review agent that combines deterministic static analysis, a custom tool-calling agent loop, OpenAI function calling, optional LLM synthesis, GitHub workflow integration, Dockerized execution, a FastAPI interface, and MCP tools for AI coding assistant integration.

## Remaining Nice-to-Haves

- Capture a real AI-generated demo report after configuring `OPENAI_API_KEY` or pulling an Ollama model.
- Add dependency vulnerability checks.
- Add GitHub Actions PR annotation mode.
- Add screenshots of the web UI and sample report.
