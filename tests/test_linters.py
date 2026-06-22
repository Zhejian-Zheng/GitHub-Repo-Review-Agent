import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from repo_review_agent.linters import collect_linter_findings, ruff_findings
from repo_review_agent.models import RepoFile, RepositorySnapshot


def _python_snapshot(root: Path) -> RepositorySnapshot:
    return RepositorySnapshot(
        root=str(root),
        name=root.name,
        files=[RepoFile(path="app.py", size_bytes=10, suffix=".py", kind="source", language="Python")],
        top_level_items=["app.py"],
        dependency_files=[],
        ci_files=[],
        docs_files=[],
        test_files=[],
        source_files=["app.py"],
        language_counts={"Python": 1},
        total_size_bytes=10,
        skipped_files=0,
    )


def _fake_ruff(diagnostics):
    def _run(*args, **kwargs):
        return SimpleNamespace(stdout=json.dumps(diagnostics), returncode=0)

    return _run


class RuffFindingsTests(unittest.TestCase):
    def test_returns_empty_when_ruff_missing(self) -> None:
        with patch("repo_review_agent.linters.shutil.which", return_value=None):
            self.assertEqual(ruff_findings(Path(".")), [])

    def test_normalizes_and_orders_by_severity(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            diagnostics = [
                {
                    "code": "F401",
                    "message": "`os` imported but unused",
                    "filename": str(root / "app.py"),
                    "location": {"row": 1, "column": 1},
                    "url": "https://docs.astral.sh/ruff/rules/unused-import/",
                },
                {
                    "code": "S105",
                    "message": "Possible hardcoded password",
                    "filename": str(root / "app.py"),
                    "location": {"row": 3, "column": 5},
                },
                {
                    "code": "E701",
                    "message": "Multiple statements on one line",
                    "filename": str(root / "b.py"),
                    "location": {"row": 2, "column": 1},
                },
            ]
            with (
                patch("repo_review_agent.linters.shutil.which", return_value="/usr/bin/ruff"),
                patch("repo_review_agent.linters.subprocess.run", _fake_ruff(diagnostics)),
            ):
                findings = ruff_findings(root)

        self.assertEqual(len(findings), 3)
        # Security finding ranks first, then correctness, then maintainability.
        self.assertEqual(findings[0].category, "security")
        self.assertEqual(findings[0].severity, "high")
        self.assertEqual(findings[1].severity, "medium")
        self.assertEqual(findings[1].category, "correctness")
        self.assertEqual(findings[2].severity, "low")
        self.assertEqual(findings[0].evidence_paths, ["app.py"])
        self.assertIn("app.py:3", findings[0].evidence[0])

    def test_aggregates_repeated_codes_with_overflow_note(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            diagnostics = [
                {
                    "code": "F401",
                    "message": "unused import",
                    "filename": str(root / f"mod_{index}.py"),
                    "location": {"row": index + 1, "column": 1},
                }
                for index in range(7)
            ]
            with (
                patch("repo_review_agent.linters.shutil.which", return_value="/usr/bin/ruff"),
                patch("repo_review_agent.linters.subprocess.run", _fake_ruff(diagnostics)),
            ):
                findings = ruff_findings(root)

        self.assertEqual(len(findings), 1)
        self.assertIn("Fix 7 Ruff F401", findings[0].title)
        self.assertTrue(any("more occurrence" in line for line in findings[0].evidence))

    def test_invalid_or_empty_output_is_ignored(self) -> None:
        with patch("repo_review_agent.linters.shutil.which", return_value="/usr/bin/ruff"):
            with patch(
                "repo_review_agent.linters.subprocess.run",
                lambda *a, **k: SimpleNamespace(stdout="not json", returncode=0),
            ):
                self.assertEqual(ruff_findings(Path(".")), [])
            with patch(
                "repo_review_agent.linters.subprocess.run",
                lambda *a, **k: SimpleNamespace(stdout="", returncode=0),
            ):
                self.assertEqual(ruff_findings(Path(".")), [])

    def test_collect_skips_non_python_repositories(self) -> None:
        snapshot = RepositorySnapshot(
            root="/tmp/x",
            name="x",
            files=[RepoFile(path="main.go", size_bytes=10, suffix=".go", kind="source", language="Go")],
            top_level_items=["main.go"],
            dependency_files=[],
            ci_files=[],
            docs_files=[],
            test_files=[],
            source_files=["main.go"],
            language_counts={"Go": 1},
            total_size_bytes=10,
            skipped_files=0,
        )
        with patch("repo_review_agent.linters.ruff_findings") as ruff_mock:
            findings = collect_linter_findings(snapshot, Path("/tmp/x"))
        self.assertEqual(findings, [])
        ruff_mock.assert_not_called()

    def test_collect_runs_for_python_repositories(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            diagnostics = [
                {
                    "code": "F841",
                    "message": "local variable assigned but never used",
                    "filename": str(root / "app.py"),
                    "location": {"row": 2, "column": 5},
                }
            ]
            with (
                patch("repo_review_agent.linters.shutil.which", return_value="/usr/bin/ruff"),
                patch("repo_review_agent.linters.subprocess.run", _fake_ruff(diagnostics)),
            ):
                findings = collect_linter_findings(_python_snapshot(root), root)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "correctness")


if __name__ == "__main__":
    unittest.main()
