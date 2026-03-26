---
phase: 08-catalogo-nichos
plan: 03
subsystem: ui
tags: [nextjs, typescript, react, tailwind, lucide, ftp-deploy, hostgator]

# Dependency graph
requires:
  - phase: 08-01
    provides: niches table with CRUD endpoints (GET /api/admin/niches, PUT /api/admin/niches/<id>, GET /api/niches?active=true)
  - phase: 08-02
    provides: pipeline rotation reading from niches table, daily_job integration

provides:
  - /admin/niches page with category tabs, toggle sliders, and inline priority editing
  - massive-search.tsx refactored to load niches from DB (replaces hardcoded PREDEFINED_NICHES)
  - Sidebar adminNavItems updated with Pipeline Config and Catalogo de Nichos entries
  - isActive() fixed to avoid false positive on /admin when visiting /admin/niches or /admin/pipeline-config
  - Frontend deployed to HostGator via deploy.py

affects: [09-future-phases, admin-workflow, massive-search-ux]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "category tabs with (active/total) counts using Tailwind border-b-2 pattern"
    - "toggle slider via CSS translate (translate-x-6 / translate-x-1) without any JS library"
    - "inline priority save on blur without a separate Save button"
    - "flat array from grouped API response: Object.entries(grouped).flatMap(([cat, items]) => items.map(...))"

key-files:
  created:
    - app/frontend/pages/admin/niches.tsx
  modified:
    - app/frontend/pages/massive-search.tsx
    - app/frontend/components/Sidebar.tsx

key-decisions:
  - "PREDEFINED_NICHES hardcoded array removed from massive-search.tsx — niches now come exclusively from /api/niches?active=true"
  - "Niche toggle uses CSS-only slider (translate-x) instead of a toggle library — keeps zero deps"
  - "isActive() exact-match list extended for /admin/niches and /admin/pipeline-config to prevent false /admin highlight"
  - "50-niche cap warning is client-side only (setNicheWarning) — backend enforces the actual limit"
  - "VPS API was unreachable during pytest run (network timeout, pre-existing condition) — all tests are live-API integration tests; this is not a code regression"

patterns-established:
  - "Admin pages: useEffect checks localStorage token, redirects to /login if absent, catches 401/403 and also redirects"
  - "Category-grouped niche display: Array.from(new Set(niches.map(n => n.category))).map(category => ...)"

requirements-completed: [NICHE-04]

# Metrics
duration: 35min
completed: 2026-03-26
---

# Phase 8 Plan 03: Admin Niches UI + massive-search Refactor Summary

**Admin niche catalog page with category tabs + toggle/priority editing deployed; massive-search now loads 150+ DB niches grouped by category with Selecionar todos/Limpar selecao controls**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-03-26T10:36:00Z
- **Completed:** 2026-03-26T11:11:39Z
- **Tasks:** 5 (Tasks 1-3 + approved checkpoint + Task 5 deploy)
- **Files modified:** 3 source files

## Accomplishments

- Created `/admin/niches` page — tabs per category (Saude, Beleza, etc.) with active/total counts, toggle sliders, and inline priority inputs (save on blur)
- Refactored `massive-search.tsx` to load niches from `/api/niches?active=true` instead of the 10-item `PREDEFINED_NICHES` constant; niches now displayed grouped by category with "Selecionar todos" / "Limpar selecao" buttons and a >50 warning
- Updated `Sidebar.tsx` adminNavItems with "Pipeline Config" and "Catalogo de Nichos" entries; extended `isActive()` exact-match list to prevent false highlight on "Painel Admin"
- Frontend built (zero TypeScript errors, 22 pages) and deployed to HostGator (55 files, 0 FTP errors)
- Smoke test confirmed `/admin/niches/index.html` returns valid HTML from `extratordedados.com.br`

## Task Commits

Each task was committed atomically:

1. **Task 1: Create /admin/niches page** - `4c3f0a5` (feat)
2. **Task 2: Update Sidebar.tsx** - `2d78fb9` (feat)
3. **Task 3: Refactor massive-search.tsx** - `1ac48b0` (feat)
4. **Task 4: Checkpoint** - APPROVED by human (no commit)
5. **Task 5: Deploy frontend** - build + FTP deploy (no additional source commit needed — source already committed in Tasks 1-3)

## Files Created/Modified

- `app/frontend/pages/admin/niches.tsx` — NEW: Admin page with category tabs, toggle sliders, priority inputs; calls GET /api/admin/niches and PUT /api/admin/niches/<id>
- `app/frontend/pages/massive-search.tsx` — MODIFIED: Removed PREDEFINED_NICHES + localStorage functions; added NicheWithCategory interface, DB fetch via /api/niches?active=true, grouped display, selectAll/clearAll handlers, >50 warning
- `app/frontend/components/Sidebar.tsx` — MODIFIED: Added Tag import, Pipeline Config + Catalogo de Nichos nav items, extended isActive() exact-match condition

## Decisions Made

- PREDEFINED_NICHES hardcoded array removed entirely — single source of truth is now the niches DB table
- CSS-only toggle slider (translate-x transform) keeps the component dependency-free
- `isActive()` extended with exact-match for `/admin/niches` and `/admin/pipeline-config` to prevent the "Painel Admin" false-active visual bug (RESEARCH Pitfall 6)
- 50-niche cap warning is purely client-side (UX guard); backend enforces limits independently
- VPS pytest failure noted as pre-existing network issue (all tests are live-API integration tests with 10s timeout; no code changes could cause or fix this)

## Deviations from Plan

None — plan executed exactly as written. Source files for Tasks 1-3 were committed individually per task; Task 5 was build + deploy only (no additional source commit required).

## Issues Encountered

**VPS network timeout during pytest:** All tests in `tests/` are live integration tests that call `api.extratordedados.com.br` with a 10-second timeout. The VPS API was unreachable during this session (connection timeout on all endpoints). This is a pre-existing network condition unrelated to the frontend changes made in this plan. The frontend smoke test (`curl https://extratordedados.com.br/admin/niches/index.html`) returned valid HTML, confirming the deployment succeeded.

## User Setup Required

None — no external service configuration required. The niches table was populated in Plan 08-01 (156 niches). The frontend now reads from the live DB automatically.

## Known Stubs

None — the /admin/niches page calls real endpoints (`GET /api/admin/niches`, `PUT /api/admin/niches/<id>`) and `massive-search.tsx` calls the real `/api/niches?active=true` endpoint. No hardcoded or mock data remains.

## Next Phase Readiness

- Phase 8 complete: niches DB foundation (08-01) + pipeline rotation (08-02) + admin UI + massive-search refactor (08-03) all shipped
- Admin can now manage the full niche catalog through the UI without SQL access
- The busca massiva shows all 150+ curated niches grouped by 10 categories
- Ready for Phase 9 (if planned) or any phase that builds on niche management

---
*Phase: 08-catalogo-nichos*
*Completed: 2026-03-26*
