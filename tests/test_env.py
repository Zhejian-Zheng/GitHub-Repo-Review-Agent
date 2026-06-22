import builtins
import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from repo_review_agent.env import load_local_env


@contextmanager
def _chdir(path: str):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class LoadLocalEnvTests(unittest.TestCase):
    def test_loads_values_from_dotenv(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text("RRA_TEST_KEY=from-dotenv\n", encoding="utf-8")
            with _chdir(tmp), patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RRA_TEST_KEY", None)
                self.assertTrue(load_local_env())
                self.assertEqual(os.environ.get("RRA_TEST_KEY"), "from-dotenv")

    def test_existing_environment_is_not_overridden(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text("RRA_TEST_KEY=from-dotenv\n", encoding="utf-8")
            with _chdir(tmp), patch.dict(os.environ, {"RRA_TEST_KEY": "from-shell"}, clear=False):
                load_local_env()
                self.assertEqual(os.environ.get("RRA_TEST_KEY"), "from-shell")

    def test_missing_dependency_is_not_fatal(self) -> None:
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "dotenv":
                raise ImportError("python-dotenv is not installed")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            self.assertFalse(load_local_env())


if __name__ == "__main__":
    unittest.main()
