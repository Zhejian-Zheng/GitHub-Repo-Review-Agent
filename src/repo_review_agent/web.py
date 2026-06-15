from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from .agent import RepoReviewAgent
from .analyzer import analyze_repository
from .auth import AuthError, AuthUser, bearer_token_from_headers, get_supabase_user
from .cli import resolve_target
from .function_agent import OpenAIFunctionCallingAgent
from .i18n import localize_report
from .history import HistoryStoreError, SupabaseHistoryStore
from .llm import AIProviderError, add_ai_review, attach_ai_error
from .report import render_markdown
from .security import (
    InMemoryRateLimiter,
    bool_from_env,
    client_identifier,
    int_from_env,
    request_token_matches,
    validate_target_policy,
)

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request
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
WEB_MAX_FILES_LIMIT = int_from_env("REPO_REVIEW_MAX_FILES_LIMIT", 1_000, minimum=1)
WEB_MAX_FILE_SIZE_LIMIT = int_from_env(
    "REPO_REVIEW_MAX_FILE_SIZE_LIMIT",
    1_000_000,
    minimum=1_024,
)
WEB_RATE_LIMITER = InMemoryRateLimiter(
    limit_per_minute=int_from_env("REPO_REVIEW_RATE_LIMIT_PER_MINUTE", 30, minimum=0)
)

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
    max_files: int = Field(500, ge=1, le=WEB_MAX_FILES_LIMIT)
    max_file_size: int = Field(512_000, ge=1_024, le=WEB_MAX_FILE_SIZE_LIMIT)
    save_history: bool = False
    history_repo_url: str | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="GitHub Repo Review Agent", version="0.1.0")

    @app.get("/auth/me")
    def auth_me(http_request: Request) -> dict:
        user = authenticated_user_from_request(http_request, required=True)
        return {"user": user.to_dict()}

    @app.post("/review")
    def review_repository(http_request: Request, request: ReviewRequest) -> dict:
        user = authenticated_user_from_request(http_request)
        enforce_public_api_controls(http_request, request.target)

        try:
            with resolve_target(request.target) as repo_path:
                report = run_review_for_path(request, repo_path)
        except (AIProviderError, RuntimeError, SystemExit) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        history_result = None
        if request.save_history:
            if user is None:
                raise HTTPException(status_code=401, detail="Sign in before saving review history.")
            try:
                history_store = SupabaseHistoryStore.from_env()
                history_result = history_store.save_report(
                    report=report,
                    repo_url=request.history_repo_url or request.target,
                    report_markdown=render_markdown(report, language=request.report_language),
                    owner_id=user.id,
                )
            except HistoryStoreError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        report = localize_report(report, request.report_language)
        response = {
            "markdown": render_markdown(report, language=request.report_language),
            "report": report.to_dict(),
        }
        if history_result:
            response["history"] = history_result.to_dict()
        return response

    if FRONTEND_ASSETS.exists():
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_ASSETS)), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def index():
        if FRONTEND_INDEX.exists():
            return FileResponse(FRONTEND_INDEX)
        return HTMLResponse(FALLBACK_HTML)

    return app


def authenticated_user_from_request(http_request: Request, *, required: bool | None = None) -> AuthUser | None:
    if required is None:
        required = bool_from_env("REPO_REVIEW_REQUIRE_AUTH", False)

    token = bearer_token_from_headers(http_request.headers)
    if not token:
        if required:
            raise HTTPException(status_code=401, detail="Sign in is required.")
        return None

    try:
        return get_supabase_user(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def enforce_public_api_controls(http_request: Request, target: str) -> None:
    expected_token = os.environ.get("REPO_REVIEW_API_TOKEN")
    if not request_token_matches(http_request.headers, expected_token):
        raise HTTPException(status_code=401, detail="Invalid or missing API token.")

    client_id = client_identifier(
        http_request.headers,
        http_request.client.host if http_request.client else None,
    )
    if not WEB_RATE_LIMITER.allow(client_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    try:
        validate_target_policy(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
