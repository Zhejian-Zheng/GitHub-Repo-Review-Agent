import sys
import time
import unittest
from unittest.mock import patch

from repo_review_agent import web
from repo_review_agent.job_runtime import run_isolated


class JobRuntimeTests(unittest.TestCase):
    def test_deadline_kills_process_and_returns_capacity(self):
        start = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "deadline"):
            run_isolated({}, None, timeout=0.1,
                         command=[sys.executable, "-c", "import time; time.sleep(30)"])
        self.assertLess(time.monotonic() - start, 3)

    def test_memory_backlog_and_owner_quota(self):
        store = web.InMemoryReviewJobStore(max_workers=1, max_pending=2, per_user_limit=1)
        with patch.object(store, "_dispatch"):
            store.submit(request=web.ReviewRequest(target="."), user=None)
            with self.assertRaises(web.JobCapacityError):
                store.submit(request=web.ReviewRequest(target="."), user=None)
        store.shutdown()

    def test_completion_write_failure_attempts_failed_transition(self):
        store = web.InMemoryReviewJobStore(max_workers=1)
        with patch.object(store, "_set_running"), patch.object(store, "_execute", return_value={}), patch.object(
            store, "_set_completed", side_effect=RuntimeError("database unavailable")
        ), patch.object(store, "_set_failed") as failed:
            store._run("job", web.ReviewRequest(target="."), None)
        failed.assert_called_once()
        store.shutdown()

    def test_memory_result_expiration(self):
        store = web.InMemoryReviewJobStore(max_workers=1, result_ttl=0)
        with patch.object(store, "_dispatch"):
            job = store.submit(request=web.ReviewRequest(target="."), user=None)
        store._set_completed(job.id, {})
        self.assertIsNone(store.get(job.id))
        store.shutdown()

    def test_global_backlog_limits_different_users(self):
        from repo_review_agent.auth import AuthUser
        store = web.InMemoryReviewJobStore(max_workers=1, max_pending=1, per_user_limit=3)
        with patch.object(store, "_dispatch"):
            store.submit(request=web.ReviewRequest(target="."), user=AuthUser("one"))
            with self.assertRaises(web.JobCapacityError):
                store.submit(request=web.ReviewRequest(target="."), user=AuthUser("two"))
        store.shutdown()

    def test_real_worker_reports_stages_and_cleans_workspace(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        phases = []
        with TemporaryDirectory() as target:
            (Path(target) / "README.md").write_text("# Example")
            result = run_isolated({"target": target, "mode": "direct"}, None,
                                  timeout=10, on_progress=phases.append)
        self.assertIn("markdown", result)
        self.assertIn("cloning", phases)
        self.assertIn("analyzing", phases)

    def test_shutdown_interrupts_worker(self):
        import threading
        stop = threading.Event()
        stop.set()
        with self.assertRaisesRegex(RuntimeError, "shutdown"):
            run_isolated({}, None, timeout=20, stop=stop,
                         command=[sys.executable, "-c", "import time; time.sleep(30)"])

    def test_deadline_still_kills_child_when_progress_write_blocks(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            marker = Path(temp) / "survived"
            command = [sys.executable, "-c", (
                "import os,time,pathlib; "
                "pathlib.Path(os.environ['TMPDIR'],'progress').write_text('analyzing\\n'); "
                f"time.sleep(0.3); pathlib.Path({str(marker)!r}).write_text('alive'); time.sleep(5)"
            )]
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                run_isolated({}, None, timeout=0.15, command=command,
                             on_progress=lambda phase: time.sleep(0.5))
            self.assertFalse(marker.exists())

    def test_expired_lease_write_is_rejected(self):
        from repo_review_agent.history import HistoryStoreError, SupabaseReviewJobStore
        storage = SupabaseReviewJobStore(supabase_url="https://example.test", service_key="secret")
        with patch.object(storage, "_request", return_value=[]) as request, \
                self.assertRaisesRegex(HistoryStoreError, "ownership"):
            storage.write_claimed_job("id", lease_token="stale", status="completed", result={})
        path = request.call_args.args[1]
        self.assertIn("lease_token=eq.stale", path)
        self.assertIn("lease_expires_at=gt.", path)
        self.assertIn("status=eq.running", path)

    def test_sweep_recovers_then_claims_persisted_request(self):
        from unittest.mock import Mock
        storage = Mock()
        storage.claim_job.side_effect = [{"id": "restored", "owner_id": "owner", "request_json":
                                         {"target": ".", "mode": "direct"}}, None]
        store = web.SupabaseBackedReviewJobStore(storage=storage, max_workers=2)
        with patch.object(store, "_dispatch") as dispatch:
            store.sweep()
        storage.recover_jobs.assert_called_once_with(result_ttl=86400)
        self.assertEqual(dispatch.call_args.args[0], "restored")
        self.assertEqual(dispatch.call_args.args[2].id, "owner")
        self.assertIn("restored", store._leases)
        store.shutdown()

    def test_clone_failure_cleans_temp_and_is_noninteractive(self):
        import subprocess
        from pathlib import Path

        from repo_review_agent.cli import resolve_target
        resolver = resolve_target("https://github.com/owner/repo")
        captured = []

        def fail(*args, **kwargs):
            captured.append(Path(args[0][-1]).parent)
            self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            self.assertGreater(kwargs["timeout"], 0)
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

        with patch("repo_review_agent.cli.subprocess.run", side_effect=fail), \
                self.assertRaises(subprocess.TimeoutExpired):
            resolver.__enter__()
        self.assertFalse(captured[0].exists())

    def test_worker_entrypoint_success_and_redacted_failure(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from repo_review_agent.job_runtime import main

        def execute(request, user, on_progress):
            self.assertEqual(user.id, "owner")
            on_progress("analyzing")
            return {"report": {}}

        with TemporaryDirectory() as workspace:
            root = Path(workspace)
            (root / "input.json").write_text(json.dumps({"request": {"target": "."}, "user": {"id": "owner"}}))
            with patch("repo_review_agent.web.execute_review_request", side_effect=execute):
                main(workspace)
            self.assertEqual(json.loads((root / "output.json").read_text()), {"result": {"report": {}}})
            self.assertEqual((root / "progress").read_text(), "analyzing\n")
            with patch("repo_review_agent.web.execute_review_request", side_effect=RuntimeError("worker failure")):
                main(workspace)
            self.assertEqual(json.loads((root / "output.json").read_text()), {"error": "worker failure"})

    def test_worker_crash_without_output(self):
        with self.assertRaisesRegex(RuntimeError, "without a result"):
            run_isolated({}, None, timeout=2, command=[sys.executable, "-c", "pass"])

    def test_completion_write_retries_before_failing(self):
        from repo_review_agent.history import HistoryStoreError
        store = web.InMemoryReviewJobStore()
        with patch.object(store, "_execute", return_value={}), patch.object(
            store, "_set_completed", side_effect=[HistoryStoreError("outage"), None]
        ) as completed, patch.object(store, "_set_failed") as failed:
            store._run("job", web.ReviewRequest(target="."), None)
        self.assertEqual(completed.call_count, 2)
        failed.assert_not_called()
        with patch.object(store, "_execute", return_value={}), patch.object(
            store, "_set_completed", side_effect=HistoryStoreError("outage")
        ) as completed, patch.object(store, "_set_failed") as failed:
            store._run("job", web.ReviewRequest(target="."), None)
        self.assertEqual(completed.call_count, 3)
        failed.assert_called_once()
        store.shutdown()

    def test_dispatch_failure_releases_memory_admission(self):
        store = web.InMemoryReviewJobStore(max_pending=1)
        with patch.object(store, "_dispatch", side_effect=RuntimeError("executor stopped")), \
                self.assertRaises(RuntimeError):
            store.submit(request=web.ReviewRequest(target="."), user=None)
        self.assertEqual(store._jobs, {})
        store._set_phase("missing", "analyzing")
        store.shutdown()

    def test_memory_cleanup_lifecycle(self):
        store = web.InMemoryReviewJobStore(result_ttl=0)
        with patch.object(store, "_dispatch"):
            job = store.submit(request=web.ReviewRequest(target="."), user=None)
        store._set_completed(job.id, {})
        store.start()
        store.start()
        time.sleep(1.1)
        self.assertEqual(store._jobs, {})
        store.shutdown()
        self.assertFalse(store._cleaner.is_alive())

    def test_scheduler_retries_after_sweep_error_and_shuts_down(self):
        from unittest.mock import Mock
        storage = Mock()
        storage.claim_job.return_value = None
        store = web.SupabaseBackedReviewJobStore(storage=storage)
        with patch.object(store, "sweep", side_effect=RuntimeError("offline")), \
                self.assertLogs("repo_review_agent.web", level="ERROR"):
            store.start()
            store.start()
            time.sleep(0.05)
            store.shutdown()
        self.assertFalse(store._scheduler.is_alive())
        with self.assertRaises(web.JobCapacityError):
            store.submit(request=web.ReviewRequest(target="."), user=None)

    def test_durable_admission_and_invalid_recovery_payload(self):
        from unittest.mock import Mock
        storage = Mock()
        storage.enqueue_job.return_value = None
        store = web.SupabaseBackedReviewJobStore(storage=storage)
        with self.assertRaises(web.JobCapacityError):
            store.submit(request=web.ReviewRequest(target="."), user=None)
        storage.claim_job.side_effect = [{"id": "bad", "request_json": {}}, None]
        store.sweep()
        self.assertEqual(store._leases, {})
        self.assertEqual(storage.write_claimed_job.call_args.kwargs["status"], "failed")
        store._leases["phase"] = "token"
        store._set_phase("phase", "analyzing")
        self.assertEqual(storage.write_claimed_job.call_args.kwargs["phase"], "analyzing")
        store.shutdown()

    def test_history_lease_rpc_payloads(self):
        from repo_review_agent.history import SupabaseReviewJobStore
        store = SupabaseReviewJobStore(supabase_url="https://example.test", service_key="secret")
        with patch.object(store, "_request", return_value=[{"id": "one"}]) as request:
            self.assertEqual(store.enqueue_job(target=".", request_payload={}, owner_id=None,
                                              max_pending=4, per_user_limit=2), {"id": "one"})
            self.assertEqual(request.call_args.args[2]["p_max_pending"], 4)
            self.assertEqual(store.claim_job(lease_token="token", lease_seconds=60), {"id": "one"})
            store.recover_jobs(result_ttl=3600)
            self.assertEqual(request.call_args.args[2], {"p_result_ttl": 3600})
            store.write_claimed_job("one", lease_token="token", phase="ai")
            self.assertNotIn("completed_at", request.call_args.args[2])
            request.return_value = []
            self.assertIsNone(store.claim_job(lease_token="token", lease_seconds=60))
            self.assertIsNone(store.enqueue_job(target=".", request_payload={}, owner_id=None,
                                               max_pending=4, per_user_limit=2))

    def test_sync_result_expiry_and_shutdown(self):
        from unittest.mock import Mock
        store = web.InMemoryReviewJobStore()
        with patch.object(store, "submit", return_value=Mock(id="one")), \
                patch.object(store, "get", return_value=None), \
                self.assertRaisesRegex(RuntimeError, "expired"):
            store.execute_sync(web.ReviewRequest(target="."), None)
        store.shutdown()
        with patch.object(store, "submit", return_value=Mock(id="one")), \
                self.assertRaisesRegex(RuntimeError, "shutting down"):
            store.execute_sync(web.ReviewRequest(target="."), None)

    def test_timeout_removes_partial_workspace(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        created = []

        def temporary(**kwargs):
            directory = TemporaryDirectory(**kwargs)
            created.append(Path(directory.name))
            return directory

        with patch("repo_review_agent.job_runtime.tempfile.TemporaryDirectory", side_effect=temporary), \
                self.assertRaisesRegex(RuntimeError, "deadline"):
            run_isolated({}, None, timeout=0.1,
                         command=[sys.executable, "-c", "import time; time.sleep(10)"])
        self.assertFalse(created[0].exists())

    def test_queue_saturation_maps_to_http_429_for_both_routes(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from fastapi import HTTPException
        storage = Mock()
        storage.submit.side_effect = web.JobCapacityError("full")
        storage.execute_sync.side_effect = web.JobCapacityError("full")
        with patch.object(web, "build_review_job_store", return_value=storage), \
                patch.object(web, "authenticated_user_from_request", return_value=None), \
                patch.object(web, "enforce_public_api_controls"):
            app = web.create_app()
            for route in app.routes:
                if route.path in {"/review", "/review/jobs"}:
                    with self.assertRaises(HTTPException) as error:
                        route.endpoint(SimpleNamespace(), web.ReviewRequest(target="."))
                    self.assertEqual(error.exception.status_code, 429)

    def test_watchdog_cleanup_does_not_signal_terminated_group_twice(self):
        from unittest.mock import Mock
        proc = Mock(pid=12345)
        proc.poll.return_value = -9

        def timer(interval, callback):
            result = Mock()
            result.start.side_effect = callback
            return result

        with patch("repo_review_agent.job_runtime.subprocess.Popen", return_value=proc), \
                patch("repo_review_agent.job_runtime.threading.Timer", side_effect=timer), \
                patch("repo_review_agent.job_runtime.os.killpg", side_effect=[None, PermissionError("dead group")]) as kill, \
                self.assertRaisesRegex(RuntimeError, "deadline"):
            run_isolated({}, None, timeout=0)
        kill.assert_called_once()
        proc.wait.assert_called_once()

    def test_cleanup_permission_error_only_ignored_for_dead_child(self):
        from unittest.mock import Mock
        for alive in (False, True):
            with self.subTest(alive=alive):
                proc = Mock(pid=12345)
                proc.poll.return_value = None if alive else -9
                expected = PermissionError if alive else RuntimeError
                with patch("repo_review_agent.job_runtime.subprocess.Popen", return_value=proc), \
                        patch("repo_review_agent.job_runtime.threading.Timer"), \
                        patch("repo_review_agent.job_runtime.os.killpg", side_effect=PermissionError("denied")), \
                        self.assertRaises(expected):
                    run_isolated({}, None, timeout=0)
                if not alive:
                    proc.wait.assert_called_once()
