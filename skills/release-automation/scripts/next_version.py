#!/usr/bin/env python3
"""Compute the next semantic version and a changelog section from Conventional Commits.

Input is git log output (stdin or --log FILE), either one subject per line:
    git log --format=%s v1.4.2..HEAD
or full messages with short hashes (recommended, detects BREAKING CHANGE footers):
    git log --format='%h%x1f%s%x1f%b%x1e' v1.4.2..HEAD

Rules: `type!:` or a `BREAKING CHANGE:` footer -> major; feat -> minor; fix/perf -> patch;
other types (docs, chore, ci, test, refactor, build, style) -> no release unless
--patch-for-other. On 0.x versions --pre-major turns major bumps into minor bumps.
--check lints the messages instead and exits 1 when any subject is not conventional.

Offline, reads text only. Exit codes: 0 = ok, 1 = --check found bad subjects or
--fail-if-none and nothing to release, 2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date

SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
CC_RE = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^()\r\n]+)\))?(?P<bang>!)?: (?P<desc>\S.*)$")
BREAKING_RE = re.compile(r"^BREAKING[ -]CHANGE: ?(.*)", re.M)
SECTIONS = [
    ("breaking", "Breaking changes"),
    ("feat", "Features"),
    ("fix", "Bug fixes"),
    ("perf", "Performance"),
    ("revert", "Reverts"),
    ("other", "Other changes"),
]
ORDER = ["none", "patch", "minor", "major"]
SKIP_SUBJECT_RE = re.compile(r"^(Merge (pull request|branch|remote-tracking)|Revert \"|fixup! |squash! )")


def parse_version(text: str) -> tuple[int, int, int, str | None]:
    m = SEMVER_RE.match(text.strip())
    if not m:
        raise ValueError(f"not a semantic version: {text!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)


def parse_log(text: str) -> list[dict]:
    commits = []
    if "\x1f" in text:
        for record in text.split("\x1e"):
            record = record.strip("\n")
            if not record.strip():
                continue
            parts = record.split("\x1f")
            if len(parts) >= 3:
                commits.append({"hash": parts[0].strip(), "subject": parts[1].strip(), "body": parts[2].strip()})
            elif len(parts) == 2:
                commits.append({"hash": parts[0].strip(), "subject": parts[1].strip(), "body": ""})
    else:
        for line in text.splitlines():
            if line.strip():
                commits.append({"hash": "", "subject": line.strip(), "body": ""})
    return commits


def classify(commit: dict) -> dict:
    m = CC_RE.match(commit["subject"])
    out = dict(commit)
    if not m:
        out.update(type=None, scope=None, desc=commit["subject"], breaking=False, conventional=False)
        return out
    breaking_note = BREAKING_RE.search(commit.get("body", ""))
    out.update(
        type=m.group("type").lower(),
        scope=m.group("scope"),
        desc=m.group("desc").strip(),
        breaking=bool(m.group("bang") or breaking_note),
        breaking_note=(breaking_note.group(1).strip() if breaking_note else ""),
        conventional=True,
    )
    return out


def bump_for(commits: list[dict], patch_for_other: bool) -> str:
    level = "none"
    for c in commits:
        if c["breaking"]:
            b = "major"
        elif c["type"] == "feat":
            b = "minor"
        elif c["type"] in ("fix", "perf", "revert") or patch_for_other:
            b = "patch"
        else:
            b = "none"
        if ORDER.index(b) > ORDER.index(level):
            level = b
    return level


def next_version(current: str, bump: str, pre_major: bool = False, pre: str | None = None) -> str:
    major, minor, patch, cur_pre = parse_version(current)
    if bump == "major" and major == 0 and pre_major:
        bump = "minor"
    if cur_pre and pre:
        # 1.3.0-rc.1 -> 1.3.0-rc.2 when continuing the same prerelease line
        m = re.match(rf"^{re.escape(pre)}\.(\d+)$", cur_pre)
        if m:
            return f"{major}.{minor}.{patch}-{pre}.{int(m.group(1)) + 1}"
    if cur_pre and bump != "none":
        base = f"{major}.{minor}.{patch}"  # releasing a prerelease line
    elif bump == "major":
        base = f"{major + 1}.0.0"
    elif bump == "minor":
        base = f"{major}.{minor + 1}.0"
    elif bump == "patch":
        base = f"{major}.{minor}.{patch + 1}"
    else:
        return f"{major}.{minor}.{patch}" + (f"-{cur_pre}" if cur_pre else "")
    return f"{base}-{pre}.1" if pre else base


def changelog(version: str, commits: list[dict], repo: str | None, day: str, include_other: bool) -> str:
    groups: dict[str, list[str]] = {k: [] for k, _ in SECTIONS}
    for c in commits:
        if SKIP_SUBJECT_RE.match(c["subject"]):
            continue
        scope = f"**{c['scope']}:** " if c.get("scope") else ""
        ref = ""
        if c.get("hash"):
            short = c["hash"][:7]
            ref = f" ([{short}](https://github.com/{repo}/commit/{c['hash']}))" if repo else f" ({short})"
        line = f"- {scope}{c['desc']}{ref}"
        if c["breaking"]:
            groups["breaking"].append(f"- {scope}{c.get('breaking_note') or c['desc']}{ref}")
        if c["type"] in groups and c["type"] != "breaking":
            groups[c["type"]].append(line)
        elif include_other and not c["breaking"]:
            groups["other"].append(line)
    out = [f"## [{version}] - {day}", ""]
    for key, title in SECTIONS:
        if groups[key]:
            out += [f"### {title}", "", *groups[key], ""]
    if len(out) == 2:
        out += ["No user-facing changes.", ""]
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Next semantic version + changelog section from Conventional Commits.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example: git log --format='%%h%%x1f%%s%%x1f%%b%%x1e' v1.4.2..HEAD | "
        "next_version.py --current v1.4.2 --repo owner/name",
    )
    p.add_argument("--current", help="current version or tag, e.g. v1.4.2 (default 0.0.0)", default="0.0.0")
    p.add_argument("--log", help="file with git log output (default: stdin)")
    p.add_argument("--repo", help="owner/name for commit links in the changelog")
    p.add_argument("--date", default=date.today().isoformat(), help="release date (default today)")
    p.add_argument("--pre", help="prerelease identifier, e.g. rc -> 1.5.0-rc.1")
    p.add_argument("--pre-major", action="store_true", help="on 0.x, breaking changes bump minor, not major")
    p.add_argument("--patch-for-other", action="store_true", help="release a patch for docs/chore/ci-only changes")
    p.add_argument("--include-other", action="store_true", help="list non-feat/fix commits under Other changes")
    p.add_argument("--check", action="store_true", help="lint commit subjects; exit 1 if any is not conventional")
    p.add_argument("--fail-if-none", action="store_true", help="exit 1 when there is nothing to release")
    p.add_argument("--tag-prefix", default="v", help="prefix for the printed tag (default v)")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    try:
        parse_version(args.current)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        if args.log:
            with open(args.log, encoding="utf-8") as fh:
                text = fh.read()
        else:
            text = sys.stdin.read()
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    commits = [classify(c) for c in parse_log(text)]
    commits = [c for c in commits if not SKIP_SUBJECT_RE.match(c["subject"])]

    if args.check:
        bad = [c for c in commits if not c["conventional"]]
        if args.json:
            print(json.dumps({"checked": len(commits), "invalid": [c["subject"] for c in bad]}, indent=2))
        else:
            for c in bad:
                print(f"not conventional: {c['subject']!r}  (expected 'type(scope): description')")
            print(f"{len(commits) - len(bad)}/{len(commits)} commit subjects are conventional")
        return 1 if bad else 0

    bump = bump_for(commits, args.patch_for_other)
    version = next_version(args.current, bump, args.pre_major, args.pre if bump != "none" else None)
    notes = changelog(version, commits, args.repo, args.date, args.include_other) if bump != "none" else ""
    result = {
        "current": args.current.lstrip("v"),
        "bump": bump,
        "next": version,
        "tag": f"{args.tag_prefix}{version}",
        "commits": len(commits),
        "non_conventional": sum(1 for c in commits if not c["conventional"]),
        "changelog": notes,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['current']} -> {version} ({bump}), {len(commits)} commits")
        if notes:
            print()
            print(notes, end="")
        else:
            print("Nothing to release (no feat, fix, perf or breaking commits).")
    return 1 if (args.fail_if_none and bump == "none") else 0


if __name__ == "__main__":
    sys.exit(main())
