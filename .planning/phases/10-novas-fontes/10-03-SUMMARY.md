---
plan: 10-03
phase: 10-novas-fontes
status: complete
completed_at: 2026-03-27
---

## Summary

Integrated Foursquare Places API as Thread 18 in the massive search orchestrator, added source-stats BarChart to admin dashboard, and deployed both backend and frontend.

## What Was Built

**Foursquare Thread 18 (SRC-02)**
- `_get_foursquare_key()` — resolves `FOURSQUARE_API_KEY` from env or AWS SM `extratordedados/prod`
- `search_foursquare_places(niche, city, state, api_key, limit=50)` — calls Foursquare v3 `/places/search` with `Authorization` header; handles 429 → `quota_exceeded`
- `process_foursquare_massive()` decorated `@_persist_thread_errors('foursquare')` — quota-safe, retry 3x, never stops
- Thread 18 wired: `foursquare_jobs` (niches[:3] × cities[:2]), counter, thread start, return dict, default methods list

**Admin Dashboard BarChart (source-stats)**
- `SourceStat` interface + `SOURCE_LABELS` map for human-readable labels
- `sourceStats` state + fetch from `GET /api/admin/source-stats` in useEffect
- `<BarChart>` (recharts, already installed) renders "Leads por Fonte (últimos 30 dias)" — hidden when empty

**Deploy**
- Frontend: 56 files uploaded to HostGator, 0 errors
- Backend: health check OK — `https://api.extratordedados.com.br/api/health`

## Key Files

- `app/backend/app.py` — _get_foursquare_key, search_foursquare_places, process_foursquare_massive, Thread 18 wiring
- `app/frontend/pages/admin/index.tsx` — SourceStat interface, SOURCE_LABELS, sourceStats state, BarChart JSX

## Self-Check: PASSED

- `grep -n "process_foursquare_massive" app/backend/app.py` → 3 lines (def, thread start, decorator)
- `grep -n "BarChart" app/frontend/pages/admin/index.tsx` → import + JSX usage ✓
- Build: `npx next build` exits 0, no TypeScript errors ✓
- Deploy: backend health OK, frontend 56/56 files uploaded ✓
