import json

import pytest

from conftest import WORKFLOWS, load_script, run_script, wf_text

SKILL = "secrets-and-oidc"
CHECK = "oidc_check.py"
POLICY = "trust_policy.py"
oc = load_script(SKILL, CHECK)
tp = load_script(SKILL, POLICY)


def ids(findings):
    return [f["check"] for f in findings]


def run(text):
    return oc.check(oc.load_workflow(text), "wf.yml")


def test_cloud_keys_fixture():
    found = oc.check(oc.load_workflow(wf_text("cloud-keys.yml")), "cloud-keys.yml")
    per_job = {}
    for f in found:
        per_job.setdefault(f["job"], set()).add(f["check"])
    assert per_job["aws"] == {"keys.long_lived"}
    assert per_job["gcp"] == {"keys.long_lived"}
    assert per_job["azure"] == {"keys.long_lived", "secrets.in_run"}
    assert per_job["oidc-no-perm"] == {"oidc.missing_id_token", "oidc.no_environment"}


def test_good_oidc_fixture_is_clean():
    assert oc.check(oc.load_workflow(wf_text("oidc.yml")), "oidc.yml") == []


@pytest.mark.parametrize(
    "with_block,provider",
    [
        ("role-to-assume: arn:aws:iam::123456789012:role/x\n          aws-region: us-east-1", "aws"),
        ("workload_identity_provider: projects/1/locations/global/workloadIdentityPools/p/providers/g", "gcp"),
        ("client-id: abc\n          tenant-id: def\n          subscription-id: ghi", "azure"),
    ],
)
def test_oidc_providers_need_id_token(with_block, provider):
    action = {
        "aws": "aws-actions/configure-aws-credentials",
        "gcp": "google-github-actions/auth",
        "azure": "azure/login",
    }[provider]
    base = (
        "on: push\n{perms}jobs:\n  d:\n    runs-on: ubuntu-latest\n    environment: prod\n    steps:\n"
        f"      - uses: {action}@v1\n        with:\n          {with_block}\n"
    )
    missing = run(base.format(perms="permissions:\n  contents: read\n"))
    assert ids(missing) == ["oidc.missing_id_token"] and provider in missing[0]["title"]
    ok = run(base.format(perms="permissions:\n  id-token: write\n  contents: read\n"))
    assert ok == []
    assert ids(run(base.format(perms="permissions: write-all\n"))) == []


def test_workflow_level_id_token_with_many_jobs():
    text = (
        "on: push\npermissions:\n  id-token: write\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: []\n"
        "  b:\n    runs-on: ubuntu-latest\n    steps: []\n"
    )
    assert ids(run(text)) == ["oidc.workflow_level"]


def test_attest_counts_as_oidc():
    text = "on: push\npermissions:\n  contents: read\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/attest@v4\n        with:\n          subject-path: dist/*\n"
    assert ids(run(text)) == ["oidc.missing_id_token"]


def test_workflow_env_key_reported_once():
    text = (
        "on: push\nenv:\n  AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}\n"
        "jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: aws s3 ls\n"
    )
    found = run(text)
    assert ids(found) == ["keys.long_lived"] and found[0]["job"] is None


def test_ordinary_secrets_are_not_cloud_keys():
    text = (
        "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: ./notify.sh\n"
        "        env:\n          SLACK: ${{ secrets.SLACK_WEBHOOK }}\n          NPM: ${{ secrets.NPM_TOKEN }}\n"
    )
    assert run(text) == []


def test_check_cli(tmp_path):
    r = run_script(SKILL, CHECK, str(WORKFLOWS / "cloud-keys.yml"))
    assert r.returncode == 1 and "keys.long_lived" in r.stdout
    r = run_script(SKILL, CHECK, str(WORKFLOWS / "oidc.yml"), "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["findings"] == []
    r = run_script(SKILL, CHECK, str(WORKFLOWS / "cloud-keys.yml"), "--fail-on", "high", "--json")
    assert r.returncode == 1
    assert run_script(SKILL, CHECK, str(tmp_path / "none")).returncode == 2


def test_subjects():
    assert tp.subject("o/r", environment="prod") == "repo:o/r:environment:prod"
    assert tp.subject("o/r", branch="main") == "repo:o/r:ref:refs/heads/main"
    assert tp.subject("o/r", tag="v*") == "repo:o/r:ref:refs/tags/v*"
    assert tp.subject("o/r", pull_request=True) == "repo:o/r:pull_request"
    with pytest.raises(ValueError):
        tp.subject("o/r")


def test_aws_policy_exact_and_wildcard():
    exact = tp.aws_policy("123456789012", "repo:o/r:environment:prod")["Statement"][0]
    assert exact["Condition"]["StringEquals"]["token.actions.githubusercontent.com:sub"] == "repo:o/r:environment:prod"
    assert exact["Condition"]["StringEquals"]["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    assert "StringLike" not in exact["Condition"]
    wild = tp.aws_policy("123456789012", "repo:o/r:ref:refs/tags/v*")["Statement"][0]["Condition"]
    assert wild["StringLike"]["token.actions.githubusercontent.com:sub"].endswith("v*")


def test_gcp_conditions():
    assert (
        tp.gcp_condition("o/r", branch="main") == "assertion.repository == 'o/r' && assertion.ref == 'refs/heads/main'"
    )
    assert tp.gcp_condition("o/r", repo_id="42", environment="prod").startswith("assertion.repository_id == '42'")
    assert "startsWith('refs/tags/v')" in tp.gcp_condition("o/r", tag="v*")


def test_policy_cli():
    r = run_script(
        SKILL, POLICY, "aws", "--repo", "acme/web", "--environment", "production", "--account", "123456789012", "--json"
    )
    assert r.returncode == 0 and json.loads(r.stdout)["Version"] == "2012-10-17"
    r = run_script(SKILL, POLICY, "azure", "--repo", "acme/web", "--branch", "main", "--json")
    doc = json.loads(r.stdout)
    assert doc["subject"] == "repo:acme/web:ref:refs/heads/main" and doc["audiences"] == ["api://AzureADTokenExchange"]
    r = run_script(SKILL, POLICY, "gcp", "--repo", "acme/web", "--pull-request")
    assert r.returncode == 0 and "WARNING" in r.stdout and "gcloud iam workload-identity-pools" in r.stdout
    r = run_script(SKILL, POLICY, "aws", "--repo", "acme/web", "--branch", "main", "--account", "1234")
    assert r.returncode == 2
    r = run_script(SKILL, POLICY, "aws", "--repo", "acme/*", "--branch", "main", "--account", "123456789012")
    assert r.returncode == 2 and "wildcard" in r.stderr
    assert run_script(SKILL, POLICY, "azure", "--repo", "acme/web", "--tag", "v*").returncode == 2
    assert run_script(SKILL, POLICY, "aws", "--repo", "acme/web").returncode == 2  # scope required
