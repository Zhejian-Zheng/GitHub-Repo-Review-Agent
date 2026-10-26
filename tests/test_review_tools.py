import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory


class ReviewToolsTests(unittest.TestCase):
    def test_large_inventory_keeps_analysis_valid_and_findings_visible(self):
        from repo_review_agent.review_tools import ReviewSession

        for count in (200, 500):
            with self.subTest(count=count), TemporaryDirectory() as tmp:
                root = Path(tmp)
                for index in range(count):
                    (root / f'component_{index:03d}_with_a_descriptive_name.py').write_text('value = 1\n')
                session = ReviewSession(root)
                analyze = next(t for t in session.tools() if t.name == 'analyze_repository')
                result = analyze.invoke({})
                self.assertLessEqual(len(result), 6000)
                data = json.loads(result)
                self.assertTrue(data['findings'])
                self.assertEqual(data['total_findings'], len(session.report.findings))
                self.assertNotIn('inventory_paths', data['metrics']['review_coverage'])
                self.assertEqual(data['metrics']['files_scanned'], count)
                self.assertEqual(len(session.report.metrics['review_coverage']['inventory_paths']), count)

    def test_analysis_pages_include_every_finding_and_preserve_high_priority(self):
        from repo_review_agent.models import Finding
        from repo_review_agent.review_tools import ReviewSession

        with TemporaryDirectory() as tmp:
            session = ReviewSession(Path(tmp))
            findings = [Finding(f'Finding {i}', 'low', 'code', ['quote'], '修复 "quoted" \\ text ' * 80,
                                [f'src/file_{i}.py']) for i in range(30)]
            findings.append(Finding('Critical defect', 'high', 'security', ['bad'], 'Fix', ['app.py']))
            session.report = replace(session.current_report(), findings=findings)
            analyze = next(t for t in session.tools() if t.name == 'analyze_repository')
            titles, offset = [], 0
            while offset is not None:
                result = analyze.invoke({'offset': offset})
                self.assertLessEqual(len(result), 6000)
                page = json.loads(result)
                self.assertTrue(page['findings'])
                titles.extend(item['title'] for item in page['findings'])
                next_offset = page['next_offset']
                self.assertTrue(next_offset is None or next_offset > offset)
                self.assertEqual(page['truncated'], next_offset is not None)
                offset = next_offset
            self.assertEqual(titles[0], 'Critical defect')
            self.assertCountEqual(titles, [f.title for f in findings])
            self.assertEqual(session.report.findings, findings)
            self.assertEqual(json.loads(analyze.invoke({'offset': 1000}))['findings'], [])

    def test_analysis_bounds_escaped_fields_without_cutting_paths(self):
        from repo_review_agent.models import Finding
        from repo_review_agent.review_tools import ReviewSession

        with TemporaryDirectory() as tmp:
            session = ReviewSession(Path(tmp))
            paths = ['src/' + 'nested/' * 200 + 'app.py', 'src/app.py']
            finding = Finding('\x01' * 500, 'high', '\x01' * 500, [], '\x01' * 3000,
                              paths, rule_id='\x01' * 500)
            session.report = replace(session.current_report(), findings=[finding])
            analyze = next(t for t in session.tools() if t.name == 'analyze_repository')
            result = analyze.invoke({})
            self.assertLessEqual(len(result), 6000)
            summary = json.loads(result)['findings'][0]
            self.assertEqual(summary['evidence_paths'], ['src/app.py'])
            self.assertCountEqual(summary['truncated_fields'],
                                  ['title', 'category', 'rule_id', 'recommendation', 'evidence_paths'])
            self.assertEqual(session.report.findings[0].evidence_paths, paths)

    def test_scan_inspect_analyze_render_share_state(self):
        from repo_review_agent.review_tools import ReviewSession

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\nhello")
            session = ReviewSession(root)
            tools = {tool.name: tool for tool in session.tools()}
            self.assertIn("README.md", tools["scan_repository"].invoke({}))
            self.assertIn("hello", tools["inspect_file"].invoke({"path": "README.md"}))
            self.assertIn("findings", tools["analyze_repository"].invoke({}))
            self.assertIn("Repository Review:", tools["generate_report"].invoke({}))
            self.assertEqual(session.report.metrics["agent_inspected_files"], ["README.md"])
            self.assertEqual(
                [step.tool for step in session.trace],
                ["scan_repository", "inspect_file", "analyze_repository", "generate_report"],
            )

    def test_tools_reject_outside_ignored_missing_and_unbounded_reads(self):
        from pydantic import ValidationError

        from repo_review_agent.review_tools import ReviewSession

        with TemporaryDirectory() as tmp, TemporaryDirectory() as outside:
            root = Path(tmp)
            (Path(outside) / "secret.txt").write_text("private source")
            (root / "link.txt").symlink_to(Path(outside) / "secret.txt")
            (root / ".env").write_text("private source")
            (root / "large.md").write_text("x" * 200)
            session = ReviewSession(root, max_file_size=100)
            tool = next(t for t in session.tools() if t.name == "inspect_file")
            for path in (
                "../secret.txt",
                str(Path(outside) / "secret.txt"),
                "link.txt",
                ".env",
                "missing",
                "large.md",
            ):
                with self.subTest(path=path):
                    result = tool.invoke({"path": path})
                    self.assertNotIn("private source", result)
                    self.assertIn("error", result)
            for length in (0, -1, 8001):
                with self.subTest(length=length), self.assertRaises(ValidationError):
                    tool.invoke({"path": "large.md", "max_chars": length})

    def test_analysis_is_idempotent_and_read_is_bounded(self):
        from repo_review_agent.review_tools import ReviewSession

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("a" * 5000)
            session = ReviewSession(root)
            tools = {tool.name: tool for tool in session.tools()}
            tools["analyze_repository"].invoke({})
            original = session.report.findings
            result = tools["inspect_file"].invoke({"path": "README.md", "max_chars": 20})
            self.assertNotIn("a" * 21, result)
            tools["analyze_repository"].invoke({})
            self.assertEqual(session.report.findings, original)
            self.assertEqual(session.report.metrics["agent_inspected_files"], ["README.md"])

    def test_symlink_alias_cannot_bypass_sensitive_or_excluded_scope(self):
        from repo_review_agent.review_tools import ReviewSession

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("sensitive test value")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("sensitive git value")
            (root / "README.md").symlink_to(root / ".env")
            (root / "alias.txt").symlink_to(root / ".git" / "config")
            session = ReviewSession(root)
            inspect = next(t for t in session.tools() if t.name == "inspect_file")
            for name in ("README.md", "alias.txt"):
                result = inspect.invoke({"path": name})
                self.assertIn("error", result)
                self.assertNotIn("sensitive", result)

    def test_invalid_paths_return_recoverable_tool_errors(self):
        from repo_review_agent.review_tools import ReviewSession

        with TemporaryDirectory() as tmp:
            inspect = next(t for t in ReviewSession(Path(tmp)).tools() if t.name == "inspect_file")
            result = inspect.invoke({"path": "a\x00b"})
            self.assertIn("error", result)
