---
plan: 10-02
phase: 10-novas-fontes
status: complete
completed_at: 2026-03-27
---

## Summary

Improved Outscraper (limit 20→100, capped at 4 jobs) and expanded search engine queries from 1 to 5 distinct templates per niche+city.

## What Was Built

**Outscraper improvements (SRC-03)**
- `limit=20` → `limit=100` in `process_outscraper_massive()` `_massive_retry` call
- `niches[:3]` → `niches[:2]` in orchestrator to stay within 500 records/month free tier (max 4 jobs: 2 niches × 2 cities)
- Net effect: 5× more results per query, same or lower total job count

**5-template query expansion (SRC-04)**
- `SEARCH_QUERY_TEMPLATES` constant: 5 distinct queries (contato, email, whatsapp, site:*.com.br, OR neighboring city)
- `ES_NEIGHBORING_CITIES` dict: maps ES cities to their neighbors for the 5th template
- `search_engines` orchestrator block refactored: niches[:2] × cities[:1] × 5 templates = 10 jobs max
- Each job gets a `query_override` key with the pre-built query string
- `process_search_job`: reads `query_override` when present, falls back to original logic otherwise
- `total_jobs` counter updated to reflect 5× multiplier

## Key Files

- `app/backend/app.py` — constants + orchestrator block + process_search_job update

## Self-Check: PASSED

- `grep "SEARCH_QUERY_TEMPLATES" app/backend/app.py` → 4 occurrences (definition + 2 usages + counter)
- `grep "query_override" app/backend/app.py` → 3 occurrences (set in orchestrator, read in process_search_job)
- `grep "limit=100" app/backend/app.py` → line 12570 in outscraper _massive_retry ✓
