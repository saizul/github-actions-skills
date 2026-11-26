#!/usr/bin/env python3
"""Expand GitHub Actions matrices exactly like GitHub does and check service containers.

Matrix (per job with strategy.matrix):
  * lists every combination after exclude and include, with the job count
  matrix.too_large          more than 256 combinations (GitHub's limit) -> error;
                            more than --max (default 20) -> warning
  matrix.exclude_unmatched  an exclude entry matches no combination (typo?)
  matrix.include_new        an include entry matched nothing and became its own job
  matrix.dynamic            values come from an expression (fromJSON); cannot expand

Services (jobs.<id>.services):
  services.non_linux        service containers need a Linux runner
  services.no_ports         job runs on the runner but the service publishes no ports
  services.localhost_in_container  job runs in a container but env points at localhost
  services.no_healthcheck   database/queue image without --health-cmd (tests start too early)
  services.no_password      postgres/mysql/mariadb without the required password variable
  services.floating_tag     image without a tag or with :latest

Needs PyYAML. Read-only. Exit codes: 0 = ok, 1 = errors (or warnings with --strict), 2 = usage error.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

GITHUB_MAX = 256
HEALTH_IMAGES = ("postgres", "mysql", "mariadb", "redis", "mongo", "rabbitmq", "elasticsearch", "opensearch", "valkey")
PASSWORD_VARS = {
    "postgres": ({"POSTGRES_PASSWORD"}, {"POSTGRES_HOST_AUTH_METHOD"}),
    "mysql": ({"MYSQL_ROOT_PASSWORD"}, {"MYSQL_ALLOW_EMPTY_PASSWORD", "MYSQL_RANDOM_ROOT_PASSWORD"}),
    "mariadb": (
        {"MARIADB_ROOT_PASSWORD", "MYSQL_ROOT_PASSWORD"},
        {"MARIADB_ALLOW_EMPTY_ROOT_PASSWORD", "MARIADB_RANDOM_ROOT_PASSWORD", "MYSQL_ALLOW_EMPTY_PASSWORD"},
    ),
}
DEFAULT_PORTS = {
    "postgres": 5432,
    "mysql": 3306,
    "mariadb": 3306,
    "redis": 6379,
    "valkey": 6379,
    "mongo": 27017,
    "rabbitmq": 5672,
    "elasticsearch": 9200,
    "opensearch": 9200,
}
LOCALHOST_RE = re.compile(r"\b(localhost|127\.0\.0\.1)\b")


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


def is_expr(value) -> bool:
    return isinstance(value, str) and "${{" in value


def expand(matrix) -> dict:
    """Return {"combos": [...], "unmatched_excludes": [...], "new_includes": [...], "dynamic": bool}."""
    res = {"combos": [], "unmatched_excludes": [], "new_includes": [], "dynamic": False}
    if is_expr(matrix):
        res["dynamic"] = True
        return res
    if not isinstance(matrix, dict):
        return res
    base = {}
    for k, v in matrix.items():
        if k in ("include", "exclude"):
            continue
        if not isinstance(v, list):
            res["dynamic"] = True
            return res
        base[k] = v
    if is_expr(matrix.get("include")) or is_expr(matrix.get("exclude")):
        res["dynamic"] = True
        return res
    keys = list(base)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*(base[k] for k in keys))] if keys else []
    for ex in matrix.get("exclude") or []:
        if not isinstance(ex, dict):
            continue
        kept = [c for c in combos if not all(c.get(k) == v for k, v in ex.items())]
        if len(kept) == len(combos):
            res["unmatched_excludes"].append(ex)
        combos = kept
    originals = list(combos)  # includes only extend combinations from the product, never each other
    for inc in matrix.get("include") or []:
        if not isinstance(inc, dict):
            continue
        matched = False
        for c in originals:
            # an include extends a combination when it does not overwrite any original value
            if all(c.get(k) == v for k, v in inc.items() if k in base):
                matched = True
                for k, v in inc.items():
                    if k not in base:
                        c[k] = v
        if not matched:
            combos.append(dict(inc))
            res["new_includes"].append(inc)
    res["combos"] = combos
    return res


def image_name(image: str) -> tuple[str, str | None]:
    ref = image.split("@", 1)[0]
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        name, tag = last.split(":", 1)
    else:
        name, tag = last, None
    if "@sha256:" in image:
        tag = "digest"
    return name.lower(), tag


def check_services(job_id: str, job: dict) -> list[dict]:
    out = []
    services = job.get("services") or {}
    if not isinstance(services, dict) or not services:
        return out

    def add(level, check, message):
        out.append({"level": level, "check": check, "job": job_id, "message": message})

    runs_on = json.dumps(job.get("runs-on", ""), default=str).lower()
    if any(x in runs_on for x in ("macos", "windows")):
        add("error", "services.non_linux", f"services need a Linux runner, runs-on is {job.get('runs-on')}")
    in_container = bool(job.get("container"))
    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        image = str(svc.get("image", ""))
        if not image or is_expr(image):
            continue
        img, tag = image_name(image)
        if tag in (None, "latest"):
            add("warning", "services.floating_tag", f"{name}: image {image} has no fixed tag; pin e.g. {img}:17")
        if not in_container and not svc.get("ports"):
            port = next((v for k, v in DEFAULT_PORTS.items() if img.startswith(k)), "PORT")
            add(
                "error",
                "services.no_ports",
                f"{name}: job runs on the runner, so map ports (ports: ['{port}:{port}']) and use localhost",
            )
        options = str(svc.get("options", ""))
        if any(img.startswith(h) for h in HEALTH_IMAGES) and "--health-cmd" not in options:
            add(
                "warning",
                "services.no_healthcheck",
                f"{name}: no --health-cmd; steps may start before {img} accepts connections",
            )
        env = {str(k) for k in (svc.get("env") or {})}
        for key, (required, alternatives) in PASSWORD_VARS.items():
            if img == key or img.startswith(key + "-"):
                if not env & (required | alternatives):
                    add(
                        "error",
                        "services.no_password",
                        f"{name}: {img} needs one of {', '.join(sorted(required | alternatives))}",
                    )
    if in_container:
        env_text = json.dumps(job.get("env") or {}) + json.dumps(
            [s.get("env") for s in job.get("steps") or [] if isinstance(s, dict)]
        )
        if LOCALHOST_RE.search(env_text):
            add(
                "warning",
                "services.localhost_in_container",
                "job runs in a container: reach services by their name (e.g. postgres:5432), not localhost",
            )
    return out


def analyse(wf: dict, job_filter: str | None, max_jobs: int) -> dict:
    jobs_out = []
    problems = []
    for job_id, job in (wf.get("jobs") or {}).items():
        if not isinstance(job, dict) or (job_filter and job_id != job_filter):
            continue
        problems += check_services(job_id, job)
        matrix = (job.get("strategy") or {}).get("matrix")
        if matrix is None:
            continue
        res = expand(matrix)
        entry = {"job": job_id, "count": len(res["combos"]), "combinations": res["combos"], "dynamic": res["dynamic"]}
        jobs_out.append(entry)
        if res["dynamic"]:
            problems.append(
                {
                    "level": "info",
                    "check": "matrix.dynamic",
                    "job": job_id,
                    "message": "matrix built from an expression; expand it by running the generating step",
                }
            )
            continue
        n = len(res["combos"])
        if n > GITHUB_MAX:
            problems.append(
                {
                    "level": "error",
                    "check": "matrix.too_large",
                    "job": job_id,
                    "message": f"{n} combinations; GitHub allows at most {GITHUB_MAX} per workflow run",
                }
            )
        elif n > max_jobs:
            problems.append(
                {
                    "level": "warning",
                    "check": "matrix.too_large",
                    "job": job_id,
                    "message": f"{n} combinations (more than {max_jobs}); trim on pull requests",
                }
            )
        for ex in res["unmatched_excludes"]:
            problems.append(
                {
                    "level": "warning",
                    "check": "matrix.exclude_unmatched",
                    "job": job_id,
                    "message": f"exclude {json.dumps(ex)} matches no combination (typo or wrong value type?)",
                }
            )
        for inc in res["new_includes"]:
            problems.append(
                {
                    "level": "info",
                    "check": "matrix.include_new",
                    "job": job_id,
                    "message": f"include {json.dumps(inc)} matched nothing and adds its own job",
                }
            )
    return {"jobs": jobs_out, "problems": problems}


def fmt_combo(c: dict) -> str:
    return ", ".join(f"{k}={json.dumps(v) if not isinstance(v, str) else v}" for k, v in c.items())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Expand GitHub Actions matrices and check service containers.")
    p.add_argument("workflow", type=Path, help="workflow YAML file")
    p.add_argument("--job", help="only this job id")
    p.add_argument("--max", type=int, default=20, help="warn above this many combinations (default 20)")
    p.add_argument("--count", action="store_true", help="print only the job counts")
    p.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    try:
        wf = load_workflow(args.workflow.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: cannot parse {args.workflow}: {str(exc).splitlines()[0]}", file=sys.stderr)
        return 2
    if not isinstance(wf, dict) or "jobs" not in wf:
        print(f"error: {args.workflow} has no jobs", file=sys.stderr)
        return 2
    if args.job and args.job not in wf["jobs"]:
        print(f"error: job '{args.job}' not found (jobs: {', '.join(wf['jobs'])})", file=sys.stderr)
        return 2
    res = analyse(wf, args.job, args.max)
    if args.json:
        print(json.dumps(res, indent=2, default=str))
    else:
        for j in res["jobs"]:
            if j["dynamic"]:
                print(f"{j['job']}: dynamic matrix (expression)")
                continue
            print(f"{j['job']}: {j['count']} job(s)")
            if not args.count:
                for c in j["combinations"]:
                    print(f"  - {fmt_combo(c)}")
        for x in res["problems"]:
            print(f"{x['level'].upper():7} [{x['job']}] {x['check']}: {x['message']}")
        if not res["jobs"] and not res["problems"]:
            print("no matrix or services found")
    levels = {"error"} | ({"warning"} if args.strict else set())
    return 1 if any(x["level"] in levels for x in res["problems"]) else 0


if __name__ == "__main__":
    sys.exit(main())
