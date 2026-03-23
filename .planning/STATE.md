# STATE.md — Project Memory

> Updated: 2026-03-22

## Current Status

- **Active milestone**: Milestone 1 — Pipeline Autônomo + Qualidade + Fontes
- **Active phase**: Phase 1 — Pipeline 100% Automático
- **Current Plan**: 3 of N (Plan 02 complete)
- **Last completed**: Phase 1, Plan 02 — pipeline health endpoint, Brevo email report, healthcheck ping

## Completed Work

| Date | What |
|------|------|
| 2026-03-22 | Project reorganized: app/, scripts/, docs/, data/, .planning/ |
| 2026-03-22 | PROJECT.md, REQUIREMENTS.md, ROADMAP.md created |
| 2026-03-22 | 4 research reports created in .planning/research/ |
| 2026-03-22 | Phase 1 Plan 01: pipeline_config table, get_pipeline_config(), GET/PUT /api/admin/pipeline-config endpoints |
| 2026-03-23 | Phase 1 Plan 02: GET /api/admin/pipeline/health endpoint, Brevo email report, healthchecks.io ping, hooked into run_daily_pipeline() |

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

## Performance Metrics

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 01 | 01 | ~15 min | 2/2 | 2 |
| 01 | 02 | ~15 min | 2/2 | 2 |

## Last Session

- **Stopped at**: Completed fase1-02-PLAN.md
- **Timestamp**: 2026-03-23
