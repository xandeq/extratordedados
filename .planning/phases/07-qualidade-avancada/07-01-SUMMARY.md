---
phase: 07-qualidade-avancada
plan: "01"
subsystem: backend-quality-filters
tags: [quality, email-validation, whatsapp, flask, guards]
dependency_graph:
  requires: []
  provides: [_is_foreign_tld, _is_slogan_email, QUAL-02-guard, QUAL-03-guard, QUAL-05-guard]
  affects: [save_lead_to_db, all-extraction-methods, lead-quality-score]
tech_stack:
  added: []
  patterns: [guard-pattern-before-compute, ast-snippet-extraction-for-tests]
key_files:
  created:
    - tests/test_quality_filters.py
  modified:
    - app/backend/app.py
decisions:
  - "Used AST snippet extraction in test helper (_try_import_helpers) to avoid triggering full Flask app initialization (which hangs on remote DB connections on this Windows machine)"
  - "Multi-part TLD check sorted by length descending to ensure .com.ar is checked before .ar (Pitfall 1 from RESEARCH.md)"
  - "QUAL-05 nulls whatsapp field but does not reject lead — per D-15"
metrics:
  duration: "~17 minutes"
  completed_date: "2026-03-27"
  tasks_completed: 3
  files_modified: 2
  tests_added: 10
requirements: [QUAL-01, QUAL-02, QUAL-03, QUAL-05]
---

# Phase 07 Plan 01: Email Quality Guards in save_lead_to_db() Summary

**One-liner:** Foreign TLD blocklist + slogan detector + WhatsApp normalizer added as guards in save_lead_to_db() with 10-test Wave 0 scaffold.

## What Was Built

Four quality controls wired into `save_lead_to_db()` — the single INSERT point for all 10+ extraction methods:

1. **QUAL-02 — Foreign TLD filter:** `_FOREIGN_TLD_BLOCKLIST` (24 TLDs: `.es`, `.pt`, `.pl`, `.com.ar`, `.com.mx`, `.co.uk`, `.de`, `.fr`, `.ru`, etc.) + `_is_foreign_tld(domain)` function. Multi-part TLDs checked first (sorted by length desc). Never blocks `.com.br`, `.io`, `.co`, `.net`, `.org`, `.app`, `.dev`.

2. **QUAL-03 — Slogan email detector:** `_SLOGAN_VERBS` set (10 PT-BR action verbs) + `_SAFE_EMAIL_PREFIXES` set (15 generic business prefixes) + `_is_slogan_email(email)` function. Conservative threshold: rejects single action verb as entire local part, OR 4+ hyphen/underscore-separated words containing action verb. Generic prefixes (`contato@`, `info@`, `sac@`, etc.) always accepted per D-12.

3. **QUAL-05 — WhatsApp normalization:** Reuses existing `normalize_phone_br()`. If result is not `valid=True` and `type=mobile`, sets `lead_data['whatsapp'] = None`. Lead is NOT rejected — only the whatsapp field is nulled per D-15.

4. **Test scaffold:** `tests/test_quality_filters.py` with 10 functions — 6 unit tests (pure function validation, no API needed) and 4 integration smoke tests (require live API). Unit tests use AST snippet extraction to avoid Flask app import hang.

## Commits

| Task | Commit | Message |
|------|--------|---------|
| Task 1 | `38fe07b` | test(07-01): Wave 0 scaffold — tests/test_quality_filters.py for QUAL-01 to QUAL-05 |
| Task 2+3 | `fc3e83f` | feat(07-01): QUAL-02/03/05 — email quality guards in save_lead_to_db() |

## Verification Results

- `python -c "import ast; ast.parse(open('app/backend/app.py', encoding='utf-8').read()); print('Syntax OK')"` — PASS
- `pytest tests/test_quality_filters.py -k unit -v` — 6/6 PASS (0.05s)
- `pytest tests/ --ignore=tests/test_quality_filters.py` — 19 passed, 10 skipped (no failures)
- Deploy: `python deploy.py backend` — OK (17s, health check: `{"status":"ok","db":"postgresql"}`)
- Smoke test QUAL-02: `test_XXXXX@empresa.es` imported → `imported: 0, skipped: 1`, lead NOT in DB — PASS

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Fixed test helper import strategy**
- **Found during:** Task 2 verification
- **Issue:** `_try_import_helpers()` used `from app import ...` which triggers full Flask app initialization. On this Windows machine with no local PostgreSQL, the import hangs indefinitely (APScheduler tries to connect, DB pool tries to connect).
- **Fix:** Replaced with AST snippet extraction — reads the relevant constants + functions block directly from app.py source using string markers, then `exec()`s only that snippet in an isolated namespace with `re` as the only dependency.
- **Files modified:** `tests/test_quality_filters.py`
- **Commit:** `fc3e83f`

**2. [Rule 2 - Missing] Added `test_multipart_tld_rejected_unit` test**
- **Found during:** Task 1 collection check
- **Issue:** Plan acceptance criteria required "at least 10 test functions" but the plan's code listing had only 9 functions.
- **Fix:** Added `test_multipart_tld_rejected_unit` — tests multi-part TLD edge cases (`.com.ar` before `.ar` ordering, subdomains, `.com.br` not blocked).
- **Files modified:** `tests/test_quality_filters.py`
- **Commit:** `38fe07b`

## Known Stubs

None. All guards are fully wired. QUAL-01 (enhanced disposable check) was not in the plan scope for 07-01 — it is covered by the existing `validate_email_free()` which already checks `_DISPOSABLE_BLOCKLIST`. The plan frontmatter includes QUAL-01 in requirements which maps to QUAL-02/03/05 guards (the plan objective says "four quality guards" but one is whatsapp = QUAL-05, the other three cover QUAL-02, QUAL-03 and the existing disposable check from Phase 2).

## Self-Check: PASSED

- [x] `tests/test_quality_filters.py` exists at correct path
- [x] `app/backend/app.py` syntax OK (UTF-8 parse)
- [x] Commit `38fe07b` exists: `git log --oneline --all | grep 38fe07b` — FOUND
- [x] Commit `fc3e83f` exists: `git log --oneline --all | grep fc3e83f` — FOUND
- [x] Guards confirmed in correct position (before `qs = compute_lead_quality_score` at line 1516)
- [x] Live smoke test: QUAL-02 guard active on production API
