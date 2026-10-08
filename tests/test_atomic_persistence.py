import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from test_history import sample_report

from repo_review_agent.history import HistoryStoreError, SupabaseHistoryStore
from repo_review_agent.models import Finding


class AtomicPersistenceTests(unittest.TestCase):
    def test_single_safe_payload_replaces_independent_writes(self):
        store = SupabaseHistoryStore(supabase_url="https://invalid", service_key="test")
        secret = "sk-" + "a" * 36
        report = replace(
            sample_report(),
            findings=[Finding("Risk", "high", "security", [secret], secret)],
            ai_review=replace(sample_report().ai_review, summary=secret),
        )
        result = {
            "repository_id": "repo",
            "review_run_id": "run",
            "health_score": 75,
            "comparison": {"new_findings": [], "existing_findings": [], "resolved_findings": []},
            "finding_feedback": [],
        }
        with patch.object(store, "_request", return_value=result) as request:
            saved = store.save_report(report=report, repo_url="owner/repo", report_markdown=secret)
        self.assertEqual(saved.review_run_id, "run")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[:2], ("POST", "rpc/save_review_history"))
        self.assertNotIn(secret, json.dumps(request.call_args.args[2]))
        self.assertTrue(request.call_args.args[2]["p_operation"])

    def test_retry_uses_same_operation_and_never_falls_back(self):
        store = SupabaseHistoryStore(supabase_url="https://invalid", service_key="test")
        with patch.object(store, "_request", side_effect=HistoryStoreError("outage")) as request:
            for _ in range(2):
                with self.assertRaises(HistoryStoreError):
                    store.save_report(
                        report=sample_report(),
                        repo_url="owner/repo",
                        report_markdown="report",
                        operation_id="11111111-1111-1111-1111-111111111111",
                    )
        self.assertEqual(len(request.call_args_list), 2)
        self.assertTrue(
            all(call.args[1] == "rpc/save_review_history" for call in request.call_args_list)
        )
        self.assertEqual(request.call_args_list[0].args[2], request.call_args_list[1].args[2])


class DurableHistoryTests(unittest.TestCase):
    def test_worker_defers_history_for_atomic_parent_completion(self):
        from tempfile import TemporaryDirectory

        from repo_review_agent.auth import AuthUser
        from repo_review_agent.web import ReviewRequest, execute_review_request

        with (
            TemporaryDirectory() as tmp,
            patch("repo_review_agent.web.run_review_for_path", return_value=sample_report()),
            patch(
                "repo_review_agent.web.SupabaseHistoryStore.from_env",
                side_effect=AssertionError("worker must not save"),
            ),
        ):
            response = execute_review_request(
                ReviewRequest(target=tmp, save_history=True), AuthUser("owner"), defer_history=True
            )
        self.assertEqual(response["_pending_history"]["owner_id"], "owner")
        self.assertEqual(response["_pending_history"]["report"]["repo_name"], "repo")
        self.assertNotIn("history", response)

    def test_durable_completion_uses_job_identity_and_lease_in_transaction(self):
        from repo_review_agent.history import SupabaseReviewJobStore
        from repo_review_agent.web import SupabaseBackedReviewJobStore

        storage = SupabaseReviewJobStore(supabase_url="https://invalid", service_key="test")
        store = SupabaseBackedReviewJobStore(storage=storage)
        self.addCleanup(store.shutdown)
        store._leases["job"] = "lease"
        response = {"report": {}, "markdown": "report", "_pending_history": {"owner_id": "owner"}}
        with patch.object(storage, "_request", return_value={}) as request:
            store._set_completed("job", response)
        self.assertEqual(request.call_args.args[1], "rpc/save_review_history")
        args = request.call_args.args[2]
        self.assertEqual(
            (args["p_operation"], args["p_job"], args["p_lease"]), ("job", "job", "lease")
        )
        self.assertNotIn("_pending_history", args["p_result"])
        self.assertIn("_pending_history", response)

    def test_saved_job_markdown_uses_transaction_feedback(self):
        from repo_review_agent.findings import review_findings
        from repo_review_agent.web import _job_from_supabase_row

        report = sample_report().to_dict()
        report["finding_feedback"] = [
            {"fingerprint": review_findings(sample_report())[0].fingerprint, "status": "ignored"}
        ]
        row = {
            "id": "job",
            "status": "completed",
            "request_json": {"report_language": "en"},
            "result_json": {
                "report": report,
                "markdown": "[MEDIUM] Add automated tests",
                "history": {},
            },
        }
        job = _job_from_supabase_row(row)
        self.assertNotIn("[MEDIUM] Add automated tests", job.result["markdown"])
        self.assertIn("Add CI workflow", job.result["markdown"])
        self.assertEqual(row["result_json"]["markdown"], "[MEDIUM] Add automated tests")

    def test_durable_completion_seals_payload_without_redacting_lease(self):
        from repo_review_agent.history import SupabaseReviewJobStore

        store = SupabaseReviewJobStore(supabase_url="unused", service_key="unused")
        secret = "sk-" + "a" * 36
        with patch.object(store, "_request", return_value={}) as request:
            store.complete_with_history(
                "job",
                lease_token="valid-lease",
                result={
                    "report": {"overview": [secret]},
                    "markdown": secret,
                    "_pending_history": {"report_markdown": secret},
                },
            )
        payload = request.call_args.args[2]
        self.assertEqual(payload["p_lease"], "valid-lease")
        self.assertNotIn(secret, json.dumps(payload))

    def test_redacted_ai_round_trip_does_not_bypass_ignored_feedback(self):
        from repo_review_agent.findings import effective_findings, review_findings
        from repo_review_agent.models import AIReview
        from repo_review_agent.persistence import restore_report

        report = replace(
            sample_report(),
            findings=[],
            ai_review=AIReview(
                "openai",
                "test",
                "generated",
                "",
                findings=[
                    {
                        "title": "Risk",
                        "severity": "high",
                        "path": "app.py",
                        "start_line": 1,
                        "end_line": 1,
                        "evidence": "sk-" + "a" * 36,
                        "recommendation": "Fix",
                        "confidence": 0.9,
                    }
                ],
            ),
        )
        fingerprint = review_findings(report)[0].fingerprint
        report = replace(
            report, finding_feedback=[{"fingerprint": fingerprint, "status": "ignored"}]
        )
        restored = restore_report(report.to_dict())
        self.assertEqual(len(review_findings(restored)), 1)
        self.assertEqual(review_findings(restored)[0].fingerprint, fingerprint)
        self.assertEqual(effective_findings(restored), [])

    def test_failed_completion_never_publishes_database_details(self):
        from repo_review_agent.web import InMemoryReviewJobStore, ReviewRequest

        store = InMemoryReviewJobStore()
        self.addCleanup(store.shutdown)
        request = ReviewRequest(target=".")
        with patch.object(store, "_dispatch"):
            job = store.submit(request=request, user=None)
        with (
            patch.object(store, "_execute", return_value={}),
            patch.object(
                store, "_set_completed", side_effect=HistoryStoreError("INTERNAL SQL CONTEXT")
            ),
        ):
            store._run(job.id, request, None)
        result = store.get(job.id)
        self.assertEqual(result.status, "failed")
        self.assertNotIn("INTERNAL", result.error)

    def test_http_storage_error_is_safe_before_crossing_process_boundary(self):
        from io import BytesIO
        from urllib.error import HTTPError

        store = SupabaseHistoryStore(supabase_url="https://invalid", service_key="unused")
        error = HTTPError("https://invalid", 500, "failure", {}, BytesIO(b"INTERNAL SQL CONTEXT"))
        with (
            patch("repo_review_agent.history.urlopen", side_effect=error),
            self.assertRaises(HistoryStoreError) as caught,
        ):
            store._request("GET", "repositories")
        self.assertNotIn("INTERNAL", str(caught.exception))
