---
phase: 01-pipeline-100-automatico
plan: 01
subsystem: backend
tags: [pipeline, config, db, apscheduler, admin-api]
dependency_graph:
  requires: []
  provides: [pipeline_config-table, config-endpoints, pipeline-reads-db, scheduler-reschedule]
  affects: [trigger_daily_pipeline, APScheduler daily_pipeline job]
tech_stack:
  added: []
  patterns: [INSERT ON CONFLICT DO NOTHING (idempotent seed), INSERT ON CONFLICT DO UPDATE (upsert), reschedule_job (APScheduler 3.x)]
key_files:
  created:
    - tests/test_pipeline_config.py
  modified:
    - app/backend/app.py
decisions:
  - "Stored config values as JSON strings — lists serialize cleanly and can be parsed with json.loads() without custom type logic"
  - "get_pipeline_config() falls back to module constants on any DB error — never raises, pipeline is never blocked by a config read failure"
  - "reschedule_job only called when hour or minute is present in PUT body — region/niches changes take effect on next trigger without rescheduling"
metrics:
  duration: "~15 minutes"
  completed: "2026-03-22"
  tasks_completed: 2
  files_modified: 2
---

# Phase 1 Plan 01: Pipeline Config Table and Admin Endpoints Summary

Pipeline configuration moved from hardcoded module constants to a PostgreSQL `pipeline_config` table, with `get_pipeline_config()` providing DB-backed config with module-constant fallback, and two new admin endpoints for live inspection and update.

## What Was Implemented

### pipeline_config table (app/backend/app.py, line 1433)
- `CREATE TABLE IF NOT EXISTS pipeline_config (key VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL, updated_at TIMESTAMP DEFAULT NOW())`
- Seeded with 6 default keys on `init_db()`: `daily_niches`, `daily_region`, `daily_hour`, `daily_minute`, `notify_email`, `healthcheck_url`
- `INSERT ... ON CONFLICT (key) DO NOTHING` — idempotent, runs safely on every restart

### get_pipeline_config() (app/backend/app.py, line 854)
- Reads all rows from `pipeline_config`, parses values with `json.loads()`
- Returns dict with keys: `niches` (list), `region` (str), `hour` (int), `minute` (int), `notify_email` (str|None), `healthcheck_url` (str|None)
- Full try/except fallback to `DAILY_JOB_NICHES`/`DAILY_JOB_REGION`/`DAILY_JOB_HOUR` constants on any DB error

### trigger_daily_pipeline() updated (app/backend/app.py, line 13283)
- Changed from `niches = niches or DAILY_JOB_NICHES` to `cfg = get_pipeline_config(); niches = niches or cfg['niches']`
- Same for `region_id` — reads `cfg['region']` instead of bare module constant
- Manual calls with explicit args still work (args take precedence via `or` logic)

### GET /api/admin/pipeline-config (app/backend/app.py, line 13402)
- Rate limit: 60/minute
- Auth: Bearer token required (401 if missing/invalid)
- Admin check: `is_admin = TRUE` required (403 if not admin)
- Returns: current config JSON from `get_pipeline_config()`

### PUT /api/admin/pipeline-config (app/backend/app.py, line 13420)
- Rate limit: 30/minute
- Auth: same admin-only pattern
- Accepts partial JSON body: `niches`, `region`, `hour`, `minute`, `notify_email`, `healthcheck_url`
- Persists each present key via `INSERT ... ON CONFLICT DO UPDATE`
- If `hour` or `minute` in body: calls `_scheduler.reschedule_job('daily_pipeline', ...)` with new CronTrigger
- Returns: `{"success": true}` on 200

### tests/test_pipeline_config.py
- `test_get_config_unauthenticated_returns_401` — verifies 401 without token
- `test_get_config_admin_returns_keys` — verifies 200 + expected keys + types
- `test_put_config_updates_niches` — verifies 200 + `{success: true}`
- Live-API pattern matching `tests/test_health.py` — hits `https://api.extratordedados.com.br` post-deploy

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all DB operations are fully wired. The live-API tests require a deploy to run against the live server, which is expected behavior (as noted in the plan).

## Self-Check: PASSED

Files created/modified:
- FOUND: app/backend/app.py (modified — pipeline_config table, get_pipeline_config, trigger_daily_pipeline, 2 endpoints)
- FOUND: tests/test_pipeline_config.py (created — 3 smoke tests)

Commits:
- FOUND: 60f2a56 — feat(fase1-01): add pipeline_config table to init_db() and get_pipeline_config()
- FOUND: 8356861 — feat(fase1-01): wire trigger_daily_pipeline to DB config, add GET/PUT pipeline-config endpoints
