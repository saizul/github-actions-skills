# Dependabot configuration

Reference: https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference

## Baseline

```yaml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"            # scans .github/workflows and root action.yml
    schedule:
      interval: "weekly"
    groups:
      actions:
        patterns: ["*"]
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
    groups:
      npm-minor-patch:
        update-types: ["minor", "patch"]
```

Composite actions in subfolders (`.github/actions/*/action.yml`) need their own
directories in the `github-actions` block (`directories: ["/", "/.github/actions/*"]`;
`directories` supports globs, `directory` does not).

## Reducing noise

- `groups` - fewer PRs. Group identifiers may contain letters, `|`, `_` and `-` and must
  start and end with a letter.
- `cooldown: { default-days: 3 }` - skip versions younger than N days (version updates
  only, not security updates). Many projects use 3-7 days to avoid freshly published
  malicious or broken releases.
- `open-pull-requests-limit` - default 5 for version updates.
- `ignore` - e.g. ignore majors of a framework you upgrade by hand:
  ```yaml
  ignore:
    - dependency-name: "react"
      update-types: ["version-update:semver-major"]
  ```
- `schedule.interval: "monthly"` for slow-moving ecosystems (Terraform, Docker base images).

## Security updates

Enable Dependabot alerts and security updates in Settings > Code security. To group
security PRs: a group with `applies-to: security-updates`.

## Monorepos

```yaml
  - package-ecosystem: "npm"
    directories: ["/apps/*", "/packages/*"]
    schedule:
      interval: "weekly"
    groups:
      npm-minor-patch:
        update-types: ["minor", "patch"]
```

Each block for the same ecosystem and target branch must use distinct directories.

## Private registries

```yaml
registries:
  npm-github:
    type: npm-registry
    url: https://npm.pkg.github.com
    token: ${{ secrets.DEPENDABOT_NPM_TOKEN }}   # a Dependabot secret, not an Actions secret
updates:
  - package-ecosystem: "npm"
    directory: "/"
    registries: [npm-github]
    schedule:
      interval: "weekly"
```

## Dependabot and workflows

- Workflows triggered by Dependabot PRs get a read-only `GITHUB_TOKEN` and only
  Dependabot secrets.
- `pull_request_target` to give Dependabot PRs more access is a security risk; prefer
  separate steps that need no secrets, or `workflow_run`.

## Safe auto-merge (patch and minor, CI required)

```yaml
name: Dependabot auto-merge
on: pull_request
permissions:
  contents: write
  pull-requests: write
jobs:
  automerge:
    if: github.event.pull_request.user.login == 'dependabot[bot]'
    runs-on: ubuntu-latest
    steps:
      - id: meta
        uses: dependabot/fetch-metadata@<sha> # v3
      - if: >-
          steps.meta.outputs.update-type != 'version-update:semver-major' &&
          steps.meta.outputs.package-ecosystem != 'github_actions'
        run: gh pr merge --auto --squash "$PR_URL"
        env:
          PR_URL: ${{ github.event.pull_request.html_url }}
          GH_TOKEN: ${{ github.token }}
```

Requires "Allow auto-merge" in repository settings and branch protection with required
status checks; otherwise `--auto` merges immediately. Check the `package-ecosystem` output
value format in the fetch-metadata README for your version.
