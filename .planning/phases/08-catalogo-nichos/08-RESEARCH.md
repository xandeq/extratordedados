# Phase 8: Catálogo de Nichos - Research

**Researched:** 2026-03-25
**Domain:** PostgreSQL table migration, Flask admin endpoints, Next.js static frontend, round-robin scheduling
**Confidence:** HIGH

## Summary

Phase 8 replaces two hardcoded niche lists with a database-driven catalog: `DAILY_JOB_NICHES` in `app.py` (used by the daily pipeline) and `PREDEFINED_NICHES` in `massive-search.tsx` (used by the admin UI). The work spans a DB migration, a SQL populate script, backend endpoint additions, a modification to `get_pipeline_config()`, and a new frontend admin page plus changes to the massive-search page.

The codebase has a well-established pattern for all three areas: `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for migrations, `@require_role('admin')` (or manual `is_admin` check) for admin endpoints, and `useEffect(() => api.get(...))` for async data loading in the Next.js pages. Phase 8 follows each of these patterns without deviation.

The one migration complexity is the existing `custom_niches` table. Its rows must be migrated into the new `niches` table with `category = 'Outros'` before the old API endpoints can be redirected. The planner must schedule this as a discrete step with a fallback (keep `custom_niches` read endpoints alive until migration is confirmed).

**Primary recommendation:** Implement in three waves — Wave 0: DB + populate script + admin CRUD endpoints; Wave 1: pipeline rotation logic; Wave 2: frontend admin page + massive-search refactor.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Taxonomia (NICHE-01)**
- D-01: 10 categorias em português: `Saúde`, `Beleza & Estética`, `Alimentação`, `Serviços Profissionais`, `Educação`, `Automotivo`, `Varejo & Comércio`, `Construção & Imóveis`, `Tecnologia`, `Turismo & Lazer`
- D-02: Apenas campo `category` — sem `subcategory`. Mantém simples. Subcategoria é futuro.
- D-03: Niches do banco substituem `PREDEFINED_NICHES` hardcoded no frontend. Frontend carrega de `/api/niches?active=true`. Niches antigos da tabela `custom_niches` são migrados para `niches` (categoria = 'Outros').
- D-04: Campo `keywords[]` armazenado no banco mas não usado em Phase 8 para queries. Reservado para Phase 10.

**Rotação do Pipeline (NICHE-02)**
- D-05: Round-robin por `last_used_at ASC NULLS FIRST` — pega os N ativos que foram usados há mais tempo (NULL = nunca, vêm primeiro).
- D-06: Dia 1 (todos NULL): ordenar por `priority ASC, id ASC`.
- D-07: Quantidade 20/dia configurável via chave `daily_niches_per_run` na tabela `pipeline_config` (default 20).
- D-08: Apenas nichos com `active = true` participam da rotação.
- D-09: `get_pipeline_config()` modificado para ler nichos da tabela `niches` (round-robin) em vez da chave `daily_niches` do `pipeline_config`.

**"Selecionar todos" na Busca Massiva (NICHE-04)**
- D-10: "Selecionar todos" seleciona TODOS os nichos ativos do banco. "Desselecionar todos" limpa a seleção.
- D-11: Cap de 50 nichos selecionados na busca massiva (frontend validation). Aviso se ultrapassar.
- D-12: Dois botões separados: `[Selecionar todos]` e `[Limpar seleção]` no header do "Step 1: Select Niches".
- D-13: Frontend carrega nichos de `/api/niches?active=true`. Remove `PREDEFINED_NICHES` hardcoded e localStorage custom niches (tudo no banco). Nichos exibidos agrupados por categoria.

**Página /admin/niches (NICHE-03 + NICHE-04 frontend)**
- D-14: Lista agrupada por categoria — tabs no topo com contadores (ex: "Saúde (18)"). Cada linha: nome, toggle ativo/inativo, campo de prioridade numérico editável.
- D-15: Prioridade editável via input numérico na linha. Salva on-blur. Menor número = maior prioridade.
- D-16: `PUT /api/admin/niches/<id>` toggle individual (active, priority). `PUT /api/admin/niches/bulk` ativar/desativar lote.
- D-17: Link "Catálogo de Nichos" adicionado ao sidebar admin após "Pipeline Config".

**Estrutura do Plano**
- D-18: 1 plano por área — granularidade fina.
- D-19: Cada plano termina com: code review, smoke test, regression test (`pytest tests/ -x`), commit, deploy.

### Claude's Discretion

Not specified — all decisions locked.

### Deferred Ideas (OUT OF SCOPE)

- Subcategorias (ex: Saúde > Clínicas > Odontologia) — Phase 8 tem só category
- Multi-query per niche using keywords[] — Phase 10 (SRC-04)
- Cliente sugere novo nicho via portal — já existe em Phase 5 via niche_requests
- Busca massiva com mais de 50 nichos simultâneos — após validar performance
- Export/import do catálogo de nichos via CSV — futuro
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| NICHE-01 | Tabela `niches` (id, name, category, keywords[], active, priority, last_used_at, created_at) + migrate custom_niches data | DB migration pattern: `CREATE TABLE IF NOT EXISTS` + `INSERT ... ON CONFLICT DO NOTHING`; existing `custom_niches` must be migrated with `category = 'Outros'` |
| NICHE-02 | `get_pipeline_config()` reads active niches from `niches` table via round-robin (last_used_at ASC NULLS FIRST) | `get_pipeline_config()` at line 882 returns `{'niches': [...], ...}`; modify source of niches key; `daily_job_run()` at line 15428 still uses `DAILY_JOB_NICHES` as fallback — must update too |
| NICHE-03 | Script `scripts/import/populate_niches.sql` with 150+ niches across 10 categories | Plain SQL `INSERT ... ON CONFLICT (name) DO NOTHING` pattern; keywords stored as `ARRAY['kw1','kw2']`; ~15 niches per category |
| NICHE-04 | Frontend: "Selecionar todos"/"Limpar seleção" buttons + `/admin/niches` categorized page | `massive-search.tsx` lines 23-86 to replace; new page at `pages/admin/niches.tsx`; Sidebar.tsx `adminNavItems` must add entry |
</phase_requirements>

---

## Standard Stack

### Core (no new packages required)
| Component | Version | Purpose | Status |
|-----------|---------|---------|--------|
| Flask | existing | Backend endpoints | Already deployed |
| psycopg2 | existing | PostgreSQL driver + array type handling | Already in requirements.txt |
| Next.js 13.4 | existing | Frontend pages | Already deployed |
| Tailwind CSS 3.4 | existing | Styling | Already deployed |

**No new pip or npm packages needed for this phase.** The `keywords[]` column uses PostgreSQL native `TEXT[]` array type, which psycopg2 handles with `psycopg2.extensions.register_adapter` (already available) or by passing Python lists directly — psycopg2 auto-adapts `list` to `TEXT[]`.

### PostgreSQL Array Handling (confidence: HIGH — verified against existing codebase)
psycopg2 supports `TEXT[]` natively. Passing a Python `list` as a parameter to a `TEXT[]` column works without extra registration:
```python
cur.execute(
    "INSERT INTO niches (name, category, keywords) VALUES (%s, %s, %s)",
    ("academia", "Saúde", ["academia de musculação", "gym", "fitness"])
)
```
Reading back: psycopg2 returns `TEXT[]` as a Python `list`.

## Architecture Patterns

### Existing Patterns to Follow

**DB Migration in `init_db()`**
```python
# Pattern from lines 2180-2185 (custom_niches) and 2171-2177 (system_logs columns)
c.execute('''CREATE TABLE IF NOT EXISTS niches (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(255) NOT NULL,
    category     VARCHAR(100) NOT NULL DEFAULT 'Outros',
    keywords     TEXT[]       DEFAULT '{}',
    active       BOOLEAN      DEFAULT TRUE,
    priority     INTEGER      DEFAULT 100,
    last_used_at TIMESTAMP,
    created_at   TIMESTAMP    DEFAULT NOW(),
    UNIQUE(name)
)''')
# Migrate existing custom_niches rows:
c.execute('''
    INSERT INTO niches (name, category, created_at)
    SELECT name, 'Outros', created_at FROM custom_niches
    ON CONFLICT (name) DO NOTHING
''')
```

**Admin Endpoint Auth Check Pattern**
```python
# Pattern used consistently throughout app.py
@app.route('/api/admin/niches', methods=['GET'])
@limiter.limit("60/minute")
def admin_get_niches():
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        row = c.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403
        # ... query niches table
```

**Round-Robin Query (D-05, D-06)**
```sql
-- Select next N active niches for pipeline rotation
SELECT name FROM niches
WHERE active = true
ORDER BY last_used_at ASC NULLS FIRST, priority ASC, id ASC
LIMIT %(n)s
```
After selection, update last_used_at for selected niches:
```sql
UPDATE niches SET last_used_at = NOW() WHERE name = ANY(%(names)s)
```

**`get_pipeline_config()` Modification (line 882)**

Current return: `'niches': rows.get('daily_niches', DAILY_JOB_NICHES)`

New return:
```python
# Read N from pipeline_config, then query niches table
n = int(rows.get('daily_niches_per_run', 20))
cur.execute(
    "SELECT name FROM niches WHERE active=true "
    "ORDER BY last_used_at ASC NULLS FIRST, priority ASC, id ASC LIMIT %s",
    (n,)
)
niche_rows = cur.fetchall()
niches = [r[0] for r in niche_rows] if niche_rows else DAILY_JOB_NICHES
# Update last_used_at for selected niches
if niche_rows:
    cur.execute(
        "UPDATE niches SET last_used_at=NOW() WHERE name=ANY(%s)",
        ([r[0] for r in niche_rows],)
    )
conn.commit()
'niches': niches
```

**`daily_job_run()` Fix (line 15428)**

Current: `niches = data.get('niches') or DAILY_JOB_NICHES`

After: `niches = data.get('niches') or get_pipeline_config()['niches']`

This ensures the manual trigger also uses the DB catalog.

**`/api/niches` Public Endpoint (replaces `/api/niches/custom` as data source)**
```python
@app.route('/api/niches', methods=['GET'])
def get_niches():
    """Public: list niches. ?active=true filters to active only. Grouped by category."""
    active_only = request.args.get('active', '').lower() == 'true'
    with get_db() as conn:
        c = conn.cursor()
        if active_only:
            c.execute('SELECT id, name, category, priority FROM niches WHERE active=true ORDER BY category, priority, name')
        else:
            c.execute('SELECT id, name, category, priority, active FROM niches ORDER BY category, priority, name')
        rows = c.fetchall()
    # Group by category
    from collections import defaultdict
    grouped = defaultdict(list)
    for r in rows:
        grouped[r[2]].append({'id': r[0], 'name': r[1], 'priority': r[3]})
    return jsonify({'niches': dict(grouped)}), 200
```

**Frontend: Load Niches from DB (massive-search.tsx)**

Replace the `PREDEFINED_NICHES` constant and `loadLocalNiches()` / `saveLocalNiches()` / `mergeCustomNiches()` infrastructure with a single `useEffect` fetch:

```typescript
// Replace lines 23-86
const [niches, setNiches] = useState<NicheWithCategory[]>([]);
const [loadingNiches, setLoadingNiches] = useState(true);

useEffect(() => {
  api.get('/api/niches?active=true')
    .then(res => {
      const grouped: Record<string, {id: number; name: string}[]> = res.data?.niches || {};
      const flat: NicheWithCategory[] = Object.entries(grouped).flatMap(
        ([category, items]) => items.map(n => ({
          id: String(n.id), name: n.name, category, selected: false
        }))
      );
      setNiches(flat);
    })
    .catch(() => {})
    .finally(() => setLoadingNiches(false));
}, []);
```

**Frontend: `/admin/niches` Page Pattern**

Follow the same tab pattern as `/admin/users` and `/admin/plans`. Use `useEffect` + `api.get('/api/admin/niches')`. Toggle calls `api.put('/api/admin/niches/<id>', {active: !current})`. Priority saves on-blur: `api.put('/api/admin/niches/<id>', {priority: value})`.

**Sidebar.tsx — Add Nav Item (D-17)**

Add to `adminNavItems` array in `app/frontend/components/Sidebar.tsx`:
```typescript
{ href: '/admin/niches', label: 'Catálogo de Nichos', icon: Tag },
```
Position: after the Pipeline Config entry (which currently is NOT in the sidebar array — it must be added to the sidebar). Check: pipeline-config page exists at `pages/admin/pipeline-config.tsx` but the `adminNavItems` in Sidebar.tsx does not currently include it. The planner should add both `/admin/pipeline-config` (if missing) and `/admin/niches` in the correct order. From the current sidebar array, `niche-requests` is already present — add `pipeline-config` before it and `niches` after `pipeline-config`.

**Note on isActive() in Sidebar.tsx (line 193):**
The special-case list for exact matching must include `/admin/niches` to avoid the `/admin` prefix triggering a false active state on the "Painel Admin" link.

### Recommended Project Structure for New Files
```
app/
└── frontend/
    └── pages/
        └── admin/
            └── niches.tsx          # NEW — categorized niche catalog admin page
scripts/
└── import/
    └── populate_niches.sql         # NEW — 150+ niches bulk INSERT
tests/
└── test_niches.py                  # NEW — smoke tests for NICHE-01 to NICHE-04
```

### Anti-Patterns to Avoid

- **Don't DROP or RENAME `custom_niches`**: The table must remain until all existing data is confirmed migrated and `/api/niches/custom` endpoints are backward-compatible.
- **Don't run `UPDATE niches SET last_used_at` inside `trigger_daily_pipeline()`**: The update should happen inside `get_pipeline_config()` so every caller (scheduler + manual) shares the same rotation logic.
- **Don't fetch niches inside the APScheduler callback**: The scheduler calls `trigger_daily_pipeline()` which calls `get_pipeline_config()` — the niche selection already happens there. Don't duplicate.
- **Don't use `ARRAY_AGG` in the admin niches endpoint**: Return rows flat; group in Python. Simpler and consistent with existing patterns.
- **Don't store priority as a float**: Use `INTEGER`. The admin input is a number, Python `int()` cast is sufficient.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Grouping niches by category | Python nested loop | `collections.defaultdict` | One-liner, already used in codebase for similar groupings |
| Array parameter to PostgreSQL | String formatting | psycopg2 list → `TEXT[]` auto-adaptation | Built into psycopg2, safe from injection |
| Round-robin selection | Application-level shuffle | `ORDER BY last_used_at ASC NULLS FIRST` in SQL | Deterministic, DB handles it, survives restarts |
| Bulk toggle endpoint | N individual UPDATE calls | `WHERE id = ANY(%s)` | Single query, atomic |

## Common Pitfalls

### Pitfall 1: Double last_used_at Update
**What goes wrong:** `get_pipeline_config()` is called more than once per pipeline run (e.g., once during `trigger_daily_pipeline()` and once elsewhere), causing the same batch of nichos to get `last_used_at = NOW()` twice and skipping to the NEXT set of nichos.
**Why it happens:** `get_pipeline_config()` has a side effect (UPDATE). Multiple callers don't know about it.
**How to avoid:** Move the `UPDATE last_used_at` into `trigger_daily_pipeline()` AFTER the niche list is confirmed (not inside `get_pipeline_config()`). OR make `get_pipeline_config()` read-only and add a separate `_mark_niches_used(names)` helper called once in `trigger_daily_pipeline()`.
**Warning signs:** Pipeline rotates too fast, same nichos never repeating as expected.

### Pitfall 2: Migration Race on First Boot
**What goes wrong:** `init_db()` runs on app startup. If two Gunicorn workers start simultaneously, both try to `INSERT INTO niches SELECT ... FROM custom_niches` and one fails with a unique constraint violation.
**Why it happens:** Gunicorn 2 workers, both hit `init_db()` concurrently.
**How to avoid:** The `ON CONFLICT (name) DO NOTHING` in the migration INSERT already handles this. No additional guard needed.
**Warning signs:** App startup logs show constraint violation from the migration INSERT.

### Pitfall 3: Frontend Breaks When Niches Table is Empty
**What goes wrong:** On first deploy before `populate_niches.sql` is run, `/api/niches?active=true` returns `{}`. Massive search shows no niches.
**Why it happens:** The SQL populate script must be run AFTER the migration, separately.
**How to avoid:** Wave 0 plan must include "run populate_niches.sql on VPS" as an explicit step. Add a fallback in the frontend: if no niches loaded, show a warning "Nenhum nicho cadastrado — contate o admin."
**Warning signs:** Massive search Step 1 renders empty after deploy.

### Pitfall 4: `daily_job_run()` Still Uses Hardcoded Fallback
**What goes wrong:** Manual pipeline trigger from admin UI still uses `DAILY_JOB_NICHES` (line 15428) because the endpoint has its own fallback: `niches = data.get('niches') or DAILY_JOB_NICHES`.
**Why it happens:** `daily_job_run()` was not updated when `get_pipeline_config()` was modified.
**How to avoid:** Change fallback in `daily_job_run()` to `get_pipeline_config()['niches']`.
**Warning signs:** Manual "Run now" in pipeline-config UI ignores DB nichos.

### Pitfall 5: `keywords` Column Requires `psycopg2` Array Syntax
**What goes wrong:** Passing a Python list to `TEXT[]` column fails if psycopg2 version is old or the list is empty.
**Why it happens:** Empty list `[]` maps to `'{}'::TEXT[]` — psycopg2 may pass it as `ARRAY[]` without type info.
**How to avoid:** In the populate SQL script, use native SQL array literals: `ARRAY['kw1','kw2']` or `'{}'::TEXT[]` for empty. In Python inserts (e.g., via admin API), pass `keywords or []` and let psycopg2 adapt.
**Warning signs:** `ProgrammingError: can't adapt type 'list'` during inserts.

### Pitfall 6: Sidebar `isActive()` Marks "Painel Admin" as Active on /admin/niches
**What goes wrong:** `/admin/niches` URL starts with `/admin`, so the "Painel Admin" link (href=`/admin`) highlights as active.
**Why it happens:** `isActive()` in Sidebar.tsx line 193 uses `router.pathname === href` for exact match — but only for specific hrefs listed in the special-case list. If `/admin/niches` is not added to the list, it falls through to a prefix check.
**How to avoid:** Add `'/admin/niches'` to the exact-match list in `isActive()`.
**Warning signs:** "Painel Admin" nav item appears highlighted when on the /admin/niches page.

## Code Examples

### Round-Robin SQL Pattern
```sql
-- Source: D-05, D-06 from CONTEXT.md
SELECT name FROM niches
WHERE active = true
ORDER BY last_used_at ASC NULLS FIRST, priority ASC, id ASC
LIMIT 20;

-- After selection (run once per pipeline trigger):
UPDATE niches SET last_used_at = NOW()
WHERE name = ANY(ARRAY['restaurante', 'academia', ...]);
```

### Bulk Toggle Pattern
```python
# Source: established pattern from bulk-status endpoints in leads
@app.route('/api/admin/niches/bulk', methods=['PUT'])
def admin_bulk_toggle_niches():
    # ...auth check...
    data = request.get_json() or {}
    ids = data.get('ids', [])
    active = data.get('active', True)
    if not ids:
        return jsonify({'error': 'ids obrigatório'}), 400
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE niches SET active=%s WHERE id=ANY(%s)', (active, ids))
        conn.commit()
    return jsonify({'updated': len(ids), 'active': active}), 200
```

### populate_niches.sql Pattern (150+ entries)
```sql
-- Source: project convention for SQL scripts in scripts/import/
-- Run once on VPS: psql -U extrator -d extrator -f populate_niches.sql

INSERT INTO niches (name, category, priority, keywords) VALUES
-- Saúde (18 nichos)
('Clínica Médica',          'Saúde', 10, ARRAY['clinica medica', 'clínica médica', 'consultorio medico']),
('Clínica Odontológica',    'Saúde', 10, ARRAY['dentista', 'clinica dental', 'odontologia']),
('Clínica Veterinária',     'Saúde', 10, ARRAY['veterinario', 'pet vet', 'clinica veterinaria']),
-- ... continue for all 10 categories
ON CONFLICT (name) DO NOTHING;
```

### Frontend NicheWithCategory Type
```typescript
// In massive-search.tsx — replaces current Niche interface
interface NicheWithCategory {
  id: string;
  name: string;
  category: string;
  selected: boolean;
}
```

### Select All / Clear Selection Buttons
```typescript
// D-12: Two separate buttons, cap 50 with warning (D-11)
const selectAll = () => {
  const allActive = niches.map(n => ({ ...n, selected: true }));
  if (allActive.filter(n => n.selected).length > 50) {
    setWarning('Máximo de 50 nichos por busca para não sobrecarregar o servidor.');
  }
  setNiches(allActive);
};
const clearAll = () => setNiches(niches.map(n => ({ ...n, selected: false })));
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `DAILY_JOB_NICHES` hardcoded list (19 items) | `niches` table with 150+ entries | Phase 8 | Pipeline volume ~8× more diverse |
| `PREDEFINED_NICHES` hardcoded in frontend (10 items) | DB-loaded via `/api/niches?active=true` | Phase 8 | New nichos visible in UI without deploy |
| `custom_niches` + localStorage hybrid | `niches` table (single source of truth) | Phase 8 | Eliminates sync complexity |

**Deprecated after Phase 8:**
- `PREDEFINED_NICHES` constant in `massive-search.tsx`
- `LS_KEY_CUSTOM_NICHES` localStorage key
- `loadLocalNiches()`, `saveLocalNiches()`, `mergeCustomNiches()` functions
- `pipeline_config` key `daily_niches` (replaced by `daily_niches_per_run` + `niches` table)

**Kept for backward compatibility:**
- `/api/niches/custom` GET/POST/DELETE — must continue working (redirected to `niches` table with `category='Outros'`)
- `custom_niches` table — keep in DB, stop writing to it after migration

## Open Questions

1. **Where to run `UPDATE last_used_at` — in `get_pipeline_config()` or `trigger_daily_pipeline()`?**
   - What we know: `get_pipeline_config()` is called by `trigger_daily_pipeline()` AND possibly by the health endpoint. Running UPDATE in `get_pipeline_config()` would advance the rotation on every health check.
   - What's unclear: Does anything other than `trigger_daily_pipeline()` use the `niches` key from `get_pipeline_config()` in a way that should advance rotation?
   - Recommendation: Keep `get_pipeline_config()` read-only (no side effects). Add `_mark_niches_used(names)` helper called explicitly in `trigger_daily_pipeline()` after niches are confirmed.

2. **Should `/api/admin/niches` require admin auth or be accessible to all authenticated users?**
   - What we know: `/api/niches?active=true` is used by the massive-search page (admin-facing but any authenticated user can access it). `/api/admin/niches` is the management endpoint.
   - Recommendation: `/api/niches?active=true` — auth required (any role). `/api/admin/niches` with PUT — admin only.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | `pytest.ini` (root) |
| Quick run command | `pytest tests/test_niches.py -x -v` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NICHE-01 | `GET /api/admin/niches` returns 150+ niches with category and active fields | smoke | `pytest tests/test_niches.py::test_admin_get_niches_returns_catalog -x -v` | Wave 0 |
| NICHE-01 | `PUT /api/admin/niches/<id>` toggles active field | smoke | `pytest tests/test_niches.py::test_admin_toggle_niche_active -x -v` | Wave 0 |
| NICHE-01 | `PUT /api/admin/niches/bulk` updates multiple niches | smoke | `pytest tests/test_niches.py::test_admin_bulk_toggle_niches -x -v` | Wave 0 |
| NICHE-01 | `GET /api/admin/niches` unauthenticated returns 401 | smoke | `pytest tests/test_niches.py::test_admin_niches_requires_auth -x -v` | Wave 0 |
| NICHE-02 | `GET /api/admin/pipeline-config` `niches` key comes from DB (not hardcoded) | smoke | `pytest tests/test_niches.py::test_pipeline_config_niches_from_db -x -v` | Wave 1 |
| NICHE-03 | `GET /api/admin/niches` returns >= 150 niches after populate script | smoke | `pytest tests/test_niches.py::test_niches_catalog_count_gte_150 -x -v` | Wave 0 |
| NICHE-04 | `GET /api/niches?active=true` returns grouped dict keyed by category | smoke | `pytest tests/test_niches.py::test_public_niches_endpoint_grouped -x -v` | Wave 0 |
| NICHE-04 | `GET /api/niches?active=true` returns 10 category keys | smoke | `pytest tests/test_niches.py::test_public_niches_has_10_categories -x -v` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_niches.py -x -v`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_niches.py` — covers all NICHE-01, NICHE-03, NICHE-04 endpoint tests
- [ ] `scripts/import/populate_niches.sql` — must exist and be run on VPS before tests pass

Wave 1 gap:
- [ ] `tests/test_niches.py::test_pipeline_config_niches_from_db` — verifies NICHE-02 (pipeline reads from table)

---

## Sources

### Primary (HIGH confidence)
- `app/backend/app.py` lines 870-906 — `DAILY_JOB_NICHES` and `get_pipeline_config()` exact current implementation
- `app/backend/app.py` lines 2180-2185 — `custom_niches` table schema
- `app/backend/app.py` lines 15207-15270 — existing `/api/niches/custom` endpoints (compatibility surface)
- `app/backend/app.py` lines 15412-15441 — `daily_job_run()` hardcoded fallback
- `app/frontend/pages/massive-search.tsx` lines 23-86 — `PREDEFINED_NICHES` + localStorage code to replace
- `app/frontend/components/Sidebar.tsx` lines 36-43 — `adminNavItems` array

### Secondary (MEDIUM confidence)
- psycopg2 documentation — TEXT[] array handling via Python list auto-adaptation (widely verified behavior)
- `collections.defaultdict` — Python stdlib, no external source needed

### Tertiary (LOW confidence)
- None — all findings based on direct code inspection

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — no new dependencies, all existing
- Architecture: HIGH — patterns read directly from codebase
- Pitfalls: HIGH — pitfalls derived from actual code paths (lines cited)
- Round-robin query: HIGH — SQL pattern from CONTEXT.md specifics section

**Research date:** 2026-03-25
**Valid until:** 2026-06-25 (stable stack, 90-day window)
