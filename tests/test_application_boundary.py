import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class ApplicationBoundaryTests(unittest.TestCase):
    def test_worker_runs_without_importing_web_cli_or_optional_http_packages(self):
        # A deployment with only the core package must be able to execute a job.
        script = """
import importlib.abc, json, sys
from pathlib import Path
class NoWeb(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'fastapi', 'uvicorn', 'repo_review_agent.web', 'repo_review_agent.cli'}:
            raise AssertionError('Worker imported HTTP/CLI layer: ' + fullname)
sys.meta_path.insert(0, NoWeb())
from repo_review_agent.job_runtime import main
main(sys.argv[1])
result = json.loads((Path(sys.argv[1]) / 'output.json').read_text())
assert 'result' in result, result
assert 'markdown' in result['result']
"""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            (repo / "README.md").write_text("# Example")
            (root / "input.json").write_text(json.dumps({
                "request": {"target": str(repo), "mode": "direct"}, "user": None,
            }))
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("SUPABASE_", "REPO_REVIEW_", "LANGFUSE_"))}
            result = subprocess.run(
                [sys.executable, "-c", script, str(root)],
                capture_output=True, text=True, timeout=20, env=env,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
