# Reproducible Python dependencies

`uv.lock` locks the full resolved dependency graph, including optional providers, HTTP/MCP, database tests and tracing. Build metadata pins setuptools. Dependency ranges in `pyproject.toml` remain the library's compatibility declaration; CI and deployment install the lock.

Use the same uv version as CI and both Dockerfiles:

```sh
python -m pip install 'uv==0.10.12'
uv sync --locked --all-extras --python 3.12
uv run --locked python -m unittest discover -s tests
```

CI tests Python 3.10 (the declared floor) and 3.12 (the production interpreter). Frontend/browser and Docker build steps run once on 3.12. PostgreSQL integration tests use locked dependencies in a separate job. Both images install `--no-editable --extra all`; their `/app/.venv/bin` is on PATH for the existing commands. Native OS packages and base image tags are outside the Python lock; this is not a bit-for-bit image reproducibility claim. The PR bot installs the locked core dependencies from its trusted base checkout; head-checkout dependency changes never execute in the review process.

For an intentional dependency update:

```sh
uv lock --upgrade-package PACKAGE
uv sync --locked --all-extras
```

Review the lock diff, run the full suite/coverage, both supported CI interpreters, frontend tests and builds, and the database integration tests. Commit the manifest and lock together when changing dependencies. A stale lock fails `uv sync --locked` instead of silently selecting new versions. Do not replace the lock with a platform-specific `pip freeze`.
