# Contributing

Use Python 3.10+ and Node.js 22+. From the repository root:

    python -m venv .venv
    . .venv/bin/activate
    python -m pip install -e "packages/python[dev]"
    npm ci
    python -m pytest packages/python/tests
    python -m ruff check packages/python
    python -m ruff format --check packages/python
    npm test
    python contracts/smoke.py

On Windows, activate the environment using .venv\Scripts\Activate.ps1.
Contract tests use local fixtures and require no service credentials.

Build distributable artifacts:

    python -m build packages/python
    python -m twine check packages/python/dist/*
    npm pack --workspace @caura/rail

Before submitting, test the built artifacts from outside the source tree.
When changing request fields or response parsing, update the shared fixture and
both client test suites. Preserve the same behavior while using each language's
normal naming and async conventions.

Pull requests should explain the user-visible change and its validation.
Include synthetic reproductions for bugs; do not include API keys, customer
memories, private logs, or internal planning material.
