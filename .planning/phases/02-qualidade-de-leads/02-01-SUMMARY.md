---
phase: 02-qualidade-de-leads
plan: "01"
subsystem: backend
tags: [db-migration, lead-quality, dedup, testing, wave-0]
dependency_graph:
  requires: []
  provides:
    - "captured_at, last_verified_at, freshness_score, quality_grade columns on leads table"
    - "idx_leads_email_global partial unique index (replaces per-batch UNIQUE)"
    - "tests/test_lead_quality.py Wave 0 scaffold (14 tests)"
    - "Phase 2 stub endpoints: validate-email-free, normalize-phone, validate-batch, verify-email"
  affects:
    - "leads table schema"
    - "GET /api/leads response shape (quality_grade field added)"
    - "all INSERT INTO leads statements (ON CONFLICT removed)"
tech_stack:
  added:
    - "email-validator>=2.3.0"
    - "disposable-email-domains>=0.0.169"
    - "phonenumbers>=9.0.26"
  patterns:
    - "ADD COLUMN IF NOT EXISTS in ALTER TABLE loop (avoids rollback issue in multi-column migrations)"
    - "Global partial unique index on leads(email) with .local exclusions"
    - "try/except UniqueViolation pattern replacing ON CONFLICT (batch_id, email)"
key_files:
  created:
    - "tests/test_lead_quality.py"
  modified:
    - "app/backend/requirements.txt"
    - "app/backend/app.py"
decisions:
  - "Used ADD COLUMN IF NOT EXISTS instead of catching DuplicateColumn — avoids transaction rollback silently losing column additions"
  - "Added Phase 2 stub endpoints (return 501 when authenticated) so auth-gate tests pass immediately in Wave 0"
  - "Added quality_grade to SHARED_LEADS_SELECT and lead_row_to_dict to support test_quality_grade_field_present_in_lead"
  - "Dedup ran manually on VPS (157 duplicates removed) because init_db had rollback issue pre-fix"
metrics:
  duration: "~16 min"
  completed_date: "2026-03-23"
  tasks: "2/2"
  files: "3"
---

# Phase 02 Plan 01: DB Foundation + Wave 0 Test Scaffold Summary

Wave 0 foundation for Phase 2 lead quality: test scaffold, package pins, DB schema migrations, cross-batch dedup, global unique index, and stub endpoints for the 4 new Phase 2 API routes.

## What Was Built

**Test scaffold (tests/test_lead_quality.py):** 14 test functions — 8 live smoke tests + 6 skipped unit stubs. Auth-gate tests confirm the 4 new endpoints require authentication. Unit stubs (marked skip) will be unskipped in Wave 2 when `validate_email_free()`, `normalize_phone_br()`, `compute_lead_quality_score()` are implemented.

**Package pins (requirements.txt):** Added `email-validator>=2.3.0`, `disposable-email-domains>=0.0.169`, `phonenumbers>=9.0.26`. Module-level imports added with availability flags for graceful degradation if packages are missing.

**DB migrations (init_db in app.py):**
- 4 new columns: `captured_at TIMESTAMPTZ`, `last_verified_at TIMESTAMPTZ`, `freshness_score INTEGER DEFAULT 100`, `quality_grade CHAR(1)`
- Backfill: `UPDATE leads SET captured_at = extracted_at WHERE captured_at IS NULL`
- Dedup: DRY-RUN count then DELETE (157 real duplicates removed from live DB)
- Constraint drop: `ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_batch_id_email_key`
- Global index: `CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_email_global ON leads(email) WHERE ...`

**ON CONFLICT cleanup:** All 9 occurrences of `ON CONFLICT (batch_id, email) DO NOTHING` replaced with try/except UniqueViolation pattern.

**Phase 2 stub endpoints:** 4 routes added that return 401 unauthenticated / 501 authenticated:
- `POST /api/leads/validate-email-free`
- `POST /api/leads/normalize-phone`
- `POST /api/leads/validate-batch`
- `POST /api/leads/<int:lead_id>/verify-email`

**quality_grade in lead responses:** Added `l.quality_grade` to `SHARED_LEADS_SELECT` and `lead_row_to_dict` (row[28]) so the API returns the field (null until Wave 2 scoring runs).

## Test Results

```
tests/test_health.py .....      (5 passed)
tests/test_lead_quality.py ........ssssss  (8 passed, 6 skipped)
Total: 13 passed, 6 skipped
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ALTER TABLE loop using DuplicateColumn catch causing silent rollbacks**
- **Found during:** Task 2 deploy
- **Issue:** The `new_columns` loop used `except psycopg2.errors.DuplicateColumn: conn.rollback()` — after rollback, previously-added columns in the same transaction were lost. Phase 2 columns weren't reaching the DB.
- **Fix:** Changed to `ALTER TABLE leads ADD COLUMN IF NOT EXISTS` with `except Exception` — no rollback needed, transaction stays clean
- **Files modified:** `app/backend/app.py`
- **Commit:** `54e879f`

**2. [Rule 2 - Missing Functionality] Added Phase 2 stub endpoints so auth-gate tests pass in Wave 0**
- **Found during:** Task 1 live test run
- **Issue:** Tests for `validate-email-free`, `normalize-phone`, `validate-batch`, `verify-email` expected 401 from unauthenticated requests, but endpoints didn't exist → returned 404 (test failure)
- **Fix:** Added 4 stub endpoints that check auth and return 401 (unauthenticated) or 501 (authenticated, Wave 2 pending)
- **Files modified:** `app/backend/app.py`
- **Commit:** `1ce7f80`

**3. [Rule 2 - Missing Functionality] Added quality_grade to SHARED_LEADS_SELECT and lead_row_to_dict**
- **Found during:** Task 2 (test_quality_grade_field_present_in_lead failure)
- **Issue:** DB column existed but wasn't returned in API responses — test checked for `quality_grade` key in lead dict
- **Fix:** Added `l.quality_grade` to SELECT and `row[28]` mapping in lead_row_to_dict
- **Files modified:** `app/backend/app.py`
- **Commit:** `54e879f`

**4. [Rule 3 - Blocking] Manual DB migration on VPS due to init_db rollback issue**
- **Found during:** Post-deploy test run (500 on GET /api/leads)
- **Issue:** Column rollback bug meant `quality_grade` and other columns weren't created by init_db on first deploy
- **Fix:** Ran `ALTER TABLE leads ADD COLUMN IF NOT EXISTS` for all missing columns directly on VPS via SSH; ran dedup DELETE (157 rows) and created global index. Second deploy with IF NOT EXISTS fix ensures idempotent behavior going forward.
- **Impact:** No data loss; dedup correctly preserved highest-score lead per email

## Known Stubs

The 4 Phase 2 stub endpoints return `501 Not Implemented` when authenticated. This is intentional — Wave 2 (Plan 02) will replace the 501 body with real implementation while keeping the same routes.

## Self-Check: PASSED

- FOUND: tests/test_lead_quality.py (14 test functions)
- FOUND: app/backend/requirements.txt (3 new packages)
- FOUND: app/backend/app.py (idx_leads_email_global, 0 ON CONFLICT batch_id email)
- FOUND: .planning/phases/02-qualidade-de-leads/02-01-SUMMARY.md
- FOUND commit 1ce7f80: test(02-01) Wave 0 test scaffold
- FOUND commit 54e879f: feat(02-01) DB migrations
