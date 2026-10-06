"""Canonical findings and feedback without discarding original review evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .models import Finding, ReviewReport


def finding_fingerprint(finding: Finding) -> str:
    if finding.fingerprint:
        return finding.fingerprint
    payload = {
        "title": finding.title.strip().lower(),
        "category": finding.category.strip().lower(),
        "evidence_paths": sorted(path.strip().lower() for path in finding.evidence_paths),
    }
    if finding.rule_id:
        payload["rule_id"] = finding.rule_id
    if finding.source == "ai":
        payload.update(source="ai", evidence=finding.evidence)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def review_findings(report: ReviewReport) -> list[Finding]:
    candidates = list(report.findings)
    if report.ai_review and report.ai_review.status == "generated":
        for item in report.ai_review.findings:
            candidates.append(
                Finding(
                    title=item["title"],
                    severity=item["severity"],
                    category=item.get("category", "code"),
                    evidence=[item["evidence"]]
                    if isinstance(item["evidence"], str)
                    else list(item["evidence"]),
                    recommendation=item["recommendation"],
                    evidence_paths=[item["path"]],
                    source="ai",
                    path=item["path"],
                    start_line=item["start_line"],
                    end_line=item["end_line"],
                    confidence=item.get("confidence"),
                    rule_id=item.get("rule_id"),
                )
            )
    unique = {}
    for finding in candidates:
        fingerprint = finding_fingerprint(finding)
        unique.setdefault(fingerprint, replace(finding, fingerprint=fingerprint))
    return list(unique.values())


def feedback_active(feedback: dict[str, Any], *, now: datetime | None = None) -> bool:
    expiry = feedback.get("expires_at")
    if expiry is None:
        return True
    try:
        expires = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if expires.tzinfo is None:
            return False
        return expires > (now or datetime.now(timezone.utc))
    except (ValueError, TypeError, AttributeError):
        return False


def effective_findings(
    report_or_findings: ReviewReport | list[Finding],
    feedback: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> list[Finding]:
    if isinstance(report_or_findings, ReviewReport):
        findings = review_findings(report_or_findings)
        feedback = report_or_findings.finding_feedback if feedback is None else feedback
    else:
        findings = report_or_findings
    suppressed = {
        row["fingerprint"]
        for row in feedback or []
        if row.get("status") in {"ignored", "false_positive"} and feedback_active(row, now=now)
    }
    return [item for item in findings if finding_fingerprint(item) not in suppressed]
