---
phase: 3
slug: novas-fontes
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-23
---

# Phase 3 Validation — Novas Fontes

Nyquist rule: run a test command after each task. No watch-mode flags.

---

## Wave 0 — Test scaffolding (Plan 01, Task 0)

After creating the three test stub files:

```bash
python -m pytest tests/test_cnpj_enrichment.py tests/test_outscraper.py tests/test_prospeo.py -v
```

Expected: 10 tests collected, 10 skipped, 0 failures.
When this passes: set `wave_0_complete: true`.

---

## Plan 01 — DB Foundation

### After Task 1 (cnpj_rf migration in init_db)

Deploy backend and verify table exists on VPS:
```bash
python deploy.py backend
curl -s https://api.extratordedados.com.br/api/health
```
Expected: `{"status":"ok","db":"postgresql",...}`

### After Task 2 (enrich_from_rf_local + enrich_cnpj_with_fallback)

```bash
# Test fallback chain endpoint
curl -s -X POST https://api.extratordedados.com.br/api/leads/enrich-cnpj \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cnpj":"33000167000101"}'
```
Expected: 200 with JSON containing `razao_social`. VPS logs show `[cnpj_fallback] hit level`.

### After Task 3 (import script + docs)

```bash
python scripts/import/import_receita_federal.py --dry-run
```
Expected: exits 0, prints sample column data from first 1,000 rows. No DB required.

```bash
python -m pytest tests/test_cnpj_enrichment.py -v
```
Expected: tests unskipped and passing (requires live API + valid CNPJ).

---

## Plan 02 — Outscraper Integration

### After Task 1 (_get_outscraper_key + requirements)

```bash
grep "outscraper" app/backend/requirements.txt
grep -n "_get_outscraper_key" app/backend/app.py
```
Expected: both match.

### After Task 2 (process_outscraper_massive)

```bash
grep -n "def process_outscraper_massive" app/backend/app.py
```
Expected: function defined.

### After Task 3 (wire into massive search) — deploy and smoke test

```bash
python deploy.py backend
curl -s -X POST https://api.extratordedados.com.br/api/search/massive \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"niches":["Padaria"],"region":"grande_vitoria_es","methods":["outscraper_maps"]}' \
  | python -m json.tool
```
Expected: 200, response JSON contains `"outscraper_maps": <N>` (N >= 1) in job counts. No 500.

```bash
python -m pytest tests/test_outscraper.py -v
```
Expected: 3 tests pass (or skip if API key empty in AWS SM).

---

## Plan 03 — Prospeo + Minha Receita Guide

### After Task 1 (_get_prospeo_key + enrich_linkedin_prospeo)

```bash
grep -n "def enrich_linkedin_prospeo\|def _get_prospeo_key" app/backend/app.py
```
Expected: 2 matches.

### After Task 2 (endpoint + LinkedIn hook)

```bash
python deploy.py backend
curl -s -X POST https://api.extratordedados.com.br/api/leads/1/enrich-linkedin \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  | python -m json.tool
```
Expected: 400 (no linkedin URL on lead 1) or 503 (key not configured) — NOT 404 or 500.

### After Task 3 (Minha Receita docs)

```bash
grep -c "Minha Receita" docs/RECEITA_FEDERAL_IMPORT.md
```
Expected: >= 3.

```bash
python -m pytest tests/test_prospeo.py -v
```
Expected: 3 tests pass (or skip if key empty).

---

## Full Phase 3 Sign-off

All three plans complete when:

```bash
python -m pytest tests/test_cnpj_enrichment.py tests/test_outscraper.py tests/test_prospeo.py -v
```
Reports 0 failures (tests may still be skipped if external API keys are empty placeholders — that is acceptable).

```bash
curl -s https://api.extratordedados.com.br/api/health
```
Returns `{"status":"ok","db":"postgresql",...}`.

```bash
python scripts/import/import_receita_federal.py --dry-run
```
Exits 0.

When all checks pass, set `status: validated` in this file's frontmatter.
