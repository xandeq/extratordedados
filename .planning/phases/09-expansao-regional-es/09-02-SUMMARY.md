---
phase: 09-expansao-regional-es
plan: 02
subsystem: backend
tags: [flask, postgres, round-robin, regions, pipeline, daily-job]

# Dependency graph
requires:
  - phase: 09-01
    provides: regions table + 78 ES cities SQL + admin endpoints

provides:
  - _mark_cities_used() helper in app/backend/app.py
  - get_pipeline_config() returns 'cities' and 'daily_cities_per_run' keys
  - trigger_daily_pipeline() uses DB-driven cities with SEARCH_REGIONS fallback
  - daily_jobs.region_used records 'es_round_robin_Ncidades' for DB-driven runs

affects:
  - 09-03 (frontend coverage UI reads get_pipeline_config via pipeline-config endpoint)
  - daily pipeline execution (next nightly run will use DB-driven city rotation)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_mark_cities_used() mirrors _mark_niches_used() exactly — same pattern, same error handling"
    - "get_pipeline_config() is READ-ONLY — both read (niches + cities) done here, writes done in _mark_*_used()"
    - "trigger_daily_pipeline() uses cfg['cities'] is not None as the branch selector for DB-driven vs legacy path"
    - "SEARCH_REGIONS dict preserved intact — only trigger_daily_pipeline() gets the new DB path, all other endpoints unchanged"

key-files:
  created: []
  modified:
    - app/backend/app.py

key-decisions:
  - "cities=None (not []) in fallback is intentional — allows trigger_daily_pipeline() to distinguish 'no regions configured' from 'zero cities selected'"
  - "region_label stored in daily_jobs.region_used — 'es_round_robin_7cidades' makes pipeline mode visible at a glance in admin UI"
  - "run_daily_pipeline() call signature unchanged — cities_to_search format identical whether from DB or SEARCH_REGIONS"
  - "_mark_cities_used() called AFTER city selection, BEFORE DB INSERT for daily_jobs — ensures last_used_at advances before any potential lock failure"

# Metrics
duration: 11min
completed: 2026-03-27
---

# Phase 9 Plan 02: Round-Robin City Rotation Summary

**Round-robin city rotation wired into daily pipeline: _mark_cities_used() helper + get_pipeline_config() cities query + trigger_daily_pipeline() DB-driven path with SEARCH_REGIONS fallback**

## Performance

- **Duration:** 11 min
- **Started:** 2026-03-27T11:12:36Z
- **Completed:** 2026-03-27T11:23:xx Z
- **Tasks:** 3 of 4 (Task 4 deploy blocked — VPS unreachable from this machine)
- **Files modified:** 1

## Accomplishments

- `_mark_cities_used(city_names)` added immediately after `_mark_niches_used()` — exact mirror of the niches pattern, using `city` column (ASCII) + `state = 'ES'` WHERE condition
- `get_pipeline_config()` extended with cities query: `SELECT city, state FROM regions WHERE active=TRUE ORDER BY last_used_at ASC NULLS FIRST, priority ASC, id ASC LIMIT n` — returns `cities` and `daily_cities_per_run` keys; `cities=None` when table empty
- `trigger_daily_pipeline()` updated: when `cfg['cities']` is populated → uses DB cities, calls `_mark_cities_used()`, sets `region_label='es_round_robin_Ncidades'`; when empty → falls back to `SEARCH_REGIONS[region_id]` with clear `[DAILY] regions table vazia` log message; when both empty → logs error and returns None
- `daily_jobs.region_used` now stores `region_label` (e.g., `'es_round_robin_7cidades'`) for DB-driven runs vs legacy region key (e.g., `'grande_vitoria_es'`) for fallback runs
- `SEARCH_REGIONS` dict untouched — 17 references throughout app.py all preserved
- `run_daily_pipeline()` signature unchanged — still receives `(daily_job_id, niches, region_id, cities_to_search)`

## Task Commits

Each task was committed atomically:

1. **Task 1: _mark_cities_used() helper** - `5290b8d` (feat)
2. **Task 2: get_pipeline_config() cities query** - `3bffec4` (feat)
3. **Task 3: trigger_daily_pipeline() DB-driven path** - `366a3e9` (feat)

_Task 4 (deploy) blocked by VPS unreachable — see Issues Encountered_

## Files Created/Modified

- `app/backend/app.py`:
  - Lines 959-977: `_mark_cities_used()` function (after `_mark_niches_used()`)
  - Lines 905-913: cities query block inside `get_pipeline_config()` try block
  - Lines 921-923: `'cities'` and `'daily_cities_per_run'` keys added to return dict
  - Lines 933-936: `'cities': None` and `'daily_cities_per_run': 7` added to except fallback dict
  - Lines 15082-15101: DB-driven city path + SEARCH_REGIONS fallback in `trigger_daily_pipeline()`
  - Line 15124: `region_label` replaces `region_id` in daily_jobs INSERT

## Decisions Made

- `cities=None` not `cities=[]` when regions table empty — enables simple truthy check in trigger_daily_pipeline() (`if db_cities:`) that correctly handles both None and empty list as fallback triggers
- `_mark_cities_used()` called before the advisory lock acquire (before the DB INSERT) — this is deliberate; if the INSERT fails (another worker got the lock), the last_used_at is already updated which is acceptable (the cities will be picked next time via round-robin anyway)
- Kept `region_id` unchanged in the `threading.Thread` args for `run_daily_pipeline()` — the function uses `region_id` for internal logging only; the actual city routing is done via `cities_to_search`

## Deviations from Plan

None — plan executed exactly as written for Tasks 1-3.

## Issues Encountered

**VPS Unreachable — Task 4 deploy blocked (same as Plan 01)**

- VPS at 185.173.110.180 is unreachable from this machine (SSH/HTTPS both timeout)
- Test suite (`pytest tests/test_regions.py`) also fails due to API connectivity timeout
- This is a network restriction on the current environment, not a code issue
- All 3 code tasks are committed and ready to deploy

**Deploy command when VPS is accessible:**
```bash
cd "c:/Users/acq20/Desktop/Trabalho/Alexandre Queiroz Marketing Digital/DIAX/extrator-de-dados"
python deploy.py backend
```

**After deploy, run populate (if not done from Plan 01):**
```bash
scp scripts/import/populate_es_cities.sql root@185.173.110.180:/tmp/populate_es_cities.sql
ssh root@185.173.110.180 "docker exec -i extrator-postgres psql -U extrator -d extrator < /tmp/populate_es_cities.sql"
```

**After deploy, verify round-robin active:**
```bash
TOKEN=$(curl -s -X POST https://api.extratordedados.com.br/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"ADMIN_PASS"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -s -H "Authorization: Bearer $TOKEN" \
  https://api.extratordedados.com.br/api/admin/pipeline-config \
  | python -c "import sys,json; d=json.load(sys.stdin); print('cities:', len(d.get('cities') or [])); [print(' -', c) for c in (d.get('cities') or [])]"
```

Expected output: `cities: 7` then 7 Grande Vitória cities (Vitoria, Vila Velha, Serra, Cariacica, Viana, Guarapari, Fundao) — all NULL last_used_at so they sort first by priority=10.

**After deploy, run full test suite:**
```bash
pytest tests/ -x --tb=short
```

## Code Verification (static, no VPS needed)

All 6 plan verification checks pass:
1. `grep "def _mark_cities_used" app/backend/app.py` → line 959
2. `grep "SELECT city.*FROM regions" app/backend/app.py` → line 907 (inside get_pipeline_config)
3. `grep "es_round_robin" app/backend/app.py` → lines 15085, 15089
4. `grep "SEARCH_REGIONS" app/backend/app.py | wc -l` → 17 (well over 5)
5. `grep "'cities':.*None" app/backend/app.py` → line 935 (in except fallback)
6. `grep "ORDER BY last_used_at ASC NULLS FIRST" app/backend/app.py` → lines 898, 908 (niches + cities)

## Known Stubs

None — all implemented code is wired to real DB queries. The `cities=None` fallback is intentional design (not a stub), enabling SEARCH_REGIONS legacy path.

## Next Phase Readiness

- Plan 03 (frontend coverage UI) can start immediately — `GET /api/admin/pipeline-config` endpoint already returns `cities` key
- Round-robin rotation will be active immediately after VPS deploy + populate_es_cities.sql run
- Blocker for testing: VPS deploy must be done before integration tests can run against live API

---
*Phase: 09-expansao-regional-es*
*Completed: 2026-03-27*
