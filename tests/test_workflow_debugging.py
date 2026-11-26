import json
import zipfile

import pytest

from conftest import FIXTURES, load_script, run_script

SKILL = "workflow-debugging"
SCRIPT = "parse_run_log.py"
pl = load_script(SKILL, SCRIPT)
DBG = FIXTURES / "workflow-debugging"


def sig_ids(res):
    return {h["id"] for h in res["signatures"]}


def test_gh_log_failed_format():
    res = pl.analyse(pl.read_input(str(DBG / "gh-log-failed.txt")))
    assert res["jobs"] == ["label", "test"]
    assert res["first_error"]["job"] == "test" and res["first_error"]["step"] == "Run npm ci"
    assert any("can only install packages" in c for c in res["first_error"]["context"])
    assert {"lockfile", "npm_error", "permissions", "deprecated_runtime"} <= sig_ids(res)
    assert res["exit_codes"][0]["code"] == 1
    assert res["signatures"][0]["level"] == "error"  # errors sorted first


def test_raw_log_steps_and_details():
    res = pl.analyse(pl.read_input(str(DBG / "raw-step.log")))
    assert res["first_error"]["step"] == "python -m pytest"
    mod = next(h for h in res["signatures"] if h["id"] == "python_module")
    assert mod["detail"] == "requests"
    assert {"tests_failed", "cache_miss"} <= sig_ids(res)


def test_timestamps_are_stripped():
    assert pl.strip_ts("2026-11-20T09:00:00.1234567Z hello") == "hello"
    assert pl.strip_ts("\ufeff2026-11-20T09:00:00Z hello") == "hello"
    assert pl.strip_ts("no timestamp") == "no timestamp"


@pytest.mark.parametrize(
    "line,sid",
    [
        ("Error: Unable to get ACTIONS_ID_TOKEN_REQUEST_URL env variable", "oidc.no_id_token"),
        ("Error: Not authorized to perform sts:AssumeRoleWithWebIdentity", "oidc.aws_trust"),
        ("AADSTS70021: No matching federated identity record found", "oidc.azure_trust"),
        ("FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory", "oom"),
        ("##[error]Process completed with exit code 137.", "oom"),
        ("OSError: [Errno 28] No space left on device", "disk_full"),
        ("##[error]The job running on runner X has exceeded the maximum execution time of 360 minutes.", "timeout"),
        ("##[error]The operation was canceled.", "cancelled"),
        ("Error: Unable to resolve action `some/action@v9`, unable to find version `v9`", "action_resolve"),
        ("Error: Input required and not supplied: token", "input_required"),
        ("HttpError: Bad credentials", "bad_credentials"),
        ("API rate limit exceeded for installation ID 1", "rate_limit"),
        ("toomanyrequests: You have reached your pull rate limit.", "rate_limit"),
        ("fatal: could not read Username for 'https://github.com': terminal prompts disabled", "git_auth"),
        ("remote: error: GH006: Protected branch update failed for refs/heads/main.", "protected_branch"),
        ("npm error code ETIMEDOUT", "network"),
        ("ERR_PNPM_OUTDATED_LOCKFILE  Cannot install with frozen-lockfile", "lockfile"),
        ("ERROR: Could not find a version that satisfies the requirement foo==9.9", "pip_resolve"),
        ("/home/runner/work/_temp/x.sh: line 1: jq2: command not found", "command_not_found"),
        ("exec /usr/bin/app: exec format error", "exec_format"),
        ("x.sh: line 3: syntax error near unexpected token `('", "shell_syntax"),
        ("/bin/sh: ./deploy.sh: Permission denied", "permission_denied"),
        ("Error: Matrix must define at least one vector", "matrix_empty"),
        ("Error: Unable to download artifact(s): Artifact not found for name: dist", "artifact_missing"),
        ("--- FAIL: TestParse (0.00s)", "tests_failed"),
        ("Tests:       2 failed, 10 passed, 12 total", "tests_failed"),
        ("The `set-output` command is deprecated and will be disabled soon.", "deprecated_runtime"),
        ("##[error]Resource not accessible by integration", "permissions"),
        ("Error: Failed to initialize container postgres:17", "service_unhealthy"),
    ],
)
def test_signatures(line, sid):
    res = pl.analyse(pl.records_from_text(f"2026-11-20T09:00:00.0000000Z {line}\n"))
    assert sid in sig_ids(res), (line, sig_ids(res))


def test_publickey_is_git_auth_not_permission_denied():
    res = pl.analyse(pl.records_from_text("git@github.com: Permission denied (publickey).\n"))
    assert sig_ids(res) == {"git_auth"}


def test_signature_deduplicated_per_job():
    text = "".join("npm error code E404\n" for _ in range(5))
    assert len(pl.analyse(pl.records_from_text(text))["signatures"]) == 1


def make_archive_files():
    return {
        "0_build.txt": "2026-11-20T09:00:00Z duplicate of all steps\n2026-11-20T09:00:00Z ENOSPC\n",
        "build/1_Set up job.txt": "2026-11-20T09:00:00Z Current runner version\n",
        "build/2_Run make.txt": "2026-11-20T09:00:01Z make: *** No space left on device\n"
        "2026-11-20T09:00:02Z ##[error]Process completed with exit code 2.\n",
        "lint/1_Run lint.txt": "2026-11-20T09:00:01Z all good\n",
    }


def test_zip_archive(tmp_path):
    z = tmp_path / "logs.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name, content in make_archive_files().items():
            zf.writestr(name, content)
    res = pl.analyse(pl.read_input(str(z)))
    assert res["jobs"] == ["build", "lint"]
    disk = next(h for h in res["signatures"] if h["id"] == "disk_full")
    assert disk["job"] == "build" and disk["step"] == "Run make"
    assert all("duplicate" not in r for r in json.dumps(res).split("match"))


def test_extracted_folder(tmp_path):
    root = tmp_path / "logs"
    for name, content in make_archive_files().items():
        f = root / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    res = pl.analyse(pl.read_input(str(root)))
    assert res["first_error"]["job"] == "build" and res["first_error"]["step"] == "Run make"


def test_cli(tmp_path):
    r = run_script(SKILL, SCRIPT, str(DBG / "gh-log-failed.txt"))
    assert r.returncode == 1 and "First error in test / Run npm ci" in r.stdout and "lockfile" in r.stdout
    r = run_script(SKILL, SCRIPT, str(DBG / "raw-step.log"), "--json")
    assert r.returncode == 1 and json.loads(r.stdout)["first_error"]["line"].startswith("Process completed")
    r = run_script(SKILL, SCRIPT, str(DBG / "raw-step.log"))
    assert "cache_miss" not in r.stdout
    r = run_script(SKILL, SCRIPT, str(DBG / "raw-step.log"), "--all")
    assert "cache_miss" in r.stdout
    r = run_script(SKILL, SCRIPT, str(DBG / "clean.log"))
    assert r.returncode == 0 and "No known error signatures" in r.stdout
    r = run_script(SKILL, SCRIPT, "-", stdin="Error: Input required and not supplied: token\n")
    assert r.returncode == 1 and "input_required" in r.stdout
    assert run_script(SKILL, SCRIPT, str(tmp_path / "missing.log")).returncode == 2
