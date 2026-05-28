from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from .agent import RepoReviewAgent
from .analyzer import analyze_repository
from .cli import resolve_target
from .function_agent import OpenAIFunctionCallingAgent
from .i18n import localize_report
from .llm import AIProviderError, add_ai_review, attach_ai_error
from .report import render_markdown

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - optional dependency guard.
    raise RuntimeError(
        "Web dependencies are not installed. Run `python -m pip install -e .[web]`."
    ) from exc


FRONTEND_DIST = Path(
    os.environ.get(
        "REPO_REVIEW_FRONTEND_DIST",
        Path.cwd() / "frontend" / "dist",
    )
)
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
FRONTEND_ASSETS = FRONTEND_DIST / "assets"

FALLBACK_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GitHub Repo Review Agent</title>
</head>
<body>
  <main style="font-family: system-ui, sans-serif; max-width: 720px; margin: 48px auto; line-height: 1.5;">
    <h1>GitHub Repo Review Agent</h1>
    <p>The React frontend has not been built yet.</p>
    <pre>cd frontend
npm install
npm run build
cd ..
repo-review-web</pre>
  </main>
</body>
</html>"""


class ReviewRequest(BaseModel):
    target: str = Field(..., description="Local repository path or GitHub URL.")
    mode: Literal["direct", "agent", "function-calling"] = "agent"
    ai_provider: Literal["none", "openai", "openrouter", "ollama"] = "none"
    ai_model: str | None = None
    report_language: Literal["en", "zh-CN"] = "en"
    max_files: int = 500
    max_file_size: int = 512_000


def create_app() -> FastAPI:
    app = FastAPI(title="GitHub Repo Review Agent", version="0.1.0")

    @app.post("/review")
    def review_repository(request: ReviewRequest) -> dict:
        try:
            with resolve_target(request.target) as repo_path:
                report = run_review_for_path(request, repo_path)
        except (AIProviderError, RuntimeError, SystemExit) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        report = localize_report(report, request.report_language)
        return {
            "markdown": render_markdown(report, language=request.report_language),
            "report": report.to_dict(),
        }

    if FRONTEND_ASSETS.exists():
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_ASSETS)), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def index():
        if FRONTEND_INDEX.exists():
            return FileResponse(FRONTEND_INDEX)
        return HTMLResponse(FALLBACK_HTML)

    return app


def run_review_for_path(request: ReviewRequest, repo_path: Path):
    if request.mode == "function-calling":
        return OpenAIFunctionCallingAgent(
            model=request.ai_model,
            max_files=request.max_files,
            max_file_size=request.max_file_size,
            report_language=request.report_language,
        ).run(repo_path)

    if request.mode == "agent":
        return RepoReviewAgent(
            max_files=request.max_files,
            max_file_size=request.max_file_size,
            ai_provider=request.ai_provider,
            ai_model=request.ai_model,
            report_language=request.report_language,
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
                language=request.report_language,
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


app = create_app()
