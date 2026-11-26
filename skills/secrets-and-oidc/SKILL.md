---
name: secrets-and-oidc
description: Replace long-lived cloud keys in GitHub Actions with OpenID Connect (OIDC) federation to AWS (IAM role + trust policy), Google Cloud (Workload Identity Federation) and Azure (federated credentials), and handle remaining secrets safely - environments with reviewers, step-level env, masking, rotation. Scripts find AWS access keys, GCP service-account JSON keys and Azure client secrets in workflows, check the id-token write permission and environment scoping, flag secrets interpolated into run:, and print least-privilege trust policies scoped to one repo plus branch, tag, environment or pull_request (never wildcards). Use when the user deploys from GitHub Actions to a cloud, stores AWS_ACCESS_KEY_ID or a GCP key JSON as a secret, asks about OIDC, "keyless" auth, workload identity, or sees errors like "Not authorized to perform sts:AssumeRoleWithWebIdentity" or "Unable to get ACTIONS_ID_TOKEN_REQUEST_URL".
license: MIT
compatibility: Python 3.8+; PyYAML (pip install pyyaml) for oidc_check.py. trust_policy.py is stdlib only and prints settings; the user applies them with aws, gcloud or az.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Secrets and OIDC

Goal: no long-lived cloud keys in GitHub. Jobs get short-lived credentials via OIDC, trust
is scoped to one repository and one branch or environment, and the remaining secrets are
exposed to as few steps as possible. Scripts only read and print; cloud changes are made
by the user.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- Secrets like `AWS_ACCESS_KEY_ID`, `GCP_SA_KEY`, `AZURE_CREDENTIALS` in a workflow
- "Set up OIDC to AWS/GCP/Azure", "keyless deploy", "workload identity federation"
- Errors: `Not authorized to perform sts:AssumeRoleWithWebIdentity`,
  `Unable to get ACTIONS_ID_TOKEN_REQUEST_URL env variable`, `AADSTS70021`
- Reviewing how secrets are scoped (environments, step env, Dependabot secrets)

## When not to use

- General workflow hardening (injection, pinning, pull_request_target): `workflow-security-audit`
- A secret was leaked publicly: rotate it **now** with the provider, then come back;
  removing it from git history does not un-leak it
- Application secret management (Vault, SSM) beyond the CI login step

## Workflow

1. **Inventory** (names only, values are never printed):
   ```bash
   python3 scripts/oidc_check.py .
   python3 scripts/oidc_check.py .github/workflows --json --fail-on high
   ```
   `keys.long_lived` = migrate; `oidc.missing_id_token` = the job cannot get a token;
   `oidc.no_environment` = trust can only be scoped by branch; `secrets.in_run` = move to env.
2. **Choose the trust scope** with the user. Best: a GitHub **environment** (`production`)
   with required reviewers and deployment branch rules, trusted as
   `repo:OWNER/REPO:environment:production`. Otherwise one branch (`refs/heads/main`) or a
   tag pattern. `pull_request` subjects only for read-only roles.
3. **Generate the trust settings** (printed for review, not applied):
   ```bash
   python3 scripts/trust_policy.py aws   --repo OWNER/REPO --environment production --account 123456789012
   python3 scripts/trust_policy.py gcp   --repo OWNER/REPO --branch main --repo-id 123456789
   python3 scripts/trust_policy.py azure --repo OWNER/REPO --environment production
   ```
   Wildcard repositories are refused. Provider-side steps (create the OIDC provider once
   per account/pool, attach least-privilege permissions to the role) are in
   [references/oidc-setup.md](references/oidc-setup.md).
4. **Change the workflow:** `permissions: id-token: write` (plus `contents: read`) on the
   deploy job only, `environment:` on that job, the OIDC inputs of the login action, and
   non-secret identifiers (role ARN, client id, provider path) in `vars`, not `secrets`.
5. **Test, then delete the old keys.** Run the workflow; confirm the login step works and
   the cloud audit log (CloudTrail `AssumeRoleWithWebIdentity`, GCP STS logs, Entra sign-in
   logs) shows the expected subject. Then the user deletes the GitHub secrets **and**
   deactivates the keys at the provider.
6. **Review remaining secrets** with [references/secrets-checklist.md](references/secrets-checklist.md).

## Output

```
Secrets and OIDC review: 4 workflows

Long-lived cloud credentials (migrate):
  deploy.yml [aws]   secrets.AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
  deploy.yml [gcp]   google-github-actions/auth credentials_json (GCP_SA_KEY)
Broken OIDC: release.yml [publish] uses role-to-assume without id-token: write

Plan:
1. GitHub environment "production" (reviewers: platform team, branch: main)
2. AWS role trust: sub = repo:acme/web:environment:production, aud = sts.amazonaws.com
3. deploy.yml diff: permissions id-token: write on deploy job, role-to-assume from vars
4. After a green run: delete secrets, deactivate IAM user keys, check CloudTrail
```
