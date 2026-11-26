#!/usr/bin/env python3
"""Parse a downloaded GitHub Actions run log and explain the failure.

Accepts:
  * `gh run view RUN_ID --log` or `--log-failed` output (JOB<TAB>STEP<TAB>timestamp line)
  * the log archive from the web UI / REST API (zip, or the extracted folder of
    per-job / per-step .txt files)
  * any plain log text (timestamps are stripped)

Finds the first failing step, ##[error] lines and known error signatures (permissions,
OIDC, out of memory, disk full, timeouts, lockfile drift, missing modules, rate limits,
git auth, network, test failures, deprecated runtimes...) and prints a hint for each.
Offline and read-only; logs are already masked by GitHub, and this script prints only
short excerpts.

Exit codes: 0 = no error signatures found, 1 = errors found, 2 = unreadable input.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path

TS_RE = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ?")
GH_LINE_RE = re.compile(r"^([^\t]+)\t([^\t]*)\t(.*)$")
STEP_FILE_RE = re.compile(r"^(\d+)_(.+)\.txt$")

# (id, level, regex, hint)
SIGNATURES = [
    (
        "permissions",
        "error",
        r"Resource not accessible by integration",
        "GITHUB_TOKEN lacks a permission: add the scope to the job's permissions (contents/pull-requests/"
        "issues: write), or the run is from a fork (read-only token).",
    ),
    (
        "oidc.no_id_token",
        "error",
        r"ACTIONS_ID_TOKEN_REQUEST_URL|Could not load credentials from any providers",
        "the job has no `permissions: id-token: write` (or runs from a fork PR, which cannot get OIDC tokens).",
    ),
    (
        "oidc.aws_trust",
        "error",
        r"Not authorized to perform sts:AssumeRoleWithWebIdentity",
        "AWS trust policy does not match the token: compare `sub` (environment vs branch form) and aud "
        "sts.amazonaws.com.",
    ),
    (
        "oidc.azure_trust",
        "error",
        r"AADSTS70021|No matching federated identity record",
        "Azure federated credential subject does not match repo:OWNER/REPO:<environment|ref|pull_request>.",
    ),
    (
        "oom",
        "error",
        r"JavaScript heap out of memory|exit code 137|\bKilled\s*$|std::bad_alloc|\bMemoryError\b|"
        r"java\.lang\.OutOfMemoryError|The runner has received a shutdown signal",
        "out of memory: reduce parallel workers, set NODE_OPTIONS=--max-old-space-size, or use a larger runner.",
    ),
    (
        "disk_full",
        "error",
        r"No space left on device|ENOSPC",
        "runner disk full: delete unused toolchains (/usr/share/dotnet, /opt/ghc, android SDK), prune docker images.",
    ),
    (
        "timeout",
        "error",
        r"has exceeded the maximum execution time|exceeded the maximum execution time of",
        "job hit timeout-minutes: find the hanging step (waiting for input? service not ready?) or raise the limit.",
    ),
    (
        "cancelled",
        "warning",
        r"The operation was canceled|Canceling since a higher priority waiting request",
        "cancelled by concurrency (a newer run), a user, or fail-fast after another matrix job failed.",
    ),
    (
        "runner_lost",
        "error",
        r"lost communication with the server|The hosted runner encountered an error",
        "runner died (often memory/disk exhaustion or a self-hosted runner restart); re-run, then check resource use.",
    ),
    (
        "action_resolve",
        "error",
        r"Unable to resolve action|Can't find 'action\.ya?ml'|An action could not be found",
        "action reference is wrong: check owner/repo@ref spelling, that the SHA/tag exists, and that "
        "actions/checkout ran before a local ./ action.",
    ),
    (
        "input_required",
        "error",
        r"Input required and not supplied: ?(\S+)",
        "a required `with:` input is missing (often a secret that is empty in forks or in this environment).",
    ),
    (
        "bad_credentials",
        "error",
        r"Bad credentials|401 Unauthorized|authentication required|HTTP 401",
        "token invalid or empty: the secret is not set for this repo/environment, expired, or not passed to the step.",
    ),
    (
        "rate_limit",
        "error",
        r"API rate limit exceeded|secondary rate limit|toomanyrequests|pull rate limit",
        "rate limited: authenticate (GITHUB_TOKEN for the GitHub API, docker login for Docker Hub), cache, "
        "retry with backoff.",
    ),
    (
        "git_auth",
        "error",
        r"could not read Username for|Permission denied \(publickey\)|terminal prompts disabled|"
        r"Repository not found",
        "git cannot authenticate: private submodules/repos need a token or deploy key; check persist-credentials.",
    ),
    (
        "protected_branch",
        "error",
        r"GH006: Protected branch update failed|refusing to allow a GitHub App to create or "
        r"update workflow",
        "push blocked by branch protection or missing `workflows` permission; open a PR or use an app token.",
    ),
    (
        "network",
        "warning",
        r"ETIMEDOUT|ECONNRESET|Connection timed out|Temporary failure in name resolution|"
        r"Could not resolve host|getaddrinfo EAI_AGAIN|TLS handshake timeout",
        "network failure: transient (retry) or a firewall/proxy on self-hosted runners.",
    ),
    (
        "lockfile",
        "error",
        r"npm ci` can only install packages when|can only install packages when your package\.json "
        r"and package-lock\.json|lockfile would have been modified|frozen-lockfile|ERR_PNPM_OUTDATED_LOCKFILE|"
        r"poetry\.lock is not consistent|lock file is not up to date|uv\.lock.*(?:needs to be updated|out of date)",
        "lockfile out of sync with the manifest: run the install locally and commit the updated lockfile.",
    ),
    (
        "python_module",
        "error",
        r"ModuleNotFoundError: No module named '([^']+)'",
        "dependency not installed in this job (or wrong Python): install requirements before running.",
    ),
    (
        "pip_resolve",
        "error",
        r"Could not find a version that satisfies the requirement|ResolutionImpossible",
        "no matching package for this Python version/platform: check python-version and version pins.",
    ),
    (
        "npm_error",
        "error",
        r"^npm (?:ERR!|error) ",
        "npm failed: read the first npm error line (E404 = missing/private package, ERESOLVE = peer "
        "dependency conflict).",
    ),
    (
        "command_not_found",
        "error",
        r"command not found|is not recognized as an internal or external command",
        "tool not on PATH: install it or use the setup-* action; on Windows the default shell is pwsh.",
    ),
    ("exec_format", "error", r"exec format error", "binary built for another CPU architecture (arm64 vs x64 runner)."),
    (
        "shell_syntax",
        "error",
        r"syntax error near unexpected token|unexpected EOF while looking for matching|"
        r"ParserError:",
        "shell syntax error in run: - check quoting; an interpolated ${{ }} value may contain quotes.",
    ),
    (
        "permission_denied",
        "error",
        r"Permission denied(?! \(publickey\))|EACCES",
        "file not executable (git update-index --chmod=+x script.sh) or writing to a root-owned path.",
    ),
    (
        "service_unhealthy",
        "error",
        r"Failed to initialize container|unhealthy|service container .* failed",
        "service container did not become healthy: check image tag, required env (POSTGRES_PASSWORD), health-cmd.",
    ),
    (
        "matrix_empty",
        "error",
        r"Matrix must define at least one vector",
        "dynamic matrix produced []: guard the job with if: needs.x.outputs.list != '[]'.",
    ),
    (
        "artifact_missing",
        "error",
        r"Unable to download artifact|Artifact not found|No artifacts found",
        "artifact name/run mismatch, retention expired, or the upload job failed or was skipped.",
    ),
    (
        "tests_failed",
        "error",
        r"^FAILED [^\s]+|\b\d+ failed\b|Tests:\s+\d+ failed|^--- FAIL: |"
        r"^\s*\d+\) .+ \(\d+ms\)$",
        "tests failed: the lines above the summary name the failing tests; reproduce locally with the same versions.",
    ),
    (
        "deprecated_runtime",
        "warning",
        r"Node\.js \d+ actions are deprecated|Node\.js \d+ is deprecated|"
        r"`?(?:set-output|save-state)`? command is deprecated",
        "update the action to a version on a supported runtime; replace ::set-output with $GITHUB_OUTPUT.",
    ),
    (
        "cache_miss",
        "info",
        r"Cache not found for input keys",
        "cache miss (normal on first run or after the key changed); repeated misses mean the key changes every run.",
    ),
]
COMPILED = [(sid, lvl, re.compile(rx, re.M), hint) for sid, lvl, rx, hint in SIGNATURES]
EXIT_RE = re.compile(r"Process completed with exit code (\d+)")


def strip_ts(line: str) -> str:
    return TS_RE.sub("", line.rstrip("\r\n"))


def records_from_text(text: str, default_job: str = "", default_step: str = "") -> list[dict]:
    """Return [{job, step, line}] with step boundaries detected from ##[group]Run markers."""
    out = []
    step = default_step
    for raw in text.splitlines():
        m = GH_LINE_RE.match(raw)
        if m and TS_RE.match(m.group(3)):
            out.append({"job": m.group(1), "step": m.group(2), "line": strip_ts(m.group(3))})
            continue
        line = strip_ts(raw)
        if line.startswith("##[group]Run "):
            step = line[len("##[group]Run ") :].strip()[:80]
        out.append({"job": default_job, "step": step, "line": line})
    return out


def read_input(path: str) -> list[dict]:
    if path == "-":
        return records_from_text(sys.stdin.read())
    p = Path(path)
    if p.is_dir():
        return records_from_dir(p)
    data = p.read_bytes()
    if zipfile.is_zipfile(io.BytesIO(data)):
        return records_from_zip(zipfile.ZipFile(io.BytesIO(data)))
    return records_from_text(data.decode("utf-8", errors="replace"))


def _job_step(parts: list[str]) -> tuple[str, str]:
    """Map archive paths (job/1_Step.txt or 0_job.txt) to job and step names."""
    if len(parts) >= 2:
        job = parts[-2]
        m = STEP_FILE_RE.match(parts[-1])
        return job, (m.group(2) if m else parts[-1])
    m = STEP_FILE_RE.match(parts[-1])
    return (m.group(2) if m else parts[-1]), ""


def records_from_zip(zf: zipfile.ZipFile) -> list[dict]:
    names = sorted(n for n in zf.namelist() if n.endswith(".txt"))
    has_step_files = any("/" in n for n in names)
    out = []
    for n in names:
        if has_step_files and "/" not in n:
            continue  # top-level per-job files duplicate the per-step files
        job, step = _job_step(n.split("/"))
        out += records_from_text(zf.read(n).decode("utf-8", errors="replace"), job, step)
    return out


def records_from_dir(root: Path) -> list[dict]:
    files = sorted(p for p in root.rglob("*.txt"))
    has_step_files = any(p.parent != root for p in files)
    out = []
    for f in files:
        if has_step_files and f.parent == root:
            continue
        job, step = _job_step(list(f.relative_to(root).parts))
        out += records_from_text(f.read_text(encoding="utf-8", errors="replace"), job, step)
    return out


def analyse(records: list[dict], context: int = 3) -> dict:
    hits = []
    seen = set()
    first_error = None
    exit_codes = []
    for i, r in enumerate(records):
        line = r["line"]
        is_error_line = line.startswith("##[error]")
        if is_error_line and first_error is None:
            first_error = {
                "job": r["job"],
                "step": r["step"],
                "line": line[len("##[error]") :][:300],
                "context": [x["line"][:300] for x in records[max(0, i - context) : i]],
            }
        m = EXIT_RE.search(line)
        if m:
            exit_codes.append({"job": r["job"], "step": r["step"], "code": int(m.group(1))})
        text = line[len("##[error]") :] if is_error_line else line
        for sid, level, rx, hint in COMPILED:
            mm = rx.search(text)
            if not mm:
                continue
            key = (sid, r["job"])
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                {
                    "id": sid,
                    "level": level,
                    "job": r["job"],
                    "step": r["step"],
                    "match": text.strip()[:240],
                    "detail": mm.group(1) if mm.groups() and mm.group(1) else None,
                    "hint": hint,
                }
            )
    order = {"error": 0, "warning": 1, "info": 2}
    hits.sort(key=lambda h: order[h["level"]])
    jobs = sorted({r["job"] for r in records if r["job"]})
    return {
        "lines": len(records),
        "jobs": jobs,
        "first_error": first_error,
        "exit_codes": exit_codes,
        "signatures": hits,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Explain a failed GitHub Actions run from its downloaded log.",
        epilog="Get a log: gh run view RUN_ID --log-failed > run.log  (or download the log archive zip)",
    )
    p.add_argument("log", help="log file, log archive (.zip), extracted folder, or - for stdin")
    p.add_argument("--context", type=int, default=3, help="lines of context before the first error (default 3)")
    p.add_argument("--all", action="store_true", help="include info-level signatures in the text report")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    try:
        records = read_input(args.log)
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    res = analyse(records, args.context)
    errors = [h for h in res["signatures"] if h["level"] == "error"]
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"Parsed {res['lines']} lines, jobs: {', '.join(res['jobs']) or '(single log)'}")
        fe = res["first_error"]
        if fe:
            where = " / ".join(x for x in (fe["job"], fe["step"]) if x)
            print(f"\nFirst error{f' in {where}' if where else ''}:")
            for c in fe["context"]:
                print(f"    {c}")
            print(f"  > {fe['line']}")
        for ec in res["exit_codes"]:
            if ec["code"] != 0:
                where = " / ".join(x for x in (ec["job"], ec["step"]) if x)
                print(f"\nExit code {ec['code']}{f' ({where})' if where else ''}")
                break
        shown = [h for h in res["signatures"] if args.all or h["level"] != "info"]
        if shown:
            print("\nDiagnosis:")
            for h in shown:
                where = " / ".join(x for x in (h["job"], h["step"]) if x)
                print(f"  {h['level'].upper():7} {h['id']}{f' [{where}]' if where else ''}: {h['match']}")
                print(f"          -> {h['hint']}")
        elif not fe:
            print("\nNo known error signatures found. Read the last 50 lines of the failing step.")
    return 1 if errors or res["first_error"] else 0


if __name__ == "__main__":
    sys.exit(main())
