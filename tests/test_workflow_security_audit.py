import json

import pytest

from conftest import FIXTURES, WORKFLOWS, load_script, run_script, wf_text

SKILL = "workflow-security-audit"
SCRIPT = "audit_workflows.py"
audit = load_script(SKILL, SCRIPT)


def checks(findings, check_id=None):
    return [f for f in findings if check_id is None or f["check"] == check_id]


def run(text, **kw):
    return audit.audit_text(text, "wf.yml", **kw)


def test_insecure_fixture_finds_everything():
    found = audit.audit_text(wf_text("insecure.yml"), "insecure.yml")
    ids = {f["check"] for f in found}
    assert {
        "prt.trigger",
        "prt.checkout_pr_code",
        "injection.run",
        "injection.script",
        "injection.input",
        "action.unpinned",
        "action.docker_unpinned",
        "permissions.missing",
        "permissions.write_all",
        "secrets.workflow_env",
        "runner.self_hosted",
    } <= ids
    crit = checks(found, "prt.checkout_pr_code")
    assert any(f["severity"] == "critical" for f in crit)
    assert any(f["severity"] == "high" for f in crit)  # gh pr checkout in run


def test_secure_fixture_is_clean():
    assert audit.audit_text(wf_text("secure.yml"), "secure.yml") == []


def test_line_numbers_point_at_the_problem():
    found = audit.audit_text(wf_text("insecure.yml"), "insecure.yml")
    lines = wf_text("insecure.yml").splitlines()
    for f in checks(found, "injection.run"):
        assert "${{" in lines[f["line"] - 1]
    pin = next(f for f in found if "some-org/setup-tool" in f["title"])
    assert "some-org/setup-tool@v2" in lines[pin["line"] - 1]


@pytest.mark.parametrize(
    "uses,severity",
    [
        ("some-org/tool@v2", "high"),
        ("some-org/tool@main", "high"),
        ("actions/checkout@v7", "low"),
        ("actions/checkout@main", "high"),
        ("github/codeql-action/init@v4", "low"),
        ("some-org/tool", "high"),
    ],
)
def test_unpinned_severity(uses, severity):
    text = f"on: push\npermissions: {{}}\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: {uses}\n"
    found = checks(run(text), "action.unpinned")
    assert len(found) == 1 and found[0]["severity"] == severity


def test_strict_makes_first_party_high():
    text = "on: push\npermissions: {}\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v7\n"
    assert checks(run(text, strict=True), "action.unpinned")[0]["severity"] == "high"


def test_sha_pins_local_and_digest_are_fine():
    sha = "0123456789abcdef" * 2 + "01234567"
    text = (
        "on: push\npermissions: {}\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        f"      - uses: some-org/tool@{sha}\n"
        "      - uses: ./.github/actions/local\n"
        "      - uses: docker://alpine@sha256:" + "ab" * 32 + "\n"
    )
    assert run(text) == []


def test_reusable_workflow_call_is_checked_and_inherit_flagged():
    text = (
        "on: push\npermissions: {}\njobs:\n  call:\n"
        "    uses: org/ci/.github/workflows/build.yml@v1\n    secrets: inherit\n"
    )
    found = run(text)
    assert checks(found, "action.unpinned") and checks(found, "secrets.inherit")
    assert not checks(found, "permissions.missing")


def test_permissions_variants():
    base = "on: push\n{perm}jobs:\n  a:\n    runs-on: ubuntu-latest\n{jobperm}    steps:\n      - run: echo hi\n  b:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
    missing = run(base.format(perm="", jobperm=""))
    assert len(checks(missing, "permissions.missing")) == 2
    write_all = run(base.format(perm="permissions: write-all\n", jobperm=""))
    assert checks(write_all, "permissions.write_all")
    broad = run(base.format(perm="permissions:\n  contents: write\n", jobperm=""))
    assert checks(broad, "permissions.broad")
    job_level = run(base.format(perm="", jobperm="    permissions:\n      contents: read\n"))
    assert [f["job"] for f in checks(job_level, "permissions.missing")] == ["b"]


@pytest.mark.parametrize(
    "expr",
    [
        "github.event.issue.title",
        "github.event.issue.body",
        "github.event.pull_request.body",
        "github.event.comment.body",
        "github.event.review.body",
        "github.event.pull_request.head.ref",
        "github.event.head_commit.message",
        "github.event.head_commit.author.email",
        "github.event.commits[0].message",
        "github.event.workflow_run.head_branch",
        "github.event.discussion.title",
        "github.head_ref",
    ],
)
def test_untrusted_contexts_in_run(expr):
    text = (
        "on: issues\npermissions: {}\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        f'      - run: echo "${{{{ {expr} }}}}"\n'
    )
    assert checks(run(text), "injection.run"), expr


@pytest.mark.parametrize("expr", ["github.sha", "github.event.pull_request.number", "github.ref_name", "matrix.os"])
def test_trusted_contexts_not_flagged(expr):
    text = (
        "on: push\npermissions: {}\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        f'      - run: echo "${{{{ {expr} }}}}"\n'
    )
    found = run(text)
    assert not checks(found, "injection.run") and not checks(found, "injection.input")


def test_env_indirection_is_safe():
    text = (
        "on: pull_request\npermissions: {}\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        '      - env:\n          T: ${{ github.event.pull_request.title }}\n        run: echo "$T"\n'
    )
    assert run(text) == []


def test_pull_request_target_without_checkout_is_info_only():
    text = (
        "on: pull_request_target\npermissions:\n  pull-requests: write\njobs:\n  a:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: gh pr edit --add-label triage\n"
    )
    found = run(text)
    assert [f["check"] for f in found] == ["prt.trigger"]


def test_workflow_run_checkout_head_sha_is_critical():
    text = (
        "on:\n  workflow_run:\n    workflows: [CI]\n    types: [completed]\npermissions: {}\njobs:\n  a:\n"
        "    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@" + "a" * 40 + "\n        with:\n"
        "          ref: ${{ github.event.workflow_run.head_sha }}\n"
    )
    assert checks(run(text), "prt.checkout_pr_code")[0]["severity"] == "critical"


def test_checkout_head_on_plain_pull_request_is_fine():
    text = (
        "on: pull_request\npermissions: {}\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@" + "a" * 40 + "\n        with:\n"
        "          ref: ${{ github.event.pull_request.head.sha }}\n"
    )
    assert not checks(run(text), "prt.checkout_pr_code")


@pytest.mark.parametrize(
    "public,trigger,severity",
    [(True, "push", "high"), (False, "pull_request", "medium"), (False, "push", "info")],
)
def test_self_hosted(public, trigger, severity):
    text = f"on: {trigger}\npermissions: {{}}\njobs:\n  a:\n    runs-on: [self-hosted, x64]\n    steps:\n      - run: make\n"
    assert checks(run(text, public=public), "runner.self_hosted")[0]["severity"] == severity


def test_runner_group_counts_as_self_hosted():
    text = "on: push\npermissions: {}\njobs:\n  a:\n    runs-on:\n      group: build-fleet\n    steps:\n      - run: make\n"
    assert checks(run(text, public=True), "runner.self_hosted")


def test_unsecure_commands_and_non_workflow_yaml():
    text = "on: push\npermissions: {}\nenv:\n  ACTIONS_ALLOW_UNSECURE_COMMANDS: true\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: make\n"
    assert checks(run(text), "commands.unsecure")
    assert run("name: not a workflow\nversion: 2\n") == []


def test_secret_value_is_never_printed():
    text = "on: push\npermissions: {}\nenv:\n  TOKEN: ${{ secrets.MY_TOKEN }}\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: make\n"
    found = run(text)
    assert checks(found, "secrets.workflow_env")
    assert "MY_TOKEN" not in json.dumps(found)  # only the env key name is reported


def test_cli_text_json_and_exit_codes(tmp_path):
    r = run_script(SKILL, SCRIPT, str(WORKFLOWS / "insecure.yml"))
    assert r.returncode == 1 and "CRITICAL" in r.stdout
    r = run_script(SKILL, SCRIPT, str(WORKFLOWS / "secure.yml"))
    assert r.returncode == 0 and "no findings" in r.stdout
    r = run_script(SKILL, SCRIPT, str(WORKFLOWS / "insecure.yml"), "--json", "--fail-on", "critical")
    data = json.loads(r.stdout)
    assert r.returncode == 1 and data["counts"]["critical"] == 1
    r = run_script(
        SKILL, SCRIPT, str(WORKFLOWS / "insecure.yml"), "--ignore", "prt.checkout_pr_code", "--fail-on", "critical"
    )
    assert r.returncode == 0
    bad = tmp_path / "bad.yml"
    bad.write_text("on: [push\njobs: {")
    assert run_script(SKILL, SCRIPT, str(bad)).returncode == 2
    assert run_script(SKILL, SCRIPT, str(tmp_path / "missing.yml")).returncode == 2


def test_repository_root_uses_dot_github_workflows(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(wf_text("insecure.yml"))
    (tmp_path / "other.yml").write_text("on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: []\n")
    data = json.loads(run_script(SKILL, SCRIPT, str(tmp_path), "--json").stdout)
    assert data["files"] == 1


def test_skill_templates_pass_their_own_audit():
    paths = [
        FIXTURES.parent.parent / "skills" / "release-automation" / "assets",
        FIXTURES.parent.parent / "skills" / "reusable-workflows-composite-actions" / "assets",
    ]
    r = run_script(SKILL, SCRIPT, *map(str, paths), "--strict", "--fail-on", "low")
    assert r.returncode == 0, r.stdout


PERSIST_WF = """
on: {on}
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
{with_block}
"""


def persist_findings(on="push", with_block=""):
    return checks(run(PERSIST_WF.format(on=on, with_block=with_block)), "checkout.persist_creds")


def test_checkout_without_persist_credentials_is_low():
    found = persist_findings()
    assert len(found) == 1
    assert found[0]["severity"] == "low"
    assert found[0]["job"] == "build"
    assert found[0]["line"] == 9


def test_checkout_with_persist_credentials_false_is_clean():
    block = "        with:\n          persist-credentials: false"
    assert persist_findings(with_block=block) == []
    quoted = "        with:\n          persist-credentials: 'false'"
    assert persist_findings(with_block=quoted) == []


def test_checkout_with_persist_credentials_true_is_flagged():
    block = "        with:\n          persist-credentials: true\n          fetch-depth: 0"
    assert len(persist_findings(with_block=block)) == 1


def test_checkout_persist_credentials_is_medium_on_privileged_trigger():
    found = persist_findings(on="pull_request_target")
    assert [f["severity"] for f in found] == ["medium"]
    assert "privileged" in found[0]["title"]


def test_checkout_persist_credentials_can_be_ignored(tmp_path):
    wf = tmp_path / "ci.yml"
    wf.write_text(PERSIST_WF.format(on="push", with_block=""), encoding="utf-8")
    result = run_script(SKILL, SCRIPT, str(wf), "--json", "--fail-on", "low", "--ignore", "checkout.persist_creds")
    assert result.returncode == 0
    assert json.loads(result.stdout)["findings"] == []
