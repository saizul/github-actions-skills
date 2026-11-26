# Debugging techniques

## Debug logging

- Re-run with debug logging from the UI or `gh run rerun RUN_ID --failed --debug`.
- Permanent (noisy): repository **variables** or secrets `ACTIONS_STEP_DEBUG=true`
  (step `::debug::` output) and `ACTIONS_RUNNER_DEBUG=true` (runner diagnostics).
- Inside a step: `set -euxo pipefail` for bash tracing (not in steps that handle secrets).

## Diagnostics on failure

```yaml
- name: Diagnostics
  if: failure()
  run: |
    df -h
    free -m || true
    docker ps -a || true
    env | sort | grep -vE 'TOKEN|SECRET|KEY|PASSWORD' || true
- name: Upload test reports
  if: failure()
  uses: actions/upload-artifact@<sha> # v7
  with:
    name: reports-${{ github.job }}-${{ strategy.job-index }}
    path: |
      test-results/
      **/*.log
    retention-days: 5
```

Dump a context safely: `echo '${{ toJSON(github.event) }}'` is an injection risk; use

```yaml
- env:
    EVENT: ${{ toJSON(github.event) }}
  run: echo "$EVENT" | jq '.pull_request.head.ref'
```

Write a summary for humans: `echo "### Failed: $X" >> "$GITHUB_STEP_SUMMARY"`.

## gh CLI loop

```bash
gh run watch                          # follow the latest run
gh run view RUN_ID --json jobs --jq '.jobs[] | select(.conclusion=="failure") | .name'
gh run rerun RUN_ID --failed          # only failed jobs
gh workflow run ci.yml --ref my-branch -f debug=true   # workflow_dispatch with inputs
```

## act (run workflows locally in Docker)

```bash
act -l                                # list jobs
act pull_request -j test              # run one job for an event
act -W .github/workflows/ci.yml push
act --secret-file .secrets --var-file .vars     # never commit these files
act -P ubuntu-latest=catthehacker/ubuntu:act-latest   # fuller image (large)
act --container-architecture linux/amd64        # Apple Silicon
```

Limits: no OIDC tokens, GitHub-hosted image differences, partial support for services and
caches, no macOS/Windows jobs. Good for workflow logic and scripts, not for proving a fix
of runner-specific problems.

Alternative: run the job's commands in a matching container:

```bash
docker run --rm -it -v "$PWD":/src -w /src ubuntu:24.04 bash
```

## Interactive SSH (action-tmate) and alternatives

```yaml
- name: Debug session
  if: ${{ failure() && github.event_name == 'workflow_dispatch' && inputs.debug }}
  uses: mxschmitt/action-tmate@<sha> # v3
  with:
    limit-access-to-actor: true     # only the person who triggered the run (their SSH keys)
    detached: true
  timeout-minutes: 20
```

Rules: only on `workflow_dispatch` by maintainers, only in jobs without deploy secrets or
OIDC, never on `pull_request_target`, always a timeout. Anyone with the session can read
everything the job can.

Alternatives that avoid a live shell:
1. `if: failure()` diagnostics and artifacts (above).
2. Re-run with debug logging.
3. `act` or a matching container locally.
4. A temporary `workflow_dispatch` workflow that runs only the failing command with extra
   output, on a branch.

## Flaky tests

- Run the failing job several times: matrix `attempt: [1, 2, 3, 4, 5]` on a branch.
- Randomise order locally (`pytest -p randomly`, `jest --randomize`) to surface hidden coupling.
- Quarantine with a tracking issue rather than blanket `continue-on-error`.
- Retry only transient network steps (`nick-fields/retry`-style wrappers or a shell loop),
  not whole test suites.
