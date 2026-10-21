import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from repo_review_agent.findings import effective_findings, review_findings
from repo_review_agent.i18n import localize_report
from repo_review_agent.models import AIReview, ReviewReport
from repo_review_agent.persistence import restore_report
from repo_review_agent.pr_bot import load_report_json


def ai_report():
    return ReviewReport("example", "", [], {}, {}, [], AIReview(
        "mock", "mock", "generated", "", findings=[{
            "title": "Add automated tests for the core behavior",
            "severity": "high", "category": "testing",
            "evidence": "sk-abcdefghijk", "recommendation": "Add tests",
            "path": "app.py", "start_line": 1, "end_line": 1,
        }],
    ))


class FindingIdentityTests(unittest.TestCase):
    def test_feedback_survives_translation_redaction_and_repeated_reload(self):
        for status in ("ignored", "false_positive"):
            for language in ("en", "zh-CN"):
                with self.subTest(status=status, language=language):
                    report = ai_report()
                    identity = review_findings(report)[0].fingerprint
                    report = replace(report, finding_feedback=[
                        {"fingerprint": identity, "status": status},
                    ])
                    for _ in range(3):
                        report = localize_report(restore_report(report.to_dict()), language)
                        self.assertEqual(len(review_findings(report)), 1)
                        self.assertEqual(review_findings(report)[0].fingerprint, identity)
                        self.assertEqual(effective_findings(report), [])
                        self.assertNotIn("sk-abcdefghijk", json.dumps(report.to_dict()))

    def test_pr_json_reload_preserves_localized_identity(self):
        original = ai_report()
        identity = review_findings(original)[0].fingerprint
        original = replace(original, finding_feedback=[
            {"fingerprint": identity, "status": "ignored"},
        ])
        localized = localize_report(restore_report(original.to_dict()), "zh-CN")
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            path.write_text(json.dumps(localized.to_dict()), encoding="utf-8")
            restored = load_report_json(path)
        self.assertEqual(len(review_findings(restored)), 1)
        self.assertEqual(effective_findings(restored), [])

    def test_legacy_ai_only_and_canonical_exports_both_load(self):
        original = ai_report()
        identity = review_findings(original)[0].fingerprint
        legacy = original.to_dict()
        legacy.pop("findings_canonical", None)
        # Old exported reports contained both projections, without a schema marker.
        restored = localize_report(restore_report(legacy), "zh-CN")
        self.assertEqual([f.fingerprint for f in review_findings(restored)], [identity])
        # Older producers could put AI findings only in the AI section.
        legacy["findings"] = []
        restored = restore_report(legacy)
        self.assertEqual(len(review_findings(restored)), 1)

    def test_canonical_empty_list_does_not_resurrect_legacy_ai_projection(self):
        data = ai_report().to_dict()
        data["findings_canonical"] = True
        data["findings"] = []
        self.assertEqual(review_findings(restore_report(data)), [])
