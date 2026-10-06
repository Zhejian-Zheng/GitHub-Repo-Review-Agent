"""Validated PR context for bounded repository inspection."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath


def normalize_changed_files(files: list[dict] | None) -> list[dict] | None:
    if files is None:
        return None
    if not isinstance(files, list) or len(files) > 3000 or len(json.dumps(files).encode()) > 2_000_000:
        raise ValueError('Changed-file context must be an array of at most 3000 files and 2 MB.')
    result = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError('Changed-file entries must be objects.')
        name = item.get('filename')
        if (not isinstance(name, str) or not name or len(name) > 500 or '\\' in name or '\x00' in name
                or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts):
            raise ValueError('Changed filenames must be repository-relative paths.')
        if item.get('patch') is not None and not isinstance(item['patch'], str):
            raise ValueError('Changed-file patches must be strings or null.')
        result.append({**item, 'filename': PurePosixPath(name).as_posix()})
    return result


def load_changed_files(path: Path) -> list[dict]:
    try:
        with path.open('rb') as stream:
            raw = stream.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Changed-file context exceeds 2 MB.')
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError('Changed-file context must be an array.')
        return normalize_changed_files(parsed)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError('Invalid or unreadable changed-file context JSON.') from exc


def diff_summary(files: list[dict]) -> list[dict]:
    from .pr_bot import changed_line_ranges
    ranges = changed_line_ranges(files)
    return [{'filename':item['filename'], 'status':item.get('status','modified'),
             'added_line_ranges':ranges.get(item['filename'], [])} for item in files[:100]]
