---
name: matrix-and-services
description: Design GitHub Actions build matrices and service containers - matrix include/exclude semantics, fail-fast, max-parallel, dynamic matrices with fromJSON, version and OS coverage, plus Postgres, MySQL, Redis, MongoDB and other service containers with health checks, ports vs container networking and connection strings. A script expands a job's matrix exactly like GitHub (product, exclude, then include rules), lists every job, and flags excludes that match nothing, includes that add unexpected jobs, matrices over the 256 limit, and service mistakes (no ports, no --health-cmd, missing POSTGRES_PASSWORD, localhost inside container jobs, services on macOS/Windows, :latest images). Use when the user writes or debugs strategy.matrix, asks "how many jobs will this create", needs a database or Redis in CI, or sees "connection refused" to a service container.
license: MIT
compatibility: Python 3.8+ with PyYAML (pip install pyyaml). Offline; reads the workflow file only.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Matrix and services

Get the job list right before pushing (include/exclude rules surprise everyone) and give
tests a database that is actually ready when they start.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- Writing or changing `strategy.matrix`; "test on Node 20/22/24 and three OSes"
- "Why does my matrix run 9 jobs instead of 6?", an `exclude` that does nothing
- Postgres/MySQL/Redis/MongoDB/RabbitMQ/Elasticsearch in CI; `connection refused`,
  `role "root" does not exist`, `database system is starting up`

## When not to use

- Cutting minutes in general (concurrency, caching): `workflow-speed`
- Sharing a matrix job across repositories: `reusable-workflows-composite-actions`
- Docker Compose based integration environments: run `docker compose up --wait` in a step
  instead of `services:` (see references)

## Workflow

1. **Write the matrix** from the requirement: list axes (`os`, `version`), then
   `exclude` impossible pairs, then `include` to add extra keys (e.g. `coverage: true`)
   or one-off jobs. Rules and examples: [references/matrix.md](references/matrix.md).
2. **Expand it** and show the user the exact job list:
   ```bash
   python3 scripts/expand_matrix.py .github/workflows/ci.yml
   python3 scripts/expand_matrix.py ci.yml --job test --count
   python3 scripts/expand_matrix.py ci.yml --json --strict
   ```
   Exit 1 = errors (or warnings with `--strict`). Typical fixes: `matrix.exclude_unmatched`
   usually means a value type mismatch (`node: 20` vs `"20"`) or a typo;
   `matrix.include_new` is right for one-off jobs, wrong when you meant to extend combos.
3. **Set strategy options:** `fail-fast: false` when each combination is informative
   (library compatibility), keep `true` for PR feedback speed; `max-parallel` only to
   protect a shared resource. Use `continue-on-error: ${{ matrix.experimental }}` for
   allowed failures.
4. **Add services** from [references/services.md](references/services.md):
   fixed image tag, required env (`POSTGRES_PASSWORD`), `--health-cmd` options so the job
   waits for healthy, and the right host:
   - job on the runner (no `container:`): `ports: ["5432:5432"]`, host `localhost`
   - job in `container:`: no ports needed, host = service name (`postgres`)
5. **Re-run the script**, then push and confirm the "Initialize containers" step shows
   the services healthy.

## Output

```
Matrix for test (ci.yml): 5 jobs
  os=ubuntu-latest node=20 | node=22 | node=24 coverage=true
  os=windows-latest node=22 | node=24
WARNING exclude {"os": "macos-latest", "node": 22} matches nothing -> remove or add macos to os

Services: postgres:17 (health: pg_isready), redis:8 (health: redis-cli ping)
Connection: DATABASE_URL=postgres://postgres:postgres@localhost:5432/app_test
Diff: (proposed)
```
