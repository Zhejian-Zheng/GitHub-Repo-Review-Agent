import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from repo_review_agent.analyzer import analyze_repository, build_overview, detect_framework_signals
from repo_review_agent.scanner import scan_repository


class AnalyzerTests(unittest.TestCase):
    def test_analyzer_reports_missing_project_metadata_and_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")

            report = analyze_repository(root)

        titles = {finding.title for finding in report.findings}
        self.assertIn("Add a README with setup and usage instructions", titles)
        self.assertIn("Add an explicit open-source license", titles)
        self.assertIn("Add a .gitignore file", titles)
        self.assertIn("Add a dependency manifest", titles)

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
        paths_by_title = {finding.title: finding.evidence_paths for finding in report.findings}
        self.assertIn("Add automated tests for the core behavior", titles)
        self.assertIn("Add a CI workflow", titles)
        self.assertEqual(paths_by_title["Add automated tests for the core behavior"], ["app.py"])
        self.assertIn("app.py", paths_by_title["Add a CI workflow"])

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
        self.assertEqual(report.findings[0].evidence_paths, ["app.py"])

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
        paths_by_title = {finding.title: finding.evidence_paths for finding in report.findings}
        self.assertIn("Expand README with setup and example output", titles)
        self.assertEqual(paths_by_title["Expand README with setup and example output"], ["README.md"])

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
        paths_by_title = {finding.title: finding.evidence_paths for finding in report.findings}
        self.assertIn("Commit a JavaScript package lockfile", titles)
        self.assertEqual(paths_by_title["Commit a JavaScript package lockfile"], ["package.json"])

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
        paths_by_title = {finding.title: finding.evidence_paths for finding in report.findings}
        self.assertIn("Run automated tests in CI", titles)
        self.assertIn("Build frontend assets in CI", titles)
        self.assertEqual(paths_by_title["Run automated tests in CI"], [".github/workflows/ci.yml"])
        self.assertIn(".github/workflows/ci.yml", paths_by_title["Build frontend assets in CI"])
        self.assertIn("package.json", paths_by_title["Build frontend assets in CI"])

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
        paths_by_title = {finding.title: finding.evidence_paths for finding in report.findings}
        self.assertIn("Expand test coverage across source modules", titles)
        self.assertIn("tests/test_one.py", paths_by_title["Expand test coverage across source modules"])

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
        paths_by_title = {finding.title: finding.evidence_paths for finding in report.findings}
        self.assertIn("Harden Docker image with a non-root runtime user", titles)
        self.assertEqual(paths_by_title["Harden Docker image with a non-root runtime user"], ["Dockerfile"])

    def test_analyzer_attaches_evidence_paths_to_summary_finding(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "README.md").write_text(
                "# Example\n\n## Usage\nRun python -m unittest.\n\n## Demo\nExample report output.\n",
                encoding="utf-8",
            )
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / ".gitignore").write_text(".venv\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            (root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
            (root / "tests" / "test_app.py").write_text("def test_app(): pass\n", encoding="utf-8")
            (root / ".github" / "workflows" / "ci.yml").write_text(
                "name: CI\nrun: python -m unittest discover\n",
                encoding="utf-8",
            )

            report = analyze_repository(root)

        self.assertEqual(report.findings[0].title, "No major project hygiene gaps detected")
        self.assertTrue(report.findings[0].evidence_paths)
        self.assertIn("README.md", report.findings[0].evidence_paths)

    def test_analyzer_detects_framework_signals_from_package_json_and_pyproject(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "frontend").mkdir()
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                "[project]\ndependencies = ['fastapi', 'pytest', 'openai']\n",
                encoding="utf-8",
            )
            (root / "frontend" / "package.json").write_text(
                '{"dependencies":{"react":"18.0.0","next":"14.0.0","@nestjs/core":"1.0.0"}}',
                encoding="utf-8",
            )
            (root / "Dockerfile").write_text("FROM python:3.12\nUSER app\n", encoding="utf-8")

            snapshot = scan_repository(root)
            signals = detect_framework_signals(snapshot, root)

        self.assertIn("FastAPI", signals)
        self.assertIn("Pytest", signals)
        self.assertIn("OpenAI", signals)
        self.assertIn("React", signals)
        self.assertIn("Next.js", signals)
        self.assertIn("NestJS", signals)
        self.assertIn("Docker", signals)

    def test_analyzer_handles_invalid_package_json_as_tooling_signal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{invalid", encoding="utf-8")

            snapshot = scan_repository(root)
            signals = detect_framework_signals(snapshot, root)

        self.assertIn("JavaScript tooling", signals)
        self.assertIn("could not be parsed", signals["JavaScript tooling"][0])

    def test_dockerfile_with_non_root_user_does_not_report_hardening_gap(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# Example\n\n## Usage\nRun docker build.\n\n## Demo\nExample output.\n",
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
            (root / "Dockerfile").write_text("FROM python:3.12-slim\nUSER 1000:1000\n", encoding="utf-8")

            report = analyze_repository(root)

        titles = {finding.title for finding in report.findings}
        self.assertNotIn("Harden Docker image with a non-root runtime user", titles)

    def test_build_overview_reports_absent_signals(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            snapshot = scan_repository(root)

        overview = build_overview(snapshot, {})

        self.assertIn("No application source files were detected in the scanned sample.", overview)
        self.assertIn("No dependency manifest was found.", overview)
        self.assertIn("No test files were detected.", overview)
        self.assertIn("No CI workflow files were detected.", overview)


if __name__ == "__main__":
    unittest.main()
