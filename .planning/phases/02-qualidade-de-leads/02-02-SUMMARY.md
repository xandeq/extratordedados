---
phase: 02-qualidade-de-leads
plan: "02"
subsystem: backend
tags: [lead-quality, email-validation, phone-normalization, scoring, flask]
dependency_graph:
  requires: [02-01]
  provides: [validate_email_free, normalize_phone_br, compute_lead_quality_score, save_lead_to_db, POST /api/leads/validate-batch]
  affects: [all extraction pipelines, GET /api/leads filter, POST /api/leads/sanitize]
tech_stack:
  added: [disposable-email-domains==0.0.169, phonenumbers==9.0.26, email-validator==2.3.0]
  patterns: [6-dimension quality scoring, canonical insert helper, MX cache reuse]
key_files:
  modified:
    - app/backend/app.py
    - tests/test_lead_quality.py
decisions:
  - validate_email_free uses check_deliverability=False to avoid per-call DNS — MX check uses existing has_valid_mx() cache
  - save_lead_to_db calls conn.commit() internally — safe for autocommit connections (no-op) and regular connections
  - validate-batch endpoint uses with get_db() as conn per-lead loop for connection pool safety
  - import endpoint skips duplicate count corrected: save_lead_to_db returns False on duplicate, previously skipped count was only for pre-check duplicates
  - normalize_phone_br FIXED_LINE_OR_MOBILE with 8-digit national treated as landline (Pitfall 5)
  - quality filter now supports both A/B/C/D/F (quality_grade) and legacy premium/medio/basico (quality_score)
metrics:
  duration: 11 minutes
  completed: 2026-03-23
  tasks: 2/2
  files_modified: 2
---

# Phase 2 Plan 02: Core Quality Functions + save_lead_to_db + validate-batch Endpoint Summary

Single-sentence summary: JWT-free 3-layer email validator, E.164 phone normalizer, 6-dimension A-F lead scorer, and a single `save_lead_to_db()` helper that writes quality_grade into every extraction pipeline INSERT path.

## Objective

Implement the three core quality functions, create the canonical `save_lead_to_db()` helper replacing all ~10 former ON CONFLICT INSERT sites, update the leads filter to use quality_grade, add the POST /api/leads/validate-batch endpoint, and unskip the 6 unit stubs in the test file.

## Tasks Completed

### Task 1: Add quality functions + save_lead_to_db() + unskip unit stubs

**Functions added to app/backend/app.py (after has_valid_mx() at line ~1115):**

- `validate_email_free(email)` — Layer 1: RFC syntax (email-validator, check_deliverability=False), Layer 2: disposable blocklist (100k+ domains), Layer 3: MX check reusing existing `has_valid_mx()` + `_MX_CACHE`
- `normalize_phone_br(raw)` — Google libphonenumber: E.164, national format, type detection (mobile/landline/toll_free), whatsapp_id for mobile numbers
- `compute_lead_quality_score(lead)` — 6-dimension score: email(30) + phone(20) + completeness(20) + freshness(15) + cnpj(10) + source(5) → grade A/B/C/D/F + tier premium/medio/basico
- `save_lead_to_db(conn, lead_data)` — canonical INSERT helper that calls compute_lead_quality_score before every INSERT, returns True/False on duplicate

**Delegated functions (backward compat kept):**
- `calculate_lead_score_numeric()` now delegates to `compute_lead_quality_score().score`
- `calculate_quality_score()` now delegates to `compute_lead_quality_score().tier`

**INSERT sites refactored (10 call sites):**
All former `INSERT INTO leads` sites replaced with `save_lead_to_db()` calls:
1. process_search_job — search engine crawl (simple search path)
2. process_search_api_job — directory leads (Phase 0 directories)
3. process_search_api_job — API enrichment (hunter/snov)
4. process_search_api_job — scrape fallback (deep crawl)
5. process_batch — batch URL crawl (website_crawl)
6. scrape_google_maps_endpoint thread — Google Maps
7. scrape_instagram_endpoint thread — Instagram
8. scrape_linkedin_endpoint thread — LinkedIn
9. import_leads endpoint — JSON import
10. _save_leads_to_batch — massive search helper (all 7 thread methods)

**grep -c "INSERT INTO leads"** = 1 (only inside save_lead_to_db itself)
**grep -c "save_lead_to_db"** = 12 (1 def + print + 10 call sites)

### Task 2: Sanitize hook + validate-batch endpoint + quality_grade filter

**Integration A — sanitize_leads_internal Pass 3:**
- Added `compute_lead_quality_score()` call per-lead to compute quality_grade/lead_score/freshness_score
- Added `normalize_phone_br()` call to populate whatsapp_id if missing
- Added `validate_email_free()` call to mark mx_valid=FALSE for emails with no MX record
- UPDATE now sets quality_grade, lead_score, freshness_score, last_verified_at alongside existing fields

**Integration B — GET /api/leads filter:**
- Changed `AND l.quality_score = %s` (old tier filter) to support both:
  - `AND l.quality_grade = %s` for grades A/B/C/D/F (new)
  - `AND l.quality_score = %s` for legacy tiers premium/medio/basico (kept for compat)

**Integration C — POST /api/leads/validate-batch endpoint:**
- Replaced 501 stub with full implementation
- Fetches all leads in batch_id (or all leads for admin with no batch_id)
- Calls compute_lead_quality_score() per lead, UPDATEs quality_grade/quality_score/lead_score/freshness_score
- Returns {updated: int, errors: int, batch_id: int|null}
- Rate limit: 5/hour
- Auth: 401 without token, 400 for non-admin without batch_id

**validate-email-free and normalize-phone endpoints:**
- Both replaced 501 stubs with working implementations

## Verification Results

```
14 passed, 0 failed, 6441 warnings in 17.09s

Tests:
- test_validate_email_free_endpoint_requires_auth — PASS
- test_normalize_phone_endpoint_requires_auth — PASS
- test_db_columns_health_still_ok — PASS
- test_leads_list_returns_200_authenticated — PASS
- test_validate_batch_requires_auth — PASS
- test_validate_batch_authenticated — PASS
- test_verify_email_requires_auth — PASS
- test_quality_grade_field_present_in_lead — PASS
- test_validate_email_free_invalid_mx — PASS (unit)
- test_validate_email_free_disposable — PASS (unit)
- test_normalize_phone_br_mobile — PASS (unit)
- test_normalize_phone_br_invalid — PASS (unit)
- test_quality_score_complete_lead — PASS (unit)
- test_quality_score_no_email — PASS (unit)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Packages not installed locally**
- **Found during:** Task 1 RED phase — test_validate_email_free_disposable and test_normalize_phone_br_mobile failed
- **Issue:** `disposable-email-domains` and `phonenumbers` not installed in local Python (packages were in requirements.txt from Plan 01 but not installed locally)
- **Fix:** `python -m pip install email-validator==2.3.0 disposable-email-domains==0.0.169 phonenumbers==9.0.26`
- **Note:** Already in requirements.txt — VPS will have them installed via `pip install -r requirements.txt` on next deploy

**2. [Rule 1 - Bug] validate-batch endpoint used get_db_connection() which doesn't exist**
- **Found during:** Task 2 implementation — plan template used get_db_connection() but app.py uses get_db() context manager
- **Fix:** Rewrote validate-batch to use `with get_db() as conn:` pattern consistent with app.py conventions

**3. [Rule 1 - Bug] import endpoint double-counted skipped leads**
- **Found during:** Task 1 refactor — import endpoint had pre-check dedup that incremented skipped, then save_lead_to_db could also return False for duplicates
- **Fix:** save_lead_to_db returning False now increments skipped count correctly

## Known Stubs

None — all quality functions are fully implemented and wired into all extraction pipelines.

## Self-Check: PASSED

- app/backend/app.py: FOUND
- tests/test_lead_quality.py: FOUND
- .planning/phases/02-qualidade-de-leads/02-02-SUMMARY.md: FOUND
- Commit 8439d02: FOUND
- All 14 tests passing: VERIFIED
- Python syntax check: PASSED
- INSERT INTO leads count (1 = only in save_lead_to_db): VERIFIED
- save_lead_to_db count (12 = def + print + 10 calls): VERIFIED
