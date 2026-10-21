"""Real transaction tests; only run against a disposable database named *_test."""

import copy
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

DSN = os.environ.get("REPO_REVIEW_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]


def payload():
    return {
        "owner_id": None,
        "repo_url": "owner/repo",
        "repo_name": "repo",
        "branch": "main",
        "commit_sha": None,
        "report_markdown": "# Report",
        "report": {
            "repo_name": "repo",
            "generated_at": "",
            "overview": [],
            "metrics": {"review_coverage": {"version": 1, "rules_complete": True}},
            "framework_signals": {},
            "ai_review": None,
            "findings": [
                {
                    "fingerprint": "one",
                    "title": "Risk",
                    "severity": "high",
                    "category": "security",
                    "evidence": ["bad"],
                    "evidence_paths": ["app.py"],
                    "recommendation": "Fix",
                    "source": "rule",
                    "rule_id": None,
                    "path": None,
                    "start_line": None,
                    "end_line": None,
                    "confidence": None,
                }
            ],
        },
    }


@unittest.skipUnless(DSN, "Requires disposable PostgreSQL database")
class AtomicHistoryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = psycopg.connect(DSN, autocommit=True)
        name = cls.db.execute("select current_database()").fetchone()[0]
        if not name.endswith("_test"):
            cls.db.close()
            raise RuntimeError("Refusing to modify a database without a _test suffix")
        cls.db.execute("""do $$ begin
          if not exists(select from pg_roles where rolname='anon') then create role anon; end if;
          if not exists(select from pg_roles where rolname='authenticated') then create role authenticated; end if;
          if not exists(select from pg_roles where rolname='service_role') then create role service_role bypassrls; end if;
        end $$;
        create schema if not exists auth;
        create table if not exists auth.users(id uuid primary key);
        create or replace function auth.uid() returns uuid language sql stable as
          'select nullif(current_setting(''request.jwt.claim.sub'',true),'''')::uuid';
        grant usage on schema auth to authenticated;
        """)
        for migration in sorted((ROOT / "supabase/migrations").glob("*.sql")):
            if os.environ.get("REPO_REVIEW_TEST_PRE_ATOMIC") and migration.name.startswith(
                "20261006"
            ):
                continue
            cls.db.execute(migration.read_text())

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        self.db.execute("truncate repositories, review_jobs, auth.users cascade")
        if not os.environ.get("REPO_REVIEW_TEST_PRE_ATOMIC"):
            self.db.execute("truncate review_history_operations")

    def save(self, value=None, operation=None, job=None, lease=None, result=None, db=None):
        return (
            (db or self.db)
            .execute(
                "select save_review_history(%s,%s,%s,%s,%s)",
                (
                    Jsonb(value or payload()),
                    operation or uuid.uuid4(),
                    job,
                    lease,
                    Jsonb(result) if result is not None else None,
                ),
            )
            .fetchone()[0]
        )

    def test_question_capacity_rate_and_expired_lease_recovery(self):
        owner, other = uuid.uuid4(), uuid.uuid4()
        self.db.execute("insert into auth.users(id) values (%s),(%s)", (owner, other))
        def acquire(user, global_limit=1, rate=2):
            return self.db.execute(
                "select acquire_review_question(%s,%s,1,%s,10)", (user, global_limit, rate)
            ).fetchone()[0]
        lease = acquire(owner)
        self.assertIsNotNone(lease)
        self.assertIsNone(acquire(owner))
        self.assertIsNone(acquire(other))
        self.db.execute("select release_review_question(%s)", (lease,))
        second = acquire(owner)
        self.assertIsNotNone(second)
        self.db.execute("select release_review_question(%s)", (second,))
        self.assertIsNone(acquire(owner))  # Completed calls still count toward rate.
        other_lease = acquire(other)
        self.assertIsNotNone(other_lease)
        self.db.execute("update review_question_leases set expires_at=now()-interval '1 second'")
        self.assertIsNotNone(acquire(other))

    def test_question_concurrent_workers_and_unprivileged_access(self):
        owner = uuid.uuid4()
        self.db.execute("insert into auth.users(id) values (%s)", (owner,))
        def acquire(_):
            with psycopg.connect(DSN, autocommit=True) as db:
                return db.execute("select acquire_review_question(%s,1,1,10,10)", (owner,)).fetchone()[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(value is not None for value in pool.map(acquire, range(4))), 1)
        with self.db.transaction():
            self.db.execute("set local role authenticated")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege), self.db.transaction():
                self.db.execute("select acquire_review_question(%s,1,1,10,10)", (owner,))

    def test_full_transaction_rolls_back_after_run_insert(self):
        value = payload()
        value["report"]["findings"][0]["severity"] = "invalid"
        with self.assertRaises(psycopg.Error):
            self.save(value)
        self.assertEqual(self.db.execute("select count(*) from review_runs").fetchone()[0], 0)
        self.assertEqual(self.db.execute("select count(*) from repositories").fetchone()[0], 0)
        self.assertEqual(
            self.db.execute("select count(*) from review_history_operations").fetchone()[0], 0
        )

    def test_retry_after_lost_response_and_payload_conflict(self):
        operation = uuid.uuid4()
        first = self.save(operation=operation)
        self.assertEqual(self.save(operation=operation), first)
        self.assertEqual(first["health_score"], 75)
        self.assertEqual(self.db.execute("select count(*) from review_runs").fetchone()[0], 1)
        other = payload()
        other["repo_name"] = "changed"
        with self.assertRaisesRegex(psycopg.Error, "conflicts"):
            self.save(other, operation=operation)

    def test_concurrent_first_save_serializes_comparison_and_repository(self):
        def save_new(_):
            with psycopg.connect(DSN, autocommit=True) as db:
                return self.save(db=db)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save_new, range(2)))
        self.assertEqual(self.db.execute("select count(*) from repositories").fetchone()[0], 1)
        self.assertEqual(self.db.execute("select count(*) from review_runs").fetchone()[0], 2)
        self.assertEqual(sorted(r["new_findings_count"] for r in results), [0, 1])
        self.assertEqual(sorted(r["existing_findings_count"] for r in results), [0, 1])

    def test_concurrent_duplicate_operation_creates_one_run(self):
        operation = uuid.uuid4()

        def save_same(_):
            with psycopg.connect(DSN, autocommit=True) as db:
                return self.save(operation=operation, db=db)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save_same, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.db.execute("select count(*) from review_runs").fetchone()[0], 1)

    def test_feedback_owner_isolation_and_resolved_findings(self):
        owner, other = uuid.uuid4(), uuid.uuid4()
        self.db.execute("insert into auth.users values(%s),(%s)", (owner, other))
        value = payload()
        value["owner_id"] = str(owner)
        first = self.save(value)
        self.db.execute(
            "insert into finding_feedback(repository_id,owner_id,fingerprint,status) values(%s,%s,'one','ignored')",
            (first["repository_id"], owner),
        )
        second = self.save(value)
        self.assertEqual(second["health_score"], 100)
        self.assertEqual(second["existing_findings_count"], 1)
        value["owner_id"] = str(other)
        third = self.save(value)
        self.assertNotEqual(third["repository_id"], first["repository_id"])
        self.assertEqual(third["health_score"], 75)
        value["owner_id"] = str(owner)
        value["report"]["findings"] = []
        resolved = self.save(value)
        self.assertEqual(resolved["resolved_findings_count"], 1)
        self.assertEqual(resolved["comparison"]["resolved_findings"][0]["fingerprint"], "one")
        self.db.execute("set role authenticated")
        try:
            self.db.execute("select set_config('request.jwt.claim.sub',%s,false)", (str(other),))
            self.assertEqual(self.db.execute("select count(*) from repositories").fetchone()[0], 1)
            with self.assertRaises(psycopg.Error):
                self.save(value)
        finally:
            self.db.execute("reset role")

    def create_job(self, status="running", token="current", expired=False):
        job = uuid.uuid4()
        self.db.execute(
            """insert into review_jobs(id,status,target,lease_token,lease_expires_at)
            values(%s,%s,'owner/repo',%s,now()+ %s * interval '1 second')""",
            (job, status, token, -1 if expired else 60),
        )
        return job

    def test_stale_cancelled_and_expired_workers_cannot_save_history(self):
        for status, token, expired in [
            ("cancelled", "current", False),
            ("running", "new", False),
            ("running", "current", True),
        ]:
            job = self.create_job(status, token, expired)
            with (
                self.subTest(status=status, token=token, expired=expired),
                self.assertRaisesRegex(psycopg.Error, "lease"),
            ):
                self.save(
                    operation=job, job=job, lease="current", result={"report": payload()["report"]}
                )
        self.assertEqual(self.db.execute("select count(*) from review_runs").fetchone()[0], 0)

    def test_job_and_history_commit_together_and_retry_succeeds(self):
        job = self.create_job()
        response = {"report": payload()["report"], "markdown": "# Report"}
        saved = self.save(operation=job, job=job, lease="current", result=response)
        row = self.db.execute(
            "select status,result_json from review_jobs where id=%s", (job,)
        ).fetchone()
        self.assertEqual(row[0], "completed")
        self.assertEqual(row[1]["history"]["review_run_id"], saved["review_run_id"])
        self.assertEqual(self.save(operation=job, job=job, lease="current", result=response), saved)
        job2 = self.create_job()
        broken = copy.deepcopy(payload())
        broken["report"]["findings"][0]["severity"] = "invalid"
        with self.assertRaises(psycopg.Error):
            self.save(broken, operation=job2, job=job2, lease="current", result=response)
        self.assertEqual(
            self.db.execute("select status from review_jobs where id=%s", (job2,)).fetchone()[0],
            "running",
        )
        self.assertEqual(self.db.execute("select count(*) from review_runs").fetchone()[0], 1)

    def test_python_projection_persists_ai_and_redacts_every_report_table(self):
        from repo_review_agent.history import SupabaseHistoryStore
        from repo_review_agent.models import AIReview, Finding, ReviewReport

        secret = "sk-" + "a" * 36
        report = ReviewReport(
            "repo",
            "",
            [secret],
            {"note": secret},
            {"x": [secret]},
            [Finding("Risk", "high", "security", [secret], secret)],
            AIReview(
                "openai",
                "test",
                "generated",
                secret,
                findings=[
                    {
                        "title": "Unsafe SQL",
                        "severity": "high",
                        "path": "app.py",
                        "start_line": 1,
                        "end_line": 1,
                        "evidence": "query(raw)",
                        "recommendation": "Bind",
                        "confidence": 0.9,
                    }
                ],
            ),
        )
        database = self.db

        class SQLTransport(SupabaseHistoryStore):
            def _request(self, method, path, body=None, **kwargs):
                if (method, path) != ("POST", "rpc/save_review_history"):
                    raise AssertionError("Expected one history transaction")
                return database.execute(
                    "select save_review_history(%s,%s)",
                    (Jsonb(body["p_payload"]), body["p_operation"]),
                ).fetchone()[0]

        store = SQLTransport(supabase_url="unused", service_key="unused")
        first = store.save_report(report=report, repo_url="owner/repo", report_markdown=secret)
        self.assertEqual(first.health_score, 50)
        self.assertEqual(len(first.comparison.new_findings), 2)
        ai = self.db.execute(
            "select path,start_line,end_line,confidence,evidence_json from findings where source='ai'"
        ).fetchone()
        self.assertEqual(ai, ("app.py", 1, 1, 0.9, ["query(raw)"]))
        second = store.save_report(report=report, repo_url="owner/repo", report_markdown=secret)
        self.assertEqual(len(second.comparison.existing_findings), 2)
        for table in ["review_runs", "findings", "ai_reviews", "review_history_operations"]:
            # Table names are fixed test literals, never request input.
            rows = self.db.execute(f"select row_to_json(t)::text from {table} t").fetchall()
            self.assertNotIn(secret, str(rows))

    def test_cancellation_winning_row_lock_prevents_history_commit(self):
        from concurrent.futures import TimeoutError

        job = self.create_job()

        def complete():
            with psycopg.connect(DSN, autocommit=True) as db:
                return self.save(
                    operation=job,
                    job=job,
                    lease="current",
                    result={"report": payload()["report"]},
                    db=db,
                )

        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.db.transaction():
                self.db.execute("update review_jobs set status='cancelled' where id=%s", (job,))
                future = pool.submit(complete)
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.1)
            with self.assertRaisesRegex(psycopg.Error, "lease"):
                future.result(timeout=3)
        self.assertEqual(self.db.execute("select count(*) from review_runs").fetchone()[0], 0)

    def test_service_role_can_execute_but_owner_reuse_is_rejected(self):
        owner = uuid.uuid4()
        self.db.execute("insert into auth.users values(%s)", (owner,))
        operation = uuid.uuid4()
        self.db.execute("set role service_role")
        try:
            self.assertEqual(self.save(operation=operation)["health_score"], 75)
            value = payload()
            value["owner_id"] = str(owner)
            with self.assertRaisesRegex(psycopg.Error, "conflicts"):
                self.save(value, operation=operation)
        finally:
            self.db.execute("reset role")

    def test_partial_runs_retain_unknown_until_rechecked(self):
        first = payload()
        first['report']['metrics']['review_coverage'] = {
            'version': 1, 'inventory_complete': True, 'inventory_paths': ['app.py'],
            'rules_complete': True, 'ruff_complete': False}
        self.save(first)
        partial = copy.deepcopy(first)
        partial['report']['findings'] = []
        partial['report']['metrics']['review_coverage']['rules_complete'] = False
        for _ in range(2):
            result = self.save(partial)
            self.assertEqual(result['resolved_findings_count'], 0)
            self.assertEqual(result['unverified_findings_count'], 1)
        reappeared = self.save(first)
        self.assertEqual(reappeared['existing_findings_count'], 1)
        self.assertEqual(reappeared['new_findings_count'], 0)
        self.save(partial)
        fixed = copy.deepcopy(first)
        fixed['report']['findings'] = []
        result = self.save(fixed)
        self.assertEqual(result['resolved_findings_count'], 1)
        self.assertEqual(result['unverified_findings_count'], 0)

    def test_unknown_retains_original_policy_across_runs(self):
        value = payload()
        value['report']['metrics']['review_coverage'] = {
            'version': 1, 'inventory_complete': True, 'inventory_paths': ['app.py'],
            'rules_complete': True}
        self.save(value)
        value['report']['findings'] = []
        value['report']['metrics']['policy_config'] = {'ignore': ['vendor/**']}
        for _ in range(2):
            result = self.save(value)
            self.assertEqual(result['resolved_findings_count'], 0)
            self.assertEqual(result['unverified_findings_count'], 1)

    def test_resolution_decisions_match_python_for_optional_checks_and_deletion(self):
        from repo_review_agent.models import Finding, ReviewReport
        from repo_review_agent.resolution import finding_rechecked

        coverage = {'version': 1, 'inventory_complete': True, 'inventory_paths': ['app.py'],
                    'rules_complete': True, 'ruff_complete': False}
        policy = {'ignore': [], 'disabled_rules': [], 'disabled_categories': [], 'severity_overrides': {}}
        cases = [
            ('rule', 'Risk', None, {}, coverage, True),
            ('ai', 'AI risk', None, {}, coverage, False),
            ('rule', 'Fix 1 Ruff F821 lint finding(s)', None, {}, coverage, False),
            ('rule', 'Fix 1 Ruff F821 lint finding(s)', None, {}, {**coverage, 'ruff_complete': True}, True),
            ('rule', 'Vulnerability', 'dependency.osv', {'vulnerability_scan': {'status': 'partial'}}, coverage, False),
            ('rule', 'Vulnerability', 'dependency.osv', {'vulnerability_scan': {'status': 'clean'}}, coverage, True),
            ('rule', 'Vulnerability', 'dependency.osv', {'vulnerability_scan': {'status': 'clean'}}, {**coverage, 'inventory_complete': False}, False),
            ('rule', 'Risk', None, {'policy_config': {'ignore': ['vendor/**']}}, coverage, False),
            ('ai', 'AI risk', None, {}, {**coverage, 'rules_complete': False, 'inventory_paths': []}, True),
            ('rule', 'Risk', None, {}, {**coverage, 'rules_complete': False, 'inventory_complete': False, 'inventory_paths': []}, False),
            ('rule', 'Risk', None, {}, {}, False),
        ]
        for source, title, rule, extra, current_coverage, expected in cases:
            with self.subTest(source=source, title=title, extra=extra, coverage=current_coverage):
                finding = Finding(title, 'high', 'code', ['bad'], 'Fix', ['app.py'], source=source, rule_id=rule)
                previous = ReviewReport('repo', '', [], {'review_coverage': coverage}, {}, [finding])
                current = ReviewReport('repo', '', [], {'review_coverage': current_coverage, **extra}, {}, [])
                self.assertIs(finding_rechecked(finding, current, previous), expected)
                row = previous.to_dict()['findings'][0]
                row['resolution_context'] = {'policy': policy, 'evidence_was_present': True}
                sql_result = self.db.execute('select review_finding_rechecked(%s,%s)',
                                             (Jsonb(current.to_dict()), Jsonb(row))).fetchone()[0]
                self.assertIs(sql_result, expected)
