---
name: release-automation
description: Automate releases with GitHub Actions - semantic version tags, Conventional Commits, changelogs, GitHub Releases with assets via gh release create, auto-generated release notes (.github/release.yml), release-please or semantic-release, and signed build provenance with actions/attest plus gh attestation verify. Includes a tag-triggered release workflow template and a script that computes the next version and a Keep a Changelog section from git log (BREAKING CHANGE footers, feat/fix/perf, prereleases) and lints commit subjects. Use when the user wants to cut releases automatically, generate a changelog or release notes, decide the next version number, publish binaries to GitHub Releases, add SLSA provenance or artifact attestations, or fix a release workflow that fails with "Resource not accessible by integration".
license: MIT
compatibility: Python 3.8+ standard library for the script; git and the GitHub CLI (gh) for the commands the user runs.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Release automation

Turn "we release by hand" into: merge to main -> tag -> build -> attest -> GitHub Release
with notes. Never push tags or publish releases yourself without the user's go-ahead.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Automate our releases", "generate a changelog", "what should the next version be?"
- Attaching binaries/packages to GitHub Releases, prereleases (`-rc.1`)
- Supply-chain asks: provenance, SLSA, signed artifacts, `gh attestation verify`
- A release job fails with `Resource not accessible by integration` (missing `contents: write`)

## When not to use

- Publishing to a package registry with its own flow (npm provenance, PyPI trusted
  publishing): follow the registry's docs; this skill covers the GitHub side
- Keeping action versions updated: `dependabot-and-pinning`
- Cloud deploys after a release: `secrets-and-oidc`

## Workflow

1. **Pick a strategy** with the user (details in [references/release-patterns.md](references/release-patterns.md)):
   - **Tag-driven** (simplest): a maintainer pushes `vX.Y.Z`; the workflow builds and publishes.
   - **Release PR** (release-please): a bot keeps a PR with the version bump and
     CHANGELOG; merging it tags and releases.
   - **Fully automatic** (semantic-release): every merge to main may release.
2. **Compute the version and notes** from commits since the last tag:
   ```bash
   last=$(git describe --tags --abbrev=0)
   git log --format='%h%x1f%s%x1f%b%x1e' "$last"..HEAD | \
     python3 scripts/next_version.py --current "$last" --repo OWNER/REPO
   python3 scripts/next_version.py --current v0.9.0 --pre-major --log log.txt --json
   python3 scripts/next_version.py --current v1.4.2 --pre rc --log log.txt   # 1.5.0-rc.1
   git log --format=%s "$last"..HEAD | python3 scripts/next_version.py --check   # lint subjects
   ```
   Use the full format (with `%b`) so `BREAKING CHANGE:` footers are seen. `--check` exits
   1 for non-conventional subjects (useful as a PR title check). Show the user the bump
   and the changelog section; edit wording with them before committing it.
3. **Add the workflow** from `assets/release.yml`: tag trigger, least-privilege
   permissions per job (`contents: write` only in the publishing job; `id-token`,
   `attestations`, `artifact-metadata: write` for attestations), `--verify-tag`,
   prerelease detection, `concurrency` without cancel. Pin actions by SHA.
4. **Release notes.** Either commit the generated section to `CHANGELOG.md`, or use
   GitHub's generated notes with categories from `assets/release-notes-config.yml`
   (copy to `.github/release.yml`; categories come from PR labels).
5. **Provenance.** `actions/attest` signs a SLSA provenance statement for each artifact.
   Consumers verify with:
   ```bash
   gh attestation verify dist/app-v1.5.0.tar.gz --repo OWNER/REPO
   ```
   Attestations need a public repository, or GitHub Enterprise Cloud for private ones.
6. **Hand the user the release commands** (they run them, after reviewing):
   ```bash
   git tag -a v1.5.0 -m "v1.5.0" && git push origin v1.5.0
   ```
   Then check the run (`gh run watch`) and the release page. Protect tags with a ruleset
   (Settings > Rules) so only maintainers or the release workflow can create `v*` tags.

## Output

```
Release plan for acme/tool

Last tag v1.4.2 -> next v2.0.0 (major: refactor(api)! renames Client.run)
Commits: 5 (1 not conventional: "updated stuff")

CHANGELOG section:
## [2.0.0] - 2026-11-26
### Breaking changes
- **api:** Client.run was removed; use Client.execute. (d4e5f60)
### Features ...

Workflow: .github/workflows/release.yml (tag v*, attest, gh release create --generate-notes)
You run: git tag -a v2.0.0 -m v2.0.0 && git push origin v2.0.0
Verify:  gh attestation verify dist/app-v2.0.0.tar.gz --repo acme/tool
```
