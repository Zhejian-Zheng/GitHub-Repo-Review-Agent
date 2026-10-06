import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from repo_review_agent.scanner import _relative_path, read_text_file, scan_repository


class ScannerTests(unittest.TestCase):
    def test_inventory_survives_content_cap_and_counts_all_omissions(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("a.py", "b.py", "c.py", "README.md", "LICENSE", "package.json"):
                (root / name).write_text("{}", encoding="utf-8")
            snapshot = scan_repository(root, max_files=1)
        self.assertEqual(snapshot.skipped_files, 5)
        self.assertEqual(len(snapshot.inventory_files), 6)
        self.assertEqual(snapshot.files[0].path, "README.md")
        self.assertIn("package.json", snapshot.dependency_files)

    def test_symlinks_are_not_scanned_or_read(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real.py").write_text("secret", encoding="utf-8")
            (root / "link.py").symlink_to(root / "real.py")
            snapshot = scan_repository(root)
            self.assertEqual(read_text_file(root, "link.py"), "")
        self.assertNotIn("link.py", [file.path for file in snapshot.files])

    def test_text_read_is_bounded_without_read_text(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "large.txt").write_text("a" * 100000, encoding="utf-8")
            with patch.object(Path, "read_text", side_effect=AssertionError("unbounded read")):
                self.assertEqual(read_text_file(root, "large.txt", limit=3), "aaa")

    def test_unreadable_top_level_marks_inventory_incomplete(self) -> None:
        with (
            TemporaryDirectory() as tmp,
            patch.object(Path, "iterdir", side_effect=PermissionError("denied")),
        ):
            snapshot = scan_repository(Path(tmp))
        self.assertFalse(snapshot.inventory_complete)
        self.assertEqual(snapshot.top_level_items, [])

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

    def test_scan_repository_records_skipped_file_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            (root / "large.py").write_text("x" * 20, encoding="utf-8")

            snapshot = scan_repository(root, max_file_size=10)

        self.assertEqual(snapshot.skipped_files, 1)
        self.assertEqual(snapshot.skipped_file_paths, ["large.py"])

    def test_scan_repository_respects_max_files_and_ignored_dirs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "node_modules").mkdir()
            (root / "src").mkdir()
            (root / "node_modules" / "ignored.js").write_text("console.log('x')\n", encoding="utf-8")
            (root / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
            (root / "src" / "b.py").write_text("print('b')\n", encoding="utf-8")

            snapshot = scan_repository(root, max_files=1)

        self.assertEqual(len(snapshot.files), 1)
        self.assertEqual(snapshot.skipped_files, 1)
        self.assertNotIn("node_modules", snapshot.top_level_items)
        self.assertNotIn("node_modules/ignored.js", [file.path for file in snapshot.files])

    def test_scan_repository_returns_files_in_deterministic_path_order(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / ".gitignore").write_text(".venv\n", encoding="utf-8")
            (root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")

            snapshot = scan_repository(root)
            limited_snapshot = scan_repository(root, max_files=2)

        self.assertEqual(
            [file.path for file in snapshot.files],
            [".gitignore", "LICENSE", "README.md", "src/app.py"],
        )
        self.assertEqual([file.path for file in limited_snapshot.files], ["LICENSE", "README.md"])

    def test_scan_repository_classifies_many_file_kinds(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "test").mkdir()
            (root / ".gitlab-ci.yml").write_text("test\n", encoding="utf-8")
            (root / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
            (root / "compose.yml").write_text("services: {}\n", encoding="utf-8")
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / ".gitignore").write_text(".venv\n", encoding="utf-8")
            (root / "docs" / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
            (root / "test" / "app.spec.ts").write_text("test('x', () => {})\n", encoding="utf-8")
            (root / "query.sql").write_text("select 1;\n", encoding="utf-8")

            snapshot = scan_repository(root)

        kinds = {file.path: file.kind for file in snapshot.files}
        self.assertEqual(kinds[".gitlab-ci.yml"], "ci")
        self.assertEqual(kinds["Dockerfile"], "ops")
        self.assertEqual(kinds["compose.yml"], "ops")
        self.assertEqual(kinds["LICENSE"], "project-meta")
        self.assertEqual(kinds[".gitignore"], "project-meta")
        self.assertEqual(kinds["docs/architecture.md"], "docs")
        self.assertEqual(kinds["test/app.spec.ts"], "test")
        self.assertEqual(kinds["query.sql"], "other")

    def test_read_text_file_limits_content_and_handles_missing_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("abcdef", encoding="utf-8")

            self.assertEqual(read_text_file(root, "README.md", limit=3), "abc")
            self.assertEqual(read_text_file(root, "missing.md"), "")

    def test_scan_repository_skips_non_file_entries(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
            broken_symlink = root / "broken.py"
            try:
                broken_symlink.symlink_to(root / "does-not-exist.py")
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks are not supported in this environment.")

            snapshot = scan_repository(root)

        paths = {file.path for file in snapshot.files}
        self.assertIn("app.py", paths)
        self.assertNotIn("broken.py", paths)

    def test_scan_repository_excludes_test_fixture_directories(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
            (root / "tests" / "fixtures" / "risky-js-app").mkdir(parents=True)
            (root / "tests" / "fixtures" / "risky-js-app" / "package.json").write_text(
                '{"dependencies": {"react": "latest"}}\n', encoding="utf-8"
            )

            snapshot = scan_repository(root)

        paths = {file.path for file in snapshot.files}
        self.assertIn("app.py", paths)
        self.assertNotIn("tests/fixtures/risky-js-app/package.json", paths)
        self.assertEqual(snapshot.dependency_files, [])

    def test_relative_path_falls_back_for_unrelated_paths(self) -> None:
        self.assertEqual(_relative_path(Path("/a/b"), Path("/c/d")), "/c/d")

    def test_read_text_file_rejects_path_traversal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (Path(tmp) / "secret.txt").write_text("top secret", encoding="utf-8")

            self.assertEqual(read_text_file(root, "../secret.txt"), "")

    def test_disappearing_file_marks_inventory_incomplete(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch('repo_review_agent.scanner._iter_files', return_value=iter([root / 'gone.py'])):
                snapshot = scan_repository(root)
            self.assertFalse(snapshot.inventory_complete)
            self.assertIn('gone.py', snapshot.skipped_file_paths)

    def test_special_files_are_skipped_and_read_errors_are_isolated(self):
        import stat
        from types import SimpleNamespace

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'named-pipe'
            with patch('repo_review_agent.scanner._iter_files', return_value=iter([path])), patch.object(
                Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFIFO)
            ):
                self.assertEqual(scan_repository(root).files, [])
            (root / 'app.py').write_text('print(1)')
            with patch.object(Path, 'open', side_effect=PermissionError):
                self.assertEqual(read_text_file(root, 'app.py'), '')


if __name__ == "__main__":
    unittest.main()
