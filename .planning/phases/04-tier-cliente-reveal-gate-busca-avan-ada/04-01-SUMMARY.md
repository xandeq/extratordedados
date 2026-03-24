---
phase: 04-tier-cliente-reveal-gate-busca-avan-ada
plan: 01
subsystem: database
tags: [postgresql, rbac, credit-ledger, select-for-update, apscheduler, masking, serializer]

# Dependency graph
requires:
  - phase: 03-novas-fontes
    provides: leads table with quality_score/quality_grade columns, APScheduler already running
  - phase: 02-qualidade-de-leads
    provides: plan_limits table, usage_tracking, save_lead_to_db
  - phase: 01-pipeline-autonomo
    provides: pipeline_config, APScheduler CronTrigger pattern

provides:
  - credit_ledger table (BIGSERIAL, SELECT FOR UPDATE atomic deduction)
  - user_lead_reveals table (PRIMARY KEY user_id+lead_id for idempotent reveals)
  - role column on users (VARCHAR(20) DEFAULT 'client') with admin backfill
  - credits_per_month column on plan_limits (free=10, pro=200, enterprise=999999)
  - require_role() decorator with ROLE_HIERARCHY dict
  - deduct_credit(conn, user_id, operation, ref_id) atomic function
  - grant_monthly_credits() APScheduler job (day=1 at 00:05 with double-fire guard)
  - mask_email() and mask_phone() portal masking helpers
  - portal_lead_to_dict() serializer (never exposes crm_status/notes/batch_id/tags)
  - /api/me now returns role field
  - 12 Wave 0 skip-stub test files (test_credits.py, test_reveal.py, test_client_search.py)

affects:
  - 04-02 (reveal gate endpoint uses deduct_credit, user_lead_reveals)
  - 04-03 (portal search endpoint uses portal_lead_to_dict, mask_email, mask_phone)
  - future admin plans (require_role decorator)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - SELECT FOR UPDATE on credit_ledger last row for atomic deduction
    - Double-fire guard via credit_ledger created_at window check (5 min)
    - require_role() wraps get_auth_header() + verify_token() + ROLE_HIERARCHY lookup
    - portal_lead_to_dict() positional row serializer — never field-maps internal columns

key-files:
  created:
    - tests/test_credits.py
    - tests/test_reveal.py
    - tests/test_client_search.py
  modified:
    - app/backend/app.py
    - tests/conftest.py

key-decisions:
  - "ROLE_HIERARCHY dict (admin=3, operator=2, client=1) — numeric comparison enables >= checks for future roles"
  - "deduct_credit takes open conn (not get_db()) — caller controls transaction boundary for atomicity"
  - "grant_monthly_credits double-fire guard checks credit_ledger operation='monthly_grant' in last 5 minutes — same pattern as daily pipeline"
  - "portal_lead_to_dict uses positional row slicing — caller query must SELECT columns in exact order"
  - "mask_email shows first 2 chars then *** — balances recognizability with privacy"
  - "website not masked in portal_lead_to_dict — not sensitive per spec (public info)"
  - "Wave 0 stubs use pytest.skip() not pytest.mark.skip — fixture params skip at collection time, not execution"

patterns-established:
  - "Phase 4 DB pattern: each new ALTER TABLE in own try/except with conn.rollback() — prevents transaction abort on duplicate column"
  - "Credit deduction: SELECT FOR UPDATE on most recent ledger row, never on users table — avoids user row lock contention"
  - "Monthly grant: INSERT row per user per month — never UPDATE balance; ledger is append-only"

requirements-completed: [P4-ROLE-COLUMN, P4-CREDIT-LEDGER, P4-DEDUCT-CREDIT, P4-GRANT-MONTHLY]

# Metrics
duration: 12min
completed: 2026-03-24
---

# Phase 4 Plan 01: DB Foundation + RBAC + Credit Ledger Summary

**credit_ledger and user_lead_reveals tables + require_role/deduct_credit/grant_monthly_credits/mask_email/mask_phone/portal_lead_to_dict helpers wired into app.py with APScheduler monthly job**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-03-24T00:30:00Z
- **Completed:** 2026-03-24T00:42:00Z
- **Tasks:** 2/2
- **Files modified:** 3 (app.py, conftest.py) + 3 created (test_credits.py, test_reveal.py, test_client_search.py)

## Accomplishments

- DB migrations added to init_db(): role column (users), credits_per_month (plan_limits), credit_ledger table, user_lead_reveals table — all idempotent with IF NOT EXISTS / own try/except blocks
- 6 Python helper functions added to app.py: require_role(), deduct_credit(), grant_monthly_credits(), mask_email(), mask_phone(), portal_lead_to_dict()
- APScheduler monthly_credit_grant job registered (day=1, 00:05, America/Sao_Paulo) with double-fire guard
- /api/me updated to return role field
- 12 Wave 0 test stubs created — all skip cleanly, zero failures
- Full existing test suite: 53 passed + 17 skipped, 0 failures

## Task Commits

1. **Task 1: Wave 0 test stubs** - `70358d5` (test)
2. **Task 2: DB migrations + helpers** - `9616223` (feat)

## Files Created/Modified

- `app/backend/app.py` — init_db migrations (role, credits_per_month, credit_ledger, user_lead_reveals), 6 helper functions, APScheduler job, /api/me role field
- `tests/conftest.py` — client_token fixture added
- `tests/test_credits.py` — 3 Wave 0 skip stubs
- `tests/test_reveal.py` — 4 Wave 0 skip stubs
- `tests/test_client_search.py` — 5 Wave 0 skip stubs

## Decisions Made

- deduct_credit() takes an open psycopg2 connection (not get_db() context manager) so the caller controls transaction boundary — essential for atomicity with the INSERT into user_lead_reveals in plan 02
- ROLE_HIERARCHY uses integers (admin=3, operator=2, client=1) so a single >= comparison handles any future role additions
- grant_monthly_credits double-fire guard uses the same 5-minute window pattern as the daily pipeline guard already in app.py — consistent across schedulers
- portal_lead_to_dict() uses positional row indexing — callers in plans 02/03 must SELECT columns in the exact documented order
- Wave 0 stubs use pytest.skip() inside fixture functions and pytest.mark.skip on tests — correct skip mechanism for each scenario

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None — all functions are fully implemented. The 12 test stubs are intentional Wave 0 placeholders that will be filled by plans 04-02 and 04-03.

## Next Phase Readiness

- Plan 04-02 (Reveal Gate endpoint) can import deduct_credit, user_lead_reveals, require_role immediately
- Plan 04-03 (Portal Search) can import portal_lead_to_dict, mask_email, mask_phone immediately
- DB tables will be created on next app startup (VPS deployment of app.py triggers init_db())
- All 48 pre-existing regression tests still pass

---
*Phase: 04-tier-cliente-reveal-gate-busca-avan-ada*
*Completed: 2026-03-24*
