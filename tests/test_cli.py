import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from repo_review_agent.cli import main


class CLITests(unittest.TestCase):
    def test_main_writes_markdown_and_json_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            output_path = Path(tmp) / "review.md"
            json_path = Path(tmp) / "review.json"
            (root / "README.md").write_text(
                "# Example\n\n## Usage\nRun python -m unittest.\n\n## Demo\nExample output.\n",
                encoding="utf-8",
            )
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / ".gitignore").write_text(".venv\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")

            exit_code = main(
                [
                    str(root),
                    "--output",
                    str(output_path),
                    "--json",
                    str(json_path),
                    "--max-files",
                    "50",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertIn("# Repository Review: repo", output_path.read_text(encoding="utf-8"))
            data = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(data["repo_name"], "repo")
            self.assertIn("findings", data)

    def test_main_rejects_missing_target_path(self) -> None:
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"

            with self.assertRaises(SystemExit):
                main([str(missing)])


if __name__ == "__main__":
    unittest.main()
