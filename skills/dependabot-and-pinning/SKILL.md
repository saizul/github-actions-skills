---
name: dependabot-and-pinning
description: Pin GitHub Actions to full commit SHAs with version comments and keep them (and every other dependency) updated with Dependabot. Scripts convert tag references such as owner/repo@v4 into full commit-SHA pins with a version comment, offline from a mapping file you provide (dry run, --diff, --write, plus a git ls-remote script to build the mapping), and detect ecosystems in a repository (github-actions, npm, bun, pip, uv, gomod, cargo, bundler, composer, maven, gradle, nuget, docker, docker-compose, terraform and more) to generate a grouped .github/dependabot.yml or check an existing one for missing ecosystems. Use when the user asks to pin actions to SHAs, fix OpenSSF Scorecard Pinned-Dependencies, set up or review dependabot.yml, reduce Dependabot PR noise with groups or cooldown, or auto-merge Dependabot updates safely.
license: MIT
compatibility: Python 3.8+ standard library only. Resolving SHAs needs git and network access, run by the user; the scripts themselves are offline.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Dependabot and pinning

Pin what you run, then let Dependabot move the pins. SHA pins without updates rot; tag
pins with updates can be hijacked. Do both. Scripts never touch the network and default
to a dry run.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Pin our actions to SHAs", Scorecard `Pinned-Dependencies`, a supply-chain review
- Creating or reviewing `.github/dependabot.yml`; too many Dependabot PRs
- Auto-merging Dependabot patch updates

## When not to use

- Full workflow security review (injection, permissions, pull_request_target):
  `workflow-security-audit`
- Renovate users: the pinning part applies (Renovate's `helpers:pinGitHubActionDigests`
  preset does it), the dependabot.yml part does not
- Vulnerability triage of a specific advisory: read the advisory and the changelog

## Workflow

1. **List what is unpinned** (dry run, no mapping needed):
   ```bash
   python3 scripts/pin_actions.py .
   ```
   Exit 1 = unpinned references remain. Local `./` actions and `docker://` images are skipped
   (pin images by `@sha256:` digest by hand).
2. **Build the mapping.** Never invent or recall SHAs from memory. Either the user runs:
   ```bash
   python3 scripts/pin_actions.py . --resolve-script > resolve-pins.sh
   sh resolve-pins.sh            # git ls-remote per action; writes pins.txt
   ```
   or provides a JSON/text mapping from their own tooling. Prefer full versions
   (`v7.0.1`) over moving majors (`v7`) in the comment: change the `uses:` ref first if
   the user agrees. Formats are in [references/pinning.md](references/pinning.md).
3. **Apply the pins.**
   ```bash
   python3 scripts/pin_actions.py . --map pins.txt --diff     # review
   python3 scripts/pin_actions.py . --map pins.txt --write    # rewrite in place
   ```
   Result: `uses: actions/checkout@<40-hex> # v7.0.1`. The comment is what Dependabot
   updates alongside the SHA and what humans read.
4. **Generate or check dependabot.yml.**
   ```bash
   python3 scripts/dependabot_gen.py . > dependabot.yml.new          # review, then move to .github/
   python3 scripts/dependabot_gen.py . --cooldown 3 --limit 5 --label dependencies
   python3 scripts/dependabot_gen.py . --check .github/dependabot.yml  # exit 1 if ecosystems missing
   ```
   Defaults: weekly, one group per ecosystem for minor+patch, all actions in one group,
   `ci:`/`deps:` commit prefixes. Tune with [references/dependabot-config.md](references/dependabot-config.md)
   (monorepo `directories`, private registries, ignore rules, security-update groups).
5. **Optional: safe auto-merge** for patch/minor updates with required CI, using
   `dependabot/fetch-metadata` (template in the reference). Never auto-merge majors or
   GitHub Actions updates without review of the release notes.
6. **Verify:** re-run `pin_actions.py .` (exit 0), commit, then check Insights >
   Dependency graph > Dependabot for "Last checked" without errors.

## Output

```
Pinning: 14 uses: references in 5 files
  pinned now 11 | already pinned 2 | unresolved 1 (acme/internal-action@v1: private, needs a token)
Diff: (shown)

dependabot.yml: github-actions /, npm /, pip /apps/api, docker /apps/api + /services/worker,
terraform /infra - weekly, grouped minor/patch, cooldown 3 days
Existing config was missing: pip, docker, terraform
```
