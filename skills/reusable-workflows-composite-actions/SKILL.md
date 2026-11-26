---
name: reusable-workflows-composite-actions
description: Remove copy-pasted GitHub Actions YAML with reusable workflows (on workflow_call, inputs, secrets, outputs, cross-repo calls pinned by SHA) and composite actions (action.yml, runs using composite, shell on every step), with ready templates and a checker that validates callers against what they call - unknown or missing inputs, wrong boolean/number types, undeclared or missing secrets, runs-on/steps next to uses, missing files, composite steps without shell, secrets used inside composite actions and outputs without value. Use when the user wants to share CI across jobs or repositories, DRY up workflows, create an internal action, choose between reusable workflow and composite action, or gets errors like "Unexpected value 'runs-on'", a missing required shell property, or "Invalid input".
license: MIT
compatibility: Python 3.8+ with PyYAML (pip install pyyaml) for the checker. Templates are plain YAML.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Reusable workflows and composite actions

Pick the right reuse mechanism, start from a template, and validate every call site with
the checker before pushing (GitHub only reports these mistakes when the run starts).

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- The same job or step list is copied across workflows or repositories
- "Make an internal action for our setup steps", "share CI across our 20 repos"
- Errors: `Unexpected value 'runs-on'`, `Required property is missing: shell`,
  `Invalid input, x is not defined in the referenced workflow`, `secret ... is required`

## When not to use

- Publishing a JavaScript or Docker action to the Marketplace (different packaging)
- Matrix design inside a job: `matrix-and-services`
- Release pipelines specifically: `release-automation` (it can still call reusable workflows)

## Workflow

1. **Decide the mechanism** (full table in [references/patterns.md](references/patterns.md)):
   - **Reusable workflow** (`workflow_call`): reuse whole jobs - own runners, `needs`,
     environments, matrix, secrets passed explicitly. Shows as separate jobs in the UI.
   - **Composite action** (`runs.using: composite`): reuse a list of steps inside the
     caller's job - shares the job's workspace, runner and env; no `secrets` context.
   - Both: a reusable workflow whose jobs use a composite action for setup.
2. **Start from a template:** `assets/reusable-workflow.yml`, `assets/caller-workflow.yml`,
   `assets/composite-action/action.yml`. Keep inputs few and typed (`string`,
   `boolean`, `number`), give defaults, document each one.
3. **Wire secrets explicitly.** Declare them under `workflow_call.secrets` and pass by
   name. `secrets: inherit` is acceptable inside one organisation when the called workflow
   needs many secrets; never for workflows from other owners. Composite actions get secrets
   as inputs (`with: token: ${{ secrets.X }}`).
4. **Version it.** Local calls (`./.github/workflows/x.yml`) use the same commit. Cross-repo
   calls must pin a ref: `org/ci/.github/workflows/build.yml@<sha> # v1.4.0`, released
   with tags from the shared repository. The shared repository must allow access
   (Settings > Actions > General > Access) if it is private or internal.
5. **Run the checker** from the repository root:
   ```bash
   python3 scripts/check_reusable.py .
   python3 scripts/check_reusable.py . --json --strict
   ```
   Exit 1 = errors (or warnings with `--strict`). Fix every error; check ids are listed in
   the script's `--help`.
6. **Explain limits** that commonly surprise people:
   [references/patterns.md](references/patterns.md#limits-and-gotchas) (nesting depth,
   env not inherited by called workflows, outputs only via jobs, `GITHUB_TOKEN`
   permissions can only be reduced by the callee).
7. **Show the diff** of the extracted workflow/action and the updated callers; apply after
   confirmation, re-run the checker.

## Output

```
Reuse plan: 4 workflows repeat checkout + setup-node + npm ci (11 copies)

1. .github/actions/setup-project/action.yml (composite): node-version, install-args
2. .github/workflows/_build-test.yml (reusable): node-version, working-directory, run-e2e;
   secret NPM_TOKEN
3. ci.yml and nightly.yml call _build-test.yml; deploy.yml uses the composite action

check_reusable.py: 0 errors, 0 warnings (was: 3 errors - missing shell, unknown input 'regoin')
Diff: (proposed)
```
