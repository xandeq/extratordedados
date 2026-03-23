---
phase: 02-qualidade-de-leads
verified: 2026-03-23T00:00:00Z
status: passed
score: 8/8 must-haves verified
re_verification: null
gaps: []
human_verification:
  - test: "Open https://extratordedados.com.br/leads and check grade badges are visible"
    expected: "Each lead row shows a colored A/B/C/D/F badge and a freshness dot in the Qualidade column"
    why_human: "Static export — cannot verify Tailwind CSS rendering or actual DB values programmatically"
  - test: "Open the quality filter dropdown"
    expected: "Options are A, B, C, D, F — no basico/medio/premium options visible"
    why_human: "HTML options exist in code but rendering and removal of old options requires visual confirmation"
  - test: "Click a lead to open the drawer, look for 'Verificar Email' button"
    expected: "Button is present; clicking with no ZeroBounce key shows toast 'ZeroBounce API key not configured'; with key shows ZeroBounce status"
    why_human: "LeadDrawer is a separate component — integration through onVerifyEmail prop needs end-to-end check"
  - test: "Filter leads by grade 'A'"
    expected: "Table updates to show only A-grade leads"
    why_human: "Requires live DB with quality_grade column populated to verify filter behavior"
---

# Phase 2: Qualidade de Leads — Verification Report

**Phase Goal:** Cada lead tem score A-F auditável. Emails inválidos não entram na base. Telefones normalizados.
**Verified:** 2026-03-23
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | New columns (captured_at, last_verified_at, freshness_score, quality_grade) exist on leads table | VERIFIED | app.py lines 1684-1687: new_columns list in init_db() has all 4 columns |
| 2 | Old UNIQUE(batch_id, email) constraint gone; global partial index idx_leads_email_global exists | VERIFIED | Zero matches for `ON CONFLICT (batch_id, email)` in app.py; idx_leads_email_global at line 1758 |
| 3 | Packages email-validator, disposable-email-domains, phonenumbers in requirements.txt | VERIFIED | requirements.txt lines 19-21 have all three packages pinned |
| 4 | validate_email_free() rejects disposable and no-MX emails | VERIFIED | Defined at line 1117; uses _DISPOSABLE_BLOCKLIST (line 1151) and has_valid_mx() call present |
| 5 | normalize_phone_br() returns E.164 + type + whatsapp_id for mobile numbers | VERIFIED | Defined at line 1174; whatsapp_id built at lines 1221, 1229 (`@c.us` suffix) |
| 6 | compute_lead_quality_score() stores grade on every insert via save_lead_to_db() | VERIFIED | save_lead_to_db() at line 1332; only one INSERT INTO leads in file (line 1352, inside save_lead_to_db); 12 total references (1 def + 11 call sites) |
| 7 | POST /api/leads/validate-batch returns 401 without auth, 200 with auth | VERIFIED | validate_batch_endpoint() at lines 7252-7331; auth check at top; compute_lead_quality_score called at line 7309 |
| 8 | Frontend shows GradeBadge + FreshnessIndicator + A-F filter + Verificar Email button | VERIFIED | GradeBadge and FreshnessIndicator defined in both leads.tsx (lines 103, 120) and LeadDrawer.tsx (lines 11, 28); A-F options at leads.tsx lines 922-926; handleVerifyEmail at line 592 wired to LeadDrawer via onVerifyEmail prop |

**Score:** 8/8 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/backend/requirements.txt` | email-validator, disposable-email-domains, phonenumbers pinned | VERIFIED | Lines 19-21, all three present |
| `app/backend/app.py` | validate_email_free(), normalize_phone_br(), compute_lead_quality_score(), save_lead_to_db(), validate_batch_endpoint(), validate_zerobounce(), verify_lead_email() | VERIFIED | All 7 functions/endpoints present; lines 1117, 1174, 1240, 1332, 7252, 7333, 7367 |
| `tests/test_lead_quality.py` | 14 tests (8 live smoke + 6 unit stubs), no Wave-0 skips | VERIFIED | All 14 def test_ functions present; Wave 0 skip messages absent; unit stubs use ImportError guard pattern |
| `app/frontend/pages/leads.tsx` | GradeBadge, FreshnessIndicator, quality_grade interface field, A-F filter options | VERIFIED | All present; quality_grade in Lead interface at line 51; A-F options lines 922-926 |
| `app/frontend/components/LeadDrawer.tsx` | GradeBadge, FreshnessIndicator, Verificar Email button, onVerifyEmail prop | VERIFIED | GradeBadge at line 153, FreshnessIndicator at line 154, button text at line 331, prop at line 88 |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| app.py init_db() | leads table new columns | ALTER TABLE ADD COLUMN IF NOT EXISTS | WIRED | Lines 1684-1687: captured_at, last_verified_at, freshness_score, quality_grade |
| app.py init_db() | leads table global index | CREATE UNIQUE INDEX IF NOT EXISTS | WIRED | Line 1758: idx_leads_email_global with partial WHERE clause |
| validate_email_free() | has_valid_mx() + _MX_CACHE | reuses existing cache dict | WIRED | _DISPOSABLE_BLOCKLIST usage at line 1151; has_valid_mx() call in validate_email_free body |
| compute_lead_quality_score() | leads table quality_grade + lead_score | called in save_lead_to_db() | WIRED | save_lead_to_db() calls compute_lead_quality_score() at line 1341; quality_grade written in INSERT |
| save_lead_to_db() | all former ON CONFLICT (batch_id, email) INSERT sites | each former INSERT site calls save_lead_to_db() | WIRED | Only 1 INSERT INTO leads in entire file (line 1352, inside save_lead_to_db); 12 total occurrences (1 def + 11 call sites) |
| POST /api/leads/validate-batch | compute_lead_quality_score() loop | SELECT leads → recompute → UPDATE | WIRED | Line 7309: qs = compute_lead_quality_score(lead_data) inside batch loop |
| validate_zerobounce() | AWS SM tools/zerobounce | resolve_secret_value('ZEROBOUNCE_API_KEY', secret_ids=['tools/zerobounce']) | WIRED | Line 7339-7343: secret fetch; secret confirmed present in AWS SM with non-empty key |
| leads.tsx Verificar Email button | POST /api/leads/<id>/verify-email | handleVerifyEmail → onVerifyEmail prop → LeadDrawer | WIRED | leads.tsx line 594: api.post('/api/leads/${leadId}/verify-email'); line 1272: onVerifyEmail={handleVerifyEmail} passed to LeadDrawer; LeadDrawer line 326-331: button renders when prop provided |
| GET /api/leads quality filter | l.quality_grade = %s | ?quality=A/B/C/D/F routed to quality_grade column | WIRED | Backend line 6315 reads `quality` param; line 6355 routes A/B/C/D/F to `AND l.quality_grade = %s`; frontend sends `params.append('quality', qualityFilter)` — param name matches |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| validate-email-free | 02-01, 02-02 | validate_email_free() with 3-layer validation (syntax + MX + disposable) | SATISFIED | app.py line 1117; check_deliverability=False at line 1135; _DISPOSABLE_BLOCKLIST at line 1151 |
| normalize-phone-br | 02-01, 02-02 | normalize_phone_br() → E.164 + DDD valid + mobile/landline + WhatsApp ID | SATISFIED | app.py line 1174; whatsapp_id built for mobile type at lines 1221, 1229 |
| quality-score-6dim | 02-01, 02-02 | 6-dimension score A/B/C/D/F + numeric 0-100 | SATISFIED | app.py line 1240; all 6 dimensions (email, phone, completeness, freshness, cnpj, source) present |
| db-migrations | 02-01 | 4 new columns (captured_at, last_verified_at, freshness_score, quality_grade) + backfill | SATISFIED | app.py lines 1684-1699; backfill UPDATE at line 1699 |
| dedup-cross-batch | 02-01 | DROP UNIQUE(batch_id, email); CREATE partial global index; delete duplicates | SATISFIED | Zero ON CONFLICT (batch_id, email) remaining; idx_leads_email_global at line 1758; dedup DELETE block in init_db() |
| validate-batch-endpoint | 02-01, 02-02 | POST /api/leads/validate-batch recomputes scores for leads in batch | SATISFIED | validate_batch_endpoint() at line 7252; 401 without auth; loops and calls compute_lead_quality_score per lead |
| zerobounce-button | 02-03 | validate_zerobounce() + POST /api/leads/<id>/verify-email; 503 if key missing | SATISFIED | validate_zerobounce() at line 7333; graceful 'zerobounce_key_missing' error; verify_lead_email() at line 7367; secret present in AWS SM |
| frontend-badges | 02-03 | GradeBadge + FreshnessIndicator + A-F filter + Verificar Email button | SATISFIED | Both components defined in leads.tsx (lines 103, 120) and LeadDrawer.tsx (lines 11, 28); A-F options present; button wired via onVerifyEmail prop |

All 8 requirement IDs from all 3 plan frontmatter files are accounted for. No orphaned requirements found in REQUIREMENTS.md Phase 2 section.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| app/backend/app.py | 7344 | `api_key == 'PLACEHOLDER_REPLACE_WITH_ACTUAL_KEY'` guard | Info | Defensive check for placeholder value — correct behavior, not a stub. ZeroBounce key in AWS SM is confirmed populated. |

No blocker anti-patterns. The placeholder guard is correct defensive programming, not a stub — the actual secret contains a real key.

---

## Human Verification Required

### 1. Grade badges visible in leads table

**Test:** Open https://extratordedados.com.br/leads while logged in
**Expected:** Each lead row shows a colored badge (A-F grade) and freshness dot in the Qualidade column; leads with no quality_grade yet show "?" badge
**Why human:** DB column quality_grade is newly added — existing leads need validate-batch to be run first to populate grades; visual confirmation of badge colors required

### 2. Quality filter dropdown shows A-F only

**Test:** Open the quality filter dropdown on /leads
**Expected:** Exactly 5 grade options (A, B, C, D, F) — no basico/medio/premium options
**Why human:** Old options removed in code (grep returns 0 matches) but visual confirmation ensures no CSS hidden elements or duplicate dropdowns

### 3. Verificar Email button in lead drawer works end-to-end

**Test:** Open any lead drawer and click "Verificar Email"
**Expected:** If ZeroBounce key is configured (it is), toast shows ZeroBounce status (valid/invalid/catch-all); last_verified_at updates in DB
**Why human:** Requires live ZeroBounce API call — cannot verify network round-trip programmatically; also confirms button renders in the specific drawer UI layout

### 4. Filtering by grade returns correct results

**Test:** Select grade "A" from quality filter — verify table shows only A-grade leads
**Expected:** Only leads with quality_grade='A' appear; count decreases from total
**Why human:** Requires live DB with populated quality_grade values — need to run validate-batch first if grades not yet computed

---

## Gaps Summary

No gaps found. All 8 phase requirements are implemented, substantive, and wired. The phase goal is achieved:

- **Emails inválidos nao entram na base**: `validate_email_free()` blocks disposable domains and no-MX records. The single `save_lead_to_db()` helper is the only INSERT path — all 11 former direct-INSERT sites now flow through it, which calls `compute_lead_quality_score()` before insert.
- **Cada lead tem score A-F auditavel**: `compute_lead_quality_score()` scores 6 dimensions and writes `quality_grade` (A-F) on every insert and every sanitize run. `validate-batch` endpoint allows retroactive re-scoring.
- **Telefones normalizados**: `normalize_phone_br()` normalizes to E.164 with WhatsApp ID. It is called in `save_lead_to_db()` indirectly (via score computation) and directly in the sanitize path (line 7541).

Human verification items are for visual/UX confirmation, not correctness gaps.

---

_Verified: 2026-03-23_
_Verifier: Claude (gsd-verifier)_
