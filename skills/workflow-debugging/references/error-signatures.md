# Error signatures

| Signature id | Log text (examples) | Usual cause | Fix |
| --- | --- | --- | --- |
| `permissions` | `Resource not accessible by integration` | `GITHUB_TOKEN` scope missing; fork PR token is read-only | Add the scope to the job's `permissions`; for fork PR comments use a `workflow_run` follow-up workflow |
| `oidc.no_id_token` | `Unable to get ACTIONS_ID_TOKEN_REQUEST_URL env variable`, `Could not load credentials from any providers` | No `id-token: write`; fork PR | Grant `id-token: write` on the job; forks cannot use OIDC |
| `oidc.aws_trust` | `Not authorized to perform sts:AssumeRoleWithWebIdentity` | Trust policy `sub`/`aud` mismatch | Match `repo:OWNER/REPO:environment:NAME` when the job uses an environment |
| `oidc.azure_trust` | `AADSTS70021` | Federated credential subject mismatch | Create a credential for this exact subject |
| `oom` | `JavaScript heap out of memory`, `exit code 137`, `Killed` | Memory exhausted | Fewer workers (`--maxWorkers=2`, `-n 2`), `NODE_OPTIONS=--max-old-space-size=4096`, larger runner |
| `disk_full` | `No space left on device`, `ENOSPC` | ~14 GB free on hosted Linux runners | Remove unused SDKs, `docker system prune -af`, build in `/mnt` |
| `timeout` | `has exceeded the maximum execution time` | Hanging step (prompt, deadlock, waiting for a service) | Find the last output line; add `timeout-minutes` per step |
| `cancelled` | `The operation was canceled` | Concurrency cancel, user, fail-fast | Usually not the root cause; look at the job that failed first |
| `runner_lost` | `lost communication with the server` | Runner crashed (OOM, disk), self-hosted restart | Re-run; check memory/disk use |
| `action_resolve` | `Unable to resolve action`, `Can't find 'action.yml'` | Typo, deleted tag, private action, local action before checkout | Fix the ref; checkout first; allow access to private action repos |
| `input_required` | `Input required and not supplied: token` | Secret empty (forks, other environment), input missing | Provide the input; guard with `if: secrets...` via env check |
| `bad_credentials` | `Bad credentials`, `401` | Expired/empty token | Re-create the secret; confirm it is set for this environment |
| `rate_limit` | `API rate limit exceeded`, `toomanyrequests` | Unauthenticated API or Docker Hub pulls | Pass `GITHUB_TOKEN`; `docker/login-action` before pulls; mirror images to GHCR |
| `git_auth` | `could not read Username`, `Permission denied (publickey)` | Private submodules/dependencies | Token or deploy key with access; `submodules: recursive` + `token:` on checkout |
| `protected_branch` | `GH006: Protected branch update failed` | Pushing to a protected branch from CI | Open a PR or use a GitHub App allowed by the ruleset |
| `network` | `ETIMEDOUT`, `ECONNRESET`, `Could not resolve host` | Transient or firewall | Retry with backoff; check proxy on self-hosted |
| `lockfile` | npm ci "can only install packages when ... in sync", `ERR_PNPM_OUTDATED_LOCKFILE`, `frozen-lockfile` | Manifest changed without lockfile | Regenerate and commit the lockfile |
| `python_module` | `ModuleNotFoundError: No module named 'x'` | Not installed, wrong interpreter, missing extra | Install requirements; use `python -m pip`; check `setup-python` version |
| `pip_resolve` | `Could not find a version that satisfies the requirement` | Version not available for this Python/platform | Adjust pins or Python version |
| `npm_error` | `npm error code E404 / ERESOLVE` | Private package without auth / peer conflict | `registry-url` + `NODE_AUTH_TOKEN`; fix peer versions |
| `command_not_found` | `command not found` | Tool missing, wrong shell on Windows | Install it; `shell: bash` |
| `exec_format` | `exec format error` | Wrong CPU architecture | Match arm64/x64 binaries to the runner |
| `shell_syntax` | `syntax error near unexpected token` | Quoting; interpolated value with quotes | Use env variables instead of `${{ }}` in scripts |
| `permission_denied` | `Permission denied`, `EACCES` | Script not executable | `git update-index --chmod=+x script.sh` |
| `service_unhealthy` | `unhealthy`, `Failed to initialize container` | Service misconfigured | Fixed tag, required env, `--health-cmd` |
| `matrix_empty` | `Matrix must define at least one vector` | Dynamic matrix returned `[]` | `if: needs.plan.outputs.list != '[]'` |
| `artifact_missing` | `Unable to download artifact` | Name mismatch, expired, upload skipped | Check names and `run-id`; retention |
| `tests_failed` | `FAILED tests/...`, `3 failed`, `--- FAIL:` | Test failure | Reproduce locally with the same versions and env |
| `deprecated_runtime` | `Node.js 20 actions are deprecated`, `set-output command is deprecated` | Old action versions | Update actions; use `$GITHUB_OUTPUT` |
| `cache_miss` | `Cache not found for input keys` | Cold cache or key changes every run | See `workflow-speed` caching reference |

## "Works locally, fails in CI"

1. Versions: runtime, OS image (`ubuntu-latest` moves), tool versions. Print them in CI.
2. Environment: CI has no `.env`, no global config, different locale/timezone (UTC), no TTY.
3. Case-sensitive filesystem on Linux (`import ./Utils` vs `utils.ts`).
4. Clean checkout: generated files or untracked files present locally only.
5. Parallelism and resource limits (2-4 vCPU, limited memory) expose race conditions.
6. Network: services are `localhost` only when the job is not in a container.
