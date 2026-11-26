import json
import shutil

from conftest import FIXTURES, ROOT, load_script, run_script

SKILL = "reusable-workflows-composite-actions"
SCRIPT = "check_reusable.py"
cr = load_script(SKILL, SCRIPT)
GOOD = FIXTURES / "reusable" / "good"
BAD = FIXTURES / "reusable" / "bad"


def checks(problems):
    return {p["check"] for p in problems}


def test_good_repo_is_clean():
    problems, stats = cr.scan(GOOD)
    assert problems == []
    assert stats == {"workflows": 2, "reusable": 1, "calls": 1, "composite": 1}


def test_bad_repo_finds_every_problem():
    problems, _ = cr.scan(BAD)
    assert {
        "reusable.undeclared_input",
        "reusable.undeclared_secret",
        "reusable.output_no_value",
        "call.invalid_keys",
        "call.input_type",
        "call.unknown_input",
        "call.missing_input",
        "call.unknown_secret",
        "call.missing_secret",
        "call.missing_file",
        "call.not_reusable",
        "action.unknown_input",
        "action.missing_input",
        "action.missing_file",
        "composite.missing_shell",
        "composite.secrets_context",
        "composite.undeclared_input",
        "composite.output_no_value",
    } == checks(problems)
    levels = {p["check"]: p["level"] for p in problems}
    assert levels["reusable.undeclared_secret"] == "warning"
    assert levels["action.unknown_input"] == "warning"


def test_inherit_skips_secret_checks(tmp_path):
    repo = tmp_path / "r"
    shutil.copytree(BAD, repo)
    caller = repo / ".github" / "workflows" / "release.yml"
    text = caller.read_text().replace(
        "    secrets:\n      DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}\n", "    secrets: inherit\n"
    )
    caller.write_text(text)
    problems, _ = cr.scan(repo)
    assert "call.missing_secret" not in checks(problems) and "call.unknown_secret" not in checks(problems)


def test_type_checks():
    assert cr.type_ok(True, "boolean") and not cr.type_ok("true", "boolean")
    assert cr.type_ok(3, "number") and not cr.type_ok(True, "number") and not cr.type_ok("3", "number")
    assert cr.type_ok("${{ inputs.x }}", "boolean") and cr.type_ok("anything", "string")


def test_workflow_dispatch_inputs_count_as_declared(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "both.yml").write_text(
        "on:\n  workflow_dispatch:\n    inputs:\n      debug:\n        type: boolean\n"
        "  workflow_call:\n    inputs:\n      env:\n        type: string\n"
        "jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ${{ inputs.debug }} ${{ inputs.env }}\n"
    )
    assert cr.scan(tmp_path)[0] == []


def test_remote_calls_are_ignored(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(
        "on: push\njobs:\n  a:\n    uses: org/ci/.github/workflows/b.yml@v1\n    with:\n      x: 1\n"
    )
    problems, stats = cr.scan(tmp_path)
    assert problems == [] and stats["calls"] == 1


def test_node_modules_action_files_skipped(tmp_path):
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "action.yml").write_text("runs:\n  using: composite\n  steps:\n    - run: echo no shell\n")
    assert cr.scan(tmp_path)[0] == []


def test_invalid_yaml_reported(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "broken.yml").write_text("on: [push\n")
    assert checks(cr.scan(tmp_path)[0]) == {"yaml.invalid"}


def test_templates_are_valid(tmp_path):
    assets = ROOT / "skills" / SKILL / "assets"
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    shutil.copy(assets / "reusable-workflow.yml", wf / "_build-test.yml")
    shutil.copy(assets / "caller-workflow.yml", wf / "ci.yml")
    action_dir = tmp_path / ".github" / "actions" / "setup-project"
    action_dir.mkdir(parents=True)
    shutil.copy(assets / "composite-action" / "action.yml", action_dir / "action.yml")
    problems, stats = cr.scan(tmp_path)
    assert problems == [] and stats["reusable"] == 1 and stats["composite"] == 1


def test_cli():
    r = run_script(SKILL, SCRIPT, str(GOOD))
    assert r.returncode == 0 and "0 errors" in r.stdout
    r = run_script(SKILL, SCRIPT, str(BAD), "--json")
    data = json.loads(r.stdout)
    assert r.returncode == 1 and data["stats"]["composite"] == 1
    assert run_script(SKILL, SCRIPT, str(BAD / "nope")).returncode == 2


def test_strict_fails_on_warnings(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "r.yml").write_text(
        "on: workflow_call\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo\n"
        "        env:\n          T: ${{ secrets.UNDECLARED }}\n"
    )
    assert run_script(SKILL, SCRIPT, str(tmp_path)).returncode == 0
    assert run_script(SKILL, SCRIPT, str(tmp_path), "--strict").returncode == 1
