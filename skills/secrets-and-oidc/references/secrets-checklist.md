# Secrets checklist

## Storage and scope

- [ ] Cloud access uses OIDC; no cloud keys stored as secrets.
- [ ] Deploy secrets are **environment** secrets (not repository secrets) on an environment
      with required reviewers and deployment branch/tag rules.
- [ ] Organisation secrets are limited to selected repositories.
- [ ] Non-sensitive identifiers (role ARNs, client ids, project ids, URLs) are `vars`, so
      logs stay readable and nobody treats them as secrets.
- [ ] Dependabot has its own secret store (Dependabot secrets); only registry credentials
      it needs are there.

## Exposure in workflows

- [ ] Secrets are passed at step level (`env:` or `with:` on the step that needs them),
      never in workflow-level `env`.
- [ ] No `${{ secrets.X }}` inside `run:` text; use env and `"$X"`.
- [ ] No `set -x` / `--verbose` in steps that handle secrets; no `printenv` / `env` dumps.
- [ ] Derived values are masked: `echo "::add-mask::$DERIVED"` before printing anything
      built from a secret (masking only hides exact strings; base64, URL-encoded or split
      values are not masked automatically).
- [ ] Secrets are not written to files that are uploaded as artifacts or cached.
- [ ] Reusable workflows receive named secrets, not `secrets: inherit` across owners.
- [ ] Fork PR workflows (`pull_request`) get no secrets - that is GitHub's default; do not
      work around it with `pull_request_target`.

## GITHUB_TOKEN

- [ ] Repository default is read-only; each job requests what it needs.
- [ ] For cross-repo access use a GitHub App installation token
      (`actions/create-github-app-token`) with minimal repository scope instead of a
      personal access token.
- [ ] Fine-grained PATs, if unavoidable, have an expiry and one repository.

## Rotation and incident response

- [ ] Each remaining secret has an owner and a rotation interval.
- [ ] After a leak: revoke at the provider first, then replace the GitHub secret, then
      check provider audit logs for use during the exposure window.
- [ ] Secret scanning and push protection are enabled on the repository.
