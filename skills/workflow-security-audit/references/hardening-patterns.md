# Hardening patterns

## Least-privilege token

```yaml
permissions:
  contents: read          # default for every job

jobs:
  release:
    permissions:
      contents: write     # only this job can create releases
    steps: ...
```

Common scopes: `contents`, `pull-requests`, `issues`, `packages`, `id-token` (OIDC),
`attestations`, `checks`, `statuses`, `deployments`, `actions`, `security-events`.
`permissions: {}` removes all scopes (fine for jobs that only run tests on public code).

Also set the repository default to read-only: Settings > Actions > General > Workflow
permissions > "Read repository contents and packages permissions".

## Script injection: env indirection

```yaml
# Vulnerable
- run: echo "Checking ${{ github.event.pull_request.title }}"

# Safe: the value reaches the shell as data, not code
- env:
    PR_TITLE: ${{ github.event.pull_request.title }}
  run: echo "Checking $PR_TITLE"     # always quote: "$PR_TITLE"
```

github-script:

```yaml
- uses: actions/github-script@<sha> # v9
  with:
    script: |
      const title = context.payload.pull_request.title;   // no ${{ }} in code
```

## pull_request_target done safely

Option A - never check out the PR (labelers, triage, size checks): use the API only.

Option B - split privileged and unprivileged work:

```yaml
# .github/workflows/pr-build.yml - untrusted, no secrets
on: pull_request
permissions: { contents: read }
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha> # v7
        with: { persist-credentials: false }
      - run: make test > results.txt
      - uses: actions/upload-artifact@<sha> # v7
        with: { name: results, path: results.txt }
```

```yaml
# .github/workflows/pr-comment.yml - privileged, never runs PR code
on:
  workflow_run:
    workflows: ["pr-build"]
    types: [completed]
permissions:
  pull-requests: write
  actions: read
jobs:
  comment:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@<sha> # v8
        with:
          name: results
          run-id: ${{ github.event.workflow_run.id }}
          github-token: ${{ github.token }}
      # Treat results.txt as untrusted DATA: no eval, no sourcing, size-limit it.
```

If a maintainer must approve before privileged jobs run on a PR, use an environment with
required reviewers on the privileged job; labels alone can be added by bots or triagers.

## Checkout credentials

`actions/checkout` stores the token in `.git/config` by default. If later steps run
third-party code or upload the workspace as an artifact, set `persist-credentials: false`.

## Pinning

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
```

Keep the version comment: Dependabot updates both the SHA and the comment.

## Self-hosted runners

- Never attach persistent self-hosted runners to public repositories.
- Prefer ephemeral runners (`--ephemeral`, JIT config, actions-runner-controller) so each
  job starts clean.
- Restrict runner groups to selected repositories and workflows.

## Secrets

- Step-level `env`, never workflow-level, for secrets.
- Use environments with required reviewers and branch rules for deploy secrets.
- Do not `echo` secrets or write them to files that get uploaded; masking only hides exact
  matches in logs (a base64'd secret is not masked).
