#!/usr/bin/env python3
"""Generate least-privilege OIDC trust settings for GitHub Actions -> AWS, GCP or Azure.

Prints (never applies) the trust policy / attribute condition / federated credential for
one repository, scoped to exactly one of: a branch, a tag pattern, an environment, or
pull requests. The user reviews it and applies it with their own cloud CLI or IaC.

Subject claim formats (GitHub default):
  repo:OWNER/REPO:ref:refs/heads/BRANCH
  repo:OWNER/REPO:ref:refs/tags/TAG
  repo:OWNER/REPO:environment:NAME
  repo:OWNER/REPO:pull_request

Offline. Exit codes: 0 = printed, 2 = invalid arguments (for example a wildcard repository).
"""

from __future__ import annotations

import argparse
import json
import re
import sys

ISSUER = "https://token.actions.githubusercontent.com"
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
ACCOUNT_RE = re.compile(r"^\d{12}$")


def subject(repo: str, branch=None, tag=None, environment=None, pull_request=False) -> str:
    if environment:
        return f"repo:{repo}:environment:{environment}"
    if branch:
        return f"repo:{repo}:ref:refs/heads/{branch}"
    if tag:
        return f"repo:{repo}:ref:refs/tags/{tag}"
    if pull_request:
        return f"repo:{repo}:pull_request"
    raise ValueError("choose one of --branch, --tag, --environment, --pull-request")


def aws_policy(account: str, sub: str) -> dict:
    op = "StringLike" if "*" in sub else "StringEquals"
    cond = {
        "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
    }
    if op == "StringEquals":
        cond["StringEquals"]["token.actions.githubusercontent.com:sub"] = sub
    else:
        cond["StringLike"] = {"token.actions.githubusercontent.com:sub": sub}
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Federated": f"arn:aws:iam::{account}:oidc-provider/token.actions.githubusercontent.com"},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": cond,
            }
        ],
    }


def gcp_condition(repo: str, repo_id=None, branch=None, tag=None, environment=None, pull_request=False) -> str:
    parts = [f"assertion.repository_id == '{repo_id}'" if repo_id else f"assertion.repository == '{repo}'"]
    if environment:
        parts.append(f"assertion.environment == '{environment}'")
    elif branch:
        parts.append(f"assertion.ref == 'refs/heads/{branch}'")
    elif tag:
        if "*" in tag:
            prefix = tag.split("*", 1)[0]
            parts.append(f"assertion.ref.startsWith('refs/tags/{prefix}')")
        else:
            parts.append(f"assertion.ref == 'refs/tags/{tag}'")
    elif pull_request:
        parts.append("assertion.event_name == 'pull_request'")
    return " && ".join(parts)


def azure_credential(sub: str, name: str) -> dict:
    return {
        "name": name,
        "issuer": ISSUER,
        "subject": sub,
        "description": f"GitHub Actions OIDC for {sub}",
        "audiences": ["api://AzureADTokenExchange"],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Print OIDC trust settings for GitHub Actions (AWS, GCP, Azure).")
    p.add_argument("provider", choices=["aws", "gcp", "azure"])
    p.add_argument("--repo", required=True, help="OWNER/REPO (no wildcards)")
    scope = p.add_mutually_exclusive_group(required=True)
    scope.add_argument("--branch", help="trust only this branch, e.g. main")
    scope.add_argument("--tag", help="trust tags, e.g. v1.2.3 or 'v*' (AWS StringLike / GCP startsWith)")
    scope.add_argument("--environment", help="trust only jobs that use this GitHub environment (recommended)")
    scope.add_argument("--pull-request", action="store_true", help="trust pull_request runs (read-only roles only!)")
    p.add_argument("--account", help="AWS account id (12 digits), required for aws")
    p.add_argument("--repo-id", help="numeric repository id for GCP conditions (survives renames)")
    p.add_argument("--name", default="github-actions", help="Azure federated credential name")
    p.add_argument("--json", action="store_true", help="print only the JSON/condition, no explanation")
    args = p.parse_args(argv)

    if "*" in args.repo or not REPO_RE.match(args.repo):
        print("error: --repo must be an exact OWNER/REPO; wildcards would trust other repositories", file=sys.stderr)
        return 2
    if args.provider == "aws" and not (args.account and ACCOUNT_RE.match(args.account)):
        print("error: aws needs --account with a 12-digit account id", file=sys.stderr)
        return 2
    if args.provider == "azure" and args.tag and "*" in args.tag:
        print(
            "error: Azure federated credentials match the subject exactly; use one tag or an environment",
            file=sys.stderr,
        )
        return 2
    sub = subject(args.repo, args.branch, args.tag, args.environment, args.pull_request)
    warn = []
    if args.pull_request:
        warn.append("pull_request tokens come from code anyone can propose; grant read-only permissions only")
    if args.branch and args.branch != args.branch.strip("*"):
        warn.append("branch wildcards trust any matching branch anyone with push access can create")

    if args.provider == "aws":
        doc = aws_policy(args.account, sub)
        if args.json:
            print(json.dumps(doc, indent=2))
            return 0
        print("# IAM role trust policy (aws iam create-role --assume-role-policy-document file://trust.json)")
        print(json.dumps(doc, indent=2))
        print(
            "\n# Workflow step:\n"
            "#   permissions: {id-token: write, contents: read}\n"
            "#   - uses: aws-actions/configure-aws-credentials@<sha> # v6\n"
            "#     with:\n"
            f"#       role-to-assume: arn:aws:iam::{args.account}:role/<role-name>\n"
            "#       aws-region: <region>"
        )
    elif args.provider == "gcp":
        cond = gcp_condition(args.repo, args.repo_id, args.branch, args.tag, args.environment, args.pull_request)
        if args.json:
            print(json.dumps({"attribute_condition": cond, "subject": sub}, indent=2))
            return 0
        print("# Workload Identity Pool provider (review, then run yourself):")
        print(
            "gcloud iam workload-identity-pools providers create-oidc github \\\n"
            "  --location=global --workload-identity-pool=<pool> \\\n"
            f"  --issuer-uri={ISSUER} \\\n"
            '  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,'
            'attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref" \\\n'
            f'  --attribute-condition="{cond}"'
        )
        print(
            "\n# Workflow step:\n"
            "#   permissions: {id-token: write, contents: read}\n"
            "#   - uses: google-github-actions/auth@<sha> # v3\n"
            "#     with:\n"
            "#       workload_identity_provider: projects/<number>/locations/global/\n"
            "#         workloadIdentityPools/<pool>/providers/github   (one line)\n"
            "#       service_account: <sa>@<project>.iam.gserviceaccount.com   # or direct resource access"
        )
    else:
        doc = azure_credential(sub, args.name)
        if args.json:
            print(json.dumps(doc, indent=2))
            return 0
        print("# Federated credential (az ad app federated-credential create --id <app-id> --parameters cred.json)")
        print(json.dumps(doc, indent=2))
        print(
            "\n# Workflow step:\n"
            "#   permissions: {id-token: write, contents: read}\n"
            "#   - uses: azure/login@<sha> # v3\n"
            "#     with:\n"
            "#       client-id: ${{ vars.AZURE_CLIENT_ID }}\n"
            "#       tenant-id: ${{ vars.AZURE_TENANT_ID }}\n"
            "#       subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}"
        )
    print(f"\n# Trusted subject: {sub}")
    for w in warn:
        print(f"# WARNING: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
