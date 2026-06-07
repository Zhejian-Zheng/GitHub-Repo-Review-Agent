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

    def test_analyzer_ignores_secret_placeholders(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "export OPENAI_API_KEY=\"your_api_key_here\"\n",
                encoding="utf-8",
            )
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")

            report = analyze_repository(root)

        titles = {finding.title for finding in report.findings}
        self.assertNotIn("Remove possible hard-coded secrets", titles)

    def test_analyzer_reports_readme_quality_gaps(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n\nA project overview.\n", encoding="utf-8")
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / ".gitignore").write_text(".env\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")

            report = analyze_repository(root)

        titles = {finding.title for finding in report.findings}
        self.assertIn("Expand README with setup and example output", titles)

    def test_analyzer_reports_missing_javascript_lockfile(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# Example\n\n## Usage\nRun npm install.\n\n## Demo\nExample report output.\n",
                encoding="utf-8",
            )
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / ".gitignore").write_text("node_modules\n", encoding="utf-8")
            (root / "package.json").write_text('{"dependencies":{"react":"latest"}}\n', encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "app.js").write_text("console.log('hello')\n", encoding="utf-8")

            report = analyze_repository(root)

        titles = {finding.title for finding in report.findings}
        self.assertIn("Commit a JavaScript package lockfile", titles)

    def test_analyzer_reports_ci_without_test_or_frontend_build(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "README.md").write_text(
                "# Example\n\n## Usage\nRun npm install.\n\n## Demo\nExample report output.\n",
                encoding="utf-8",
            )
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / ".gitignore").write_text("node_modules\n", encoding="utf-8")
            (root / "package.json").write_text('{"scripts":{"build":"vite build"}}\n', encoding="utf-8")
            (root / "package-lock.json").write_text("{}\n", encoding="utf-8")
            (root / "src" / "app.js").write_text("console.log('hello')\n", encoding="utf-8")
            (root / "tests" / "app.test.js").write_text("test('x', () => {})\n", encoding="utf-8")
            (root / ".github" / "workflows" / "ci.yml").write_text(
                "name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n",
                encoding="utf-8",
            )

            report = analyze_repository(root)

        titles = {finding.title for finding in report.findings}
        self.assertIn("Run automated tests in CI", titles)
        self.assertIn("Build frontend assets in CI", titles)

    def test_analyzer_reports_low_test_to_source_ratio(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / "README.md").write_text(
                "# Example\n\n## Usage\nRun python -m unittest.\n\n## Demo\nExample report output.\n",
                encoding="utf-8",
            )
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / ".gitignore").write_text(".venv\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            for index in range(8):
                (root / "src" / f"module_{index}.py").write_text("print('hello')\n", encoding="utf-8")
            (root / "tests" / "test_one.py").write_text("def test_one(): pass\n", encoding="utf-8")
            (root / ".github" / "workflows" / "ci.yml").write_text(
                "name: CI\nrun: python -m unittest discover\n",
                encoding="utf-8",
            )

            report = analyze_repository(root)

        titles = {finding.title for finding in report.findings}
        self.assertIn("Expand test coverage across source modules", titles)

    def test_analyzer_reports_dockerfile_without_non_root_user(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# Example\n\n## Usage\nRun docker build.\n\n## Demo\nExample report output.\n",
                encoding="utf-8",
            )
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / ".gitignore").write_text(".venv\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_app.py").write_text("def test_app(): pass\n", encoding="utf-8")
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "ci.yml").write_text(
                "name: CI\nrun: python -m unittest discover\n",
                encoding="utf-8",
            )
            (root / "Dockerfile").write_text("FROM python:3.12-slim\nCOPY . /app\n", encoding="utf-8")

            report = analyze_repository(root)

        titles = {finding.title for finding in report.findings}
        self.assertIn("Harden Docker image with a non-root runtime user", titles)


if __name__ == "__main__":
    unittest.main()
