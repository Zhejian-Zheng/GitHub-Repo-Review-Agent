"""Local, versioned regression datasets with opt-in privacy-preserving Langfuse scores."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .redaction import redact_text
from .review_tools import ReviewSession
from .service import run_review
from .telemetry import record_evaluation_scores, review_tracing


class DefectLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=500)
    start_line: int = Field(ge=1, strict=True)
    end_line: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def validate_location(self):
        from pathlib import PurePosixPath
        if (self.end_line < self.start_line or PurePosixPath(self.path).is_absolute()
                or ".." in PurePosixPath(self.path).parts or "\\" in self.path or "\x00" in self.path):
            raise ValueError("Defect locations must be bounded repository-relative ranges.")
        return self


class DefectLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    locations: list[DefectLocation] = Field(min_length=1, max_length=10)


class Case(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=500)
    expected_findings: list[str] = Field(default_factory=list, max_length=100)
    forbidden_findings: list[str] = Field(default_factory=list, max_length=100)
    acceptable_findings: list[str] | None = Field(default=None, max_length=100)
    expected_defects: list[str] = Field(default_factory=list, max_length=100)
    acceptable_defects: list[DefectLabel] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_defects(self):
        ids = [label.id for label in self.acceptable_defects or []]
        if len(set(ids)) != len(ids) or not set(self.expected_defects) <= set(ids):
            raise ValueError("Expected defect IDs must reference unique acceptable defects.")
        return self


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
        'evidence_location_recall': None,
        'evidence_location_precision': None,
        'semantic_recall': None,
        'semantic_precision': None,
    }
    cited = [f for f in data['findings'] if f.get('source') == 'ai']
    valid_indices = set()
    if root is not None and cited:
        session = ReviewSession(root)
        valid = 0
        for index, finding in enumerate(cited):
            try:
                text = session.read_safe_text(finding['path']).splitlines()
                start, end = finding['start_line'], finding['end_line']
                if type(start) is not int or type(end) is not int:
                    continue
                quote = '\n'.join(text[start - 1:end])
                if 0 < start <= end <= len(text) and quote == '\n'.join(finding['evidence']) and '[REDACTED]' not in quote:
                    valid += 1
                    valid_indices.add(index)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        scores['citation_validity'] = valid / len(cited)
    if root is not None and labels.get("acceptable_defects") is not None:
        expected_ids = set(labels.get("expected_defects", []))
        defects = sorted(labels["acceptable_defects"], key=lambda d: d["id"] not in expected_ids)
        edges = {}
        for defect in defects:
            edges[defect["id"]] = [
                index for index, finding in enumerate(cited) if index in valid_indices
                and any(finding["path"] == location["path"]
                        and location["start_line"] <= finding["start_line"]
                        <= finding["end_line"] <= location["end_line"]
                        for location in defect["locations"])
            ]
        matched = {}

        def match(label, visited):
            for index in edges[label]:
                if index in visited:
                    continue
                visited.add(index)
                if index not in matched or match(matched[index], visited):
                    matched[index] = label
                    return True
            return False

        for defect in defects:
            match(defect["id"], set())
        scores["evidence_location_precision"] = len(matched) / len(cited) if cited else 1.0
        scores["evidence_location_recall"] = len(set(matched.values()) & expected_ids) / len(expected_ids) if expected_ids else 1.0
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
                                'langfuse_scores_queued': exported,
                                'expected_defects': case.expected_defects,
                                'acceptable_defects': [d.model_dump() for d in case.acceptable_defects] if case.acceptable_defects is not None else None,
                                'review_candidates': [f for f in report.to_dict()['findings'] if f.get('source') == 'ai']})
    summary = {}
    for name in ('recall', 'precision', 'forbidden_pass', 'citation_validity', 'ai_success',
                 'evidence_location_recall', 'evidence_location_precision', 'semantic_recall', 'semantic_precision'):
        values = [row['scores'][name] for row in results if row['scores'][name] is not None]
        summary[name] = sum(values) / len(values) if values else None
    return {'dataset_sha256': hashlib.sha256(raw).hexdigest(), 'label': redact_text(label[:100]),
            'provider': provider, 'model': model, 'cases': results, 'summary': summary,
            'limitations': ['Precision is unavailable without exhaustive acceptable_findings labels.',
                            'Citation validity checks exact source quotations, not semantic correctness.',
                            'Location matches identify benchmark evidence only. Semantic metrics require independent human adjudication.',
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
    parser.add_argument('--min-location-recall', type=float)
    parser.add_argument('--min-location-precision', type=float)
    args = parser.parse_args(argv)
    from .env import load_local_env
    load_local_env()
    for threshold in (args.min_recall, args.min_precision, args.min_location_recall, args.min_location_precision):
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
    for threshold, key in ((args.min_location_recall, "evidence_location_recall"),
                           (args.min_location_precision, "evidence_location_precision")):
        if threshold is not None:
            failed |= summary.get(key) is None or summary[key] < threshold
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
