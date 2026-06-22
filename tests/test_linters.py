import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from repo_review_agent.linters import (
    _finding_for_code,
    _first_message,
    _relative_filename,
    _ruff_category,
    _ruff_severity,
    _run_ruff,
    collect_linter_findings,
    ruff_findings,
)
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


class RuffHelperTests(unittest.TestCase):
    def test_severity_mapping(self) -> None:
        self.assertEqual(_ruff_severity("E999"), "high")
        self.assertEqual(_ruff_severity("syntax-error"), "high")
        self.assertEqual(_ruff_severity("S105"), "high")
        self.assertEqual(_ruff_severity("F401"), "medium")
        self.assertEqual(_ruff_severity("E701"), "low")

    def test_category_mapping(self) -> None:
        self.assertEqual(_ruff_category("S105"), "security")
        self.assertEqual(_ruff_category("syntax-error"), "correctness")
        self.assertEqual(_ruff_category("F401"), "correctness")
        self.assertEqual(_ruff_category("PERF401"), "performance")
        self.assertEqual(_ruff_category("E701"), "maintainability")

    def test_run_ruff_swallows_subprocess_errors(self) -> None:
        with patch("repo_review_agent.linters.shutil.which", return_value="/usr/bin/ruff"):
            with patch("repo_review_agent.linters.subprocess.run", side_effect=OSError):
                self.assertEqual(_run_ruff(Path("."), timeout=1), [])
            with patch(
                "repo_review_agent.linters.subprocess.run",
                side_effect=subprocess.TimeoutExpired("ruff", 1),
            ):
                self.assertEqual(_run_ruff(Path("."), timeout=1), [])

    def test_relative_filename_edge_cases(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(_relative_filename({}, root), "")
            self.assertEqual(_relative_filename({"filename": "/etc/hosts"}, root), "hosts")

    def test_first_message_empty_when_all_blank(self) -> None:
        self.assertEqual(_first_message([{"message": ""}, {"message": None}]), "")

    def test_finding_for_code_without_message_or_filename(self) -> None:
        finding = _finding_for_code(
            "E701",
            [{"code": "E701", "message": "", "filename": ""}],
            Path("."),
        )
        self.assertEqual(finding.evidence_paths, [])
        self.assertEqual(finding.recommendation, "Resolve the Ruff E701 findings.")

    def test_non_dict_diagnostics_are_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            diagnostics = [
                "not-a-dict",
                {
                    "code": "F401",
                    "message": "unused import",
                    "filename": str(root / "a.py"),
                    "location": {"row": 1, "column": 1},
                },
            ]
            with (
                patch("repo_review_agent.linters.shutil.which", return_value="/usr/bin/ruff"),
                patch("repo_review_agent.linters.subprocess.run", _fake_ruff(diagnostics)),
            ):
                findings = ruff_findings(root)
        self.assertEqual(len(findings), 1)


if __name__ == "__main__":
    unittest.main()
