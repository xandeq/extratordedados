---
phase: 3
plan: 3
slug: novas-fontes
title: "Prospeo LinkedIn-to-email enrichment + Minha Receita deploy guide"
status: complete
completed_date: "2026-03-23"
duration_minutes: 6
tasks_completed: 3
tasks_total: 3
files_created: 0
files_modified: 3
one_liner: "Prospeo Social URL API for LinkedIn→email with 75-credit cap + full Minha Receita docker-compose deploy guide appended to RF runbook"

dependency_graph:
  requires:
    - "03-01"
    - "03-02"
  provides:
    - prospeo-integration
    - minha-receita-deploy
  affects:
    - app/backend/app.py
    - docs/RECEITA_FEDERAL_IMPORT.md
    - tests/test_prospeo.py

tech_stack:
  added: []
  patterns:
    - "resolve_secret_value() + module-level cache for Prospeo key"
    - "with get_db() as conn: context manager pattern in Flask endpoints"
    - "prospeo_credits_used counter for per-run free-tier cap"

key_files:
  created: []
  modified:
    - app/backend/app.py
    - docs/RECEITA_FEDERAL_IMPORT.md
    - tests/test_prospeo.py

decisions:
  - "Prospeo key stored as empty placeholder in AWS SM tools/prospeo — operator must set real key"
  - "with get_db() as conn used in enrich_lead_linkedin (consistent with other Flask endpoints)"
  - "prospeo_credits_used is a per-run counter, not persisted — simple and sufficient for free tier limit"
  - "enrich_linkedin_prospeo handles both flat and nested response structures from Prospeo API"
---

# Phase 3 Plan 3: Prospeo LinkedIn-to-email enrichment + Minha Receita deploy guide — Summary

## What Was Built

Prospeo Social URL API integration for LinkedIn→email enrichment on individual leads and inside the LinkedIn massive scrape thread, with a 75-credit monthly cap guard. Full Minha Receita Docker deployment guide added to the existing Receita Federal import runbook.

## Tasks Completed

### Task 1 — AWS SM secret + `_get_prospeo_key()` + `enrich_linkedin_prospeo()`
- Created `tools/prospeo` secret in AWS SM (placeholder empty key)
- Added `_prospeo_key_cache` / `_prospeo_key_failed` module-level cache pattern after `_get_outscraper_key()`
- `enrich_linkedin_prospeo(linkedin_url)` validates URL format, calls `POST https://api.prospeo.io/social-url-enrichment`, handles both flat and nested response JSON, raises `ConfigError` on 402/quota, returns `{}` on miss, never raises on other errors
- **Commit:** `092f535`

### Task 2 — `POST /api/leads/<id>/enrich-linkedin` endpoint + LinkedIn hook
- New Flask route `POST /api/leads/<int:lead_id>/enrich-linkedin` (rate limit 30/hour)
- Returns 400 (no LinkedIn URL), 404 (lead not found), 503 (key not configured), 429 (quota), 200 (enriched or not found)
- Updates lead email in DB only if currently empty; uses `with get_db() as conn:` pattern
- `process_linkedin_massive()` now calls `enrich_linkedin_prospeo()` for leads with linkedin URL but no email, capped at 75 per run via `prospeo_credits_used` counter
- **Commit:** `a86a3ad`

### Task 3 — Minha Receita deploy guide + test_prospeo.py activation
- `docs/RECEITA_FEDERAL_IMPORT.md` section 7 fully replaced with complete Minha Receita deploy guide: prerequisites, double-download warning, docker-compose.yml, initial data load, start, verification, Flask integration note
- `tests/test_prospeo.py` skip markers removed; 3 smoke tests implemented and passing (5 passed, 5 skipped in full Phase 3 suite)
- **Commit:** `cf36465`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed NameError: `get_db_connection` is not defined in `enrich_lead_linkedin`**
- **Found during:** Deploy verification (live endpoint returned 500)
- **Issue:** Endpoint used `get_db_connection()` which does not exist in app.py. The anchor endpoint `verify_lead_email` also uses this non-existent function (pre-existing bug, out of scope to fix).
- **Fix:** Replaced with `with get_db() as conn:` context manager pattern, consistent with all other Flask endpoints in the codebase.
- **Files modified:** `app/backend/app.py`
- **Commit:** `53820a4`

## Test Results

```
tests/test_prospeo.py::test_prospeo_enrich_endpoint_exists PASSED
tests/test_prospeo.py::test_prospeo_skips_leads_without_linkedin_url PASSED
tests/test_prospeo.py::test_prospeo_quota_exceeded_returns_graceful_error PASSED
3 passed, 0 skipped
```

Full Phase 3 suite: 5 passed, 5 skipped (CNPJ stubs + 1 Outscraper live test still pending real keys).

## Deploy

Backend deployed to VPS (185.173.110.180). Health check: passing. Endpoint verified live: `POST /api/leads/1/enrich-linkedin` returns `{"error":"Lead not found"}` (404) — not 500.

## Known Stubs

None — all functionality is implemented. The Prospeo key in AWS SM is an empty placeholder; the endpoint gracefully returns 503 until a real key is set.

## Self-Check: PASSED
