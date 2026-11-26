# Pinning reference

## Why SHAs

A tag (`v4`) or branch (`main`) can be moved by anyone with write access to the action's
repository, including an attacker with a stolen token. A full 40-character commit SHA
cannot be changed. Short SHAs are rejected by GitHub for actions and would be ambiguous.

Organisations can enforce SHA pinning in the Actions policy settings ("Require actions to
be pinned to a full-length commit SHA") where the plan offers it.

## Mapping file formats

```json
{
  "actions/checkout": { "v7.0.1": "3d3c42e5aac5ba805825da76410c181273ba90b1" },
  "actions/setup-node@v7.1.0": "949feb2413d6458794dcd2491c4babbbce0c15c1"
}
```

```text
# owner/repo@ref sha
actions/setup-python@v7.1.0 6d4fd22b20465ccc0f7354476588e8df7c9ca0e0
```

Keys use `owner/repo` even for actions in subfolders (`github/codeql-action/init@v4`
uses the `github/codeql-action@v4` entry).

## Resolving a tag to a commit SHA yourself

```bash
git ls-remote https://github.com/actions/checkout 'refs/tags/v7.0.1^{}' 'refs/tags/v7.0.1'
```

If a `^{}` line is printed, the tag is annotated and **that** line's SHA is the commit;
the other line is the tag object and must not be used. Alternatively, with the GitHub CLI:

```bash
gh api repos/actions/checkout/commits/v7.0.1 --jq .sha
```

Check that the SHA belongs to the action's repository and not to a fork (GitHub resolves
fork commits through the parent repository's network): open
`https://github.com/OWNER/REPO/commit/SHA` and confirm it is on a branch or tag of that repo.

## Reusable workflows and composite actions

- `uses: org/ci/.github/workflows/build.yml@<sha> # v2.1.0` - same rules.
- A composite action pinned by SHA can still call unpinned actions inside it; review
  third-party composite actions' `action.yml` too.
- Docker actions (`runs.using: docker` with `image: docker://...:tag`) can change the image
  behind a pinned SHA; prefer actions that pin their image by digest.

## Images

```yaml
container: node:22@sha256:<digest>
services:
  postgres:
    image: postgres:17@sha256:<digest>
```

`docker buildx imagetools inspect postgres:17` prints the index digest. Dependabot's
`docker` ecosystem updates digests in Dockerfiles; for workflow `container:`/`services:`
images check the current Dependabot docs for support, otherwise update them manually.
