---
phase: 06-saved-searches-notifica-es-de-novos-leads
plan: 01
subsystem: backend
tags: [db-migration, test-scaffold, helpers, wave-0]
dependency_graph:
  requires: []
  provides:
    - saved_searches table in PostgreSQL
    - tests/test_saved_searches.py (6 stubs)
    - _build_portal_filter_query() helper
    - send_notification_email() helper
    - /api/client/saved-searches stub endpoints (auth gate)
  affects:
    - app/backend/app.py (init_db, client_search_leads refactored)
    - tests/test_saved_searches.py (new file)
tech_stack:
  added: []
  patterns:
    - Wave 0 test scaffold pattern (1 pass, 5 skip)
    - ADD COLUMN IF NOT EXISTS in separate try/except block
    - Shared filter query helper extracted from endpoint
key_files:
  created:
    - tests/test_saved_searches.py
  modified:
    - app/backend/app.py
decisions:
  - Wave 0 stub endpoints return 401 for unauth, 501 for auth — enables test_saved_search_auth to pass immediately
  - _build_portal_filter_query returns (conditions, params) tuple — caller joins conditions, allows future callers to add extra conditions before joining
  - send_notification_email follows exact send_pipeline_email_report pattern — consistent error handling, never raises
  - saved_searches table uses UNIQUE(user_id, name) — same pattern as saved_filters
metrics:
  duration: ~11 min
  completed: "2026-03-24"
  tasks: 2/2
  files: 2
---

# Phase 06 Plan 01: Wave 0 Foundation — saved_searches DB + Test Scaffold Summary

Wave 0 foundation for Phase 6 Saved Searches: test scaffold with 6 stubs, saved_searches table DDL, and extracted helpers (_build_portal_filter_query + send_notification_email) that all subsequent plans depend on.

## What Was Built

### Task 1: Wave 0 Test Stubs + DB Migration

Created `tests/test_saved_searches.py` with 6 test functions:
- `test_saved_search_auth` — PASSES immediately (live API returns 401 for unauth POST)
- 4 CRUD stubs — skip with "not implemented yet — Wave 1"
- `test_notification_email_format` — skips until Wave 1

Added `saved_searches` table to `init_db()` in a separate `try/except` block (same pattern as Phase 5 niche_requests):
- Columns: id, user_id, name, filters (JSONB), notify_enabled, notify_email, last_notified_at, created_at
- Indexes: `idx_saved_searches_user` (user_id), `idx_saved_searches_notify` (notify_enabled, last_notified_at)

Added stub endpoints `/api/client/saved-searches` (GET, POST) and `/api/client/saved-searches/<id>` (DELETE, PATCH) that:
- Return 401 for unauthenticated requests (enables test to pass)
- Return 501 for authenticated requests (signals not-yet-implemented)

Deployed to VPS — `test_saved_search_auth` now passes against live API.

### Task 2: _build_portal_filter_query() + send_notification_email()

Extracted `_build_portal_filter_query(filters: dict)` helper that:
- Accepts a dict with keys: category, city, state, q, quality_grade, has_email, has_phone, has_whatsapp, has_website, has_cnpj
- Returns `(conditions: list[str], params: list)` tuple
- Always includes `b.is_shared = TRUE` as base condition
- Caller joins conditions with AND

Refactored `client_search_leads()` to call `_build_portal_filter_query({...})` instead of duplicating WHERE clause logic. Builds `base_query` using f-string with joined `where_clause`.

Added `send_notification_email(to_email, search_name, new_count)` after `send_pipeline_email_report()`:
- Uses Brevo transactional email API (same pattern as pipeline report)
- HTML email with "Ver leads no portal" CTA button
- Returns bool, never raises, logs errors with `[NOTIFY]` prefix

Deployed to VPS — all changes live.

## Verification Results

```
tests/test_saved_searches.py::test_saved_search_auth PASSED
tests/test_saved_searches.py::test_saved_search_created SKIPPED
tests/test_saved_searches.py::test_saved_search_list SKIPPED
tests/test_saved_searches.py::test_saved_search_delete SKIPPED
tests/test_saved_searches.py::test_saved_search_toggle SKIPPED
tests/test_saved_searches.py::test_notification_email_format SKIPPED
1 passed, 5 skipped
```

All acceptance criteria met:
- `CREATE TABLE IF NOT EXISTS saved_searches` — 1 match in init_db()
- `def _build_portal_filter_query` — 1 definition
- `def send_notification_email` — 1 definition
- `_build_portal_filter_query(` — 2 lines (definition + call in client_search_leads)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Stub endpoints required for auth guard test to pass**
- **Found during:** Task 1
- **Issue:** test_saved_search_auth calls live API at `/api/client/saved-searches` — without endpoint, server returns 404 instead of 401, causing test FAIL
- **Fix:** Added `client_saved_searches()` and `client_saved_search_detail()` stub routes that return 401 (unauth) / 501 (auth). These Wave 0 stubs will be replaced by full CRUD in Plan 02.
- **Files modified:** app/backend/app.py
- **Commit:** 6b30271

**2. [Rule 3 - Blocking] Backend deployment required for live API test**
- **Found during:** Task 1
- **Issue:** Tests run against live API `https://api.extratordedados.com.br` — local code changes have no effect on tests
- **Fix:** Deployed backend to VPS after each task via `python deploy.py backend`
- **Commits:** 6b30271, 4a3b7fc (both include deployment)

## Commits

| Hash | Message |
|------|---------|
| 6b30271 | test(06-01): Wave 0 test stubs + saved_searches DB migration |
| 4a3b7fc | feat(06-01): _build_portal_filter_query() helper + send_notification_email() |

## Known Stubs

| Stub | File | Reason |
|------|------|--------|
| `client_saved_searches()` returns 501 | app/backend/app.py | Wave 0 auth gate only — full CRUD in Plan 02 |
| `client_saved_search_detail()` returns 501 | app/backend/app.py | Wave 0 auth gate only — full CRUD in Plan 02 |
| `test_saved_search_created` | tests/test_saved_searches.py | Skips until Plan 02 implements POST /api/client/saved-searches |
| `test_saved_search_list` | tests/test_saved_searches.py | Skips until Plan 02 implements GET /api/client/saved-searches |
| `test_saved_search_delete` | tests/test_saved_searches.py | Skips until Plan 02 implements DELETE endpoint |
| `test_saved_search_toggle` | tests/test_saved_searches.py | Skips until Plan 02 implements PATCH endpoint |
| `test_notification_email_format` | tests/test_saved_searches.py | Skips until Plan 02 wires full notification flow |

These stubs are intentional Wave 0 scaffolding — Plan 02 will activate them.

## Self-Check: PASSED
