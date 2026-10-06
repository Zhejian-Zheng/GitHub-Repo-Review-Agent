from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .findings import feedback_active, finding_fingerprint
from .models import Finding, ReviewReport
from .persistence import history_payload

DEFAULT_TIMEOUT = 30
REVIEW_JOB_COLUMNS = (
    "id,owner_id,status,target,request_json,result_json,error,"
    "created_at,updated_at,started_at,completed_at,phase,lease_token,lease_expires_at,attempts"
)
SEVERITY_PENALTIES = {
    "high": 25,
    "medium": 12,
    "low": 5,
    "info": 0,
}
ReviewJobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


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
    source: str = "rule"
    rule_id: str | None = None
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "title": self.title,
            "severity": self.severity,
            "category": self.category,
            "evidence": self.evidence,
            "evidence_paths": self.evidence_paths,
            "recommendation": self.recommendation,
            "source": self.source,
            "rule_id": self.rule_id,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "confidence": self.confidence,
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
        statuses.update({finding.fingerprint: "existing" for finding in self.existing_findings})
        return statuses


@dataclass(frozen=True)
class HistorySaveResult:
    repository_id: str
    review_run_id: str
    health_score: int
    comparison: RunComparison
    finding_feedback: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "review_run_id": self.review_run_id,
            "health_score": self.health_score,
            "new_findings_count": len(self.comparison.new_findings),
            "existing_findings_count": len(self.comparison.existing_findings),
            "resolved_findings_count": len(self.comparison.resolved_findings),
            "finding_feedback": self.finding_feedback,
        }


def finding_to_snapshot(finding: Finding) -> FindingSnapshot:
    return FindingSnapshot(
        fingerprint=finding_fingerprint(finding),
        title=finding.title,
        severity=finding.severity,
        category=finding.category,
        evidence=list(finding.evidence),
        evidence_paths=list(finding.evidence_paths),
        recommendation=finding.recommendation,
        source=finding.source,
        rule_id=finding.rule_id,
        path=finding.path,
        start_line=finding.start_line,
        end_line=finding.end_line,
        confidence=finding.confidence,
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

    def __init__(
        self, *, supabase_url: str, service_key: str, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
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
        self, *, report: ReviewReport, repo_url: str, report_markdown: str,
        branch: str | None = None, commit_sha: str | None = None,
        owner_id: str | None = None, operation_id: str | None = None,
    ) -> HistorySaveResult:
        payload = history_payload(report=report, repo_url=repo_url,
                                  report_markdown=report_markdown, branch=branch,
                                  commit_sha=commit_sha, owner_id=owner_id)
        result = self._request("POST", "rpc/save_review_history", {
            "p_payload": payload, "p_operation": operation_id or str(uuid.uuid4()),
        })
        return _history_save_result(result)

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
        feedback = self._list_finding_feedback(repository_id, owner_id)
        by_fingerprint = {row["fingerprint"]: row for row in feedback}
        for finding in findings:
            finding["feedback"] = by_fingerprint.get(finding["fingerprint"])
        effective_rows = [
            row
            for row in findings
            if not (
                row.get("feedback")
                and row["feedback"].get("status") in {"ignored", "false_positive"}
                and feedback_active(row["feedback"])
            )
        ]
        effective_score = max(
            0, 100 - sum(SEVERITY_PENALTIES.get(row["severity"], 8) for row in effective_rows)
        )
        return {
            "repository": repository,
            "runs": runs,
            "latestRun": latest_run,
            "findings": _sort_finding_rows(findings),
            "aiReview": ai_review,
            "finding_feedback": feedback,
            "effective_health_score": effective_score,
        }

    def _list_finding_feedback(self, repository_id: str, owner_id: str) -> list[dict[str, Any]]:
        rows = self._request(
            "GET",
            "finding_feedback"
            f"?repository_id=eq.{_url_value(repository_id)}"
            f"&owner_id=eq.{_url_value(owner_id)}&select=*",
        )
        return _ensure_rows(rows, "finding feedback")

    def set_finding_feedback(
        self,
        *,
        repository_id: str,
        fingerprint: str,
        owner_id: str,
        status: str,
        reason: str = "",
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"confirmed", "false_positive", "ignored"}:
            raise HistoryStoreError("Invalid finding feedback status.")
        if not owner_id or not fingerprint or len(reason) > 4000:
            raise HistoryStoreError(
                "Owner, fingerprint and a reason up to 4000 characters are required."
            )
        if expires_at is not None:
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if expiry.tzinfo is None or expiry.utcoffset() != timedelta(0):
                    raise ValueError("UTC required")
                expires_at = expiry.astimezone(timezone.utc).isoformat()
            except (ValueError, TypeError, AttributeError) as exc:
                raise HistoryStoreError("Feedback expiry must be an ISO UTC timestamp.") from exc
        self._get_owned_repository(repository_id=repository_id, owner_id=owner_id)
        runs = self._list_review_runs(repository_id=repository_id, limit=1)
        if not runs or not any(
            row.get("fingerprint") == fingerprint
            for row in self._list_run_findings(_require_id(runs[0], "review run"))
        ):
            raise HistoryNotFoundError("Finding was not found in the latest repository review.")
        payload = {
            "repository_id": repository_id,
            "owner_id": owner_id,
            "fingerprint": fingerprint,
            "status": status,
            "reason": reason,
            "expires_at": expires_at,
            "updated_at": _utc_now(),
        }
        rows = self._request(
            "POST",
            "finding_feedback?on_conflict=repository_id,owner_id,fingerprint",
            [payload],
            prefer="resolution=merge-duplicates,return=representation",
        )
        return _first_row(rows, "finding feedback")

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
                "evidence_paths_json,recommendation,status,created_at,source,rule_id,path,start_line,end_line,confidence"
            ),
        )
        return _ensure_rows(rows, "findings")

    def _get_run_ai_review(self, review_run_id: str) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            (
                "ai_reviews"
                f"?review_run_id=eq.{_url_value(review_run_id)}"
                "&select=provider,model,status,summary,error,sections_json,findings_json,created_at"
                "&limit=1"
            ),
        )
        if not rows:
            return None
        return _first_row(rows, "AI review")

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


class SupabaseReviewJobStore(SupabaseHistoryStore):
    """Persist asynchronous web review jobs through Supabase's PostgREST API."""

    def enqueue_job(
        self,
        *,
        target: str,
        request_payload: dict[str, Any],
        owner_id: str | None,
        max_pending: int,
        per_user_limit: int,
        daily_limit: int = 100,
    ) -> dict[str, Any] | None:
        rows = self._request(
            "POST",
            "rpc/enqueue_review_job",
            {
                "p_target": target,
                "p_request": request_payload,
                "p_owner": owner_id,
                "p_max_pending": max_pending,
                "p_per_user": per_user_limit,
                "p_daily_limit": daily_limit,
            },
        )
        rows = _ensure_rows(rows, "review jobs")
        return rows[0] if rows else None

    def request_cancel(self, job_id: str, *, owner_id: str) -> dict[str, Any] | None:
        rows = self._request(
            "POST", "rpc/cancel_review_job", {"p_job": job_id, "p_owner": owner_id}
        )
        rows = _ensure_rows(rows, "review jobs")
        return rows[0] if rows else None

    def claim_job(self, *, lease_token: str, lease_seconds: int) -> dict[str, Any] | None:
        rows = self._request(
            "POST",
            "rpc/claim_review_job",
            {
                "p_token": lease_token,
                "p_lease_seconds": lease_seconds,
            },
        )
        rows = _ensure_rows(rows, "review jobs")
        return rows[0] if rows else None

    def recover_jobs(self, *, result_ttl: int) -> None:
        self._request("POST", "rpc/recover_review_jobs", {"p_result_ttl": result_ttl})

    def complete_with_history(self, job_id: str, *, lease_token: str, result: dict) -> None:
        self._request("POST", "rpc/save_review_history", {
            "p_payload": result["_pending_history"], "p_operation": job_id,
            "p_job": job_id, "p_lease": lease_token,
            "p_result": {key: value for key, value in result.items() if key != "_pending_history"},
        })

    def write_claimed_job(
        self,
        job_id: str,
        *,
        lease_token: str,
        status: str = "running",
        phase: str | None = None,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        payload = {"status": status, "phase": phase or status, "updated_at": _utc_now()}
        if status in {"completed", "failed"}:
            payload.update(completed_at=_utc_now(), result_json=result, error=error)
        rows = self._request(
            "PATCH",
            "review_jobs"
            f"?id=eq.{_url_value(job_id)}&lease_token=eq.{_url_value(lease_token)}"
            f"&status=eq.running&lease_expires_at=gt.{_url_value(_utc_now())}",
            payload,
            prefer="return=representation",
        )
        if not _ensure_rows(rows, "review jobs"):
            raise HistoryStoreError("Review job lease expired or ownership changed.")

    def create_job(
        self,
        *,
        target: str,
        request_payload: dict[str, Any],
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "target": target,
            "status": "queued",
            "request_json": request_payload,
        }
        if owner_id:
            payload["owner_id"] = owner_id

        rows = self._request(
            "POST",
            "review_jobs",
            [payload],
            prefer="return=representation",
        )
        return _first_row(rows, "review job")

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            (f"review_jobs?id=eq.{_url_value(job_id)}&select={REVIEW_JOB_COLUMNS}&limit=1"),
        )
        ensured_rows = _ensure_rows(rows, "review jobs")
        return ensured_rows[0] if ensured_rows else None

    def update_job(
        self,
        job_id: str,
        *,
        status: ReviewJobStatus,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": status,
            "updated_at": _utc_now(),
        }
        if status == "running":
            payload["started_at"] = _utc_now()
            payload["error"] = None
        if status in {"completed", "failed"}:
            payload["completed_at"] = _utc_now()
        if result is not None:
            payload["result_json"] = result
        if error is not None:
            payload["error"] = error

        rows = self._request(
            "PATCH",
            (f"review_jobs?id=eq.{_url_value(job_id)}&select={REVIEW_JOB_COLUMNS}"),
            payload,
            prefer="return=representation",
        )
        return _first_row(rows, "review job")

    def fail_stale_running_jobs(self, *, max_age_minutes: int = 120) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        payload = {
            "status": "failed",
            "error": "Review job was marked failed after stalling.",
            "updated_at": _utc_now(),
            "completed_at": _utc_now(),
        }
        rows = self._request(
            "PATCH",
            (
                "review_jobs"
                "?status=eq.running"
                f"&updated_at=lt.{_url_value(cutoff.isoformat())}"
                f"&select={REVIEW_JOB_COLUMNS}"
            ),
            payload,
            prefer="return=representation",
        )
        return len(_ensure_rows(rows, "stale review jobs"))


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _history_save_result(result: Any) -> HistorySaveResult:
    try:
        comparison = result["comparison"]
        return HistorySaveResult(
            repository_id=result["repository_id"], review_run_id=result["review_run_id"],
            health_score=int(result["health_score"]),
            comparison=RunComparison(**{name: [FindingSnapshot(**row) for row in comparison[name]]
                                       for name in ("new_findings", "existing_findings", "resolved_findings")}),
            finding_feedback=result.get("finding_feedback", []),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HistoryStoreError("History transaction returned an invalid result.") from exc
