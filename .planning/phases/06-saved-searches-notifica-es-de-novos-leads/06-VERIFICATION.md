---
phase: 06-saved-searches-notifica-es-de-novos-leads
verified: 2026-03-24T00:00:00Z
status: human_needed
score: 10/10 must-haves verified
re_verification: null
gaps: []
human_verification:
  - test: "Visit https://extratordedados.com.br/portal as a client user"
    expected: "'Salvar Busca' button is visible in the filter panel area with a Bookmark icon"
    why_human: "Static export deployed via FTP — cannot verify rendered page programmatically"
  - test: "Click 'Salvar Busca' on the portal, fill in name + email, click Salvar"
    expected: "Modal appears, POST call succeeds, success message shows for ~2.5s then modal closes"
    why_human: "Requires a client-role session token; CRUD endpoint behaviour in browser context"
  - test: "Visit https://extratordedados.com.br/saved-searches as a client user"
    expected: "Sidebar shows 'Buscas Salvas' link; page loads the saved search just created"
    why_human: "UI rendering and navigation require a live browser session"
  - test: "Toggle the notification switch on the saved search"
    expected: "Switch state changes immediately (optimistic update); PATCH call returns 200"
    why_human: "Real-time state update and toggle animation require browser interaction"
  - test: "Click the trash button on a saved search"
    expected: "Confirmation dialog appears; on confirm, row disappears; DELETE returns 200"
    why_human: "confirm() dialog and DOM removal require browser"
---

# Phase 6: Saved Searches + Notificações de Novos Leads — Verification Report

**Phase Goal:** Clients can save searches and receive daily email notifications when new matching leads arrive.
**Verified:** 2026-03-24
**Status:** human_needed — all automated checks passed, 5 visual/interactive items need human confirmation
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `saved_searches` table exists in PostgreSQL with all required columns | VERIFIED | `CREATE TABLE IF NOT EXISTS saved_searches` at app.py line 2351 with id, user_id, name, filters JSONB, notify_enabled, notify_email, last_notified_at, created_at, UNIQUE(user_id, name) |
| 2 | POST /api/client/saved-searches creates a row and returns 201 | VERIFIED | `create_saved_search()` at line 16216 with ON CONFLICT upsert and RETURNING clause |
| 3 | GET /api/client/saved-searches returns only the authenticated user's rows | VERIFIED | `list_saved_searches()` at line 16262, WHERE user_id = %s |
| 4 | DELETE /api/client/saved-searches/\<id\> enforces owner check | VERIFIED | `delete_saved_search()` at line 16297, `WHERE id = %s AND user_id = %s RETURNING id` |
| 5 | PATCH /api/client/saved-searches/\<id\> toggles notify_enabled | VERIFIED | `update_saved_search()` at line 16324, dynamic SET clause with owner check |
| 6 | APScheduler job registered at 08:00 America/Sao_Paulo | VERIFIED | `CronTrigger(hour=8, minute=0, timezone=_tz)` at line 17514, id='saved_search_notifications' |
| 7 | Scheduler counts new leads per filter and sends email only when count > 0 | VERIFIED | `trigger_saved_search_notifications()` line 17317: calls `_build_portal_filter_query()`, counts via `SELECT COUNT(*)`, calls `send_notification_email()` only when `new_count > 0` |
| 8 | No duplicate emails: last_notified_at guard (23h) prevents re-sending | VERIFIED | Lines 17360–17368: `elapsed_hours < 23 → continue`; `last_notified_at` updated only on successful send (line 17397) |
| 9 | "Salvar Busca" button on /portal submits to POST /api/client/saved-searches | VERIFIED | portal.tsx line 289 (Bookmark icon + label), line 145 `api.post('/api/client/saved-searches', {...})` |
| 10 | /saved-searches page lists saved searches with toggle and delete | VERIFIED | saved-searches.tsx 147 lines; `api.patch` (line 45), `api.delete` (line 57), `api.get` (line 25); all wired to real endpoints |

**Score:** 10/10 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/backend/app.py` | saved_searches table, 4 REST endpoints, scheduler job, helpers | VERIFIED | Table at line 2351; endpoints at 16216–16376; `_build_portal_filter_query` at 16505; `send_notification_email` at 14431; `trigger_saved_search_notifications` at 17317 |
| `tests/test_saved_searches.py` | 6 test functions — 1 auth guard passes, 5 CRUD/unit tests | VERIFIED | File exists, 124 lines; real assertions in all 5 (skip only when CLIENT_TEST_PASSWORD or DB_HOST absent from env) |
| `app/frontend/pages/saved-searches.tsx` | Saved searches list page, min 80 lines | VERIFIED | 147 lines; toggle calls PATCH, delete calls DELETE, mount calls GET |
| `app/frontend/pages/portal.tsx` | "Salvar Busca" button + modal | VERIFIED | showSaveModal state (line 78), saveSearch handler (line 145), button with Bookmark icon (line 289), modal (line 455–499) |
| `app/frontend/components/Sidebar.tsx` | "Buscas Salvas" nav link with Bookmark icon | VERIFIED | Bookmark in imports (line 21), clientNavItems entry at line 33, isActive list at line 193 |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `portal.tsx` SaveSearchModal submit | POST /api/client/saved-searches | `api.post('/api/client/saved-searches', {...})` | WIRED | portal.tsx line 145 — posts all current filters + name + notify_email |
| `saved-searches.tsx` toggle button | PATCH /api/client/saved-searches/\<id\> | `api.patch(\`/api/client/saved-searches/${ss.id}\`, {notify_enabled: !current})` | WIRED | saved-searches.tsx line 45 |
| `saved-searches.tsx` delete button | DELETE /api/client/saved-searches/\<id\> | `api.delete(\`/api/client/saved-searches/${id}\`)` | WIRED | saved-searches.tsx line 57 |
| `Sidebar.tsx` clientNavItems | /saved-searches route | `{ href: '/saved-searches', label: 'Buscas Salvas', icon: Bookmark }` | WIRED | Sidebar.tsx line 33 |
| `trigger_saved_search_notifications()` | `_build_portal_filter_query()` | Direct call with saved filters dict | WIRED | app.py line 17373 |
| `trigger_saved_search_notifications()` | `send_notification_email()` | Called when new_count > 0 | WIRED | app.py line 17392 |
| `_scheduler.add_job` | `trigger_saved_search_notifications` | CronTrigger(hour=8, minute=0, timezone=_tz) | WIRED | app.py lines 17513–17518 |
| `client_search_leads()` | `_build_portal_filter_query()` | Refactored — shared helper called at line 16586 | WIRED | app.py lines 16585–16597 |

---

## Requirements Coverage

REQUIREMENTS.md uses prose checkboxes (no P6-xxx IDs). Requirement IDs from PLAN frontmatter (P6-SAVED-SEARCHES, P6-NOTIFICATION, P6-FRONTEND) are internal planning labels. Cross-referencing against REQUIREMENTS.md prose items for Fase 6:

| Requirement (REQUIREMENTS.md, Fase 6) | Plan | Status | Evidence |
|---------------------------------------|------|--------|----------|
| Tabela `saved_searches` (user_id, name, filters JSONB, last_notified_at, notify_email) | 06-01 (P6-SAVED-SEARCHES) | SATISFIED | app.py line 2351 — all columns present including notify_enabled bonus column |
| `POST/GET/DELETE /api/client/saved-searches` | 06-01/02 (P6-SAVED-SEARCHES) | SATISFIED | 4 routes implemented (POST/GET/DELETE/PATCH) — PATCH is additive, not a deviation |
| Job APScheduler diário às 08:00 | 06-02 (P6-NOTIFICATION) | SATISFIED | CronTrigger(hour=8) registered at line 17514 |
| Email de notificação via Brevo: "X novos leads em..." | 06-02 (P6-NOTIFICATION) | SATISFIED | `send_notification_email()` calls Brevo v3 SMTP API with subject `[DIAX] {N} novos leads em '{search_name}'` |
| Máximo 1 email/dia por saved search | 06-02 (P6-NOTIFICATION) | SATISFIED | 23h guard at lines 17360–17368 + last_notified_at updated on success |
| Botão "Salvar Busca" na página de busca para clientes | 06-03 (P6-FRONTEND) | SATISFIED | portal.tsx line 289, modal at lines 455–499 |
| Página `/saved-searches` — listar, nomear, deletar, toggle notificação | 06-03 (P6-FRONTEND) | SATISFIED | saved-searches.tsx 147 lines; all CRUD actions wired |

**Orphaned requirements:** None. All REQUIREMENTS.md Fase 6 items are covered by plans 06-01, 06-02, 06-03.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tests/test_saved_searches.py` | 105, 116 | Tests skip when CLIENT_TEST_PASSWORD absent / DB_HOST not set | Info | Tests `test_saved_search_created`, `test_saved_search_list`, `test_saved_search_toggle`, `test_saved_search_delete`, `test_notification_email_format` will skip in local dev — this is intentional design; requires `test_client` user to be seeded in prod DB and CLIENT_TEST_PASSWORD in AWS SM for full coverage |
| `trigger_saved_search_notifications()` | 17361 | `import pytz as _pytz` inside loop body (per-row iteration) | Info | Non-blocking: Python caches module imports, so this does not cause repeated module loading; cosmetically unclean |
| `trigger_saved_search_notifications()` | 17384–17402 | Opens 2 separate DB connections per notified row (count_conn + upd_conn) | Warning | Functional but slightly wasteful for high-volume subscriptions; acceptable for current scale (few clients, few saved searches) |

No blockers found. No stubs in the user-visible code path. All rendered state is driven by real API data.

---

## Human Verification Required

### 1. "Salvar Busca" button visible on /portal

**Test:** Log in as a client user, visit https://extratordedados.com.br/portal
**Expected:** A button labeled "Salvar Busca" with a Bookmark icon is visible in or near the filter panel. Clicking it opens a modal asking for a name and optional email.
**Why human:** Static Next.js export deployed via FTP — cannot render React components or verify Tailwind CSS output programmatically.

### 2. Modal submits and shows success

**Test:** In the "Salvar Busca" modal, type a name (e.g., "Teste Fase 6"), enter an email, click "Salvar"
**Expected:** A green success message appears briefly, modal auto-closes after ~2.5s, no JavaScript console errors
**Why human:** Requires a browser session with a valid client Bearer token; Axios interceptor and state transitions cannot be verified statically.

### 3. Sidebar shows "Buscas Salvas" nav link

**Test:** While logged in as a client user, check the sidebar navigation
**Expected:** "Buscas Salvas" with a Bookmark icon appears in the client nav section; clicking it navigates to /saved-searches
**Why human:** Sidebar renders conditionally based on user role; requires live session.

### 4. /saved-searches page lists saved searches with working toggle

**Test:** Navigate to https://extratordedados.com.br/saved-searches after creating at least one saved search
**Expected:** The search created in step 2 appears; clicking the toggle switch flips its state without page reload; the filter summary (category · city · state) is displayed correctly
**Why human:** Real-time state update, CSS toggle animation, and API call response handling require browser.

### 5. Delete removes the saved search

**Test:** Click the trash icon on a saved search, confirm the dialog
**Expected:** The row disappears from the list immediately; a second attempt to delete the same item (if re-created) returns 404 from the API
**Why human:** Browser confirm() dialog and DOM mutation require human interaction.

---

## Gaps Summary

No gaps found. All 10 observable truths verified against the codebase. All 5 frontend artifacts exist with substantive content and are wired to real backend endpoints. The APScheduler job is registered and correctly calls the notification chain. The only pending items are human-only verifications of the deployed frontend behavior.

**Note on test coverage:** The 5 CRUD tests in `test_saved_searches.py` skip locally due to missing `CLIENT_TEST_PASSWORD` and `test_client` user seeding. This is a test infrastructure gap, not a feature gap — the endpoints themselves are implemented and verified by code inspection. Provisioning `test_client` user + password in AWS SM would activate all 5 tests against the live API.

---

_Verified: 2026-03-24_
_Verifier: Claude (gsd-verifier)_
