# Matrix reference

## Evaluation order

1. Cartesian product of all list-valued keys (except `include` / `exclude`).
2. `exclude`: remove every combination that matches **all** key/values of an entry
   (partial entries match many combinations).
3. `include`, entry by entry:
   - For each combination, if the entry does not change any **original** matrix value,
     its extra keys are added to that combination (added keys can be overwritten by later
     includes).
   - If it could not be added to any combination, it becomes a new combination.

Values are compared with their YAML type: `20` (number) is not `"20"` (string).
`["3.10"]` must be quoted, otherwise YAML reads `3.10` as `3.1`.

## Patterns

Extra variable for one combination:

```yaml
matrix:
  os: [ubuntu-latest, windows-latest]
  node: [20, 22, 24]
  include:
    - os: ubuntu-latest
      node: 24
      coverage: true
```

Only specific pairs (no product):

```yaml
matrix:
  include:
    - { python: "3.10", django: "4.2" }
    - { python: "3.13", django: "5.2" }
```

Allowed failure:

```yaml
strategy:
  fail-fast: false
  matrix:
    python: ["3.12", "3.13"]
    experimental: [false]
    include:
      - python: "3.14"
        experimental: true
continue-on-error: ${{ matrix.experimental }}
```

Dynamic matrix from a previous job (monorepo packages that changed):

```yaml
jobs:
  plan:
    runs-on: ubuntu-latest
    outputs:
      packages: ${{ steps.p.outputs.packages }}
    steps:
      - uses: actions/checkout@<sha>
      - id: p
        run: echo "packages=$(ls packages | jq -R . | jq -cs .)" >> "$GITHUB_OUTPUT"
  test:
    needs: plan
    if: needs.plan.outputs.packages != '[]'
    strategy:
      matrix:
        package: ${{ fromJSON(needs.plan.outputs.packages) }}
```

An empty array makes the job fail ("Matrix must define at least one vector"), hence the `if:`.

## Limits and options

- At most 256 jobs per matrix per workflow run.
- `fail-fast` (default `true`) cancels the rest when one job fails.
- `max-parallel` limits concurrent jobs of the matrix.
- Job names include matrix values; use `name: test (${{ matrix.os }}, node ${{ matrix.node }})`
  for readable required-check names. Renaming changes the check names that branch
  protection requires.

## Coverage strategy

- Libraries: oldest and newest supported runtime on every PR, the full range nightly.
- Applications: the production runtime only, plus the next version as `experimental`.
- OS: Linux everywhere; macOS/Windows only for code with OS-specific behaviour.
