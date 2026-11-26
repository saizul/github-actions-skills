#!/usr/bin/env python3
"""Check reusable workflows, composite actions and their callers in one repository.

Reusable workflows (on: workflow_call) and local callers (jobs.<id>.uses: ./.github/workflows/x.yml):
  call.missing_file        called workflow does not exist
  call.not_reusable        called workflow has no workflow_call trigger
  call.invalid_keys        caller job also sets runs-on/steps (not allowed with uses)
  call.unknown_input       with: key not declared in workflow_call.inputs
  call.missing_input       required input without default not passed
  call.input_type          literal value does not match the declared type (boolean/number)
  call.unknown_secret      secrets: key not declared in workflow_call.secrets
  call.missing_secret      required secret not passed (and no secrets: inherit)
  reusable.undeclared_input  ${{ inputs.X }} used but X not declared
  reusable.undeclared_secret ${{ secrets.X }} used but X not declared (warning)
  reusable.output_no_value   workflow_call output without value

Composite actions (action.yml with runs.using: composite) and local uses: ./path steps:
  composite.missing_shell    run step without shell (required in composite actions)
  composite.secrets_context  ${{ secrets.* }} inside a composite action (not available)
  composite.undeclared_input ${{ inputs.X }} used but X not declared
  composite.output_no_value  output without value
  action.missing_file / action.unknown_input / action.missing_input for local uses: ./dir

Needs PyYAML. Read-only. Exit codes: 0 = ok, 1 = errors (or warnings with --strict), 2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

INPUT_REF_RE = re.compile(r"\binputs\.([A-Za-z_][A-Za-z0-9_-]*)")
SECRET_REF_RE = re.compile(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)")
EXPR_RE = re.compile(r"\$\{\{(.*?)\}\}", re.S)
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "vendor"}


def yaml_load(text: str):
    try:
        import yaml
    except ImportError:
        print("error: PyYAML is required: pip install pyyaml", file=sys.stderr)
        raise SystemExit(2) from None
    data = yaml.safe_load(text)
    if isinstance(data, dict) and True in data and "on" not in data:
        data["on"] = data.pop(True)
    return data


def problem(level, check, file, job, message):
    return {"level": level, "check": check, "file": str(file), "job": job, "message": message}


def expr_text(obj) -> str:
    """All ${{ }} expression bodies anywhere inside obj, joined."""
    if isinstance(obj, dict):
        return "\n".join(expr_text(k) + "\n" + expr_text(v) for k, v in obj.items())
    if isinstance(obj, list):
        return "\n".join(expr_text(x) for x in obj)
    if isinstance(obj, str):
        return "\n".join(EXPR_RE.findall(obj))
    return ""


def workflow_call(wf: dict):
    on = wf.get("on")
    if isinstance(on, dict) and "workflow_call" in on:
        return on.get("workflow_call") or {}
    if on == "workflow_call" or (isinstance(on, list) and "workflow_call" in on):
        return {}
    return None


def other_input_sources(wf: dict) -> set[str]:
    """Inputs declared by workflow_dispatch also populate the inputs context."""
    on = wf.get("on")
    if isinstance(on, dict) and isinstance(on.get("workflow_dispatch"), dict):
        return set((on["workflow_dispatch"].get("inputs") or {}).keys())
    return set()


def type_ok(value, declared: str) -> bool:
    if isinstance(value, str) and "${{" in value:
        return True
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def check_reusable(path: Path, wf: dict, call: dict) -> list[dict]:
    out = []
    inputs = set((call.get("inputs") or {}).keys()) | other_input_sources(wf)
    secrets = set((call.get("secrets") or {}).keys())
    text = expr_text(wf.get("jobs") or {})
    for name in sorted(set(INPUT_REF_RE.findall(text)) - inputs):
        out.append(problem("error", "reusable.undeclared_input", path, None, f"inputs.{name} is not declared"))
    for name in sorted(set(SECRET_REF_RE.findall(text)) - secrets - {"GITHUB_TOKEN"}):
        out.append(
            problem(
                "warning",
                "reusable.undeclared_secret",
                path,
                None,
                f"secrets.{name} is not declared in workflow_call.secrets (works only with secrets: inherit)",
            )
        )
    for name, spec in (call.get("outputs") or {}).items():
        if not isinstance(spec, dict) or "value" not in spec:
            out.append(problem("error", "reusable.output_no_value", path, None, f"output {name} needs value:"))
    return out


def check_call(caller: Path, job_id: str, job: dict, root: Path, cache: dict) -> list[dict]:
    out = []
    uses = str(job["uses"])
    if not uses.startswith("./"):
        return out
    target = (root / uses.split("@", 1)[0]).resolve()
    for key in ("runs-on", "steps", "container", "services", "env", "timeout-minutes"):
        if key in job:
            out.append(problem("error", "call.invalid_keys", caller, job_id, f"`{key}` is not allowed with uses:"))
    if not target.is_file():
        return out + [problem("error", "call.missing_file", caller, job_id, f"{uses} does not exist")]
    wf = cache.get(target)
    if wf is None:
        wf = yaml_load(target.read_text(encoding="utf-8")) or {}
        cache[target] = wf
    call = workflow_call(wf) if isinstance(wf, dict) else None
    if call is None:
        return out + [problem("error", "call.not_reusable", caller, job_id, f"{uses} has no workflow_call trigger")]
    declared_inputs = call.get("inputs") or {}
    given = job.get("with") or {}
    for key, value in given.items():
        if key not in declared_inputs:
            out.append(problem("error", "call.unknown_input", caller, job_id, f"input '{key}' is not declared"))
            continue
        spec = declared_inputs[key] or {}
        if not type_ok(value, str(spec.get("type", "string"))):
            out.append(
                problem(
                    "error",
                    "call.input_type",
                    caller,
                    job_id,
                    f"input '{key}' is {spec.get('type')} but got {value!r} ({type(value).__name__})",
                )
            )
    for key, spec in declared_inputs.items():
        spec = spec or {}
        if spec.get("required") and "default" not in spec and key not in given:
            out.append(problem("error", "call.missing_input", caller, job_id, f"required input '{key}' not passed"))
    declared_secrets = call.get("secrets") or {}
    passed = job.get("secrets")
    if passed != "inherit":
        passed = passed or {}
        for key in passed:
            if key not in declared_secrets:
                out.append(problem("error", "call.unknown_secret", caller, job_id, f"secret '{key}' is not declared"))
        for key, spec in declared_secrets.items():
            if (spec or {}).get("required") and key not in passed:
                out.append(
                    problem("error", "call.missing_secret", caller, job_id, f"required secret '{key}' not passed")
                )
    return out


def check_composite(path: Path, action: dict) -> list[dict]:
    out = []
    runs = action.get("runs") or {}
    if str(runs.get("using")) != "composite":
        return out
    declared = set((action.get("inputs") or {}).keys())
    for i, step in enumerate(runs.get("steps") or []):
        if not isinstance(step, dict):
            continue
        label = step.get("name") or step.get("id") or f"step {i + 1}"
        if "run" in step and "shell" not in step:
            out.append(problem("error", "composite.missing_shell", path, None, f"{label}: run step needs shell:"))
    text = expr_text(runs)
    if SECRET_REF_RE.search(text):
        out.append(
            problem(
                "error",
                "composite.secrets_context",
                path,
                None,
                "secrets context is not available in composite actions; pass secrets as inputs",
            )
        )
    for name in sorted(set(INPUT_REF_RE.findall(text)) - declared):
        out.append(problem("error", "composite.undeclared_input", path, None, f"inputs.{name} is not declared"))
    for name, spec in (action.get("outputs") or {}).items():
        if not isinstance(spec, dict) or "value" not in spec:
            out.append(problem("error", "composite.output_no_value", path, None, f"output {name} needs value:"))
    return out


def check_local_action_step(caller: Path, job_id, step: dict, root: Path) -> list[dict]:
    uses = str(step.get("uses", ""))
    if not uses.startswith("./"):
        return []
    base = root / uses
    meta = next((base / n for n in ("action.yml", "action.yaml") if (base / n).is_file()), None)
    if meta is None:
        return [problem("error", "action.missing_file", caller, job_id, f"{uses} has no action.yml")]
    action = yaml_load(meta.read_text(encoding="utf-8")) or {}
    declared = action.get("inputs") or {}
    given = step.get("with") or {}
    out = []
    for key in given:
        if key not in declared:
            out.append(
                problem("warning", "action.unknown_input", caller, job_id, f"{uses}: input '{key}' not declared")
            )
    for key, spec in declared.items():
        spec = spec or {}
        if spec.get("required") and "default" not in spec and key not in given:
            out.append(problem("error", "action.missing_input", caller, job_id, f"{uses}: required input '{key}'"))
    return out


def scan(root: Path) -> tuple[list[dict], dict]:
    problems: list[dict] = []
    stats = {"workflows": 0, "reusable": 0, "calls": 0, "composite": 0}
    cache: dict = {}
    wf_dir = root / ".github" / "workflows"
    workflows = sorted(p for p in wf_dir.glob("*") if p.suffix in (".yml", ".yaml")) if wf_dir.is_dir() else []
    for path in workflows:
        rel = path.relative_to(root)
        try:
            wf = yaml_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            problems.append(problem("error", "yaml.invalid", rel, None, str(exc).splitlines()[0]))
            continue
        if not isinstance(wf, dict):
            continue
        cache[path.resolve()] = wf
        stats["workflows"] += 1
        call = workflow_call(wf)
        if call is not None:
            stats["reusable"] += 1
            problems += check_reusable(rel, wf, call)
        for job_id, job in (wf.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            if "uses" in job:
                stats["calls"] += 1
                problems += check_call(rel, job_id, job, root, cache)
            for step in job.get("steps") or []:
                if isinstance(step, dict) and step.get("uses"):
                    problems += check_local_action_step(rel, job_id, step, root)
    for meta in sorted(root.rglob("action.y*ml")):
        if any(part in SKIP_DIRS for part in meta.relative_to(root).parts):
            continue
        try:
            action = yaml_load(meta.read_text(encoding="utf-8"))
        except Exception as exc:
            problems.append(problem("error", "yaml.invalid", meta.relative_to(root), None, str(exc).splitlines()[0]))
            continue
        if isinstance(action, dict) and str((action.get("runs") or {}).get("using")) == "composite":
            stats["composite"] += 1
            problems += check_composite(meta.relative_to(root), action)
    return problems, stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Check reusable workflows, composite actions and their callers.")
    p.add_argument("root", nargs="?", default=".", type=Path, help="repository root (default .)")
    p.add_argument("--json", action="store_true", help="print JSON")
    p.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    args = p.parse_args(argv)
    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2
    problems, stats = scan(args.root)
    if args.json:
        print(json.dumps({"stats": stats, "problems": problems}, indent=2))
    else:
        for x in problems:
            job = f" [{x['job']}]" if x["job"] else ""
            print(f"{x['level'].upper():7} {x['file']}{job} {x['check']}: {x['message']}")
        print(
            f"\n{stats['workflows']} workflows ({stats['reusable']} reusable, {stats['calls']} local calls),"
            f" {stats['composite']} composite actions: "
            f"{sum(x['level'] == 'error' for x in problems)} errors, {sum(x['level'] == 'warning' for x in problems)}"
            " warnings"
        )
    levels = {"error"} | ({"warning"} if args.strict else set())
    return 1 if any(x["level"] in levels for x in problems) else 0


if __name__ == "__main__":
    sys.exit(main())
