"""Canonical findings and feedback without discarding original review evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .models import Finding, ReviewReport


def ruff_rule_code(finding: Finding) -> str | None:
    """Recognize current rule groups and legacy display-only Ruff findings."""
    if finding.source != 'rule':
        return None
    match = re.fullmatch(r'ruff\.([A-Z][A-Z0-9]*|syntax-error)', finding.rule_id or '')
    if not match:
        match = re.fullmatch(r'Fix \d+ Ruff ([A-Z][A-Z0-9]*|syntax-error) lint finding\(s\)', finding.title)
    return match[1] if match else None


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
    code = ruff_rule_code(finding)
    if code and finding.rule_id == f'ruff.{code}':
        # A finding represents the whole rule group; samples and counts are display data.
        # Persisted legacy fingerprints above are deliberately never rewritten.
        payload = {'identity_version': 'ruff-group-v1', 'source': 'rule', 'rule_id': finding.rule_id}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def review_findings(report: ReviewReport) -> list[Finding]:
    candidates = list(report.findings)
    if not report.findings_canonical and report.ai_review and report.ai_review.status == "generated":
        for item in report.ai_review.findings:
            candidate = Finding(
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
            # Persisted canonical findings already carry their original fingerprint.
            # Rehashing redacted AI evidence would create a second identity.
            if not any(replace(existing, fingerprint=None) == candidate for existing in candidates):
                candidates.append(candidate)
    unique = {}
    for finding in candidates:
        fingerprint = finding_fingerprint(finding)
        unique.setdefault(fingerprint, replace(finding, fingerprint=fingerprint))
    return list(unique.values())


def canonicalize_report(report: ReviewReport) -> ReviewReport:
    """Capture identity before redaction/localization; accept legacy projections."""
    return replace(report, findings=review_findings(report), findings_canonical=True)


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
