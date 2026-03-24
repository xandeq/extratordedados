---
phase: 05-export-com-cotas-niche-request-queue
plan: "04"
subsystem: backend-extraction + frontend-navigation
tags: [gap-closure, niche-requests, sidebar, search-engines]
dependency_graph:
  requires: [05-03]
  provides: [P5-NICHE-APPROVE]
  affects: [app/backend/app.py, app/frontend/components/Sidebar.tsx]
tech_stack:
  added: []
  patterns: [background-thread-extraction, daemon-thread, search-engines-processor]
key_files:
  modified:
    - app/backend/app.py
    - app/frontend/components/Sidebar.tsx
decisions:
  - "Use process_search_job (not process_search_engines_massive which doesn't exist) — same function used by massive search Thread 2"
  - "3 search_jobs created per approval (duckduckgo/bing/yahoo engines) for better coverage"
  - "user_id=1 for system batch (admin user, safe assumption per plan spec)"
  - "leads_added count persisted to niche_requests row after extraction completes"
metrics:
  duration: ~5 min
  completed: 2026-03-24
  tasks: 2/2
  files: 2
---

# Phase 05 Plan 04: Niche Extraction Gap Closure Summary

Closed two gaps preventing Phase 5 from fully achieving its goal: wired niche approval to real DuckDuckGo+Bing extraction and added admin sidebar nav to the orphaned niche requests page.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Wire _trigger_niche_extraction to real search pipeline | 4e2b90d | app/backend/app.py |
| 2 | Add Fila de Nichos to adminNavItems in Sidebar.tsx | c1b03a3 | app/frontend/components/Sidebar.tsx |

## What Was Built

**Task 1 — Backend extraction wiring:**
Replaced the stub body of `_trigger_niche_extraction` (which immediately set `status='done'` with no search) with real extraction logic:
1. Creates a shared batch row in the `batches` table (`is_shared=True`, `user_id=1`)
2. Creates 3 `search_jobs` rows (engines: duckduckgo, bing, yahoo)
3. Calls `process_search_job(batch_id, jobs_data, 1)` — the existing search engines processor (DuckDuckGo + Bing, pure HTTP, no Playwright, safe in daemon thread)
4. After completion, counts `leads_added` (leads in batch after minus before)
5. Updates `niche_requests` with `status='done'`, `leads_added=N`, `completed_at=NOW()`
6. On error, rolls back status to `'pending'` (preserved from original)

**Task 2 — Sidebar nav item:**
Added `{ href: '/admin/niche-requests', label: 'Fila de Nichos', icon: MessageSquarePlus }` to `adminNavItems` between "Planos & Limites" and "System Logs". Uses `MessageSquarePlus` which was already imported at line 20. Array now has 8 items (was 7).

## Deviations from Plan

**1. [Rule 1 - Bug] Corrected function name `process_search_engines_massive` → `process_search_job`**
- **Found during:** Task 1 read_first phase
- **Issue:** Plan's `<interfaces>` block listed `process_search_engines_massive` as the function to call, but searching `app.py` found no such function. The actual function that Thread 2 (search engines) uses in `start_massive_search` is `process_search_job(batch_id, search_jobs_data, user_id)`.
- **Fix:** Used `process_search_job` — same function, same signature, identical result. The plan's `<artifacts>` section also mentioned `process_search_engines_massive` as the `contains` value for app.py, but the acceptance criteria can still be satisfied because the function call is present in `_trigger_niche_extraction` (just with the correct name).
- **Files modified:** app/backend/app.py (no additional change — used correct name from start)
- **Commit:** 4e2b90d

## Known Stubs

None — both gaps are fully wired. `_trigger_niche_extraction` performs real extraction; admin sidebar links to the real page.

## Verification Results

- Python syntax: `python -c "import ast; ast.parse(...)"` → syntax OK
- `process_search_job` appears 6 times in app.py (definition + usages including new call)
- `INSERT INTO batches` appears inside `_trigger_niche_extraction` body (line ~16162)
- `leads_added` count computed and stored (lines ~16202-16210)
- `grep -n "niche-requests" Sidebar.tsx` → 1 match at line 41 in adminNavItems
- `grep -n "Fila de Nichos" Sidebar.tsx` → 1 match
- TypeScript: `npx tsc --noEmit` → no errors
- Next.js build: `npx next build` → exits 0, all pages static

## Self-Check: PASSED

- [x] app/backend/app.py modified and committed (4e2b90d)
- [x] app/frontend/components/Sidebar.tsx modified and committed (c1b03a3)
- [x] Both commits exist in git log
- [x] Python syntax valid
- [x] TypeScript and Next.js build clean
