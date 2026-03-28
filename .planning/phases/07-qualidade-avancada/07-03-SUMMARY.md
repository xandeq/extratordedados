---
phase: "07"
plan: "03"
subsystem: backend
tags: [crm-sync, quality-gate, admin-api, qual-06]
dependency_graph:
  requires: ["07-01", "07-02"]
  provides: ["QUAL-06 CRM gate in all 3 sync paths", "GET /api/admin/quality-stats endpoint"]
  affects: ["auto_sync_new_leads_background", "_run_crm_sync_batch", "crm_sync_all"]
tech_stack:
  added: []
  patterns: ["WHERE clause quality gate", "Admin endpoint with is_admin check", "get_db() context manager"]
key_files:
  created: []
  modified:
    - app/backend/app.py
decisions:
  - "Used get_db() context manager (not psycopg2.connect) for quality-stats endpoint — matches adjacent source-stats pattern"
  - "crm_sent_leads query wrapped in try/except in quality-stats — table may not exist in all environments"
  - "b.is_shared = TRUE preserved in _run_crm_sync_batch — existing condition unchanged"
  - "auto_sync uses quality_grade != 'F' as the email gate, matching the grade assigned by save_lead_to_db()"
metrics:
  duration: "~20 minutes"
  completed_date: "2026-03-28"
  tasks_completed: 3
  files_modified: 1
---

# Phase 7 Plan 03: QUAL-06 CRM Quality Gate + quality-stats Endpoint Summary

**One-liner:** Added quality gate (valid email grade!=F OR valid whatsapp) to all three CRM sync paths and implemented GET /api/admin/quality-stats with grade distribution and CRM eligibility metrics.

## What Was Built

### Task 1: QUAL-06 gate applied to all three CRM sync functions

Three WHERE clause modifications in `app/backend/app.py`:

**`auto_sync_new_leads_background()`** (line ~14685):
- Before: `WHERE batch_id = %s AND email IS NOT NULL AND email != ''`
- After: `WHERE batch_id = %s AND ((email IS NOT NULL AND email != '' AND quality_grade != 'F') OR (whatsapp IS NOT NULL AND whatsapp != ''))`

**`crm_sync_all()`** (line ~14754):
- Before: `WHERE email IS NOT NULL AND email != ''`
- After: `WHERE ((email IS NOT NULL AND email != '' AND quality_grade != 'F') OR (whatsapp IS NOT NULL AND whatsapp != ''))`
- Count query also updated for consistency

**`_run_crm_sync_batch()`** (line ~15376):
- Before: `WHERE l.email IS NOT NULL AND l.email != '' AND b.is_shared = TRUE`
- After: `WHERE b.is_shared = TRUE AND ((l.email IS NOT NULL AND l.email != '' AND l.quality_grade != 'F') OR (l.whatsapp IS NOT NULL AND l.whatsapp != ''))`
- `b.is_shared = TRUE` condition preserved

### Task 2: GET /api/admin/quality-stats endpoint

New route added after `source-stats` endpoint (line ~18164). Uses `get_db()` context manager pattern.

Returns:
- `total_leads`: total leads in DB
- `grade_distribution`: dict of {grade: count} for all non-null grades
- `leads_with_valid_email`: count with email + grade != F
- `leads_with_valid_whatsapp`: count with whatsapp non-null/non-empty
- `leads_eligible_for_crm`: count passing QUAL-06 gate
- `leads_blocked_from_crm`: total - eligible
- `leads_sent_to_crm`: count in crm_sent_leads (nullable if table missing)
- `leads_last_24h`: leads added in last 24 hours
- `crm_gate_rule`: human-readable rule description

Auth: 401 without token, 403 for non-admin users.

### Task 3: Deploy + smoke tests

- Backend deployed via `python deploy.py backend` — health check OK
- Live smoke test results:
  - Total leads: 1664
  - Eligible for CRM: 1528
  - Blocked from CRM: 136
  - Grade distribution: A=239, B=763, C=509, D=153
  - Note: 0 leads with grade F in DB (all rejected at entry by QUAL-02/03/05 guards from 07-01)
  - No-auth returns 401 as expected

## Commits

| Task | Commit | Files |
|------|--------|-------|
| Tasks 1+2+3 | f7b9496 | app/backend/app.py (+114/-10 lines) |

## Verification Results

```
grep -c "QUAL-06" app/backend/app.py     → 12 (>= 3 required)
grep -c "_is_foreign_tld" app/backend/app.py → 2 (QUAL-02, 07-01)
grep -c "crm_sent_leads" app/backend/app.py  → 3 (QUAL-04, 07-02)
pytest tests/ --tb=short                 → 25 passed, 14 skipped (0 failed)
GET /api/admin/quality-stats             → 200 OK, all required keys present
GET /api/admin/quality-stats (no auth)   → 401 Unauthorized
GET /api/health                          → status: ok
```

## Deviations from Plan

None — plan executed exactly as written.

## Phase 7 Completion Status

All QUAL requirements addressed:

| Requirement | Plan | Status |
|-------------|------|--------|
| QUAL-01 | 07-01 | Done — disposable email validation in save_lead_to_db() |
| QUAL-02 | 07-01 | Done — _is_foreign_tld() blocks .es, .pt, etc. |
| QUAL-03 | 07-01 | Done — _is_slogan_email() blocks action-verb patterns |
| QUAL-04 | 07-02 | Done — crm_sent_leads cache prevents re-sync |
| QUAL-05 | 07-01 | Done — normalize_phone_br() validates whatsapp field |
| QUAL-06 | 07-03 | Done — quality gate in all 3 CRM sync paths |

## Self-Check: PASSED
