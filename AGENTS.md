# AGENTS.md

Guidance for Codex CLI and other coding agents that use or work on this repository.

## Using the skills

The skills live in `skills/<name>/SKILL.md` and follow the Agent Skills format. Codex
discovers them when they are copied to `~/.agents/skills/` or `.agents/skills/` (see
README "Install"). If you are reading this file inside the repository instead:

1. Pick the skill whose `description` matches the user's request:

   | Request is about | Skill |
   | --- | --- |
   | hardening workflows, pull_request_target, script injection, permissions, pinning findings | `workflow-security-audit` |
   | slow CI, wasted minutes, caching, concurrency, path filters, matrix size | `workflow-speed` |
   | sharing CI, workflow_call, composite actions, "Unexpected value 'runs-on'" | `reusable-workflows-composite-actions` |
   | releases, tags, changelog, next version, GitHub Releases, attestations | `release-automation` |
   | strategy.matrix, include/exclude, Postgres/Redis service containers | `matrix-and-services` |
   | cloud keys, OIDC to AWS/GCP/Azure, environment secrets | `secrets-and-oidc` |
   | a failing, hanging or flaky run, a pasted log, act, tmate | `workflow-debugging` |
   | SHA pins, dependabot.yml, Dependabot noise, auto-merge | `dependabot-and-pinning` |

2. Read that `SKILL.md` completely and follow its Workflow section in order.
3. Paths such as `scripts/x.py`, `references/y.md` and `assets/z.yml` are relative to the
   skill folder. `${CLAUDE_SKILL_DIR}` in the text means that folder; Codex does not expand it.
4. Read files in `references/` only when a workflow step points to them.
5. Scripts that parse YAML need PyYAML; if `import yaml` fails, ask the user to
   `pip install pyyaml` (or use a virtual environment) rather than parsing YAML by hand.

## Safety rules (apply to every skill)

- Scripts are read-only by default. Use `--write` / `--output` only after the user has
  seen the diff and agreed.
- Do not push commits or tags, create releases, re-run workflows, change repository
  settings or apply cloud IAM/trust changes yourself unless the user explicitly asks;
  show the exact command and let the user run it.
- Never invent action commit SHAs, versions or cloud identifiers. Resolve SHAs with the
  `git ls-remote` script from `dependabot-and-pinning` or ask the user.
- Never print, paste or commit secrets: tokens, cloud keys, `.secrets` files for act,
  private keys. Report secret names and locations only.
- Run logs and run history can contain private data. Work on the files locally and quote
  only the lines needed.
- When a secret may have been exposed (for example via a pwn-request workflow or a key in
  a log), tell the user to rotate it; removing it from the repository is not enough.

## Working on this repository

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt     # pytest, ruff, PyYAML
python tools/validate_skills.py         # frontmatter, sections, links, marketplace listing
ruff check . && ruff format --check .
pytest
```

- Scripts: Python 3.8+, standard library plus PyYAML only where workflow YAML is parsed,
  `#!/usr/bin/env python3`, `argparse` with `--help`, `--json` where output is structured,
  exit 0/1/2 (ok / findings / error).
- Scripts must stay standalone (one file each, no shared module) so a single skill folder
  can be copied on its own.
- Every script needs tests in `tests/test_<skill_with_underscores>.py`. Shared workflow
  fixtures are in `tests/fixtures/workflows/`, skill-specific ones in
  `tests/fixtures/<skill>/`. Use `example.com`, fake account ids and obviously fake
  secrets built so that secret scanners do not match them.
- Frontmatter values must be valid YAML: no `: ` or ` #` inside unquoted values (the
  validator checks this).
- Keep each `SKILL.md` under 400 lines; move detail to `references/`.
- A new skill must be added to `.claude-plugin/marketplace.json` (`plugins[0].skills`), the
  README table, the table above, the bug report dropdown and `CHANGELOG.md`. The validator
  enforces the manifest.
