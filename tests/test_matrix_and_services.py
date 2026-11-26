import json

import pytest

from conftest import WORKFLOWS, load_script, run_script, wf_text

SKILL = "matrix-and-services"
SCRIPT = "expand_matrix.py"
em = load_script(SKILL, SCRIPT)


def matrix_of(job):
    return em.load_workflow(wf_text("matrix.yml"))["jobs"][job]["strategy"]["matrix"]


def test_github_docs_include_example():
    # Example from the GitHub docs "Expanding or adding matrix configurations"
    combos = em.expand(matrix_of("docs-example"))["combos"]
    assert combos == [
        {"fruit": "apple", "animal": "cat", "color": "pink", "shape": "circle"},
        {"fruit": "apple", "animal": "dog", "color": "green", "shape": "circle"},
        {"fruit": "pear", "animal": "cat", "color": "pink"},
        {"fruit": "pear", "animal": "dog", "color": "green"},
        {"fruit": "banana"},
        {"fruit": "banana", "animal": "cat"},
    ]


def test_exclude_and_include_extra_key():
    res = em.expand(matrix_of("versions"))
    assert len(res["combos"]) == 5
    assert {"os": "ubuntu-latest", "node": 24, "coverage": True} in res["combos"]
    assert {"os": "windows-latest", "node": 20} not in res["combos"]
    assert res["unmatched_excludes"] == [{"os": "macos-latest", "node": 22}]


def test_type_mismatch_exclude_is_unmatched():
    res = em.expand({"node": [20, 22], "exclude": [{"node": "20"}]})
    assert len(res["combos"]) == 2 and res["unmatched_excludes"]


def test_include_only_matrix():
    res = em.expand({"include": [{"python": "3.10"}, {"python": "3.13", "django": "5.2"}]})
    assert len(res["combos"]) == 2 and len(res["new_includes"]) == 2


@pytest.mark.parametrize(
    "matrix", ["${{ fromJSON(x) }}", {"pkg": "${{ fromJSON(x) }}"}, {"a": [1], "include": "${{ x }}"}]
)
def test_dynamic(matrix):
    assert em.expand(matrix)["dynamic"] is True


def test_matrix_limits():
    wf = {
        "jobs": {
            "big": {"runs-on": "ubuntu-latest", "strategy": {"matrix": {"a": list(range(17)), "b": list(range(16))}}}
        }
    }
    res = em.analyse(wf, None, 20)
    assert res["jobs"][0]["count"] == 272
    assert res["problems"][0]["level"] == "error"
    wf["jobs"]["big"]["strategy"]["matrix"] = {"a": list(range(5)), "b": list(range(5))}
    assert em.analyse(wf, None, 20)["problems"][0]["level"] == "warning"


def test_services_problems():
    res = em.analyse(em.load_workflow(wf_text("services.yml")), None, 20)
    by_job = {}
    for p in res["problems"]:
        by_job.setdefault(p["job"], set()).add(p["check"])
    assert "good" not in by_job
    assert by_job["bad"] == {
        "services.floating_tag",
        "services.no_ports",
        "services.no_healthcheck",
        "services.no_password",
    }
    assert by_job["in-container"] == {"services.localhost_in_container"}
    assert by_job["mac"] == {"services.non_linux"}


def test_password_alternatives_accepted():
    job = {
        "runs-on": "ubuntu-latest",
        "services": {
            "pg": {
                "image": "postgres:17",
                "ports": ["5432:5432"],
                "env": {"POSTGRES_HOST_AUTH_METHOD": "trust"},
                "options": "--health-cmd pg_isready",
            },
            "my": {
                "image": "mariadb:11",
                "ports": ["3306:3306"],
                "env": {"MARIADB_ALLOW_EMPTY_ROOT_PASSWORD": "1"},
                "options": "--health-cmd 'healthcheck.sh --connect'",
            },
        },
    }
    assert em.check_services("j", job) == []


def test_image_name_parsing():
    assert em.image_name("postgres:17") == ("postgres", "17")
    assert em.image_name("ghcr.io/org/redis") == ("redis", None)
    assert em.image_name("postgres@sha256:" + "a" * 64) == ("postgres", "digest")


def test_cli():
    r = run_script(SKILL, SCRIPT, str(WORKFLOWS / "matrix.yml"))
    assert r.returncode == 0 and "docs-example: 6 job(s)" in r.stdout and "fruit=banana" in r.stdout
    r = run_script(SKILL, SCRIPT, str(WORKFLOWS / "matrix.yml"), "--strict")
    assert r.returncode == 1  # unmatched exclude warning
    r = run_script(SKILL, SCRIPT, str(WORKFLOWS / "matrix.yml"), "--job", "versions", "--count", "--json")
    data = json.loads(r.stdout)
    assert [j["job"] for j in data["jobs"]] == ["versions"] and data["jobs"][0]["count"] == 5
    r = run_script(SKILL, SCRIPT, str(WORKFLOWS / "matrix.yml"), "--job", "versions", "--count")
    assert "versions: 5 job(s)" in r.stdout and "os=" not in r.stdout
    assert run_script(SKILL, SCRIPT, str(WORKFLOWS / "services.yml")).returncode == 1
    assert run_script(SKILL, SCRIPT, str(WORKFLOWS / "matrix.yml"), "--job", "nope").returncode == 2
    assert run_script(SKILL, SCRIPT, str(WORKFLOWS / "missing.yml")).returncode == 2
