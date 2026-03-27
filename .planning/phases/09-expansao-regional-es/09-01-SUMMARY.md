---
phase: 09-expansao-regional-es
plan: 01
subsystem: database
tags: [postgres, flask, regions, ibge, round-robin, admin-api]

# Dependency graph
requires:
  - phase: 08-catalogo-nichos
    provides: niches table pattern + admin endpoint pattern (mirrored for regions)

provides:
  - regions table in PostgreSQL with 9-column schema and 2 indexes
  - idx_leads_city_state composite index on leads(city, state) for JOIN performance
  - GET /api/admin/regions — admin-only list with leads_last_30d + leads_total via LEFT JOIN
  - PUT /api/admin/regions/bulk — bulk activate/deactivate by ID list
  - populate_es_cities.sql — 78 ES cities with verified IBGE codes, idempotent
  - tests/test_regions.py — 8 test stubs for REG-01 and REG-02 behaviors

affects:
  - 09-02 (round-robin rotation reads from regions table)
  - 09-03 (frontend coverage UI calls GET /api/admin/regions)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "regions table mirrors niches table pattern exactly (Phase 8 → Phase 9)"
    - "PUT /api/admin/regions/bulk registered BEFORE any /<int:region_id> to prevent Flask route conflict"
    - "Admin auth pattern: 401 for no token, 403 for non-admin (standard codebase pattern)"
    - "idx_leads_city_state enables efficient LEFT JOIN for leads-per-city aggregation"

key-files:
  created:
    - scripts/import/populate_es_cities.sql
    - tests/test_regions.py
  modified:
    - app/backend/app.py

key-decisions:
  - "Use IBGE codes from plan (verified against servicodados.ibge.gov.br API) — codes follow 32XXXXX pattern for ES"
  - "name column stores accented display name (Vitória); city column stores ASCII form (Vitoria) for scraper queries"
  - "idx_leads_city_state added in Wave 0 to prevent slow JOIN when leads table grows large"
  - "UNIQUE(city, state) enables idempotent populate_es_cities.sql via ON CONFLICT DO NOTHING"

patterns-established:
  - "Phase 9 regions table follows Phase 8 niches pattern exactly — same column structure, same index pattern, same admin endpoint pattern"
  - "Bulk route /api/admin/regions/bulk registered before /<int:region_id> to prevent Flask matching 'bulk' as integer"

requirements-completed: [REG-01]

# Metrics
duration: 8min
completed: 2026-03-27
---

# Phase 9 Plan 01: Regions DB Foundation Summary

**PostgreSQL regions table with 9-column schema, 78 ES cities SQL script with IBGE codes, and 2 admin API endpoints (GET list + PUT bulk toggle) mirroring the Phase 8 niches pattern**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-27T11:00:42Z
- **Completed:** 2026-03-27T11:08:26Z
- **Tasks:** 3 of 4 (Task 4 deploy blocked — see Issues)
- **Files modified:** 3

## Accomplishments

- regions table created in init_db() with correct 9-column schema and UNIQUE(city, state) constraint
- populate_es_cities.sql created with 78 ES cities: 7 at priority 10 (Grande Vitória), 4 at priority 20 (regional hubs), 67 at priority 50 (interior)
- GET /api/admin/regions and PUT /api/admin/regions/bulk endpoints added after niches endpoints block
- idx_leads_city_state composite index added for efficient leads-per-city JOIN aggregation
- 8 test stubs created in tests/test_regions.py that skip gracefully when DB is empty

## Task Commits

Each task was committed atomically:

1. **Task 1: regions table DDL + idx_leads_city_state** - `ed4fa38` (feat)
2. **Task 2: populate_es_cities.sql — 78 cities** - `a39cfa8` (feat)
3. **Task 3: admin endpoints + test stubs** - `652f1e8` (feat)

_Task 4 (deploy) blocked by VPS unreachable — see Issues Encountered_

## Files Created/Modified

- `app/backend/app.py` — regions table DDL in init_db() (lines 2237-2252) + 2 new admin endpoints (lines 15473-15543)
- `scripts/import/populate_es_cities.sql` — 78 ES cities INSERT with IBGE codes, idempotent
- `tests/test_regions.py` — 8 test stubs for REG-01 and REG-02 behaviors

## Decisions Made

- Followed Phase 8 niches pattern exactly: same column names, same index names, same admin endpoint pattern — zero learning curve for Plan 02
- Used `city` (ASCII) vs `name` (accented) dual-column design: `city` is used in scraper URL queries, `name` is shown in UI
- PUT /api/admin/regions/bulk registered BEFORE any future /<int:region_id> route to prevent Flask route conflict (same anti-pattern from Phase 8 STATE.md decision log)
- idx_leads_city_state added in Wave 0 (not deferred to Plan 03) because the LEFT JOIN in GET /api/admin/regions uses it immediately

## Deviations from Plan

None — plan executed exactly as written for Tasks 1-3.

## Issues Encountered

**VPS Unreachable — Task 4 deploy blocked**

- VPS at 185.173.110.180 is unreachable from this machine (SSH port 22 timed out, ping 100% packet loss, HTTPS also timed out)
- This appears to be a network restriction on the current environment
- All code changes are committed and ready to deploy
- **Deploy command when VPS is accessible:** `python deploy.py backend`
- **After deploy, run populate:**
  ```bash
  scp scripts/import/populate_es_cities.sql root@185.173.110.180:/tmp/populate_es_cities.sql
  ssh root@185.173.110.180 "docker exec -i extrator-postgres psql -U extrator -d extrator < /tmp/populate_es_cities.sql"
  ```
- **After populate, verify:** `curl -s -H "Authorization: Bearer TOKEN" https://api.extratordedados.com.br/api/admin/regions | python -c "import sys,json;d=json.load(sys.stdin);print('Regions:', d['total']); assert d['total']==78"`
- **After deploy, run full test suite:** `pytest tests/ -x --tb=short`

## Known Stubs

None — no placeholder data wired to UI. The admin endpoint returns live DB data. The test stubs skip gracefully with `pytest.skip()` when the DB is empty (not placeholder text, intentional skip behavior).

## Next Phase Readiness

- Plan 02 (round-robin rotation) can start immediately — all DB infrastructure is ready
- regions table exists with UNIQUE(city, state) constraint and correct indexes
- GET /api/admin/regions returns the data Plan 02 needs for _mark_cities_used() verification
- Blocker: deploy must be done before Plan 02's test suite can run against the live API

---
*Phase: 09-expansao-regional-es*
*Completed: 2026-03-27*
