---
phase: 06-saved-searches-notifica-es-de-novos-leads
plan: 03
subsystem: frontend
tags: [saved-searches, portal, sidebar, frontend, wave-3]
dependency_graph:
  requires:
    - 06-02 (POST/GET/DELETE/PATCH /api/client/saved-searches endpoints, APScheduler notification job)
  provides:
    - /saved-searches page (list, toggle notify, delete)
    - "Salvar Busca" button + modal on /portal
    - Sidebar "Buscas Salvas" nav link for client users
  affects:
    - app/frontend/pages/saved-searches.tsx (created)
    - app/frontend/pages/portal.tsx (Salvar Busca button + modal + saveSearch handler)
    - app/frontend/components/Sidebar.tsx (Bookmark import + clientNavItems entry)
tech_stack:
  added: []
  patterns:
    - Inline modal pattern (no separate component file) — consistent with portal.tsx style
    - Toggle switch using CSS transform translate-x (consistent with RESEARCH.md pattern)
    - api.get/patch/delete pattern with 401 redirect to /login
    - State vars for modal (showSaveModal, saveName, saveEmail, saving, saveSuccess, saveError)
key_files:
  created:
    - app/frontend/pages/saved-searches.tsx
  modified:
    - app/frontend/pages/portal.tsx
    - app/frontend/components/Sidebar.tsx
decisions:
  - Inline modal in portal.tsx (no separate component) — simplest approach, no extra file
  - /saved-searches added to isActive exact-match list in Sidebar to prevent false active state on sub-paths
  - Bookmark icon added alongside existing imports (BookMarked already present, Bookmark is different — filled bookmark)
  - notify_enabled defaults to true on save so users immediately get notifications unless they toggle off
metrics:
  duration: ~16 min
  completed: "2026-03-24"
  tasks: 2/2
  files: 3
---

# Phase 06 Plan 03: Frontend — Saved Searches Page + Salvar Busca Button Summary

Client-facing frontend for saved searches: /saved-searches management page with notification toggle + delete, "Salvar Busca" button + modal on /portal wired to POST /api/client/saved-searches, and "Buscas Salvas" Sidebar nav link for client users. Frontend deployed via FTP (54 files, 0 errors).

## What Was Built

### Task 1: saved-searches.tsx + Sidebar nav link

**app/frontend/pages/saved-searches.tsx** (147 lines):
- Fetches GET /api/client/saved-searches on mount
- Renders each saved search with: name, filter summary (category · city · state), last notified date, notify email
- Notification toggle: calls PATCH /api/client/saved-searches/<id> with {notify_enabled: !current}; updates row in local state on success
- Delete button: calls DELETE /api/client/saved-searches/<id>; removes row from local state
- Empty state: "Nenhuma busca salva. Acesse o portal e clique em 'Salvar Busca'."
- 401 response redirects to /login via useRouter
- Loading and error states handled

**app/frontend/components/Sidebar.tsx**:
- Added `Bookmark` to lucide-react imports
- Added `{ href: '/saved-searches', label: 'Buscas Salvas', icon: Bookmark }` to clientNavItems
- Added `/saved-searches` to isActive exact-match list

### Task 2: "Salvar Busca" button + modal on portal.tsx + deploy

**app/frontend/pages/portal.tsx**:
- Added `Bookmark` to lucide-react import line
- Added 6 state vars: showSaveModal, saveName, saveEmail, saving, saveSuccess, saveError
- Added `saveSearch()` async handler: validates name, POSTs to /api/client/saved-searches with all current filter values, shows success message for 2.5s then auto-closes
- Added "Salvar Busca" button in filter panel (below "Buscar Leads") — outline blue, Bookmark icon
- Added inline modal with: name input (required), email input (optional), cancel/save buttons, error/success states

**Frontend deploy**: `python deploy.py frontend` — Next.js build clean, 54 files uploaded via FTP, 0 errors.

## Verification Results

TypeScript: `npx tsc --noEmit` exits 0 — no errors.

Acceptance criteria:
- `grep "Salvar Busca" portal.tsx` → 2 matches (button label + modal title)
- `grep "api.post.*saved-searches" portal.tsx` → 1 match
- `grep "showSaveModal|saveSearch|saveName" portal.tsx` → 8 matches
- `grep "Bookmark" portal.tsx` → 2 matches (import + usage)
- `grep "saved-searches" Sidebar.tsx` → 2 matches (nav item + isActive)
- `grep "Bookmark" Sidebar.tsx` → 2 matches (import + usage)
- `grep "api.patch.*saved-searches|api.delete.*saved-searches|api.get.*saved-searches" saved-searches.tsx` → 3 matches
- saved-searches.tsx: 147 lines (> 80 minimum)
- Frontend build: /saved-searches and /portal in build output
- FTP deploy: 54 files, 0 errors

## Deviations from Plan

None — plan executed exactly as written.

## Commits

| Hash | Message |
|------|---------|
| f65cdb5 | feat(06-03): saved-searches.tsx page + Sidebar Buscas Salvas nav link |
| 16dfb49 | feat(06-03): Salvar Busca button + modal on portal.tsx + frontend deployed |

## Known Stubs

None — all API calls wire to real endpoints implemented in Plan 02.

## Self-Check: PASSED
