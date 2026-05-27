from __future__ import annotations

from pathlib import Path
from typing import Literal

from .agent import RepoReviewAgent
from .analyzer import analyze_repository
from .cli import resolve_target
from .function_agent import OpenAIFunctionCallingAgent
from .llm import AIProviderError, add_ai_review, attach_ai_error
from .report import render_markdown

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised only when optional deps are missing.
    raise RuntimeError(
        "Web dependencies are not installed. Run `python -m pip install -e .[web]`."
    ) from exc


class ReviewRequest(BaseModel):
    target: str = Field(..., description="Local repository path or GitHub URL.")
    mode: Literal["direct", "agent", "function-calling"] = "agent"
    ai_provider: Literal["none", "openai", "ollama"] = "none"
    ai_model: str | None = None
    max_files: int = 500
    max_file_size: int = 512_000


def create_app() -> FastAPI:
    app = FastAPI(title="GitHub Repo Review Agent", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.post("/review")
    def review_repository(request: ReviewRequest) -> dict:
        try:
            with resolve_target(request.target) as repo_path:
                report = run_review_for_path(request, repo_path)
        except (AIProviderError, RuntimeError, SystemExit) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "markdown": render_markdown(report),
            "report": report.to_dict(),
        }

    return app


def run_review_for_path(request: ReviewRequest, repo_path: Path):
    if request.mode == "function-calling":
        return OpenAIFunctionCallingAgent(
            model=request.ai_model,
            max_files=request.max_files,
            max_file_size=request.max_file_size,
        ).run(repo_path)

    if request.mode == "agent":
        return RepoReviewAgent(
            max_files=request.max_files,
            max_file_size=request.max_file_size,
            ai_provider=request.ai_provider,
            ai_model=request.ai_model,
        ).run(repo_path)

    report = analyze_repository(
        repo_path,
        max_files=request.max_files,
        max_file_size=request.max_file_size,
    )
    if request.ai_provider != "none":
        try:
            report = add_ai_review(
                report,
                provider=request.ai_provider,
                model=request.ai_model,
            )
        except AIProviderError as exc:
            report = attach_ai_error(
                report,
                provider=request.ai_provider,
                model=request.ai_model,
                error=str(exc),
            )
    return report


def main() -> None:
    uvicorn.run("repo_review_agent.web:create_app", factory=True, host="0.0.0.0", port=8000)


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GitHub Repo Review Agent</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f5f7fb; color: #172033; }
    main { max-width: 1120px; margin: 0 auto; padding: 32px 20px; display: grid; grid-template-columns: 360px 1fr; gap: 24px; }
    h1 { font-size: 26px; margin: 0 0 18px; letter-spacing: 0; }
    label { display: block; font-size: 13px; font-weight: 650; margin: 14px 0 6px; }
    input, select, button, textarea { width: 100%; box-sizing: border-box; border: 1px solid #c9d3e1; border-radius: 6px; padding: 10px 11px; font: inherit; background: white; color: #172033; }
    button { margin-top: 16px; background: #1f6feb; color: white; border-color: #1f6feb; font-weight: 700; cursor: pointer; }
    button:disabled { opacity: .65; cursor: wait; }
    section { background: white; border: 1px solid #d9e1ec; border-radius: 8px; padding: 18px; }
    pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.45; }
    .status { min-height: 22px; margin-top: 12px; font-size: 13px; color: #4f5f76; }
    @media (max-width: 860px) { main { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main>
    <section>
      <h1>Repo Review Agent</h1>
      <form id="review-form">
        <label for="target">Repository</label>
        <input id="target" name="target" value="." placeholder="Local path or GitHub URL" />

        <label for="mode">Mode</label>
        <select id="mode" name="mode">
          <option value="agent">Custom Agent</option>
          <option value="direct">Direct Analysis</option>
          <option value="function-calling">OpenAI Function Calling</option>
        </select>

        <label for="ai_provider">AI Provider</label>
        <select id="ai_provider" name="ai_provider">
          <option value="none">None</option>
          <option value="openai">OpenAI</option>
          <option value="ollama">Ollama</option>
        </select>

        <label for="ai_model">Model</label>
        <input id="ai_model" name="ai_model" placeholder="gpt-5-mini or llama3.2" />

        <button id="submit" type="submit">Run Review</button>
        <div class="status" id="status"></div>
      </form>
    </section>
    <section>
      <pre id="output">Run a review to see the Markdown report here.</pre>
    </section>
  </main>
  <script>
    const form = document.getElementById("review-form");
    const output = document.getElementById("output");
    const status = document.getElementById("status");
    const button = document.getElementById("submit");

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      button.disabled = true;
      status.textContent = "Running review...";
      output.textContent = "";
      const payload = Object.fromEntries(new FormData(form).entries());
      if (!payload.ai_model) payload.ai_model = null;
      try {
        const response = await fetch("/review", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Review failed");
        output.textContent = data.markdown;
        status.textContent = "Review complete.";
      } catch (error) {
        output.textContent = String(error);
        status.textContent = "Review failed.";
      } finally {
        button.disabled = false;
      }
    });
  </script>
</body>
</html>"""


app = create_app()
