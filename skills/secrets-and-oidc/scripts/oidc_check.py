#!/usr/bin/env python3
"""Find long-lived cloud credentials in GitHub Actions workflows and check OIDC setup.

Checks:
  keys.long_lived          AWS access keys, GCP service-account JSON keys, Azure client
                           secrets / AZURE_CREDENTIALS used from secrets or action inputs
  oidc.missing_id_token    a job authenticates with OIDC but has no `id-token: write`
  oidc.workflow_level      id-token: write granted at workflow level to several jobs
  oidc.no_environment      a job assumes a cloud role without `environment:` (trust is
                           then scoped only by branch/ref)
  secrets.in_run           ${{ secrets.X }} interpolated directly into a run: script

Only names are reported, never values. Needs PyYAML. Read-only, offline.
Exit codes: 0 = nothing at/above --fail-on, 1 = findings, 2 = error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITIES = ["info", "low", "medium", "high"]
KEY_SECRET_RE = re.compile(
    r"secrets\.("
    r"AWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SECRET_KEY)\w*|"
    r"\w*(?:GCP|GCLOUD|GOOGLE)\w*(?:SA_KEY|CREDENTIALS|KEY_JSON|SERVICE_ACCOUNT\w*)|"
    r"\w*SERVICE_ACCOUNT_KEY\w*|"
    r"AZURE_CREDENTIALS\w*|AZURE_CLIENT_SECRET\w*|ARM_CLIENT_SECRET\w*"
    r")",
    re.I,
)
EXPR_SECRET_RE = re.compile(r"\$\{\{\s*secrets\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def load_workflow(text: str):
    try:
        import yaml
    except ImportError:
        print("error: PyYAML is required: pip install pyyaml", file=sys.stderr)
        raise SystemExit(2) from None
    data = yaml.safe_load(text)
    if isinstance(data, dict) and True in data and "on" not in data:
        data["on"] = data.pop(True)
    return data


def oidc_usage(step: dict) -> str | None:
    """Return the provider name when a step authenticates with OIDC."""
    uses = str(step.get("uses", "")).split("@", 1)[0].lower()
    w = step.get("with") or {}
    if uses == "aws-actions/configure-aws-credentials" and w.get("role-to-assume") and not w.get("aws-access-key-id"):
        return "aws"
    if uses == "google-github-actions/auth" and w.get("workload_identity_provider"):
        return "gcp"
    if uses == "azure/login" and w.get("client-id") and not w.get("creds"):
        return "azure"
    if uses == "hashicorp/vault-action" and str(w.get("method", "")).lower() == "jwt":
        return "vault"
    if uses in ("actions/attest", "actions/attest-build-provenance", "sigstore/cosign-installer"):
        return "sigstore"
    if "ACTIONS_ID_TOKEN_REQUEST" in json.dumps(step):
        return "custom"
    return None


def long_lived_inputs(step: dict) -> list[str]:
    uses = str(step.get("uses", "")).split("@", 1)[0].lower()
    w = step.get("with") or {}
    found = []
    if uses == "aws-actions/configure-aws-credentials" and w.get("aws-access-key-id"):
        found.append("aws-actions/configure-aws-credentials with aws-access-key-id")
    if uses == "google-github-actions/auth" and w.get("credentials_json"):
        found.append("google-github-actions/auth with credentials_json")
    if uses == "azure/login" and w.get("creds"):
        found.append("azure/login with creds (client secret JSON)")
    return found


def perm(perms, key: str) -> str | None:
    if perms == "write-all":
        return "write"
    if perms == "read-all":
        return "read"
    if isinstance(perms, dict):
        v = perms.get(key)
        return str(v) if v is not None else "none"
    return None  # not set


def check(wf: dict, path: str) -> list[dict]:
    out = []

    def add(check_id, severity, job, title, fix):
        out.append({"check": check_id, "severity": severity, "file": path, "job": job, "title": title, "fix": fix})

    top_perms = wf.get("permissions")
    jobs = wf.get("jobs") or {}
    if perm(top_perms, "id-token") == "write" and len(jobs) > 1:
        add(
            "oidc.workflow_level",
            "low",
            None,
            f"id-token: write at workflow level reaches all {len(jobs)} jobs",
            "grant id-token: write only in the deploy job",
        )
    top_env_text = json.dumps(wf.get("env") or {})
    reported_keys: set[tuple] = set()
    for name in sorted(set(KEY_SECRET_RE.findall(top_env_text))):
        reported_keys.add((None, name))
        add(
            "keys.long_lived",
            "high",
            None,
            f"long-lived cloud credential secrets.{name} in workflow env",
            "replace with OIDC (see references/oidc-setup.md) and delete the key",
        )
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_text = json.dumps(job, default=str)
        for name in sorted(set(KEY_SECRET_RE.findall(job_text))):
            if (None, name) in reported_keys:
                continue
            add(
                "keys.long_lived",
                "high",
                job_id,
                f"long-lived cloud credential secrets.{name}",
                "replace with OIDC role/workload identity federation, then revoke the key",
            )
        providers = set()
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            for desc in long_lived_inputs(step):
                add(
                    "keys.long_lived",
                    "high",
                    job_id,
                    f"{desc}: static key instead of OIDC",
                    "use role-to-assume / workload_identity_provider / client-id+tenant-id+subscription-id",
                )
            prov = oidc_usage(step)
            if prov:
                providers.add(prov)
            run = step.get("run")
            if run:
                for name in sorted(set(EXPR_SECRET_RE.findall(str(run)))):
                    add(
                        "secrets.in_run",
                        "medium",
                        job_id,
                        f"secrets.{name} interpolated into run: (ends up in the script file; leaks with set -x)",
                        f'env: {{{name}: ${{{{ secrets.{name} }}}}}} and use "${name}"',
                    )
        if providers:
            job_perm = perm(job.get("permissions"), "id-token")
            effective = job_perm if job_perm is not None else perm(top_perms, "id-token")
            if effective != "write":
                add(
                    "oidc.missing_id_token",
                    "high",
                    job_id,
                    f"job uses OIDC ({', '.join(sorted(providers))}) but has no id-token: write",
                    "permissions: {id-token: write, contents: read} on this job",
                )
            cloud = providers & {"aws", "gcp", "azure", "vault"}
            if cloud and not job.get("environment"):
                add(
                    "oidc.no_environment",
                    "info",
                    job_id,
                    f"{', '.join(sorted(cloud))} role assumed without an environment",
                    "use environment: production and trust sub repo:OWNER/REPO:environment:production",
                )
    return out


def collect(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            base = p / ".github" / "workflows" if (p / ".github" / "workflows").is_dir() else p
            files += sorted(x for x in base.rglob("*") if x.suffix in (".yml", ".yaml"))
        elif p.is_file():
            files.append(p)
        else:
            raise FileNotFoundError(raw)
    return files


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Find long-lived cloud keys and check OIDC in GitHub Actions workflows.")
    p.add_argument("paths", nargs="+", help="workflow files, .github/workflows, or a repository root")
    p.add_argument("--fail-on", choices=SEVERITIES, default="medium", help="exit 1 at or above (default medium)")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    try:
        files = collect(args.paths)
    except FileNotFoundError as exc:
        print(f"error: no such file or directory: {exc}", file=sys.stderr)
        return 2
    findings: list[dict] = []
    errors = []
    for f in files:
        try:
            wf = load_workflow(f.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{f}: {str(exc).splitlines()[0]}")
            continue
        if isinstance(wf, dict) and "jobs" in wf:
            findings += check(wf, str(f))
    findings.sort(key=lambda x: (-SEVERITIES.index(x["severity"]), x["file"]))
    if args.json:
        print(json.dumps({"files": len(files), "findings": findings, "errors": errors}, indent=2))
    else:
        for x in findings:
            job = f" [{x['job']}]" if x["job"] else ""
            print(f"{x['severity'].upper():7} {x['file']}{job} {x['check']}: {x['title']}\n        -> {x['fix']}")
        for e in errors:
            print(f"ERROR   {e}", file=sys.stderr)
        print(f"\n{len(files)} workflow file(s), {len(findings)} finding(s)")
    if errors and not findings:
        return 2
    t = SEVERITIES.index(args.fail_on)
    return 1 if any(SEVERITIES.index(x["severity"]) >= t for x in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
