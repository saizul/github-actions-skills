## What does this pull request do?

<!-- One or two sentences. Link the issue: "Closes #123". -->

## Type

- [ ] New skill
- [ ] New check or option in an existing script
- [ ] Workflow / reference improvement
- [ ] Bug fix
- [ ] Repository tooling (validator, CI)

## Checklist

- [ ] `python tools/validate_skills.py` passes
- [ ] `ruff check . && ruff format --check .` passes
- [ ] `pytest` passes; new script behaviour has tests with fixtures in `tests/fixtures/`
- [ ] Scripts use the Python standard library (plus PyYAML only where they parse workflow
      YAML), support `--help`, have a `--json` option where output is structured, and exit
      non-zero on findings
- [ ] Scripts are read-only by default, make no network calls and never print secret values
- [ ] Fixtures contain no real secrets, private logs or internal hostnames (use example.com and
      fake values built so secret scanners do not match them)
- [ ] Action versions and SHAs in docs were checked against the action's repository, not recalled
- [ ] New skills: listed in `.claude-plugin/marketplace.json`, the README skills table,
      `AGENTS.md` and CHANGELOG.md
