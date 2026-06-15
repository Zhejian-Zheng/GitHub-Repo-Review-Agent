import json
import re
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from repo_review_agent.analyzer import analyze_repository
from repo_review_agent.report import render_markdown

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "evaluation"
GOLDEN_ROOT = Path(__file__).parent / "fixtures" / "golden"


class EvaluationGoldenTests(unittest.TestCase):
    def test_evaluation_cases_match_expected_findings_and_golden_reports(self) -> None:
        for case_dir in sorted(path for path in FIXTURE_ROOT.iterdir() if path.is_dir()):
            with self.subTest(case=case_dir.name):
                with TemporaryDirectory() as tmp:
                    repo_root = Path(tmp) / case_dir.name
                    shutil.copytree(
                        case_dir,
                        repo_root,
                        ignore=shutil.ignore_patterns("expected.json"),
                    )

                    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
                    report = analyze_repository(repo_root)
                    finding_titles = {finding.title for finding in report.findings}

                    for title in expected["expected_findings"]:
                        self.assertIn(title, finding_titles)
                    for title in expected["forbidden_findings"]:
                        self.assertNotIn(title, finding_titles)
                    for framework in expected["expected_frameworks"]:
                        self.assertIn(framework, report.framework_signals)

                    markdown = _normalize_generated_at(render_markdown(report))
                    golden = (GOLDEN_ROOT / f"{case_dir.name}.md").read_text(encoding="utf-8").rstrip()

                self.assertEqual(markdown, golden)


def _normalize_generated_at(markdown: str) -> str:
    return re.sub(r"Generated: `[^`]+`", "Generated: `<generated-at>`", markdown).rstrip()


if __name__ == "__main__":
    unittest.main()
