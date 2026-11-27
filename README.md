# github-actions-skills

[![CI](https://github.com/saizul/github-actions-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/saizul/github-actions-skills/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/saizul/github-actions-skills?sort=semver)](https://github.com/saizul/github-actions-skills/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/saizul/github-actions-skills?style=social)](https://github.com/saizul/github-actions-skills/stargazers)

**Agent Skills that help Claude Code and Codex write fast, secure and reliable GitHub Actions workflows - with tested scripts that read your YAML, logs and run history instead of guessing.**

Eight skills for the work every repository with CI runs into: hardening workflows against
supply-chain and injection attacks, cutting wasted minutes, sharing CI with reusable
workflows, shipping releases with provenance, getting matrices and service containers
right, replacing cloud keys with OIDC, debugging red runs, and keeping actions pinned and
updated. Every skill ships at least one deterministic Python script.

- **Deterministic checks.** Scripts parse workflow files, run logs and `gh` JSON and report
  findings with file, line and job, as text or JSON, with CI-friendly exit codes.
- **Safe by default.** Read-only unless you pass `--write`/`--output`, no network calls,
  never print secret values, never apply cloud trust policies or push tags for you.
- **Tested.** 200+ tests with fixture workflows (pwn-request patterns, injection, OIDC,
  matrices from the GitHub docs, service containers, real-format run logs), run on Python
  3.11-3.13 in CI. This repository audits and pin-checks its own workflows in CI.
- **Current.** Written for late-2026 GitHub Actions: `actions/attest`, Dependabot
  `cooldown` and `directories`, `uv`/`bun` ecosystems, deprecated action runtimes.

## Skills

| Skill | What it does | Try asking |
| --- | --- | --- |
| [workflow-security-audit](skills/workflow-security-audit/SKILL.md) | Lints workflows for tag/branch-pinned actions, missing or write-all `permissions`, `pull_request_target` checking out PR code, `${{ github.event.* }}` script injection, secrets in workflow env, `actions/checkout` without `persist-credentials: false`, self-hosted runners on public repos; gives safe rewrites | "Audit our .github/workflows before we open-source the repo" |
| [workflow-speed](skills/workflow-speed/SKILL.md) | Caching, concurrency cancel, path filters, duplicate push/PR runs, matrix trimming, timeouts; estimates wasted minutes from `gh run list --json` history | "Our CI burns 4,000 minutes a month - where does it go?" |
| [reusable-workflows-composite-actions](skills/reusable-workflows-composite-actions/SKILL.md) | When to use `workflow_call` vs composite actions, templates, and a checker for unknown/missing inputs, secrets, types, `shell`, outputs | "Turn the setup steps copied in 6 workflows into one action" |
| [release-automation](skills/release-automation/SKILL.md) | Tag-driven releases, changelog from Conventional Commits, `gh release create`, release-please, `actions/attest` provenance and `gh attestation verify` | "Automate releases and tell me the next version" |
| [matrix-and-services](skills/matrix-and-services/SKILL.md) | Exact matrix include/exclude expansion and job counts; Postgres/MySQL/Redis/MongoDB service containers with health checks and correct hosts | "Why does my matrix create 9 jobs? Add Postgres to the tests" |
| [secrets-and-oidc](skills/secrets-and-oidc/SKILL.md) | Finds AWS keys, GCP key JSON, Azure secrets; checks `id-token: write`; prints least-privilege trust policies for AWS, GCP and Azure | "Replace our AWS access keys with OIDC" |
| [workflow-debugging](skills/workflow-debugging/SKILL.md) | Parses `gh run view --log` output or the log archive: first error, failing step, 30 error signatures with fixes; debug logging, act, safe tmate | "Why did this run fail? Here is the log" |
| [dependabot-and-pinning](skills/dependabot-and-pinning/SKILL.md) | Converts action tags to SHA pins offline from a mapping file, builds the mapping with `git ls-remote`, generates or checks `dependabot.yml` for all ecosystems | "Pin every action to a SHA and keep them updated" |

## Install

### Claude Code: plugin marketplace (recommended)

```text
/plugin marketplace add saizul/github-actions-skills
/plugin install github-actions-skills@github-actions-skills
```

Or from your shell:

```bash
claude plugin marketplace add saizul/github-actions-skills
claude plugin install github-actions-skills@github-actions-skills
```

Plugin skills are namespaced, e.g. `/github-actions-skills:workflow-security-audit`.
Claude also picks them up automatically when your request matches a skill's description.
Update later with `/plugin marketplace update github-actions-skills`.

### Claude Code: copy the skills

```bash
git clone https://github.com/saizul/github-actions-skills.git
# all projects (personal skills)
mkdir -p ~/.claude/skills && cp -r github-actions-skills/skills/* ~/.claude/skills/
# or just one project
mkdir -p .claude/skills && cp -r github-actions-skills/skills/workflow-security-audit .claude/skills/
```

Each release also has one zip per skill and an all-skills zip under
[Releases](https://github.com/saizul/github-actions-skills/releases).

### Codex CLI

Codex reads skills from `~/.agents/skills` (all repositories) and `.agents/skills` in a
repository (from the current directory up to the repository root):

```bash
git clone https://github.com/saizul/github-actions-skills.git
mkdir -p ~/.agents/skills && cp -r github-actions-skills/skills/* ~/.agents/skills/
# or per repository
mkdir -p .agents/skills && cp -r github-actions-skills/skills/workflow-security-audit .agents/skills/
```

Codex also ships a `$skill-installer` skill that can install skills from a GitHub
repository; ask it to install from `saizul/github-actions-skills`. Skill locations and the
installer are described in the [Codex skills documentation](https://developers.openai.com/codex/skills);
check it if your Codex version behaves differently. [AGENTS.md](AGENTS.md) explains how
Codex and other agents should use these skills.

### Any other agent

The skills follow the open [Agent Skills format](https://agentskills.io/specification):
a folder with `SKILL.md` (YAML frontmatter + instructions), `scripts/`, `references/` and
`assets/`. Point your agent at the folder, or run the scripts yourself; every script has `--help`.

### Requirements

Python 3.8+. Scripts that parse workflow YAML need PyYAML (`pip install pyyaml`); the
release, debugging, trust-policy and pinning scripts use only the standard library. The
GitHub CLI (`gh`) is used for commands **you** run to fetch logs and run history.

## Usage examples

```text
> Audit .github/workflows - we are making this repo public next week.
  (Runs audit_workflows.py --public: a pull_request_target job checks out the PR head,
   two run: steps interpolate the PR title, three third-party actions are pinned by tag.
   Proposes the pull_request + workflow_run split, env indirection and SHA pins as a diff.)

> CI takes 20 minutes and we keep hitting the minutes limit.
  (Asks you for `gh run list --json ...`; estimate_waste.py shows 44% waste from superseded
   and duplicate push/PR runs; adds concurrency, push: branches [main], pip/npm caching and
   a trimmed PR matrix.)

> Deploy to AWS without the access keys in secrets.
  (oidc_check.py lists the key usages; trust_policy.py prints a role trust policy for
   repo:acme/web:environment:production; the workflow diff adds id-token: write on the
   deploy job only; you delete the keys after a green run.)
```

Run the scripts directly too:

```bash
python3 skills/workflow-security-audit/scripts/audit_workflows.py . --fail-on high
python3 skills/workflow-speed/scripts/estimate_waste.py --workflow .github/workflows/ci.yml --runs runs.json
python3 skills/reusable-workflows-composite-actions/scripts/check_reusable.py .
git log --format='%h%x1f%s%x1f%b%x1e' v1.4.2..HEAD | \
  python3 skills/release-automation/scripts/next_version.py --current v1.4.2 --repo OWNER/REPO
python3 skills/matrix-and-services/scripts/expand_matrix.py .github/workflows/ci.yml
python3 skills/secrets-and-oidc/scripts/oidc_check.py .
python3 skills/secrets-and-oidc/scripts/trust_policy.py aws --repo OWNER/REPO --environment production --account 123456789012
gh run view RUN_ID --log-failed > run.log && python3 skills/workflow-debugging/scripts/parse_run_log.py run.log
python3 skills/dependabot-and-pinning/scripts/pin_actions.py . --map pins.txt --diff
python3 skills/dependabot-and-pinning/scripts/dependabot_gen.py . --check .github/dependabot.yml
```

## How skills work

At startup the agent loads only each skill's `name` and `description` (about 100 tokens
each). When your request matches a description, it reads that skill's `SKILL.md`: the
workflow, decision points and safety rules. Longer material lives in `references/` and is
read only when a step needs it; `assets/` holds templates to copy (release workflow,
reusable workflow, composite action). Scripts run as normal commands, so their output is
exact and repeatable.

```
skills/<skill-name>/
  SKILL.md          frontmatter (name, description) + workflow
  scripts/          standalone Python 3 helpers (--help, --json, exit codes)
  references/       check tables, patterns, setup guides
  assets/           templates to copy into .github/
```

## FAQ

**Do the scripts call GitHub or my cloud account?**
No. They read local files only. Commands that need the network (`gh run list`,
`git ls-remote`, `aws iam create-role`) are printed for you to review and run.

**Why do I have to provide SHAs for pinning?**
Because a pin is only as good as the SHA behind it. `pin_actions.py --resolve-script`
writes a `git ls-remote` script you can read and run; the agent never makes SHAs up.

**Is this a replacement for actionlint or zizmor?**
No, it complements them. actionlint checks syntax and expression types; zizmor does deep
static analysis. These skills add the workflow around the findings (what to fix first, the
safe rewrite, OIDC setup, verifying the fix) and cover speed, releases and debugging too.

**Which GitHub plans?**
Everything works on github.com. Artifact attestations need a public repository or GitHub
Enterprise Cloud; OIDC works on all plans. GitHub Enterprise Server users should check
feature availability for their version.

**Can I use the checks in CI?**
Yes: every checker exits 1 on findings (configurable with `--fail-on` or `--strict`) and
supports `--json`. This repository runs its own security audit and pin check in CI.

## Roadmap

Ideas for new skills (great first contributions; see [CONTRIBUTING.md](CONTRIBUTING.md)):

- `self-hosted-runners` - ephemeral runners, actions-runner-controller, runner groups, hardening
- `container-image-pipelines` - buildx caching, multi-arch builds, GHCR, SBOM and image attestations
- `monorepo-ci` - change detection, per-package workflows, required checks that tolerate skips
- `deployment-environments` - environments, required reviewers, deployment protection rules, rollbacks
- `actions-cost-report` - per-workflow and per-runner cost from the billing usage export
- `custom-javascript-actions` - scaffold, test, bundle and release a JS/TS action
- `workflow-migration` - convert Travis CI, CircleCI or GitLab CI configs to GitHub Actions
- `branch-protection-rulesets` - rulesets for required checks, tag protection and merge queues

## Contributing

Contributions are welcome: new checks, new skills, fixture workflows and logs from real
projects (redacted), fixes and better docs. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the
skill template, the quality bar and how to run the validator and tests:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python tools/validate_skills.py && ruff check . && ruff format --check . && pytest
```

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) and report security issues
privately as described in [SECURITY.md](SECURITY.md).

GitHub and GitHub Actions are trademarks of GitHub, Inc. This project is independent and
not affiliated with GitHub.

## License

[MIT](LICENSE) (c) Saizul Amin
