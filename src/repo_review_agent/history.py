from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .models import Finding, ReviewReport

DEFAULT_TIMEOUT = 30
SEVERITY_PENALTIES = {
    "high": 25,
    "medium": 12,
    "low": 5,
    "info": 0,
}


class HistoryStoreError(RuntimeError):
    pass


class HistoryNotFoundError(HistoryStoreError):
    pass


@dataclass(frozen=True)
class FindingSnapshot:
    fingerprint: str
    title: str
    severity: str
    category: str
    evidence: list[str]
    evidence_paths: list[str]
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "title": self.title,
            "severity": self.severity,
            "category": self.category,
            "evidence": self.evidence,
            "evidence_paths": self.evidence_paths,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class RunComparison:
    new_findings: list[FindingSnapshot]
    existing_findings: list[FindingSnapshot]
    resolved_findings: list[FindingSnapshot]

    def to_dict(self) -> dict[str, Any]:
        return {
            "new_findings": [finding.to_dict() for finding in self.new_findings],
            "existing_findings": [finding.to_dict() for finding in self.existing_findings],
            "resolved_findings": [finding.to_dict() for finding in self.resolved_findings],
        }

    def status_by_fingerprint(self) -> dict[str, str]:
        statuses = {finding.fingerprint: "new" for finding in self.new_findings}
        statuses.update(
            {finding.fingerprint: "existing" for finding in self.existing_findings}
        )
        return statuses


@dataclass(frozen=True)
class HistorySaveResult:
    repository_id: str
    review_run_id: str
    health_score: int
    comparison: RunComparison

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "review_run_id": self.review_run_id,
            "health_score": self.health_score,
            "new_findings_count": len(self.comparison.new_findings),
            "existing_findings_count": len(self.comparison.existing_findings),
            "resolved_findings_count": len(self.comparison.resolved_findings),
        }


def finding_fingerprint(finding: Finding) -> str:
    payload = {
        "title": finding.title.strip().lower(),
        "category": finding.category.strip().lower(),
        "evidence_paths": sorted(path.strip().lower() for path in finding.evidence_paths),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def finding_to_snapshot(finding: Finding) -> FindingSnapshot:
    return FindingSnapshot(
        fingerprint=finding_fingerprint(finding),
        title=finding.title,
        severity=finding.severity,
        category=finding.category,
        evidence=list(finding.evidence),
        evidence_paths=list(finding.evidence_paths),
        recommendation=finding.recommendation,
    )


def compare_findings(
    current_findings: list[Finding],
    previous_findings: list[FindingSnapshot],
) -> RunComparison:
    current_by_fingerprint = {
        finding.fingerprint: finding for finding in map(finding_to_snapshot, current_findings)
    }
    previous_by_fingerprint = {finding.fingerprint: finding for finding in previous_findings}

    new_findings = [
        finding
        for fingerprint, finding in current_by_fingerprint.items()
        if fingerprint not in previous_by_fingerprint
    ]
    existing_findings = [
        finding
        for fingerprint, finding in current_by_fingerprint.items()
        if fingerprint in previous_by_fingerprint
    ]
    resolved_findings = [
        finding
        for fingerprint, finding in previous_by_fingerprint.items()
        if fingerprint not in current_by_fingerprint
    ]
    return RunComparison(
        new_findings=new_findings,
        existing_findings=existing_findings,
        resolved_findings=resolved_findings,
    )


def calculate_health_score(findings: list[Finding]) -> int:
    penalty = sum(SEVERITY_PENALTIES.get(finding.severity, 8) for finding in findings)
    return max(0, min(100, 100 - penalty))


class SupabaseHistoryStore:
    """Persist review history through Supabase's PostgREST API."""

    def __init__(self, *, supabase_url: str, service_key: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.supabase_url = supabase_url.rstrip("/")
        self.service_key = service_key
        self.timeout = timeout

    @classmethod
    def from_env(
        cls,
        *,
        supabase_url: str | None = None,
        service_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> SupabaseHistoryStore:
        resolved_url = supabase_url or os.environ.get("SUPABASE_URL")
        resolved_key = (
            service_key
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or os.environ.get("SUPABASE_SERVICE_KEY")
        )
        if not resolved_url:
            raise HistoryStoreError("SUPABASE_URL is required to save review history.")
        if not resolved_key:
            raise HistoryStoreError("SUPABASE_SERVICE_ROLE_KEY is required to save review history.")
        return cls(supabase_url=resolved_url, service_key=resolved_key, timeout=timeout)

    def save_report(
        self,
        *,
        report: ReviewReport,
        repo_url: str,
        report_markdown: str,
        branch: str | None = None,
        commit_sha: str | None = None,
        owner_id: str | None = None,
    ) -> HistorySaveResult:
        repository = self._upsert_repository(
            repo_url=repo_url,
            repo_name=report.repo_name,
            branch=branch,
            owner_id=owner_id,
        )
        repository_id = _require_id(repository, "repository")
        previous_findings = self._latest_findings(repository_id)
        comparison = compare_findings(report.findings, previous_findings)
        health_score = calculate_health_score(report.findings)
        review_run = self._insert_review_run(
            repository_id=repository_id,
            report=report,
            report_markdown=report_markdown,
            branch=branch,
            commit_sha=commit_sha,
            health_score=health_score,
            comparison=comparison,
        )
        review_run_id = _require_id(review_run, "review run")
        self._insert_findings(review_run_id, report.findings, comparison)
        self._insert_ai_review(review_run_id, report)
        return HistorySaveResult(
            repository_id=repository_id,
            review_run_id=review_run_id,
            health_score=health_score,
            comparison=comparison,
        )

    def list_repositories(self, *, owner_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._request(
            "GET",
            (
                "repositories"
                f"?owner_id=eq.{_url_value(owner_id)}"
                "&select=id,repo_url,repo_name,default_branch,created_at,updated_at"
                "&order=updated_at.desc"
                f"&limit={limit}"
            ),
        )
        return _ensure_rows(rows, "repositories")

    def get_project_detail(
        self,
        *,
        repository_id: str,
        owner_id: str,
        runs_limit: int = 12,
    ) -> dict[str, Any]:
        repository = self._get_owned_repository(repository_id=repository_id, owner_id=owner_id)
        runs = self._list_review_runs(repository_id=repository_id, limit=runs_limit)
        latest_run = runs[0] if runs else None
        if latest_run is None:
            return {
                "repository": repository,
                "runs": runs,
                "latestRun": None,
                "findings": [],
                "aiReview": None,
            }

        review_run_id = _require_id(latest_run, "review run")
        findings = self._list_run_findings(review_run_id)
        ai_review = self._get_run_ai_review(review_run_id)
        return {
            "repository": repository,
            "runs": runs,
            "latestRun": latest_run,
            "findings": _sort_finding_rows(findings),
            "aiReview": ai_review,
        }

    def _upsert_repository(
        self,
        *,
        repo_url: str,
        repo_name: str,
        branch: str | None,
        owner_id: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "repo_url": repo_url,
            "repo_name": repo_name,
            "default_branch": branch,
        }
        if owner_id:
            payload["owner_id"] = owner_id

        existing = self._find_repository(repo_url=repo_url, owner_id=owner_id)
        if existing:
            repository_id = _require_id(existing, "repository")
            rows = self._request(
                "PATCH",
                f"repositories?id=eq.{_url_value(repository_id)}",
                payload,
                prefer="return=representation",
            )
            return _first_row(rows, "repository")

        rows = self._request("POST", "repositories", [payload], prefer="return=representation")
        return _first_row(rows, "repository")

    def _find_repository(self, *, repo_url: str, owner_id: str | None) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            (
                "repositories"
                f"?repo_url=eq.{_url_value(repo_url)}"
                f"&owner_id={_owner_filter(owner_id)}"
                "&select=id,repo_url,owner_id,repo_name,default_branch"
                "&limit=1"
            ),
        )
        if not rows:
            return None
        return _first_row(rows, "repository")

    def _get_owned_repository(self, *, repository_id: str, owner_id: str) -> dict[str, Any]:
        rows = self._request(
            "GET",
            (
                "repositories"
                f"?id=eq.{_url_value(repository_id)}"
                f"&owner_id=eq.{_url_value(owner_id)}"
                "&select=id,repo_url,repo_name,default_branch,created_at,updated_at"
                "&limit=1"
            ),
        )
        if not rows:
            raise HistoryNotFoundError("Repository history was not found.")
        return _first_row(rows, "repository")

    def _list_review_runs(self, *, repository_id: str, limit: int) -> list[dict[str, Any]]:
        rows = self._request(
            "GET",
            (
                "review_runs"
                f"?repository_id=eq.{_url_value(repository_id)}"
                "&select=id,status,commit_sha,branch,health_score,new_findings_count,"
                "existing_findings_count,resolved_findings_count,created_at,metrics_json,diff_json"
                "&order=created_at.desc"
                f"&limit={limit}"
            ),
        )
        return _ensure_rows(rows, "review runs")

    def _list_run_findings(self, review_run_id: str) -> list[dict[str, Any]]:
        rows = self._request(
            "GET",
            (
                "findings"
                f"?review_run_id=eq.{_url_value(review_run_id)}"
                "&select=fingerprint,title,severity,category,evidence_json,"
                "evidence_paths_json,recommendation,status,created_at"
            ),
        )
        return _ensure_rows(rows, "findings")

    def _get_run_ai_review(self, review_run_id: str) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            (
                "ai_reviews"
                f"?review_run_id=eq.{_url_value(review_run_id)}"
                "&select=provider,model,status,summary,error,sections_json,created_at"
                "&limit=1"
            ),
        )
        if not rows:
            return None
        return _first_row(rows, "AI review")

    def _latest_findings(self, repository_id: str) -> list[FindingSnapshot]:
        runs = self._request(
            "GET",
            (
                "review_runs"
                f"?repository_id=eq.{repository_id}"
                "&status=eq.completed"
                "&select=id"
                "&order=created_at.desc"
                "&limit=1"
            ),
        )
        if not runs:
            return []

        review_run_id = _first_row(runs, "previous review run")["id"]
        rows = self._request(
            "GET",
            (
                "findings"
                f"?review_run_id=eq.{review_run_id}"
                "&select=fingerprint,title,severity,category,evidence_json,evidence_paths_json,recommendation"
            ),
        )
        return [
            FindingSnapshot(
                fingerprint=row["fingerprint"],
                title=row["title"],
                severity=row["severity"],
                category=row["category"],
                evidence=list(row.get("evidence_json") or []),
                evidence_paths=list(row.get("evidence_paths_json") or []),
                recommendation=row["recommendation"],
            )
            for row in rows or []
        ]

    def _insert_review_run(
        self,
        *,
        repository_id: str,
        report: ReviewReport,
        report_markdown: str,
        branch: str | None,
        commit_sha: str | None,
        health_score: int,
        comparison: RunComparison,
    ) -> dict[str, Any]:
        payload = {
            "repository_id": repository_id,
            "status": "completed",
            "commit_sha": commit_sha,
            "branch": branch,
            "health_score": health_score,
            "metrics_json": report.metrics,
            "framework_signals_json": report.framework_signals,
            "report_json": report.to_dict(),
            "report_markdown": report_markdown,
            "diff_json": comparison.to_dict(),
            "new_findings_count": len(comparison.new_findings),
            "existing_findings_count": len(comparison.existing_findings),
            "resolved_findings_count": len(comparison.resolved_findings),
        }
        rows = self._request("POST", "review_runs", [payload], prefer="return=representation")
        return _first_row(rows, "review run")

    def _insert_findings(
        self,
        review_run_id: str,
        findings: list[Finding],
        comparison: RunComparison,
    ) -> None:
        statuses = comparison.status_by_fingerprint()
        rows = []
        for finding in findings:
            fingerprint = finding_fingerprint(finding)
            rows.append(
                {
                    "review_run_id": review_run_id,
                    "fingerprint": fingerprint,
                    "title": finding.title,
                    "severity": finding.severity,
                    "category": finding.category,
                    "evidence_json": finding.evidence,
                    "evidence_paths_json": finding.evidence_paths,
                    "recommendation": finding.recommendation,
                    "status": statuses.get(fingerprint, "new"),
                }
            )
        if rows:
            self._request("POST", "findings", rows)

    def _insert_ai_review(self, review_run_id: str, report: ReviewReport) -> None:
        if not report.ai_review:
            return
        self._request(
            "POST",
            "ai_reviews",
            [
                {
                    "review_run_id": review_run_id,
                    "provider": report.ai_review.provider,
                    "model": report.ai_review.model,
                    "status": report.ai_review.status,
                    "summary": report.ai_review.summary,
                    "error": report.ai_review.error,
                    "sections_json": report.ai_review.sections or {},
                }
            ],
        )

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | list[dict[str, Any]] | None = None,
        *,
        prefer: str | None = None,
    ) -> Any:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer

        request = Request(
            f"{self.supabase_url}/rest/v1/{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise HistoryStoreError(f"Supabase request failed ({exc.code}): {detail}") from exc
        except URLError as exc:
            raise HistoryStoreError(f"Supabase request failed: {exc.reason}") from exc

        if not raw.strip():
            return None
        return json.loads(raw)


def _first_row(rows: Any, label: str) -> dict[str, Any]:
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise HistoryStoreError(f"Supabase did not return a {label} row.")
    return rows[0]


def _ensure_rows(rows: Any, label: str) -> list[dict[str, Any]]:
    if rows is None:
        return []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise HistoryStoreError(f"Supabase did not return valid {label} rows.")
    return rows


def _require_id(row: dict[str, Any], label: str) -> str:
    value = row.get("id")
    if not isinstance(value, str) or not value:
        raise HistoryStoreError(f"Supabase {label} row did not include an id.")
    return value


def _url_value(value: str) -> str:
    return quote(value, safe="")


def _owner_filter(owner_id: str | None) -> str:
    return f"eq.{_url_value(owner_id)}" if owner_id else "is.null"


def _sort_finding_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    severity_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    return sorted(
        rows,
        key=lambda row: (
            severity_rank.get(str(row.get("severity", "info")), 4),
            str(row.get("title", "")),
        ),
    )
