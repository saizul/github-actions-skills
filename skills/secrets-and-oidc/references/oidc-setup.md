# OIDC setup per cloud

GitHub's issuer is `https://token.actions.githubusercontent.com`. Each job with
`permissions: id-token: write` can request a token whose claims include `sub`, `aud`,
`repository`, `repository_id`, `repository_owner`, `ref`, `environment`, `event_name`,
`workflow_ref`, `job_workflow_ref` (the reusable workflow that runs) and `runner_environment`.

Default `sub` formats:

| Run | `sub` |
| --- | --- |
| job with `environment: production` | `repo:OWNER/REPO:environment:production` |
| push to a branch | `repo:OWNER/REPO:ref:refs/heads/main` |
| tag | `repo:OWNER/REPO:ref:refs/tags/v1.2.3` |
| pull request | `repo:OWNER/REPO:pull_request` |

When a job uses an environment, the `sub` is the environment form, not the branch form.
Organisations can customise the `sub` template (for example to include `repository_id`
or `job_workflow_ref`) through the REST API; trust policies must then match the custom format.

## AWS

1. Once per account: IAM > Identity providers > Add provider > OpenID Connect,
   URL `https://token.actions.githubusercontent.com`, audience `sts.amazonaws.com`.
2. Role with the trust policy from `trust_policy.py aws ...` and only the permissions the
   deploy needs (for example `s3:PutObject` on one bucket, not `AdministratorAccess`).
3. Workflow:
   ```yaml
   jobs:
     deploy:
       runs-on: ubuntu-latest
       environment: production
       permissions:
         id-token: write
         contents: read
       steps:
         - uses: aws-actions/configure-aws-credentials@45666896f5d8e0f10ae255413f3a4cdd03bdc8f5 # v6.3.1
           with:
             role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
             aws-region: eu-west-1
   ```

Errors:
- `Not authorized to perform sts:AssumeRoleWithWebIdentity`: `sub` mismatch (environment vs
  branch form is the usual cause), wrong audience, or provider missing in that account.
- `Could not load credentials from any providers`: no `id-token: write` on the job.

Never trust `repo:OWNER/*` or `StringLike` with `*` in the repository part.

## Google Cloud

1. Workload Identity Pool + OIDC provider (command printed by `trust_policy.py gcp`), with
   an **attribute condition** that pins the repository (prefer `repository_id`, which does
   not change on rename and cannot be re-registered by someone else).
2. Either grant roles directly to the federated principal
   (`principalSet://iam.googleapis.com/projects/NUMBER/locations/global/workloadIdentityPools/POOL/attribute.repository/OWNER/REPO`)
   or allow it to impersonate a service account (`roles/iam.workloadIdentityUser`).
3. Workflow:
   ```yaml
   permissions:
     id-token: write
     contents: read
   steps:
     - uses: google-github-actions/auth@<sha> # v3
       with:
         workload_identity_provider: ${{ vars.GCP_WIF_PROVIDER }}
         service_account: ${{ vars.GCP_DEPLOY_SA }}
   ```

Delete the service-account JSON keys afterwards and consider the org policy that blocks
key creation (`iam.disableServiceAccountKeyCreation`).

## Azure

1. App registration or user-assigned managed identity > Federated credentials > GitHub
   Actions scenario, or `az ad app federated-credential create --id APP_ID --parameters cred.json`
   with the JSON from `trust_policy.py azure ...`. Subjects match exactly: one credential
   per environment/branch.
2. Role assignment for the identity on the narrowest scope (resource group, not subscription).
3. Workflow:
   ```yaml
   permissions:
     id-token: write
     contents: read
   steps:
     - uses: azure/login@<sha> # v3
       with:
         client-id: ${{ vars.AZURE_CLIENT_ID }}
         tenant-id: ${{ vars.AZURE_TENANT_ID }}
         subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}
   ```

`AADSTS70021: No matching federated identity record found` = subject mismatch.

## Other systems

HashiCorp Vault (`hashicorp/vault-action` with `method: jwt`), PyPI and npm trusted
publishing, Terraform Cloud, Kubernetes clusters with OIDC auth all accept the same token;
bind them to `repository_id` plus environment or ref the same way.

## Reusable workflows

To trust only a central deploy workflow (no matter which repo calls it), match the
`job_workflow_ref` claim, e.g. `org/ci/.github/workflows/deploy.yml@refs/heads/main`. On
AWS this requires a custom `sub` template that includes `job_workflow_ref`.
