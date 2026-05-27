from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from repo_review_agent.scanner import scan_repository


class ScannerTests(unittest.TestCase):
    def test_scan_repository_classifies_common_files(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            (root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
            (root / "tests" / "test_app.py").write_text("def test_app(): pass\n", encoding="utf-8")
            (root / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")

            snapshot = scan_repository(root)

        self.assertIn("pyproject.toml", snapshot.dependency_files)
        self.assertIn(".github/workflows/ci.yml", snapshot.ci_files)
        self.assertIn("tests/test_app.py", snapshot.test_files)
        self.assertIn("src/app.py", snapshot.source_files)
        self.assertEqual(snapshot.language_counts["Python"], 1)


if __name__ == "__main__":
    unittest.main()
