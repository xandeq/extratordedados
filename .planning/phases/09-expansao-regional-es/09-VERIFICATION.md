---
phase: 09-expansao-regional-es
verified: 2026-03-27T14:00:00Z
status: human_needed
score: 9/9 must-haves verified (code); 3 items pending live-API confirmation after deploy
re_verification: false
human_verification:
  - test: "After VPS backend deploy: GET /api/admin/regions returns 78 cities (requires populate_es_cities.sql to be run)"
    expected: '{"regions": [...], "total": 78}'
    why_human: "VPS was unreachable during execution. Backend code is committed and ready; SQL populate script is ready. Live API tests require VPS access."
  - test: "After VPS deploy: GET /api/admin/pipeline-config returns 'cities' list with 7 entries (Grande Vitória priority-10 cities first)"
    expected: "cities key present with 7 city dicts [{city: 'Vitoria', state: 'ES'}, ...]"
    why_human: "Depends on VPS deploy + populate_es_cities.sql. Round-robin ordering requires live DB with populated regions table."
  - test: "After first pipeline trigger: verify round-robin advances (7 new cities get last_used_at updated, next run picks next 7)"
    expected: "Two consecutive GET /api/admin/regions calls show different last_used_at values for rotated cities"
    why_human: "Requires triggering POST /api/admin/daily-job/run on live VPS, waiting ~30s, and re-checking regions. Cannot simulate without live DB."
  - test: "Browser: /admin/pipeline-config page shows 'Cobertura de Cidades — ES' section with colored city badges"
    expected: "City coverage section visible below the Região dropdown with 78 badge chips (green/gray) and X/78 counter"
    why_human: "Visual UI check. Frontend deployed to HostGator. Badges will show empty state ('Nenhuma cidade cadastrada') until SQL is populated on VPS, then should show real data."
  - test: "Browser: /massive-search page shows 'Cidade específica do ES' as 5th region option with searchable dropdown"
    expected: "5 region cards in Step 2, clicking the ES card shows input + 78-item select; selecting a city enables the search button and sends {city, state: 'ES'} in POST body"
    why_human: "Visual and functional UI check. Dropdown will show 0 items until populate_es_cities.sql runs on VPS (graceful empty state)."
---

# Phase 9: Expansão Regional ES — Verification Report

**Phase Goal:** Pipeline cobre progressivamente todas as 78 cidades do Espírito Santo, rotacionando sem repetir na mesma semana.
**Verified:** 2026-03-27T14:00:00Z
**Status:** human_needed (all code verified; 5 items require live-API / visual confirmation post-deploy)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | regions table with 78 ES cities exists in DB schema | PENDING DEPLOY | DDL in init_db() at app.py:2274 — `CREATE TABLE IF NOT EXISTS regions` with 9 columns, 2 indexes, UNIQUE(city,state). SQL populate script: 78 rows confirmed by `grep -c "'ES'" populate_es_cities.sql` = 78. Pending VPS deploy + SQL run. |
| 2 | GET /api/admin/regions returns all 78 cities with correct fields (id, name, city, state, ibge_code, priority, active, last_used_at, leads_last_30d, leads_total) | PENDING DEPLOY | Endpoint exists at app.py:15522. LEFT JOIN query with COUNT FILTER at line 15546. Field mapping at lines 15553-15563. Code is complete; live response requires VPS deploy. |
| 3 | PUT /api/admin/regions/bulk with {ids:[...], active:false} deactivates regions and returns 200 | PENDING DEPLOY | Endpoint at app.py:15571. `UPDATE regions SET active = %s WHERE id = ANY(%s)` at line 15591. Empty ids validation returns 400 at line 15588. Code complete; live test requires VPS deploy. |
| 4 | round-robin rotation: get_pipeline_config() returns 'cities' list ordered by last_used_at ASC NULLS FIRST | VERIFIED | get_pipeline_config() at app.py:882. Cities query at lines 907-912: `SELECT city, state FROM regions WHERE active=TRUE ORDER BY last_used_at ASC NULLS FIRST, priority ASC, id ASC LIMIT n`. Returns `cities: None` (not []) on empty table (line 935) enabling fallback detection. |
| 5 | trigger_daily_pipeline() uses DB-driven cities from regions table and falls back to SEARCH_REGIONS when table is empty | VERIFIED | DB path at app.py:15082-15089. `db_cities = cfg.get('cities')` → if truthy uses DB cities, calls `_mark_cities_used()`, sets `region_label = f"es_round_robin_{len(db_cities)}cidades"`. Fallback path at lines 15091-15100 logs `[DAILY] regions table vazia`. SEARCH_REGIONS preserved (17 references). |
| 6 | _mark_cities_used() updates last_used_at in regions table, advancing the rotation | VERIFIED | Function at app.py:959. `UPDATE regions SET last_used_at = NOW() WHERE city = ANY(%s) AND state = 'ES'` at line 971. Called in trigger_daily_pipeline() at line 15088 after city selection. Non-fatal error handling. |
| 7 | Admin UI (/admin/pipeline-config) shows city coverage section with green/gray badges | PENDING HUMAN | pipeline-config.tsx: `api.get('/api/admin/regions')` useEffect at line 68. `isRecentlyUsed()` helper at line 74. "Cobertura de Cidades — ES" section at line 264. Badges render at lines 280-300. Counter "X/78 visitadas (7 dias)" at line 272. Visual confirmation needed. |
| 8 | massive-search page has "Cidade específica do ES" as 5th region option with searchable dropdown | PENDING HUMAN | massive-search.tsx: "Cidade específica do ES" button card at line 472. ES city selector rendered at lines 478-508 when `selectedRegion === 'es_city'`. Searchable filter at line 489. Visual confirmation needed. |
| 9 | Selecting a specific ES city passes {city, state: 'ES'} to POST /api/search/massive (not region key) | VERIFIED | massive-search.tsx lines 245-248: `if (selectedRegion === 'es_city' && selectedCity) { payload.city = selectedCity; payload.state = 'ES'; }`. Submit button guard at line 623 adds `|| (selectedRegion === 'es_city' && !selectedCity)`. Original REGIONS constant at line 24 preserved. |

**Score:** 4/9 truths fully verified without deploy; 5/9 pending live VPS or visual confirmation. All code artifacts are substantive and wired.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/backend/app.py` | regions table DDL in init_db() + 2 admin endpoints + idx_leads_city_state | VERIFIED | DDL at line 2274 (inside init_db). GET endpoint at line 15522. PUT bulk at line 15571. idx_leads_city_state at line 2289. All correct. |
| `app/backend/app.py` | _mark_cities_used() + updated get_pipeline_config() + updated trigger_daily_pipeline() | VERIFIED | _mark_cities_used() at line 959. get_pipeline_config() cities query at lines 905-923. trigger_daily_pipeline() DB path at lines 15082-15100. region_label wired to daily_jobs INSERT at line 15124. |
| `scripts/import/populate_es_cities.sql` | 78 ES cities INSERT with IBGE codes, idempotent | VERIFIED | File exists. `grep -c "'ES'"` = 78. `ON CONFLICT (city, state) DO NOTHING` confirmed. Priority tiers: Grande Vitória=10, hubs=20, interior=50. |
| `tests/test_regions.py` | 8 test stubs for REG-01 and REG-02 (skip gracefully when DB empty) | VERIFIED | File exists with exactly 8 `def test_` functions. All tests use `pytest.skip()` on empty DB (not hard failures). Covers auth 401, field validation, count=78, bulk toggle, 400 on empty ids, pipeline-config backward compat, last_used_at structure, round-robin structure. |
| `app/frontend/pages/admin/pipeline-config.tsx` | City coverage section fetching GET /api/admin/regions | VERIFIED | File contains `api.get('/api/admin/regions')` at line 68. `isRecentlyUsed()` defined at line 74. Coverage section JSX at lines 264-305. `setRegions` called 3 times. No @apply usage. Existing Região dropdown unchanged. |
| `app/frontend/pages/massive-search.tsx` | ES city selector with {city, state: 'ES'} POST routing | VERIFIED | "Cidade específica do ES" text at line 472. `api.get('/api/admin/regions')` at line 59. `selectedCity` state at line 66. `payload.city = selectedCity` at line 246. `payload.state = 'ES'` at line 247. Submit disabled guard at line 623. Original REGIONS constant at line 24 preserved. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| init_db() in app.py | regions table | `CREATE TABLE IF NOT EXISTS regions` + 2 indexes | VERIFIED | app.py:2274. idx_regions_active at :2286, idx_regions_last_used at :2287. |
| GET /api/admin/regions | regions + leads tables | LEFT JOIN with COUNT FILTER for 30d window | VERIFIED | app.py:15537-15550. `LEFT JOIN leads l ON l.city = r.city AND l.state = r.state`, `COUNT(l.id) FILTER (WHERE l.extracted_at > NOW() - INTERVAL '30 days')`. |
| PUT /api/admin/regions/bulk | regions table | `UPDATE regions SET active = %s WHERE id = ANY(%s)` | VERIFIED | app.py:15591. Validation at :15588. Admin auth check at :15581-15585. |
| _mark_cities_used() | regions table | `UPDATE regions SET last_used_at = NOW() WHERE city = ANY(%s) AND state = 'ES'` | VERIFIED | app.py:971. Called by trigger_daily_pipeline() at :15088. |
| get_pipeline_config() | regions table | `SELECT city, state FROM regions WHERE active=TRUE ORDER BY last_used_at ASC NULLS FIRST LIMIT n` | VERIFIED | app.py:907-912. Returns `cities` and `daily_cities_per_run` keys. Returns `cities=None` on empty. |
| trigger_daily_pipeline() | regions table via get_pipeline_config() | `cfg.get('cities')` → DB path or SEARCH_REGIONS fallback | VERIFIED | app.py:15082-15100. `region_label` set in both branches, used in daily_jobs INSERT at :15124. |
| pipeline-config.tsx | GET /api/admin/regions | `api.get('/api/admin/regions')` in useEffect, renders as badge grid | VERIFIED | pipeline-config.tsx:68. setRegions(res.data.regions). Coverage section renders at :264. |
| massive-search.tsx | POST /api/search/massive | `selectedCity` state → conditional `payload.city = selectedCity` when `es_city` mode | VERIFIED | massive-search.tsx:245-248. Button guard at :623. |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| REG-01 | 09-01, 09-03 | Tabela regions com 78 cidades do ES + admin endpoints (GET list, PUT bulk toggle) + coverage badges no frontend | VERIFIED (code) / PENDING (live data) | regions table DDL verified. Endpoints verified. SQL script 78 rows verified. Frontend badges wired. Live data after VPS deploy + SQL populate. |
| REG-02 | 09-02, 09-03 | Round-robin city rotation — _mark_cities_used(), get_pipeline_config() cities query, trigger_daily_pipeline() DB path | VERIFIED (code) / PENDING (live pipeline run) | _mark_cities_used() verified. get_pipeline_config() cities query verified. trigger_daily_pipeline() DB path verified. Rotation behavior requires live pipeline trigger to confirm. |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| app/frontend/pipeline-config.tsx | 226, 366, 382 | `placeholder="..."` HTML attribute | Info | These are HTML input placeholder attributes for form fields (niche input, email, healthcheck URL) — NOT code stubs. No impact. |
| app/frontend/massive-search.tsx | 409, 488 | `placeholder="..."` HTML attribute | Info | HTML input placeholders for city search input and niche input — NOT code stubs. No impact. |

No blocker anti-patterns found. No TODO/FIXME/placeholder code stubs detected. No `return null` / empty implementations found in the new code paths. The "empty state" shown in city coverage when DB is empty (`"Nenhuma cidade cadastrada"`) is intentional graceful degradation, not a stub.

---

## Human Verification Required

### 1. VPS Backend Deploy + SQL Population

**Test:** Run `python deploy.py backend`, then `scp scripts/import/populate_es_cities.sql root@185.173.110.180:/tmp/` and `ssh root@185.173.110.180 "docker exec -i extrator-postgres psql -U extrator -d extrator < /tmp/populate_es_cities.sql"`
**Expected:** `curl -s -H "Authorization: Bearer $TOKEN" https://api.extratordedados.com.br/api/admin/regions | python -c "import sys,json;d=json.load(sys.stdin);print('Regions:', d['total']); assert d['total']==78"` prints `Regions: 78`
**Why human:** VPS at 185.173.110.180 was unreachable from this machine (SSH/HTTPS both timed out) during execution. Network restriction on local environment.

### 2. Pipeline-Config Cities Response

**Test:** After deploy + populate: `curl -s -H "Authorization: Bearer $TOKEN" https://api.extratordedados.com.br/api/admin/pipeline-config | python -c "import sys,json;d=json.load(sys.stdin);print('cities:', len(d.get('cities') or []))"`
**Expected:** `cities: 7` — first 7 cities are Grande Vitória (priority=10, last_used_at=NULL initially, so they sort first)
**Why human:** Requires live DB with populated regions table.

### 3. Round-Robin Rotation

**Test:** Trigger `POST /api/admin/daily-job/run` twice with a short delay between runs. After first trigger: GET /api/admin/regions and note last_used_at for first 7 cities. After second trigger: GET again and confirm different 7 cities have last_used_at updated (next batch by priority/id order since all start with last_used_at=NULL).
**Expected:** Two runs update different sets of cities in last_used_at, confirming rotation advances.
**Why human:** Requires actual pipeline triggers on live VPS with populated DB.

### 4. City Coverage Badges Visual Check

**Test:** Navigate to `https://extratordedados.com.br/admin/pipeline-config` (after VPS deploy + SQL populate)
**Expected:** "Cobertura de Cidades — ES" section visible below the Região dropdown. 78 city badges rendered (green for recently used, gray for unused). Counter "0/78 visitadas (7 dias)" shown initially (all gray before any pipeline run). Tooltip on hover shows city name, leads_last_30d, last used date.
**Why human:** Visual UI check. Frontend is deployed. Badges will show empty state until SQL populates DB.

### 5. ES City Selector Functional Check

**Test:** Navigate to `https://extratordedados.com.br/massive-search`. In Step 2, confirm 5 region option cards. Click "Cidade específica do ES". Type "vi" in search box.
**Expected:** 5 cards visible (4 original + 1 ES city). After clicking ES card: searchable input + scrollable select appears. Filtering "vi" shows Vitória, Vila Velha, Viana, Vila Pavão, Vila Valério. Selecting "Vitória" enables search button and shows "Cidade selecionada: Vitoria". Search button disabled if no city selected.
**Why human:** Visual + functional check. City dropdown will be empty until VPS DB is populated (graceful empty state shown).

---

## Gaps Summary

No gaps blocking goal achievement at the code level. The phase goal "Pipeline cobre progressivamente todas as 78 cidades do Espírito Santo, rotacionando sem repetir na mesma semana" is fully implemented in code:

- The infrastructure (regions table, 78-city SQL, indexes) is complete and correct.
- The rotation logic (_mark_cities_used, get_pipeline_config cities query, trigger_daily_pipeline DB path) is wired end-to-end.
- The frontend visibility (city coverage badges, ES city selector) is implemented and deployed.

The only pending items are operational (VPS deploy + SQL populate) and visual/live confirmation, not code gaps. These are marked as `human_needed` per the instruction that "VPS backend deploy is pending — mark live-API tests as pending deploy rather than failed."

**Pending VPS actions to complete the operational setup:**
1. `python deploy.py backend` — deploys app.py with all Phase 9 changes
2. `scp scripts/import/populate_es_cities.sql root@185.173.110.180:/tmp/ && ssh root@185.173.110.180 "docker exec -i extrator-postgres psql -U extrator -d extrator < /tmp/populate_es_cities.sql"`
3. Verify: `curl -s -H "Authorization: Bearer $TOKEN" https://api.extratordedados.com.br/api/admin/regions | python -c "import sys,json;d=json.load(sys.stdin);assert d['total']==78,d['total']"`
4. `pytest tests/ -x --tb=short` — full suite (tests with empty DB will skip gracefully)

---

_Verified: 2026-03-27T14:00:00Z_
_Verifier: Claude (gsd-verifier)_
