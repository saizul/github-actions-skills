# Speed patterns

## Concurrency: cancel superseded PR runs, keep main

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

For deployments use a fixed group (`group: deploy-production`, `cancel-in-progress: false`)
so deploys queue instead of running in parallel.

## Triggers: one run per commit

```yaml
on:
  push:
    branches: [main]
  pull_request:
```

## Path filters and required checks

`paths` / `paths-ignore` skip the whole workflow. A required status check that never
reports blocks the merge. Options:

1. Use path filters only on workflows that are not required checks.
2. Keep the workflow running and decide per job:
   ```yaml
   jobs:
     changes:
       runs-on: ubuntu-latest
       outputs:
         code: ${{ steps.f.outputs.code }}
       steps:
         - uses: actions/checkout@<sha>
         - id: f
           run: |
             base="${{ github.event.pull_request.base.sha || github.event.before }}"
             if git diff --name-only "$base" HEAD | grep -qvE '^(docs/|.*\.md$)'; then
               echo "code=true" >> "$GITHUB_OUTPUT"
             else
               echo "code=false" >> "$GITHUB_OUTPUT"
             fi
     test:
       needs: changes
       if: needs.changes.outputs.code == 'true'
   ```
   (Checkout needs `fetch-depth: 0` or enough history for the diff.) A job skipped by
   `if:` reports success, so required checks pass.

## Matrix trimming

```yaml
strategy:
  fail-fast: true
  matrix:
    os: [ubuntu-latest]
    python: ["3.13"]
    include: ${{ fromJSON(github.event_name == 'pull_request' && '[]' || '[{"os":"windows-latest","python":"3.13"},{"os":"macos-latest","python":"3.13"},{"os":"ubuntu-latest","python":"3.10"}]') }}
```

Simpler alternative: two jobs, `test-pr` (small matrix, `if: github.event_name == 'pull_request'`)
and `test-full` (full matrix on `push` to main and a nightly `schedule`).

Test oldest and newest supported versions on PRs; the middle versions rarely fail alone.

## Parallel jobs and sharding

- Separate `lint`, `typecheck`, `unit`, `build` jobs run in parallel; use `needs:` only for
  real dependencies.
- Shard tests: `matrix: { shard: [1, 2, 3, 4] }` with `pytest --splits 4 --group ${{ matrix.shard }}`
  (pytest-split) or `jest --shard=${{ matrix.shard }}/4`, `playwright test --shard=...`.
- Pass build outputs with `actions/upload-artifact` / `download-artifact` instead of
  rebuilding in each job.

## Checkout

- `fetch-depth: 1` (default) unless you need history. `fetch-depth: 0` on big repos costs minutes.
- `sparse-checkout:` for monorepos when a job needs one folder.

## Runner choice

- Private repositories bill Windows at 2x and macOS at 10x Linux minutes (check
  current GitHub billing docs for your plan; larger runners cost more per minute).
- Larger runners finish faster but cost more per minute; worth it for CPU-bound builds
  that parallelise.
- Public repositories on standard GitHub-hosted runners do not consume minutes, but speed
  still matters for contributors.

## Timeouts

```yaml
jobs:
  test:
    timeout-minutes: 20      # default is 360
    steps:
      - run: npm test
        timeout-minutes: 15  # step level also works
```
