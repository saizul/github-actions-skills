import json
import shutil

import pytest

from conftest import FIXTURES, WORKFLOWS, load_script, run_script

SKILL = "dependabot-and-pinning"
PIN = "pin_actions.py"
GEN = "dependabot_gen.py"
pa = load_script(SKILL, PIN)
dg = load_script(SKILL, GEN)
DP = FIXTURES / "dependabot-and-pinning"
CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
NODE_SHA = "949feb2413d6458794dcd2491c4babbbce0c15c1"


def test_load_mapping_formats():
    m = pa.load_mapping(DP / "pins.json")
    assert m["actions/checkout@v7"] == CHECKOUT_SHA and m["actions/setup-node@v7"] == NODE_SHA
    t = pa.load_mapping(DP / "pins.txt")
    assert set(t) == {"actions/setup-python@v7", "aws-actions/configure-aws-credentials@v6"}


@pytest.mark.parametrize(
    "content,message",
    [
        ('{"actions/checkout@v7": "abc123"}', "40-character"),
        ('{"actions/checkout": "' + "a" * 40 + '"}', "needs @ref"),
        ("actions/checkout v7 sha\n", "expected"),
    ],
)
def test_bad_mappings(tmp_path, content, message):
    f = tmp_path / "m"
    f.write_text(content)
    with pytest.raises(ValueError, match=message):
        pa.load_mapping(f)


def test_process_rewrites_and_classifies():
    text = (WORKFLOWS / "tags.yml").read_text()
    new, items = pa.process(text, pa.load_mapping(DP / "pins.json"))
    status = {(i["action"], i["ref"][:7]): i["status"] for i in items}
    assert status[("actions/checkout", "v7")] == "pinnable"
    assert status[("actions/setup-node", "v7")] == "pinnable"
    assert status[("some-org/unknown-action", "v1")] == "unresolved"
    assert status[("acme/ci/.github/workflows/build.yml", "v2")] == "unresolved"
    assert status[("actions/cache", CHECKOUT_SHA[:7])] == "pinned_no_comment"
    assert status[("actions/checkout", CHECKOUT_SHA[:7])] == "pinned"
    assert f"      - uses: actions/checkout@{CHECKOUT_SHA} # v7\n" in new
    assert f'        uses: "actions/setup-node@{NODE_SHA}" # v7 - keep comment\n' in new
    assert "./.github/actions/local" in new and "docker://alpine:3.20" in new
    assert len(items) == 6  # local and docker skipped


def test_subpath_actions_use_repo_key():
    mapping = {"github/codeql-action@v4": "b" * 40}
    new, items = pa.process("      - uses: github/codeql-action/init@v4\n", mapping)
    assert new == f"      - uses: github/codeql-action/init@{'b' * 40} # v4\n"


def test_comment_suggested_for_bare_sha():
    _, items = pa.process(f"  - uses: actions/checkout@{CHECKOUT_SHA}\n", {"actions/checkout@v7.0.1": CHECKOUT_SHA})
    assert items[0]["status"] == "pinned_no_comment" and items[0]["suggested_comment"] == "v7.0.1"


def test_crlf_preserved():
    new, _ = pa.process("- uses: actions/checkout@v7\r\n", {"actions/checkout@v7": CHECKOUT_SHA})
    assert new.endswith(" # v7\r\n")


def test_resolve_script():
    script = pa.resolve_script({("actions/checkout", "v7")})
    assert "git ls-remote https://github.com/actions/checkout 'refs/tags/v7^{}'" in script
    assert 'echo "actions/checkout@v7 $sha" >> pins.txt' in script


def test_cli_dry_run_write_and_exit_codes(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    target = wf / "tags.yml"
    shutil.copy(WORKFLOWS / "tags.yml", target)
    before = target.read_text()
    r = run_script(SKILL, PIN, str(tmp_path), "--map", str(DP / "pins.json"), "--diff")
    assert r.returncode == 1 and "PIN " in r.stdout and "+      - uses: actions/checkout@" in r.stdout
    assert target.read_text() == before  # dry run
    r = run_script(SKILL, PIN, str(tmp_path), "--map", str(DP / "pins.json"), "--write", "--json")
    data = json.loads(r.stdout)
    assert data["written"] and data["counts"]["pinnable"] == 2 and r.returncode == 1  # 2 unresolved remain
    assert CHECKOUT_SHA in target.read_text()
    target.write_text(target.read_text().replace("      - uses: some-org/unknown-action@v1\n", ""))
    target.write_text(
        target.read_text().replace("    uses: acme/ci/.github/workflows/build.yml@v2\n", "    uses: ./x.yml\n")
    )
    r = run_script(SKILL, PIN, str(tmp_path))
    assert r.returncode == 0, r.stdout
    r = run_script(SKILL, PIN, str(WORKFLOWS / "tags.yml"), "--resolve-script")
    assert r.stdout.startswith("#!/bin/sh") and "some-org/unknown-action" in r.stdout
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    assert run_script(SKILL, PIN, str(target), "--map", str(bad)).returncode == 2
    assert run_script(SKILL, PIN, str(tmp_path / "missing")).returncode == 2


def test_detect_fixture_repo(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(DP / "repo", repo)
    nm = repo / "node_modules" / "left-pad"
    nm.mkdir(parents=True)
    (nm / "package.json").write_text("{}")
    (nm / "Dockerfile").write_text("FROM scratch\n")
    eco = dg.detect(repo)
    assert eco == {
        "github-actions": ["/"],
        "npm": ["/"],
        "pip": ["/apps/api"],
        "uv": ["/tools/uvtool"],
        "gomod": ["/services/worker"],
        "docker": ["/apps/api", "/services/worker"],
        "terraform": ["/infra"],
    }


def test_detect_other_ecosystems(tmp_path):
    for name in ["Cargo.toml", "Gemfile", "composer.json", "pom.xml", "app.csproj", "compose.yaml", ".gitmodules"]:
        (tmp_path / name).write_text("x")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text("{}")
    (tmp_path / "web" / "bun.lock").write_text("{}")
    (tmp_path / ".devcontainer").mkdir()
    eco = dg.detect(tmp_path)
    for e in [
        "cargo",
        "bundler",
        "composer",
        "maven",
        "nuget",
        "docker-compose",
        "gitsubmodule",
        "devcontainers",
        "bun",
    ]:
        assert e in eco, e
    assert "npm" not in eco  # bun owns that folder


def test_package_json_without_lockfile_means_npm(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert dg.detect(tmp_path) == {"npm": ["/"]}


def test_render_yaml_shape():
    out = dg.render({"github-actions": ["/"], "docker": ["/a", "/b"]}, cooldown=3, limit=5, labels=["deps"])
    assert out.startswith("# Generated") and "version: 2\nupdates:\n" in out
    assert '    directories:\n      - "/a"\n      - "/b"\n' in out
    assert "      default-days: 3\n" in out and "open-pull-requests-limit: 5" in out
    assert 'prefix: "ci"' in out and 'patterns: ["*"]' in out
    assert "groups" not in dg.render({"npm": ["/"]}, group=False)
    try:
        import yaml
    except ImportError:
        return
    data = yaml.safe_load(out)
    assert [u["package-ecosystem"] for u in data["updates"]] == ["github-actions", "docker"]
    assert data["updates"][1]["directories"] == ["/a", "/b"]
    for u in data["updates"]:
        for gname in u["groups"]:
            assert gname[0].isalpha() and gname[-1].isalpha()


def test_gen_cli(tmp_path):
    r = run_script(SKILL, GEN, str(DP / "repo"), "--json")
    assert r.returncode == 0 and "terraform" in json.loads(r.stdout)
    r = run_script(SKILL, GEN, str(DP / "repo"), "--check", str(DP / "dependabot-partial.yml"))
    assert r.returncode == 1 and "MISSING pip" in r.stdout and "EXTRA   bundler" in r.stdout
    out = tmp_path / ".github" / "dependabot.yml"
    r = run_script(SKILL, GEN, str(DP / "repo"), "--output", str(out))
    assert r.returncode == 0 and out.is_file()
    assert run_script(SKILL, GEN, str(DP / "repo"), "--output", str(out)).returncode == 2  # no overwrite
    assert run_script(SKILL, GEN, str(DP / "repo"), "--output", str(out), "--force").returncode == 0
    r = run_script(SKILL, GEN, str(DP / "repo"), "--check", str(out))
    assert r.returncode == 0
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run_script(SKILL, GEN, str(empty)).returncode == 2
    assert run_script(SKILL, GEN, str(tmp_path / "nope")).returncode == 2
