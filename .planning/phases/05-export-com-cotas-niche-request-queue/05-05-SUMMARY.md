---
phase: 05-export-com-cotas-niche-request-queue
plan: "05"
subsystem: backend-deploy
tags: [deploy, bugfix, gap-closure]
dependency_graph:
  requires: ["05-04"]
  provides: ["live-phase5-endpoints"]
  affects: ["api.extratordedados.com.br"]
tech_stack:
  added: []
  patterns: ["deploy-script", "paramiko-sftp", "gunicorn-service"]
key_files:
  created: []
  modified:
    - app/backend/app.py
decisions:
  - "Auto-fixed NameError: @wraps(fn) was missing functools import — added 'import functools' at module level and changed @wraps to @functools.wraps in require_role()"
  - "Verified endpoints via both internal 172.17.0.1:8000 and public HTTPS — both return correct status codes"
metrics:
  duration: "~6 min"
  completed: "2026-03-24"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 1
---

# Phase 05 Plan 05: Deploy Backend to VPS — Summary

Backend deployed to VPS with auto-fix for `NameError: name 'wraps' is not defined` that prevented gunicorn from booting after the Phase 5 code was uploaded.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Deploy backend to VPS + verify Phase 5 endpoints live | ba1ce28 | app/backend/app.py |

## Acceptance Criteria — All Met

| Check | Result |
|-------|--------|
| `GET /api/health` returns `{"status":"ok","db":"postgresql"}` | PASS |
| `GET /api/client/leads/export` returns 401 (not 404) | PASS |
| `GET /api/admin/niche-requests` returns 401 (not 404) | PASS |
| `POST /api/client/niche-requests` returns 401 (not 404) | PASS |
| `python deploy.py backend` exited 0 | PASS (2 runs — first discovered bug, second succeeded) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] NameError: name 'wraps' is not defined in require_role decorator**

- **Found during:** Task 1 — first deploy attempt showed gunicorn crashing at startup
- **Issue:** The `require_role()` decorator at line ~2427 used `@wraps(fn)` but `wraps` was never imported at module scope. The `functools` module was only imported locally inside `_persist_thread_errors()` (line 446), not available at module level.
- **Fix:** Added `import functools` to the top-level stdlib import block and changed `@wraps(fn)` to `@functools.wraps(fn)` in `require_role`.
- **Files modified:** `app/backend/app.py` (2 lines changed)
- **Commit:** ba1ce28

## Known Stubs

None — this plan is a pure deployment/gap-closure plan. No frontend stubs added.

## Self-Check: PASSED

- `app/backend/app.py` modified — confirmed
- Commit ba1ce28 exists — confirmed via `git rev-parse --short HEAD`
- Health check via public HTTPS returns `{"db":"postgresql","status":"ok"}` — confirmed
- Phase 5 endpoints return 401 (not 404) — confirmed via both VPS-local and public HTTPS
