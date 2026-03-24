---
phase: 05-export-com-cotas-niche-request-queue
plan: 03
subsystem: ui
tags: [nextjs, react, typescript, export, credits, niche-requests]

requires:
  - phase: 05-export-com-cotas-niche-request-queue
    provides: GET /api/client/leads/export endpoint, niche request endpoints (POST/GET/approve/reject)
  - phase: 04-tier-cliente-reveal-gate-busca-avan-ada
    provides: useClientCredits hook, RevealButton, UpgradeModal, portal.tsx base structure

provides:
  - ClientExportModal component (download trigger, credit cost preview, 402 → UpgradeModal)
  - portal.tsx export button (visible when leads.length > 0)
  - request-niche.tsx page (form + vote list)
  - admin/niche-requests.tsx page (approve/reject table with optimistic UI)
  - Sidebar Solicitar Nicho nav item for client role

affects: [phase-06, deploy-frontend, human-verification]

tech-stack:
  added: []
  patterns:
    - Export modal with credit cost preview before confirming (shows debit amount, not just download)
    - Optimistic status update on approve (pending → processing immediately, rollback on error)
    - fetch() with Bearer token for file download (avoids axios blob handling complexity)
    - Vote list with user_voted flag drives button state (voted = filled blue, not voted = outlined)

key-files:
  created:
    - app/frontend/components/ClientExportModal.tsx
    - app/frontend/pages/request-niche.tsx
    - app/frontend/pages/admin/niche-requests.tsx
  modified:
    - app/frontend/pages/portal.tsx
    - app/frontend/components/Sidebar.tsx

key-decisions:
  - "ClientExportModal uses fetch() not axios for file download — avoids blob streaming complexity with axios interceptors"
  - "Export button placed in portal header row (next to credits display) not in leads list — one action for all current results"
  - "currentFilters computed inline in Portal component (not useCallback) — filters change triggers re-render anyway"
  - "Sidebar Solicitar Nicho only added to clientNavItems (not adminNavItems) — admin has separate niche-requests page via admin nav"
  - "handleVote calls POST /api/client/niche-requests with same niche+city+state — backend deduplicates via vote logic"
  - "Admin handleApprove does optimistic update to processing before API call — provides immediate visual feedback"

requirements-completed: []

duration: ~15min
completed: 2026-03-24
---

# Phase 5 Plan 03: Frontend Export + Niche Request UI Summary

**ClientExportModal with credit cost preview + portal export button + Solicitar Nicho page + admin niche queue with approve/reject**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-24T10:38:25Z
- **Completed:** 2026-03-24T10:53:00Z
- **Tasks:** 2 auto + 1 checkpoint (human-verify APPROVED)
- **Files modified:** 5

## Accomplishments

- Created ClientExportModal.tsx targeting GET /api/client/leads/export — credit cost preview, CSV/JSON format selector, file download via fetch(), 402 opens UpgradeModal, success Toast with remaining balance
- Updated portal.tsx with export button (hidden when no leads), showExportModal/showUpgradeModal state, currentFilters computed object
- Added MessageSquarePlus icon + Solicitar Nicho nav item to Sidebar.tsx clientNavItems (client role only)
- Created request-niche.tsx with form validation (Segmento required), vote list with optimistic user_voted state, 409 conflict handling
- Created admin/niche-requests.tsx with full table (Nicho, Local, Votos, Usuário, Status, Data, Ações), approve/reject with optimistic status update
- Next.js build passes TypeScript clean with all 5 pages/components

## Task Commits

1. **Task 1: ClientExportModal + portal.tsx export button** - `4914c87` (feat)
2. **Task 2: Sidebar + request-niche + admin/niche-requests** - `0b641d3` (feat)

## Files Created/Modified

- `app/frontend/components/ClientExportModal.tsx` - Export modal with credit cost preview, file download, 402 handling
- `app/frontend/pages/portal.tsx` - Added Download button, showExportModal/showUpgradeModal state, currentFilters
- `app/frontend/components/Sidebar.tsx` - Added MessageSquarePlus import + Solicitar Nicho nav item + isActive update
- `app/frontend/pages/request-niche.tsx` - Form + vote list page for client niche requests
- `app/frontend/pages/admin/niche-requests.tsx` - Admin queue table with approve/reject actions

## Decisions Made

- ClientExportModal uses native `fetch()` not axios for file download — avoids blob streaming complexity with axios interceptors
- Export button in portal header row (next to credits display), not in each lead card — one bulk export action
- Sidebar Solicitar Nicho only in clientNavItems — admin has dedicated admin/niche-requests page
- handleVote reuses POST /api/client/niche-requests with same niche/city/state — backend deduplicates
- Admin approve does optimistic status update (pending → processing) — immediate visual feedback, rollback on error

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None — all components are wired to real API endpoints from Plans 01/02.

## Next Phase Readiness

- Human verification APPROVED (Task 3): all 4 flows verified — portal export button + modal + file download, Solicitar Nicho nav item, /request-niche form + vote list, /admin/niche-requests table with Aprovar/Rejeitar
- Phase 5 COMPLETE — all 3 plans done: export endpoints (Plan 01), niche request endpoints (Plan 02), frontend UI (Plan 03)
- Ready for Phase 6: Saved Searches + Notificações de Novos Leads

---
*Phase: 05-export-com-cotas-niche-request-queue*
*Completed: 2026-03-24*
