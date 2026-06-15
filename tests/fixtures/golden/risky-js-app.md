# Repository Review: risky-js-app

Generated: `<generated-at>`

## Executive Summary

- Primary source languages detected: JavaScript (1).
- Dependency manifests found: package.json.
- No test files were detected.
- CI configuration detected: .github/workflows/ci.yml.
- Framework and tooling signals: CI/CD, Docker, React, Vite.

## Metrics

- Files scanned: `5`
- Files skipped: `0`
- Source files: `1`
- Test files: `0`
- Dependency manifests: `1`
- CI files: `1`
- Languages: `JavaScript: 1`

## Framework Signals

- **CI/CD**: .github/workflows/ci.yml
- **Docker**: Dockerfile
- **React**: package.json: react
- **Vite**: package.json: vite

## Findings

### 1. Expand README with setup and example output

- Severity: `low`
- Category: `documentation`
- Evidence:
  - README.md is missing setup or usage instructions, example output, demo, or screenshots.
- Evidence files:
  - `README.md`
- Recommendation:
  - Add installation steps, run commands, and a small report/demo screenshot so reviewers can understand the project quickly.

### 2. Add an explicit open-source license

- Severity: `medium`
- Category: `project hygiene`
- Evidence:
  - No LICENSE file was detected.
- Evidence files:
  - `LICENSE`
- Recommendation:
  - Add a LICENSE file so users know how they can use and adapt the code.

### 3. Add a .gitignore file

- Severity: `low`
- Category: `project hygiene`
- Evidence:
  - .gitignore was not found.
- Evidence files:
  - `.gitignore`
- Recommendation:
  - Ignore virtual environments, caches, build outputs, local reports, and secrets.

### 4. Add automated tests for the core behavior

- Severity: `medium`
- Category: `testing`
- Evidence:
  - 1 source file(s) found, but no tests were detected.
- Evidence files:
  - `src/index.js`
- Recommendation:
  - Add small tests around the scanner and analyzer so regressions are caught before release.

### 5. Run automated tests in CI

- Severity: `medium`
- Category: `delivery`
- Evidence:
  - CI files were found (.github/workflows/ci.yml), but no common test command was detected.
- Evidence files:
  - `.github/workflows/ci.yml`
- Recommendation:
  - Add language-specific test commands to CI so regressions are caught before merge.

### 6. Build frontend assets in CI

- Severity: `medium`
- Category: `delivery`
- Evidence:
  - A JavaScript frontend package was detected, but CI does not appear to run a frontend build command.
- Evidence files:
  - `.github/workflows/ci.yml`
  - `package.json`
- Recommendation:
  - Run npm run build, pnpm build, or the equivalent frontend build command in CI.

### 7. Restrict GitHub Actions workflow permissions

- Severity: `medium`
- Category: `security`
- Evidence:
  - One or more GitHub Actions workflows grant write-level permissions.
- Evidence files:
  - `.github/workflows/ci.yml`
- Recommendation:
  - Set the narrowest required permissions for each workflow, default to read-only contents access, and grant write access only to jobs that need it.

### 8. Commit a JavaScript package lockfile

- Severity: `medium`
- Category: `dependency hygiene`
- Evidence:
  - package.json was found without package-lock.json, pnpm-lock.yaml, yarn.lock, or bun.lock.
- Evidence files:
  - `package.json`
- Recommendation:
  - Commit the package manager lockfile so dependency resolution is reproducible in CI and deployments.

### 9. Pin broad or floating dependency versions

- Severity: `medium`
- Category: `dependency hygiene`
- Evidence:
  - package.json: dependencies.react uses floating version 'latest'
  - package.json: devDependencies.vite uses floating version '*'
- Evidence files:
  - `package.json`
- Recommendation:
  - Replace latest, wildcard, and unconstrained dependency versions with explicit compatible ranges or pinned versions so builds are reproducible.

### 10. Pin Docker base image versions

- Severity: `medium`
- Category: `dependency hygiene`
- Evidence:
  - Dockerfile: FROM node:latest
- Evidence files:
  - `Dockerfile`
- Recommendation:
  - Use explicit, maintained base image tags instead of latest or untagged images so container builds are reproducible.

### 11. Harden Docker image with a non-root runtime user

- Severity: `low`
- Category: `security`
- Evidence:
  - Dockerfile does not set a non-root USER before runtime.
- Evidence files:
  - `Dockerfile`
- Recommendation:
  - Create and switch to an application user in the final Docker stage to reduce container privilege risk.


## GitHub Issue Backlog

- [LOW] Expand README with setup and example output - Add installation steps, run commands, and a small report/demo screenshot so reviewers can understand the project quickly.
- [MEDIUM] Add an explicit open-source license - Add a LICENSE file so users know how they can use and adapt the code.
- [LOW] Add a .gitignore file - Ignore virtual environments, caches, build outputs, local reports, and secrets.
- [MEDIUM] Add automated tests for the core behavior - Add small tests around the scanner and analyzer so regressions are caught before release.
- [MEDIUM] Run automated tests in CI - Add language-specific test commands to CI so regressions are caught before merge.
- [MEDIUM] Build frontend assets in CI - Run npm run build, pnpm build, or the equivalent frontend build command in CI.
- [MEDIUM] Restrict GitHub Actions workflow permissions - Set the narrowest required permissions for each workflow, default to read-only contents access, and grant write access only to jobs that need it.
- [MEDIUM] Commit a JavaScript package lockfile - Commit the package manager lockfile so dependency resolution is reproducible in CI and deployments.
- [MEDIUM] Pin broad or floating dependency versions - Replace latest, wildcard, and unconstrained dependency versions with explicit compatible ranges or pinned versions so builds are reproducible.
- [MEDIUM] Pin Docker base image versions - Use explicit, maintained base image tags instead of latest or untagged images so container builds are reproducible.
- [LOW] Harden Docker image with a non-root runtime user - Create and switch to an application user in the final Docker stage to reduce container privilege risk.
