from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from .agent import RepoReviewAgent
from .analyzer import analyze_repository
from .chatgpt_agent import ChatGPTReviewAgent
from .function_agent import OpenAIFunctionCallingAgent
from .github import (
    GitHubIntegrationError,
    apply_github_issue_mode,
    apply_github_pr_comment_mode,
    parse_github_repo,
)
from .history import HistoryStoreError, SupabaseHistoryStore
from .i18n import localize_report
from .llm import AIProviderError, add_ai_review, attach_ai_error
from .report import render_markdown, write_json, write_markdown


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    with resolve_target(args.target) as repo_path:
        if args.chatgpt_agent:
            agent = ChatGPTReviewAgent(
                model=args.ai_model,
                timeout=args.ai_timeout,
                max_output_tokens=args.ai_max_output_tokens,
                max_files=args.max_files,
                max_file_size=args.max_file_size,
                report_language=args.report_language,
            )
            try:
                report = agent.run(repo_path)
            except AIProviderError as exc:
                raise SystemExit(str(exc)) from exc
        elif args.function_calling:
            agent = OpenAIFunctionCallingAgent(
                model=args.ai_model,
                timeout=args.ai_timeout,
                max_output_tokens=args.ai_max_output_tokens,
                max_files=args.max_files,
                max_file_size=args.max_file_size,
                report_language=args.report_language,
            )
            try:
                report = agent.run(repo_path)
            except AIProviderError as exc:
                raise SystemExit(str(exc)) from exc
        elif args.agent:
            agent = RepoReviewAgent(
                max_files=args.max_files,
                max_file_size=args.max_file_size,
                ai_provider=args.ai_provider,
                ai_model=args.ai_model,
                ai_timeout=args.ai_timeout,
                ai_max_output_tokens=args.ai_max_output_tokens,
                ollama_url=args.ollama_url,
                fail_on_ai_error=args.fail_on_ai_error,
                report_language=args.report_language,
            )
            report = agent.run(repo_path)
        else:
            report = analyze_repository(
                repo_path,
                max_files=args.max_files,
                max_file_size=args.max_file_size,
            )
            if args.ai_provider != "none":
                try:
                    report = add_ai_review(
                        report,
                        provider=args.ai_provider,
                        model=args.ai_model,
                        language=args.report_language,
                        timeout=args.ai_timeout,
                        max_output_tokens=args.ai_max_output_tokens,
                        ollama_url=args.ollama_url,
                    )
                except AIProviderError as exc:
                    if args.fail_on_ai_error:
                        raise SystemExit(str(exc)) from exc
                    report = attach_ai_error(
                        report,
                        provider=args.ai_provider,
                        model=args.ai_model,
                        error=str(exc),
                    )

        history_result = None
        if args.save_history:
            try:
                history_store = SupabaseHistoryStore.from_env(
                    supabase_url=args.supabase_url,
                    service_key=args.supabase_service_key,
                    timeout=args.history_timeout,
                )
                history_result = history_store.save_report(
                    report=report,
                    repo_url=_history_repo_identifier(args, repo_path),
                    branch=args.history_branch or _git_output(repo_path, "rev-parse", "--abbrev-ref", "HEAD"),
                    commit_sha=args.history_commit_sha or _git_output(repo_path, "rev-parse", "HEAD"),
                    report_markdown=render_markdown(report, language="en"),
                )
            except HistoryStoreError as exc:
                raise SystemExit(str(exc)) from exc

        report = localize_report(report, args.report_language)

        if args.output:
            write_markdown(report, args.output, language=args.report_language)
            print(f"Markdown report written to {args.output}")
        else:
            print(render_markdown(report, language=args.report_language))

        if args.json:
            write_json(report, args.json)
            print(f"JSON report written to {args.json}")

        github_repo = args.github_repo or parse_github_repo(args.target)
        if args.github_issues != "none":
            if not github_repo:
                raise SystemExit("--github-repo owner/repo is required when the target is not a GitHub URL.")
            try:
                issue_results = apply_github_issue_mode(
                    report=report,
                    repo=github_repo,
                    mode=args.github_issues,
                    token=args.github_token,
                )
            except GitHubIntegrationError as exc:
                raise SystemExit(str(exc)) from exc
            print(json.dumps({"github_issues": issue_results}, indent=2, ensure_ascii=False))

        if args.github_pr_comment is not None:
            if not github_repo:
                raise SystemExit("--github-repo owner/repo is required when the target is not a GitHub URL.")
            try:
                comment_result = apply_github_pr_comment_mode(
                    report=report,
                    repo=github_repo,
                    pr_number=args.github_pr_comment,
                    mode=args.github_pr_comment_mode,
                    token=args.github_token,
                )
            except GitHubIntegrationError as exc:
                raise SystemExit(str(exc)) from exc
            print(json.dumps({"github_pr_comment": comment_result}, indent=2, ensure_ascii=False))

        if history_result:
            print(json.dumps({"history": history_result.to_dict()}, indent=2, ensure_ascii=False))

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-review",
        description="Analyze a local or GitHub repository and generate a review report.",
    )
    parser.add_argument("target", help="Local repository path or GitHub URL")
    parser.add_argument("-o", "--output", type=Path, help="Write Markdown report to this path")
    parser.add_argument("--json", type=Path, help="Write structured JSON report to this path")
    parser.add_argument(
        "--agent",
        action="store_true",
        help="Run the custom tool-calling RepoReviewAgent instead of the direct analysis pipeline.",
    )
    parser.add_argument(
        "--function-calling",
        action="store_true",
        help="Run the OpenAI Responses API function-calling agent. Requires OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--chatgpt-agent",
        action="store_true",
        help="Run the ChatGPT API repository review agent. Requires OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--ai-provider",
        choices=["none", "openai", "openrouter", "ollama"],
        default="none",
        help="Optional LLM provider used to generate an AI review section",
    )
    parser.add_argument(
        "--ai-model",
        help="Model name for the selected AI provider. Defaults to OPENAI_MODEL, OLLAMA_MODEL, or a provider default.",
    )
    parser.add_argument(
        "--report-language",
        choices=["en", "zh-CN"],
        default="en",
        help="Language for generated Markdown and AI review content.",
    )
    parser.add_argument(
        "--ai-timeout",
        type=float,
        default=60,
        help="Timeout in seconds for the optional AI provider request",
    )
    parser.add_argument(
        "--ai-max-output-tokens",
        type=int,
        default=900,
        help="Maximum output tokens requested from the optional AI provider",
    )
    parser.add_argument(
        "--ollama-url",
        default=None,
        help="Base URL for Ollama. Defaults to OLLAMA_BASE_URL or http://localhost:11434.",
    )
    parser.add_argument(
        "--fail-on-ai-error",
        action="store_true",
        help="Exit with an error if the optional AI provider call fails.",
    )
    parser.add_argument(
        "--github-repo",
        help="GitHub repository slug, for example owner/repo. Inferred from GitHub URL targets when possible.",
    )
    parser.add_argument(
        "--github-token",
        help="GitHub token for create modes. Defaults to GITHUB_TOKEN.",
    )
    parser.add_argument(
        "--github-issues",
        choices=["none", "dry-run", "create"],
        default="none",
        help="Generate GitHub issues from actionable findings, either as a dry-run or by creating them.",
    )
    parser.add_argument(
        "--github-pr-comment",
        type=int,
        help="Post or preview a pull request timeline comment using the issue comments API.",
    )
    parser.add_argument(
        "--github-pr-comment-mode",
        choices=["dry-run", "create"],
        default="dry-run",
        help="Whether PR comment mode should preview or create the comment.",
    )
    parser.add_argument("--max-files", type=int, default=500, help="Maximum number of files to scan")
    parser.add_argument(
        "--max-file-size",
        type=int,
        default=512_000,
        help="Maximum file size, in bytes, to read during the scan",
    )
    parser.add_argument(
        "--save-history",
        action="store_true",
        help="Save the review run, findings, AI review, and history diff to Supabase.",
    )
    parser.add_argument(
        "--supabase-url",
        help="Supabase project URL. Defaults to SUPABASE_URL.",
    )
    parser.add_argument(
        "--supabase-service-key",
        help="Supabase service role key. Defaults to SUPABASE_SERVICE_ROLE_KEY.",
    )
    parser.add_argument(
        "--history-repo-url",
        help="Repository identifier stored in history. Defaults to GitHub owner/repo, Git URL, or local path.",
    )
    parser.add_argument(
        "--history-branch",
        help="Branch name stored with the history run. Defaults to the current Git branch when available.",
    )
    parser.add_argument(
        "--history-commit-sha",
        help="Commit SHA stored with the history run. Defaults to the current Git commit when available.",
    )
    parser.add_argument(
        "--history-timeout",
        type=float,
        default=30,
        help="Timeout in seconds for Supabase history requests.",
    )
    return parser


class resolve_target:
    def __init__(self, target: str) -> None:
        self.target = target
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        if _looks_like_git_url(self.target):
            self._tmpdir = tempfile.TemporaryDirectory(prefix="repo-review-")
            clone_path = Path(self._tmpdir.name) / "repo"
            subprocess.run(
                ["git", "clone", "--depth", "1", self.target, str(clone_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            return clone_path

        path = Path(self.target).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise SystemExit(f"Target path does not exist or is not a directory: {path}")
        return path

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._tmpdir is not None:
            self._tmpdir.cleanup()


def _looks_like_git_url(target: str) -> bool:
    parsed = urlparse(target)
    return parsed.scheme in {"http", "https", "ssh", "git"} or target.startswith("git@")


def _history_repo_identifier(args: argparse.Namespace, repo_path: Path) -> str:
    return args.history_repo_url or args.github_repo or parse_github_repo(args.target) or args.target or str(repo_path)


def _git_output(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    value = result.stdout.strip()
    return value or None


if __name__ == "__main__":
    sys.exit(main())
