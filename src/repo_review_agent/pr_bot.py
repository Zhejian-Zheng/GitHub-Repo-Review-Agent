from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .findings import effective_findings
from .github import GitHubClient, GitHubIntegrationError, ensure_comment_marker
from .history import calculate_health_score, finding_fingerprint
from .models import AIReview, Finding, ReviewReport

SEVERITY_RANK = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}
PR_BOT_COMMENT_MARKER = "<!-- repo-review-agent:pr-bot -->"


@dataclass(frozen=True)
class PullRequestReviewDiff:
    current_report: ReviewReport
    baseline_report: ReviewReport | None
    new_findings: list[Finding]
    existing_findings: list[Finding]
    resolved_findings: list[Finding]
    changed_files: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_name": self.current_report.repo_name,
            "health_score": calculate_health_score(effective_findings(self.current_report)),
            "baseline": self.baseline_report.repo_name if self.baseline_report else None,
            "new_findings_count": len(self.new_findings),
            "existing_findings_count": len(self.existing_findings),
            "resolved_findings_count": len(self.resolved_findings),
        }


def build_pr_review_diff(
    current_report: ReviewReport,
    baseline_report: ReviewReport | None = None,
    *,
    changed_files: list[dict[str, Any]] | None = None,
) -> PullRequestReviewDiff:
    current_actionable = _incremental_findings(
        _actionable_findings(effective_findings(current_report)), changed_files
    )
    if baseline_report is None:
        return PullRequestReviewDiff(
            current_report=current_report,
            baseline_report=None,
            new_findings=current_actionable,
            existing_findings=[],
            resolved_findings=[],
            changed_files=changed_files,
        )

    baseline_actionable = _incremental_findings(
        _actionable_findings(effective_findings(baseline_report)), changed_files, baseline=True
    )
    current_by_fingerprint = {
        finding_fingerprint(finding): finding for finding in current_actionable
    }
    baseline_by_fingerprint = {
        finding_fingerprint(finding): finding for finding in baseline_actionable
    }

    new_findings = [
        finding
        for fingerprint, finding in current_by_fingerprint.items()
        if fingerprint not in baseline_by_fingerprint
    ]
    existing_findings = [
        finding
        for fingerprint, finding in current_by_fingerprint.items()
        if fingerprint in baseline_by_fingerprint
    ]
    resolved_findings = [
        finding
        for fingerprint, finding in baseline_by_fingerprint.items()
        if fingerprint not in current_by_fingerprint
    ]
    return PullRequestReviewDiff(
        current_report=current_report,
        baseline_report=baseline_report,
        new_findings=new_findings,
        existing_findings=existing_findings,
        resolved_findings=resolved_findings,
        changed_files=changed_files,
    )


def changed_line_ranges(files: list[dict[str, Any]]) -> dict[str, list[tuple[int, int]]]:
    """Return added head lines only from complete unified-diff hunks."""
    result = {}
    for file in files:
        path = file.get("filename")
        if not isinstance(path, str):
            continue
        result[path] = []
        patch = file.get("patch")
        if file.get("status") == "removed" or not isinstance(patch, str):
            continue
        added = []
        hunk_lines = []
        expected_old = expected_new = None
        line_number = 0
        old_count = new_count = 0
        valid = True
        for line in patch.splitlines():
            hunk = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if hunk:
                if expected_old is not None:
                    valid &= (old_count, new_count) == (expected_old, expected_new)
                    added.extend(hunk_lines)
                expected_old = int(hunk.group(2)) if hunk.group(2) is not None else 1
                expected_new = int(hunk.group(4)) if hunk.group(4) is not None else 1
                line_number = int(hunk.group(3))
                old_count = new_count = 0
                hunk_lines = []
            elif expected_old is not None:
                if line.startswith("+"):
                    hunk_lines.append(line_number)
                    new_count += 1
                    line_number += 1
                elif line.startswith("-"):
                    old_count += 1
                elif line.startswith(" "):
                    old_count += 1
                    new_count += 1
                    line_number += 1
                elif line != "\\ No newline at end of file":
                    valid = False
        if expected_old is None:
            continue
        valid &= (old_count, new_count) == (expected_old, expected_new)
        added.extend(hunk_lines)
        if not valid or any(number < 1 for number in added):
            continue
        ranges = []
        for number in sorted(set(added)):
            if ranges and ranges[-1][1] == number - 1:
                ranges[-1] = (ranges[-1][0], number)
            else:
                ranges.append((number, number))
        result[path] = ranges
    return result


def _incremental_findings(
    findings: list[Finding], files: list[dict[str, Any]] | None, *, baseline: bool = False
) -> list[Finding]:
    if files is None:
        return findings
    changed = {
        file.get("filename") for file in files if baseline or file.get("status") != "removed"
    }
    renames = {
        file["previous_filename"]: file["filename"]
        for file in files
        if file.get("status") == "renamed" and isinstance(file.get("previous_filename"), str)
    }
    scoped = []
    for finding in findings:
        if baseline and renames:
            paths = [renames.get(path, path) for path in finding.evidence_paths]
            path = renames.get(finding.path, finding.path)
            if paths != finding.evidence_paths or path != finding.path:
                finding = replace(finding, evidence_paths=paths, path=path, fingerprint=None)
        locations = set(finding.evidence_paths)
        if finding.path:
            locations.add(finding.path)
        # Rules without a location can apply to repository-wide configuration.
        if not locations or changed.intersection(locations):
            scoped.append(finding)
    return scoped


def build_pr_annotations(
    report: ReviewReport, changed_files: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    ranges = changed_line_ranges(changed_files)
    annotations = []
    for finding in effective_findings(report):
        if (
            not finding.path
            or not finding.start_line
            or not finding.end_line
            or finding.start_line < 1
            or finding.end_line < finding.start_line
        ):
            continue
        for start, end in ranges.get(finding.path, []):
            start = max(start, finding.start_line)
            end = min(end, finding.end_line)
            if start > end:
                continue
            annotations.append(
                {
                    "path": finding.path,
                    "start_line": start,
                    "end_line": end,
                    "annotation_level": {
                        "high": "failure",
                        "medium": "warning",
                        "low": "warning",
                    }.get(finding.severity, "notice"),
                    "title": finding.title[:255],
                    "message": (finding.recommendation + "\n\n" + "\n".join(finding.evidence))[
                        :65535
                    ],
                }
            )
    return annotations


def build_pr_bot_comment(
    review_diff: PullRequestReviewDiff, *, fail_on_severity: str | None = None
) -> str:
    current_report = review_diff.current_report
    health_score = calculate_health_score(effective_findings(current_report))
    lines = [
        PR_BOT_COMMENT_MARKER,
        "## Repository Review Agent",
        "",
        "### PR Review Summary",
        "",
        f"- Repository: `{current_report.repo_name}`",
        f"- Health score: `{health_score}`",
        f"- New findings: `{len(review_diff.new_findings)}`",
        f"- Existing findings: `{len(review_diff.existing_findings)}`",
        f"- Resolved findings: `{len(review_diff.resolved_findings)}`",
    ]
    if fail_on_severity:
        lines.append(f"- CI guard: blocks `{fail_on_severity}` or higher findings.")

    if current_report.ai_review and current_report.ai_review.status == "generated":
        lines.extend(["", "### AI Review", "", current_report.ai_review.summary])

    lines.extend(["", "### New Risks", ""])
    if review_diff.new_findings:
        for finding in review_diff.new_findings:
            lines.extend(_finding_comment_lines(finding))
    else:
        lines.append("- No new actionable findings compared with the baseline.")

    lines.extend(["", "### Resolved Since Baseline", ""])
    if review_diff.resolved_findings:
        for finding in review_diff.resolved_findings:
            lines.append(f"- **{finding.severity.upper()}**: {finding.title}")
    else:
        lines.append("- No previously detected findings were resolved in this diff.")

    return "\n".join(lines).strip() + "\n"


def blocking_findings(
    review_diff: PullRequestReviewDiff,
    *,
    fail_on_severity: str | None,
    scope: str = "new",
) -> list[Finding]:
    if not fail_on_severity:
        return []
    threshold = SEVERITY_RANK[fail_on_severity]
    candidates = (
        review_diff.new_findings
        if scope == "new"
        else _incremental_findings(
            _actionable_findings(effective_findings(review_diff.current_report)),
            review_diff.changed_files,
        )
    )
    return [
        finding for finding in candidates if SEVERITY_RANK.get(finding.severity, 0) >= threshold
    ]


def run_pr_bot(
    *,
    report_json: Path,
    baseline_json: Path | None = None,
    github_repo: str | None = None,
    pr_number: int | None = None,
    comment_mode: str = "dry-run",
    github_token: str | None = None,
    fail_on_severity: str | None = None,
    block_scope: str = "new",
    changed_files_json: Path | None = None,
    annotation_mode: str = "none",
    head_sha: str | None = None,
) -> dict[str, Any]:
    current_report = load_report_json(report_json)
    baseline_report = load_report_json(baseline_json) if baseline_json else None
    changed_files = None
    if changed_files_json:
        try:
            changed_files = json.loads(changed_files_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GitHubIntegrationError(f"Changed files JSON could not be read: {exc}") from exc
        if not isinstance(changed_files, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("filename"), str)
            and bool(item["filename"])
            and (item.get("patch") is None or isinstance(item["patch"], str))
            for item in changed_files
        ):
            raise GitHubIntegrationError(
                "Changed files JSON must be an array of GitHub file objects."
            )
    if annotation_mode not in {"none", "dry-run", "create"}:
        raise GitHubIntegrationError("Unsupported annotation mode.")
    if annotation_mode != "none" and changed_files is None:
        raise GitHubIntegrationError("--changed-files-json is required for line annotations.")
    if annotation_mode == "create" and (not github_repo or not head_sha):
        raise GitHubIntegrationError(
            "--github-repo and --head-sha are required for annotation create mode."
        )
    if annotation_mode == "create":
        if not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha or ""):
            raise GitHubIntegrationError("--head-sha must be an exact 40-character commit SHA.")
        if current_report.metrics.get("source_dirty"):
            raise GitHubIntegrationError(
                "Report source is dirty; generate a report from the exact clean head commit."
            )
        source_sha = current_report.metrics.get("source_commit_sha")
        if source_sha is not None and str(source_sha).lower() != head_sha.lower():
            raise GitHubIntegrationError(
                "Report source commit does not match --head-sha; regenerate the report."
            )
    review_diff = build_pr_review_diff(current_report, baseline_report, changed_files=changed_files)
    comment_body = build_pr_bot_comment(review_diff, fail_on_severity=fail_on_severity)

    result: dict[str, Any] = {
        **review_diff.to_dict(),
        "comment_mode": comment_mode,
        "blocked": False,
    }
    if comment_mode == "dry-run":
        result["body"] = comment_body
    elif comment_mode in {"create", "upsert"}:
        if not github_repo or pr_number is None:
            raise GitHubIntegrationError(
                "--github-repo and --pr-number are required for create/upsert mode."
            )
        client = GitHubClient(token=github_token)
        if comment_mode == "upsert":
            action, response = client.upsert_issue_comment(
                github_repo,
                pr_number,
                comment_body,
                marker=PR_BOT_COMMENT_MARKER,
            )
            result["comment_action"] = action
        else:
            response = client.create_issue_comment(
                github_repo,
                pr_number,
                ensure_comment_marker(comment_body, PR_BOT_COMMENT_MARKER),
            )
            result["comment_action"] = "created"
        result["comment_url"] = response.get("html_url")
    elif comment_mode != "none":
        raise GitHubIntegrationError(f"Unsupported PR bot comment mode: {comment_mode}")

    failures = blocking_findings(review_diff, fail_on_severity=fail_on_severity, scope=block_scope)
    if failures:
        result["blocked"] = True
        result["blocking_findings"] = [
            {
                "title": finding.title,
                "severity": finding.severity,
                "category": finding.category,
                "evidence_paths": finding.evidence_paths,
            }
            for finding in failures
        ]
    if annotation_mode != "none":
        annotations = build_pr_annotations(current_report, changed_files)
        result["annotations"] = annotations
        if annotation_mode == "create":
            response = GitHubClient(token=github_token).create_annotated_check(
                github_repo,
                head_sha=head_sha,
                annotations=annotations,
                summary=comment_body,
                conclusion="failure" if failures else "success",
            )
            result["check_url"] = response.get("html_url")
    return result


def load_report_json(path: Path | None) -> ReviewReport:
    if path is None:
        raise GitHubIntegrationError("Report JSON path is required.")
    data = json.loads(path.read_text(encoding="utf-8"))
    findings = [
        Finding(
            title=item["title"],
            severity=item["severity"],
            category=item["category"],
            evidence=list(item.get("evidence") or []),
            recommendation=item["recommendation"],
            evidence_paths=list(item.get("evidence_paths") or []),
            **{
                key: item[key]
                for key in (
                    "source",
                    "rule_id",
                    "path",
                    "start_line",
                    "end_line",
                    "confidence",
                    "fingerprint",
                )
                if key in item
            },
        )
        for item in data.get("findings", [])
    ]
    ai_review_data = data.get("ai_review")
    ai_review = None
    if isinstance(ai_review_data, dict):
        ai_review = AIReview(
            provider=ai_review_data.get("provider", "unknown"),
            model=ai_review_data.get("model", "unknown"),
            status=ai_review_data.get("status", "unknown"),
            summary=ai_review_data.get("summary", ""),
            error=ai_review_data.get("error"),
            sections=ai_review_data.get("sections"),
            findings=list(ai_review_data.get("findings") or []),
        )

    return ReviewReport(
        repo_name=data.get("repo_name", path.stem),
        generated_at=data.get("generated_at", ""),
        overview=list(data.get("overview") or []),
        metrics=dict(data.get("metrics") or {}),
        framework_signals=dict(data.get("framework_signals") or {}),
        findings=findings,
        ai_review=ai_review,
        finding_feedback=list(data.get("finding_feedback") or []),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    fail_on_severity = None if args.fail_on_severity == "none" else args.fail_on_severity
    try:
        result = run_pr_bot(
            report_json=args.report_json,
            baseline_json=args.baseline_json,
            github_repo=args.github_repo,
            pr_number=args.pr_number,
            comment_mode=args.comment_mode,
            github_token=args.github_token,
            fail_on_severity=fail_on_severity,
            block_scope=args.block_scope,
            changed_files_json=args.changed_files_json,
            annotation_mode=args.annotation_mode,
            head_sha=args.head_sha,
        )
    except GitHubIntegrationError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps({"pr_bot": result}, indent=2, ensure_ascii=False))
    if result["blocked"]:
        raise SystemExit("Repository review blocked CI because threshold findings were detected.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-review-pr-bot",
        description="Compare repository review reports, comment on PRs, and fail CI on risk thresholds.",
    )
    parser.add_argument(
        "--report-json", type=Path, required=True, help="Current review JSON report."
    )
    parser.add_argument("--baseline-json", type=Path, help="Baseline JSON report for comparison.")
    parser.add_argument("--github-repo", help="GitHub repository slug, for example owner/repo.")
    parser.add_argument("--pr-number", type=int, help="Pull request number to comment on.")
    parser.add_argument("--github-token", help="GitHub token. Defaults to GITHUB_TOKEN.")
    parser.add_argument(
        "--comment-mode",
        choices=["none", "dry-run", "create", "upsert"],
        default="dry-run",
        help="Whether to print, skip, create, or update the sticky PR comment.",
    )
    parser.add_argument(
        "--fail-on-severity",
        choices=["none", "low", "medium", "high"],
        default="none",
        help="Exit non-zero when findings at this severity or higher are present.",
    )
    parser.add_argument(
        "--block-scope",
        choices=["new", "all"],
        default="new",
        help="Apply the CI gate to only new findings or to all current findings.",
    )
    parser.add_argument(
        "--changed-files-json",
        type=Path,
        help="GitHub PR files API JSON array for incremental findings.",
    )
    parser.add_argument("--annotation-mode", choices=["none", "dry-run", "create"], default="none")
    parser.add_argument("--head-sha", help="Exact PR head commit for Checks annotations.")
    return parser


def _actionable_findings(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.severity != "info"]


def _finding_comment_lines(finding: Finding) -> list[str]:
    lines = [
        f"- **{finding.severity.upper()}**: {finding.title}",
        f"  - Category: `{finding.category}`",
        f"  - Recommendation: {finding.recommendation}",
    ]
    if finding.evidence_paths:
        evidence_paths = ", ".join(f"`{path}`" for path in finding.evidence_paths)
        lines.append(f"  - Evidence files: {evidence_paths}")
    return lines


if __name__ == "__main__":
    sys.exit(main())
