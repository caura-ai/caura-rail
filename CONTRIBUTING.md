# Contributing

Use Python 3.10+ and Node.js 22+. From the repository root:

```bash
python -m venv .venv
. .venv/bin/activate                       # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e "packages/python[dev]"
npm ci
```

Run everything CI runs:

```bash
python -m ruff check . && python -m ruff format --check .
python -m mypy --config-file packages/python/pyproject.toml packages/python/src/caura_rail examples contracts
python -m pytest packages/python/tests -q
npm test
python contracts/smoke.py
python contracts/verify_docs.py
```

To verify against a real server, start Caura locally (see the
[guide](docs/guide.md#self-hosted-caura)) and run:

```bash
CAURA_URL=http://localhost:8000 CAURA_API_KEY=standalone python contracts/live.py
```

Build and inspect the distributable artifacts:

```bash
python -m build packages/python
python -m twine check packages/python/dist/*
npm pack --workspace @caura/rail
```

## Changing behavior

- Keep the two packages equivalent. A behavior change lands in both, with tests in
  both suites, using each language's naming and async conventions.
- When request fields or response parsing change, update `contracts/caura.json`,
  `contracts/fixture.py`, and both test suites, then run `contracts/live.py`
  against a real server.
- Documentation is verified: every `python` or `ts` code block in `README.md` and
  `docs/` must run and type-check. Change the docs in the same pull request as
  the behavior.
- Add a line to `CHANGELOG.md` under Unreleased.
- Pull requests explain the user-visible change and its validation. Include
  synthetic reproductions for bugs; never include API keys, customer memories, or
  private logs.

## Releasing

1. Set the same version in `packages/python/pyproject.toml` and
   `packages/typescript/package.json`, move the Unreleased changelog entries under
   that version with the date, and merge to `main`.
2. Tag the merge commit `vX.Y.Z` and push the tag. The release workflow rebuilds,
   re-runs the test suites and the contract check, publishes to PyPI through
   trusted publishing and to npm with provenance, and creates a GitHub release
   with the artifacts attached.
3. Trigger the workflow manually with `dry_run` enabled to rehearse without
   publishing.

Publishing requires a PyPI trusted-publisher entry for this repository's
`release.yml` workflow and an `NPM_TOKEN` repository secret with publish rights
to `@caura/rail`.
