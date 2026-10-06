"""Safe report projection shared by synchronous and durable history writes."""
from __future__ import annotations

from .models import ReviewReport
from .redaction import redact_data


def history_payload(*, report: ReviewReport, repo_url: str, report_markdown: str,
                    owner_id: str | None = None, branch: str | None = None,
                    commit_sha: str | None = None) -> dict:
    return redact_data({
        'repo_url': repo_url, 'repo_name': report.repo_name, 'owner_id': owner_id,
        'branch': branch, 'commit_sha': commit_sha or report.metrics.get('source_commit_sha'),
        'report': report.to_dict(), 'report_markdown': report_markdown,
    })
