import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from repo_review_agent.service import run_review


class ProvenanceTests(unittest.TestCase):
    def test_review_records_clean_commit_and_marks_local_changes(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            for args in (['init','-q'], ['config','user.name','Review Test'], ['config','user.email','test@example.invalid']):
                subprocess.run(['git',*args],cwd=root,check=True,capture_output=True)
            (root/'app.py').write_text('print(1)\n')
            subprocess.run(['git','add','app.py'],cwd=root,check=True,capture_output=True)
            subprocess.run(['git','commit','-qm','fixture'],cwd=root,check=True,capture_output=True)
            clean=run_review(root,mode='direct')
            self.assertEqual(len(clean.metrics['source_commit_sha']),40)
            self.assertIs(clean.metrics['source_dirty'],False)
            (root/'app.py').write_text('print(2)\n')
            dirty=run_review(root,mode='agent')
            self.assertEqual(dirty.metrics['source_commit_sha'],clean.metrics['source_commit_sha'])
            self.assertIs(dirty.metrics['source_dirty'],True)
