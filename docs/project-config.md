# Project review configuration

Repository configuration is **not trusted by default**, including HTTP, MCP and ordinary CLI reviews. To opt in locally, use `repo-review PATH --trust-repository-config` for the root `.repo-review.json`, or explicitly select a trusted file with `repo-review PATH --config policy.json`. Public HTTP callers cannot enable this trust. A missing trusted default file means the default policy. An explicitly selected missing file, invalid JSON, duplicate keys or unsupported fields cause a clear configuration error.

```json
{
  "ignore": ["generated/**", "**/*.generated.py"],
  "disabled_rules": ["Add an explicit open-source license"],
  "disabled_categories": [],
  "severity_overrides": {
    "dependency.osv": "high",
    "Add a CI workflow": "low"
  }
}
```

The configuration can only change review scope and finding policy. It cannot enable a provider, network access, vulnerability scans, linters, shell commands or repository code execution. Those remain explicit application/CLI options.

## Fields

| Field | Meaning |
| --- | --- |
| `ignore` | Case-sensitive repository-relative globs applied before inventory and content sampling, including vulnerability lockfile discovery. |
| `disabled_rules` | Exact stable `rule_id` values, where supplied, or exact English finding titles. |
| `disabled_categories` | Exact finding categories; AI code findings default to `code`. |
| `severity_overrides` | Map a rule ID or English finding title to `high`, `medium`, `low` or `info`. A rule ID override wins over a title override. |

Matching a directory ignores its descendants. `generated/` and `generated/**` ignore the root generated directory; `**/generated/**` also matches nested directories. `**/*.generated.py` matches root and nested files. Patterns use shell-style wildcards, not Git's ignore format: no negation, absolute paths or parent traversal. Existing built-in exclusions such as `.git`, `node_modules` and test fixture directories still apply.

Policy filters structured deterministic findings and structured AI findings. Findings whose evidence paths are all ignored are removed. Free-form AI narrative is not rewritten by a title/category filter; inspect the structured findings for the policy-adjusted result. Ignored files are outside the review scope, not evidence that an entire repository is safe.

Each array/map permits at most 100 entries; each selector is at most 500 characters. The UTF-8 JSON file is limited to 64 KiB and must be a regular file, not a symlink. No configuration includes are followed. Configuration errors never echo the file contents.

Use stable IDs when present in JSON reports. Existing deterministic rules without an ID use their exact English title as the compatibility selector. Known dependency vulnerability findings use `dependency.osv`, with category `dependency vulnerabilities`.

Reports retain pre-policy findings in `raw_findings`, with the same export redaction as other report fields. `policy_decisions` records affected finding fingerprints, suppression/severity action and source. `metrics.policy_source` and `metrics.policy_config` disclose the selected scope and policy. Ignored files cannot produce raw findings because they were excluded before scanning. Ruff uses its isolated built-in rules and cannot accept target-project auto-fix settings.
