"""Evidence required to distinguish resolution from an omitted check."""
from __future__ import annotations

from .findings import ruff_rule_code
from .models import Finding, ReviewReport


def review_policy(report: ReviewReport) -> dict:
    policy = report.metrics.get('policy_config') or {}
    return {key: policy.get(key, default) for key, default in (
        ('ignore', []), ('disabled_rules', []), ('disabled_categories', []), ('severity_overrides', {}))}


def finding_rechecked(finding: Finding, current: ReviewReport, previous: ReviewReport,
                      *, removed_paths: set[str] | None = None) -> bool:
    """Fail closed for legacy/partial reports, policy changes and model omission."""
    if review_policy(current) != review_policy(previous):
        return False
    coverage = current.metrics.get('review_coverage') or {}
    code = ruff_rule_code(finding)
    if code:
        # A legacy identity or disappearing sample is not proof the rule group is clean.
        return (coverage.get('version') == 1 and coverage.get('ruff_complete') is True
                and not any(ruff_rule_code(item) == code
                            for item in [*current.findings, *current.raw_findings]))
    paths = set(finding.evidence_paths)
    if finding.path:
        paths.add(finding.path)
    if paths and paths <= (removed_paths or set()):
        return True
    if coverage.get('version') != 1:
        return False
    previous_paths = set((previous.metrics.get('review_coverage') or {}).get('inventory_paths', []))
    inventory_paths = coverage.get('inventory_paths')
    # A compressed API report removes the path list; missing evidence must not
    # be mistaken for an empty inventory. Only an explicit list can prove deletion.
    inventory_known = (isinstance(inventory_paths, list)
                       and coverage.get('inventory_paths_elided') is not True)
    if (paths and inventory_known and paths <= previous_paths
            and coverage.get('inventory_complete') is True
            and paths.isdisjoint(inventory_paths)):
        return True
    if finding.source == 'ai':
        # A generated response can omit a still-valid defect, even after reading it.
        return False
    if finding.rule_id == 'dependency.osv' or finding.category == 'dependency vulnerabilities':
        return (coverage.get('inventory_complete') is True
                and (current.metrics.get('vulnerability_scan') or {}).get('status') in {'clean', 'findings'})
    completed = coverage.get('completed_rules')
    if isinstance(completed, list) and finding.title in completed:
        return True
    return coverage.get('rules_complete') is True
