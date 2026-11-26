# Caching

## Prefer the setup action's cache

```yaml
- uses: actions/setup-node@<sha> # v7
  with:
    node-version: 22
    cache: npm            # pnpm | yarn; key = hash of the lockfile
- uses: actions/setup-python@<sha> # v7
  with:
    python-version: "3.13"
    cache: pip            # pipenv | poetry; cache-dependency-path: requirements*.txt
- uses: actions/setup-java@<sha> # v6
  with:
    distribution: temurin
    java-version: 21
    cache: gradle         # maven | sbt
- uses: actions/setup-go@<sha> # v7   (module + build cache on by default)
- uses: ruby/setup-ruby@<sha>
  with:
    bundler-cache: true
```

These cache the package manager's download cache, not `node_modules`. `npm ci` still
runs, but without network downloads.

## actions/cache for everything else

```yaml
- uses: actions/cache@<sha> # v6
  with:
    path: |
      ~/.cache/pre-commit
      .mypy_cache
    key: lint-${{ runner.os }}-${{ hashFiles('.pre-commit-config.yaml', 'pyproject.toml') }}
    restore-keys: |
      lint-${{ runner.os }}-
```

Key design:

- Include `runner.os` (and arch / tool version) - caches are not portable across them.
- Hash the files that determine the content (lockfiles, config). A key that never
  changes never refreshes; a key with `github.sha` never hits.
- `restore-keys` give a partial hit (older cache) so only the delta is downloaded.
- Caches are immutable per key: to update, the key must change.
- Scope: a branch can read caches from its own branch and the default branch, not from
  sibling branches. Warm the cache on `main` (push) so PRs benefit.
- Repository cache storage is limited (10 GB by default) and least-recently-used entries
  are evicted; huge caches evict each other. Check usage with `gh cache list`.
- Split restore and save (`actions/cache/restore`, `actions/cache/save`) to save only on
  `main` or only when the job succeeded.

## Docker builds

```yaml
- uses: docker/setup-buildx-action@<sha>
- uses: docker/build-push-action@<sha> # v7
  with:
    context: .
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

Order the Dockerfile so dependency install layers come before `COPY . .`.

## When caching does not help

- Restoring a 2 GB cache can take longer than a fresh install from a fast registry.
  Compare step timings before and after.
- Caches written by untrusted PR runs can be read by later runs on the same branch only,
  but privileged workflows on `main` should not restore caches that PR code could poison
  (keep cache keys distinct for release jobs).
