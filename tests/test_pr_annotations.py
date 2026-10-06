import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from repo_review_agent.github import GitHubClient, GitHubIntegrationError
from repo_review_agent.models import Finding, ReviewReport
from repo_review_agent.pr_bot import (
    build_pr_annotations,
    build_pr_review_diff,
    changed_line_ranges,
    main,
    run_pr_bot,
)

SHA = "a" * 40


def report(*findings):
    return ReviewReport("repo", "", [], {}, {}, list(findings))


def risk(path="app.py", start=8, end=10):
    return Finding(
        "Unsafe input",
        "high",
        "security",
        ["unsafe(input)"],
        "Validate input",
        [path],
        path=path,
        start_line=start,
        end_line=end,
    )


class AnnotationEvidenceTests(unittest.TestCase):
    def test_annotation_spans_only_added_lines_and_splits_at_context(self):
        files = [dict(filename="app.py", patch="@@ -8,2 +8,3 @@\n+a\n context\n+b\n-old")]
        annotations = build_pr_annotations(report(risk()), files)
        self.assertEqual(
            [(a["start_line"], a["end_line"]) for a in annotations], [(8, 8), (10, 10)]
        )
        self.assertEqual(annotations[0]["message"], "Validate input\n\nunsafe(input)")

    def test_missing_binary_removed_and_truncated_patches_have_no_annotation_ranges(self):
        files = [
            dict(filename="missing.py"),
            dict(filename="binary.py", patch=None),
            dict(filename="removed.py", status="removed", patch="@@ -0,0 +1 @@\n+x"),
            dict(filename="truncated.py", patch="@@ -1,2 +1,2 @@\n-old\n+new"),
            dict(filename="overrun.py", patch="@@ -0,0 +1 @@\n+x\n+y"),
        ]
        self.assertEqual(changed_line_ranges(files), {f["filename"]: [] for f in files})

    def test_multiple_hunks_count_deletions_and_no_newline_markers(self):
        patch_text = "@@ -2,2 +2,2 @@\n old\n-removed\n+new\n\\ No newline at end of file\n@@ -9 +9,2 @@\n-old\n+one\n+two"
        self.assertEqual(
            changed_line_ranges([dict(filename="app.py", patch=patch_text)]),
            {"app.py": [(3, 3), (9, 10)]},
        )

    def test_incremental_deleted_file_resolves_and_renamed_file_keeps_baseline(self):
        old = risk("old.py")
        deleted = risk("deleted.py")
        diff = build_pr_review_diff(
            report(risk("new.py")),
            report(old, deleted),
            changed_files=[
                dict(filename="new.py", previous_filename="old.py", status="renamed"),
                dict(filename="deleted.py", status="removed"),
            ],
        )
        self.assertEqual(diff.new_findings, [])
        self.assertEqual([f.path for f in diff.existing_findings], ["new.py"])
        self.assertEqual([f.path for f in diff.resolved_findings], ["deleted.py"])

    def test_location_only_finding_does_not_become_repository_level(self):
        item = replace(risk("elsewhere.py"), evidence_paths=[])
        diff = build_pr_review_diff(report(item), changed_files=[dict(filename="app.py")])
        self.assertEqual(diff.new_findings, [])


class PRCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.report_path = self.root / "report.json"
        self.report_path.write_text(json.dumps(report(risk()).to_dict()))
        self.files_path = self.root / "files.json"
        self.files_path.write_text(
            json.dumps([dict(filename="app.py", patch="@@ -8 +8 @@\n-old\n+new")])
        )

    def args(self, *extra):
        return [
            "--report-json",
            str(self.report_path),
            "--changed-files-json",
            str(self.files_path),
            *extra,
        ]

    def test_cli_annotation_dry_run_has_public_evidence_without_network(self):
        output = io.StringIO()
        with (
            patch("repo_review_agent.github.urlopen", side_effect=AssertionError("network")),
            redirect_stdout(output),
        ):
            self.assertEqual(main(self.args("--annotation-mode", "dry-run")), 0)
        result = json.loads(output.getvalue())["pr_bot"]
        self.assertEqual(result["annotations"][0]["start_line"], 8)
        self.assertEqual(result["annotations"][0]["end_line"], 8)
        self.assertFalse(result["blocked"])
        self.assertIn("Unsafe input", result["body"])

    def test_invalid_files_json_is_a_cli_error_before_any_write(self):
        for value in ["{", "{}", "[1]", "[{}]", '[{"filename":"app.py","patch":123}]']:
            with self.subTest(value=value):
                self.files_path.write_text(value)
                with (
                    patch(
                        "repo_review_agent.github.urlopen", side_effect=AssertionError("network")
                    ),
                    self.assertRaises(SystemExit) as error,
                ):
                    main(
                        self.args(
                            "--annotation-mode",
                            "create",
                            "--comment-mode",
                            "create",
                            "--github-repo",
                            "owner/repo",
                            "--pr-number",
                            "1",
                            "--head-sha",
                            SHA,
                        )
                    )
                self.assertIn("Changed files", str(error.exception))

    def test_invalid_sha_is_rejected_before_comment_write(self):
        with (
            patch("repo_review_agent.github.urlopen", side_effect=AssertionError("network")),
            self.assertRaises(GitHubIntegrationError),
        ):
            run_pr_bot(
                report_json=self.report_path,
                changed_files_json=self.files_path,
                annotation_mode="create",
                comment_mode="create",
                github_repo="owner/repo",
                pr_number=1,
                head_sha="main",
            )

    def test_stale_report_source_commit_is_rejected_before_comment_write(self):
        data = json.loads(self.report_path.read_text())
        data["metrics"]["source_commit_sha"] = "b" * 40
        self.report_path.write_text(json.dumps(data))
        with (
            patch("repo_review_agent.github.urlopen", side_effect=AssertionError("network")),
            self.assertRaisesRegex(GitHubIntegrationError, "source commit"),
        ):
            run_pr_bot(
                report_json=self.report_path,
                changed_files_json=self.files_path,
                annotation_mode="create",
                comment_mode="create",
                github_repo="owner/repo",
                pr_number=1,
                head_sha=SHA,
            )

    def test_dirty_report_source_is_rejected_before_any_write(self):
        data = json.loads(self.report_path.read_text())
        data["metrics"]["source_dirty"] = True
        self.report_path.write_text(json.dumps(data))
        with (
            patch("repo_review_agent.github.urlopen", side_effect=AssertionError("network")),
            self.assertRaisesRegex(GitHubIntegrationError, "dirty"),
        ):
            run_pr_bot(
                report_json=self.report_path,
                changed_files_json=self.files_path,
                annotation_mode="create",
                comment_mode="create",
                github_repo="owner/repo",
                pr_number=1,
                head_sha=SHA,
            )

    def test_cli_annotation_requires_files_and_explicit_creation_requires_target(self):
        for args, message in [
            (
                ["--report-json", str(self.report_path), "--annotation-mode", "dry-run"],
                "changed-files-json",
            ),
            (self.args("--annotation-mode", "create"), "github-repo"),
            (self.args("--annotation-mode", "create", "--github-repo", "owner/repo"), "head-sha"),
        ]:
            with self.subTest(args=args), self.assertRaisesRegex(SystemExit, message):
                main(args)

    def test_annotation_none_and_empty_incremental_diff_have_no_network_side_effects(self):
        self.files_path.write_text("[]")
        output = io.StringIO()
        with (
            patch("repo_review_agent.github.urlopen", side_effect=AssertionError("network")),
            redirect_stdout(output),
        ):
            self.assertEqual(
                main(
                    self.args(
                        "--comment-mode",
                        "none",
                        "--annotation-mode",
                        "none",
                        "--fail-on-severity",
                        "high",
                    )
                ),
                0,
            )
        result = json.loads(output.getvalue())["pr_bot"]
        self.assertEqual(result["new_findings_count"], 0)
        self.assertNotIn("annotations", result)

    def test_cli_create_publishes_head_check_and_ci_failure_public_output(self):
        requests = []

        def transport(request, **kwargs):
            requests.append(request)
            return io.BytesIO(b'{"id":7,"html_url":"https://github.com/owner/repo/checks/7"}')

        output = io.StringIO()
        with (
            patch("repo_review_agent.github.urlopen", side_effect=transport),
            redirect_stdout(output),
            self.assertRaisesRegex(SystemExit, "blocked CI"),
        ):
            main(
                self.args(
                    "--annotation-mode",
                    "create",
                    "--comment-mode",
                    "none",
                    "--github-repo",
                    "owner/repo",
                    "--github-token",
                    "test",
                    "--head-sha",
                    SHA,
                    "--fail-on-severity",
                    "high",
                )
            )
        result = json.loads(output.getvalue())["pr_bot"]
        self.assertTrue(result["blocked"])
        self.assertEqual(result["check_url"], "https://github.com/owner/repo/checks/7")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].full_url, "https://api.github.com/repos/owner/repo/check-runs")
        payload = json.loads(requests[0].data)
        self.assertEqual(payload["head_sha"], SHA)
        self.assertEqual(payload["conclusion"], "failure")
        self.assertEqual(payload["output"]["annotations"][0]["end_line"], 8)


class GitHubHTTPTests(unittest.TestCase):
    def test_check_batches_append_every_annotation_to_same_check(self):
        requests = []

        def transport(request, **kwargs):
            requests.append(request)
            return io.BytesIO(b'{"id":7,"html_url":"https://example.com/check"}')

        annotations = [
            dict(
                path="app.py", start_line=i, end_line=i, annotation_level="warning", message="risk"
            )
            for i in range(1, 102)
        ]
        with patch("repo_review_agent.github.urlopen", side_effect=transport):
            result = GitHubClient(token="test").create_annotated_check(
                "owner/repo",
                head_sha=SHA,
                annotations=annotations,
                summary="Review",
                conclusion="failure",
            )
        self.assertEqual(result["id"], 7)
        self.assertEqual(
            [(r.method, r.full_url) for r in requests],
            [
                ("POST", "https://api.github.com/repos/owner/repo/check-runs"),
                ("PATCH", "https://api.github.com/repos/owner/repo/check-runs/7"),
                ("PATCH", "https://api.github.com/repos/owner/repo/check-runs/7"),
            ],
        )
        batches = [json.loads(r.data)["output"]["annotations"] for r in requests]
        self.assertEqual([len(b) for b in batches], [50, 50, 1])
        self.assertEqual([a for batch in batches for a in batch], annotations)

    def test_direct_check_writer_rejects_invalid_sha_without_network(self):
        with (
            patch("repo_review_agent.github.urlopen", side_effect=AssertionError("network")),
            self.assertRaisesRegex(GitHubIntegrationError, "SHA"),
        ):
            GitHubClient(token="test").create_annotated_check(
                "owner/repo", head_sha="main", annotations=[], summary="Review"
            )

    def test_malformed_file_page_is_not_silently_dropped(self):
        with (
            patch("repo_review_agent.github.urlopen", return_value=io.BytesIO(b"[{}, 1]")),
            self.assertRaisesRegex(GitHubIntegrationError, "file"),
        ):
            GitHubClient(token="test").list_pull_request_files("owner/repo", 85)

    def test_missing_created_check_id_prevents_batch_evidence_loss(self):
        requests = []

        def transport(request, **kwargs):
            requests.append(request)
            return io.BytesIO(b'{"html_url":"https://example.com/check"}')

        with (
            patch("repo_review_agent.github.urlopen", side_effect=transport),
            self.assertRaisesRegex(GitHubIntegrationError, "without an id"),
        ):
            GitHubClient(token="test").create_annotated_check(
                "owner/repo",
                head_sha=SHA,
                annotations=[
                    dict(
                        path="app.py",
                        start_line=1,
                        end_line=1,
                        annotation_level="warning",
                        message="risk",
                    )
                ]
                * 51,
                summary="Review",
            )
        self.assertEqual(len(requests), 1)

    def test_file_pages_use_pr_endpoint_and_do_not_lose_second_page(self):
        requests = []

        def transport(request, **kwargs):
            requests.append(request.full_url)
            page = (
                [dict(filename=f"file{i}.py", status="modified") for i in range(100)]
                if len(requests) == 1
                else [dict(filename="last.py", status="added")]
            )
            return io.BytesIO(json.dumps(page).encode())

        with patch("repo_review_agent.github.urlopen", side_effect=transport):
            files = GitHubClient(token="test").list_pull_request_files("owner/repo", 85)
        self.assertEqual(len(files), 101)
        self.assertEqual(files[-1]["filename"], "last.py")
        self.assertEqual(
            requests,
            [
                "https://api.github.com/repos/owner/repo/pulls/85/files?per_page=100&page=1",
                "https://api.github.com/repos/owner/repo/pulls/85/files?per_page=100&page=2",
            ],
        )

    def test_3000_file_cap_rejects_partial_diff(self):
        requests = []

        def transport(request, **kwargs):
            requests.append(request.full_url)
            return io.BytesIO(json.dumps([dict(filename=f"{i}.py") for i in range(100)]).encode())

        with (
            patch("repo_review_agent.github.urlopen", side_effect=transport),
            self.assertRaisesRegex(GitHubIntegrationError, "3000-file limit"),
        ):
            GitHubClient(token="test").list_pull_request_files("owner/repo", 85)
        self.assertEqual(len(requests), 30)
        self.assertTrue(requests[-1].endswith("page=30"))
