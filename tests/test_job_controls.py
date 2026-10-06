import sys
import threading
import time
import unittest
from unittest.mock import patch

from repo_review_agent import web
from repo_review_agent.auth import AuthUser
from repo_review_agent.job_runtime import run_isolated


class JobControlTests(unittest.TestCase):
    def test_cancelled_queued_job_never_executes_and_terminal_result_cannot_overwrite(self):
        store = web.InMemoryReviewJobStore(max_workers=1)
        self.addCleanup(store.shutdown)
        with patch.object(store, '_dispatch'):
            job = store.submit(request=web.ReviewRequest(target='.'), user=AuthUser('owner'))
        cancelled = store.cancel(job.id, 'owner')
        self.assertEqual(cancelled.status, 'cancelled')
        with patch.object(store, '_execute', side_effect=AssertionError('must not execute')):
            store._run(job.id, web.ReviewRequest(target='.'), AuthUser('owner'))
        store._set_completed(job.id, {'unsafe': True})
        self.assertEqual(store.get(job.id).status, 'cancelled')
        self.assertIsNone(store.get(job.id).result)

    def test_cancellation_checks_owner_before_mutating(self):
        store = web.InMemoryReviewJobStore()
        self.addCleanup(store.shutdown)
        with patch.object(store, '_dispatch'):
            job = store.submit(request=web.ReviewRequest(target='.'), user=AuthUser('owner'))
        with self.assertRaises(PermissionError):
            store.cancel(job.id, 'stranger')
        self.assertEqual(store.get(job.id).status, 'queued')

    def test_cancel_signal_kills_actual_worker_promptly(self):
        cancelled = threading.Event()
        timer = threading.Timer(.15, cancelled.set)
        timer.start()
        self.addCleanup(timer.join)
        start = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            run_isolated({}, None, timeout=10, cancelled=cancelled.is_set,
                         command=[sys.executable, '-c', 'import time; time.sleep(30)'])
        self.assertLess(time.monotonic() - start, 2)

    def test_daily_admission_quota_survives_job_expiration(self):
        store = web.InMemoryReviewJobStore(daily_limit=1, result_ttl=0)
        self.addCleanup(store.shutdown)
        with patch.object(store, '_dispatch'):
            job = store.submit(request=web.ReviewRequest(target='.'), user=AuthUser('owner'))
            store._set_completed(job.id, {})
            self.assertIsNone(store.get(job.id))
            with self.assertRaises(web.JobCapacityError):
                store.submit(request=web.ReviewRequest(target='.'), user=AuthUser('owner'))
            self.assertIsNotNone(store.submit(request=web.ReviewRequest(target='.'), user=AuthUser('other')))

    def test_budget_rejects_zero_and_excessive_values(self):
        for budget in [0, 200001]:
            with self.assertRaises(ValueError):
                web.ReviewRequest(target='.', ai_token_budget=budget)

class ControlRouteTests(unittest.TestCase):
    def endpoint(self, app, path):
        return next(route.endpoint for route in app.routes if route.path == path)

    def test_cancel_route_requires_auth_and_returns_terminal_status(self):
        from types import SimpleNamespace

        from fastapi import HTTPException
        store = web.InMemoryReviewJobStore()
        self.addCleanup(store.shutdown)
        with patch.object(store, '_dispatch'):
            job = store.submit(request=web.ReviewRequest(target='.'), user=AuthUser('owner'))
        with patch.object(web, 'build_review_job_store', return_value=store):
            app = web.create_app()
        cancel = self.endpoint(app, '/review/jobs/{job_id}/cancel')
        with patch.object(web, 'authenticated_user_from_request', return_value=AuthUser('other')):
            with self.assertRaises(HTTPException) as error:
                cancel(SimpleNamespace(), job.id)
            self.assertEqual(error.exception.status_code, 403)
        with patch.object(web, 'authenticated_user_from_request', return_value=AuthUser('owner')):
            self.assertEqual(cancel(SimpleNamespace(), job.id)['status'], 'cancelled')

    def test_feedback_writes_owner_and_validated_status(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        fake = Mock()
        fake.set_finding_feedback.return_value = {'status': 'ignored', 'reason': 'accepted risk'}
        with patch.object(web, 'authenticated_user_from_request', return_value=AuthUser('owner')), \
             patch.object(web.SupabaseHistoryStore, 'from_env', return_value=fake):
            route = self.endpoint(web.create_app(), '/history/repositories/{repository_id}/findings/{fingerprint}/feedback')
            result = route(SimpleNamespace(), 'repo', 'fp', web.FindingFeedbackRequest(status='ignored', reason='accepted risk'))
        self.assertEqual(result['status'], 'ignored')
        self.assertEqual(fake.set_finding_feedback.call_args.kwargs['owner_id'], 'owner')

    def test_questions_deny_other_owners_report(self):
        from types import SimpleNamespace

        from fastapi import HTTPException
        store = web.InMemoryReviewJobStore()
        self.addCleanup(store.shutdown)
        with patch.object(store, '_dispatch'):
            job = store.submit(request=web.ReviewRequest(target='.'), user=AuthUser('owner'))
        store._set_completed(job.id, {'report': {'findings': []}})
        with patch.object(web, 'build_review_job_store', return_value=store):
            app = web.create_app()
        route = self.endpoint(app, '/review/questions')
        with patch.object(web, 'authenticated_user_from_request', return_value=AuthUser('other')):
            with self.assertRaises(HTTPException) as error:
                route(SimpleNamespace(headers={}), web.ReportQuestionRequest(job_id=job.id, question='Why?'))
            self.assertEqual(error.exception.status_code, 403)

    def test_durable_question_quota_calls_correct_postgrest_rpc(self):
        from repo_review_agent.history import SupabaseReviewJobStore
        calls = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'true'
        def request(req, **kwargs):
            calls.append(req.full_url)
            return Response()
        storage = SupabaseReviewJobStore(supabase_url='https://example.supabase.co',service_key='test')
        store = web.SupabaseBackedReviewJobStore(storage=storage)
        self.addCleanup(store.shutdown)
        with patch('repo_review_agent.history.urlopen', request):
            store.admit_question('owner')
        self.assertEqual(calls, ['https://example.supabase.co/rest/v1/rpc/admit_review_question'])


class ControlHTTPTests(unittest.TestCase):
    def setUp(self):
        import os

        from fastapi.testclient import TestClient
        self.env = patch.dict(os.environ, {'REPO_REVIEW_REQUIRE_AUTH': 'false',
                                           'REPO_REVIEW_API_TOKEN': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        web.WEB_AUTH_CACHE.clear()
        self.addCleanup(web.WEB_AUTH_CACHE.clear)
        self.store = web.InMemoryReviewJobStore(daily_limit=2)
        self.addCleanup(self.store.shutdown)
        with patch.object(web, 'build_review_job_store', return_value=self.store):
            self.client = TestClient(web.create_app())
        self.addCleanup(self.client.close)
        auth = patch.object(web, 'get_supabase_user', side_effect=lambda token: AuthUser(token))
        auth.start()
        self.addCleanup(auth.stop)
        self.headers = {'Authorization': 'Bearer owner'}
        self.report = {'findings': [{'path': 'app.py', 'start_line': 2, 'end_line': 2,
                                    'title': 'Unsafe evaluation', 'evidence': ['eval(input())'],
                                    'recommendation': 'Parse input without executing it.'}]}

    def job(self, status='completed', owner='owner'):
        with patch.object(self.store, '_dispatch'):
            job = self.store.submit(request=web.ReviewRequest(target='.'), user=AuthUser(owner))
        if status == 'completed':
            self.store._set_completed(job.id, {'report': self.report})
        return job

    def ask(self, **kwargs):
        return self.client.post('/review/questions', json={'question': 'Why unsafe evaluation?', **kwargs},
                                headers=self.headers)

    def test_completed_owned_report_answers_offline_with_real_citations(self):
        response = self.ask(job_id=self.job().id)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Parse input', response.json()['answer'])
        self.assertEqual(response.json()['citations'][0]['path'], 'app.py')
        self.assertIsNone(response.json()['usage'])

    def test_anonymous_offline_report_and_insufficient_evidence(self):
        response = self.client.post('/review/questions', json={'question': 'Why?', 'report': {'findings': []}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['citations'], [])
        self.assertIn('insufficient', response.json()['answer'])

    def test_ai_requires_login_before_provider_or_admission(self):
        with patch.object(self.store, 'admit_question') as admission:
            response = self.client.post('/review/questions', json={'question': 'Why?', 'report': self.report,
                                                                  'provider': 'openai'})
        self.assertEqual(response.status_code, 401)
        admission.assert_not_called()

    def test_api_token_is_checked_for_questions(self):
        import os
        with patch.dict(os.environ, {'REPO_REVIEW_API_TOKEN': 'shared-secret'}):
            self.assertEqual(self.ask(report=self.report).status_code, 401)
            response = self.client.post('/review/questions', json={'question': 'Why?', 'report': self.report},
                                        headers={**self.headers, 'X-Repo-Review-Token': 'shared-secret'})
        self.assertEqual(response.status_code, 200)

    def test_question_job_absence_owner_and_state_are_checked(self):
        self.assertEqual(self.ask(job_id='missing').status_code, 404)
        queued = self.job(status='queued')
        self.assertEqual(self.ask(job_id=queued.id).status_code, 409)
        response = self.client.post('/review/questions', json={'question': 'Why?', 'job_id': queued.id},
                                    headers={'Authorization': 'Bearer stranger'})
        self.assertEqual(response.status_code, 403)

    def test_question_and_utf8_report_boundaries_fail_before_admission(self):
        with patch.object(self.store, 'admit_question') as admission:
            for payload in [{'question': ' ', 'report': self.report},
                            {'question': 'x' * 2001, 'report': self.report}, {},
                            {'report': {'blob': '中' * 70000}}, {'provider': 'unknown'},
                            {'token_budget': 0}, {'token_budget': 20001}]:
                with self.subTest(payload=list(payload)):
                    response = self.ask(**payload)
                    self.assertEqual(response.status_code, 422)
        admission.assert_not_called()

    def test_ai_daily_quota_rejects_without_calling_provider(self):
        from repo_review_agent.questions import answer_report_question
        self.store.admit_question('owner')
        self.store.admit_question('owner')
        with patch('repo_review_agent.questions.answer_report_question', wraps=answer_report_question) as answer:
            response = self.ask(report=self.report, provider='openai')
        self.assertEqual(response.status_code, 429)
        answer.assert_not_called()

    def test_ai_success_admits_owner_and_passes_bounded_options(self):
        expected = {'answer': 'Known evidence', 'citations': [], 'limitations': [], 'usage': {}}
        with patch('repo_review_agent.questions.answer_report_question', return_value=expected) as answer:
            response = self.ask(report=self.report, provider='openai', model='test', token_budget=1000)
        self.assertEqual(response.json(), expected)
        self.assertEqual(self.store._daily_usage[(web._utc_now()[:10], 'owner')], 1)
        self.assertEqual(answer.call_args.kwargs['token_budget'], 1000)
        self.assertEqual(answer.call_args.kwargs['model'], 'test')

    def test_storage_failures_are_sanitized_for_questions_and_cancellation(self):
        from repo_review_agent.history import HistoryStoreError
        failure = HistoryStoreError('private database credential detail')
        with patch.object(self.store, 'get', side_effect=failure):
            response = self.ask(job_id='stored-job')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private', response.text)
        with patch.object(self.store, 'cancel', side_effect=failure):
            response = self.client.post('/review/jobs/stored-job/cancel', headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private', response.text)
        with patch.object(self.store, 'admit_question', side_effect=failure):
            response = self.ask(report=self.report, provider='openai')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private', response.text)

    def test_provider_and_validation_errors_have_controlled_http_responses(self):
        from repo_review_agent.provider import AIProviderError
        for error in [AIProviderError('Provider unavailable.'), ValueError('Invalid report.')]:
            with self.subTest(error=type(error).__name__), patch(
                    'repo_review_agent.questions.answer_report_question', side_effect=error):
                self.assertEqual(self.ask(report=self.report).status_code, 400)

    def test_cancel_http_login_absent_owner_and_terminal_semantics(self):
        self.assertEqual(self.client.post('/review/jobs/missing/cancel').status_code, 401)
        self.assertEqual(self.client.post('/review/jobs/missing/cancel', headers=self.headers).status_code, 404)
        job = self.job()
        response = self.client.post(f'/review/jobs/{job.id}/cancel', headers={'Authorization': 'Bearer stranger'})
        self.assertEqual(response.status_code, 403)
        response = self.client.post(f'/review/jobs/{job.id}/cancel', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'completed')
        self.assertEqual(response.json()['result']['report'], self.report)


class DurableControlTests(unittest.TestCase):
    def storage(self, row):
        from unittest.mock import Mock
        storage = Mock()
        storage.get_job.return_value = row
        store = web.SupabaseBackedReviewJobStore(storage=storage)
        self.addCleanup(store.shutdown)
        return store, storage

    def row(self, status='running'):
        return {'id': 'job', 'owner_id': 'owner', 'status': status, 'target': '.',
                'created_at': web._utc_now(), 'updated_at': web._utc_now()}

    def test_cancel_checks_durable_owner_and_absence_before_rpc(self):
        store, storage = self.storage(None)
        self.assertIsNone(store.cancel('job', 'owner'))
        storage.request_cancel.assert_not_called()
        storage.get_job.return_value = self.row()
        for owner in ['stranger', None]:
            with self.assertRaises(PermissionError):
                store.cancel('job', owner)
        storage.request_cancel.assert_not_called()

    def test_cancel_persists_and_worker_monitor_observes_cancellation(self):
        from repo_review_agent.history import SupabaseReviewJobStore
        storage = SupabaseReviewJobStore(supabase_url='https://example.supabase.co', service_key='test')
        store = web.SupabaseBackedReviewJobStore(storage=storage)
        self.addCleanup(store.shutdown)
        running, cancelled = self.row(), self.row('cancelled')
        def request(method, path, payload=None, **kwargs):
            if path == 'rpc/cancel_review_job':
                self.assertEqual(payload, {'p_job': 'job', 'p_owner': 'owner'})
                return [cancelled]
            return [running]
        with patch.object(storage, '_request', side_effect=request):
            self.assertEqual(store.cancel('job', 'owner').status, 'cancelled')
        with patch.object(storage, '_request', return_value=[cancelled]):
            self.assertTrue(store._is_cancelled('job'))

    def test_durable_cancel_handles_no_return_row_and_terminal_report(self):
        store, storage = self.storage(self.row('completed'))
        storage.request_cancel.return_value = None
        self.assertIsNone(store.cancel('job', 'owner'))
        completed = {**self.row('completed'), 'result_json': {'report': {'findings': []}}}
        storage.request_cancel.return_value = completed
        self.assertEqual(store.cancel('job', 'owner').result, completed['result_json'])

    def test_durable_question_false_admission_rejects_quota(self):
        store, storage = self.storage(None)
        storage._request.return_value = False
        with self.assertRaises(web.JobCapacityError):
            store.admit_question('owner')

    def test_question_only_usage_prunes_previous_days(self):
        store = web.InMemoryReviewJobStore(daily_limit=1)
        self.addCleanup(store.shutdown)
        with patch.object(web, '_utc_now', return_value='2026-10-05T00:00:00+00:00'):
            store.admit_question('owner')
        with patch.object(web, '_utc_now', return_value='2026-10-06T00:00:00+00:00'):
            store.admit_question('owner')
        self.assertEqual(store._daily_usage, {('2026-10-06', 'owner'): 1})

    def test_store_cancellation_monitor_captures_worker_job_identity(self):
        from repo_review_agent import job_runtime
        store=web.InMemoryReviewJobStore()
        self.addCleanup(store.shutdown)
        store.timeout=2
        with patch.object(store,'_dispatch'):
            job=store.submit(request=web.ReviewRequest(target='.'),user=AuthUser('owner'))
        store._worker_context.job_id=job.id
        timer=threading.Timer(.1,lambda:store.cancel(job.id,'owner'))
        timer.start()
        self.addCleanup(timer.join)
        original=job_runtime.run_isolated
        def isolated(*args,**kwargs):
            return original(*args,**kwargs,command=[sys.executable,'-c','import time; time.sleep(30)'])
        begin=time.monotonic()
        with patch('repo_review_agent.web.run_isolated',isolated),self.assertRaisesRegex(RuntimeError,'cancelled'):
            store._execute(web.ReviewRequest(target='.'),AuthUser('owner'))
        self.assertLess(time.monotonic()-begin,1.5)
