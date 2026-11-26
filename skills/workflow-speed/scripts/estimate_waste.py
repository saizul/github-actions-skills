#!/usr/bin/env python3
"""Find speed problems in a GitHub Actions workflow and estimate wasted runner minutes.

Two inputs, use either or both:
  --workflow FILE   static checks: concurrency, caching, path filters, duplicate push/PR
                    triggers, matrix size, missing timeouts, expensive runner OS
  --runs FILE       run history as JSON from
                    gh run list --workflow ci.yml --limit 200 --json \\
                      databaseId,workflowName,event,status,conclusion,headBranch,headSha,\\
                      createdAt,startedAt,updatedAt
                    Optional per-run "jobs": [{"startedAt": ..., "completedAt": ...}] (from
                    gh run view ID --json jobs) gives billed minutes per job instead of wall time.

Waste = minutes of runs superseded by a newer run on the same branch (concurrency with
cancel-in-progress would have stopped them) + cancelled runs + duplicate push/pull_request
runs of the same commit. Read-only and offline. --workflow needs PyYAML.
Exit codes: 0 = ok, 1 = findings at/above --fail-on or waste >= --max-waste-pct, 2 = error.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from datetime import datetime
from pathlib import Path

SEVERITIES = ["info", "low", "medium", "high"]
CACHE_INPUTS = {
    "actions/setup-node": ("cache", "npm  # or pnpm / yarn"),
    "actions/setup-python": ("cache", "pip  # or pipenv / poetry"),
    "actions/setup-java": ("cache", "maven  # or gradle / sbt"),
    "ruby/setup-ruby": ("bundler-cache", "true"),
    "actions/setup-dotnet": ("cache", "true"),
}
OS_MULTIPLIER = {"windows": 2, "macos": 10}


# ---------------------------------------------------------------- workflow (static)


def load_workflow(text: str):
    try:
        import yaml
    except ImportError:
        print("error: PyYAML is required for --workflow: pip install pyyaml", file=sys.stderr)
        raise SystemExit(2) from None
    data = yaml.safe_load(text)
    if isinstance(data, dict) and True in data and "on" not in data:
        data["on"] = data.pop(True)
    return data


def trigger_map(wf: dict) -> dict:
    on = wf.get("on")
    if isinstance(on, str):
        return {on: {}}
    if isinstance(on, list):
        return {str(x): {} for x in on}
    if isinstance(on, dict):
        return {str(k): (v or {}) for k, v in on.items()}
    return {}


def expand_matrix(matrix) -> list[dict] | None:
    """GitHub matrix semantics: product, then exclude, then include. None if dynamic."""
    if not isinstance(matrix, dict):
        return None if matrix else [{}]
    base = {k: v for k, v in matrix.items() if k not in ("include", "exclude")}
    for v in base.values():
        if not isinstance(v, list):
            return None
    keys = list(base)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*(base[k] for k in keys))] if keys else []
    for ex in matrix.get("exclude") or []:
        if isinstance(ex, dict):
            combos = [c for c in combos if not all(c.get(k) == v for k, v in ex.items())]
    includes = matrix.get("include") or []
    if not isinstance(includes, list):
        return None
    originals = list(combos)
    for inc in includes:
        if not isinstance(inc, dict):
            continue
        matched = False
        for c in originals:
            if all(c.get(k) == v for k, v in inc.items() if k in base):
                matched = True
                for k, v in inc.items():
                    if k not in base:
                        c[k] = v
        if not matched:
            combos.append(dict(inc))
    return combos


def job_count(wf: dict) -> int:
    total = 0
    for job in (wf.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        combos = expand_matrix((job.get("strategy") or {}).get("matrix"))
        total += len(combos) if combos else 1
    return max(total, 1)


def static_findings(wf: dict, max_matrix: int = 12) -> list[dict]:
    out = []

    def add(check, severity, job, title, fix):
        out.append({"check": check, "severity": severity, "job": job, "title": title, "fix": fix})

    trig = trigger_map(wf)
    jobs = wf.get("jobs") or {}
    ci_trig = {"push", "pull_request"} & set(trig)
    conc = wf.get("concurrency")
    job_conc = any(isinstance(j, dict) and j.get("concurrency") for j in jobs.values())
    if ci_trig and not conc and not job_conc:
        add(
            "speed.no_concurrency",
            "medium",
            None,
            "no concurrency group: every push to a PR branch keeps the older runs going",
            "concurrency: {group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true}",
        )
    elif isinstance(conc, dict) and not conc.get("cancel-in-progress"):
        add(
            "speed.no_cancel",
            "low",
            None,
            "concurrency group without cancel-in-progress queues runs instead of cancelling",
            "cancel-in-progress: ${{ github.event_name == 'pull_request' }} (keep main runs)",
        )
    if "push" in trig and "pull_request" in trig:
        push = trig["push"] if isinstance(trig["push"], dict) else {}
        if not push.get("branches") and not push.get("tags") and not push.get("branches-ignore"):
            add(
                "speed.duplicate_triggers",
                "medium",
                None,
                "push (all branches) + pull_request: every PR commit runs twice",
                "limit push to the default branch: push: {branches: [main]}",
            )
    for name in sorted(ci_trig):
        cfg = trig[name] if isinstance(trig[name], dict) else {}
        if not cfg.get("paths") and not cfg.get("paths-ignore"):
            add(
                "speed.no_path_filter",
                "info",
                None,
                f"{name} has no paths/paths-ignore: docs-only changes run the full pipeline",
                "paths-ignore: ['**.md', 'docs/**'] (careful with required checks; see references)",
            )
    for job_id, job in jobs.items():
        if not isinstance(job, dict) or "uses" in job:
            continue
        steps = [s for s in job.get("steps") or [] if isinstance(s, dict)]
        uses_list = [str(s.get("uses", "")) for s in steps]
        has_cache_action = any(u.startswith(("actions/cache", "actions/cache/restore")) for u in uses_list)
        for s in steps:
            u = str(s.get("uses", ""))
            action = u.split("@", 1)[0]
            key, example = CACHE_INPUTS.get(action, (None, None))
            with_ = s.get("with") or {}
            if key and not with_.get(key) and not has_cache_action:
                add(
                    "speed.no_cache",
                    "medium",
                    job_id,
                    f"{action} without `{key}`: dependencies download on every run",
                    f"with: {key}: {example}",
                )
            if action == "actions/setup-go" and str(with_.get("cache", "")).lower() == "false":
                add("speed.no_cache", "medium", job_id, "setup-go cache disabled", "remove cache: false")
        strategy = job.get("strategy") or {}
        combos = expand_matrix(strategy.get("matrix"))
        if combos and len(combos) > max_matrix:
            add(
                "speed.matrix_size",
                "medium",
                job_id,
                f"matrix expands to {len(combos)} jobs",
                "test the full matrix on main/nightly; on PRs run a trimmed matrix (see references)",
            )
        if "timeout-minutes" not in job:
            add(
                "speed.no_timeout",
                "low",
                job_id,
                "no timeout-minutes: a hung job runs for the 360-minute default",
                "timeout-minutes: 2-3x the normal duration",
            )
        runs_on = str(job.get("runs-on", "")).lower()
        if "matrix." in runs_on:
            runs_on += " " + json.dumps(strategy.get("matrix"), default=str).lower()
        for os_name, mult in OS_MULTIPLIER.items():
            if os_name in runs_on:
                add(
                    "speed.expensive_os",
                    "info",
                    job_id,
                    f"{os_name} runner: {mult}x minute multiplier on private repositories",
                    "run only the OS-specific tests there; keep the rest on ubuntu",
                )
    return out


# ---------------------------------------------------------------- run history


def parse_time(value) -> datetime | None:
    if not value or str(value).startswith("0001-"):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


API_KEYS = {
    "id": "databaseId",
    "name": "workflowName",
    "head_branch": "headBranch",
    "head_sha": "headSha",
    "created_at": "createdAt",
    "run_started_at": "startedAt",
    "updated_at": "updatedAt",
    "started_at": "startedAt",
    "completed_at": "completedAt",
}


def normalise(obj: dict) -> dict:
    """Accept REST API snake_case fields (GET /repos/{o}/{r}/actions/runs) as well as gh --json."""
    out = dict(obj)
    for snake, camel in API_KEYS.items():
        if snake in obj and camel not in obj:
            out[camel] = obj[snake]
    if isinstance(out.get("jobs"), list):
        out["jobs"] = [normalise(j) if isinstance(j, dict) else j for j in out["jobs"]]
    return out


def billed_minutes(run: dict, jobs_per_run: int) -> float:
    jobs = run.get("jobs")
    if isinstance(jobs, list) and jobs:
        total = 0
        for j in jobs:
            s, e = parse_time(j.get("startedAt")), parse_time(j.get("completedAt"))
            if s and e and e > s:
                total += math.ceil((e - s).total_seconds() / 60)
        return float(total)
    s = parse_time(run.get("startedAt")) or parse_time(run.get("createdAt"))
    e = parse_time(run.get("updatedAt"))
    if not s or not e or e <= s:
        return 0.0
    return round((e - s).total_seconds() / 60 * jobs_per_run, 1)


def analyse_runs(runs: list[dict], jobs_per_run: int = 1) -> dict:
    rows = []
    runs = [normalise(r) for r in runs if isinstance(r, dict)]
    for r in runs:
        start = parse_time(r.get("startedAt")) or parse_time(r.get("createdAt"))
        end = parse_time(r.get("updatedAt"))
        if not start:
            continue
        rows.append(
            {
                "id": r.get("databaseId"),
                "workflow": r.get("workflowName") or r.get("name") or "",
                "event": r.get("event") or "",
                "branch": r.get("headBranch") or "",
                "sha": r.get("headSha") or "",
                "conclusion": r.get("conclusion") or "",
                "start": start,
                "end": end or start,
                "minutes": billed_minutes(r, jobs_per_run),
            }
        )
    total = sum(r["minutes"] for r in rows)
    cancelled = sum(r["minutes"] for r in rows if r["conclusion"] == "cancelled")
    superseded = 0.0
    superseded_ids = []
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        if r["event"] in ("push", "pull_request"):
            groups.setdefault((r["workflow"], r["branch"], r["event"]), []).append(r)
    for items in groups.values():
        items.sort(key=lambda x: x["start"])
        for cur, nxt in zip(items, items[1:]):
            if cur["conclusion"] == "cancelled" or nxt["start"] >= cur["end"]:
                continue
            span = (cur["end"] - cur["start"]).total_seconds()
            if span <= 0:
                continue
            frac = (cur["end"] - nxt["start"]).total_seconds() / span
            superseded += cur["minutes"] * frac
            superseded_ids.append(cur["id"])
    duplicate = 0.0
    duplicate_shas = []
    by_sha: dict[tuple, dict[str, list[dict]]] = {}
    for r in rows:
        if r["sha"] and r["event"] in ("push", "pull_request"):
            by_sha.setdefault((r["workflow"], r["sha"]), {}).setdefault(r["event"], []).append(r)
    for (_, sha), events in by_sha.items():
        if "push" in events and "pull_request" in events:
            duplicate += min(
                sum(x["minutes"] for x in events["push"]), sum(x["minutes"] for x in events["pull_request"])
            )
            duplicate_shas.append(sha[:7])
    waste = cancelled + superseded + duplicate
    days = 0.0
    if rows:
        days = (max(r["end"] for r in rows) - min(r["start"] for r in rows)).total_seconds() / 86400
    scale = 30 / days if days >= 1 else None
    return {
        "runs": len(rows),
        "days": round(days, 1),
        "total_minutes": round(total, 1),
        "waste_minutes": round(waste, 1),
        "waste_pct": round(100 * waste / total, 1) if total else 0.0,
        "breakdown": {
            "superseded": round(superseded, 1),
            "cancelled": round(cancelled, 1),
            "duplicate_push_pr": round(duplicate, 1),
        },
        "superseded_runs": superseded_ids,
        "duplicate_commits": sorted(duplicate_shas),
        "per_30_days": {
            "total_minutes": round(total * scale, 0) if scale else None,
            "waste_minutes": round(waste * scale, 0) if scale else None,
        },
        "estimated": not all(isinstance(r.get("jobs"), list) and r.get("jobs") for r in runs),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Find speed problems in a workflow and estimate wasted minutes from run history.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example: gh run list --workflow ci.yml --limit 200 --json "
        "databaseId,workflowName,event,conclusion,headBranch,headSha,createdAt,startedAt,updatedAt > runs.json",
    )
    p.add_argument("--workflow", type=Path, help="workflow YAML file")
    p.add_argument("--runs", type=Path, help="run history JSON (gh run list --json ...)")
    p.add_argument("--jobs-per-run", type=int, help="billed jobs per run when runs have no jobs data")
    p.add_argument("--max-matrix", type=int, default=12, help="matrix size that counts as large (default 12)")
    p.add_argument("--max-waste-pct", type=float, default=20.0, help="exit 1 at or above this waste %% (default 20)")
    p.add_argument("--fail-on", choices=SEVERITIES, default="medium", help="exit 1 for static findings at/above")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    if not args.workflow and not args.runs:
        p.error("give --workflow, --runs or both")
    result: dict = {"findings": [], "runs": None}
    jobs_per_run = args.jobs_per_run or 1
    try:
        if args.workflow:
            wf = load_workflow(args.workflow.read_text(encoding="utf-8"))
            if not isinstance(wf, dict) or "jobs" not in wf:
                print(f"error: {args.workflow} is not a workflow (no jobs)", file=sys.stderr)
                return 2
            result["findings"] = static_findings(wf, args.max_matrix)
            result["jobs_per_run"] = job_count(wf)
            if not args.jobs_per_run:
                jobs_per_run = result["jobs_per_run"]
        if args.runs:
            data = json.loads(args.runs.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data = data.get("workflow_runs") or data.get("runs") or []
            if not isinstance(data, list):
                print("error: --runs must be a JSON list of runs", file=sys.stderr)
                return 2
            result["runs"] = analyse_runs(data, jobs_per_run)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # YAML errors
        print(f"error: cannot parse workflow: {str(exc).splitlines()[0]}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        for f in result["findings"]:
            job = f" [{f['job']}]" if f["job"] else ""
            print(f"{f['severity'].upper():7}{job} {f['check']}: {f['title']}\n        -> {f['fix']}")
        r = result["runs"]
        if r:
            b = r["breakdown"]
            kind = "partly estimated from wall time x jobs" if r["estimated"] else "from job timings"
            print(
                f"\nRuns: {r['runs']} over {r['days']} days, {r['total_minutes']} runner minutes ({kind})\n"
                f"Waste: {r['waste_minutes']} min ({r['waste_pct']}%) = superseded {b['superseded']}"
                f" + cancelled {b['cancelled']} + duplicate push/PR {b['duplicate_push_pr']}"
            )
            if r["per_30_days"]["waste_minutes"] is not None:
                print(
                    f"Per 30 days: ~{r['per_30_days']['total_minutes']:.0f} min total,"
                    f" ~{r['per_30_days']['waste_minutes']:.0f} min wasted"
                )
        if not result["findings"] and not r:
            print("no findings")
    threshold = SEVERITIES.index(args.fail_on)
    bad = any(SEVERITIES.index(f["severity"]) >= threshold for f in result["findings"])
    if result["runs"] and result["runs"]["waste_pct"] >= args.max_waste_pct:
        bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
