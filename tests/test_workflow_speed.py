import json

import pytest

from conftest import FIXTURES, WORKFLOWS, load_script, run_script, wf_text

SKILL = "workflow-speed"
SCRIPT = "estimate_waste.py"
ew = load_script(SKILL, SCRIPT)
RUNS = FIXTURES / "workflow-speed" / "runs.json"


def ids(findings):
    return {f["check"] for f in findings}


def test_slow_workflow_findings():
    found = ew.static_findings(ew.load_workflow(wf_text("slow.yml")))
    assert {
        "speed.no_concurrency",
        "speed.duplicate_triggers",
        "speed.no_path_filter",
        "speed.no_cache",
        "speed.matrix_size",
        "speed.no_timeout",
        "speed.expensive_os",
    } <= ids(found)
    os_jobs = {f["job"] for f in found if f["check"] == "speed.expensive_os"}
    assert os_jobs == {"test", "lint"}  # test via matrix.os, lint via runs-on


def test_fast_workflow_has_no_medium_findings():
    found = ew.static_findings(ew.load_workflow(wf_text("secure.yml")))
    assert all(f["severity"] in ("info", "low") for f in found)
    assert "speed.no_concurrency" not in ids(found) and "speed.no_cache" not in ids(found)


def test_concurrency_without_cancel():
    wf = ew.load_workflow(
        "on: [pull_request]\nconcurrency:\n  group: x\njobs:\n  a:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps: []\n"
    )
    assert "speed.no_cancel" in ids(ew.static_findings(wf))


def test_push_limited_to_main_is_not_duplicate():
    wf = ew.load_workflow(
        "on:\n  push:\n    branches: [main]\n  pull_request:\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: []\n"
    )
    assert "speed.duplicate_triggers" not in ids(ew.static_findings(wf))


@pytest.mark.parametrize(
    "step,flagged",
    [
        ("uses: actions/setup-node@v7\n        with:\n          node-version: 22", True),
        ("uses: actions/setup-node@v7\n        with:\n          cache: pnpm", False),
        ("uses: actions/setup-python@v7", True),
        ("uses: ruby/setup-ruby@v1\n        with:\n          bundler-cache: true", False),
        ("uses: actions/setup-go@v7", False),
        ("uses: actions/setup-go@v7\n        with:\n          cache: false", True),
    ],
)
def test_cache_detection(step, flagged):
    wf = ew.load_workflow(f"on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - {step}\n")
    assert ("speed.no_cache" in ids(ew.static_findings(wf))) is flagged


def test_actions_cache_step_counts_as_caching():
    wf = ew.load_workflow(
        "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/cache@v6\n"
        "      - uses: actions/setup-python@v7\n"
    )
    assert "speed.no_cache" not in ids(ew.static_findings(wf))


def test_matrix_expansion_and_job_count():
    wf = ew.load_workflow(wf_text("slow.yml"))
    combos = ew.expand_matrix(wf["jobs"]["test"]["strategy"]["matrix"])
    assert len(combos) == 14  # 3 x 5 - 1 excluded
    assert ew.job_count(wf) == 15
    assert ew.expand_matrix("${{ fromJSON(x) }}") is None


def test_run_analysis_numbers():
    runs = json.loads(RUNS.read_text())
    res = ew.analyse_runs(runs, jobs_per_run=1)
    assert res["runs"] == 6
    assert res["breakdown"] == {"superseded": 10.0, "cancelled": 10.0, "duplicate_push_pr": 20.0}
    assert res["superseded_runs"] == [101]
    assert res["duplicate_commits"] == ["a3"]
    # run 106 has job timings: ceil(10.5) + 2 = 13 billed minutes
    assert res["total_minutes"] == 20 + 20 + 20 + 20 + 10 + 13
    assert res["days"] == 10.0 and res["per_30_days"]["waste_minutes"] == 120
    assert res["estimated"] is True


def test_jobs_per_run_multiplies_wall_time():
    runs = json.loads(RUNS.read_text())
    one = ew.analyse_runs(runs, 1)["total_minutes"]
    three = ew.analyse_runs(runs, 3)["total_minutes"]
    assert three == (one - 13) * 3 + 13


def test_short_window_has_no_projection():
    runs = json.loads(RUNS.read_text())[:2]
    assert ew.analyse_runs(runs)["per_30_days"]["waste_minutes"] is None


def test_cli_combined_and_exit_codes(tmp_path):
    r = run_script(SKILL, SCRIPT, "--workflow", str(WORKFLOWS / "slow.yml"), "--runs", str(RUNS))
    assert r.returncode == 1 and "Waste:" in r.stdout and "speed.no_concurrency" in r.stdout
    r = run_script(SKILL, SCRIPT, "--runs", str(RUNS), "--json", "--max-waste-pct", "90")
    assert r.returncode == 0 and json.loads(r.stdout)["runs"]["waste_minutes"] == 40.0
    r = run_script(SKILL, SCRIPT, "--workflow", str(WORKFLOWS / "secure.yml"))
    assert r.returncode == 0
    assert run_script(SKILL, SCRIPT).returncode == 2  # argparse error: no input
    bad = tmp_path / "runs.json"
    bad.write_text('{"x": 1}')
    assert run_script(SKILL, SCRIPT, "--runs", str(bad)).returncode == 0  # dict without runs -> empty
    bad.write_text("not json")
    assert run_script(SKILL, SCRIPT, "--runs", str(bad)).returncode == 2
    notwf = tmp_path / "x.yml"
    notwf.write_text("a: 1\n")
    assert run_script(SKILL, SCRIPT, "--workflow", str(notwf)).returncode == 2


def test_api_shape_workflow_runs_key(tmp_path):
    runs = []
    for r in json.loads(RUNS.read_text()):
        runs.append(
            {
                "id": r["databaseId"],
                "name": r["workflowName"],
                "event": r["event"],
                "conclusion": r["conclusion"],
                "head_branch": r["headBranch"],
                "head_sha": r["headSha"],
                "created_at": r["createdAt"],
                "run_started_at": r["startedAt"],
                "updated_at": r["updatedAt"],
            }
        )
    f = tmp_path / "api.json"
    f.write_text(json.dumps({"total_count": len(runs), "workflow_runs": runs}))
    r = run_script(SKILL, SCRIPT, "--runs", str(f), "--json", "--max-waste-pct", "100")
    res = json.loads(r.stdout)["runs"]
    assert res["runs"] == 6 and res["breakdown"]["superseded"] > 0 and res["duplicate_commits"] == ["a3"]
