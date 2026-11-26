#!/usr/bin/env python3
"""Audit GitHub Actions workflow YAML for common security problems (read-only, offline).

Checks:
  action.unpinned          uses: owner/repo@tag or @branch instead of a full commit SHA
  action.docker_unpinned   uses: docker://image:tag without an @sha256 digest
  permissions.missing      no top-level permissions and a job without its own
  permissions.write_all    permissions: write-all (workflow or job)
  permissions.broad        write scopes granted at workflow level (prefer per job)
  prt.checkout_pr_code     pull_request_target / workflow_run checking out or running PR code
  prt.trigger              pull_request_target present (review it)
  injection.run            untrusted ${{ github.event.* }} / github.head_ref inside run:
  injection.script         the same inside actions/github-script `script:`
  injection.input          ${{ inputs.* }} / step outputs inside run: (lower risk)
  secrets.workflow_env     ${{ secrets.* }} in workflow-level env (visible to every step)
  secrets.inherit          secrets: inherit passed to a reusable workflow
  runner.self_hosted       self-hosted runner (high with --public)
  commands.unsecure        ACTIONS_ALLOW_UNSECURE_COMMANDS enabled

Needs PyYAML (pip install pyyaml). Never prints secret values; only names and locations.
Exit codes: 0 = no findings at/above --fail-on, 1 = findings, 2 = error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITIES = ["info", "low", "medium", "high", "critical"]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXPR_RE = re.compile(r"\$\{\{(.*?)\}\}", re.S)
FIRST_PARTY = {"actions", "github"}
BRANCH_REFS = {"main", "master", "develop", "dev", "trunk", "head", "latest", "nightly", "edge"}
UNTRUSTED = [
    r"github\.event\.issue\.(title|body)",
    r"github\.event\.pull_request\.(title|body)",
    r"github\.event\.pull_request\.head\.(ref|label|repo\.default_branch)",
    r"github\.event\.(comment|review|review_comment)\.body",
    r"github\.event\.discussion\.(title|body)",
    r"github\.event\.pages\.[^.\s]+\.page_name",
    r"github\.event\.commits\.[^.\s]+\.(message|author\.(email|name))",
    r"github\.event\.commits\b",
    r"github\.event\.head_commit\.(message|author\.(email|name))",
    r"github\.event\.workflow_run\.(head_branch|display_title|head_commit\.(message|author\.(email|name)))",
    r"github\.head_ref",
]
UNTRUSTED_RE = re.compile("|".join(f"(?:{p})" for p in UNTRUSTED))
LOW_TRUST_RE = re.compile(r"\binputs\.|\bsteps\.[^.]+\.outputs\.|\bneeds\.[^.]+\.outputs\.")
PR_CODE_REF_RE = re.compile(
    r"github\.event\.pull_request\.head\.(sha|ref)|github\.head_ref|"
    r"github\.event\.workflow_run\.head_(sha|branch)|refs/pull/|github\.event\.number"
)
PR_CODE_RUN_RE = re.compile(r"gh pr checkout|git fetch[^\n]*pull/|git checkout[^\n]*pull/")


def load_yaml_module():
    try:
        import yaml
    except ImportError:
        print("error: PyYAML is required: pip install pyyaml", file=sys.stderr)
        raise SystemExit(2) from None
    return yaml


def load_workflow(text: str):
    yaml = load_yaml_module()
    data = yaml.safe_load(text)
    if isinstance(data, dict) and True in data and "on" not in data:
        data["on"] = data.pop(True)  # YAML 1.1 reads the bare key `on` as boolean true
    return data


def triggers(wf: dict) -> set[str]:
    on = wf.get("on")
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    if isinstance(on, dict):
        return {str(k) for k in on}
    return set()


class Locator:
    """Best-effort line numbers: find the first line containing a needle after the last hit."""

    def __init__(self, text: str):
        self.lines = text.splitlines()
        self.pos: dict[str, int] = {}

    def find(self, needle: str) -> int | None:
        needle = needle.strip().splitlines()[0] if needle.strip() else needle
        start = self.pos.get(needle, 0)
        for i in range(start, len(self.lines)):
            if needle in self.lines[i]:
                self.pos[needle] = i + 1
                return i + 1
        return None


def finding(check, severity, path, line, job, title, fix):
    return {
        "check": check,
        "severity": severity,
        "file": str(path),
        "line": line,
        "job": job,
        "title": title,
        "fix": fix,
    }


def check_uses(uses: str, path, loc, job, strict: bool) -> list[dict]:
    out = []
    uses = str(uses).strip()
    if uses.startswith("./") or uses.startswith(".\\"):
        return out
    line = loc.find(uses)
    if uses.startswith("docker://"):
        if "@sha256:" not in uses:
            out.append(
                finding(
                    "action.docker_unpinned",
                    "medium",
                    path,
                    line,
                    job,
                    f"{uses} is pinned by tag, not digest",
                    "pin the image by digest: docker://image@sha256:<digest>",
                )
            )
        return out
    if "@" not in uses:
        out.append(
            finding("action.unpinned", "high", path, line, job, f"{uses} has no ref", "pin to a full commit SHA")
        )
        return out
    name, ref = uses.rsplit("@", 1)
    if SHA_RE.match(ref):
        return out
    owner = name.split("/", 1)[0].lower()
    is_branch = ref.lower() in BRANCH_REFS
    if is_branch:
        sev = "high"
        title = f"{uses} follows a branch; any push to it changes your workflow"
    elif owner in FIRST_PARTY and not strict:
        sev = "low"
        title = f"{uses} is pinned by tag (first-party action)"
    else:
        sev = "high"
        title = f"{uses} is pinned by a mutable tag, not a commit SHA"
    out.append(
        finding(
            "action.unpinned",
            sev,
            path,
            line,
            job,
            title,
            f"use {name}@<40-char-sha> # {ref} (dependabot-and-pinning skill converts tags offline)",
        )
    )
    return out


def expressions(text: str) -> list[str]:
    return [m.strip() for m in EXPR_RE.findall(text or "")]


def check_permissions(wf, path, loc) -> list[dict]:
    out = []
    jobs = wf.get("jobs") or {}
    top = wf.get("permissions", None)
    if top == "write-all":
        out.append(
            finding(
                "permissions.write_all",
                "high",
                path,
                loc.find("permissions:"),
                None,
                "workflow grants permissions: write-all to GITHUB_TOKEN",
                "set `permissions: contents: read` at the top and grant writes per job",
            )
        )
    elif isinstance(top, dict):
        writes = sorted(k for k, v in top.items() if str(v) == "write")
        if writes and len(jobs) > 1:
            out.append(
                finding(
                    "permissions.broad",
                    "low",
                    path,
                    loc.find("permissions:"),
                    None,
                    f"write scopes at workflow level apply to all {len(jobs)} jobs: {', '.join(writes)}",
                    "move write scopes to the jobs that need them",
                )
            )
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        jp = job.get("permissions", None)
        if jp == "write-all":
            out.append(
                finding(
                    "permissions.write_all",
                    "high",
                    path,
                    loc.find(f"{job_id}:"),
                    job_id,
                    "job grants permissions: write-all",
                    "list only the scopes the job needs",
                )
            )
        if top is None and jp is None and "uses" not in job:
            out.append(
                finding(
                    "permissions.missing",
                    "medium",
                    path,
                    loc.find(f"{job_id}:"),
                    job_id,
                    "no permissions block: GITHUB_TOKEN gets the repository/org default (may be read-write)",
                    "add top-level `permissions: contents: read` and per-job grants",
                )
            )
    return out


def audit_text(text: str, path="workflow.yml", public: bool = False, strict: bool = False) -> list[dict]:
    wf = load_workflow(text)
    if not isinstance(wf, dict) or "jobs" not in wf:
        return []
    loc = Locator(text)
    out: list[dict] = []
    trig = triggers(wf)
    privileged = bool(trig & {"pull_request_target", "workflow_run"})
    if "pull_request_target" in trig:
        out.append(
            finding(
                "prt.trigger",
                "info",
                path,
                loc.find("pull_request_target"),
                None,
                "pull_request_target runs with a write token and secrets on fork PRs",
                "never build or run PR code in this workflow; use pull_request for CI",
            )
        )
    out += check_permissions(wf, path, loc)

    wf_env = wf.get("env") or {}
    if isinstance(wf_env, dict):
        for key, val in wf_env.items():
            if "secrets." in str(val):
                out.append(
                    finding(
                        "secrets.workflow_env",
                        "medium",
                        path,
                        loc.find(f"{key}:"),
                        None,
                        f"secret in workflow-level env {key}: every step and action in every job can read it",
                        "pass the secret only to the step that needs it (step-level env or with:)",
                    )
                )
            if key == "ACTIONS_ALLOW_UNSECURE_COMMANDS" and str(val).lower() == "true":
                out.append(
                    finding(
                        "commands.unsecure",
                        "high",
                        path,
                        loc.find(key),
                        None,
                        "ACTIONS_ALLOW_UNSECURE_COMMANDS re-enables set-env/add-path injection",
                        "remove it; write to $GITHUB_ENV / $GITHUB_PATH",
                    )
                )

    for job_id, job in (wf.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        if "uses" in job:
            out += check_uses(job["uses"], path, loc, job_id, strict)
            if job.get("secrets") == "inherit":
                out.append(
                    finding(
                        "secrets.inherit",
                        "low",
                        path,
                        loc.find("secrets: inherit"),
                        job_id,
                        "secrets: inherit passes every secret to the called workflow",
                        "pass only the named secrets the called workflow declares",
                    )
                )
        runs_on = job.get("runs-on")
        labels = []
        if isinstance(runs_on, str):
            labels = [runs_on]
        elif isinstance(runs_on, list):
            labels = [str(x) for x in runs_on]
        elif isinstance(runs_on, dict):
            labels = [str(x) for x in (runs_on.get("labels") or [])]
            if runs_on.get("group"):
                labels.append("self-hosted")
        if any("self-hosted" in lab for lab in labels):
            if public:
                sev, why = "high", "public repository: fork pull requests can run code on this machine"
            elif trig & {"pull_request", "pull_request_target", "issue_comment"}:
                sev, why = "medium", "triggered by pull requests; if the repo is or becomes public, forks run here"
            else:
                sev, why = "info", "self-hosted runner: keep it ephemeral and the repo private"
            out.append(
                finding(
                    "runner.self_hosted",
                    sev,
                    path,
                    loc.find("self-hosted"),
                    job_id,
                    f"self-hosted runner ({why})",
                    "use GitHub-hosted runners for public repos, or ephemeral/JIT runners in a restricted group",
                )
            )
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            with_ = step.get("with") or {}
            if uses:
                out += check_uses(uses, path, loc, job_id, strict)
                if (
                    privileged
                    and str(uses).startswith("actions/checkout")
                    and PR_CODE_REF_RE.search(str(with_.get("ref", "")))
                ):
                    out.append(
                        finding(
                            "prt.checkout_pr_code",
                            "critical",
                            path,
                            loc.find("ref:"),
                            job_id,
                            "privileged trigger checks out untrusted PR code (pwn request)",
                            "split into pull_request (build, no secrets) + workflow_run that only reads artifacts",
                        )
                    )
                if str(uses).startswith("actions/github-script"):
                    for expr in expressions(str(with_.get("script", ""))):
                        if UNTRUSTED_RE.search(expr):
                            out.append(
                                finding(
                                    "injection.script",
                                    "high",
                                    path,
                                    loc.find(expr),
                                    job_id,
                                    f"untrusted `${{{{ {expr} }}}}` interpolated into github-script code",
                                    "read it from context.payload in the script, or pass it via env",
                                )
                            )
            run = step.get("run")
            if run:
                run = str(run)
                if privileged and PR_CODE_RUN_RE.search(run):
                    out.append(
                        finding(
                            "prt.checkout_pr_code",
                            "high",
                            path,
                            loc.find(PR_CODE_RUN_RE.search(run).group(0)),
                            job_id,
                            "privileged trigger fetches PR code in a run step",
                            "do not fetch or execute PR code with secrets or a write token",
                        )
                    )
                for expr in expressions(run):
                    if UNTRUSTED_RE.search(expr):
                        out.append(
                            finding(
                                "injection.run",
                                "high",
                                path,
                                loc.find(expr),
                                job_id,
                                f"script injection: `${{{{ {expr} }}}}` is attacker-controlled text inside run:",
                                'move it to step env (e.g. TITLE: ${{ ... }}) and use "$TITLE" in the script',
                            )
                        )
                    elif LOW_TRUST_RE.search(expr):
                        out.append(
                            finding(
                                "injection.input",
                                "low",
                                path,
                                loc.find(expr),
                                job_id,
                                f"`${{{{ {expr} }}}}` interpolated into run: (safe only if the value is trusted)",
                                "pass it via env and quote it",
                            )
                        )
    return out


def collect(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            wf_dir = p / ".github" / "workflows"
            base = wf_dir if wf_dir.is_dir() else p
            files += sorted(x for x in base.rglob("*") if x.suffix in (".yml", ".yaml") and x.is_file())
        elif p.is_file():
            files.append(p)
        else:
            raise FileNotFoundError(raw)
    return files


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Audit GitHub Actions workflows for security problems.")
    p.add_argument("paths", nargs="+", help="workflow files, .github/workflows, or a repository root")
    p.add_argument("--json", action="store_true", help="print JSON")
    p.add_argument("--public", action="store_true", help="the repository is public (raises self-hosted runner risk)")
    p.add_argument("--strict", action="store_true", help="treat tag-pinned first-party actions (actions/*) as high")
    p.add_argument("--fail-on", choices=SEVERITIES, default="medium", help="exit 1 at or above (default medium)")
    p.add_argument("--ignore", action="append", default=[], help="check id to skip (repeatable)")
    args = p.parse_args(argv)
    try:
        files = collect(args.paths)
    except FileNotFoundError as exc:
        print(f"error: no such file or directory: {exc}", file=sys.stderr)
        return 2
    findings: list[dict] = []
    errors: list[str] = []
    for f in files:
        try:
            findings += audit_text(f.read_text(encoding="utf-8"), f, args.public, args.strict)
        except Exception as exc:  # YAML errors, unreadable files
            errors.append(f"{f}: {exc.__class__.__name__}: {str(exc).splitlines()[0]}")
    findings = [x for x in findings if x["check"] not in args.ignore]
    findings.sort(key=lambda x: (-SEVERITIES.index(x["severity"]), x["file"], x["line"] or 0))
    counts = {s: sum(1 for x in findings if x["severity"] == s) for s in SEVERITIES}
    if args.json:
        print(json.dumps({"files": len(files), "counts": counts, "findings": findings, "errors": errors}, indent=2))
    else:
        for x in findings:
            where = f"{x['file']}:{x['line']}" if x["line"] else x["file"]
            job = f" [{x['job']}]" if x["job"] else ""
            print(f"{x['severity'].upper():8} {where}{job} {x['check']}: {x['title']}\n         -> {x['fix']}")
        for e in errors:
            print(f"ERROR    {e}", file=sys.stderr)
        summary = ", ".join(f"{counts[s]} {s}" for s in reversed(SEVERITIES) if counts[s])
        print(f"\n{len(files)} workflow file(s): {summary or 'no findings'}")
    if errors and not findings:
        return 2
    threshold = SEVERITIES.index(args.fail_on)
    return 1 if any(SEVERITIES.index(x["severity"]) >= threshold for x in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
