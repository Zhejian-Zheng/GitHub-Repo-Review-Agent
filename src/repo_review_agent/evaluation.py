"""Local, versioned regression datasets with opt-in privacy-preserving Langfuse scores."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field

from .redaction import redact_text
from .review_tools import ReviewSession
from .service import run_review
from .telemetry import record_evaluation_scores, review_tracing


class Case(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=500)
    expected_findings: list[str] = Field(default_factory=list, max_length=100)
    forbidden_findings: list[str] = Field(default_factory=list, max_length=100)
    acceptable_findings: list[str] | None = Field(default=None, max_length=100)


class Dataset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cases: list[Case] = Field(min_length=1, max_length=50)


def score_report(report, labels: dict, root: Path | None = None) -> dict:
    data = report.to_dict()
    titles = {f['title'] for f in data['findings']}
    expected = set(labels.get('expected_findings', []))
    forbidden = set(labels.get('forbidden_findings', []))
    acceptable = labels.get('acceptable_findings')
    scores = {
        'recall': len(titles & expected) / len(expected) if expected else 1.0,
        'precision': len(titles & set(acceptable)) / len(titles) if acceptable is not None and titles else (1.0 if acceptable is not None else None),
        'forbidden_pass': 0.0 if titles & forbidden else 1.0,
        'citation_validity': None,
        'ai_success': float(report.ai_review.status == 'generated') if report.ai_review else None,
    }
    cited = [f for f in data['findings'] if f.get('source') == 'ai']
    if root is not None and cited:
        session = ReviewSession(root)
        valid = 0
        for finding in cited:
            try:
                text = session.read_safe_text(finding['path']).splitlines()
                start, end = finding['start_line'], finding['end_line']
                if type(start) is not int or type(end) is not int:
                    continue
                quote = '\n'.join(text[start - 1:end])
                valid += int(0 < start <= end <= len(text) and quote == '\n'.join(finding['evidence']) and '[REDACTED]' not in quote)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        scores['citation_validity'] = valid / len(cited)
    return scores


def run_dataset(path: Path, *, provider: str = 'none', model: str | None = None,
                label: str = 'default', repeats: int = 1, token_budget: int = 50000) -> dict:
    if not 1 <= repeats <= 5:
        raise ValueError('Evaluation repeats must be between 1 and 5.')
    path = path.resolve()
    with path.open('rb') as stream:
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError('Evaluation dataset exceeds one megabyte.')
    dataset = Dataset.model_validate_json(raw)
    if len({c.id for c in dataset.cases}) != len(dataset.cases):
        raise ValueError('Evaluation case IDs must be unique.')
    resolved = []
    for case in dataset.cases:
        target = (path.parent / case.target).resolve()
        if Path(case.target).is_absolute() or not target.is_relative_to(path.parent) or not target.is_dir():
            raise ValueError('Evaluation targets must be local directories within the dataset folder.')
        resolved.append((case, target))
    results = []
    for case, target in resolved:
        for trial in range(repeats):
            with TemporaryDirectory(prefix='repo-review-evaluation-') as temporary:
                root = Path(temporary) / 'repository'
                # Never follow links when importing evaluation fixtures.
                shutil.copytree(target, root, symlinks=True, ignore=shutil.ignore_patterns('expected.json', '.git', '.venv', 'node_modules'))
                begin = time.monotonic()
                with review_tracing():
                    report = run_review(root, ai_provider=provider, ai_model=model, ai_token_budget=token_budget)
                    scores = score_report(report, case.model_dump(), root)
                    latency = time.monotonic() - begin
                    exported = record_evaluation_scores({**scores, 'latency_seconds': latency})
                results.append({'id': case.id, 'trial': trial + 1, 'scores': scores,
                                'latency_seconds': latency, 'actual_tokens': report.metrics.get('ai_usage', {}).get('actual_tokens'),
                                'langfuse_scores_queued': exported})
    summary = {}
    for name in ('recall', 'precision', 'forbidden_pass', 'citation_validity', 'ai_success'):
        values = [row['scores'][name] for row in results if row['scores'][name] is not None]
        summary[name] = sum(values) / len(values) if values else None
    return {'dataset_sha256': hashlib.sha256(raw).hexdigest(), 'label': redact_text(label[:100]),
            'provider': provider, 'model': model, 'cases': results, 'summary': summary,
            'limitations': ['Precision is unavailable without exhaustive acceptable_findings labels.',
                            'Citation validity checks exact source quotations, not semantic correctness.',
                            'Provider cost is unavailable locally; Langfuse may derive it from provider usage.']}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--provider', default='none', choices=['none', 'openai', 'openrouter', 'anthropic', 'ollama'])
    parser.add_argument('--model')
    parser.add_argument('--label', default='default')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--token-budget', type=int, default=50000)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--min-recall', type=float, default=1)
    parser.add_argument('--min-precision', type=float)
    args = parser.parse_args(argv)
    from .env import load_local_env
    load_local_env()
    for threshold in (args.min_recall, args.min_precision):
        if threshold is not None and not 0 <= threshold <= 1:
            parser.error('Thresholds must be between zero and one.')
    result = run_dataset(args.dataset, provider=args.provider, model=args.model, label=args.label,
                         repeats=args.repeats, token_budget=args.token_budget)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    else:
        print(text)
    summary = result['summary']
    failed = summary['recall'] < args.min_recall or summary['forbidden_pass'] < 1
    if args.provider != 'none' and summary['ai_success'] != 1:
        failed = True
    if args.min_precision is not None:
        failed |= summary['precision'] is None or summary['precision'] < args.min_precision
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
