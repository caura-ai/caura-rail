## Summary

<!-- What changes for a user of caura-rail or @caura/rail, in one or two sentences. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation
- [ ] Internal / tooling

## Checklist

- [ ] Both packages changed together where behaviour is shared, with tests in both suites.
- [ ] Request or response shape changes update `contracts/caura.json`, `contracts/fixture.py`, and were run against a live server with `contracts/live.py`.
- [ ] Documentation updated in the same PR; `python contracts/verify_docs.py` passes.
- [ ] The title is a [Conventional Commit](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `ci:` ...): release-please writes the changelog from it and picks the next version (see CONTRIBUTING.md, Changing behavior).
- [ ] Every commit is signed off (`git commit -s`).

## How was this tested?

<!-- Commands run and their outcome. Never paste API keys, customer memories, or private logs. -->
