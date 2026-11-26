# Contributing to github-actions-skills

Thank you for helping! New checks, new skills, fixes, fixture workflows and run logs from
real projects (redacted) and clearer docs are all welcome.

- [Ways to contribute](#ways-to-contribute)
- [Good first issues](#good-first-issues)
- [Development setup](#development-setup)
- [Repository layout](#repository-layout)
- [Write a new skill](#write-a-new-skill)
- [Quality bar](#quality-bar)
- [Pull request process](#pull-request-process)

## Ways to contribute

| Size | Idea |
| --- | --- |
| 10 minutes | Fix a typo, clarify a workflow step, update an action version in a reference |
| 30 minutes | Add a fixture workflow or log that triggers a false positive or a missed finding |
| 1-2 hours | Add a check or an error signature to an existing script (see below) |
| Half a day | Write a new skill from the template |

Comment on an issue before you start so nobody else picks the same one.

## Good first issues

Each of these is self-contained and touches one script and its test file.

1. **workflow-security-audit: `persist-credentials`.** Report `low` when `actions/checkout`
   runs without `persist-credentials: false` in a job that later uploads artifacts.
2. **workflow-security-audit: `GITHUB_ENV` injection.** Flag `run:` steps that write an
   untrusted `${{ github.event.* }}` value into `$GITHUB_ENV` or `$GITHUB_OUTPUT`.
3. **workflow-security-audit: `--baseline` file.** Accept a JSON file of accepted findings
   (check + file + job) and report only new ones, for gradual adoption in CI.
4. **workflow-speed: `fetch-depth: 0`.** Report `info` for checkouts with full history in
   jobs that never run git commands.
5. **workflow-speed: per-workflow breakdown.** When `--runs` contains several
   `workflowName`s, print the waste table per workflow.
6. **reusable-workflows-composite-actions: `github.action_path`.** Warn when a composite
   action runs `./script.sh` (relative to the caller's workspace) instead of
   `${{ github.action_path }}/script.sh`.
7. **release-automation: `--from-changelog`.** Extract the section for a tag from an
   existing `CHANGELOG.md` for `gh release create --notes-file`.
8. **matrix-and-services: `--values`.** Accept `--values key=JSON` to expand matrices
   built with `fromJSON(...)`.
9. **secrets-and-oidc: Vault and PyPI.** Recognise `hashicorp/vault-action` with
   `method: token` and PyPI uploads with `password: ${{ secrets.PYPI_TOKEN }}` as
   long-lived credentials and point to trusted publishing.
10. **workflow-debugging: more signatures.** Add Gradle (`Could not resolve all files`),
    Cargo (`failed to select a version`) and Playwright (`browserType.launch`) signatures
    with a test line each.
11. **dependabot-and-pinning: `container:` and `services:` images.** Report images in
    workflows that are not pinned by digest, with a `docker buildx imagetools inspect`
    command to resolve them.
12. **New skill: `self-hosted-runners`** (see the roadmap in the README).

## Development setup

```bash
git clone https://github.com/saizul/github-actions-skills.git
cd github-actions-skills
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt      # pytest, ruff, PyYAML

python tools/validate_skills.py   # SKILL.md frontmatter, sections, links, marketplace listing
ruff check . && ruff format --check .
pytest
```

To try your changes in Claude Code, either copy a skill to `~/.claude/skills/` or add your
checkout as a local marketplace:

```bash
claude plugin marketplace add ./github-actions-skills
claude plugin install github-actions-skills@github-actions-skills
```

For Codex, copy the skill folder to `~/.agents/skills/`.

## Repository layout

```
.claude-plugin/
  marketplace.json      marketplace + plugin entry listing every skill
  plugin.json           plugin manifest (name, version, author)
skills/<name>/
  SKILL.md              frontmatter + workflow (the part agents read)
  scripts/*.py          standalone helpers
  references/*.md       detail loaded on demand
  assets/               templates (workflows, composite action)
templates/skill/        copy this to start a new skill
tests/
  test_<skill>.py       one test module per skill
  fixtures/workflows/   shared workflow YAML (good and bad)
  fixtures/<skill>/     skill-specific inputs (run logs, run JSON, mappings, fixture repos)
tools/validate_skills.py
```

## Write a new skill

1. Open a "New skill proposal" issue first so we can agree on scope.
2. Copy the template:
   ```bash
   cp -r templates/skill skills/my-skill
   mv skills/my-skill/scripts/your_script.py skills/my-skill/scripts/my_check.py
   ```
3. Edit `SKILL.md`:
   - `name` equals the folder name: lowercase letters, digits, single hyphens, max 64 chars.
   - `description` (max 1024 chars) says **what** it does with concrete keywords and **when**
     to use it, starting the second part with "Use when ...". This text decides whether
     the agent picks the skill, so list the phrases and error messages users actually type.
     Avoid `: ` and ` #` in it (YAML would misread them).
   - Required sections: `## When to use`, `## When not to use`, `## Workflow`, `## Output`.
   - Workflow steps are imperative and numbered, with exact commands, decision points and
     the point where the agent must ask before changing anything.
   - Keep it under 400 lines; move tables, snippets and long configs to `references/`.
4. Write the script: `argparse` with a useful `--help`, `--json` output, exit codes
   0 (ok) / 1 (findings) / 2 (error), read-only by default, no network, never print secret
   values. Handle YAML's `on:` key being read as `True` (copy `load_workflow` from an
   existing script).
5. Add `tests/test_my_skill.py`. Reuse `tests/fixtures/workflows/` where possible and add
   new fixtures for your cases. Cover a bad input, a good input with no findings, edge
   cases and the CLI exit codes.
6. Add the skill to `.claude-plugin/marketplace.json` (`plugins[0].skills`), the README
   skills table, the table in `AGENTS.md`, the bug report dropdown and `CHANGELOG.md`
   under "Unreleased".
7. Run the validator, ruff and pytest.

## Quality bar

- **Grounded in real GitHub Actions.** Keys, contexts, error messages and action inputs
  must match the GitHub docs or the action's `action.yml`. Link the source in the PR.
- **Versions and SHAs are checked, not recalled.** Look up the current release of any
  action you mention; put real SHAs only where you verified them, `<sha>` otherwise.
- **Safety first.** A skill must never tell the agent to push, release, re-run, change
  settings or apply cloud permissions without showing the change and getting confirmation.
- **Deterministic where it matters.** If a step is "parse this YAML/log and find X", write
  a script and test it instead of relying on the model reading 800 lines.
- **Low false positives.** If a check is often wrong, make it `info`/`low` or drop it, and
  document known limits in the skill's references.
- **Fake secrets only.** Build test tokens from pieces in test code so secret scanners do
  not match the repository.

## Pull request process

1. Fork, create a branch, make focused commits.
2. Make sure CI passes locally (validator, ruff, pytest).
3. Fill in the pull request template.
4. A maintainer reviews within a few days. Small, focused pull requests are merged fastest.

By contributing you agree that your contributions are licensed under the MIT License.
