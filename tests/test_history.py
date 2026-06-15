import os
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from repo_review_agent.history import (
    FindingSnapshot,
    HistoryStoreError,
    SupabaseHistoryStore,
    calculate_health_score,
    compare_findings,
    finding_fingerprint,
)
from repo_review_agent.models import AIReview, Finding, ReviewReport


def sample_finding(
    title: str = "Add automated tests",
    *,
    severity: str = "medium",
    evidence_paths: list[str] | None = None,
) -> Finding:
    return Finding(
        title=title,
        severity=severity,
        category="testing",
        evidence=["No tests were detected."],
        evidence_paths=evidence_paths or ["tests/test_app.py", "src/app.py"],
        recommendation="Add focused tests.",
    )


def sample_report() -> ReviewReport:
    return ReviewReport(
        repo_name="repo",
        generated_at="2026-06-15T00:00:00+00:00",
        overview=["Dependency manifests found: pyproject.toml."],
        metrics={
            "files_scanned": 3,
            "files_skipped": 0,
            "source_files": 1,
            "test_files": 0,
            "dependency_files": 1,
            "ci_files": 0,
        },
        framework_signals={"Pytest": ["pyproject.toml"]},
        findings=[
            sample_finding(),
            sample_finding("Add CI workflow", severity="low", evidence_paths=[".github/workflows/ci.yml"]),
        ],
        ai_review=AIReview(
            provider="openai",
            model="gpt-test",
            status="generated",
            summary="AI summary",
            sections={"risks": ["No tests."]},
        ),
    )


class FakeSupabaseHistoryStore(SupabaseHistoryStore):
    def __init__(self, previous_findings: list[FindingSnapshot] | None = None) -> None:
        super().__init__(supabase_url="https://example.supabase.co", service_key="service-key")
        self.previous_findings = previous_findings or []
        self.calls: list[tuple[str, str, list[dict] | None, str | None]] = []

    def _request(self, method, path, body=None, *, prefer=None):  # type: ignore[no-untyped-def]
        self.calls.append((method, path, body, prefer))
        if path.startswith("repositories"):
            return [{"id": "repo-id"}]
        if path.startswith("review_runs?"):
            return [{"id": "previous-run-id"}] if self.previous_findings else []
        if path.startswith("findings?"):
            return [
                {
                    "fingerprint": finding.fingerprint,
                    "title": finding.title,
                    "severity": finding.severity,
                    "category": finding.category,
                    "evidence_json": finding.evidence,
                    "evidence_paths_json": finding.evidence_paths,
                    "recommendation": finding.recommendation,
                }
                for finding in self.previous_findings
            ]
        if path == "review_runs":
            return [{"id": "run-id"}]
        return []


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        return None

    def read(self) -> bytes:
        return self.body


class HistoryTests(unittest.TestCase):
    def test_finding_fingerprint_is_stable_for_evidence_path_order(self) -> None:
        first = sample_finding(evidence_paths=["src/app.py", "tests/test_app.py"])
        second = sample_finding(evidence_paths=["tests/test_app.py", "src/app.py"])

        self.assertEqual(finding_fingerprint(first), finding_fingerprint(second))

    def test_compare_findings_marks_new_existing_and_resolved(self) -> None:
        existing = sample_finding()
        new = sample_finding("Add CI workflow", evidence_paths=[".github/workflows/ci.yml"])
        resolved = FindingSnapshot(
            fingerprint="resolved-fingerprint",
            title="Old finding",
            severity="low",
            category="docs",
            evidence=["Old evidence"],
            evidence_paths=["README.md"],
            recommendation="Old recommendation",
        )
        previous = [
            FindingSnapshot(
                fingerprint=finding_fingerprint(existing),
                title=existing.title,
                severity=existing.severity,
                category=existing.category,
                evidence=existing.evidence,
                evidence_paths=existing.evidence_paths,
                recommendation=existing.recommendation,
            ),
            resolved,
        ]

        comparison = compare_findings([existing, new], previous)

        self.assertEqual([finding.title for finding in comparison.new_findings], ["Add CI workflow"])
        self.assertEqual([finding.title for finding in comparison.existing_findings], ["Add automated tests"])
        self.assertEqual([finding.title for finding in comparison.resolved_findings], ["Old finding"])

    def test_calculate_health_score_applies_severity_penalties(self) -> None:
        score = calculate_health_score(
            [
                sample_finding(severity="high"),
                sample_finding("Medium", severity="medium"),
                sample_finding("Low", severity="low"),
            ]
        )

        self.assertEqual(score, 58)

    def test_supabase_history_store_saves_report_and_diff_payloads(self) -> None:
        report = sample_report()
        previous = [
            FindingSnapshot(
                fingerprint=finding_fingerprint(report.findings[0]),
                title=report.findings[0].title,
                severity=report.findings[0].severity,
                category=report.findings[0].category,
                evidence=report.findings[0].evidence,
                evidence_paths=report.findings[0].evidence_paths,
                recommendation=report.findings[0].recommendation,
            )
        ]
        store = FakeSupabaseHistoryStore(previous_findings=previous)

        result = store.save_report(
            report=report,
            repo_url="owner/repo",
            branch="main",
            commit_sha="abc123",
            report_markdown="# Report",
        )

        self.assertEqual(result.repository_id, "repo-id")
        self.assertEqual(result.review_run_id, "run-id")
        self.assertEqual(result.health_score, 83)

        review_run_call = next(call for call in store.calls if call[1] == "review_runs")
        review_run_payload = review_run_call[2][0]  # type: ignore[index]
        self.assertEqual(review_run_payload["new_findings_count"], 1)
        self.assertEqual(review_run_payload["existing_findings_count"], 1)
        self.assertEqual(review_run_payload["resolved_findings_count"], 0)
        self.assertEqual(review_run_payload["report_markdown"], "# Report")

        findings_call = next(call for call in store.calls if call[1] == "findings")
        finding_statuses = {row["title"]: row["status"] for row in findings_call[2]}  # type: ignore[index]
        self.assertEqual(finding_statuses["Add automated tests"], "existing")
        self.assertEqual(finding_statuses["Add CI workflow"], "new")

    @patch.dict(
        os.environ,
        {
            "SUPABASE_URL": "https://env.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "env-service-key",
        },
        clear=True,
    )
    def test_supabase_history_store_from_env_uses_environment(self) -> None:
        store = SupabaseHistoryStore.from_env()

        self.assertEqual(store.supabase_url, "https://env.supabase.co")
        self.assertEqual(store.service_key, "env-service-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_supabase_history_store_from_env_requires_configuration(self) -> None:
        with self.assertRaises(HistoryStoreError) as context:
            SupabaseHistoryStore.from_env()

        self.assertIn("SUPABASE_URL is required", str(context.exception))

        with self.assertRaises(HistoryStoreError) as key_context:
            SupabaseHistoryStore.from_env(supabase_url="https://example.supabase.co")

        self.assertIn("SUPABASE_SERVICE_ROLE_KEY is required", str(key_context.exception))

    @patch("repo_review_agent.history.urlopen")
    def test_supabase_request_sends_json_and_returns_decoded_rows(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(b'[{"id": "row-id"}]')
        store = SupabaseHistoryStore(
            supabase_url="https://example.supabase.co/",
            service_key="service-key",
        )

        rows = store._request(
            "POST",
            "repositories",
            [{"repo_url": "owner/repo"}],
            prefer="return=representation",
        )

        self.assertEqual(rows, [{"id": "row-id"}])
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.supabase.co/rest/v1/repositories")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Prefer"), "return=representation")

    @patch("repo_review_agent.history.urlopen")
    def test_supabase_request_wraps_http_and_url_errors(self, mock_urlopen) -> None:
        store = SupabaseHistoryStore(
            supabase_url="https://example.supabase.co",
            service_key="service-key",
        )
        mock_urlopen.side_effect = HTTPError(
            "https://example.supabase.co/rest/v1/repositories",
            400,
            "Bad Request",
            hdrs=None,
            fp=BytesIO(b"bad request"),
        )

        with self.assertRaises(HistoryStoreError) as http_context:
            store._request("GET", "repositories")

        self.assertIn("400", str(http_context.exception))
        self.assertIn("bad request", str(http_context.exception))

        mock_urlopen.side_effect = URLError("offline")
        with self.assertRaises(HistoryStoreError) as url_context:
            store._request("GET", "repositories")

        self.assertIn("offline", str(url_context.exception))


if __name__ == "__main__":
    unittest.main()
