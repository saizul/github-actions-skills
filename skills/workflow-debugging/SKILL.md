---
name: workflow-debugging
description: Debug failing or flaky GitHub Actions runs systematically - get the right log with gh run view --log-failed or the log archive, find the first real error instead of the last line, enable step and runner debug logging, reproduce locally with act or a matching container, and use interactive debugging (action-tmate) safely or its alternatives. A script parses downloaded run logs (gh output, zip archive or folder) and maps 30 common error signatures to fixes - "Resource not accessible by integration", missing id-token permission, AssumeRoleWithWebIdentity, out of memory (exit 137), disk full, timeouts, lockfile drift, ModuleNotFoundError, rate limits, git auth, unhealthy services, empty matrix, test failures, deprecated Node runtimes. Use when a workflow run fails, hangs, is cancelled or flaky, the user pastes an Actions log or run URL, or asks why CI is red or how to debug Actions locally.
license: MIT
compatibility: Python 3.8+ standard library for the script. gh (GitHub CLI) and optionally act/Docker for the commands the user runs.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Workflow debugging

Find the first real error, classify it, fix the cause, and prove the fix - without
guessing from the last red line. Read-only analysis of logs; re-runs and debug settings
are suggested to the user.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "CI is red", "this job fails only on GitHub", a pasted log or run URL
- Hanging jobs, timeouts, cancelled runs, flaky tests
- "How do I run my workflow locally?", "can I SSH into the runner?"

## When not to use

- The workflow file is rejected before running (`Invalid workflow file`): read the
  annotation on the run page; check syntax with actionlint
- Slow but green runs: `workflow-speed`
- Service container setup: `matrix-and-services`; OIDC/cloud login design: `secrets-and-oidc`

## Workflow

1. **Get the log** (the user runs these; `gh auth login` first):
   ```bash
   gh run list --workflow ci.yml --limit 5              # find the run id
   gh run view RUN_ID --log-failed > run.log             # failed steps only
   gh run view RUN_ID --log > full.log                   # everything
   gh run download RUN_ID -D artifacts/                  # uploaded artifacts (test reports)
   ```
   Or download the log archive from the run page (gear menu > Download log archive).
2. **Parse it.**
   ```bash
   python3 scripts/parse_run_log.py run.log
   python3 scripts/parse_run_log.py logs_123.zip --json
   python3 scripts/parse_run_log.py logs_123/ --context 10 --all
   ```
   Exit 1 = error signatures or `##[error]` lines found. The **first error** is usually
   the cause; later errors are often consequences.
3. **Classify and fix.** Each signature has a hint; the full table with causes and fixes
   is in [references/error-signatures.md](references/error-signatures.md). Decide:
   - **Config** (permissions, inputs, missing secret in this environment, wrong action ref):
     fix the YAML.
   - **Environment drift** (runner image update, new tool version, lockfile drift): pin
     versions (`ubuntu-24.04` not `ubuntu-latest`, `node-version-file`), commit lockfiles.
   - **Resources** (exit 137, ENOSPC, timeout): reduce parallelism, free disk, larger runner.
   - **Flaky / transient** (network, rate limit): retry with backoff, cache, authenticate.
   - **Real test failure**: reproduce locally with the same versions.
4. **Need more detail?** Re-run with debug logging (run page > Re-run jobs > Enable debug
   logging, or `gh run rerun RUN_ID --failed --debug`), or set repository variables
   `ACTIONS_STEP_DEBUG=true` / `ACTIONS_RUNNER_DEBUG=true`. Add a diagnostics step with
   `if: failure()` (env, disk, versions, service logs). See
   [references/debugging-techniques.md](references/debugging-techniques.md).
5. **Reproduce locally** when the loop is slow: `act` for workflow logic, or the job's
   commands in a container matching the runner. Know act's limits (no OIDC, partial
   services/caches). Interactive SSH (`action-tmate`) only with `limit-access-to-actor`
   and never in workflows that hold deploy secrets or run on untrusted PRs.
6. **Fix and verify:** propose the diff, then `gh run rerun RUN_ID --failed` or push, and
   parse the new log if it fails again. For flaky tests, run the job several times
   (matrix `attempt: [1, 2, 3]`) before calling it fixed.

## Output

```
Run 1234567890 (ci.yml, push to main) failed in test / Run npm ci

First error:
  npm error `npm ci` can only install packages when your package.json and
  package-lock.json ... are in sync.  Missing: left-pad@1.3.0 from lock file
Diagnosis: lockfile (error) - package.json changed without updating package-lock.json
Also: label job - Resource not accessible by integration -> add pull-requests: write

Fix:
1. npm install && commit package-lock.json
2. jobs.label.permissions: {pull-requests: write}
Verify: gh run rerun 1234567890 --failed
```
