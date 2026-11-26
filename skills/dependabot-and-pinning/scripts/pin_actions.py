#!/usr/bin/env python3
"""Suggest (or apply) commit-SHA pins for GitHub Actions `uses:` references, offline.

SHAs come from a mapping file you provide; this script never calls the network.
Mapping formats (--map FILE):
  JSON flat:    {"actions/checkout@v7": "<40-hex sha>", ...}
  JSON nested:  {"actions/checkout": {"v7": "<sha>", "v7.0.1": "<sha>"}, ...}
  text:         one "owner/repo@ref <sha>" per line (# comments allowed)
--resolve-script prints a shell script that builds the text mapping with `git ls-remote`
(the user runs it; it needs network access).

Default is a dry run: report each tag/branch reference and the suggested pin.
--write rewrites files in place to `owner/repo@<sha> # <ref>`; --diff shows a unified diff.
Local (./) actions and docker:// images are skipped.

Exit codes: 0 = everything pinned (or pinned by --write), 1 = unpinned references remain,
2 = error (unreadable files, invalid mapping).
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
USES_RE = re.compile(
    r"^(?P<prefix>\s*(?:-\s+)?uses:\s*)(?P<q>['\"]?)(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)@(?P<ref>[^\s'\"#]+)"
    r"(?P=q)(?P<rest>\s*(?:#.*)?)$"
)
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "vendor"}


def repo_of(action: str) -> str:
    """owner/repo from owner/repo/sub/path."""
    return "/".join(action.split("/")[:2])


def load_mapping(path: Path) -> dict[str, str]:
    """Return {"owner/repo@ref": sha} (repo lowercased, ref as given)."""
    text = path.read_text(encoding="utf-8")
    mapping: dict[str, str] = {}
    stripped = text.lstrip()
    if stripped.startswith("{"):
        data = json.loads(text)
        for key, value in data.items():
            if isinstance(value, dict):
                for ref, sha in value.items():
                    mapping[f"{repo_of(key).lower()}@{ref}"] = str(sha).strip().lower()
            elif "@" in key:
                action, ref = key.rsplit("@", 1)
                mapping[f"{repo_of(action).lower()}@{ref}"] = str(value).strip().lower()
            else:
                raise ValueError(f"mapping key {key!r} needs @ref or a nested object")
    else:
        for n, line in enumerate(text.splitlines(), 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2 or "@" not in parts[0]:
                raise ValueError(f"line {n}: expected 'owner/repo@ref sha'")
            action, ref = parts[0].rsplit("@", 1)
            mapping[f"{repo_of(action).lower()}@{ref}"] = parts[1].lower()
    for key, sha in mapping.items():
        if not SHA_RE.match(sha):
            raise ValueError(f"{key}: {sha!r} is not a full 40-character commit SHA")
    return mapping


def collect(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            wf = p / ".github" / "workflows"
            if wf.is_dir():
                files += sorted(x for x in wf.rglob("*") if x.suffix in (".yml", ".yaml"))
                for meta in sorted(p.rglob("action.y*ml")):
                    if not any(part in SKIP_DIRS for part in meta.relative_to(p).parts):
                        files.append(meta)
            else:
                files += sorted(x for x in p.rglob("*") if x.suffix in (".yml", ".yaml"))
        elif p.is_file():
            files.append(p)
        else:
            raise FileNotFoundError(raw)
    seen, out = set(), []
    for f in files:
        if f.resolve() not in seen:
            seen.add(f.resolve())
            out.append(f)
    return out


def process(text: str, mapping: dict[str, str]) -> tuple[str, list[dict]]:
    """Return (new_text, items) for one file."""
    reverse: dict[tuple[str, str], list[str]] = {}
    for key, sha in mapping.items():
        repo, ref = key.rsplit("@", 1)
        reverse.setdefault((repo, sha), []).append(ref)
    out_lines = []
    items = []
    for n, line in enumerate(text.splitlines(keepends=True), 1):
        body = line.rstrip("\r\n")
        eol = line[len(body) :]
        m = USES_RE.match(body)
        if not m or m.group("action").startswith("./"):
            out_lines.append(line)
            continue
        action, ref = m.group("action"), m.group("ref")
        repo = repo_of(action).lower()
        item = {"line": n, "action": action, "ref": ref, "status": "", "sha": None}
        if SHA_RE.match(ref):
            comment = m.group("rest").strip()
            item["status"] = "pinned"
            if not comment:
                tags = sorted(reverse.get((repo, ref), []), key=len, reverse=True)
                item["status"] = "pinned_no_comment"
                item["suggested_comment"] = tags[0] if tags else None
            items.append(item)
            out_lines.append(line)
            continue
        sha = mapping.get(f"{repo}@{ref}")
        if sha:
            item.update(status="pinnable", sha=sha)
            old_comment = m.group("rest").strip().lstrip("#").strip()
            suffix = f" - {old_comment}" if old_comment else ""
            new = f"{m.group('prefix')}{m.group('q')}{action}@{sha}{m.group('q')} # {ref}{suffix}"
            out_lines.append(new + eol)
        else:
            item["status"] = "unresolved"
            out_lines.append(line)
        items.append(item)
    return "".join(out_lines), items


def resolve_script(refs: set[tuple[str, str]]) -> str:
    lines = [
        "#!/bin/sh",
        "# Builds pins.txt (owner/repo@ref sha) with git ls-remote. Review, then run: sh resolve-pins.sh",
        "# Annotated tags are peeled (^{}) so the SHA is the commit, not the tag object.",
        "set -eu",
        ": > pins.txt",
    ]
    for repo, ref in sorted(refs):
        url = f"https://github.com/{repo}"
        lines.append(
            f"sha=$(git ls-remote {url} 'refs/tags/{ref}^{{}}' 'refs/tags/{ref}' 'refs/heads/{ref}' "
            "| awk 'NR==1{s=$1} /\\^\\{\\}$/{s=$1} END{print s}')"
        )
        lines.append(f'[ -n "$sha" ] && echo "{repo}@{ref} $sha" >> pins.txt || echo "not found: {repo}@{ref}" >&2')
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Suggest or apply SHA pins for GitHub Actions uses: references (offline).")
    p.add_argument("paths", nargs="+", help="workflow files, action.yml files or a repository root")
    p.add_argument("--map", type=Path, help="mapping file (JSON or 'owner/repo@ref sha' lines)")
    p.add_argument("--write", action="store_true", help="rewrite files in place (default: dry run)")
    p.add_argument("--diff", action="store_true", help="print a unified diff of the changes")
    p.add_argument("--resolve-script", action="store_true", help="print a git ls-remote script for unresolved refs")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    try:
        mapping = load_mapping(args.map) if args.map else {}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: mapping: {exc}", file=sys.stderr)
        return 2
    try:
        files = collect(args.paths)
    except FileNotFoundError as exc:
        print(f"error: no such file or directory: {exc}", file=sys.stderr)
        return 2
    report = []
    diffs = []
    unresolved_refs: set[tuple[str, str]] = set()
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        new, items = process(text, mapping)
        for it in items:
            it["file"] = str(f)
            if it["status"] == "unresolved":
                unresolved_refs.add((repo_of(it["action"]).lower(), it["ref"]))
        report += items
        if new != text:
            if args.diff:
                diffs.append("".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True), str(f), str(f))))
            if args.write:
                f.write_text(new, encoding="utf-8")
    counts = {
        s: sum(1 for x in report if x["status"] == s) for s in ("pinned", "pinned_no_comment", "pinnable", "unresolved")
    }
    if args.resolve_script:
        print(resolve_script(unresolved_refs), end="")
    elif args.json:
        print(json.dumps({"written": args.write, "counts": counts, "items": report}, indent=2))
    else:
        for x in report:
            loc = f"{x['file']}:{x['line']}"
            if x["status"] == "pinnable":
                verb = "pinned" if args.write else "pin"
                print(f"{verb.upper():10} {loc} {x['action']}@{x['ref']} -> @{x['sha']} # {x['ref']}")
            elif x["status"] == "unresolved":
                print(f"UNRESOLVED {loc} {x['action']}@{x['ref']} (not in mapping)")
            elif x["status"] == "pinned_no_comment":
                hint = (
                    f" (add # {x['suggested_comment']})" if x.get("suggested_comment") else " (add a # version comment)"
                )
                print(f"NO-COMMENT {loc} {x['action']}@{x['ref'][:12]}...{hint}")
        for d in diffs:
            print(d, end="")
        print(
            f"\n{len(files)} file(s): {counts['pinned'] + counts['pinned_no_comment']} already pinned, "
            f"{counts['pinnable']} {'pinned now' if args.write else 'pinnable'}, {counts['unresolved']} unresolved"
        )
        if counts["unresolved"]:
            print("Resolve the rest: --resolve-script > resolve-pins.sh, review and run it, then --map pins.txt")
    remaining = counts["unresolved"] + (0 if args.write else counts["pinnable"])
    return 1 if remaining else 0


if __name__ == "__main__":
    sys.exit(main())
