# Publishing To PyPI

This package is intended to be published with PyPI Trusted Publishing from
GitHub Actions. Trusted Publishing avoids storing a long-lived PyPI API token in
GitHub secrets.

## One-Time PyPI Setup

Create or configure the project on PyPI with a Trusted Publisher.

Use these values:

- PyPI project name: `td-ts-compressor`
- Owner: your GitHub user or organization
- Repository name: this repository name
- Workflow name: `publish.yml`
- Environment name: `pypi`

The first release can use a pending publisher if the project does not exist on
PyPI yet.

## Release Flow

1. Update `version` in `pyproject.toml`.
2. Commit the package changes.
3. Create a GitHub release for that version.
4. The `Publish package` workflow builds, tests, checks archive contents, and
   publishes the wheel and source distribution to PyPI.

The workflow can also be run manually with `workflow_dispatch`, but release
publishing should normally happen from a GitHub release.

## Local Preflight

Run these before creating a release:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m build --sdist --wheel
.\.venv\Scripts\python.exe -m twine check dist/*
```

The distribution manifest excludes repository notebooks, generated assets,
local data, SQL scripts, the broader `src/` tree, and broader project
documentation. It includes only the package modules and the bundled
`td_ts_compressor.resources/ts_compress_to.c` operator source needed by the
installation helper.
