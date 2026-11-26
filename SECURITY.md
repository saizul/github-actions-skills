# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## What counts as a vulnerability

These skills are run by AI agents on real repositories and CI pipelines, so unsafe guidance
is treated like a code vulnerability:

- A script that prints a secret value instead of only its name or location
- A script that writes files without being asked (`--write`, `--output`), writes outside
  the paths it was given, or makes network calls
- Command or code injection: crafted workflow YAML, run logs or JSON that make a script
  execute something
- A `SKILL.md` workflow that tells the agent to push tags, publish releases, change
  repository or cloud settings, or apply trust policies without asking the user first
- Security advice that is wrong in a way that leaves users exposed, for example a
  "safe" pattern that still allows script injection, a trust policy that trusts other
  repositories, or a pin that does not point at a commit
- A security check that reports a dangerous workflow as clean in a way users would rely on
  (please include the workflow)

An ordinary false negative or false positive is a normal bug: please open an issue.

## Reporting

Please **do not** open a public issue. Use
[GitHub private vulnerability reporting](https://github.com/saizul/github-actions-skills/security/advisories/new)
with the affected skill, version, impact and steps to reproduce. Remove secrets, private
logs and internal hostnames from examples.

You will get an answer within 5 working days. Fixes are released as soon as possible and
credited in the changelog unless you prefer otherwise.

Vulnerabilities in GitHub Actions itself or in third-party actions should be reported to
GitHub or to the action's maintainers, not here.
