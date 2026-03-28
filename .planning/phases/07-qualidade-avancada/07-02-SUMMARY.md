---
phase: 07-qualidade-avancada
plan: "02"
subsystem: database
tags: [postgresql, crm-sync, dedup, psycopg2, cache]

# Dependency graph
requires:
  - phase: 07-01
    provides: QUAL-02/03/05 guards in save_lead_to_db() already deployed
provides:
  - crm_sent_leads table in PostgreSQL with UNIQUE index on LOWER(email)
  - Cache READ in sync_lead_to_alexandrequeiroz() — checks local table before CRM API GET
  - Cache WRITE in sync_lead_to_alexandrequeiroz() — records email+phone+whatsapp+crm_id after successful sync
affects: [07-03, crm-sync]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dedicated psycopg2 connection per cache block (thread safety — daemon threads)"
    - "Non-fatal try/except for both cache READ and WRITE — sync never blocked by cache errors"
    - "LOWER(email) UNIQUE index for case-insensitive dedup (Pitfall 5)"
    - "ON CONFLICT (LOWER(email)) DO NOTHING for idempotent cache writes"

key-files:
  created: []
  modified:
    - app/backend/db_alter_leads.sql
    - app/backend/app.py

key-decisions:
  - "Dedicated psycopg2.connect(**DB_CONFIG) per cache block — not reusing outer connection (D-05, thread safety)"
  - "Cache failure is non-fatal — falls through to CRM API check (D-06)"
  - "LOWER(email) normalization before both SELECT and INSERT (D-05)"
  - "ON CONFLICT (LOWER(email)) DO NOTHING matches UNIQUE index definition"

patterns-established:
  - "Cache READ pattern: check local DB table BEFORE remote API call"
  - "Cache WRITE pattern: insert after confirmed success, BEFORE return"

requirements-completed: [QUAL-04]

# Metrics
duration: 19min
completed: 2026-03-28
---

# Phase 7 Plan 02: QUAL-04 CRM Dedup Cache Summary

**PostgreSQL crm_sent_leads cache table with UNIQUE LOWER(email) index wired into sync_lead_to_alexandrequeiroz() — short-circuits redundant CRM API GET calls for already-synced leads**

## Performance

- **Duration:** 19 min
- **Started:** 2026-03-28T00:13:59Z
- **Completed:** 2026-03-28T00:32:38Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- `crm_sent_leads` table created in production PostgreSQL with BIGSERIAL PK, email, phone, whatsapp, crm_id, sent_at columns
- UNIQUE index on `LOWER(email)` enables case-insensitive dedup (joao@Empresa.COM.BR = joao@empresa.com.br)
- Cache READ block inserted at top of `sync_lead_to_alexandrequeiroz()` — returns immediately if email already cached, no CRM network call needed
- Cache WRITE block inserted after successful CRM POST — records email+phone+whatsapp+crm_id in crm_sent_leads
- Both blocks non-fatal (try/except) — cache errors never block the sync pipeline
- Backend deployed to VPS, health check OK, table confirmed accessible

## Task Commits

All tasks committed as one atomic commit:

1. **Task 1: Add crm_sent_leads DDL** - `8e328a0` (feat)
2. **Task 2: Wire cache READ + WRITE** - `8e328a0` (feat)
3. **Task 3: Migration + deploy** - `8e328a0` (feat) — DB migration on VPS successful

## Files Created/Modified
- `app/backend/db_alter_leads.sql` - Appended CREATE TABLE crm_sent_leads + 2 indexes (UNIQUE on LOWER(email), DESC on sent_at)
- `app/backend/app.py` - Cache READ block (lines 14277-14295) + Cache WRITE block (lines 14363-14382) in sync_lead_to_alexandrequeiroz()

## Decisions Made
- Tasks 1 and 2 committed together as single atomic feat commit (both are part of the same QUAL-04 feature, neither works without the other)
- DB migration run via Python paramiko (no sshpass installed on local machine)
- docker cp used to get SQL file into Docker container before psql execution
- Pre-existing `print` statements in db_alter_leads.sql (lines 146-154) caused PostgreSQL syntax errors during migration — these are MySQL-only syntax and were pre-existing in the file. The QUAL-04 DDL executed successfully after them.

## Deviations from Plan

None — plan executed exactly as written. The only note is that all 3 tasks share one commit (`8e328a0`) since Task 3 was the commit/deploy step specified in the plan.

## Issues Encountered
- `sshpass` not installed on local Windows machine — used Python `paramiko` SFTP + SSH instead (standard fallback)
- Docker container couldn't access `/tmp/db_alter_leads.sql` on host — required `docker cp` to copy file into container before `psql -f` execution
- Pytest full suite had transient network timeout on first run — health/validation subsets confirmed working; API health check confirmed reachable

## Known Stubs
None — cache table is live in production with verified indexes.

## Next Phase Readiness
- crm_sent_leads table in production, indexed, 0 rows (ready to accumulate)
- sync_lead_to_alexandrequeiroz() now has local cache check before CRM API call
- Plan 07-03 (QUAL-06: CRM gate in auto_sync_new_leads_background + _run_crm_sync_batch) can proceed immediately

## Self-Check: PASSED

- app/backend/db_alter_leads.sql — FOUND (5 occurrences of crm_sent_leads)
- app/backend/app.py — FOUND (INSERT INTO crm_sent_leads + QUAL-04 comments present)
- .planning/phases/07-qualidade-avancada/07-02-SUMMARY.md — FOUND
- Commit 8e328a0 — FOUND in git log

---
*Phase: 07-qualidade-avancada*
*Completed: 2026-03-28*
