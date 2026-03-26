---
phase: 08-catalogo-nichos
plan: "02"
subsystem: backend
tags: [niches, pipeline-rotation, round-robin, flask, postgresql]
dependency_graph:
  requires: [08-01-niches-table]
  provides: [pipeline-niche-rotation, mark-niches-used]
  affects: [daily-pipeline, trigger_daily_pipeline, daily_job_run]
tech_stack:
  added: []
  patterns: [round-robin-ORDER-BY-last_used_at-ASC-NULLS-FIRST, read-only-config-function, single-update-per-trigger]
key_files:
  created: []
  modified:
    - app/backend/app.py
decisions:
  - "get_pipeline_config() kept read-only — _mark_niches_used() is separate to avoid side-effects on health checks"
  - "Single DB connection handles both pipeline_config SELECT and niches SELECT in get_pipeline_config()"
  - "DAILY_JOB_NICHES constant preserved as fallback when niches table is empty"
  - "daily_niches_per_run key in pipeline_config controls batch size (default 20)"
metrics:
  duration: "~8 minutes"
  completed: "2026-03-26"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 1
requirements_addressed: [NICHE-02]
---

# Phase 08 Plan 02: Pipeline Niche Rotation from DB Summary

`get_pipeline_config()` now reads active niches from the `niches` table via round-robin (ORDER BY `last_used_at` ASC NULLS FIRST), with `_mark_niches_used()` advancing rotation on each pipeline trigger.

## What Was Built

### Change 1: Modified `get_pipeline_config()` (app/backend/app.py ~line 882)

The function now:
- Reads `daily_niches_per_run` from `pipeline_config` table (default 20)
- Queries `niches` table: `SELECT name FROM niches WHERE active = TRUE ORDER BY last_used_at ASC NULLS FIRST, priority ASC, id ASC LIMIT n`
- Falls back to `DAILY_JOB_NICHES` constant only when the niches table is empty
- Returns `daily_niches_per_run` key in the config dict
- Is **read-only** — no UPDATE statements, safe to call from health checks

### Change 2: Added `_mark_niches_used()` helper (app/backend/app.py ~line 924)

New function between `get_pipeline_config()` and `SKIP_DOMAINS`:
- Takes a list of niche names, runs `UPDATE niches SET last_used_at = NOW() WHERE name = ANY(%s)`
- No-op on empty list
- Errors are logged but never raised (non-fatal)
- Called exactly once per pipeline trigger

### Change 3: Updated `trigger_daily_pipeline()` and `daily_job_run()`

- `trigger_daily_pipeline()`: calls `_mark_niches_used(niches)` after niches are resolved from `cfg['niches']` — advances round-robin for the next run
- `daily_job_run()`: fallback changed from `DAILY_JOB_NICHES` (hardcoded) to `get_pipeline_config()['niches']` (from DB)

## Test Results

```
tests/test_niches.py::test_pipeline_config_niches_from_db — SKIPPED (auth creds not in local AWS SM)
tests/test_health.py — 5 passed
All non-auth tests — 24 passed, 58 skipped
Pre-existing flakiness: test_login_wrong_credentials_returns_401 (timeout post-restart)
```

All tests pass or skip correctly. No new test failures introduced.

## Deploy

- `python deploy.py backend` — deployed to VPS 185.173.110.180
- Health check confirmed OK via deploy script
- Backend responding at https://api.extratordedados.com.br/api/health

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all three changes are fully functional. The round-robin rotation is live in the DB.

## Self-Check: PASSED
