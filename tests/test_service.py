import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fake_model import ScriptedModel, final

from repo_review_agent.llm import AIProviderError


class ReviewServiceTests(unittest.TestCase):
    def test_all_modes_share_report_contract(self):
        from repo_review_agent.service import run_review

        for mode, label in [
            ("direct", None),
            ("agent", None),
            ("function-calling", "openai-functions"),
            ("chatgpt-agent", "chatgpt-api"),
        ]:
            with (
                self.subTest(mode=mode),
                TemporaryDirectory() as tmp,
                patch(
                    "repo_review_agent.agent.create_chat_model",
                    return_value=ScriptedModel(responses=[final()]),
                ),
            ):
                root = Path(tmp)
                report = run_review(root, mode=mode, ai_model="test")
                self.assertEqual(report.repo_name, root.name)
                if label:
                    self.assertEqual(report.ai_review.provider, label)
                else:
                    self.assertIsNone(report.ai_review)

    def test_direct_failure_policy(self):
        from repo_review_agent.service import run_review

        with (
            TemporaryDirectory() as tmp,
            patch(
                "repo_review_agent.service.add_ai_review", side_effect=AIProviderError("offline")
            ),
        ):
            report = run_review(Path(tmp), mode="direct", ai_provider="ollama")
            self.assertEqual(report.ai_review.status, "error")
            with self.assertRaises(AIProviderError):
                run_review(Path(tmp), mode="direct", ai_provider="ollama", fail_on_ai_error=True)

    def test_linter_option_reaches_analysis_in_every_mode(self):
        from repo_review_agent.models import Finding
        from repo_review_agent.service import run_review

        finding = Finding("linter issue", "low", "style", ["ruff"], "fix")
        for mode in ("direct", "agent", "function-calling", "chatgpt-agent"):
            with (
                self.subTest(mode=mode),
                TemporaryDirectory() as tmp,
                patch("repo_review_agent.analyzer.collect_linter_findings", return_value=[finding]),
                patch(
                    "repo_review_agent.agent.create_chat_model",
                    return_value=ScriptedModel(responses=[final()]),
                ),
            ):
                report = run_review(Path(tmp), mode=mode, run_linters=True)
                self.assertIn(finding, report.findings)

    def test_unknown_mode(self):
        from repo_review_agent.service import run_review

        with self.assertRaises(ValueError):
            run_review(Path("."), mode="unknown")

    def test_direct_ai_progress_occurs_before_provider_call(self):
        from repo_review_agent.service import run_review
        phases = []
        def enrich(report, **kwargs):
            self.assertEqual(phases, ['analyzing', 'ai'])
            return report
        with TemporaryDirectory() as tmp, patch('repo_review_agent.service.add_ai_review', enrich):
            run_review(Path(tmp), mode='direct', ai_provider='ollama', on_progress=phases.append)

    def test_project_ignore_applies_to_all_runtime_modes(self):
        import json

        from repo_review_agent.service import run_review
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'private').mkdir()
            (root / 'private' / 'secret.py').write_text('print(1)')
            (root / '.repo-review.json').write_text(json.dumps({'ignore':['private/**']}))
            for mode in ('direct','agent','function-calling','chatgpt-agent'):
                with self.subTest(mode=mode), patch('repo_review_agent.agent.create_chat_model', return_value=ScriptedModel(responses=[final()])):
                    report = run_review(root, mode=mode, trust_repository_config=True)
                self.assertEqual(report.metrics['source_files'], 0)
                self.assertNotIn('private/secret.py', str(report.to_dict()))

    def test_vulnerability_scan_is_opt_in_and_reaches_report(self):
        from types import SimpleNamespace

        from repo_review_agent.models import Finding
        from repo_review_agent.service import run_review
        finding = Finding('Known dependency flaw', 'medium','dependency vulnerabilities',['OSV-X'],'upgrade')
        with TemporaryDirectory() as tmp, patch('repo_review_agent.service.scan_vulnerabilities', return_value=SimpleNamespace(
            findings=[finding],status='findings',details=[],checked_packages=1,total_packages=1
        )):
            ordinary = run_review(Path(tmp), mode='direct')
            scanned = run_review(Path(tmp), mode='direct', vulnerability_scan=True)
        self.assertNotIn(finding, ordinary.findings)
        self.assertIn(finding, scanned.findings)
        self.assertEqual(scanned.metrics['vulnerability_scan']['status'], 'findings')
