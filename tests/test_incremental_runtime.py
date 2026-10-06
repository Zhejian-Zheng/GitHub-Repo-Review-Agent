import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fake_model import ScriptedModel, final

from repo_review_agent.agent import RepoReviewAgent
from repo_review_agent.scanner import scan_repository
from repo_review_agent.service import run_review


class IncrementalRuntimeTests(unittest.TestCase):
    def test_changed_source_is_prioritized_inside_bounded_sample(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'README.md').write_text('Usage example')
            (root/'a.py').write_text('a=1')
            (root/'changed.py').write_text('b=2')
            snapshot=scan_repository(root,max_files=1,priority_paths=['changed.py'])
        self.assertEqual([f.path for f in snapshot.files],['changed.py'])
        self.assertEqual(len(snapshot.inventory_files),3)

    def test_agent_inspects_changed_source_before_metadata(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'README.md').write_text('Usage example')
            (root/'changed.py').write_text('return_value=1')
            report=RepoReviewAgent(changed_files=[{'filename':'changed.py','patch':'@@ -1 +1 @@\n-old\n+return_value=1'}]).run(root)
        reads=[step.tool_input['path'] for step in report.agent_trace if step.tool=='inspect_file']
        self.assertEqual(reads[0],'changed.py')
        self.assertEqual(report.metrics['review_scope'],'incremental')

    def test_service_passes_diff_context_to_model_without_raw_patch(self):
        model=ScriptedModel(responses=[final()])
        with TemporaryDirectory() as tmp, patch('repo_review_agent.agent.create_chat_model',return_value=model):
            root=Path(tmp)
            (root/'changed.py').write_text('return_value=1')
            report=run_review(root,ai_provider='ollama',changed_files=[{'filename':'changed.py','patch':'private diff content'}])
        self.assertEqual(report.ai_review.status,'generated')
        prompt=str(model.seen_messages[0])
        self.assertIn('changed.py',prompt)
        self.assertNotIn('private diff content',prompt)

    def test_changed_file_paths_validate_before_scan(self):
        with TemporaryDirectory() as tmp:
            for path in ('../outside.py','/tmp/out.py','dir\\file.py'):
                with self.assertRaises(ValueError):
                    run_review(Path(tmp),changed_files=[{'filename':path}])

    def test_changed_context_file_rejects_null_invalid_patch_and_oversize(self):
        from repo_review_agent.incremental import load_changed_files
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'changes.json'
            for value in (None, {}, [{'filename':'ok.py','patch':4}], ['not-an-object']):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    load_changed_files(path)
            path.write_bytes(b'x'*2_000_001)
            with self.assertRaises(ValueError):
                load_changed_files(path)
            with self.assertRaises(ValueError):
                load_changed_files(Path(tmp)/'missing.json')

    def test_cli_changed_context_and_budget_reach_runtime(self):
        from contextlib import redirect_stdout
        from io import StringIO

        from repo_review_agent.cli import main
        with TemporaryDirectory() as tmp, redirect_stdout(StringIO()):
            root=Path(tmp)/'repo'
            root.mkdir()
            (root/'README.md').write_text('Usage example')
            (root/'changed.py').write_text('value=1')
            diff=Path(tmp)/'changes.json'
            diff.write_text(json.dumps([{'filename':'changed.py'}]))
            output=Path(tmp)/'out.json'
            self.assertEqual(main([str(root),'--agent','--max-files','1','--changed-files-json',str(diff),'--ai-token-budget','20000','--json',str(output)]),0)
            result=json.loads(output.read_text())
            self.assertEqual(result['metrics']['review_scope'],'incremental')
            self.assertEqual(result['metrics']['agent_inspected_files'],['changed.py'])
            with self.assertRaises(SystemExit):
                main([str(root),'--ai-token-budget','0'])
