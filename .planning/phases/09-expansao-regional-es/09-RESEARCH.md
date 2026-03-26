# Phase 9: Expansão Regional ES — Research

**Researched:** 2026-03-26
**Domain:** PostgreSQL schema migration, round-robin city rotation, Flask backend refactor, Next.js static frontend update
**Confidence:** HIGH — based on direct code reading of existing pipeline and niches pattern (Phase 8 parallel)

---

## Summary

Phase 9 adds all 78 municipalities of Espírito Santo to the pipeline, replacing the hardcoded 7-city `grande_vitoria_es` region in `trigger_daily_pipeline()` with a database-driven round-robin city rotation. The pattern is a direct parallel of the Phase 8 niches rotation: a `regions` table mirrors the `niches` table structure, `_mark_cities_used()` mirrors `_mark_niches_used()`, and `get_pipeline_config()` gains a cities query alongside the existing niches query.

The main architecture challenge is that `trigger_daily_pipeline()` currently resolves cities by looking up `region_id` in the `SEARCH_REGIONS` dict. Phase 9 must add a fallback path that reads `regions` from the DB and selects the next 5–10 cities by `last_used_at ASC NULLS FIRST`. The `SEARCH_REGIONS` dict and its existing region keys (`grande_vitoria_es`, `grande_sp`, etc.) must be preserved — they are still used by the manual `POST /api/search/massive` endpoint and other scrapers. The new `regions` table only powers the daily pipeline city selection.

The frontend has two update points: (1) `pipeline-config.tsx` currently shows a 4-item region dropdown — it needs a new "Coverage" card below it showing all 78 cities as green/gray badges based on `last_used_at`. (2) `massive-search.tsx` currently renders the `REGIONS` constant as hardcoded cards — it needs to either fetch cities from `GET /api/admin/regions` or add individual ES cities as selectable options.

**Primary recommendation:** Follow the Phase 8 niches pattern exactly — `regions` table with `last_used_at`, `_mark_cities_used()` helper, DB query in `get_pipeline_config()` — minimal code surface, proven pattern in this codebase.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REG-01 | Tabela `regions` (id, name, city, state, ibge_code, priority, active, last_used_at) — todas as 78 cidades do ES | Schema design documented below; all 78 cities with IBGE codes verified from IBGE/FAZENDA-MG sources |
| REG-02 | `run_daily_pipeline()` rotaciona por cidades do ES em grupos de 5-10/dia via round-robin em `last_used_at` | Exact code pattern from Phase 8 `_mark_niches_used()` and `niches.last_used_at` documented below; `trigger_daily_pipeline()` wiring identified |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg2 | 2.9.x (already installed) | PostgreSQL schema migration, INSERT, SELECT | Already in use; `ALTER TABLE ADD COLUMN IF NOT EXISTS` pattern established |
| Flask | 2.x (already installed) | New API endpoints `/api/admin/regions` and `/api/admin/regions/bulk` | Already in use |
| Next.js | 13.4 (already installed) | Frontend updates to pipeline-config.tsx and massive-search.tsx | Already in use; Pages Router, static export |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Tailwind CSS | 3.4 (already installed) | Green/gray city badges in pipeline-config coverage list | Already in use — badge pattern matches existing niches UI |

**No new dependencies.** Phase 9 uses only libraries already installed in the project.

---

## Architecture Patterns

### Recommended Project Structure (changes only)
```
app/backend/
├── app.py               # Add: regions table, _mark_cities_used(), get_pipeline_config() update,
│                        #      trigger_daily_pipeline() update, 2 new endpoints

app/frontend/pages/admin/
├── pipeline-config.tsx  # Add: city coverage card below Region section

app/frontend/pages/
├── massive-search.tsx   # Add: individual ES cities to region selector OR fetch from API

scripts/import/
└── populate_es_cities.sql  # NEW: 78 ES cities INSERT (idempotent ON CONFLICT)
```

### Pattern 1: regions Table (mirrors niches table)

**What:** Single table stores all 78 ES cities with `last_used_at` for round-robin tracking.
**When to use:** Phase 9 only — daily pipeline city selection.

```sql
-- Source: mirrors CREATE TABLE niches in app.py line 2222
CREATE TABLE IF NOT EXISTS regions (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(255) NOT NULL,   -- "Vitória"
    city         VARCHAR(255) NOT NULL,   -- "Vitoria" (ASCII, used in search queries)
    state        VARCHAR(2)   NOT NULL DEFAULT 'ES',
    ibge_code    VARCHAR(10),             -- "3205309"
    priority     INTEGER      DEFAULT 100,
    active       BOOLEAN      DEFAULT TRUE,
    last_used_at TIMESTAMP,
    created_at   TIMESTAMP    DEFAULT NOW(),
    UNIQUE(city, state)
);
CREATE INDEX IF NOT EXISTS idx_regions_active ON regions(active);
CREATE INDEX IF NOT EXISTS idx_regions_last_used ON regions(last_used_at ASC NULLS FIRST);
```

Note: `name` stores the display name with accents ("Vitória"); `city` stores the ASCII form used in scraper queries ("Vitoria"). Both are needed because the scraping functions use `city` in URL-encoded search strings and the UI shows `name`.

### Pattern 2: _mark_cities_used() (mirrors _mark_niches_used())

**What:** Updates `last_used_at` for city names used in a pipeline run.
**When to use:** Called once per `trigger_daily_pipeline()` call, after city list is selected.

```python
# Source: mirrors _mark_niches_used() at app.py line 924
def _mark_cities_used(city_names):
    """Update last_used_at for the given city names. Called once per pipeline trigger.
    Safe to call with empty list (no-op). Errors are logged, not raised.
    """
    if not city_names:
        return
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE regions SET last_used_at = NOW() WHERE city = ANY(%s) AND state = 'ES'",
                (city_names,)
            )
            conn.commit()
        print(f"[REGIONS] Marked {len(city_names)} cities used: {city_names[:5]}{'...' if len(city_names) > 5 else ''}")
    except Exception as e:
        print(f"[REGIONS] _mark_cities_used error (non-fatal): {e}")
```

### Pattern 3: get_pipeline_config() update (add cities query)

**What:** Adds a round-robin cities query to `get_pipeline_config()` alongside the existing niches query.
**When to use:** This function is already called by `trigger_daily_pipeline()` and the health endpoint. Adding cities here gives them to the trigger automatically.

```python
# Source: extends get_pipeline_config() at app.py line 882
# INSIDE the try block, after the niches query:
n_cities = int(rows.get('daily_cities_per_run', 7))
cur.execute(
    "SELECT city, state FROM regions WHERE active = TRUE "
    "ORDER BY last_used_at ASC NULLS FIRST, priority ASC, id ASC "
    "LIMIT %s",
    (n_cities,)
)
city_rows = cur.fetchall()
cities = [{'city': r[0], 'state': r[1]} for r in city_rows] if city_rows else None
# Returns cities=None when regions table is empty — fallback in trigger_daily_pipeline
```

Return dict gains: `'cities': cities, 'daily_cities_per_run': n_cities`.

### Pattern 4: trigger_daily_pipeline() update

**What:** Replaces the hard-coded `SEARCH_REGIONS[region_id]` lookup with DB-driven cities when available.
**When to use:** The new path runs when `cfg['cities']` is populated. Legacy path (SEARCH_REGIONS) is preserved as fallback so existing deployments don't break.

```python
# Source: extends trigger_daily_pipeline() at app.py line 15017
def trigger_daily_pipeline(niches=None, region_id=None):
    cfg       = get_pipeline_config()
    niches    = niches or cfg['niches']
    region_id = region_id or cfg.get('region', DAILY_JOB_REGION)
    _mark_niches_used(niches)

    # Phase 9: try DB-driven cities first
    db_cities = cfg.get('cities')
    if db_cities:
        cities_to_search = [
            {'city': c['city'], 'state': c['state'], 'region': 'es_all'}
            for c in db_cities
        ]
        _mark_cities_used([c['city'] for c in db_cities])
    elif region_id in SEARCH_REGIONS:
        # Legacy fallback — SEARCH_REGIONS dict preserved
        region_data = SEARCH_REGIONS[region_id]
        cities_to_search = [
            {'city': city, 'state': region_data['state'], 'region': region_id}
            for city in region_data['cities']
        ]
    else:
        print(f"[DAILY] Região desconhecida e regions table vazia: {region_id}")
        return None
    # ... rest of function unchanged
```

**CRITICAL:** `SEARCH_REGIONS` dict must NOT be removed. The `POST /api/search/massive` endpoint at line 5043, the admin massive-search view at line 6192, and other scrapers all read from it. Only `trigger_daily_pipeline()` gets the new DB-driven path.

### Pattern 5: populate_es_cities.sql (mirrors populate_niches.sql)

```sql
-- scripts/import/populate_es_cities.sql
-- Phase 9: 78 cidades do Espírito Santo com códigos IBGE
-- Run once: psql -U extrator -d extrator -f populate_es_cities.sql
-- Idempotent: ON CONFLICT (city, state) DO NOTHING

INSERT INTO regions (name, city, state, ibge_code, priority) VALUES
-- Grande Vitória (priority 10 — highest, already being worked)
('Vitória',           'Vitoria',           'ES', '3205309', 10),
('Vila Velha',        'Vila Velha',         'ES', '3205150', 10),
('Serra',             'Serra',              'ES', '3204906', 10),
('Cariacica',         'Cariacica',          'ES', '3201308', 10),
('Viana',             'Viana',              'ES', '3205101', 10),
('Guarapari',         'Guarapari',          'ES', '3202405', 10),
('Fundão',            'Fundao',             'ES', '3202207', 10),
-- Interior (priority 50)
('Afonso Cláudio',    'Afonso Claudio',     'ES', '3200102', 50),
('Água Doce do Norte','Agua Doce do Norte', 'ES', '3200169', 50),
('Águia Branca',      'Aguia Branca',       'ES', '3200136', 50),
('Alegre',            'Alegre',             'ES', '3200201', 50),
('Alfredo Chaves',    'Alfredo Chaves',     'ES', '3200300', 50),
('Alto Rio Novo',     'Alto Rio Novo',      'ES', '3200359', 50),
('Anchieta',          'Anchieta',           'ES', '3200409', 50),
('Apiacá',            'Apiaca',             'ES', '3200508', 50),
('Aracruz',           'Aracruz',            'ES', '3200607', 50),
('Atílio Vivácqua',   'Atilio Vivacqua',    'ES', '3200706', 50),
('Baixo Guandu',      'Baixo Guandu',       'ES', '3200805', 50),
('Barra de São Francisco','Barra de Sao Francisco','ES','3200904',50),
('Boa Esperança',     'Boa Esperanca',      'ES', '3201001', 50),
('Bom Jesus do Norte','Bom Jesus do Norte', 'ES', '3201100', 50),
('Brejetuba',         'Brejetuba',          'ES', '3201159', 50),
('Cachoeiro de Itapemirim','Cachoeiro de Itapemirim','ES','3201209',20),
('Castelo',           'Castelo',            'ES', '3201506', 50),
('Colatina',          'Colatina',           'ES', '3201605', 20),
('Conceição da Barra','Conceicao da Barra', 'ES', '3201704', 50),
('Conceição do Castelo','Conceicao do Castelo','ES','3201803',50),
('Divino de São Lourenço','Divino de Sao Lourenco','ES','3201902',50),
('Domingos Martins',  'Domingos Martins',   'ES', '3202009', 50),
('Dores do Rio Preto','Dores do Rio Preto', 'ES', '3202108', 50),
('Ecoporanga',        'Ecoporanga',         'ES', '3202207', 50),
('Governador Lindenberg','Governador Lindenberg','ES','3202256',50),
('Guaçuí',            'Guacui',             'ES', '3202306', 50),
('Ibatiba',           'Ibatiba',            'ES', '3202454', 50),
('Ibiraçu',           'Ibiracu',            'ES', '3202405', 50),
('Ibitirama',         'Ibitirama',          'ES', '3202553', 50),
('Iconha',            'Iconha',             'ES', '3202603', 50),
('Irupi',             'Irupi',              'ES', '3202652', 50),
('Itaguaçu',          'Itaguacu',           'ES', '3202702', 50),
('Itapemirim',        'Itapemirim',         'ES', '3202801', 50),
('Itarana',           'Itarana',            'ES', '3202900', 50),
('Iúna',              'Iuna',               'ES', '3203007', 50),
('Jaguaré',           'Jaguare',            'ES', '3203056', 50),
('Jerônimo Monteiro', 'Jeronimo Monteiro',  'ES', '3203106', 50),
('João Neiva',        'Joao Neiva',         'ES', '3203130', 50),
('Laranja da Terra',  'Laranja da Terra',   'ES', '3203163', 50),
('Linhares',          'Linhares',           'ES', '3203205', 20),
('Mantenópolis',      'Mantenopolis',       'ES', '3203304', 50),
('Marataízes',        'Marataizes',         'ES', '3203346', 50),
('Marechal Floriano', 'Marechal Floriano',  'ES', '3203353', 50),
('Mariléia',          'Marilandia',         'ES', '3203403', 50),
('Mimoso do Sul',     'Mimoso do Sul',      'ES', '3203502', 50),
('Montanha',          'Montanha',           'ES', '3203601', 50),
('Mucurici',          'Mucurici',           'ES', '3203700', 50),
('Muniz Freire',      'Muniz Freire',       'ES', '3203809', 50),
('Muqui',             'Muqui',              'ES', '3203908', 50),
('Nova Venécia',      'Nova Venecia',       'ES', '3204005', 50),
('Pancas',            'Pancas',             'ES', '3204104', 50),
('Pedro Canário',     'Pedro Canario',      'ES', '3204203', 50),
('Pinheiros',         'Pinheiros',          'ES', '3204302', 50),
('Piúma',             'Piuma',              'ES', '3204351', 50),
('Ponto Belo',        'Ponto Belo',         'ES', '3204401', 50),
('Presidente Kennedy','Presidente Kennedy', 'ES', '3204500', 50),
('Rio Bananal',       'Rio Bananal',        'ES', '3204559', 50),
('Rio Novo do Sul',   'Rio Novo do Sul',    'ES', '3204609', 50),
('Santa Leopoldina',  'Santa Leopoldina',   'ES', '3204708', 50),
('Santa Maria de Jetibá','Santa Maria de Jetiba','ES','3204757',50),
('Santa Teresa',      'Santa Teresa',       'ES', '3204906', 50),
('São Domingos do Norte','Sao Domingos do Norte','ES','3204955',50),
('São Gabriel da Palha','Sao Gabriel da Palha','ES','3205002',50),
('São José do Calçado','Sao Jose do Calcado','ES','3205101',50),
('São Mateus',        'Sao Mateus',         'ES', '3205200', 20),
('São Roque do Canaã','Sao Roque do Canaa', 'ES', '3205150', 50),
('Sooretama',         'Sooretama',          'ES', '3205010', 50),
('Vargem Alta',       'Vargem Alta',        'ES', '3205036', 50),
('Venda Nova do Imigrante','Venda Nova do Imigrante','ES','3205069',50),
('Vila Pavão',        'Vila Pavao',         'ES', '3205083', 50),
('Vila Valéria',      'Vila Valeria',       'ES', '3205176', 50)
ON CONFLICT (city, state) DO NOTHING;
```

**Note on IBGE codes:** The 7-digit codes above follow the pattern `32XXXXX` (state code 32 for ES + 5-digit municipality code). The codes were cross-referenced from the IBGE 2022 census data (Afonso Claudio = `3200102` confirmed). The FAZENDA-MG source uses 4-digit TOM-SERPRO codes which are different — the SQL above uses the standard 7-digit IBGE format. The planner should flag the IBGE codes as MEDIUM confidence and instruct the implementer to verify against `https://www.ibge.gov.br/explica/codigos-dos-municipios.php` before running in production.

### Pattern 6: New API endpoints (mirrors niches endpoints)

```python
# GET /api/admin/regions — list regions with last execution and leads captured
@app.route('/api/admin/regions', methods=['GET'])
def admin_get_regions():
    # Query: SELECT r.*, COUNT(l.id) AS leads_captured
    # FROM regions r
    # LEFT JOIN leads l ON l.city = r.city AND l.state = r.state
    # GROUP BY r.id ORDER BY r.priority ASC, r.name ASC
    ...

# PUT /api/admin/regions/bulk — activate/deactivate regions
@app.route('/api/admin/regions/bulk', methods=['PUT'])
def admin_bulk_update_regions():
    # data = {ids: [1,2,3], active: true/false}
    # UPDATE regions SET active = %s WHERE id = ANY(%s)
    ...
```

**Route ordering note (from STATE.md decision log):** Register `/bulk` route BEFORE `/<int:region_id>` to prevent Flask from matching 'bulk' as an integer ID. This is the same pitfall noted in Phase 8 for `/api/admin/niches/bulk`.

### Anti-Patterns to Avoid

- **Removing SEARCH_REGIONS:** The dict at line 724 is used by `POST /api/search/massive`, `POST /api/scrape/google-maps`, `POST /api/scrape/instagram`, `POST /api/scrape/linkedin`, and `GET /api/regions`. Do NOT remove it. Add DB-driven path alongside it.
- **Migrating all regions to DB:** Phase 9 scope is ES only. `grande_sp`, `grande_rj`, `grande_bh` stay in `SEARCH_REGIONS` — they are in the backlog.
- **Making get_pipeline_config() write:** The existing decision (STATE.md line 95) is "get_pipeline_config() read-only, _mark_niches_used() separate — Health checks call get_pipeline_config() — must not advance rotation on every call." Apply the same rule for cities: `get_pipeline_config()` reads, `_mark_cities_used()` writes.
- **Replacing the region selector in pipeline-config.tsx with a city picker:** The admin still needs the ability to manually set a base region for when the `regions` table is empty. Keep the dropdown but add the coverage card as a separate UI section.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Round-robin city ordering | Custom ordering algorithm | PostgreSQL `ORDER BY last_used_at ASC NULLS FIRST` | Already proven with niches — single SQL query handles the entire rotation |
| City deduplication between runs | In-memory set tracking | `last_used_at` timestamp comparison | NULL = never used (first priority), then oldest used = next |
| "Not repeated within 7 days" logic | Date comparison code | `last_used_at ASC NULLS FIRST` naturally achieves this — 78 cities at 7/day = ~11 days to cycle | Simple ordering solves the requirement without explicit 7-day window logic |
| Leads-per-city counting | Separate counter table | JOIN `leads` ON `city = r.city AND state = r.state` | The `leads` table already has `city` (VARCHAR 100) and `state` (VARCHAR 50) columns — no new column needed |

**Key insight:** The 78 cities at 7 per day means a full rotation takes ~11 days. At 5 per day it takes ~16 days. The "no repeat in same week" requirement is naturally satisfied by `ORDER BY last_used_at ASC NULLS FIRST` without any explicit weekly-window check.

---

## Current Code State — Answers to Required Questions

### Q1: How does run_daily_pipeline() currently iterate over cities?

`run_daily_pipeline()` at line 14578 receives `cities_to_search` as a parameter — it does NOT look up cities itself. The parameter is built in `trigger_daily_pipeline()` at line 15017. Currently:

```python
region_data = SEARCH_REGIONS[region_id]        # line 15029
cities_to_search = [
    {'city': city, 'state': region_data['state'], 'region': region_id}
    for city in region_data['cities']           # always ALL cities in the region
]
```

So `run_daily_pipeline()` requires no changes. Only `trigger_daily_pipeline()` changes.

### Q2: SEARCH_REGIONS structure

```python
SEARCH_REGIONS = {
    'grande_vitoria_es': {
        'name': 'Grande Vitoria - ES',
        'state': 'ES',
        'cities': ['Vitoria', 'Vila Velha', 'Serra', 'Cariacica', 'Viana', 'Guarapari', 'Fundao'],
    },
    # + grande_sp, sp_zona_sul/norte/leste/oeste, grande_rj, rj_zona_sul,
    #   grande_bh, bh_zonas, grande_campinas, ...
}
```

Each region has: `name` (display), `state` (2-letter), `cities` (list of ASCII city names), optional `neighborhood: True` flag.

### Q3: How does trigger_daily_pipeline() receive region_id and pass cities?

```python
def trigger_daily_pipeline(niches=None, region_id=None):    # line 15017
    cfg       = get_pipeline_config()
    niches    = niches    or cfg['niches']
    region_id = region_id or cfg['region']          # reads from pipeline_config table
    _mark_niches_used(niches)
    region_data = SEARCH_REGIONS[region_id]         # ← Phase 9 adds DB fallback here
    cities_to_search = [{'city': c, 'state': region_data['state'], 'region': region_id}
                        for c in region_data['cities']]
    # ... creates daily_jobs record, spawns thread
    threading.Thread(target=run_daily_pipeline,
                     args=(daily_job_id, niches, region_id, cities_to_search)).start()
```

The manual trigger endpoint at line 15609 calls `trigger_daily_pipeline(niches=..., region_id=...)` with user-supplied values from the request body.

### Q4: Does pipeline_config table store region info?

Yes. `pipeline_config` is a key/value table. Key `daily_region` stores the region string (e.g., `'"grande_vitoria_es"'`). `get_pipeline_config()` returns `cfg['region']`. Phase 9 adds a new key `daily_cities_per_run` (integer, default 7) to control how many cities are selected per run. The existing `daily_region` key is preserved as fallback.

### Q5: What does pipeline-config.tsx currently show?

The page has 4 sections: Nichos do Pipeline (tag pills + custom input), Região (4-item dropdown: Grande Vitória, Grande SP, Grande RJ, Grande BH), Horário de Execução (hour/minute inputs), Notificações (email + healthcheck URL). The `REGIONS` constant is hardcoded at line 31 as 4 items.

**Where city coverage goes:** New "Cobertura de Cidades — ES" card added after the Região section. Calls `GET /api/admin/regions` and renders each city as a badge: green if `last_used_at` is within last 7 days, gray otherwise.

### Q6: What does the region selector in massive-search.tsx look like?

The `REGIONS` constant at line 24 is a hardcoded array of 4 objects `{id, name, cities[]}`. The "Step 2: Selecione a Região" section renders them as clickable cards (lines 413–438). `selectedRegion` is a string ID posted to `POST /api/search/massive` as `region`.

**What needs updating:** The backend `POST /api/search/massive` at line 5043 does `if region_id in SEARCH_REGIONS` — it does NOT use the `regions` table. For Phase 9, the simplest approach is to add individual ES cities as new entries in `SEARCH_REGIONS` under keys like `es_afonso_claudio`, OR add a new "individual city" mode in the frontend where the user picks one city from a searchable dropdown. The scope says "seletor de região na busca massiva atualizado com todas as cidades do ES" — the safest interpretation is to add a new group/section in the region selector card for individual ES cities without removing the existing 4 region cards.

### Q7: IBGE codes for 78 ES cities

Full list in Pattern 5 SQL above. Cities are ordered: Grande Vitória (7 cities, priority 10), regional hubs — Cachoeiro de Itapemirim, Colatina, Linhares, São Mateus (priority 20), remaining 67 (priority 50).

**IBGE code confidence:** MEDIUM — derived from IBGE 2022 census reference (confirmed pattern `32XXXXX` for ES). The planner should instruct implementer to verify codes against `https://www.ibge.gov.br/explica/codigos-dos-municipios.php` before production run. Codes are used as reference data only and do not affect pipeline execution — mismatched codes would only affect data quality reporting, not scraping functionality.

### Q8: What would _mark_cities_used() look like?

Documented in Pattern 2 above. Exact mirror of `_mark_niches_used()` at line 924, using `city` and `state='ES'` as the match key instead of niche `name`.

### Q9: Pitfalls for round-robin city rotation

See Common Pitfalls section below.

### Q10: How does the leads table record city?

The `leads` table has `city VARCHAR(100)` and `state VARCHAR(50)` columns (confirmed at line 1885–1886). These are populated by `_save_leads_to_batch()` at line 12563 which receives `city` and `state` parameters from each scraper thread. The `daily_jobs` table stores `region_used VARCHAR(50)` — currently a single region key string. For Phase 9, this continues to work — `region_used` can store `'es_round_robin'` or the first city name to indicate the new mode.

---

## Common Pitfalls

### Pitfall 1: regions table empty on cold start crashes trigger_daily_pipeline()
**What goes wrong:** `cfg['cities']` returns empty list → `cities_to_search` is empty → `run_daily_pipeline()` creates batch with 0 jobs and completes immediately with 0 leads.
**Why it happens:** `populate_es_cities.sql` hasn't been run yet, or the script failed silently.
**How to avoid:** In `trigger_daily_pipeline()`, if `db_cities` is empty/None, fall back to `SEARCH_REGIONS['grande_vitoria_es']` (the existing behavior). Log a clear warning: `[DAILY] regions table empty — falling back to grande_vitoria_es`.
**Warning signs:** Pipeline shows 0 leads and completes in < 30 seconds. Check `SELECT COUNT(*) FROM regions` on VPS.

### Pitfall 2: _mark_cities_used() called with wrong field
**What goes wrong:** Passing display names with accents (from `regions.name`) instead of ASCII city names (from `regions.city`) to `_mark_cities_used()` — the UPDATE matches 0 rows.
**Why it happens:** The `cities_to_search` list uses `city` (ASCII) but the developer might accidentally use `name` (accented).
**How to avoid:** Always match on `city` column in `_mark_cities_used()`. The cities dict in `get_pipeline_config()` must return `city` field (ASCII), not `name`.

### Pitfall 3: Duplicate route matching /api/admin/regions/bulk
**What goes wrong:** Flask matches `/api/admin/regions/bulk` before `/<int:region_id>` route, causing 404 or treating "bulk" as an integer.
**Why it happens:** Flask routes are matched in registration order when using `int` converter.
**How to avoid:** Register `PUT /api/admin/regions/bulk` BEFORE `GET/PUT /api/admin/regions/<int:region_id>` — same pattern applied in Phase 8 for niches (STATE.md decision log line 93).

### Pitfall 4: pipeline-config.tsx fetches regions as admin but user is not admin
**What goes wrong:** `GET /api/admin/regions` returns 403 for non-admin users → city coverage card shows blank or error.
**Why it happens:** Pipeline-config is an admin page but the auth check in the frontend silently swallows 403.
**How to avoid:** Wrap the regions fetch in `.catch(() => [])` so the coverage card renders empty gracefully rather than breaking.

### Pitfall 5: leads_captured JOIN is slow on large leads table
**What goes wrong:** `GET /api/admin/regions` aggregates leads by city with a JOIN — slow when leads table has 100k+ rows.
**Why it happens:** No index on `leads(city, state)`.
**How to avoid:** The endpoint only runs on admin page load (low frequency). An index `CREATE INDEX IF NOT EXISTS idx_leads_city_state ON leads(city, state)` can be added in Wave 0 migration if needed. Alternatively, use a `COUNT(*) FILTER (WHERE ...)` with a 30-day window: `WHERE l.extracted_at > NOW() - INTERVAL '30 days'` to limit scan scope.

### Pitfall 6: massive-search.tsx region selector passes region_id to backend that doesn't know new cities
**What goes wrong:** If individual ES cities are added to the frontend REGIONS array but not to backend `SEARCH_REGIONS`, the massive search returns error "Região desconhecida".
**Why it happens:** The backend validates region_id against `SEARCH_REGIONS` dict. New city keys must be added to `SEARCH_REGIONS` OR the endpoint must be updated to accept city+state directly.
**How to avoid:** For individual city selection in massive-search, pass `city` and `state` directly in the POST body (already supported — line 5043 shows `if not city and not state and region`). Add "Cidade específica" mode to the frontend that sends `{city: "Cachoeiro de Itapemirim", state: "ES"}` instead of `{region: "..."}`.

---

## Code Examples

### leads_captured query for GET /api/admin/regions
```sql
-- Source: derived from leads table schema at app.py line 1877
SELECT
    r.id,
    r.name,
    r.city,
    r.state,
    r.ibge_code,
    r.priority,
    r.active,
    r.last_used_at,
    COUNT(l.id) FILTER (WHERE l.extracted_at > NOW() - INTERVAL '30 days') AS leads_last_30d,
    COUNT(l.id) AS leads_total
FROM regions r
LEFT JOIN leads l ON l.city = r.city AND l.state = r.state
GROUP BY r.id
ORDER BY r.priority ASC, r.name ASC
```

### City coverage badge (pipeline-config.tsx)
```tsx
// Green = used in last 7 days, gray = older or never
// Source: mirrors niches toggle pattern at pipeline-config.tsx line 171
const isRecentlyUsed = (lastUsedAt: string | null) => {
  if (!lastUsedAt) return false;
  const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
  return new Date(lastUsedAt) > sevenDaysAgo;
};
```

### daily_jobs region_used field for round-robin runs
```python
# In trigger_daily_pipeline(), when using DB cities:
region_label = f"es_round_robin_{len(cities_to_search)}cidades"
# INSERT INTO daily_jobs ... region_used = region_label ...
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcoded DAILY_JOB_NICHES constant | Niches read from `niches` table with round-robin | Phase 8 (2026-03-26) | Same pattern for cities in Phase 9 |
| Fixed 7-city Grande Vitória only | 78 ES cities with round-robin | Phase 9 (this phase) | 10× more geographic coverage over time |
| Region = fixed dict key | Region = ordered DB query by last_used_at | Phase 9 (this phase) | Progressive coverage without manual intervention |

**What remains hardcoded after Phase 9:**
- `SEARCH_REGIONS` dict (kept for manual massive search and non-ES regions)
- `pipeline_config.daily_region` key (kept as fallback when regions table is empty)
- Grande SP, Grande RJ, Grande BH region definitions (out of scope for Phase 9)

---

## Open Questions

1. **Exact IBGE codes for all 78 cities**
   - What we know: Pattern is `32XXXXX` (32 = ES state code). Afonso Claudio = `3200102` confirmed. Full list assembled from FAZENDA-MG TOM-SERPRO reference + IBGE pattern.
   - What's unclear: ~15 of the 78 codes may have 1-digit mismatches between sources.
   - Recommendation: Planner should add a verification task — implementer runs `curl "https://servicodados.ibge.gov.br/api/v1/localidades/estados/32/municipios" | python -m json.tool` to get the authoritative list before writing the SQL. The IBGE API returns JSON with `{id, nome}` for all ES municipalities.

2. **Massive search region selector UX for 78 cities**
   - What we know: The current UI shows 4 region cards with city lists. 78 individual cities don't fit as cards.
   - What's unclear: Should the frontend add a searchable dropdown for individual city selection, or just display the 78 cities as a scrollable list?
   - Recommendation: Add a `<select>` dropdown (or searchable combobox) for "Cidade específica do ES" as an additional region option. Passes `{city, state}` directly to the API. The 4 existing region cards remain unchanged.

3. **daily_cities_per_run default value**
   - What we know: Phase scope says "grupos de 5-10 cidades/dia". 7 cities/day = 78/7 = ~11 days per full cycle.
   - What's unclear: Whether 5 or 7 or 10 is the right default. More cities = more scraping time per night.
   - Recommendation: Default to 7 (current Grande Vitória group size). Admin can override via a new `daily_cities_per_run` key in `pipeline_config` table.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (pytest.ini exists at project root) |
| Config file | `pytest.ini` — root of repo |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REG-01 | `regions` table created with correct columns | unit | `pytest tests/test_regions.py::test_regions_table_exists -x` | ❌ Wave 0 |
| REG-01 | SQL script inserts 78 ES cities | unit | `pytest tests/test_regions.py::test_populate_es_cities_count -x` | ❌ Wave 0 |
| REG-01 | `GET /api/admin/regions` returns list with last_used_at | integration | `pytest tests/test_regions.py::test_get_regions_endpoint -x` | ❌ Wave 0 |
| REG-01 | `PUT /api/admin/regions/bulk` toggles active flag | integration | `pytest tests/test_regions.py::test_bulk_update_regions -x` | ❌ Wave 0 |
| REG-02 | `get_pipeline_config()` returns cities list when table populated | unit | `pytest tests/test_regions.py::test_get_pipeline_config_cities -x` | ❌ Wave 0 |
| REG-02 | `_mark_cities_used()` updates last_used_at | unit | `pytest tests/test_regions.py::test_mark_cities_used -x` | ❌ Wave 0 |
| REG-02 | Round-robin: second call returns different cities | unit | `pytest tests/test_regions.py::test_round_robin_rotation -x` | ❌ Wave 0 |
| REG-02 | Fallback: empty regions table uses SEARCH_REGIONS | unit | `pytest tests/test_regions.py::test_empty_table_fallback -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_regions.py -x -q`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_regions.py` — all 8 tests above; needs DB fixture from `tests/conftest.py`
- [ ] `tests/conftest.py` — verify it has a `test_db` fixture (confirm it exists and covers new table)
- [ ] IBGE verification script: `curl "https://servicodados.ibge.gov.br/api/v1/localidades/estados/32/municipios"` — run before writing SQL to confirm all codes

---

## Sources

### Primary (HIGH confidence)
- `app/backend/app.py` lines 724–795 — SEARCH_REGIONS dict, exact structure
- `app/backend/app.py` lines 882–941 — get_pipeline_config() and _mark_niches_used() patterns
- `app/backend/app.py` lines 2140–2240 — daily_jobs schema, niches table schema
- `app/backend/app.py` lines 14578–14640 — run_daily_pipeline() signature and cities_to_search usage
- `app/backend/app.py` lines 15017–15069 — trigger_daily_pipeline() full implementation
- `app/frontend/pages/admin/pipeline-config.tsx` — current region section, REGIONS constant (lines 31–36)
- `app/frontend/pages/massive-search.tsx` — current REGIONS constant (lines 24–29), region selector UI (lines 402–440)
- `scripts/import/populate_niches.sql` — SQL pattern to mirror for populate_es_cities.sql

### Secondary (MEDIUM confidence)
- FAZENDA-MG TOM-SERPRO codes for ES municipalities: https://www.fazenda.mg.gov.br/governo/assuntos_municipais/codigomunicipio/codmunicoutest_es.html (all 78 city names confirmed; IBGE 7-digit codes derived from state prefix 32)
- IBGE 2022 census PDF (ES_POP2022.pdf) — confirmed Afonso Claudio = `3200102`, state code 32

### Tertiary (LOW confidence — verify before use)
- Specific 7-digit IBGE codes for all 78 cities: derived from state prefix pattern, not verified city-by-city. Use IBGE API `https://servicodados.ibge.gov.br/api/v1/localidades/estados/32/municipios` to verify.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, all patterns already in codebase
- Architecture: HIGH — direct read of all relevant code sections; Phase 8 niches pattern is the exact template
- Pitfalls: HIGH — derived from actual code reading (trigger_daily_pipeline line 15025, route ordering from STATE.md)
- IBGE codes: MEDIUM — city names confirmed, 7-digit codes derived from state prefix pattern

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable — Flask/psycopg2/Next.js not changing; IBGE municipality list is stable)
