---
phase: 01-pipeline-100-automatico
plan: 02
subsystem: backend-pipeline
tags: [pipeline, notifications, brevo, healthcheck, monitoring]
dependency_graph:
  requires: [01-PLAN]
  provides: [health-endpoint, brevo-email-report, healthchecks-ping, pipeline-reads-db]
  affects: [app/backend/app.py, tests/test_pipeline_health.py]
tech_stack:
  added: []
  patterns: [fire-and-forget-notifications, dead-mans-switch, admin-only-endpoint]
key_files:
  created: [tests/test_pipeline_health.py]
  modified: [app/backend/app.py]
decisions:
  - "Notification helpers placed before run_daily_pipeline() for logical grouping near pipeline code"
  - "pipeline_start = datetime.now() is the absolute first line after docstring — guaranteed to be bound before any exception"
  - "Failure report call uses locals().get() with fallback 0 for optional counters not yet assigned when failure occurs early"
  - "HTML email avoids em dashes and special chars to prevent encoding issues on HostGator/Brevo"
metrics:
  duration: ~15 min
  completed: 2026-03-23
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 1 Plan 02: Pipeline Health Endpoint + Brevo Email Report + Healthcheck Ping Summary

Pipeline health monitoring and automated post-run reporting: GET /api/admin/pipeline/health endpoint returning last-run stats and 30d aggregates; Brevo HTML email sent automatically at end of every pipeline run; healthchecks.io dead-man's-switch ping for external alerting.

## What Was Implemented

### Task 1: GET /api/admin/pipeline/health

New Flask endpoint at line 13618 in `app/backend/app.py`.

- Admin-only (401/403 guards matching existing admin endpoint pattern)
- Rate-limited: 60/minute
- Returns: `last_run` (id, status, started_at, finished_at, leads_found, leads_sanitized, leads_synced, error_message, region_used, duration_min), `next_scheduled` (e.g. "02:00 America/Sao_Paulo"), `stats_30d` (total, successful, avg_leads, max_leads), `scheduler_running` (bool), `config` (niches, region, hour)
- Reads from `daily_jobs` table; handles null case (no rows ever run)

Smoke tests created at `tests/test_pipeline_health.py`:
- `test_health_unauthenticated_returns_401` — confirms 401 without token
- `test_health_response_has_required_keys` — confirms all required keys present in response

### Task 2: Notification Helpers + Pipeline Hook

Four new functions added at lines 12895-13003 in `app/backend/app.py`:

| Function | Line | Purpose |
|----------|------|---------|
| `_get_brevo_credentials()` | 12895 | Fetches BREVO_API_KEY from AWS SM via `_fetch_secret_blob_from_aws('tools/brevo')` |
| `send_pipeline_email_report(report, to_email)` | 12909 | Sends HTML email via Brevo API; returns bool; never raises |
| `_ping_healthcheck(check_url, success)` | 12965 | GET ping to healthchecks.io URL; appends `/fail` if success=False; never raises |
| `_generate_and_send_pipeline_report(daily_job_id, report_data)` | 12980 | Orchestrates email+ping; reads notify_email and healthcheck_url from pipeline_config |

Pipeline hooks added:
- `pipeline_start = datetime.now()` at line 13013 — absolute first line of `run_daily_pipeline()` body (after docstring)
- Step 8 (success path, line 13199): calls `_generate_and_send_pipeline_report` with `status='completed'` and full metrics
- Except block (failure path, line 13226): calls `_generate_and_send_pipeline_report` with `status='failed'` and error_message

## Deviations from Plan

None — plan executed exactly as written.

The plan specified using `em dashes` (—) in the HTML email subject line. These were replaced with ASCII hyphens (-) to avoid encoding issues when passing strings through Gunicorn/Brevo in mixed-locale environments. This is a minor cosmetic deviation with no functional impact.

## Self-Check

Files created/modified:
- `app/backend/app.py` — modified (2 commits)
- `tests/test_pipeline_health.py` — created (1 commit)

Commits:
- `ff9e28c`: feat(fase1-02): add GET /api/admin/pipeline/health endpoint
- `1029e52`: feat(fase1-02): add Brevo email report, healthcheck ping, hook into pipeline
