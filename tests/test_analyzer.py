from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from repo_review_agent.analyzer import analyze_repository


class AnalyzerTests(unittest.TestCase):
    def test_analyzer_reports_missing_tests_and_ci(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / ".gitignore").write_text(".env\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")

            report = analyze_repository(root)

        titles = {finding.title for finding in report.findings}
        self.assertIn("Add automated tests for the core behavior", titles)
        self.assertIn("Add a CI workflow", titles)

    def test_analyzer_detects_secret_like_values(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            (root / "app.py").write_text(
                "API_KEY = '1234567890abcdef1234567890abcdef'\n",
                encoding="utf-8",
            )

            report = analyze_repository(root)

        self.assertEqual(report.findings[0].title, "Remove possible hard-coded secrets")
        self.assertEqual(report.findings[0].severity, "high")


if __name__ == "__main__":
    unittest.main()
