"""Opt-in, bounded OSV lookup of exact dependency versions; executes no packages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import Request, urlopen

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from .models import Finding
from .scanner import scan_repository

OSV_BATCH_URL = 'https://api.osv.dev/v1/querybatch'
_MAX_LOCK_BYTES = 2_097_152
_MAX_RESPONSE_BYTES = 1_048_576
_MAX_PACKAGES = 500
_MAX_LOCKFILES = 20
_BATCH_SIZE = 100
_NAME = re.compile(r'(?:@[a-zA-Z0-9._-]+/)?[a-zA-Z0-9][a-zA-Z0-9._-]{0,213}\Z')
_NPM_NUMBER = r'(?:0|[1-9][0-9]*)'
_NPM_PRERELEASE = r'(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)'
_NPM_VERSION = re.compile(
    rf'{_NPM_NUMBER}\.{_NPM_NUMBER}\.{_NPM_NUMBER}'
    rf'(?:-{_NPM_PRERELEASE}(?:\.{_NPM_PRERELEASE})*)?'
    r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z'
)
_ADVISORY_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}\Z')


@dataclass(frozen=True)
class VulnerabilityScan:
    findings: list[Finding] = field(default_factory=list)
    status: str = 'unavailable'
    details: list[str] = field(default_factory=list)
    checked_packages: int = 0
    total_packages: int = 0


def _parse_lock(path: str, raw: bytes) -> tuple[list[tuple[str, str, str]], bool]:
    text = raw.decode('utf-8')
    packages = []
    incomplete = False
    if Path(path).name == 'package-lock.json':
        data = json.loads(text)
        if (not isinstance(data, dict) or type(data.get('lockfileVersion')) is not int
                or data['lockfileVersion'] not in {2, 3} or not isinstance(data.get('packages'), dict)):
            raise ValueError('Unsupported npm lockfile schema')
        for location, package in data['packages'].items():
            if not location or 'node_modules/' not in location:
                continue
            if not isinstance(package, dict):
                incomplete = True
                continue
            name = package.get('name', location.rsplit('node_modules/', 1)[1])
            version = package.get('version')
            resolved = package.get('resolved')
            if (package.get('link') or not isinstance(name, str) or len(name) > 214
                    or not _NAME.fullmatch(name) or not isinstance(version, str)
                    or len(version) > 100 or not _NPM_VERSION.fullmatch(version)
                    or (resolved is not None and (not isinstance(resolved, str)
                        or not resolved.startswith(('https://', 'http://'))))):
                incomplete = True
                continue
            packages.append(('npm', name, version))
    else:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            line = re.split(r'\s+#', line, maxsplit=1)[0].strip()
            try:
                requirement = Requirement(line)
                specifiers = list(requirement.specifier)
                if (requirement.url is not None or len(specifiers) != 1
                        or specifiers[0].operator != '==' or '*' in specifiers[0].version):
                    raise ValueError('Not an exact registry version')
                name = requirement.name
                version = str(Version(specifiers[0].version))
            except (InvalidRequirement, InvalidVersion, ValueError):
                incomplete = True
                continue
            if len(name) > 214 or len(version) > 100:
                incomplete = True
                continue
            packages.append(('PyPI', re.sub(r'[-_.]+', '-', name).lower(), version))
    return packages, incomplete


def _query_batch(packages: list[tuple[str, str, str]]) -> list[dict]:
    payload = json.dumps({'queries': [
        {'package': {'ecosystem': ecosystem, 'name': name}, 'version': version}
        for ecosystem, name, version in packages
    ]}).encode('utf-8')
    if len(payload) > 65_536:
        raise ValueError('Request too large')
    request = Request(OSV_BATCH_URL, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=5) as response:
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError('Response too large')
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('results'), list) or len(data['results']) != len(packages):
        raise ValueError('Incomplete OSV result')
    for result in data['results']:
        if (not isinstance(result, dict) or not isinstance(result.get('vulns', []), list)
                or set(result) - {'vulns', 'next_page_token'}):
            raise ValueError('Invalid OSV result')
        for item in result.get('vulns', []):
            if (not isinstance(item, dict) or not isinstance(item.get('id'), str)
                    or not _ADVISORY_ID.fullmatch(item['id'])):
                raise ValueError('Invalid advisory identifier')
        if 'next_page_token' in result and not isinstance(result['next_page_token'], str):
            raise ValueError('Invalid OSV continuation')
    return data['results']


def scan_vulnerabilities(root: Path, *, ignore_patterns: list[str] | tuple[str, ...] = ()) -> VulnerabilityScan:
    root = root.resolve()
    snapshot = scan_repository(root, max_files=0, ignore_patterns=ignore_patterns)
    inventory = snapshot.inventory_files or []
    supported = [file for file in inventory if Path(file.path).name == 'package-lock.json'
                 or (Path(file.path).name.startswith('requirements') and file.path.endswith('.txt'))]
    supported.sort(key=lambda file: file.path)
    details = []
    if not snapshot.inventory_complete:
        details.append('Dependency file inventory is incomplete.')
    if len(supported) > _MAX_LOCKFILES:
        details.append('Only the first 20 supported dependency files were checked.')
    dependencies: dict[tuple[str, str, str], set[str]] = {}
    for file in supported[:_MAX_LOCKFILES]:
        try:
            path = root / file.path
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Unsafe dependency file')
            with path.open('rb') as stream:
                raw = stream.read(_MAX_LOCK_BYTES + 1)
            if len(raw) > _MAX_LOCK_BYTES:
                raise ValueError('Oversized dependency file')
            packages, incomplete = _parse_lock(file.path, raw)
            if incomplete:
                details.append(f'{file.path}: some entries were not exact supported versions.')
            for package in packages:
                dependencies.setdefault(package, set()).add(file.path)
        except (OSError, ValueError, UnicodeError, RecursionError):
            details.append(f'{file.path}: dependency file could not be fully parsed.')
    if not dependencies:
        return VulnerabilityScan(details=details + ['No supported exact dependency versions were available.'])
    all_packages = sorted(dependencies)
    packages = all_packages[:_MAX_PACKAGES]
    if len(all_packages) > _MAX_PACKAGES:
        details.append('Only the first 500 distinct package versions were checked.')
    findings = []
    checked = 0
    for offset in range(0, len(packages), _BATCH_SIZE):
        batch = packages[offset:offset + _BATCH_SIZE]
        try:
            results = _query_batch(batch)
        except (OSError, ValueError, RecursionError):
            details.append('An OSV batch was unavailable or invalid; remaining packages were not checked.')
            break
        checked += len(batch)
        for package, result in zip(batch, results, strict=True):
            if result.get('next_page_token'):
                details.append('OSV returned additional advisory pages; results are incomplete.')
            ids = sorted({item['id'] for item in result.get('vulns', [])})
            if not ids:
                continue
            ecosystem, name, version = package
            findings.append(Finding(
                title=f'Known vulnerabilities in {name}@{version}', severity='medium',
                category='dependency vulnerabilities', rule_id='dependency.osv',
                evidence=[f'{ecosystem} {name}@{version}: https://osv.dev/vulnerability/{identifier}' for identifier in ids[:20]],
                recommendation='Review the linked OSV advisories and upgrade to a compatible fixed release. Advisory severity was not provided by the batch API.',
                evidence_paths=sorted(dependencies[package]),
            ))
            if len(ids) > 20:
                details.append('Advisory evidence was limited to 20 IDs per package version.')
    status = 'unavailable' if not checked else 'partial' if details else 'findings' if findings else 'clean'
    return VulnerabilityScan(findings, status, list(dict.fromkeys(details)), checked, len(all_packages))
