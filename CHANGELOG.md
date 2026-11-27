# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `workflow-security-audit`: `checkout.persist_creds` check for `actions/checkout` steps that
  keep the default `persist-credentials: true`, which leaves the job token in `.git/config`
  for every later step. Low by default, medium under `pull_request_target` or
  `workflow_run`; the line points at the checkout step.

## [0.1.0] - 2026-11-26

### Added

- `workflow-security-audit`: `audit_workflows.py` for actions pinned by tag or branch,
  unpinned `docker://` images, missing or `write-all` permissions, `pull_request_target` /
  `workflow_run` pwn requests, script injection in `run:` and github-script, secrets in
  workflow-level env, `secrets: inherit`, self-hosted runners and unsecure commands;
  checks reference and hardening patterns.
- `workflow-speed`: `estimate_waste.py` (concurrency, caching, path filters, duplicate
  push/PR triggers, matrix size, timeouts, expensive runner OS; wasted minutes from
  `gh run list --json` history) with caching and speed pattern references.
- `reusable-workflows-composite-actions`: `check_reusable.py` validating callers against
  `workflow_call` inputs/secrets/outputs and composite actions; reusable workflow, caller
  and composite action templates.
- `release-automation`: `next_version.py` (Conventional Commits -> next SemVer, changelog
  section, prereleases, commit linting); tag-driven release workflow with `actions/attest`
  provenance and release-notes configuration.
- `matrix-and-services`: `expand_matrix.py` (exact include/exclude expansion, limits,
  service container checks) with matrix and service container references.
- `secrets-and-oidc`: `oidc_check.py` (long-lived cloud keys, missing `id-token: write`,
  environment scoping, secrets in `run:`) and `trust_policy.py` (AWS, GCP, Azure trust
  settings for one repository and branch/tag/environment); OIDC setup guide and secrets checklist.
- `workflow-debugging`: `parse_run_log.py` for `gh run view --log` output, log archives and
  folders with 30 error signatures; debugging techniques (debug logging, act, tmate safety).
- `dependabot-and-pinning`: `pin_actions.py` (offline tag -> SHA pins from a mapping, diff,
  write, git ls-remote resolver script) and `dependabot_gen.py` (ecosystem detection,
  grouped dependabot.yml, drift check).
- Claude Code plugin marketplace manifest, `tools/validate_skills.py`, CI and release workflows.

[Unreleased]: https://github.com/saizul/github-actions-skills/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/saizul/github-actions-skills/releases/tag/v0.1.0
