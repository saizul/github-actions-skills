# Reuse patterns

## Reusable workflow vs composite action

| | Reusable workflow | Composite action |
| --- | --- | --- |
| Unit of reuse | Jobs | Steps |
| Defined in | `.github/workflows/*.yml` with `on: workflow_call` | `action.yml` anywhere (often `.github/actions/<name>/`) |
| Called with | `jobs.<id>.uses:` (no `runs-on`, `steps`) | `steps[*].uses:` |
| Runner | Chooses its own `runs-on` | Runs in the caller's job |
| Secrets | `secrets:` declared and passed (or `inherit`) | No `secrets` context; pass as inputs |
| Env | Caller's `env` is **not** passed | Shares job env and workspace |
| Outputs | `on.workflow_call.outputs.*.value: ${{ jobs.X.outputs.Y }}` | `outputs.*.value: ${{ steps.X.outputs.Y }}` |
| Matrix / environments / `needs` | Yes | No (uses the caller's) |
| UI and logs | Separate jobs, each step visible | Collapsed into one step in the caller |
| Good for | Whole pipelines shared across repos (build, test, deploy with approvals) | Setup steps, toolchains, "install + cache" |

## Calling with a matrix

```yaml
jobs:
  test:
    strategy:
      matrix:
        node: ["20", "22", "24"]
    uses: ./.github/workflows/_build-test.yml
    with:
      node-version: ${{ matrix.node }}
```

## Passing outputs back

```yaml
# called workflow
on:
  workflow_call:
    outputs:
      image:
        value: ${{ jobs.build.outputs.image }}
jobs:
  build:
    outputs:
      image: ${{ steps.meta.outputs.image }}
    steps:
      - id: meta
        run: echo "image=ghcr.io/org/app:${GITHUB_SHA::7}" >> "$GITHUB_OUTPUT"

# caller
jobs:
  build:
    uses: ./.github/workflows/_build.yml
  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - run: echo "deploying $IMAGE"
        env:
          IMAGE: ${{ needs.build.outputs.image }}
```

## Permissions

The called workflow gets the caller's `GITHUB_TOKEN` permissions and can only reduce them.
If the called workflow needs `id-token: write` (OIDC) or `packages: write`, the **caller
job** must grant it:

```yaml
jobs:
  deploy:
    permissions:
      contents: read
      id-token: write
    uses: org/ci/.github/workflows/deploy.yml@<sha> # v2.1.0
```

## Composite action tips

- Every `run` step needs `shell:` (`bash`, `pwsh`, `python`, ...).
- Reference files in the action folder with `${{ github.action_path }}`:
  `run: ${{ github.action_path }}/scripts/setup.sh` (set `shell: bash`).
- `if:` on steps, `continue-on-error`, `working-directory`, `env` and nested `uses:` work.
- Pass inputs to scripts via `env:`, not by interpolating `${{ inputs.x }}` into the
  script (avoids injection from callers).
- Local composite actions need `actions/checkout` first; actions from another repository
  (`org/actions/setup@<sha>`) do not.

## Versioning shared workflows

- Keep shared workflows in one repository (`org/.github` or `org/ci`), tag releases
  (`v1.4.0`) and move a major tag (`v1`) only if consumers accept tag pinning; otherwise
  consumers pin SHAs and Dependabot (`github-actions` ecosystem) updates them.
- Write a CHANGELOG for inputs added/removed; removing an input breaks every caller.

## Limits and gotchas

- Nesting depth of reusable workflows is limited (several levels, and a total number of
  unique reusable workflows per run); check the current limits in the GitHub docs
  ("Reusing workflows" > Limitations) before designing deep chains.
- `env` set at the caller's workflow level is not visible in the called workflow; pass inputs.
- The `strategy`, `needs`, `if`, `permissions`, `concurrency`, `with`, `secrets` keys are
  allowed on a calling job; `runs-on`, `steps`, `container`, `services`, `env` (job-level),
  `timeout-minutes` are not.
- Inputs are typed: a boolean input given `"false"` (a string) fails. Use
  `run-e2e: false` or an expression.
- The `github` context in the called workflow is the caller's (event, ref, sha). To trust
  the shared workflow itself in a cloud OIDC policy, match the `job_workflow_ref` claim of
  the OIDC token (see `secrets-and-oidc`).
