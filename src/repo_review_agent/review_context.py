"""Size-bounded structured context for model prompts and analysis tools."""
from __future__ import annotations

import json

from .models import Finding, ReviewReport
from .redaction import redact_data
from .report import public_metrics

PRIORITIES = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}


def bounded_json_text(value: str, limit: int) -> str:
    """Bound serialized size, including escaped control characters and quotes."""
    text = value[:limit]
    while len(json.dumps(text, ensure_ascii=False)) > limit:
        text = text[:len(text) // 2]
    return text


def finding_summary(finding: Finding) -> dict:
    original = redact_data({
        'title': finding.title, 'severity': finding.severity,
        'category': finding.category, 'rule_id': finding.rule_id,
        'recommendation': finding.recommendation,
        'evidence_paths': finding.evidence_paths,
    })
    summary = dict(original)
    truncated = []
    for key, limit in (('title', 400), ('severity', 50), ('category', 150),
                       ('rule_id', 150), ('recommendation', 1200)):
        if isinstance(summary[key], str):
            summary[key] = bounded_json_text(summary[key], limit)
            if summary[key] != original[key]:
                truncated.append(key)
    # A shortened path would name a different file. Omit oversized paths whole.
    paths = []
    for path in original['evidence_paths'][:3]:
        if len(json.dumps([*paths, path], ensure_ascii=False)) <= 1200:
            paths.append(path)
    summary['evidence_paths'] = paths
    if paths != original['evidence_paths']:
        truncated.append('evidence_paths')
    summary['truncated_fields'] = truncated
    return summary


def build_review_context(report: ReviewReport) -> str:
    """Reserve room for findings; remove whole fields/items before JSON encoding."""
    budget = 24000
    payload = {'repo_name': bounded_json_text(report.repo_name, 500),
               'generated_at': bounded_json_text(report.generated_at, 100),
               'overview': [], 'metrics': {}, 'framework_signals': {}, 'findings': [],
               'total_findings': len(report.findings), 'omitted_findings': len(report.findings),
               'truncated_fields': []}
    truncated = payload['truncated_fields']
    for key in ('repo_name', 'generated_at'):
        if payload[key] != getattr(report, key):
            truncated.append(key)
    # Each optional section has its own budget, leaving most of the prompt for findings.
    overview = [bounded_json_text(text, 500) for text in report.overview[:20]]
    for text in overview:
        if len(json.dumps([*payload['overview'], text], ensure_ascii=False)) <= 2000:
            payload['overview'].append(text)
    if payload['overview'] != report.overview:
        truncated.append('overview')
    metrics = public_metrics(report.metrics)
    # Put coverage before potentially huge inventories, patches or policy diagnostics.
    keys = list(dict.fromkeys(['review_coverage', 'files_scanned', 'files_skipped',
                              'source_files', 'test_files', *metrics]))
    for key in keys:
        if key in metrics:
            candidate = {**payload['metrics'], key: metrics[key]}
            if len(json.dumps(candidate, ensure_ascii=False)) <= 2500:
                payload['metrics'] = candidate
    if payload['metrics'] != metrics:
        truncated.append('metrics')
    for key, paths in report.framework_signals.items():
        candidate = {**payload['framework_signals'], key: paths}
        if len(json.dumps(candidate, ensure_ascii=False)) <= 1500:
            payload['framework_signals'] = candidate
    if payload['framework_signals'] != report.framework_signals:
        truncated.append('framework_signals')
    if report.metrics.get('review_scope') == 'incremental':
        payload['review_scope'] = 'incremental'
        payload['changed_files'] = []
        changes = report.metrics.get('changed_files', [])
        for change in changes[:40]:
            # Patches are available via tools, not copied wholesale into the initial prompt.
            summary = {key: change[key] for key in (
                'filename', 'previous_filename', 'status', 'added_line_ranges') if key in change}
            if len(json.dumps([*payload['changed_files'], summary], ensure_ascii=False)) <= 2000:
                payload['changed_files'].append(summary)
        if payload['changed_files'] != changes:
            truncated.append('changed_files')
    payload = redact_data(payload)
    findings = sorted(report.findings, key=lambda item: PRIORITIES.get(item.severity, 5))
    for finding in findings[:40]:
        summary = finding_summary(finding)
        evidence = redact_data(finding.evidence)
        summary['evidence'] = [bounded_json_text(text, 1200) for text in evidence[:3]]
        if summary['evidence'] != evidence:
            summary['truncated_fields'].append('evidence')
        candidate = {**payload, 'findings': [*payload['findings'], summary],
                     'omitted_findings': len(findings) - len(payload['findings']) - 1}
        # Reserve a small margin for the final truncation flag.
        if len(json.dumps(candidate, ensure_ascii=False)) > budget - 100:
            break
        payload = candidate
    if payload['omitted_findings'] or any(item['truncated_fields'] for item in payload['findings']):
        payload['truncated_fields'].append('findings')
    return json.dumps(payload, ensure_ascii=False)
