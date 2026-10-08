"""Bounded, declarative project policy; never grants execution or network access."""

from __future__ import annotations

import fnmatch
import json
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, StringConstraints, field_validator

from .findings import finding_fingerprint
from .models import Finding, ReviewReport

Selector = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Selectors = Annotated[list[Selector], Field(max_length=100)]
Severity = Literal['high', 'medium', 'low', 'info']


class ReviewConfig(BaseModel):
    _source: str = PrivateAttr(default="explicit")
    model_config = ConfigDict(extra='forbid', strict=True)
    ignore: Selectors = Field(default_factory=list)
    disabled_rules: Selectors = Field(default_factory=list)
    disabled_categories: Selectors = Field(default_factory=list)
    severity_overrides: dict[Selector, Severity] = Field(default_factory=dict, max_length=100)

    @field_validator('ignore')
    @classmethod
    def relative_globs(cls, patterns):
        for pattern in patterns:
            if (pattern.startswith(('/', '!', '~')) or '\\' in pattern or ':' in pattern
                    or '..' in pattern.split('/') or '\x00' in pattern):
                raise ValueError('Ignore patterns must be repository-relative globs.')
        return patterns


def path_is_ignored(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    """Case-sensitive root-relative globs; matching a directory ignores descendants."""
    parts = path.rstrip('/').split('/')
    candidates = ['/'.join(parts[:i]) for i in range(1, len(parts) + 1)]
    for pattern in patterns:
        variants = [pattern.rstrip('/')]
        if pattern.startswith('**/'):
            variants.append(pattern[3:].rstrip('/'))
        if pattern.endswith('/**'):
            variants.append(pattern[:-3])
        if any(fnmatch.fnmatchcase(candidate, variant)
               for candidate in candidates for variant in variants):
            return True
    return False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate configuration key.')
        result[key] = value
    return result


def load_review_config(root: Path, config_path: Path | None = None) -> ReviewConfig:
    path = Path(config_path) if config_path is not None else root / '.repo-review.json'
    if not path.exists() and not path.is_symlink() and config_path is None:
        return ReviewConfig()
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Configuration must be a regular file, not a symlink.')
        with path.open('rb') as stream:
            raw = stream.read(65_537)
        if len(raw) > 65_536:
            raise ValueError('Configuration exceeds 64 KiB.')
        parsed = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
        config = ReviewConfig.model_validate(parsed)
        config._source = "explicit" if config_path is not None else "repository"
        return config
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError('Invalid review configuration: use a regular JSON file up to 64 KiB with supported policy fields.') from exc


def apply_review_config(report: ReviewReport, config: ReviewConfig) -> ReviewReport:
    originals = {finding_fingerprint(f): f for f in report.raw_findings}
    candidates = list(report.findings)
    if report.ai_review:
        for item in report.ai_review.findings:
            evidence = item.get("evidence", [])
            candidates.append(Finding(
                title=item.get("title", ""), severity=item.get("severity", "info"),
                category=item.get("category", "code"),
                evidence=[evidence] if isinstance(evidence, str) else evidence,
                recommendation=item.get("recommendation", ""),
                evidence_paths=[item.get("path", "")], source="ai",
                path=item.get("path"), start_line=item.get("start_line"),
                end_line=item.get("end_line"), confidence=item.get("confidence"),
                rule_id=item.get("rule_id")))
    decisions = {d["fingerprint"]: d for d in report.policy_decisions}
    for finding in candidates:
        key = finding_fingerprint(finding)
        originals.setdefault(key, replace(finding, fingerprint=key))

    def permitted(title, category, rule_id, paths):
        return not (
            title in config.disabled_rules or rule_id in config.disabled_rules
            or category in config.disabled_categories
            or (paths and all(path_is_ignored(path, config.ignore) for path in paths))
        )

    def severity(title, rule_id, original):
        return config.severity_overrides.get(rule_id, config.severity_overrides.get(title, original))

    for finding in candidates:
        key = finding_fingerprint(finding)
        allowed = permitted(finding.title, finding.category, finding.rule_id, finding.evidence_paths)
        effective_severity = severity(finding.title, finding.rule_id, finding.severity)
        if not allowed or effective_severity != finding.severity:
            decisions[key] = {"fingerprint": key, "action": "suppressed" if not allowed else "severity_override",
                              "source": config._source, "original_severity": originals[key].severity,
                              "effective_severity": effective_severity if allowed else None}

    findings = [replace(finding, severity=severity(finding.title, finding.rule_id, finding.severity))
                for finding in report.findings
                if permitted(finding.title, finding.category, finding.rule_id, finding.evidence_paths)]
    ai = report.ai_review
    if ai is not None:
        ai_findings = [{**finding, 'severity': severity(finding.get('title'), finding.get('rule_id'),
                                                       finding.get('severity', 'info'))}
                       for finding in ai.findings
                       if permitted(finding.get('title'), finding.get('category', 'code'),
                                    finding.get('rule_id'), [finding.get('path', '')])]
        ai = replace(ai, findings=ai_findings)
    return replace(report, findings=findings, ai_review=ai, raw_findings=list(originals.values()),
                   policy_decisions=list(decisions.values()), metrics={
        **report.metrics, 'policy_source': config._source, 'policy_config': config.model_dump(),
        'config_suppressed_findings': report.metrics.get('config_suppressed_findings', 0)
        + len(report.findings) - len(findings)
        + (len(report.ai_review.findings) - len(ai.findings) if ai else 0),
    })
