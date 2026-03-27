---
phase: 10-novas-fontes
verified: 2026-03-27T00:00:00Z
status: passed
score: 8/8 must-haves verified
---

# Phase 10: Novas Fontes Verification Report

**Phase Goal:** Add new extraction sources (Apple Maps, Foursquare) and improve existing ones (Outscraper limit, 5-query search templates)
**Verified:** 2026-03-27
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth                                                                            | Status     | Evidence                                                                               |
|----|----------------------------------------------------------------------------------|------------|----------------------------------------------------------------------------------------|
| 1  | process_apple_maps_massive() exists and is wired as Thread 17                   | VERIFIED   | Defined at app.py:12743 with @_persist_thread_errors('apple_maps'); thread start at 12303 |
| 2  | process_foursquare_massive() exists and is wired as Thread 18                   | VERIFIED   | Defined at app.py:12881 with @_persist_thread_errors('foursquare'); thread start at 12311 |
| 3  | SEARCH_QUERY_TEMPLATES constant with 5 templates exists                          | VERIFIED   | Defined at app.py:1137 with 5 entries (contato, email, whatsapp, site:*.com.br, OR vizinha) |
| 4  | query_override logic in process_search_job uses template-built queries           | VERIFIED   | app.py:5116 reads job_data.get('query_override') before falling back to original build  |
| 5  | Outscraper limit=100 (not limit=20) in process_outscraper_massive                | VERIFIED   | app.py:12625 shows limit=100 in _massive_retry lambda; comment "SRC-03: limit 20->100" |
| 6  | GET /api/admin/source-stats endpoint exists                                      | VERIFIED   | app.py:17998 — admin token + is_admin check, captured_at filter, GROUP BY source       |
| 7  | BarChart in admin/index.tsx fetching from source-stats                           | VERIFIED   | index.tsx:2 imports BarChart; :217 fetches /api/admin/source-stats; :516 renders chart |
| 8  | tests/test_sources.py with 8 smoke tests covering all 4 requirements             | VERIFIED   | File exists at 106 lines; 8 test functions covering SRC-01/02/03/04 + source-stats      |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact                                      | Expected                                                        | Status     | Details                                                                         |
|-----------------------------------------------|-----------------------------------------------------------------|------------|---------------------------------------------------------------------------------|
| `app/backend/app.py`                          | process_apple_maps_massive + Thread 17                          | VERIFIED   | Function at line 12743, wired at 12303, return dict entry at 12344              |
| `app/backend/app.py`                          | process_foursquare_massive + Thread 18                          | VERIFIED   | Function at line 12881, wired at 12311, return dict entry at 12345              |
| `app/backend/app.py`                          | SEARCH_QUERY_TEMPLATES constant (5 templates)                   | VERIFIED   | Lines 1137-1143, used in orchestrator at 11920 and total_jobs counter at 11854  |
| `app/backend/app.py`                          | query_override in process_search_job                            | VERIFIED   | Lines 5115-5118, orchestrator sets query_override at 11939                      |
| `app/backend/app.py`                          | Outscraper limit=100                                            | VERIFIED   | Line 12625, lambda passes limit=100 to client.google_maps_search                |
| `app/backend/app.py`                          | GET /api/admin/source-stats                                     | VERIFIED   | Lines 17998-18025, manual admin guard (functionally equivalent to @require_admin) |
| `app/frontend/pages/admin/index.tsx`          | BarChart reading from source-stats                              | VERIFIED   | Import at line 2, SourceStat interface at 62, state at 192, fetch at 217, JSX at 510 |
| `tests/test_sources.py`                       | 8 smoke tests                                                   | VERIFIED   | 106-line file with 8 test functions, uses api_base + auth_headers fixtures       |

### Key Link Verification

| From                                  | To                               | Via                                                    | Status  | Details                                                   |
|---------------------------------------|----------------------------------|--------------------------------------------------------|---------|-----------------------------------------------------------|
| POST /api/search/massive              | process_apple_maps_massive       | threading.Thread(target=..., daemon=True).start()      | WIRED   | app.py:12301-12305; 'apple_maps' in default methods list at 11811 |
| POST /api/search/massive              | process_foursquare_massive       | threading.Thread(target=..., daemon=True).start()      | WIRED   | app.py:12309-12313; 'foursquare' in default methods list at 11811 |
| process_outscraper_massive            | client.google_maps_search        | lambda q=query: client.google_maps_search([q], limit=100, ...) | WIRED | app.py:12624-12626                                   |
| search_engines orchestrator           | process_search_job               | 5 INSERT rows per niche+city with query_override       | WIRED   | app.py:11920 iterates SEARCH_QUERY_TEMPLATES; 11939 sets query_override |
| admin/index.tsx                       | GET /api/admin/source-stats      | useEffect -> api.get('/api/admin/source-stats')        | WIRED   | index.tsx:217-224; BarChart renders sourceStats at 510-524 |

### Requirements Coverage

| Requirement | Source Plan | Description                                         | Status    | Evidence                                                               |
|-------------|-------------|-----------------------------------------------------|-----------|------------------------------------------------------------------------|
| SRC-01      | 10-01       | Apple Maps as Thread 17 in massive search           | SATISFIED | process_apple_maps_massive defined + Thread 17 wired + return dict     |
| SRC-02      | 10-03       | Foursquare Places API as Thread 18                  | SATISFIED | process_foursquare_massive defined + Thread 18 wired + return dict     |
| SRC-03      | 10-02       | Outscraper limit 20 -> 100, cap at 4 jobs           | SATISFIED | limit=100 in _massive_retry lambda; niches[:2] in orchestrator block   |
| SRC-04      | 10-02       | 5 search engine query templates per niche+city      | SATISFIED | SEARCH_QUERY_TEMPLATES[5] defined; orchestrator inserts 5 jobs; query_override read in process_search_job |

### Anti-Patterns Found

No blockers or warnings found.

| File                                    | Line  | Pattern                          | Severity | Impact    |
|-----------------------------------------|-------|----------------------------------|----------|-----------|
| app/backend/app.py                      | 18004 | Manual admin check (not decorator) | Info   | Functionally equivalent to @require_admin — all other admin routes use same inline pattern; no gap |

### Human Verification Required

The following items require live environment verification and cannot be confirmed programmatically:

#### 1. Apple Maps Playwright Extraction

**Test:** Run POST /api/search/massive with methods=["apple_maps"], niches=["Clinica Medica"], city="Vitoria", state="ES". Wait for batch completion (30-60s), then check search_jobs table for completed/paused status and leads count.
**Expected:** At least one job completes or is marked paused (selector_timeout is acceptable). If Apple Maps serves results for the selector .place-list-item, leads appear with source='apple_maps'.
**Why human:** Playwright + Apple Maps DOM selector accuracy depends on live page structure which may differ from the selector used (.place-list-item). Cannot verify without a browser.

#### 2. Foursquare API Key Setup

**Test:** Add FOURSQUARE_API_KEY to AWS SM extratordedados/prod, then run POST /api/search/massive with methods=["foursquare"]. Check response methods dict shows foursquare >= 1.
**Expected:** When key is present, foursquare_jobs are created and thread starts. When key is absent, jobs are marked failed/quota_exceeded and workflow continues.
**Why human:** FOURSQUARE_API_KEY is not yet provisioned per plan's user_setup block — requires manual API registration at foursquare.com/developers.

#### 3. Admin Dashboard Chart Visibility

**Test:** Visit https://extratordedados.com.br/admin with admin account. Check if "Leads por Fonte (últimos 30 dias)" bar chart appears.
**Expected:** If leads with captured_at within last 30 days exist, chart renders with colored bars. If all leads are older, chart is hidden (conditional render).
**Why human:** Chart visibility depends on live DB data. Source-stats endpoint may return empty list for test environments with old data.

#### 4. pytest tests/test_sources.py full suite

**Test:** Run `pytest tests/test_sources.py -v --tb=short` with VPS reachable and valid admin token in environment.
**Expected:** All 8 tests pass. test_source_stats_has_data may fail if no leads with known sources exist in last 30 days — this is a data-dependency, not a code bug.
**Why human:** Tests call live API at api.extratordedados.com.br; network access and admin token required.

### Gaps Summary

No gaps. All automated must-haves are verified in the codebase.

One note on the source-stats endpoint: the plan specified `@require_admin` decorator but the codebase does not have this decorator — it uses inline token + is_admin checks consistently across all admin routes. The implementation at lines 18004-18012 is functionally identical and follows the existing pattern. This is not a gap.

---

_Verified: 2026-03-27_
_Verifier: Claude (gsd-verifier)_
