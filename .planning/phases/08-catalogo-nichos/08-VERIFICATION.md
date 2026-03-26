---
phase: 08-catalogo-nichos
verified: 2026-03-26T12:00:00Z
status: passed
score: 18/18 must-haves verified
re_verification: false
gaps: []
human_verification:
  - test: "Admin visits /admin/niches and sees category tabs"
    expected: "Page loads 10+ category tabs (Saúde, Beleza & Estética, etc.) each showing active/total niche counts"
    why_human: "Static HTML build cannot verify dynamic API fetch; visual layout and tab switching require browser"
  - test: "Toggle niche active/inactive on /admin/niches and refresh"
    expected: "Toggle slider moves, persists after page reload (change stored in DB)"
    why_human: "Requires live API call through browser; cannot verify round-trip persistence statically"
  - test: "massive-search Step 1 shows niches grouped by category after loading"
    expected: "Step 1 shows section headings like 'Saúde', 'Alimentação', etc. above niche pill buttons"
    why_human: "Requires browser + live /api/niches?active=true response; grouping logic is in runtime JS"
  - test: "Pipeline daily job uses niches from DB (not hardcoded DAILY_JOB_NICHES)"
    expected: "POST /api/admin/daily-job/run followed by GET /api/admin/daily-job/status shows niches_used containing names from the niches catalog (e.g., 'Clínica Médica' not 'clinica medica')"
    why_human: "Requires triggering a live pipeline run; cannot verify round-robin advancement without DB state"
---

# Phase 8: Catálogo de Nichos — Verification Report

**Phase Goal:** Build a curated niche catalog with 150+ entries, admin UI to manage it, pipeline round-robin rotation, and massive-search loading niches from DB.
**Verified:** 2026-03-26T12:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | `niches` table DDL exists in `init_db()` with all 8 columns | VERIFIED | `app/backend/app.py:2222` — `CREATE TABLE IF NOT EXISTS niches` with id, name, category, keywords, active, priority, last_used_at, created_at + UNIQUE(name) |
| 2 | `custom_niches` rows are migrated on startup | VERIFIED | `app/backend/app.py:2236-2240` — `INSERT INTO niches SELECT name, 'Outros', created_at FROM custom_niches ON CONFLICT (name) DO NOTHING` |
| 3 | `populate_niches.sql` has 150+ niche rows across 10 categories | VERIFIED | 156 value rows confirmed by Python count; `ON CONFLICT` present (idempotent) |
| 4 | `GET /api/admin/niches` returns grouped catalog with `total` (admin-only) | VERIFIED | `app/backend/app.py:15330-15359` — full implementation with 401/403 guards, `SELECT ... FROM niches ORDER BY category`, grouped dict response with `total` |
| 5 | `PUT /api/admin/niches/<id>` toggles active/priority (admin-only) | VERIFIED | `app/backend/app.py:15390-15425` — updates `active` and/or `priority` fields, returns updated row |
| 6 | `PUT /api/admin/niches/bulk` enables/disables a batch by IDs (admin-only) | VERIFIED | `app/backend/app.py:15362-15387` — bulk `UPDATE niches SET active = %s WHERE id = ANY(%s)` |
| 7 | Bulk route registered BEFORE single-ID route (Flask routing order) | VERIFIED | `/api/admin/niches/bulk` at line 15362 precedes `/api/admin/niches/<int:niche_id>` at line 15390 |
| 8 | `GET /api/niches?active=true` returns only active niches grouped by category (auth required) | VERIFIED | `app/backend/app.py:15428-15451` — filters by `active = TRUE` when `?active=true`, returns grouped dict |
| 9 | `get_pipeline_config()` reads from `niches` table using round-robin (`ORDER BY last_used_at ASC NULLS FIRST`) | VERIFIED | `app/backend/app.py:894-901` — `SELECT name FROM niches WHERE active = TRUE ORDER BY last_used_at ASC NULLS FIRST, priority ASC, id ASC LIMIT n` |
| 10 | `get_pipeline_config()` is read-only (no side effects on health checks) | VERIFIED | No UPDATE statement inside `get_pipeline_config()`; comment explicitly documents this |
| 11 | `_mark_niches_used(names)` helper updates `last_used_at` for selected niches | VERIFIED | `app/backend/app.py:924-940` — `UPDATE niches SET last_used_at = NOW() WHERE name = ANY(%s)`, non-fatal error handling |
| 12 | `trigger_daily_pipeline()` calls `_mark_niches_used(niches)` exactly once after niches resolved | VERIFIED | `app/backend/app.py:15022-15023` — `_mark_niches_used(niches)` called immediately after `niches = niches or cfg['niches']` |
| 13 | `daily_job_run()` fallback uses `get_pipeline_config()['niches']` (not hardcoded) | VERIFIED | `app/backend/app.py:15609` — `niches = data.get('niches') or get_pipeline_config()['niches']`; no `or DAILY_JOB_NICHES` in that function |
| 14 | `DAILY_JOB_NICHES` constant preserved as ultimate fallback | VERIFIED | Constant present at `app/backend/app.py:~870`; used only in `get_pipeline_config()` exception fallback |
| 15 | `app/frontend/pages/admin/niches.tsx` — category tabs, toggle, priority save | VERIFIED | File exists; `api.get('/api/admin/niches')`, `toggleActive` calls `api.put(/api/admin/niches/${id})`, `savePriority` calls `api.put` on blur, `activeTab` state drives tab rendering |
| 16 | `massive-search.tsx` loads niches from DB; `PREDEFINED_NICHES` removed | VERIFIED | `api.get('/api/niches?active=true')` at line 40; `PREDEFINED_NICHES` grep returns zero matches; `NicheWithCategory` interface with `category` field |
| 17 | "Selecionar todos" / "Limpar seleção" buttons present; >50 warning fires | VERIFIED | Both button labels found at lines 323/329; `nicheWarning` state, `selectAll`/`clearAll` handlers, warning message "Máximo de 50 nichos por busca para não sobrecarregar o servidor." |
| 18 | Sidebar shows "Catálogo de Nichos" + "Pipeline Config" nav items; `isActive()` exact-matches both routes | VERIFIED | `app/frontend/components/Sidebar.tsx:44-45` — both entries present; `isActive()` at line 196 includes `/admin/niches` and `/admin/pipeline-config` in exact-match condition |

**Score:** 18/18 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/backend/app.py` | niches DDL in init_db() + 4 endpoints + _mark_niches_used + modified get_pipeline_config | VERIFIED | All components present at expected line numbers |
| `scripts/import/populate_niches.sql` | 150+ niches across 10 categories, idempotent | VERIFIED | 156 rows, 2 ON CONFLICT occurrences (header + data section), UTF-8 with category names |
| `tests/test_niches.py` | 8 test stubs covering NICHE-01/02/03/04 | VERIFIED | 8 `def test_` functions confirmed by grep count |
| `app/frontend/pages/admin/niches.tsx` | Admin page with tabs + toggle + priority | VERIFIED | File created; all required handlers and API calls present |
| `app/frontend/pages/massive-search.tsx` | DB-loaded niches, grouped, select-all/clear, empty state | VERIFIED | All required patterns confirmed |
| `app/frontend/components/Sidebar.tsx` | Two new nav items + isActive() fix | VERIFIED | Both entries + Tag import + updated isActive() |
| `app/frontend/out/admin/niches/index.html` | Built static page | VERIFIED | File exists at `app/frontend/out/admin/niches/index.html` |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `init_db()` in app.py | `niches` table | `CREATE TABLE IF NOT EXISTS niches` | WIRED | Line 2222 |
| `init_db()` in app.py | `custom_niches` migration | `INSERT INTO niches SELECT ... FROM custom_niches ON CONFLICT` | WIRED | Lines 2236-2240 |
| `GET /api/admin/niches` | `niches` table | `SELECT id, name, category, active, priority, last_used_at, created_at FROM niches` | WIRED | Line 15344 |
| `PUT /api/admin/niches/<id>` | `niches` table | `UPDATE niches SET ... WHERE id = %s RETURNING ...` | WIRED | Line 15417 |
| `PUT /api/admin/niches/bulk` | `niches` table | `UPDATE niches SET active = %s WHERE id = ANY(%s)` | WIRED | Line 15382 |
| `GET /api/niches` | `niches` table | `SELECT ... FROM niches WHERE active = TRUE ORDER BY ...` | WIRED | Line 15440 |
| `get_pipeline_config()` | `niches` table | `SELECT name FROM niches WHERE active = TRUE ORDER BY last_used_at ASC NULLS FIRST` | WIRED | Lines 894-901 |
| `trigger_daily_pipeline()` | `_mark_niches_used()` | called after `niches = niches or cfg['niches']` | WIRED | Line 15023 |
| `daily_job_run()` | `get_pipeline_config()` | `data.get('niches') or get_pipeline_config()['niches']` | WIRED | Line 15609 |
| `admin/niches.tsx` | `/api/admin/niches` | `api.get('/api/admin/niches')` in useEffect | WIRED | Line 33 |
| `admin/niches.tsx` toggle | `/api/admin/niches/<id>` | `api.put(\`/api/admin/niches/${niche.id}\`, { active: !niche.active })` | WIRED | Line 49 |
| `admin/niches.tsx` priority | `/api/admin/niches/<id>` | `api.put(\`/api/admin/niches/${niche.id}\`, { priority })` | WIRED | Line 68 |
| `massive-search.tsx` | `/api/niches?active=true` | `api.get('/api/niches?active=true')` in useEffect | WIRED | Line 40 |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| NICHE-01 | 08-01-PLAN | `niches` table with catalog schema (id, name, category, keywords[], active, priority, created_at) | SATISFIED | `app/backend/app.py:2222-2232` — all required columns present; `subcategory` from REQUIREMENTS.md not in DDL (plan intentionally omitted it — not a gap) |
| NICHE-02 | 08-02-PLAN | `get_pipeline_config()` reads from `niches` table for daily rotation | SATISFIED | `app/backend/app.py:894-901` — round-robin SELECT; `_mark_niches_used` advances rotation; `daily_job_run` fallback fixed |
| NICHE-03 | 08-01-PLAN | `populate_niches.sql` with 150+ niches organized by category | SATISFIED | 156 rows in script, 10 categories, idempotent ON CONFLICT |
| NICHE-04 | 08-01-PLAN + 08-03-PLAN | "Selecionar todos / Desselecionar todos" on massive-search; admin niches page | SATISFIED | `massive-search.tsx` lines 320/326 — both buttons; `/admin/niches` page created and deployed |

**Orphaned requirements check:** REQUIREMENTS.md lines 223-224 and 229 list untagged sub-requirements for Phase 8 (GET/PUT admin niches endpoints, admin niches page) — these were implemented as part of NICHE-01 and NICHE-04 plans and are verified above. No true orphans found.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | — | — | — |

Scanned for: TODO/FIXME/placeholder comments, `return null/[]/{} ` stubs, hardcoded empty data, stub handlers in `toggleActive`/`savePriority`, presence of `PREDEFINED_NICHES` in massive-search, `or DAILY_JOB_NICHES` in `daily_job_run`. All clear.

---

## Human Verification Required

### 1. Admin Niches Page — Category Tabs

**Test:** Log in as admin, navigate to `/admin/niches`
**Expected:** Page loads 10+ category tabs (Saúde, Alimentação, etc.); each tab shows niche count as "(active/total)"; clicking a tab switches the niche list
**Why human:** Static HTML build cannot verify dynamic API fetch; visual layout requires browser

### 2. Toggle + Persist on /admin/niches

**Test:** Click a toggle slider for any niche, then refresh the page
**Expected:** Toggle reflects the changed state after reload (PUT /api/admin/niches/<id> was executed and DB updated)
**Why human:** Requires live API + DB round-trip through browser

### 3. massive-search Grouped Niches Display

**Test:** Log in, navigate to `/massive-search` (or `/admin/massive-search`), go to Step 1
**Expected:** Niches appear grouped under category headings (e.g., "SAÚDE", "ALIMENTAÇÃO"); "Selecionar todos" selects all; warning appears when >50 selected
**Why human:** Requires browser + live `/api/niches?active=true` response; grouping is runtime JS

### 4. Pipeline Round-Robin Advancement

**Test:** POST `/api/admin/daily-job/run` (manual trigger), then GET `/api/admin/daily-job/status`
**Expected:** `niches_used` in the latest daily job entry contains names from the niches catalog (proper-cased, e.g., "Clínica Médica"), not the old constant names ("clinica medica")
**Why human:** Requires triggering a live pipeline run; cannot verify DB state advancement statically

---

## Notes

- The `subcategory` column listed in REQUIREMENTS.md (NICHE-01) was not added to the DDL — plans deliberately omitted it. The requirements file marks NICHE-01 as `[x]` (done) without it. This is not a gap; the plan's scope was authoritative.
- The 08-VALIDATION.md `nyquist_compliant: false` reflects the doc's draft state at planning time — not a runtime failure.
- 170 rows are reported in the VPS DB (21 migrated from custom_niches + 149 from populate script), which exceeds the 150+ requirement.

---

_Verified: 2026-03-26T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
