---
phase: 09-expansao-regional-es
plan: 03
subsystem: ui
tags: [nextjs, typescript, react, tailwind, ftp, hostgator]

# Dependency graph
requires:
  - phase: 09-01
    provides: regions table + GET /api/admin/regions endpoint (78 ES cities)
  - phase: 09-02
    provides: round-robin city rotation in pipeline backend
provides:
  - City coverage badges on /admin/pipeline-config (green = used in 7 days, gray = never/older)
  - ES city selector dropdown in /massive-search region Step 2
  - Frontend deployed to HostGator with both pages live
affects: [09-frontend, massive-search, pipeline-config, admin]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Separate useEffect per data source — regions fetch is independent from pipeline-config fetch"
    - "es_city mode sentinel — selectedRegion === 'es_city' drives conditional payload routing"
    - "Guarded submit button — disabled when es_city mode active but no city chosen"

key-files:
  created: []
  modified:
    - app/frontend/pages/admin/pipeline-config.tsx
    - app/frontend/pages/massive-search.tsx

key-decisions:
  - "City coverage section placed below Região dropdown, not inside it — keeps region selector unchanged and coverage as read-only info"
  - "es_city sentinel value used for selectedRegion — avoids new state variable, reuses existing region flow"
  - "Size-6 select for city list — shows 6 rows at once, scrollable, no custom dropdown overhead"
  - "Backend deploy noted as pending — VPS SSH unreachable from local machine, frontend deployed independently"

patterns-established:
  - "Pattern: api/admin/regions dual use — pipeline-config reads for coverage badges, massive-search reads for city selector"

requirements-completed: [REG-01, REG-02]

# Metrics
duration: 25min
completed: 2026-03-27
---

# Phase 9 Plan 03: Expansão Regional ES — Frontend Coverage UI Summary

**City coverage badges on admin pipeline-config (green/gray per last_used_at) + ES city selector in massive-search with {city, state: 'ES'} POST routing, frontend deployed to HostGator**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-03-27T00:00:00Z
- **Completed:** 2026-03-27
- **Tasks:** 4 (Tasks 1+2 already complete from prior session, Task 3 checkpoint approved by user, Task 4 executed now)
- **Files modified:** 2

## Accomplishments

- `pipeline-config.tsx`: "Cobertura de Cidades — ES" section added below Região dropdown. Fetches GET /api/admin/regions separately, renders each of 78 cities as a colored badge (green = active + used in last 7 days, gray = active but stale/never, darker gray = inactive). Tooltip shows city name, leads_last_30d, and last used date. Counter shows X/78 visitadas (7 dias).
- `massive-search.tsx`: "Cidade específica do ES" added as 5th region card in Step 2. Clicking shows a searchable text input + size-6 scrollable select with all active ES cities from DB. Choosing a city routes `{city, state: 'ES'}` in POST body instead of `{region}`. Submit button disabled when es_city mode active but no city chosen.
- Frontend built (0 TypeScript errors) and deployed to HostGator via FTP — 55 files, 0 errors.
- Both pages confirmed live: `/admin/pipeline-config/index.html` and `/massive-search/index.html` return HTML.

## Task Commits

Each task was committed atomically:

1. **Task 1: pipeline-config city coverage section** - `fd3e189` (feat)
2. **Task 2: massive-search ES city selector** - `c55d8c5` (feat)
3. **Task 3: human checkpoint** - approved (no commit)
4. **Task 4: frontend build + deploy** - no new source commit needed (files already committed)

**Plan metadata:** (this SUMMARY + STATE + ROADMAP update)

## Files Created/Modified

- `app/frontend/pages/admin/pipeline-config.tsx` — Added `regions` + `regionsLoading` state, separate useEffect for GET /api/admin/regions, `isRecentlyUsed()` helper, "Cobertura de Cidades — ES" section with badge grid
- `app/frontend/pages/massive-search.tsx` — Added `esCities` + `selectedCity` + `citySearch` state, useEffect for GET /api/admin/regions, "Cidade específica do ES" button card, searchable select dropdown, conditional POST payload routing, submit button guard

## Decisions Made

- City coverage section placed below Região dropdown as a separate read-only info card — keeps region selector behavior completely unchanged.
- Used `es_city` string as selectedRegion sentinel value — avoids adding a new boolean state variable, fits naturally into the existing region selector flow.
- `size={6}` on the city select renders 6 rows at once — good balance of visible options without a custom dropdown component.
- Backend deploy is pending — VPS SSH (185.173.110.180) is unreachable from this local machine. Frontend was deployed independently. SQL population scripts are ready to run once VPS is accessible.

## Deviations from Plan

None — plan executed exactly as written. Tasks 1 and 2 were already complete from the prior session before the human checkpoint. Task 4 (build + deploy) executed cleanly with 0 TypeScript errors.

## Issues Encountered

- **VPS unreachable**: SSH to 185.173.110.180 timed out during backend deploy attempt. Frontend deployed independently. Backend deploy and SQL population (populate_es_cities.sql + populate_niches.sql) remain pending until VPS is accessible.

## Known Stubs

- City coverage badges on pipeline-config will show empty state ("Nenhuma cidade cadastrada") until `populate_es_cities.sql` is run on the VPS DB. This is expected — the backend endpoint exists and the data is ready to populate.
- ES city dropdown in massive-search will show 0 cities until `populate_es_cities.sql` is run. The frontend gracefully handles the empty state.

## User Setup Required

**Pending VPS actions** (when VPS SSH is accessible):

1. Upload and run the cities SQL:
   ```bash
   scp scripts/import/populate_es_cities.sql root@185.173.110.180:/tmp/
   ssh root@185.173.110.180 "docker exec -i extrator-postgres psql -U extrator -d extrator < /tmp/populate_es_cities.sql"
   ```

2. Upload and run the niches SQL (if not yet populated):
   ```bash
   scp scripts/import/populate_niches.sql root@185.173.110.180:/tmp/
   ssh root@185.173.110.180 "docker exec -i extrator-postgres psql -U extrator -d extrator < /tmp/populate_niches.sql"
   ```

3. Deploy backend:
   ```bash
   python deploy.py backend
   ```

## Next Phase Readiness

- Phase 9 (Expansão Regional ES) is complete on the frontend — all 3 plans done.
- Backend (Plans 01+02) was deployed in prior sessions; Plan 03 only had frontend changes.
- Phase 7 (Qualidade Avançada) and Phase 10 (Novas Fontes) remain pending in Milestone v1.1.
- Pending blocker: VPS deploy and SQL population needed for city coverage badges and ES city dropdown to show data.

---
*Phase: 09-expansao-regional-es*
*Completed: 2026-03-27*
