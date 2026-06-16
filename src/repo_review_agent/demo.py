from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Literal, Mapping

from .history import HistoryStoreError, SupabaseHistoryStore

CheckStatus = Literal["pass", "warn", "fail"]

TRUTHY_VALUES = {"1", "true", "yes", "on"}
SERVER_ENV_KEYS = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY")
FRONTEND_ENV_PAIRS = (
    ("VITE_SUPABASE_URL", "SUPABASE_URL"),
    ("VITE_SUPABASE_ANON_KEY", "SUPABASE_ANON_KEY"),
)
SCHEMA_PROBES = {
    "repositories": "id,owner_id,repo_url,repo_name,default_branch,created_at,updated_at",
    "review_runs": (
        "id,repository_id,status,commit_sha,branch,health_score,metrics_json,"
        "framework_signals_json,report_json,report_markdown,diff_json,"
        "new_findings_count,existing_findings_count,resolved_findings_count,created_at"
    ),
    "findings": (
        "id,review_run_id,fingerprint,title,severity,category,evidence_json,"
        "evidence_paths_json,recommendation,status,created_at"
    ),
    "ai_reviews": "id,review_run_id,provider,model,status,summary,error,sections_json,created_at",
}


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: CheckStatus
    detail: str


def collect_readiness_checks(
    env: Mapping[str, str] | None = None,
    *,
    check_supabase: bool = True,
    timeout: float = 10,
) -> list[ReadinessCheck]:
    env = env or os.environ
    checks: list[ReadinessCheck] = []

    for key in SERVER_ENV_KEYS:
        value = _env_value(env, key)
        if value:
            checks.append(ReadinessCheck(key, "pass", "configured"))
        else:
            checks.append(ReadinessCheck(key, "fail", "required for Supabase-backed history"))

    _check_frontend_env(env, checks)
    _check_public_demo_controls(env, checks)
    _check_split_deployment(env, checks)

    if check_supabase:
        _check_supabase_schema(env, checks, timeout=timeout)
    else:
        checks.append(
            ReadinessCheck(
                "Supabase schema probe",
                "warn",
                "skipped; run without --skip-supabase before a real demo",
            )
        )

    return checks


def render_readiness_report(checks: list[ReadinessCheck]) -> str:
    failures = [check for check in checks if check.status == "fail"]
    warnings = [check for check in checks if check.status == "warn"]
    lines = ["Demo readiness check", ""]
    for check in checks:
        lines.append(f"[{check.status.upper()}] {check.name}: {check.detail}")

    lines.append("")
    if failures:
        lines.append(f"Result: not ready ({len(failures)} failure(s), {len(warnings)} warning(s)).")
    elif warnings:
        lines.append(f"Result: ready with warnings ({len(warnings)} warning(s)).")
    else:
        lines.append("Result: ready.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="repo-review-demo-check",
        description="Check whether the Supabase-backed web demo is ready to run.",
    )
    parser.add_argument(
        "--skip-supabase",
        action="store_true",
        help="Only check local environment values; skip the live Supabase schema probe.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10,
        help="Timeout in seconds for each Supabase schema probe.",
    )
    args = parser.parse_args(argv)

    checks = collect_readiness_checks(
        check_supabase=not args.skip_supabase,
        timeout=args.timeout,
    )
    print(render_readiness_report(checks))
    return 1 if any(check.status == "fail" for check in checks) else 0


def _check_frontend_env(env: Mapping[str, str], checks: list[ReadinessCheck]) -> None:
    for frontend_key, server_key in FRONTEND_ENV_PAIRS:
        frontend_value = _env_value(env, frontend_key)
        server_value = _env_value(env, server_key)
        if not frontend_value:
            checks.append(
                ReadinessCheck(frontend_key, "warn", "missing; browser login will stay disabled")
            )
            continue

        if server_value and _normalized_url_or_value(frontend_value) != _normalized_url_or_value(server_value):
            checks.append(
                ReadinessCheck(frontend_key, "warn", f"does not match {server_key}")
            )
            continue

        checks.append(ReadinessCheck(frontend_key, "pass", "configured"))

    anon_key = _env_value(env, "SUPABASE_ANON_KEY")
    service_key = _env_value(env, "SUPABASE_SERVICE_ROLE_KEY")
    if anon_key and service_key and anon_key == service_key:
        checks.append(
            ReadinessCheck(
                "Supabase key separation",
                "fail",
                "anon key and service role key must be different",
            )
        )
    elif anon_key and service_key:
        checks.append(ReadinessCheck("Supabase key separation", "pass", "anon and service keys differ"))


def _check_public_demo_controls(env: Mapping[str, str], checks: list[ReadinessCheck]) -> None:
    if _env_bool(env, "REPO_REVIEW_REQUIRE_AUTH", default=False):
        checks.append(ReadinessCheck("REPO_REVIEW_REQUIRE_AUTH", "pass", "review API requires login"))
    else:
        checks.append(
            ReadinessCheck(
                "REPO_REVIEW_REQUIRE_AUTH",
                "warn",
                "set to true for a private authenticated demo",
            )
        )

    if _env_bool(env, "REPO_REVIEW_ALLOW_LOCAL_TARGETS", default=False):
        checks.append(
            ReadinessCheck(
                "REPO_REVIEW_ALLOW_LOCAL_TARGETS",
                "warn",
                "local paths are enabled; turn this off for public deployments",
            )
        )
    else:
        checks.append(
            ReadinessCheck(
                "REPO_REVIEW_ALLOW_LOCAL_TARGETS",
                "pass",
                "public target policy only allows GitHub URLs",
            )
        )

    if _env_value(env, "REPO_REVIEW_API_TOKEN"):
        checks.append(ReadinessCheck("REPO_REVIEW_API_TOKEN", "pass", "configured"))
    else:
        checks.append(
            ReadinessCheck(
                "REPO_REVIEW_API_TOKEN",
                "warn",
                "not set; acceptable for login-only demos, less ideal for public API access",
            )
        )


def _check_split_deployment(env: Mapping[str, str], checks: list[ReadinessCheck]) -> None:
    api_base_url = _env_value(env, "VITE_API_BASE_URL")
    cors_origins = _env_value(env, "REPO_REVIEW_CORS_ORIGINS")

    if api_base_url:
        checks.append(ReadinessCheck("VITE_API_BASE_URL", "pass", api_base_url))
        if cors_origins:
            checks.append(ReadinessCheck("REPO_REVIEW_CORS_ORIGINS", "pass", cors_origins))
        else:
            checks.append(
                ReadinessCheck(
                    "REPO_REVIEW_CORS_ORIGINS",
                    "warn",
                    "required when the frontend is hosted on GitHub Pages, Vercel, or Netlify",
                )
            )
    else:
        checks.append(
            ReadinessCheck(
                "VITE_API_BASE_URL",
                "warn",
                "not set; frontend will call the same origin as the page",
            )
        )


def _check_supabase_schema(
    env: Mapping[str, str],
    checks: list[ReadinessCheck],
    *,
    timeout: float,
) -> None:
    supabase_url = _env_value(env, "SUPABASE_URL")
    service_key = _env_value(env, "SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        checks.append(
            ReadinessCheck(
                "Supabase schema probe",
                "fail",
                "missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY",
            )
        )
        return

    store = SupabaseHistoryStore(
        supabase_url=supabase_url,
        service_key=service_key,
        timeout=timeout,
    )
    for table, columns in SCHEMA_PROBES.items():
        try:
            store._request("GET", f"{table}?select={columns}&limit=1")
        except HistoryStoreError as exc:
            checks.append(ReadinessCheck(f"table {table}", "fail", str(exc)))
        else:
            checks.append(ReadinessCheck(f"table {table}", "pass", "required columns are readable"))


def _env_value(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _env_bool(env: Mapping[str, str], key: str, *, default: bool) -> bool:
    value = _env_value(env, key)
    if value is None:
        return default
    return value.lower() in TRUTHY_VALUES


def _normalized_url_or_value(value: str) -> str:
    return value.rstrip("/") if value.startswith(("http://", "https://")) else value


if __name__ == "__main__":
    sys.exit(main())
