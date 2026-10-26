import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from repo_review_agent.review_jobs import InMemoryReviewJobStore, JobCapacityError


class QuestionCapacityTests(unittest.TestCase):
    def store(self, **kwargs):
        store = InMemoryReviewJobStore(**kwargs)
        self.addCleanup(store.shutdown)
        return store

    def test_same_user_cannot_hold_two_slots_and_error_releases_capacity(self):
        store = self.store()
        self.assertTrue(hasattr(store, "question_slot"), "Questions need bounded admission")
        with self.assertRaisesRegex(ValueError, "provider failure"), store.question_slot("owner"):
            with self.assertRaises(JobCapacityError), store.question_slot("owner"):
                self.fail("Concurrent question admitted")
            raise ValueError("provider failure")
        with store.question_slot("owner"):
            pass

    def test_different_users_share_a_global_limit(self):
        store = self.store()
        self.assertTrue(hasattr(store, "question_slot"), "Questions need bounded admission")
        with (store.question_slot("one"), store.question_slot("two"),
              self.assertRaises(JobCapacityError), store.question_slot("three")):
            self.fail("Global limit bypassed")
        with store.question_slot("three"):
            pass

    def test_rate_limit_survives_completed_questions_and_recovers(self):
        with patch.dict("os.environ", {"REPO_REVIEW_QUESTION_RATE_PER_MINUTE": "2"}):
            store = self.store()
        self.assertTrue(hasattr(store, "question_slot"), "Questions need bounded admission")
        with patch("repo_review_agent.question_runtime.time.monotonic", return_value=100):
            for _ in range(2):
                with store.question_slot("owner"):
                    pass
            with self.assertRaises(JobCapacityError), store.question_slot("owner"):
                self.fail("Rate limit bypassed")
        with (patch("repo_review_agent.question_runtime.time.monotonic", return_value=161),
              store.question_slot("owner")):
            pass

    def test_concurrent_admission_is_atomic(self):
        store = self.store()
        self.assertTrue(hasattr(store, "question_slot"), "Questions need bounded admission")
        acquired, release = threading.Event(), threading.Event()

        def hold():
            with store.question_slot("owner"):
                acquired.set()
                release.wait(2)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(hold)
            try:
                self.assertTrue(acquired.wait(1))
                with self.assertRaises(JobCapacityError), store.question_slot("owner"):
                    self.fail("Concurrent slot admitted")
            finally:
                release.set()
            future.result()

    def test_question_deadline_releases_slot_and_consumes_daily_quota_once(self):
        store = self.store(daily_limit=2)
        self.assertTrue(hasattr(store, "execute_question"), "Questions need isolated execution")
        from repo_review_agent.requests import ReportQuestionRequest
        request = ReportQuestionRequest(question="Why?", provider="ollama", report={"findings": []})
        with (patch("repo_review_agent.question_runtime.run_isolated",
                    side_effect=RuntimeError("Review exceeded its total execution deadline.")),
              self.assertRaisesRegex(RuntimeError, "deadline")):
            store.execute_question(request, "owner", request.report)
        with patch("repo_review_agent.question_runtime.run_isolated", return_value={"answer": "ok"}) as run:
            self.assertEqual(store.execute_question(request, "owner", request.report), {"answer": "ok"})
            self.assertEqual(run.call_args.kwargs["operation"], "question")
            self.assertEqual(run.call_args.kwargs["timeout"], 45)
        with self.assertRaises(JobCapacityError):
            store.execute_question(request, "owner", request.report)

    def test_real_question_worker_returns_offline_evidence(self):
        from repo_review_agent.job_runtime import run_isolated
        result = run_isolated(
            {"question": "Why?", "provider": "none", "report": {"findings": [{
                "path": "app.py", "evidence": ["eval(input())"],
                "title": "Untrusted evaluation", "recommendation": "Parse input.",
            }]}}, None, timeout=10, operation="question",
        )
        self.assertIn("Parse input.", result["answer"])
        self.assertEqual(result["citations"][0]["path"], "app.py")

    def test_durable_release_occurs_on_provider_failure_and_tolerates_storage_outage(self):
        from unittest.mock import Mock

        from repo_review_agent.history import HistoryStoreError
        from repo_review_agent.question_runtime import QuestionRuntime
        runtime = QuestionRuntime()
        storage = Mock()
        storage._request.side_effect = ["lease-id", HistoryStoreError("offline")]
        with (self.assertLogs("repo_review_agent.question_runtime", level="WARNING"),
              self.assertRaisesRegex(ValueError, "failed"), runtime.slot("owner", storage=storage)):
            raise ValueError("provider failed")
        self.assertEqual(storage._request.call_args.args,
                         ("POST", "rpc/release_review_question", {"p_lease": "lease-id"}))
        storage._request.side_effect = [None]
        with self.assertRaises(JobCapacityError), runtime.slot("owner", storage=storage):
            self.fail("Rejected lease admitted")

    def test_shutdown_rejects_question_admission(self):
        store = self.store()
        store.shutdown()
        with self.assertRaises(JobCapacityError), store.question_slot("owner"):
            self.fail("Shutdown admitted new work")
