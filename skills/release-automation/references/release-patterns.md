# Release patterns

## Versioning rules (SemVer + Conventional Commits)

| Commit | Bump |
| --- | --- |
| `feat!: ...`, `fix(api)!: ...`, or a `BREAKING CHANGE:` footer | major |
| `feat: ...` | minor |
| `fix: ...`, `perf: ...`, `revert: ...` | patch |
| `docs`, `chore`, `ci`, `test`, `refactor`, `build`, `style` | none |

On `0.y.z`, many projects bump minor for breaking changes (`--pre-major`).

## Option A: tag-driven (assets/release.yml)

- Trigger `on: push: tags: ["v*"]`.
- `gh release create "$TAG" dist/* --verify-tag --generate-notes` fails if the tag does
  not exist remotely, so the release always matches a pushed tag.
- `--notes-file CHANGELOG-section.md` instead of `--generate-notes` to use your own notes;
  extract the section for the tag from `CHANGELOG.md` with a small `awk`:
  ```bash
  awk -v v="${TAG#v}" '$0 ~ "^## \\[" v "\\]" {p=1; next} /^## \[/ {p=0} p' CHANGELOG.md > notes.md
  ```
- `--draft` to review before publishing; `--prerelease` for `-rc`/`-beta` tags;
  `--latest=false` for backport releases.

## Option B: release PR (release-please)

```yaml
on:
  push:
    branches: [main]
permissions:
  contents: write
  pull-requests: write
jobs:
  release-please:
    runs-on: ubuntu-latest
    steps:
      - id: rp
        uses: googleapis/release-please-action@<sha> # v5
        with:
          release-type: simple       # node, python, go, rust, ...
      - if: ${{ steps.rp.outputs.release_created }}
        run: echo "released ${{ steps.rp.outputs.tag_name }}"
```

Note: PRs and tags created with `GITHUB_TOKEN` do not trigger other workflows (no CI on
the release PR, no tag-triggered build). Either build in the same workflow behind
`if: steps.rp.outputs.release_created`, or use a GitHub App token
(`actions/create-github-app-token`) for the action's `token` input.

## Option C: semantic-release

Runs on every push to main, analyses commits, tags, publishes and writes notes. Good for
libraries with strict Conventional Commits; needs the npm toolchain even for non-JS
projects. Same `GITHUB_TOKEN` trigger caveat as above.

## Permissions cheat sheet

| Step | Permission |
| --- | --- |
| Create release, upload assets, push tags/commits | `contents: write` |
| Comment on / label PRs | `pull-requests: write` |
| Attestations | `id-token: write`, `attestations: write` (+ `artifact-metadata: write` per actions/attest docs) |
| Push container images to GHCR | `packages: write` |

`Resource not accessible by integration` almost always means a missing permission above,
or the repository's default token permission is read-only and the job did not request write.

## Provenance and verification

```yaml
- uses: actions/attest@<sha> # v4
  with:
    subject-path: dist/*          # files; or subject-name + subject-digest for images
```

```bash
gh attestation verify dist/app.tar.gz --repo OWNER/REPO
gh attestation verify oci://ghcr.io/owner/app:1.5.0 --repo OWNER/REPO
# stricter: only accept artifacts built by a specific workflow
gh attestation verify dist/app.tar.gz --repo OWNER/REPO \
  --signer-workflow OWNER/REPO/.github/workflows/release.yml
```

Container images: build with `docker/build-push-action`, then attest with
`subject-name: ghcr.io/${{ github.repository }}` and `subject-digest: ${{ steps.build.outputs.digest }}`
and `push-to-registry: true`.

## Hardening the release path

- Protect `v*` tags with a tag ruleset; protect `main`.
- Put the publishing job in an environment with required reviewers.
- If your plan offers immutable releases, enable them so assets cannot be swapped after publishing.
- Build from the tagged commit only (`actions/checkout` default ref on tag pushes).
- Publish checksums (`SHA256SUMS`) alongside assets for users without `gh`.
