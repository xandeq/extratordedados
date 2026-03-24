---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-24T10:22:19.178Z"
progress:
  total_phases: 6
  completed_phases: 4
  total_plans: 15
  completed_plans: 13
---

# STATE.md — Project Memory

> Updated: 2026-03-23

## Current Status

- **Active milestone**: Milestone 2 — Portal de Clientes
- **Active phase**: Phase 5 (next) — Phase 4 COMPLETE, human verification approved
- **Milestone 2**: COMPLETE — Phase 4 all 3 plans done, human verification passed, portal UX live
- **Milestone 1**: COMPLETE (Phases 1-3 all done, 48/48 regression tests passing)
- **Last completed**: Phase 4 Plan 03 COMPLETE — client portal frontend verified live. Wave 0 test stubs activated (56 passed, 9 skipped). Phase 4 deliver: reveal-gate UX, credit ledger, masked search, RevealButton.

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
| 2026-03-23 | Phase 3 Plan 02: Outscraper Google Maps — tools/outscraper AWS SM secret, _get_outscraper_key(), outscraper in requirements.txt, process_outscraper_massive() Thread 16, outscraper_maps wired into POST /api/search/massive (default methods + jobs + thread + response dict). 2/3 tests pass (3rd skips until real API key set). Deployed to VPS. |
| 2026-03-23 | Phase 3 Plan 03: Prospeo LinkedIn enrichment — tools/prospeo AWS SM secret, _get_prospeo_key(), enrich_linkedin_prospeo(), POST /api/leads/<id>/enrich-linkedin (rate limit 30/hour), 75-credit cap in process_linkedin_massive(), Minha Receita docker-compose deploy guide in RECEITA_FEDERAL_IMPORT.md. 3/3 tests passing. Deployed to VPS. |
| 2026-03-24 | Phase 4 Plan 01: DB foundation — role column on users, credits_per_month on plan_limits, credit_ledger table (BIGSERIAL, SELECT FOR UPDATE), user_lead_reveals table (PK user_id+lead_id), require_role() decorator, deduct_credit() atomic helper, grant_monthly_credits() APScheduler job (day=1 00:05 with double-fire guard), mask_email(), mask_phone(), portal_lead_to_dict(). /api/me returns role. 12 Wave 0 test stubs. 53 passed, 17 skipped. |
| 2026-03-24 | Phase 4 Plan 02: Three client portal endpoints — POST /api/leads/reveal/<id> (atomic credit deduction, admin bypass, idempotent re-reveal, 402 on zero balance), GET /api/client/credits (balance + 20 event history), GET /api/leads/search (masked search over shared batches, 9 filter params, portal_lead_to_dict masking). 52 passed, 18 skipped. Deployed + VPS health check OK. |
| 2026-03-24 | Phase 4 Plan 03: Client portal frontend — /portal page (filter panel + masked results + RevealButton), useClientCredits hook, RevealButton (4 states), Sidebar Portal nav + CreditBalance widget, plans.tsx credits row. TypeScript clean, Next.js build OK, 56 passed, 9 skipped. Frontend deployed. Human verification APPROVED. |

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
| Outscraper ApiClient lazy-imported inside thread function | Avoids import-time cost for optional SDK at startup |
| tools/outscraper placeholder in AWS SM | Missing key treated as quota_exceeded (graceful degradation) — same pattern as serper/apify |
| Prospeo key stored as empty placeholder in AWS SM | Endpoint returns 503 until real key set — same pattern as ZeroBounce/Outscraper |
| with get_db() as conn in enrich_lead_linkedin | Consistent with all other Flask endpoints; get_db_connection() does not exist |
| prospeo_credits_used per-run counter (not persisted) | Simple and sufficient for Prospeo free tier 75-credit cap per run |
| deduct_credit takes open conn (not get_db()) | Caller controls transaction boundary — atomicity with user_lead_reveals INSERT in plan 02 |
| ROLE_HIERARCHY uses integers (admin=3, operator=2, client=1) | Single >= comparison handles future role additions |
| portal_lead_to_dict uses positional row indexing | Callers in plans 02/03 must SELECT columns in documented order |
| grant_monthly_credits double-fire guard uses 5-min window | Same pattern as daily pipeline guard — consistent across schedulers |
| reveal_lead() verifies lead exists before credit logic | Prevents credit deduction attempts for nonexistent leads — 404 check before any DB credit operations |
| client_search_leads() delegates masking to portal_lead_to_dict() | Single source of truth for reveal state — no inline masking in endpoint |
| quality_grade filter uses grade_order dict + = ANY(%s) | Cleaner than multiple OR conditions — allows A/B/C/D/F scale filtering at-or-better |
| alert() for reveal toast in portal.tsx | No custom toast system in Phase 4 scope; sufficient for MVP |
| RevealButton balance=null treated as hasCredits=true | Safe default for loading state and admin users without prop drilling null checks |
| useClientCredits called independently in Sidebar and portal.tsx | Acceptable parallel calls vs prop-drilling complexity through layout tree |
| No _has_minimum_role() in export endpoint | Function does not exist — consistent with reveal_lead and client_search_leads using verify_token + _is_admin_user only |
| Export uses single bulk credit deduction (not loop of deduct_credit()) | Bulk INSERT INTO credit_ledger with amount=-N is correct for export — deduct_credit() is for single-credit operations |
| Boolean filter conditions for has_email etc use inline SQL (no %s params) | Prevents psycopg2 parameter binding mismatch — inline NULL checks are equivalent |

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
| 03-novas-fontes | 02 | ~5 min | 3/3 | 3 |
| 03-novas-fontes | 03 | ~6 min | 3/3 | 3 |
| Phase 04-tier-cliente-reveal-gate-busca-avan-ada P01 | 12 | 2 tasks | 5 files |
| 04-tier-cliente-reveal-gate-busca-avan-ada | 01 | ~12 min | 2/2 | 5 |
| Phase 04-tier-cliente-reveal-gate-busca-avan-ada P02 | 4 | 2 tasks | 1 files |
| Phase 04-tier-cliente-reveal-gate-busca-avan-ada P03 | 10 | 2 tasks | 5 files |
| Phase 04-tier-cliente-reveal-gate-busca-avan-ada P03 | 15 | 3 tasks | 8 files |
| Phase 05-export-com-cotas-niche-request-queue P01 | 10 | 2 tasks | 3 files |

## Last Session

- **Stopped at**: Completed 05-export-com-cotas-niche-request-queue/05-01-PLAN.md — Wave 0 stubs (8 skipped), niche_requests/niche_request_votes tables, GET /api/client/leads/export with credit deduction. 19 passed, 18 skipped. Ready for Plan 02 (niche request queue endpoints).
- **Timestamp**: 2026-03-24
