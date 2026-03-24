---
phase: 04-tier-cliente-reveal-gate-busca-avan-ada
plan: 02
subsystem: api
tags: [flask, postgresql, credits, reveal-gate, lead-search, masking]

# Dependency graph
requires:
  - phase: 04-tier-cliente-reveal-gate-busca-avan-ada
    plan: 01
    provides: "credit_ledger table, user_lead_reveals table, deduct_credit(), portal_lead_to_dict(), mask_email(), mask_phone(), _is_admin_user(), grant_monthly_credits() APScheduler job"
provides:
  - "POST /api/leads/reveal/<id> — atomic credit deduction, admin bypass, idempotent re-reveal"
  - "GET /api/client/credits — balance + last 20 credit ledger events"
  - "GET /api/leads/search — masked client-facing lead search with 9 filter params"
affects:
  - 04-03-frontend
  - portal-clients

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reveal gate: check user_lead_reveals first, deduct only on first reveal"
    - "Admin bypass pattern: _is_admin_user() before credit logic, returns None for credits_remaining"
    - "ON CONFLICT DO NOTHING on INSERT to user_lead_reveals — race-condition safe"
    - "Grade filter: quality_grade = ANY(list) using grade_order dict to compute allowed grades"
    - "Client search: portal_lead_to_dict() handles masking, revealed= param controls visibility"

key-files:
  created: []
  modified:
    - app/backend/app.py

key-decisions:
  - "reveal_lead() fetches lead first (404 check), then checks admin bypass, then checks already-revealed — order matters for correct 404 before credit logic"
  - "client_search_leads() uses portal_lead_to_dict() with revealed=(row[0] in revealed_set) — single function handles both masked and unmasked output"
  - "quality_grade filter returns leads at-or-better: grade_order dict with <= comparison for A/B/C/D/F scale"
  - "GET /api/leads/search returns pages count in response: (total + per_page - 1) // per_page — useful for frontend pagination"
  - "has_email/has_phone/has_whatsapp/has_website/has_cnpj filters use AND col IS NOT NULL AND col != '' (inline SQL, not parameterized empty string) — avoids extra param slot"

patterns-established:
  - "Three client portal endpoints follow the same auth pattern: get_auth_header() -> verify_token() -> 401 guard"
  - "All three endpoints have try/except outer block with print([ERROR] /api/endpoint: {e}) logging"

requirements-completed:
  - P4-REVEAL-ENDPOINT
  - P4-CREDITS-ENDPOINT
  - P4-SEARCH-ENDPOINT

# Metrics
duration: 4min
completed: 2026-03-24
---

# Phase 4 Plan 02: Client Portal API Endpoints Summary

**Three client-facing Flask endpoints implementing the revenue model: atomic credit-per-reveal gate, credit balance history, and masked lead search with 9 filter params over shared batches only.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-24T00:30:22Z
- **Completed:** 2026-03-24T00:34:06Z
- **Tasks:** 2/2
- **Files modified:** 1

## Accomplishments

- `POST /api/leads/reveal/<id>` — deducts 1 credit atomically, admin users bypass entirely, re-reveals are free (idempotent via user_lead_reveals check), returns 402 with `insufficient_credits` on zero balance
- `GET /api/client/credits` — returns current balance + last 20 credit_ledger events with ISO timestamps
- `GET /api/leads/search` — client search over shared batches only (JOIN batches WHERE is_shared=TRUE), returns masked email/phone via portal_lead_to_dict(), unmasked for already-revealed leads, 9 filter params, pagination with pages count

## Task Commits

1. **Task 1: POST /api/leads/reveal/<id> and GET /api/client/credits** - `4a1105d` (feat)
2. **Task 2: GET /api/leads/search — masked client search** - `a1444e1` (feat)

## Files Created/Modified

- `app/backend/app.py` — Three new endpoints added after `/api/client/usage`: reveal_lead(), client_credits(), client_search_leads()

## Decisions Made

- `reveal_lead()` verifies lead exists (404 check) before entering credit logic — prevents credit deduction attempts for nonexistent leads
- `client_search_leads()` delegates all masking logic to `portal_lead_to_dict()` — no masking inline in the endpoint, single source of truth
- `quality_grade` filter computes `allowed_grades` list using `grade_order` dict, then uses `= ANY(%s)` — cleaner than multiple OR conditions
- `has_email/phone/whatsapp/website/cnpj` filters use inline `IS NOT NULL AND != ''` rather than parameterized empty string — avoids param position confusion

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. All credentials were established in Plan 01.

## Next Phase Readiness

- All three API endpoints live on VPS, returning 401 without token (verified with curl smoke tests)
- Health check passed: `{"status": "ok", "db": "postgresql"}`
- Plan 03 (frontend portal pages) can now integrate against these endpoints
- `POST /api/leads/reveal/<id>` and `GET /api/leads/search` are the primary endpoints the client portal UI will call

## Self-Check: PASSED

- `app/backend/app.py` exists and modified: FOUND
- Commit `4a1105d` (Task 1): FOUND
- Commit `a1444e1` (Task 2): FOUND
- VPS health check: OK
- All 3 endpoints return 401 Unauthorized without token: VERIFIED

---
*Phase: 04-tier-cliente-reveal-gate-busca-avan-ada*
*Completed: 2026-03-24*
