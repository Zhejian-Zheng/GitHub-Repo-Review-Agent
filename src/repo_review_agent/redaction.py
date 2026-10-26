"""Best-effort secret masking at model and report boundaries.

This does not make arbitrary source safe to publish. Private-key/environment
files are denied separately; callers should still review exported reports.
"""

from __future__ import annotations

import re
from typing import Any

_MARKER = '[REDACTED]'
_PATTERNS = [
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)', re.S),
    re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{8,}|AKIA[A-Z0-9]{16})\b'),
    re.compile(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b'),
    re.compile(r'(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+'),
    re.compile(r'(?i)(https?://)[^\s/:@]+:[^\s/@]+@'),
]
_ASSIGNMENT = re.compile(
    r'''(?im)(["']?\b(?:[\w-]*[_-])?(?:api[_-]?key|token|secret|password|passwd|credential|access[_-]?key)(?:[_-][\w-]+)?["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}\n]+)'''
)


def redact_text(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(lambda match: _MARKER + "\n" * match.group(0).count("\n"), text)
    return _ASSIGNMENT.sub(lambda match: match.group(1) + _MARKER, text)


def redact_data(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _MARKER if re.fullmatch(
                r"(?i)(?:[\w-]*[_-])?(?:api[_-]?key|token|secret|password|passwd|credential|access[_-]?key)",
                str(key),
            ) else redact_data(item)
            for key, item in value.items()
        }
    return value
