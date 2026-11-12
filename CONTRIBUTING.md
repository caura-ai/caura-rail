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
python -m mypy --config-file packages/python/pyproject.toml packages/python/src/caura_rail examples/fleet.py contracts
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

## Pull requests

`main` is protected: changes arrive by pull request, need the `CI` and `DCO`
checks green and one maintainer review, and merge with a linear history.
Sign off every commit under the [Developer Certificate of Origin](https://developercertificate.org/):

```bash
git commit -s -m "fix: ..."          # adds Signed-off-by: Your Name <you@example.com>
git config --global format.signoff true   # or make it the default
```

Dependabot opens weekly update PRs for pip, npm, and GitHub Actions; CodeQL
scans every push and PR.

A member of the `caura-ai` organization can ask for an AI code review by
commenting `@claude` on a pull request, typically once CI is green and again
after each push. The review is advisory, covers only the commit it read, and
is posted as a comment; it runs main's copy of
`.github/workflows/claude_code_review.yml`, never the pull request's.

## Changing behavior

- Keep the two packages equivalent. A behavior change lands in both, with tests in
  both suites, using each language's naming and async conventions.
- When request fields or response parsing change, update `contracts/caura.json`,
  `contracts/fixture.py`, and both test suites, then run `contracts/live.py`
  against a real server.
- Documentation is verified: every `python` or `ts` code block in `README.md` and
  `docs/` must run and type-check. Change the docs in the same pull request as
  the behavior.
- Write the commit subject (and the pull request title) as a
  [Conventional Commit](https://www.conventionalcommits.org/): `feat:` for new
  behavior, `fix:` for a bug fix, `docs:`, `ci:`, `chore:` and so on. release-please
  builds the changelog from these and picks the next version from them: a `!` or
  `BREAKING CHANGE:` footer makes a major release, `feat` a minor one, and `fix`,
  `perf`, `deps`, `docs`, `refactor` or `revert` a patch. `ci`, `chore`, `test` and
  `build` commits stay out of the changelog and release nothing on their own. Do
  not edit `CHANGELOG.md` by hand.
- Pull requests explain the user-visible change and its validation. Include
  synthetic reproductions for bugs; never include API keys, customer memories, or
  private logs.

## Releasing

1. release-please (`.github/workflows/release-please.yml`) keeps one release pull
   request open, `chore(main): release X.Y.Z`, whenever user-visible commits have
   landed on `main`. It bumps the version in `packages/python/pyproject.toml`,
   `packages/typescript/package.json`, `package-lock.json` and
   `packages/typescript/src/version.ts` together, and adds the changelog section.
   Edit the changelog wording in that pull request if needed.
2. Merging it tags `vX.Y.Z` and publishes the GitHub release. That starts the
   release workflow, which rebuilds, re-runs the test suites and the contract
   check, publishes to PyPI and to npm with provenance, and attaches the artifacts
   to the release.
3. Run the release workflow by hand with `dry_run` enabled to rehearse without
   publishing, or on an existing tag with `dry_run` off to re-publish.

release-please authenticates as the caura-release GitHub App, whose key lives
only in the `release-please` environment (deployable from `main` alone): a
release pull request opened with the default token would run no checks, and a
release it published would not start the release workflow.

Publishing uses no stored PyPI credential. PyPI's trusted publisher entry on
`caura-rail` names this repository, `release.yml` and the `release` environment,
and the workflow exchanges its OIDC token for a short-lived upload token at
publish time. npm needs either the `NPM_TOKEN` secret (an npm token with publish
rights to the `@caura` scope) or a trusted publisher entry on `@caura/rail` at
npmjs.com naming the same repository, workflow and environment. The workflow
skips the npm step when the tagged version is already on npm, and the PyPI step
skips files that already exist, so re-running a release is safe.
