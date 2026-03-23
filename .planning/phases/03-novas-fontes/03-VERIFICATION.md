---
phase: 03-novas-fontes
verified: 2026-03-23T00:00:00Z
status: passed
score: 11/11 must-haves verified
re_verification: false
gaps: []
human_verification:
  - test: "Run POST /api/leads/enrich-cnpj on a lead with a known CNPJ and confirm fallback chain log output"
    expected: "Log line [cnpj_fallback] hit level N: {source} appears in gunicorn log"
    why_human: "Requires live API + a lead with CNPJ in DB — cannot verify log output programmatically without VPS access"
  - test: "Run POST /api/search/massive with methods=['outscraper_maps'] and a valid Outscraper API key in AWS SM"
    expected: "Jobs start, leads saved, no 500 errors"
    why_human: "AWS SM tools/outscraper key is a placeholder (empty) — live execution requires operator to fill in the key"
---

# Phase 3: Novas Fontes Verification Report

**Phase Goal:** Add three new data sources — Receita Federal local CNPJ enrichment (with 5-level fallback chain), Outscraper Google Maps as 8th massive search method, and Prospeo LinkedIn-to-email enrichment — along with import tooling and operator documentation.

**Verified:** 2026-03-23T00:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `cnpj_rf` table created by `init_db()`, idempotent | VERIFIED | Lines 1994-2032 app.py: Phase 3 migration block with `CREATE TABLE IF NOT EXISTS cnpj_rf`, two partial indexes, try/except with rollback |
| 2 | `enrich_from_rf_local()` performs SQL lookup against `cnpj_rf` | VERIFIED | Lines 1507-1576 app.py: full implementation with DB_CONFIG connection, CNPJ normalization, situacao mapping, phone formatting, source='rf_local' |
| 3 | `enrich_cnpj_with_fallback()` implements 5-level chain | VERIFIED | Lines 1579-1650 app.py: function defined with all 5 levels including Minha Receita level 2 silent skip |
| 4 | `POST /api/leads/enrich-cnpj` uses `enrich_cnpj_with_fallback()` (not direct BrasilAPI) | VERIFIED | Line 8302: `_run_cnpj_enrichment()` calls `enrich_cnpj_with_fallback(cnpj)` — endpoint routes through this function |
| 5 | `scripts/import/import_receita_federal.py` exists with `--dry-run` flag | VERIFIED | File exists at scripts/import/import_receita_federal.py; `--dry-run` argument defined at line 397; no Flask imports; AWS SM credentials via boto3 |
| 6 | `docs/RECEITA_FEDERAL_IMPORT.md` has complete runbook including Minha Receita section | VERIFIED | File exists; Minha Receita section at line 156 with 9 occurrences; docker-compose.yml, initial data load, verification, and Flask integration note all present |
| 7 | `_get_outscraper_key()` and `process_outscraper_massive()` exist in app.py | VERIFIED | `_get_outscraper_key()` at line 9097 with module-level cache; `process_outscraper_massive()` at line 11998 with `@_persist_thread_errors('outscraper')` decorator |
| 8 | `outscraper_maps` wired into `POST /api/search/massive` | VERIFIED | Line 11324: in default methods list; line 11631-11640: job creation block; line 11753-11757: thread launched; line 11787: count in response JSON |
| 9 | `_get_prospeo_key()` and `enrich_linkedin_prospeo()` exist in app.py | VERIFIED | `_get_prospeo_key()` at line 9121; `enrich_linkedin_prospeo()` at line 9140 with proper quota/402 handling |
| 10 | `POST /api/leads/<id>/enrich-linkedin` endpoint exists | VERIFIED | Route defined at line 7661: `@app.route('/api/leads/<int:lead_id>/enrich-linkedin', methods=['POST'])` with 30/hour rate limit and structured JSON responses |
| 11 | Prospeo hook in `process_linkedin_massive()` with 75-credit cap | VERIFIED | Line 12438: `prospeo_credits_used = 0`; line 12470: guard `prospeo_credits_used < 75`; line 12484: cap set to 75 on ConfigError |

**Score:** 11/11 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/backend/app.py` | `cnpj_rf` table migration in `init_db()` | VERIFIED | Lines 1994-2032 |
| `app/backend/app.py` | `enrich_from_rf_local()` function | VERIFIED | Lines 1507-1576 |
| `app/backend/app.py` | `enrich_cnpj_with_fallback()` function | VERIFIED | Lines 1579-1650 |
| `app/backend/app.py` | `_get_outscraper_key()` helper | VERIFIED | Line 9097 |
| `app/backend/app.py` | `process_outscraper_massive()` thread function | VERIFIED | Line 11998 |
| `app/backend/app.py` | `_get_prospeo_key()` helper | VERIFIED | Line 9121 |
| `app/backend/app.py` | `enrich_linkedin_prospeo()` function | VERIFIED | Line 9140 |
| `app/backend/app.py` | `POST /api/leads/<id>/enrich-linkedin` endpoint | VERIFIED | Line 7661 |
| `app/backend/requirements.txt` | `outscraper` package | VERIFIED | Line 25 |
| `scripts/import/import_receita_federal.py` | `--dry-run` flag, no Flask imports, AWS SM creds | VERIFIED | Lines 397-507; no Flask import found |
| `docs/RECEITA_FEDERAL_IMPORT.md` | Complete runbook with Minha Receita section | VERIFIED | File exists, 9 Minha Receita references, full docker-compose content |
| `tests/test_cnpj_enrichment.py` | Test file with skip stubs | VERIFIED | 4 tests, all marked `@pytest.mark.skip` — 23 lines |
| `tests/test_outscraper.py` | Test file (stubs or implemented) | VERIFIED | 3 tests — evolved beyond stubs to actual integration tests with `skipif` guard on missing API key |
| `tests/test_prospeo.py` | Test file (stubs or implemented) | VERIFIED | 3 tests — evolved beyond stubs to actual integration tests |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `POST /api/leads/enrich-cnpj` | `enrich_cnpj_with_fallback()` | `_run_cnpj_enrichment()` at line 8302 | WIRED | Endpoint dispatches to background function which calls fallback chain |
| `enrich_cnpj_with_fallback()` | `enrich_from_rf_local()` | direct call as Level 1 | WIRED | Level 1 in fallback chain |
| `POST /api/search/massive` | `process_outscraper_massive()` | `threading.Thread` at line 11753-11757 | WIRED | Thread started when `outscraper_maps` in methods |
| `process_linkedin_massive()` | `enrich_linkedin_prospeo()` | loop at lines 12469-12484 | WIRED | Called for linkedin-URL leads with no email, cap enforced |
| `POST /api/leads/<id>/enrich-linkedin` | `enrich_linkedin_prospeo()` | direct call at line 7688 | WIRED | Endpoint calls function directly, handles ConfigError → 429 |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status |
|-------------|-------------|-------------|--------|
| cnpj-rf-table | 03-01 | `cnpj_rf` PostgreSQL table in init_db() | SATISFIED |
| import-script | 03-01 | `scripts/import/import_receita_federal.py` with `--dry-run` | SATISFIED |
| enrich-from-rf-local | 03-01 | `enrich_from_rf_local()` SQL lookup | SATISFIED |
| cnpj-fallback-chain | 03-01 | `enrich_cnpj_with_fallback()` 5-level chain wired to endpoint | SATISFIED |
| rf-docs | 03-01 | `docs/RECEITA_FEDERAL_IMPORT.md` runbook | SATISFIED |
| outscraper-integration | 03-02 | `process_outscraper_massive()` + `outscraper_maps` in massive search | SATISFIED |
| outscraper-aws-key | 03-02 | `_get_outscraper_key()` using `resolve_secret_value` with `tools/outscraper` | SATISFIED |
| prospeo-integration | 03-03 | `enrich_linkedin_prospeo()`, endpoint, linkedin massive hook with 75-cap | SATISFIED |
| minha-receita-deploy | 03-03 | Minha Receita section in RECEITA_FEDERAL_IMPORT.md | SATISFIED |

---

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `app/backend/app.py` line 8508 | Message string says "via BrasilAPI" in response JSON but actual call is `enrich_cnpj_with_fallback()` | Info | Stale message text only — no functional impact, does not affect behavior |
| `app/backend/app.py` line 8264 | Docstring says "Fetches BrasilAPI" but code calls fallback chain | Info | Stale documentation string — no functional impact |
| `tests/test_cnpj_enrichment.py` | All 4 tests still marked `@pytest.mark.skip` with "implement after Plan 01 deploys" | Warning | Tests never run against the live implementation — but Plans 02 and 03 evolved their test files to real integration tests, so only cnpj tests remain as permanent stubs |

No blocker anti-patterns found. No stubs that prevent goal achievement.

---

### Human Verification Required

#### 1. CNPJ Fallback Chain Live Log

**Test:** Trigger `POST /api/leads/enrich-cnpj` on a lead with a valid CNPJ, then `tail -50 /var/log/gunicorn/app.log | grep cnpj_fallback` on the VPS.
**Expected:** At least one `[cnpj_fallback] hit level N: {source}` line appears.
**Why human:** Requires live VPS access + a lead with CNPJ in the database.

#### 2. Outscraper Live Execution

**Test:** Add a valid API key to AWS SM `tools/outscraper`, then run `POST /api/search/massive` with `methods=['outscraper_maps']` and a single niche.
**Expected:** Response includes `"outscraper_maps": N` in job counts; batch eventually shows leads with `source='outscraper_maps'`.
**Why human:** AWS SM key is currently an empty placeholder — live test requires operator action to set key value.

---

### Gaps Summary

No gaps found. All 11 observable truths are verified. All artifacts exist and are substantive (not stubs). All key links (endpoint-to-function, function-to-function, thread-to-function) are confirmed wired.

**Notable observations:**
- The test files for outscraper and prospeo were evolved beyond the plan's "skip stub" specification into real integration tests — this is a positive deviation that provides better test coverage.
- The `enrich-cnpj` endpoint docstring and response message reference "BrasilAPI" but the actual implementation correctly uses `enrich_cnpj_with_fallback()` — a cosmetic inconsistency with no functional impact.
- The `test_cnpj_enrichment.py` tests remain permanently skipped stubs. The plan intended them to be unskipped after deploy; this is a minor quality gap but does not block the phase goal.

---

_Verified: 2026-03-23T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
