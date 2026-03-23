---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-23T11:10:00.000Z"
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 9
  completed_plans: 7
---

# STATE.md — Project Memory

> Updated: 2026-03-22

## Current Status

- **Active milestone**: Milestone 1 — Pipeline Autônomo + Qualidade + Fontes
- **Active phase**: Phase 3 — Novas Fontes (IN PROGRESS)
- **Current Plan**: 1 of 3 complete
- **Last completed**: Phase 3 Plan 01 — cnpj_rf table, enrich_from_rf_local(), enrich_cnpj_with_fallback(), import_receita_federal.py, RECEITA_FEDERAL_IMPORT.md

## Completed Work

| Date | What |
|------|------|
| 2026-03-22 | Project reorganized: app/, scripts/, docs/, data/, .planning/ |
| 2026-03-22 | PROJECT.md, REQUIREMENTS.md, ROADMAP.md created |
| 2026-03-22 | 4 research reports created in .planning/research/ |
| 2026-03-22 | Phase 1 Plan 01: pipeline_config table, get_pipeline_config(), GET/PUT /api/admin/pipeline-config endpoints |
| 2026-03-23 | Phase 1 Plan 02: GET /api/admin/pipeline/health endpoint, Brevo email report, healthchecks.io ping, hooked into run_daily_pipeline() |
| 2026-03-23 | Phase 1 Plan 03: /admin/pipeline-config editor page (niche toggles, region, schedule, notifications) + pipeline health card + 30-day history on admin/index.tsx |
| 2026-03-23 | Phase 2 Plan 01: DB foundation — 4 quality columns (captured_at, quality_grade, etc.), global unique index, 157 dedup rows removed, Wave 0 test scaffold (14 tests), Phase 2 stub endpoints |
| 2026-03-23 | Phase 2 Plan 02: Core quality functions — validate_email_free, normalize_phone_br, compute_lead_quality_score, save_lead_to_db; all 10 extraction INSERT paths refactored; validate-batch endpoint; quality_grade filter; 14/14 tests passing |
| 2026-03-23 | Phase 2 Plan 03: validate_zerobounce() + POST /api/leads/<id>/verify-email; GradeBadge + FreshnessIndicator; A-F quality filter; Verificar Email button; tools/zerobounce in AWS SM |
| 2026-03-23 | Phase 3 Plan 01: cnpj_rf table (20 cols, 2 partial indexes), enrich_from_rf_local() (3s SQL timeout), enrich_cnpj_with_fallback() (5-level chain), import_receita_federal.py (nohup-safe, --dry-run), RECEITA_FEDERAL_IMPORT.md runbook. 10 test stubs (10 skipped). Deployed to VPS. |

## Research Available

| File | Topic |
|------|-------|
| `.planning/research/lead-sources.md` | APIs BR, Receita Federal dataset, Outscraper, Prospeo |
| `.planning/research/pipeline-automation.md` | APScheduler patterns, Brevo email, healthchecks.io |
| `.planning/research/saas-portal.md` | Credit-per-reveal, SELECT FOR UPDATE, niche request queue |
| `.planning/research/lead-quality.md` | email-validator, phonenumbers, 6-dimension score |

## Key Decisions Made

| Decision | Rationale |
|----------|-----------|
| Brevo email for reports (not WhatsApp now) | Zero setup, key already in AWS SM |
| Credit-per-reveal model | Industry standard (Apollo, Hunter, Lusha) |
| SELECT FOR UPDATE for credits | Prevents race condition on concurrent reveals |
| Receita Federal local import | Zero cost, 60M+ companies, no rate limits |
| APScheduler 3.x (keep, don't upgrade) | 4.x is pre-release/not production-ready |
| pipeline_config table (not hardcoded) | Enables admin UI config without code changes |
| Reveal gate before export in roadmap | You reveal before you bulk-export |
| Config values stored as JSON strings | Lists serialize cleanly, parsed with json.loads() |
| get_pipeline_config() never raises | Falls back to module constants on any DB error — pipeline never blocked |
| reschedule_job only on hour/minute change | Region/niches take effect on next trigger without APScheduler restart |
| pipeline_start as absolute first line of run_daily_pipeline | Guarantees it is always bound, even on early-exception paths |
| Notification helpers inserted before run_daily_pipeline in code | Logical grouping near pipeline code; helpers are pipeline-specific |
| Failure report call uses locals().get() for optional counters | Defensive: counters may not be assigned if exception fires before step 4/5/6 |
| PipelineHealth fetch uses .catch(() => null) — safe defaults | Admin index never fails to load if pipeline endpoint is down |
| getStatusBadge() extracted as module-level function (not inline) | Called in two places: status row and history table rows |
| History table sliced to 10 rows | daily-job/status returns all-time history; 10 rows is readable without pagination |
| ADD COLUMN IF NOT EXISTS in init_db ALTER TABLE loop | Avoids silent rollback when DuplicateColumn is thrown inside multi-column transaction |
| Phase 2 stub endpoints in Wave 0 | auth-gate tests must pass immediately; stubs return 401 unauth / 501 auth until Wave 2 |
| validate_email_free uses check_deliverability=False | Avoid per-call DNS in batch — MX check delegates to has_valid_mx() cache |
| save_lead_to_db is canonical INSERT helper | quality_grade written on every lead INSERT regardless of extraction pipeline |
| quality filter supports both A/B/C/D/F and legacy tiers | Backward compat with existing frontend quality dropdown |
| ZeroBounce key stored as placeholder in AWS SM | Operator must update tools/zerobounce with real key — endpoint returns 503 until then |
| Verificar Email logic in leads.tsx via onVerifyEmail callback prop | Keeps LeadDrawer stateless, centralized in page component |
| quality filter param remains 'quality' (not 'quality_grade') | Backend handles both A-F grades and legacy basico/medio/premium tiers |
| enrich_from_rf_local uses threading timeout (not signal-based) | Windows/Linux compat; signal.alarm not available on Windows |
| Level 2 (Minha Receita) silently passes on any exception | Connection refused is expected until Plan 03 deploys it on VPS |
| ONLY_ACTIVE=True default in import script | 60M total vs ~22M active — saves ~3x disk space; inactive CNPJs rarely needed |
| municipio_cod stored as integer (RF code), not city name | Would require separate municipios lookup table — city lookup deferred to future plan |

## Performance Metrics

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 01 | 01 | ~15 min | 2/2 | 2 |
| 01 | 02 | ~15 min | 2/2 | 2 |
| 01 | 03 | ~20 min | 2/2 | 2 |
| 02-qualidade-de-leads | 01 | ~16 min | 2/2 | 3 |
| 02-qualidade-de-leads | 02 | ~11 min | 2/2 | 2 |
| 02-qualidade-de-leads | 03 | ~7 min | 2/2 | 3 |
| 03-novas-fontes | 01 | ~6 min | 4/4 | 6 |

## Last Session

- **Stopped at**: Completed Phase 3 Plan 01 — DB Foundation (cnpj_rf table, fallback chain, import script). Next: Phase 3 Plan 02.
- **Timestamp**: 2026-03-23
