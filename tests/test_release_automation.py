import json

import pytest

from conftest import FIXTURES, load_script, run_script

SKILL = "release-automation"
SCRIPT = "next_version.py"
nv = load_script(SKILL, SCRIPT)
LOG = FIXTURES / "release-automation" / "git-log.txt"
NO_RELEASE = FIXTURES / "release-automation" / "no-release.txt"


def commits(*subjects, body=""):
    return [nv.classify({"hash": "", "subject": s, "body": body}) for s in subjects]


@pytest.mark.parametrize(
    "subjects,body,bump",
    [
        (["fix: a"], "", "patch"),
        (["perf(db): faster"], "", "patch"),
        (["feat: a", "fix: b"], "", "minor"),
        (["feat!: drop node 18"], "", "major"),
        (["fix(api)!: rename"], "", "major"),
        (["refactor: x"], "BREAKING CHANGE: removed y", "major"),
        (["refactor: x"], "BREAKING-CHANGE: removed y", "major"),
        (["docs: a", "chore: b", "ci: c"], "", "none"),
        (["updated stuff"], "", "none"),
    ],
)
def test_bump_rules(subjects, body, bump):
    assert nv.bump_for(commits(*subjects, body=body), patch_for_other=False) == bump


def test_patch_for_other():
    assert nv.bump_for(commits("docs: a"), patch_for_other=True) == "patch"


@pytest.mark.parametrize(
    "current,bump,kw,expected",
    [
        ("1.4.2", "patch", {}, "1.4.3"),
        ("v1.4.2", "minor", {}, "1.5.0"),
        ("1.4.2", "major", {}, "2.0.0"),
        ("0.9.3", "major", {}, "1.0.0"),
        ("0.9.3", "major", {"pre_major": True}, "0.10.0"),
        ("1.4.2", "minor", {"pre": "rc"}, "1.5.0-rc.1"),
        ("1.5.0-rc.1", "fix", {"pre": "rc"}, "1.5.0-rc.2"),
        ("1.5.0-rc.2", "patch", {}, "1.5.0"),
        ("1.4.2", "none", {}, "1.4.2"),
    ],
)
def test_next_version(current, bump, kw, expected):
    assert nv.next_version(current, bump, **kw) == expected


def test_invalid_version():
    with pytest.raises(ValueError):
        nv.parse_version("1.2")


def test_parse_full_log_and_changelog():
    cs = [nv.classify(c) for c in nv.parse_log(LOG.read_text())]
    cs = [c for c in cs if not nv.SKIP_SUBJECT_RE.match(c["subject"])]
    assert len(cs) == 5 and nv.bump_for(cs, False) == "major"
    md = nv.changelog("2.0.0", cs, "acme/tool", "2026-11-26", include_other=False)
    assert md.startswith("## [2.0.0] - 2026-11-26")
    assert "### Breaking changes" in md and "Client.run was removed" in md
    assert "- **cli:** add --json output ([a1b2c3d](https://github.com/acme/tool/commit/" in md
    assert "### Bug fixes" in md and "Other changes" not in md and "Merge pull request" not in md
    assert "update README" in nv.changelog("2.0.0", cs, None, "2026-11-26", include_other=True)


def test_plain_subject_lines():
    cs = nv.parse_log("feat: x\n\nfix: y\n")
    assert [c["subject"] for c in cs] == ["feat: x", "fix: y"] and cs[0]["hash"] == ""


def test_cli_json_and_text():
    r = run_script(SKILL, SCRIPT, "--current", "v1.4.2", "--log", str(LOG), "--json", "--date", "2026-11-26")
    data = json.loads(r.stdout)
    assert r.returncode == 0 and data["next"] == "2.0.0" and data["tag"] == "v2.0.0"
    assert data["non_conventional"] == 1 and "## [2.0.0]" in data["changelog"]
    r = run_script(SKILL, SCRIPT, "--current", "1.0.0", stdin="feat: new thing\n")
    assert "1.0.0 -> 1.1.0 (minor)" in r.stdout


def test_cli_nothing_to_release():
    r = run_script(SKILL, SCRIPT, "--current", "1.0.0", "--log", str(NO_RELEASE))
    assert r.returncode == 0 and "Nothing to release" in r.stdout
    r = run_script(SKILL, SCRIPT, "--current", "1.0.0", "--log", str(NO_RELEASE), "--fail-if-none")
    assert r.returncode == 1


def test_cli_check_mode():
    r = run_script(SKILL, SCRIPT, "--check", "--log", str(LOG))
    assert r.returncode == 1 and "updated stuff" in r.stdout
    r = run_script(SKILL, SCRIPT, "--check", "--log", str(NO_RELEASE), "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["invalid"] == []


def test_cli_errors(tmp_path):
    assert run_script(SKILL, SCRIPT, "--current", "banana", stdin="").returncode == 2
    assert run_script(SKILL, SCRIPT, "--log", str(tmp_path / "missing.txt")).returncode == 2
