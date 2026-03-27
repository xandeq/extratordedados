# Phase 10: Novas Fontes de Extração - Research

**Researched:** 2026-03-27
**Domain:** Web scraping sources, API integrations, search engine query optimization, analytics visualization
**Confidence:** HIGH (code verified directly) / MEDIUM (Outscraper limit parameter) / LOW (Apple Maps scraping feasibility)

---

## Summary

Phase 10 adds volume to the lead pipeline through four improvements: a new Apple Maps Playwright scraper (SRC-01), a new BR leads API integration sourced from research (SRC-02), improvements to the existing Outscraper thread (SRC-03), and five query templates per niche in the search engine thread (SRC-04). A source-stats endpoint and admin bar chart complete the phase.

The codebase is in excellent shape for this work. The massive search orchestrator already runs 16 threads (Threads 1-16). Apple Maps becomes Thread 17. The `leads` table has a dedicated `source` column (VARCHAR, not JSONB) that is already populated consistently by every existing thread with string values like `'google_maps'`, `'search_engine'`, `'outscraper_maps'`, `'apify_maps'`, `'instagram'`, `'linkedin'`, `'local_business_data'`. GROUP BY source is therefore straightforward. `process_outscraper_massive()` currently uses `limit=20` and processes one query at a time — both are improvable. `process_search_job()` currently builds a single concatenated query string; no template array exists. Recharts 2.15.4 is already installed; the admin dashboard (`/admin/index.tsx`) has no chart yet and has room to add one after the existing "Pipeline Automático" card.

Apple Maps does not have an official business search API for scraping. The web URL `https://maps.apple.com/?q={query}&near={city}` works in browsers but the results page is heavily JavaScript-rendered. Foursquare Places API offers 10,000 free calls/month and returns business name, address, phone, website, and category — this is the strongest free-tier BR leads API candidate for SRC-02.

**Primary recommendation:** Use Foursquare Places API for SRC-02 (10k free/month, covers Brazil, returns structured data). For Apple Maps use `maps.apple.com/?q=` via Playwright with stealth mode. Outscraper supports `limit` up to 500 and batch queries via list input — both improvements are drop-in changes to the existing call. Five query templates for SRC-04 are defined in the roadmap and can be implemented as a list comprehension replacing the current single-query build.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SRC-01 | Apple Maps scraper — `process_apple_maps_massive()` via Playwright; integrar como Thread 17 no massive search | Apple Maps web URL pattern confirmed: `https://maps.apple.com/?q={query}&near={city}`. Playwright already used for Google Maps (Thread 3) — same pattern applies. New thread follows exact same structure as `process_google_maps_massive()`. |
| SRC-02 | Pesquisar e implementar melhor API de leads BR disponível no free tier | Foursquare Places API: 10,000 free calls/month, 50 QPS, covers Brazil, returns name/address/phone/website/category. Significantly better than Hunter.io (email-only) or Snov.io (50 free credits). |
| SRC-03 | Melhorar `process_outscraper_massive()` — retry, cursor pagination, max_results 20→100, batch queries | Current code: `limit=20`, single query per call. SDK supports `limit` up to 500 and list of queries in a single call. `skip` parameter exists for pagination. Retry logic (`_massive_retry`) already in place but needs backoff increase. |
| SRC-04 | Melhorar `process_search_job()` — 5 templates de query por nicho | Current code: single query = `" ".join([niche, city, state])`. Must replace with 5-template expansion per niche+city combination, each as a separate search_job row. |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| playwright | already installed | Apple Maps browser automation | Same lib used for Google Maps (Thread 3) and LinkedIn (Thread 6) — zero new dependency |
| outscraper | already installed | Google Maps API via Outscraper | Already in requirements.txt, Thread 16 uses it |
| requests | already installed | Foursquare REST API calls | Simple REST, no SDK needed |
| recharts | ^2.15.4 (installed) | Bar chart in admin dashboard | Already in package.json, dark mode CSS already in globals.css |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| foursquare SDK (optional) | N/A | Foursquare Places API | Use raw requests instead — simpler, no extra dependency |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Foursquare Places API | Yelp Fusion API | Yelp requires approval for commercial use, returns fewer BR businesses |
| Foursquare Places API | Apollo.io API | Apollo free tier is very limited; not focused on BR SMBs |
| Playwright Apple Maps | Apple MapKit JS | MapKit JS requires Apple developer account + JWT; not suitable for server-side scraping |
| Playwright Apple Maps | maps.apple.com unofficial API | No documented unofficial JSON API found; web scraping is the only viable approach |

**Installation:** No new packages needed — Playwright, requests, and recharts are already installed.

---

## Architecture Patterns

### Recommended Project Structure

Phase 10 adds no new files except test stubs. All logic goes in `app/backend/app.py` (monolith convention).

```
app/backend/app.py
├── _get_foursquare_key()              # New — AWS SM key helper
├── search_foursquare_places()         # New — REST call to Foursquare Places API
├── process_foursquare_massive()       # New — Thread 18 (SRC-02)
├── process_apple_maps_massive()       # New — Thread 17 (SRC-01)
├── process_outscraper_massive()       # Modified — limit 20→100, batch support (SRC-03)
├── process_search_job()               # Modified — 5-template query expansion (SRC-04)
└── GET /api/admin/source-stats        # New endpoint

app/frontend/pages/admin/index.tsx
└── SourceStatsChart component         # New — bar chart at bottom of admin dashboard
```

### Pattern 1: Thread Registration in Massive Search Orchestrator

The orchestrator in `POST /api/search/massive` follows a strict pattern: (1) build jobs list, (2) INSERT search_jobs rows, (3) start daemon thread. Apple Maps (Thread 17) and Foursquare (Thread 18) must follow this exact pattern.

```python
# Step 1: build jobs in the orchestrator (inside the DB transaction block)
apple_maps_jobs = []
if 'apple_maps' in methods:
    for niche in niches[:3]:
        for city_data in cities_to_search[:2]:
            c.execute(
                '''INSERT INTO search_jobs (..., engine, ...) VALUES (..., 'apple_maps', ...) RETURNING id''',
                (batch_id, user_id, niche, city_data['city'], city_data['state'], ...))
            apple_maps_jobs.append({'search_job_id': c.fetchone()[0], 'niche': niche,
                                    'city': city_data['city'], 'state': city_data['state']})

# Step 2: start thread after transaction closes
# Thread 17: Apple Maps (Playwright)
if apple_maps_jobs:
    threading.Thread(target=process_apple_maps_massive,
                     args=(batch_id, apple_maps_jobs, user_id), daemon=True).start()
```

### Pattern 2: Thread Function Structure (copy of process_google_maps_massive)

All massive threads follow the same skeleton. Apple Maps should copy `process_google_maps_massive` exactly:

```python
@_persist_thread_errors('apple_maps')
def process_apple_maps_massive(batch_id, jobs_data, user_id):
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    try:
        c = conn.cursor()
        total_saved = 0
        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche = job_data['niche']
            city  = job_data['city']
            state = job_data['state']
            # ... Playwright scraping logic ...
            leads_saved = _save_leads_to_batch(c, conn, batch_id, leads,
                                               'apple_maps', city, state, 'APPLE_MAPS')
            total_saved += leads_saved
            time.sleep(random.uniform(8, 15))  # Apple Maps anti-blocking
    except Exception as e:
        scraper_log('CRITICAL', 'apple_maps', f'batch={batch_id}', str(e), e)
    finally:
        conn.close()
```

### Pattern 3: Apple Maps Playwright URL Structure

Apple Maps web search works via URL parameters on `https://maps.apple.com/`:

```
https://maps.apple.com/?q={niche}+{city}&near={city}
```

The page renders a JavaScript-heavy results list. Playwright must:
1. Navigate to the URL with a fresh browser context
2. Wait for the results panel to appear (CSS selector: `.place-list` or similar — must be verified at scraping time)
3. Scroll to load more results
4. Extract name, address, phone from each result card

**Critical:** Apple Maps results are geo-biased. Using `near={city}` or `sll={lat},{lon}` parameter improves relevance. For Brazilian cities, `near=Vitória,ES,Brasil` format.

### Pattern 4: Outscraper Batch + Higher Limit

Current code sends one query per call with `limit=20`. The SDK accepts a list of queries and supports `limit` up to 500:

```python
# Current (SRC-03 before)
result, err = _massive_retry(
    lambda q=query: client.google_maps_search([q], limit=20, ...),
    provider='outscraper', query=query
)

# Improved (SRC-03 after) — batch multiple queries, limit=100
batch_queries = [f"{niche} {city} {state}" for niche, city, state in job_batch]
result, err = _massive_retry(
    lambda qs=batch_queries: client.google_maps_search(qs, limit=100,
        language="pt", region="BR",
        fields=["name", "phone", "email", "full_address", "site", "category"]),
    provider='outscraper', query=str(batch_queries)
)
# result is list-of-lists: result[i] = businesses for batch_queries[i]
```

**Pagination via skip:** The Outscraper API supports a `skip` parameter. To get results 100-200 for a query: call again with `skip=100, limit=100`. This allows fetching up to 500 results per query in 5 calls. Given the free tier (500 records/month), skip-pagination is a future enhancement — not mandatory for Wave 1.

### Pattern 5: Five Query Templates for process_search_job

Current `process_search_job` builds a single query string. The improvement loops over 5 templates, each creating a separate `search_job` row:

```python
# Five templates (from ROADMAP.md)
SEARCH_QUERY_TEMPLATES = [
    "{niche} {city} contato",
    "{niche} {city} email",
    "{niche} {city} whatsapp",
    'site:*.com.br "{niche}" "{city}"',
    '"{niche}" "{city}" OR "{vizinha}"',
]

# In the orchestrator — 5 search_job rows per niche+city
for niche in niches[:3]:
    for city_data in cities_to_search[:2]:
        vizinha = get_nearest_city(city_data['city'])  # or hardcode fallback
        for tmpl in SEARCH_QUERY_TEMPLATES:
            query = tmpl.format(niche=niche, city=city_data['city'],
                                vizinha=vizinha or city_data['city'])
            c.execute('INSERT INTO search_jobs (...) VALUES (...)', ...)
            search_engine_jobs.append(...)
```

**Important:** Templates with `site:*.com.br` only work on Bing (not DuckDuckGo). The `search_with_fallback()` function already handles engine selection. The `site:` operator in DDG HTML is ignored silently (no crash).

### Pattern 6: GET /api/admin/source-stats

New endpoint — GROUP BY source on the leads table, filtered to last 30 days:

```python
@app.route('/api/admin/source-stats')
@require_admin
def api_admin_source_stats():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT source, COUNT(*) AS total
            FROM leads
            WHERE extracted_at >= NOW() - INTERVAL '30 days'
              AND source IS NOT NULL
            GROUP BY source
            ORDER BY total DESC
        ''')
        rows = c.fetchall()
    return jsonify([{'source': r[0], 'count': r[1]} for r in rows])
```

**Note:** The `leads` table uses `extracted_at` as the timestamp column (not `created_at`) — verify column name before writing the query.

### Pattern 7: Recharts BarChart in Admin Dashboard

The admin dashboard (`/admin/index.tsx`) already uses Recharts dark mode CSS from `globals.css`. A `BarChart` component should be added below the "Pipeline Automático" section:

```typescript
// Source: recharts 2.15.4 — already installed
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

// data shape from GET /api/admin/source-stats
interface SourceStat { source: string; count: number }

// Inside AdminHome component:
const [sourceStats, setSourceStats] = useState<SourceStat[]>([])
// fetch in useEffect alongside existing calls

// JSX:
<ResponsiveContainer width="100%" height={200}>
  <BarChart data={sourceStats} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
    <XAxis dataKey="source" tick={{ fontSize: 11 }} />
    <YAxis tick={{ fontSize: 11 }} />
    <Tooltip />
    <Bar dataKey="count" fill="#6366f1" />
  </BarChart>
</ResponsiveContainer>
```

### Anti-Patterns to Avoid

- **Don't use `@apply` in globals.css** — circular dependency with Tailwind. Use raw CSS (`fill: rgb(...)`) for Recharts dark mode overrides.
- **Don't stop the loop on Foursquare 429** — use the same `quota_exceeded` flag pattern from `process_outscraper_massive()`.
- **Don't use late-binding lambdas in loops** — use default args: `lambda q=query: client.google_maps_search([q], ...)`.
- **Don't import Playwright at module level in app.py** — keep inside the function or import at thread start to avoid startup failure if Playwright is not installed.
- **Don't add new Apple Maps thread to the response dict without also adding to the methods dict** in the `return jsonify(...)` at the end of the massive search endpoint.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Outscraper batching | Custom loop with individual requests | SDK list input: `client.google_maps_search([q1,q2,...])` | SDK handles async internally |
| Dark mode for Recharts | JS-based theme toggle | Raw CSS in globals.css (already set up) | Pattern already established |
| Foursquare auth | JWT flow | Simple API key via `?api_key=KEY` header | Foursquare v3 uses `Authorization: Bearer KEY` header |
| Apple Maps pagination | Custom scroll-to-bottom with counter | Playwright `page.evaluate("window.scrollTo(0, document.body.scrollHeight)")` in a loop | Standard pattern |
| Source labels | Raw source strings in chart | Short label map: `search_engine → Motores Busca`, `outscraper_maps → Outscraper Maps` | Better UX in admin |

---

## Runtime State Inventory

This is a greenfield phase (new threads, new endpoint, new chart). No renaming or migration.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — new `source='apple_maps'` and `source='foursquare'` values will appear in `leads.source` after implementation | None — column exists, new values are additive |
| Live service config | None | None |
| OS-registered state | None | None |
| Secrets/env vars | `OUTSCRAPER_API_KEY` (already in AWS SM as `extratordedados/prod`), `FOURSQUARE_API_KEY` (new — must be added to AWS SM) | Add `FOURSQUARE_API_KEY` to AWS SM `extratordedados/prod` |
| Build artifacts | None | None |

---

## Common Pitfalls

### Pitfall 1: Apple Maps JavaScript Rendering Lag

**What goes wrong:** Playwright navigates to `maps.apple.com` but the results list has not rendered yet when selectors are queried, returning empty results.
**Why it happens:** Apple Maps is a heavy SPA — results load asynchronously after the page loads.
**How to avoid:** Use `page.wait_for_selector('.place-list-item', timeout=15000)` before extracting data. If selector times out, mark job as `paused` (not `failed`) and record a `BlockedError`.
**Warning signs:** Zero results from every job, no error in scraper log.

### Pitfall 2: Apple Maps Bot Detection

**What goes wrong:** Apple Maps detects Playwright and shows a blank page or CAPTCHA.
**Why it happens:** Apple uses browser fingerprinting. Default Playwright has detectable headless fingerprints.
**How to avoid:** Use `playwright-stealth` (already installed for Google Maps use) or set viewport, user-agent, and locale to mimic a real iPhone user. Add 10-20s delay between searches.
**Warning signs:** Page loads but results panel never appears.

### Pitfall 3: Outscraper limit=100 Consumes Free Tier Faster

**What goes wrong:** Increasing from `limit=20` to `limit=100` with the same number of jobs burns through the 500 records/month free tier in 5 jobs instead of 25.
**Why it happens:** Free tier is capped at 500 records total, not 500 per query.
**How to avoid:** Keep `limit=100` but reduce the number of jobs in the orchestrator from `niches[:3] × cities[:2]` = 6 jobs down to `niches[:2] × cities[:2]` = 4 jobs, or `niches[:1] × cities[:5]`. Document the trade-off in a comment.
**Warning signs:** Jobs after the 5th return `quota_exceeded`.

### Pitfall 4: Five Query Templates Multiply search_engine_jobs by 5×

**What goes wrong:** Massive search takes 5× longer to complete because search_engine_jobs goes from 6 rows to 30.
**Why it happens:** Each template creates a separate search_job with deep-crawl for each result URL.
**How to avoid:** Reduce the city/niche scope for template expansion. Instead of all `niches[:3] × cities[:2] × 5 templates`, use `niches[:2] × cities[:1] × 5 templates` = 10 jobs. Or expose template count as a parameter with default=3.
**Warning signs:** Massive search takes 30+ minutes, monitor thread times out.

### Pitfall 5: source Column Timestamp Filter Wrong Column Name

**What goes wrong:** `GET /api/admin/source-stats` returns 0 rows because `extracted_at` column does not exist on the `leads` table.
**Why it happens:** The column may be named `created_at` or the migration added it as `captured_at` (Phase 2 added `captured_at`).
**How to avoid:** Verify with `SELECT column_name FROM information_schema.columns WHERE table_name='leads'` before writing the GROUP BY query. Use `captured_at` (added in Phase 2 migration).
**Warning signs:** Endpoint returns empty array even though leads exist.

### Pitfall 6: Foursquare API Key Not in AWS SM

**What goes wrong:** `_get_foursquare_key()` returns None at runtime, all Foursquare jobs fail immediately.
**Why it happens:** Key not added before deploy.
**How to avoid:** Add key to AWS SM in Wave 0 plan. Gate thread start: if no key, log warning and skip thread (same pattern as Outscraper).
**Warning signs:** All foursquare jobs go to `failed/quota_exceeded` immediately.

---

## Code Examples

### Current process_search_job query build (lines 5094-5101 of app.py)

```python
# Source: app/backend/app.py lines 5094-5101 (verified)
query_parts = [niche]
if city:
    query_parts.append(city)
if state:
    query_parts.append(state)
if not city and not state and region and region in SEARCH_REGIONS:
    query_parts.append(SEARCH_REGIONS[region]['name'])
query = ' '.join(query_parts)
```

This is the ONLY query template. SRC-04 replaces this with a 5-template loop creating multiple search_job rows.

### Current Outscraper call (lines 12500-12507 of app.py)

```python
# Source: app/backend/app.py lines 12500-12507 (verified)
result, err = _massive_retry(
    lambda q=query: client.google_maps_search(
        [q], limit=20, language="pt", region="BR",
        fields=["name", "phone", "email", "full_address", "site", "category"]
    ),
    provider='outscraper',
    query=query
)
```

SRC-03 changes `limit=20` to `limit=100`. Batch queries require refactoring the loop to accumulate N queries, then call once.

### Existing source values in leads table (verified)

```
'google_maps'         — Thread 3 (process_google_maps_massive)
'search_engine'       — Thread 2 (process_search_job)
'outscraper_maps'     — Thread 16 (process_outscraper_massive)
'apify_maps'          — Thread 12 (process_apify_maps_massive)
'instagram'           — Thread 5 (process_instagram_massive)
'linkedin'            — Thread 6 (process_linkedin_massive)
'local_business_data' — Thread 7 (process_local_business_data_massive)
'empresas.com.br'     — inside process_directories_massive
'paginas_amarelas'    — inside process_directories_massive
'catalogo_br'         — inside process_directories_massive
```

New values for Phase 10: `'apple_maps'` and `'foursquare'`.

### Foursquare Places API call pattern

```python
# Source: https://docs.foursquare.com/developer/reference/places-api-overview (MEDIUM confidence)
import requests

def search_foursquare_places(niche, city, state, api_key, limit=50):
    url = "https://api.foursquare.com/v3/places/search"
    headers = {"Authorization": api_key, "Accept": "application/json"}
    params = {
        "query": f"{niche}",
        "near": f"{city}, {state}, Brazil",
        "limit": limit,
        "fields": "name,tel,website,location,categories"
    }
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("results", [])
```

### Recharts BarChart — existing dark mode CSS (already in globals.css lines 126-132)

```css
/* Source: app/frontend/styles/globals.css lines 126-132 (verified) */
.dark .recharts-cartesian-grid line { stroke: rgb(55 65 81); }
.dark .recharts-text { fill: rgb(156 163 175); }
```

No additional CSS needed for the bar chart — dark mode is already handled.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single query per niche | 5 query templates per niche | Phase 10 (SRC-04) | 5× more search coverage per niche+city |
| Outscraper limit=20 | Outscraper limit=100 | Phase 10 (SRC-03) | 5× more results per query (free tier still 500/month total) |
| 16 extraction threads | 17-18 threads | Phase 10 (SRC-01 + SRC-02) | New sources: Apple Maps + Foursquare |
| No source analytics | GET /api/admin/source-stats + bar chart | Phase 10 | Admin can see which sources are most productive |

**Deprecated/outdated:**
- `limit=20` in `process_outscraper_massive()`: undershoots Outscraper API capabilities (verified up to 500).

---

## Open Questions

1. **Apple Maps selector names**
   - What we know: URL pattern `maps.apple.com/?q=...&near=...` works in browser
   - What's unclear: Exact CSS selectors for the results list (`.place-list`, `.search-result`, etc.) — these must be discovered at Playwright runtime
   - Recommendation: Wave 0 plan should include a mini investigation step: run Playwright interactively against the URL and log the DOM structure before committing to selectors

2. **Outscraper `skip` pagination feasibility vs. free tier**
   - What we know: `skip` parameter exists (confirmed via search); free tier is 500 records/month
   - What's unclear: Whether batch queries with `limit=100` respect the free tier or use credits proportionally
   - Recommendation: Implement `limit=100` first; only add pagination if the free tier is upgraded

3. **Foursquare API key registration**
   - What we know: Foursquare Places API is free for 10,000 calls/month
   - What's unclear: Registration process and whether key is available before Wave 0 deploy
   - Recommendation: Planner should add a Wave 0 task: "Register Foursquare developer account, add API key to AWS SM as `FOURSQUARE_API_KEY` under `extratordedados/prod`"

4. **`captured_at` vs. `extracted_at` for 30-day filter**
   - What we know: Phase 2 added `captured_at` column; CLAUDE.md mentions `extracted_at` in the leads table description
   - What's unclear: Which column is actually on the production DB
   - Recommendation: Wave 0 migration check: `SELECT column_name FROM information_schema.columns WHERE table_name='leads' AND column_name IN ('captured_at','extracted_at')` and use whichever exists

5. **Template 5: neighboring city (`cidade vizinha`)**
   - What we know: Roadmap specifies `"[nicho]" "[cidade]" OR "[cidade vizinha]"` as the 5th template
   - What's unclear: Where the neighboring city comes from — hardcoded lookup table? `regions` table join? None available?
   - Recommendation: Use a simple fallback: if no neighboring city found, duplicate the main city as `city OR city` (effectively just `city`). A small static dict of ES city neighbors can be added later.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (pytest.ini at project root) |
| Config file | `pytest.ini` — `testpaths = tests`, `-v --tb=short` |
| Quick run command | `pytest tests/test_phase10.py -v --tb=short` |
| Full suite command | `pytest tests/ -v --tb=short` |

Tests are smoke tests against the live API (`https://api.extratordedados.com.br`). They use the `auth_headers` fixture from `conftest.py` which requires `ADMIN_PASSWORD` in AWS SM.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SRC-01 | `apple_maps` method accepted in POST /api/search/massive without error | smoke | `pytest tests/test_phase10.py::test_massive_accepts_apple_maps_method -x` | ❌ Wave 0 |
| SRC-01 | `apple_maps` appears in response methods dict with job count | smoke | `pytest tests/test_phase10.py::test_apple_maps_jobs_created -x` | ❌ Wave 0 |
| SRC-02 | `foursquare` method accepted in POST /api/search/massive without error | smoke | `pytest tests/test_phase10.py::test_massive_accepts_foursquare_method -x` | ❌ Wave 0 |
| SRC-03 | Outscraper jobs created with correct engine value | smoke | `pytest tests/test_phase10.py::test_outscraper_jobs_engine_value -x` | ❌ Wave 0 |
| SRC-04 | 5 search_jobs created per niche+city for search_engines method | smoke | `pytest tests/test_phase10.py::test_search_engine_template_expansion -x` | ❌ Wave 0 |
| SRC-04 | Each search_job has a distinct query value (not identical strings) | smoke | `pytest tests/test_phase10.py::test_search_engine_unique_queries -x` | ❌ Wave 0 |
| source-stats | GET /api/admin/source-stats returns 200 with list of {source, count} | smoke | `pytest tests/test_phase10.py::test_source_stats_endpoint -x` | ❌ Wave 0 |
| source-stats | Response contains at least one known source like 'google_maps' or 'search_engine' | smoke | `pytest tests/test_phase10.py::test_source_stats_has_data -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_phase10.py -v --tb=short`
- **Per wave merge:** `pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_phase10.py` — all 8 tests above (new file)
- [ ] No conftest.py changes needed — existing `auth_headers` fixture covers admin endpoint calls

---

## Sources

### Primary (HIGH confidence)
- `app/backend/app.py` — direct code read: `process_search_job` (lines 5071-5101), `process_outscraper_massive` (lines 12433-12580), thread orchestrator (lines 12081-12198), `save_lead_to_db` (lines 1404-1499), source values in leads table
- `app/frontend/pages/admin/index.tsx` — direct code read: current admin dashboard structure, no charts yet
- `app/frontend/package.json` — recharts ^2.15.4 confirmed installed
- `app/frontend/styles/globals.css` — Recharts dark mode CSS already present (lines 126-132)
- `pytest.ini` + `tests/conftest.py` — test infrastructure verified

### Secondary (MEDIUM confidence)
- [Outscraper Python SDK — PyPI](https://pypi.org/project/outscraper/) — `limit` up to 500, batch queries confirmed via list input
- [Outscraper Google Maps Examples — GitHub](https://github.com/outscraper/outscraper-python/blob/master/examples/Google%20Maps.md) — SDK usage patterns
- [Foursquare Places API — Rate Limits](https://docs.foursquare.com/developer/reference/rate-limits) — 10,000 free calls/month, 50 QPS confirmed
- [Apple Maps URL parameters — MacStories](https://www.macstories.net/ios/opening-any-apple-maps-place-or-address-on-the-web/) — `?q=` and `near=` parameters confirmed
- [Apple Maps Business Categories — PlePer](https://pleper.com/index.php?do=tools&sdo=apple_maps_categories) — 240+ categories available

### Tertiary (LOW confidence)
- WebSearch result: "Outscraper skip parameter for pagination" — confirmed via search summary but not directly tested
- WebSearch result: Foursquare returns phone/website/address for BR businesses — plausible given 100M+ global POIs but not verified against live BR data

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already installed, verified in package.json and requirements.txt
- Architecture: HIGH — thread pattern copied from existing code, endpoint pattern matches existing admin endpoints
- Apple Maps scraping feasibility: LOW — URL pattern confirmed but DOM selectors unknown until Playwright runtime
- Outscraper improvements: MEDIUM — `limit` parameter confirmed up to 500, `skip` pagination mentioned but not tested
- Foursquare as SRC-02 recommendation: MEDIUM — free tier confirmed, BR coverage claimed but not load-tested
- Pitfalls: HIGH — derived from existing code patterns and free-tier constraints
- Source column analytics: HIGH — `source` column existence and values verified in code

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (30 days — stable stack, no fast-moving dependencies)
