---
phase: 3
plan: 1
subsystem: backend
tags: [cnpj, enrichment, receita-federal, database, import]
dependency_graph:
  requires: [phase-2-lead-quality]
  provides: [cnpj-rf-table, enrich-from-rf-local, cnpj-fallback-chain, rf-import-script]
  affects: [POST /api/leads/enrich-cnpj]
tech_stack:
  added: []
  patterns: [5-level-fallback-chain, threading-timeout, on-conflict-do-nothing]
key_files:
  created:
    - tests/test_cnpj_enrichment.py
    - tests/test_outscraper.py
    - tests/test_prospeo.py
    - scripts/import/import_receita_federal.py
    - docs/RECEITA_FEDERAL_IMPORT.md
  modified:
    - app/backend/app.py
decisions:
  - enrich_from_rf_local uses threading timeout (not signal-based) for Windows/Linux compatibility
  - Level 2 (Minha Receita) silently passes on any exception — connection refused is expected until deployed
  - ONLY_ACTIVE=True default — imports only situacao=02 to save ~3x disk space
  - municipio_cod stored as integer from RF code; city name lookup deferred (requires municipios table)
metrics:
  duration: "~6 min"
  completed_date: "2026-03-23"
  tasks: 4/4
  files: 6
---

# Phase 3 Plan 1: DB Foundation — cnpj_rf table, import script, local enrichment, fallback chain

One-liner: PostgreSQL `cnpj_rf` table + 5-level CNPJ fallback chain (rf_local → minha_receita → brasilapi → receitaws → cnpj_ws) + standalone VPS import script for Receita Federal open data.

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 0 | Phase 3 Wave 0 test scaffold | 52bafbf | tests/test_cnpj_enrichment.py, test_outscraper.py, test_prospeo.py |
| 1 | cnpj_rf table migration in init_db() | f24d60a | app/backend/app.py |
| 2 | enrich_from_rf_local() + enrich_cnpj_with_fallback() + wire endpoint | c7b9158 | app/backend/app.py |
| 3 | Standalone import script + RF docs | a7200de | scripts/import/import_receita_federal.py, docs/RECEITA_FEDERAL_IMPORT.md |

---

## What Was Built

### cnpj_rf Table (Task 1)
- `CREATE TABLE IF NOT EXISTS cnpj_rf` with 20 columns — PRIMARY KEY on `cnpj CHAR(14)`
- Two partial indexes for active companies (`situacao = 2`): `idx_cnpj_rf_uf_municipio` and `idx_cnpj_rf_cnae`
- Migration block added to `init_db()` following Phase 1/2 pattern — idempotent, wrapped in try/except

### enrich_from_rf_local() (Task 2)
- Direct SQL lookup on `cnpj_rf` table using psycopg2
- Uses threading with 3s timeout (compatible with both Windows and Linux)
- Never raises — all exceptions caught and logged with `[rf_local]` prefix
- Returns normalized dict with same schema as `enrich_cnpj_brasilapi`: `razao_social`, `nome_fantasia`, `phone`, `state`, `cep`, `address`, `cnae_code`, `situacao`, `porte`, `email_rf`, `source='rf_local'`
- Situacao mapping: `{2: 'ativa', 3: 'suspensa', 4: 'inapta', 8: 'baixada'}`
- Returns `{}` when table empty (not an error — table starts empty)

### enrich_cnpj_with_fallback() (Task 2)
- 5-level fallback chain, returns on first success
- Level 1: `enrich_from_rf_local()` — SQL, no network
- Level 2: Minha Receita `http://localhost:3000/{cnpj_fmt}` — silently skips on any exception
- Level 3: `enrich_cnpj_brasilapi()` — existing function, 8s timeout
- Level 4: `receitaws.com.br/v1/cnpj/{cnpj}` — 3 req/min free, 8s timeout
- Level 5: `publica.cnpj.ws/cnpj/{cnpj}` — 8s timeout, parses nested JSON structure
- Logs level hit: `[cnpj_fallback] hit level N: {source}`
- Logs when all 5 exhausted
- `POST /api/leads/enrich-cnpj` now calls `enrich_cnpj_with_fallback()` instead of direct BrasilAPI

### import_receita_federal.py (Task 3)
- Standalone script (no Flask imports), runs on VPS
- Credentials from AWS SM `extratordedados/prod` (boto3, 10s timeout) → `.deploy.env` fallback
- Discovers latest month from RF mirror index page; hardcoded fallback to `2026-02`
- Discovers Estabelecimentos and Empresas shards from month index
- Disk check: aborts if < 30GB free
- Loads Empresas index first (razao_social, porte) then imports Estabelecimentos shards
- `BATCH_SIZE = 10_000` with executemany + `ON CONFLICT (cnpj) DO NOTHING`
- `ONLY_ACTIVE = True` — only situacao_cadastral='02' (active companies)
- Deletes each ZIP after parse to recover disk space
- Progress every 100k rows; elapsed time at end; `nohup`-safe (all stdout)
- `--dry-run`: downloads first shard, parses 1000 rows, prints 5 sample rows, no DB write
- `--help` exits 0 with usage

### docs/RECEITA_FEDERAL_IMPORT.md (Task 3)
- 8-section runbook: prerequisites, upload, dry-run, nohup full run, verification SQL, monthly update, Minha Receita placeholder, troubleshooting
- Covers encoding errors, disk full, SSH timeout recovery, column index mismatch, rate limiting

### Test Scaffold (Task 0)
- `test_cnpj_enrichment.py`: 4 stubs for CNPJ fallback chain smoke tests
- `test_outscraper.py`: 3 stubs for Outscraper massive search method
- `test_prospeo.py`: 3 stubs for Prospeo LinkedIn-to-email enrichment
- All 10 collected, all 10 skipped, 0 failures

---

## Deviations from Plan

None - plan executed exactly as written.

---

## Known Stubs

None that affect Plan 1's goal. The `enrich_from_rf_local()` returns `{}` correctly when the `cnpj_rf` table is empty (table exists, populated by the import script once operator runs it). This is expected behavior, not a stub.

---

## Self-Check: PASSED
