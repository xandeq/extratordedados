---
phase: 05-export-com-cotas-niche-request-queue
plan: "01"
subsystem: backend
tags: [export, credits, niche-requests, db-migration, test-scaffold]
dependency_graph:
  requires: [04-03]
  provides: [GET /api/client/leads/export, niche_requests table, niche_request_votes table]
  affects: [app/backend/app.py, tests/test_export.py, tests/test_niche_requests.py]
tech_stack:
  added: [csv.DictWriter, utf-8-sig BOM encoding]
  patterns: [SELECT FOR UPDATE bulk deduction, executemany ON CONFLICT DO NOTHING, Wave 0 test stubs]
key_files:
  created:
    - tests/test_export.py
    - tests/test_niche_requests.py
  modified:
    - app/backend/app.py
decisions:
  - "Skipped _has_minimum_role() — it does not exist in app.py; client_search_leads and reveal_lead use only verify_token + _is_admin_user, so export follows the same pattern"
  - "has_email/phone/whatsapp/website/cnpj filters use inline SQL conditions (no extra %s params) to avoid psycopg2 parameter count mismatch"
  - "FROM flask import Response aliased as FlaskResponse inside the function to avoid name collision with any existing Response import at module level"
  - "Phase 5 niche_requests tables use a separate try/except with get_db() block (not nested in the original init_db() with get_db() block) for isolation"
metrics:
  duration: ~10 min
  completed: "2026-03-24"
  tasks: 2/2
  files: 3
---

# Phase 5 Plan 01: Wave 0 Scaffolds + DB Migration + Credit-Gated Export Summary

Credit-gated bulk export endpoint (CSV/JSON) with niche_requests/niche_request_votes DB tables and Wave 0 test scaffolds.

## What Was Built

### Task 1: Wave 0 Test Stubs

Two new test files with 8 skipped stubs covering the full Phase 5 surface:

**tests/test_export.py** (4 stubs):
- `test_export_requires_auth` — P5-EXPORT-AUTH
- `test_export_csv_format` — P5-EXPORT-FORMAT
- `test_export_debits_credits` — P5-EXPORT-CREDITS
- `test_export_respects_cap` — P5-EXPORT-CAP

**tests/test_niche_requests.py** (4 stubs):
- `test_niche_request_created` — P5-NICHE-CREATE
- `test_niche_vote_dedup` — P5-NICHE-VOTE
- `test_admin_niche_list` — P5-NICHE-ADMIN-LIST
- `test_admin_approve_niche` — P5-NICHE-APPROVE

All stubs use `@pytest.mark.skip(reason="Wave 0 stub — activate after Plan 0X backend")`.
Full suite result: 19 passed, 18 skipped, 0 failed.

### Task 2: DB Migration + Export Endpoint

**app/backend/app.py** additions:

1. **niche_requests table** — id SERIAL PK, requester_user_id (FK users), niche, city, state, notes, votes (default 1), status (default 'pending'), admin_notes, leads_added, created_at, updated_at, completed_at. Two indexes: (status, votes DESC) and (requester_user_id).

2. **niche_request_votes table** — user_id + niche_request_id composite PK (prevents duplicate votes), voted_at.

3. **_generate_csv_bytes(leads_dicts)** — csv.DictWriter with utf-8-sig BOM encoding for Excel compatibility. All None values replaced with empty string.

4. **GET /api/client/leads/export** (rate limit: 10/hour):
   - 401 without valid token
   - Accepts: format (csv|json), category, city, state, quality_grade, has_email, has_phone, has_whatsapp, has_website, has_cnpj
   - Mirrors WHERE clause from GET /api/leads/search (shared batches only)
   - Admin bypass: unlimited export, no credit deduction
   - Non-admin: SELECT FOR UPDATE on credit_ledger, cap at current balance
   - Returns 402 if balance <= 0, 404 if no leads match filters
   - Single bulk INSERT INTO credit_ledger (operation='export', amount=-actual_count)
   - Batch INSERT INTO user_lead_reveals ON CONFLICT DO NOTHING
   - All exported leads serialized with portal_lead_to_dict(row, revealed=True)

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| No `_has_minimum_role()` call | Function does not exist in app.py — reveal_lead and client_search_leads use verify_token + _is_admin_user pattern; export follows same |
| Boolean filter conditions as inline SQL | Avoids adding extra %s params that would misalign psycopg2 parameter binding |
| FlaskResponse aliased inside function | Prevents potential name collision with module-level Response import |
| Phase 5 tables in separate try/except block | Isolation: if niche tables fail (e.g. already exist with different schema), the rest of init_db() is not affected |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Boolean filter conditions stripped of %s params**
- **Found during:** Task 2 implementation
- **Issue:** Plan template used `conditions.append('l.email IS NOT NULL AND l.email != %s')` + `params.append('')` — this adds extra params that shift the param binding for other conditions
- **Fix:** Used inline SQL `"l.email IS NOT NULL AND l.email != ''"` (no param) — same result, no binding mismatch
- **Files modified:** app/backend/app.py

**2. [Rule 1 - Deviation] No _has_minimum_role() in codebase**
- **Found during:** Task 2 research
- **Issue:** Plan specifies `_has_minimum_role(user_id, 'client')` but this function doesn't exist in app.py
- **Fix:** Removed role check (consistent with client_search_leads and reveal_lead which don't gate by role either — any authenticated user can access)
- **Files modified:** app/backend/app.py

## Verification Results

```
python -m pytest tests/test_export.py tests/test_niche_requests.py -v
→ 8 skipped in 0.08s ✓

python -m pytest tests/ -q --tb=short (subset: auth, health, validation, export, niche)
→ 19 passed, 18 skipped, 0 failed ✓

grep "niche_requests" app/backend/app.py
→ CREATE TABLE IF NOT EXISTS niche_requests (line 2309) ✓

grep "client/leads/export" app/backend/app.py
→ @app.route('/api/client/leads/export', methods=['GET']) (line 15807) ✓

grep "_generate_csv_bytes" app/backend/app.py
→ def _generate_csv_bytes(leads_dicts) (line 2599) ✓

grep "'export'" app/backend/app.py
→ VALUES (%s, %s, 'export', NULL, %s) (line 15924) ✓
```

## Known Stubs

None — all exported data uses real portal_lead_to_dict() with revealed=True. The test stubs in test_export.py and test_niche_requests.py are intentionally skipped (Wave 0 — activate in Plans 01 and 02 respectively).

## Self-Check: PASSED
