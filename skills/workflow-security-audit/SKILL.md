---
name: workflow-security-audit
description: Audit GitHub Actions workflow YAML with a deterministic script - third-party actions pinned by tag or branch instead of a commit SHA, unpinned docker:// images, missing or write-all `permissions`, `pull_request_target`/`workflow_run` workflows that check out or run PR code (pwn requests), script injection from `${{ github.event.* }}` and `github.head_ref` in `run:` and github-script, secrets in workflow-level `env`, secrets inherit, self-hosted runners on public repos and ACTIONS_ALLOW_UNSECURE_COMMANDS. Reports file:line, job and fix, as text or JSON with CI exit codes, and gives safe rewrites. Use when the user asks to review, harden or "secure" .github/workflows, mentions pull_request_target, script injection, tj-actions style supply-chain attacks, OpenSSF Scorecard token-permissions or pinned-dependencies, or before making a repository public.
license: MIT
compatibility: Python 3.8+ with PyYAML (pip install pyyaml). Offline; reads workflow files only.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Workflow security audit

Find the mechanical security mistakes in GitHub Actions workflows with a script, then fix
them with the patterns below. Read-only: the script never edits files or calls GitHub.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Review / harden / secure our GitHub Actions", "is this workflow safe?"
- A workflow uses `pull_request_target`, `workflow_run` or `issue_comment`
- Interpolating PR titles, branch names or comments into shell (`run:`)
- Before making a private repository public, or after a supply-chain incident
  (a compromised action tag)
- OpenSSF Scorecard reports `Token-Permissions`, `Pinned-Dependencies`, `Dangerous-Workflow`

## When not to use

- Replacing cloud keys with OIDC: `secrets-and-oidc` (this skill only flags secret exposure)
- Converting tags to SHAs and keeping them updated: `dependabot-and-pinning`
- Slow or expensive workflows: `workflow-speed`
- Failing runs: `workflow-debugging`
- Vulnerabilities in the application code itself: use a SAST tool (CodeQL), not this skill

## Workflow

1. **Collect the workflows.** Usually `.github/workflows/*.yml`; also `action.yml` of local
   composite actions. Ask whether the repository is public (changes self-hosted risk).
2. **Run the audit.**
   ```bash
   python3 scripts/audit_workflows.py .                      # repo root or .github/workflows
   python3 scripts/audit_workflows.py .github/workflows --public --json
   python3 scripts/audit_workflows.py ci.yml --strict        # first-party tags count as high too
   python3 scripts/audit_workflows.py . --fail-on high --ignore action.unpinned
   ```
   Exit 1 = findings at or above `--fail-on` (default `medium`), 2 = unreadable YAML or path.
   If PyYAML is missing: `pip install pyyaml`.
3. **Triage by severity.** Meaning and fix for every check id are in
   [references/checks.md](references/checks.md).
   1. `prt.checkout_pr_code` (critical): a fork PR can run code with secrets and a write
      token. Fix first; consider rotating secrets the workflow could read if it ran on
      untrusted PRs in the past.
   2. `injection.run` / `injection.script`: move every untrusted value to `env:` and quote it.
   3. `action.unpinned` (third-party, branch refs), `permissions.write_all`,
      `runner.self_hosted` with `--public`.
   4. `permissions.missing`, `secrets.workflow_env`, `action.docker_unpinned`,
      `checkout.persist_creds` on privileged triggers.
   5. Low/info: first-party tags, `checkout.persist_creds` (token left in `.git/config`), `secrets: inherit`, `inputs.*` in run, `prt.trigger`.
4. **Read the workflow yourself** for what the script cannot know: who can trigger
   `workflow_dispatch`/`issue_comment` commands, whether artifacts from untrusted runs are
   executed later, `GITHUB_ENV` writes built from untrusted text, caches shared with
   privileged workflows, environments without required reviewers.
5. **Propose fixes as a diff** using [references/hardening-patterns.md](references/hardening-patterns.md):
   permissions block, env-indirection for injection, the pull_request + workflow_run split,
   SHA pins with version comments. Do not invent SHAs: resolve them with the
   `dependabot-and-pinning` skill or let the user run `git ls-remote`.
6. **Apply only after the user agrees**, then re-run the audit and show before/after counts.
   Suggest adding the audit (or zizmor/actionlint) as a CI job.

## CI usage

```yaml
- run: pip install pyyaml && python3 path/to/audit_workflows.py . --fail-on high
```

## Output

```
Security audit: 3 workflows - 1 critical, 4 high, 3 medium, 2 low

CRITICAL triage.yml:18 [build] pull_request_target checks out PR head (pwn request)
         -> split: pull_request builds untrusted code; workflow_run comments with the result
HIGH     triage.yml:23 [build] ${{ github.event.pull_request.title }} in run:
         -> env: TITLE: ${{ github.event.pull_request.title }}  run: echo "$TITLE"
HIGH     ci.yml:19 some-org/setup-tool@v2 (mutable tag) -> pin to SHA # v2
MEDIUM   ci.yml no permissions block -> permissions: contents: read

Diff: (proposed changes)   Next: re-run the audit; add it to CI with --fail-on high.
```
