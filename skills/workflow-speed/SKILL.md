---
name: workflow-speed
description: Make GitHub Actions workflows faster and cheaper - dependency and build caching (setup-* cache inputs, actions/cache keys), concurrency groups with cancel-in-progress, path filters, push+pull_request double runs, matrix trimming, timeouts, job parallelism and expensive macOS/Windows minutes. Includes a script that checks a workflow file and estimates wasted runner minutes from `gh run list --json` history (superseded, cancelled and duplicate runs, projected per 30 days). Use when the user says CI is slow, asks to cut GitHub Actions minutes or cost, sees queued or duplicate runs, hits the Actions minutes quota, or wants to tune caching, concurrency or matrix size.
license: MIT
compatibility: Python 3.8+; PyYAML (pip install pyyaml) for --workflow. Run history comes from the GitHub CLI (gh), run by the user.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Workflow speed

Measure first, then remove waste in this order: runs that should not happen, work that
is repeated, work that is serial but could be parallel. Read-only analysis; every change
is a proposed diff.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "CI takes 25 minutes", "cut our Actions bill", "we hit the minutes quota"
- Several runs of the same workflow on one branch at once, or the same commit built twice
- Choosing cache keys, `actions/cache` vs `setup-*` caching, matrix design

## When not to use

- A run fails rather than being slow: `workflow-debugging`
- Database/service container setup in tests: `matrix-and-services`
- Security of caches shared with privileged workflows: `workflow-security-audit`
- Application build performance (webpack, Gradle internals): profile the build tool itself

## Workflow

1. **Get data** (the user runs these; `gh` must be logged in):
   ```bash
   gh run list --workflow ci.yml --limit 200 \
     --json databaseId,workflowName,event,status,conclusion,headBranch,headSha,createdAt,startedAt,updatedAt > runs.json
   # optional, exact billed minutes for a few runs: gh run view <id> --json jobs
   ```
   Without job timings the script multiplies wall time by the number of jobs in the
   workflow (`--jobs-per-run` overrides), so treat the minutes as an estimate.
2. **Run the analysis.**
   ```bash
   python3 scripts/estimate_waste.py --workflow .github/workflows/ci.yml --runs runs.json
   python3 scripts/estimate_waste.py --workflow ci.yml --json
   python3 scripts/estimate_waste.py --runs runs.json --jobs-per-run 6 --max-waste-pct 15
   ```
   Exit 1 = static findings at/above `--fail-on` (default `medium`) or waste at/above
   `--max-waste-pct` (default 20).
3. **Remove runs that should not happen** (biggest wins, no risk to coverage):
   - `speed.no_concurrency` / `speed.no_cancel`: add a concurrency group that cancels
     superseded PR runs but not runs on `main`.
   - `speed.duplicate_triggers`: restrict `push` to the default branch.
   - `speed.no_path_filter`: `paths-ignore` for docs. If the job is a **required check**,
     a skipped workflow blocks merging: use a `dorny/paths-filter`-style job or a no-op job
     with the same name instead (see references).
4. **Stop repeating work.** `speed.no_cache`: `cache:` on `setup-node/python/java`,
   `actions/cache` with lockfile-hash keys for build outputs; Docker layer cache
   (`cache-from: type=gha`). Details and key design: [references/caching.md](references/caching.md).
5. **Parallelise and trim.** Split lint/test/build into parallel jobs, shard long test
   suites, `speed.matrix_size`: full matrix on `main`/nightly, small matrix on PRs.
   `speed.expensive_os`: keep only OS-specific tests on macOS/Windows.
   Patterns: [references/speed-patterns.md](references/speed-patterns.md).
6. **Guard rails.** `speed.no_timeout`: `timeout-minutes` per job (2-3x normal).
7. **Propose a diff**, apply after confirmation, then compare: re-run `gh run list` after a
   week and run the script again on the new history.

## Output

```
CI speed report: ci.yml (200 runs, 30 days)

Runner minutes: ~4,100 / 30 days, ~1,800 wasted (44%)
  superseded runs 150 | cancelled 150 | push+PR duplicates 300

Fixes, by impact:
1. concurrency + cancel-in-progress for PRs          saves ~150 min/30d
2. push: branches [main] (PR commits ran twice)      saves ~300 min/30d
3. setup-python cache: pip, setup-node cache: npm    ~1-2 min per job
4. matrix 14 -> 4 jobs on PRs, full matrix nightly   ~70% of test minutes on PRs
5. timeout-minutes: 20 on test

Diff: (proposed)
```
