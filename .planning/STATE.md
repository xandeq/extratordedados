---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: — Lead Quality Engine
status: unknown
last_updated: "2026-03-26T00:34:18.921Z"
progress:
  total_phases: 10
  completed_phases: 6
  total_plans: 26
  completed_plans: 23
---

# STATE.md — Project Memory

> Updated: 2026-03-24

## Current Status

- **Active milestone**: Milestone v1.1 — Lead Quality Engine
- **Active phase**: Phase 8 — Catálogo de Nichos (COMPLETE — all 3 plans done)
- **Milestone v1.0**: COMPLETE (Phases 1-6 all done, 20/20 plans, all features live)
- **Last completed**: Phase 08 Plan 03 — /admin/niches UI + massive-search DB-loaded niches + Sidebar nav links + frontend deployed to HostGator

## Milestone v1.1 Scope

| ID | Requirement |
|----|-------------|
| QUAL-01 | Rejeitar emails inválidos/bounceáveis antes de inserir na base |
| QUAL-02 | Rejeitar TLDs estrangeiros (.es, .pt, .pl, .com.ar, etc.) |
| QUAL-03 | Rejeitar emails no estilo slogan/frase |
| QUAL-04 | Não re-inserir leads já existentes no CRM (dedup por email/telefone) |
| QUAL-05 | Validar formato + DD válido de WhatsApp antes de salvar |
| QUAL-06 | Enviar ao CRM apenas leads com email válido OR WhatsApp válido |
| SRC-01 | Integrar Apple Maps na busca massiva |
| SRC-02 | Pesquisar e integrar melhores APIs de leads disponíveis |
| SRC-03 | Melhorar Google Maps scraper (mais resultados, menos bloqueios) |
| SRC-04 | Melhorar busca Google com mais variações de query por nicho |
| NICHE-01 | Criar catálogo completo de nichos + subnichos no banco |
| NICHE-02 | Pipeline usa nichos do banco (não hardcoded) para rotação |
| NICHE-03 | Script/SQL para popular e atualizar catálogo facilmente |
| NICHE-04 | Botão "Selecionar todos / Desselecionar todos" na busca massiva |
| REG-01 | Todas as cidades do ES disponíveis no pipeline |
| REG-02 | Pipeline rotaciona progressivamente pelas cidades do ES |

## Phase Map — Milestone v1.1

| Phase | Name | Requirements | Plans | Status |
|-------|------|--------------|-------|--------|
| 7 | Qualidade de Leads Avançada | QUAL-01 to QUAL-06 | 3 | Not started |
| 8 | Catálogo de Nichos | NICHE-01 to NICHE-04 | 3 | COMPLETE (3/3) |
| 9 | Expansão Regional ES | REG-01, REG-02 | 3 | Not started |
| 10 | Novas Fontes de Extração | SRC-01 to SRC-04 | 3 | Not started |

## Completed Work (Milestone v1.0 History)

| Date | What |
|------|------|
| 2026-03-22 | Project reorganized: app/, scripts/, docs/, data/, .planning/ |
| 2026-03-22 | PROJECT.md, REQUIREMENTS.md, ROADMAP.md created |
| 2026-03-22 | Phase 1: pipeline_config table, nichos configuráveis, health endpoint, Brevo reports, admin UI |
| 2026-03-23 | Phase 2: email validation, quality score, dedup cross-batch, ZeroBounce integration |
| 2026-03-23 | Phase 3: Receita Federal local import, Outscraper Google Maps, Prospeo LinkedIn |
| 2026-03-24 | Phase 4: client tier + reveal gate + portal frontend + credit system |
| 2026-03-24 | Phase 5: export com cotas + niche request queue + admin approval UI |
| 2026-03-24 | Phase 6: saved searches + email notifications + frontend deployed |
| 2026-03-24 | Milestone v1.1 roadmap created (Phases 7-10, 12 plans) |
| 2026-03-26 | Phase 8 Plan 01: niches table + populate_niches.sql (156 rows, 170 in DB) + 4 CRUD endpoints deployed |
| 2026-03-26 | Phase 8 Plan 02: get_pipeline_config() reads from niches table (round-robin) + _mark_niches_used() helper + daily_job_run fallback fixed |
| 2026-03-26 | Phase 8 Plan 03: /admin/niches page (tabs + toggle + priority) + massive-search loads niches from DB + Sidebar nav links + frontend deployed |

## Research Available

| File | Topic |
|------|-------|
| `.planning/research/lead-sources.md` | APIs BR, Receita Federal dataset, Outscraper, Prospeo |
| `.planning/research/pipeline-automation.md` | APScheduler patterns, Brevo email, healthchecks.io |
| `.planning/research/saas-portal.md` | Credit-per-reveal, SELECT FOR UPDATE, niche request queue |
| `.planning/research/lead-quality.md` | email-validator, phonenumbers, 6-dimension score |

## Key Decisions Made (Milestone v1.0)

| Decision | Rationale |
|----------|-----------|
| Brevo email for reports | Zero setup, key already in AWS SM |
| Credit-per-reveal model | Industry standard (Apollo, Hunter, Lusha) |
| SELECT FOR UPDATE for credits | Prevents race condition on concurrent reveals |
| Receita Federal local import | Zero cost, 60M+ companies, no rate limits |
| APScheduler 3.x (keep) | 4.x is pre-release/not production-ready |
| pipeline_config table (not hardcoded) | Enables admin UI config without code changes |
| save_lead_to_db is canonical INSERT | quality_grade written on every INSERT |
| _build_portal_filter_query shared helper | Used by search + notification scheduler |
| bulk route before <int:niche_id> | Flask routing: 'bulk' would match as integer ID otherwise |
| niches.keywords TEXT[] column | Future fuzzy-matching for pipeline niche selection |
| get_pipeline_config() read-only, _mark_niches_used() separate | Health checks call get_pipeline_config() — must not advance rotation on every call |
| DAILY_JOB_NICHES constant preserved | Fallback when niches table is empty (prevents crash on cold start) |
| PREDEFINED_NICHES removed from massive-search.tsx | Single source of truth is niches DB table; massive-search fetches /api/niches?active=true |
| isActive() exact-match for /admin/niches + /admin/pipeline-config | Prevents false "Painel Admin" highlight when visiting sub-admin routes (startsWith pitfall) |
| 50-niche cap warning client-side only | UX guard in massive-search; backend enforces actual limit independently |

## Last Session

- **Stopped at**: Completed 08-03-PLAN.md — Phase 8 complete (all 3 plans done)
- **Next action**: `/gsd:execute-phase 07` (Phase 7: Lead Quality Engine — QUAL-01 to QUAL-06) or `/gsd:execute-phase 09` (Expansao Regional ES)
- **Timestamp**: 2026-03-26
