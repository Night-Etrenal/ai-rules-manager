# Upstream maintenance policy

AI Rules Manager is an independent Debian-first Codex control layer derived from ideas and selected mechanisms in `OthmanAdi/planning-with-files`. It is not maintained as a line-for-line mirror.

## Branch roles

- `master`: released AI Rules Manager product after review.
- `agent/*`: isolated product changes and Draft pull requests.
- `upstream/planning-with-files`: immutable reviewed snapshot of the original upstream tree.
- `upstream-review/*`: temporary local review branches created from a newly fetched upstream commit.

## Review workflow

Run from a clean local checkout:

```bash
sh scripts/review-upstream.sh
```

The command:

1. fetches the public upstream repository without tags;
2. verifies that its history is a fast-forward of the stored snapshot;
3. creates a local `upstream-review/<timestamp>` branch at the candidate commit;
4. lists changed paths and highlights workflows, hooks, dependencies, scripts and source code;
5. does not execute upstream code;
6. does not merge into the product branch;
7. does not commit, push or change the stored snapshot.

## Accepting an upstream release

1. Review upstream provenance, commits, licenses, workflows, hooks, scripts and dependency lifecycle changes.
2. Test upstream only in a disposable isolated environment without credentials.
3. Selectively reimplement or port relevant behavior into a new `agent/*` product branch.
4. Add product-native tests and documentation. Do not restore unsupported multi-platform files merely to reduce the diff.
5. After accepting the upstream history, update `upstream/planning-with-files` explicitly and separately.
6. Open a Draft product PR and require all Debian and security checks.

A direct merge from `upstream/planning-with-files` into the independent product branch is prohibited because it can silently overwrite the rewritten architecture, security model, file layout and support scope.
