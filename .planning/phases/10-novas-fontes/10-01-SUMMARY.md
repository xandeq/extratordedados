---
plan: 10-01
phase: 10-novas-fontes
status: complete
completed_at: 2026-03-27
---

## Summary

Implemented Apple Maps as Thread 17 in the massive search orchestrator and added the `GET /api/admin/source-stats` admin endpoint.

## What Was Built

**process_apple_maps_massive() — Thread 17**
- Playwright-based scraper that navigates Apple Maps for business listings by niche+city
- Handles selector timeouts gracefully (marks job as `paused`, continues to next)
- Extracts: company_name, phone, address per listing card (`.place-list-item`)
- Anti-blocking sleep: `random.uniform(10, 20)` between jobs
- Wired as Thread 17 in `/api/search/massive` orchestrator (niches[:2] × cities[:2] = max 4 jobs)
- `'apple_maps'` added to default methods list and return dict

**GET /api/admin/source-stats**
- Admin-only endpoint returning `[{source, count}]` for leads from last 30 days
- Uses `captured_at` column (added Phase 2), groups by source, orders by count DESC

**tests/test_sources.py**
- 8 smoke tests covering SRC-01 (apple_maps), SRC-02 (foursquare stub), SRC-03 (outscraper), SRC-04 (search engine templates), source-stats endpoint

## Key Files

- `app/backend/app.py` — process_apple_maps_massive() + Thread 17 wiring + source-stats endpoint
- `tests/test_sources.py` — 8 smoke tests

## Self-Check: PASSED

- `grep -n "process_apple_maps_massive" app/backend/app.py` → 2 lines (function def + thread start)
- `grep -n "source-stats" app/backend/app.py` → endpoint registered
- `'apple_maps'` in return dict methods block ✓
- tests/test_sources.py has 8 tests ✓
