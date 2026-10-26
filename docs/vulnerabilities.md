# Optional dependency vulnerability checks

Enable a lookup explicitly:

```sh
repo-review ./my-project --vulnerability-scan
```

This sends discovered package names, ecosystems and exact versions to `https://api.osv.dev/v1/querybatch`. It sends no source files, repository URL, local paths, registry credentials or lockfile contents. Private package names are still package names: enable this only when sharing those identifiers with OSV is acceptable. A repository configuration file cannot enable the network lookup.

## Supported inputs

- npm `package-lock.json` version 2 or 3: exact versions from the `packages` map, including nested and scoped packages. Workspace links, file/Git/relative resolved sources, malformed SemVer and unresolved/non-version entries make coverage partial.
- `requirements*.txt`: exact `name==version` pins, optionally with extras or an environment marker. Versions and markers are parsed with packaging; exact PEP 440 versions are normalized. Conditional pins are queried without evaluating the marker. Unpinned ranges, direct URLs, includes and hash continuation syntax are not resolved and make coverage partial.

No package manager is invoked, no dependency is installed and no repository code is executed. Existing scanner exclusions, project ignore patterns and symlink exclusions apply. Other dependency formats are not evaluated.

## Result interpretation

| Status | Meaning |
| --- | --- |
| `clean` | The supported exact versions queried successfully and returned no known advisories. This is not a security guarantee or a check of unsupported dependencies. |
| `findings` | OSV returned known advisory IDs for one or more checked versions. |
| `partial` | Some versions were checked, but unsupported entries, limits, pagination or later failures left gaps. Findings already obtained are retained. |
| `unavailable` | No usable exact versions were found, or no batch completed successfully. This is never reported as a clean scan. |

Findings link to OSV advisory records and identify the manifest/lockfile that supplied the version. Batch responses do not include authoritative severity or remediation ranges, so findings use review priority `medium` and explicitly ask the reviewer to check advisory severity and compatible fixes. Project policy can override that review priority using rule ID `dependency.osv`.

The scanner checks at most 20 dependency files, reads at most 2 MiB per file, and queries at most 500 distinct package versions in batches of 100. Each request is limited to 64 KiB with a five-second network timeout; responses are limited to 1 MiB. Server pagination is reported as partial rather than silently treated as complete. Each package finding lists up to 20 advisory IDs; truncation is disclosed. Network and malformed-response failures retain a coverage explanation without exposing raw server errors.

The [official OSV batch API documentation](https://google.github.io/osv.dev/post-v1-querybatch/) defines ordered per-query results, advisory IDs and per-query pagination tokens. The implementation uses that order to associate each advisory with the correct exact package version.

Tests use bounded fake HTTP responses and temporary manifests; they make no live OSV requests:

```sh
python -m unittest discover -s tests -p 'test_vulnerabilities.py'
```
