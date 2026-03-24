# Phase 5: Export com Cotas + Niche Request Queue — Research

**Researched:** 2026-03-24
**Domain:** SaaS credit-gated export + user-driven niche request queue (Flask monolith + PostgreSQL)
**Confidence:** HIGH

---

## Summary

Phase 5 adds two revenue and flywheel features on top of the credit ledger and reveal gate already implemented in Phase 4. The first is a credit-gated CSV/JSON export endpoint for client-role users, drawing leads from the shared-batch pool they already browse via `GET /api/leads/search`. The second is a niche request queue: clients submit niches + cities they want, votes aggregate duplicates, and admins approve requests which trigger the existing massive search pipeline.

Both features reuse infrastructure already live in `app.py`: the `credit_ledger` table, `deduct_credit()`, `require_role()`, `_get_plan_limits()`, `_increment_usage()`, `plan_limits.credits_per_month`, and `POST /api/admin/daily-job/run` (niche trigger). No new third-party dependencies are needed. The only new DB object is the `niche_requests` table.

The export feature has one important design decision: credits are debited **after** the file bytes are ready but **inside the same DB transaction** as the export record INSERT. This prevents credit loss on file-generation failure. For the niche queue, the key pattern is vote deduplication — if a matching pending request already exists, increment its vote count rather than creating a new row.

**Primary recommendation:** Implement export as a synchronous endpoint (no async job needed for the MVP volume). Niche requests use a simple vote-aggregation approach with `INSERT ... ON CONFLICT DO UPDATE`. Both features are wired to the existing credit system; no new credit primitives needed.

---

## Standard Stack

### Core (all already installed — no new pip packages required)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg2 | 2.9.x | PostgreSQL driver | Already in requirements.txt |
| Flask | 2.x | HTTP routing | Existing monolith |
| Flask-Limiter | 3.x | Rate limiting | Existing on all endpoints |

### Frontend (all already installed)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Next.js 13.4 | 13.4 | Pages Router, static export | Existing frontend |
| Tailwind CSS | 3.4 | Styling | All new pages |
| Lucide React | latest | Icons | Vote icon, download icon |
| Framer Motion | latest | Page transitions | `_app.tsx` handles automatically |

### New Pip Packages

None required. CSV generation uses Python stdlib `csv` module (already available). JSON export uses stdlib `json`. File delivery uses Flask `Response` with streaming.

**Installation:** nothing to install.

**Version verification:** All packages already in `app/backend/requirements.txt`.

---

## Architecture Patterns

### Recommended Project Structure (additions only)

```
app/
├── backend/
│   └── app.py                 # All new endpoints go here (monolith rule)
└── frontend/
    └── pages/
        ├── portal.tsx         # Add export button + modal to existing portal page
        ├── request-niche.tsx  # NEW: niche request form + vote list
        └── admin/
            └── niche-requests.tsx  # NEW: admin queue view
```

### Pattern 1: Credit-Gated Export (Synchronous, Streaming)

**What:** `GET /api/client/leads/export` fetches leads matching the same filter params as `/api/leads/search`, generates CSV/JSON in memory, debits credits in the same transaction as an export record INSERT, streams file to client.

**When to use:** Synchronous is correct here because the max export size is bounded by credits per plan. A client with 200 credits/month can never trigger a query returning more than 200 rows. Memory footprint is bounded. No async job needed.

**Critical constraint:** Credit deduction and file generation must be inside the same DB transaction. Do NOT deduct credits before the file is ready. Do NOT stream before credits are committed.

**Example — credit-gated export pattern:**
```python
# Source: .planning/research/saas-portal.md — Section 4.2 (adapted)

@app.route('/api/client/leads/export', methods=['GET'])
@limiter.limit("10/hour")
def client_export_leads():
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    fmt = request.args.get('format', 'csv').lower()
    if fmt not in ('csv', 'json'):
        return jsonify({'error': 'format must be csv or json'}), 400

    # Same filter params as /api/leads/search
    # ... (build base_query from args, same WHERE clause)

    with get_db() as conn:
        c = conn.cursor()

        # 1. Count how many leads this query returns
        c.execute(f'SELECT COUNT(*) FROM ({base_query}) _sub', params)
        export_count = c.fetchone()[0]
        if export_count == 0:
            return jsonify({'error': 'no_leads_match', 'count': 0}), 404

        # 2. Cap at plan limit (credits_per_month is the export quota)
        plan = _get_user_plan(user_id)
        limits = _get_plan_limits(plan)
        credits_per_month = limits.get('credits_per_month', 0) if limits else 0
        export_count = min(export_count, credits_per_month)

        # 3. Atomically deduct credits (one per lead exported)
        #    NOTE: deduct_credit() is a 1-credit helper; for bulk we need a variant
        #    Fetch current balance, check sufficiency, deduct in one INSERT
        c.execute(
            'SELECT id, balance_after FROM credit_ledger WHERE user_id = %s ORDER BY id DESC LIMIT 1 FOR UPDATE',
            (user_id,)
        )
        row = c.fetchone()
        balance = row[1] if row else 0
        if balance < export_count and not _is_admin_user(user_id):
            # Export only what they can afford
            export_count = balance
            if export_count == 0:
                return jsonify({'error': 'insufficient_credits', 'balance': 0}), 402

        # 4. Fetch the actual rows (capped)
        paged_query = base_query + ' ORDER BY l.lead_score DESC NULLS LAST LIMIT %s'
        c.execute(paged_query, params + [export_count])
        rows = c.fetchall()
        actual_count = len(rows)

        # 5. Determine revealed leads (exported leads are always fully revealed)
        #    We mark them as revealed so client can re-access without paying again
        lead_ids = [r[0] for r in rows]

        if not _is_admin_user(user_id) and actual_count > 0:
            new_balance = balance - actual_count
            c.execute("""
                INSERT INTO credit_ledger (user_id, amount, operation, ref_id, balance_after)
                VALUES (%s, %s, 'export', NULL, %s)
            """, (user_id, -actual_count, new_balance))
            # Mark all exported leads as revealed (idempotent ON CONFLICT DO NOTHING)
            for lead_id in lead_ids:
                c.execute(
                    'INSERT INTO user_lead_reveals (user_id, lead_id) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                    (user_id, lead_id)
                )

    # 6. Generate file and stream
    if fmt == 'csv':
        # ... generate CSV and return as streaming response
        pass
    else:
        # ... generate JSON and return
        pass
```

**Key constraint from existing codebase:** The existing `deduct_credit()` deducts exactly 1 credit per call. For bulk export (N leads), we need an inline bulk deduction (deduct N in one INSERT) rather than calling `deduct_credit()` N times. The inline pattern is shown above.

### Pattern 2: Niche Request with Vote Deduplication

**What:** `POST /api/client/niche-requests` checks for an existing pending request with the same (niche, city, state). If found, increments `votes` on that row (the requesting user is credited as a voter via a separate `niche_request_votes` table or by checking existing user_id). If not found, creates a new row with votes=1.

**Simplest approach (recommended for MVP):** No separate votes junction table. Use a `votes` integer column on `niche_requests`. Dedup check: ILIKE match on niche+city+state. If match found AND user has not already voted, increment votes. Track "user already voted" by checking if a UNIQUE constraint row (user_id, niche_request_id) exists in a small `niche_request_votes` table.

```sql
-- Two-table approach (recommended):
CREATE TABLE niche_requests (
    id SERIAL PRIMARY KEY,
    requester_user_id INTEGER NOT NULL REFERENCES users(id),
    niche VARCHAR(200) NOT NULL,
    city VARCHAR(100),
    state VARCHAR(2),
    notes TEXT,
    votes INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    admin_notes TEXT,
    leads_added INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE niche_request_votes (
    user_id INTEGER NOT NULL REFERENCES users(id),
    niche_request_id INTEGER NOT NULL REFERENCES niche_requests(id),
    voted_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, niche_request_id)
);
```

**Status transitions:** `pending` → `approved` (admin clicks approve) → `processing` (extraction starts) → `done` (leads added). Or `pending` → `rejected`.

**Admin approve action:** Calls the existing `run_daily_pipeline()` logic with the requested niche+city. The existing `POST /api/admin/daily-job/run` endpoint triggers the massive search. The approve endpoint should set status='processing' and call `threading.Thread(target=_trigger_niche_extraction, args=(niche, city, state, request_id)).start()` — same daemon thread pattern used everywhere in app.py.

### Anti-Patterns to Avoid

- **Deducting credits before file generation:** If CSV generation raises an exception, credits are lost. Always generate bytes first, then deduct inside the same transaction commit.
- **Calling `deduct_credit()` N times in a loop:** Creates N DB round-trips and N ledger rows for a single export. Use a single bulk INSERT to `credit_ledger` with the total count.
- **Creating a new niche_requests row per vote:** Leads to duplicate rows, confuses the admin queue. Always check for existing pending requests before inserting.
- **Async export jobs for small volumes:** No Redis/Celery available on this VPS. Synchronous is correct for the credit-bounded volumes (max 200-1000 leads per export call).
- **Revealing exported leads by calling `/api/leads/reveal/<id>` per row:** Not needed. The export endpoint directly inserts all lead_ids into `user_lead_reveals` as a batch operation.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSV generation | Custom string builder | Python stdlib `csv.writer` | Handles quoting, escaping, Unicode automatically |
| Credit atomicity | Application lock / mutex | `SELECT FOR UPDATE` on `credit_ledger` (already in `deduct_credit()`) | DB-level lock is safe across 2 Gunicorn workers |
| Rate limiting | Custom counter | `@limiter.limit()` (already installed) | Consistent with all existing endpoints |
| Niche dedup logic | Fuzzy string matching | Exact ILIKE SQL check on (niche, city, state) | Simple, fast, no library needed |
| File download | Temp file + file path | Flask `Response(stream_with_context(...))` | No filesystem writes, no cleanup needed |

**Key insight:** The credit system, role checks, plan limits, and DB patterns are already built. Phase 5 is wiring, not infrastructure.

---

## Common Pitfalls

### Pitfall 1: Export Credits Lost on Exception

**What goes wrong:** Code deducts credits (INSERT to credit_ledger), then attempts CSV generation. If CSV raises (e.g., encoding error on a malformed field), credits are consumed but no file is returned.

**Why it happens:** Credits deducted before file is confirmed ready.

**How to avoid:** Generate the file bytes/string in memory FIRST, then open the DB transaction to deduct credits and stream the response. If bytes generation fails, the transaction never opens.

**Warning signs:** Test with a lead that has None values in all fields — the CSV writer must handle None gracefully (write empty string, not the literal "None").

### Pitfall 2: Bulk Credit INSERT vs. N Individual INSERTs

**What goes wrong:** Calling `deduct_credit(conn, user_id, 'export', lead_id)` in a loop over 200 leads creates 200 `credit_ledger` rows and 200 SELECT FOR UPDATE round-trips.

**Why it happens:** `deduct_credit()` was designed for single-lead reveals, not bulk operations.

**How to avoid:** For export, compute `actual_count` first, then do a single `INSERT INTO credit_ledger (..., amount=-actual_count, ...)`. Record operation='export', ref_id=None (no single lead to reference).

**Warning signs:** If you see N ledger rows with operation='export' after a single export, the loop pattern was used.

### Pitfall 3: Export Reveals All Data Without Marking user_lead_reveals

**What goes wrong:** Client exports 50 leads (full contact data returned in CSV). Later they open the portal and see those 50 leads still masked — because `user_lead_reveals` was not populated. They call support.

**Why it happens:** Export and reveal are treated as separate features with no cross-pollination.

**How to avoid:** During export, batch-insert all exported lead IDs into `user_lead_reveals` using `INSERT ... ON CONFLICT DO NOTHING`. One statement with `VALUES` for all IDs (or a loop using executemany).

### Pitfall 4: Niche Request Dedup Race Condition

**What goes wrong:** Two users simultaneously request "Dentista em Curitiba/PR". Both pass the "no existing request" check and both create new rows. Admin sees duplicates.

**Why it happens:** Check-then-insert is not atomic without a transaction lock.

**How to avoid:** Wrap the dedup check and INSERT in a single transaction. Use `SELECT ... FOR UPDATE SKIP LOCKED` on the existing niche_requests row. Or use a UNIQUE constraint on (niche, city, state, status='pending') with `INSERT ... ON CONFLICT DO UPDATE SET votes = niche_requests.votes + 1`.

**Warning signs:** Admin sees two identical pending requests in the queue from the same day.

### Pitfall 5: Export Returns Internal Operator Fields

**What goes wrong:** The export CSV includes `crm_status`, `notes`, `batch_id`, `tags` — fields that belong to the operator, not the client.

**Why it happens:** Reusing the existing admin export query instead of the client-safe `portal_lead_to_dict()` field list.

**How to avoid:** The export SELECT must use the same column list as `GET /api/leads/search` (the 14 columns in `portal_lead_to_dict`). Explicitly list columns — do not use `SELECT *`.

### Pitfall 6: JSON Export Returns Python None as null vs "None"

**What goes wrong:** `json.dumps()` converts Python `None` to JSON `null` (correct), but manually string-formatting a dict converts `None` to the string `"None"` (wrong).

**How to avoid:** Use `json.dumps(list_of_dicts, default=str, ensure_ascii=False)` on the output of `portal_lead_to_dict()`. The `portal_lead_to_dict()` function already handles None→None correctly; just pass its output to json.dumps.

### Pitfall 7: per_page Cap Not Applied to Export

**What goes wrong:** `GET /api/client/leads/export` ignores the credit balance cap and returns 10,000 leads to a user with 10 credits.

**Why it happens:** The LIMIT clause is forgotten in the export query.

**How to avoid:** Export count = `min(query_count, balance, credits_per_month_limit)`. Apply this as the SQL LIMIT before generating the file.

---

## Code Examples

### CSV Streaming Response (Python stdlib)

```python
# Source: Python stdlib docs — csv module + Flask Response
import csv
import io

def _generate_csv_bytes(leads_dicts):
    """Generate CSV bytes from list of lead dicts (output of portal_lead_to_dict).
    Returns bytes object ready for HTTP response.
    """
    output = io.StringIO()
    if not leads_dicts:
        return b''
    fieldnames = [
        'id', 'company_name', 'city', 'state', 'category',
        'email', 'phone', 'whatsapp', 'website', 'cnpj',
        'lead_score', 'quality_grade', 'source', 'captured_at',
        'has_email', 'has_phone', 'has_whatsapp', 'has_website', 'has_cnpj'
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    for lead in leads_dicts:
        # Replace None with '' to avoid "None" strings in CSV
        row = {k: (v if v is not None else '') for k, v in lead.items()}
        writer.writerow(row)
    return output.getvalue().encode('utf-8-sig')  # utf-8-sig adds BOM for Excel compat

# Flask response:
csv_bytes = _generate_csv_bytes(leads)
from flask import Response
return Response(
    csv_bytes,
    mimetype='text/csv',
    headers={'Content-Disposition': f'attachment; filename="leads_{datetime.now().strftime("%Y%m%d")}.csv"'}
)
```

### Bulk user_lead_reveals INSERT (executemany pattern)

```python
# Source: psycopg2 docs — executemany
if lead_ids and not _is_admin_user(user_id):
    conn.cursor().executemany(
        'INSERT INTO user_lead_reveals (user_id, lead_id) VALUES (%s, %s) ON CONFLICT DO NOTHING',
        [(user_id, lid) for lid in lead_ids]
    )
```

### Niche Request — Dedup-or-Vote Pattern

```python
# Source: saas-portal.md Section 5.4 (adapted for this schema)
with get_db() as conn:
    c = conn.cursor()
    # Check for existing pending request (ILIKE = case-insensitive)
    c.execute("""
        SELECT id, votes FROM niche_requests
        WHERE niche ILIKE %s
          AND (city ILIKE %s OR (%s IS NULL AND city IS NULL))
          AND (state ILIKE %s OR (%s IS NULL AND state IS NULL))
          AND status IN ('pending', 'approved')
        ORDER BY created_at DESC LIMIT 1
        FOR UPDATE
    """, (niche, city, city, state, state))
    existing = c.fetchone()

    if existing:
        req_id = existing[0]
        # Check if this user already voted
        c.execute(
            'SELECT 1 FROM niche_request_votes WHERE user_id = %s AND niche_request_id = %s',
            (user_id, req_id)
        )
        if c.fetchone():
            return jsonify({'error': 'already_voted', 'niche_request_id': req_id}), 409
        # Increment votes
        c.execute(
            'UPDATE niche_requests SET votes = votes + 1, updated_at = NOW() WHERE id = %s',
            (req_id,)
        )
        c.execute(
            'INSERT INTO niche_request_votes (user_id, niche_request_id) VALUES (%s, %s)',
            (user_id, req_id)
        )
        return jsonify({'action': 'voted', 'niche_request_id': req_id, 'votes': existing[1] + 1}), 200
    else:
        # Create new request
        c.execute("""
            INSERT INTO niche_requests (requester_user_id, niche, city, state, notes, votes)
            VALUES (%s, %s, %s, %s, %s, 1)
            RETURNING id
        """, (user_id, niche, city, state, notes))
        req_id = c.fetchone()[0]
        c.execute(
            'INSERT INTO niche_request_votes (user_id, niche_request_id) VALUES (%s, %s)',
            (user_id, req_id)
        )
        return jsonify({'action': 'created', 'niche_request_id': req_id, 'votes': 1}), 201
```

### Admin Approve → Trigger Extraction

```python
# Source: existing run_daily_pipeline pattern in app.py
@app.route('/api/admin/niche-requests/<int:req_id>/approve', methods=['POST'])
@require_role('admin')
def admin_approve_niche_request(req_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'SELECT niche, city, state FROM niche_requests WHERE id = %s AND status = %s',
            (req_id, 'pending')
        )
        row = c.fetchone()
        if not row:
            return jsonify({'error': 'not_found_or_not_pending'}), 404
        niche, city, state = row
        c.execute(
            "UPDATE niche_requests SET status = 'processing', updated_at = NOW() WHERE id = %s",
            (req_id,)
        )

    # Trigger extraction in background (same pattern as daily pipeline)
    def _run():
        try:
            # Call massive search with this specific niche/city
            # ... trigger POST /api/search/massive or call run_daily_pipeline() variant
            # On completion, update status='done', leads_added=N
        except Exception as e:
            print(f'[niche_request] Error processing req {req_id}: {e}')
    threading.Thread(target=_run, daemon=True).start()

    return jsonify({'status': 'processing', 'niche_request_id': req_id}), 200
```

### Frontend Export Button Pattern (TypeScript)

```typescript
// Source: existing leads.tsx ExportModal pattern
const handleExport = async (format: 'csv' | 'json') => {
  setExporting(true);
  try {
    const params = new URLSearchParams({ ...filters, format });
    const resp = await fetch(`/api/client/leads/export?${params}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (resp.status === 402) {
      // Insufficient credits — show upgrade prompt
      setShowUpgradeModal(true);
      return;
    }
    if (!resp.ok) throw new Error(await resp.text());
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `leads.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    console.error('Export error', e);
  } finally {
    setExporting(false);
  }
};
```

---

## What Phase 4 Delivered (Phase 5 Depends On)

This section is critical — Phase 5 must NOT re-implement these.

| Already Implemented | Location | Phase 5 Uses It Via |
|---------------------|----------|---------------------|
| `credit_ledger` table | `init_db()` in app.py | Direct INSERT for bulk export deduction |
| `user_lead_reveals` table | `init_db()` in app.py | Batch INSERT after export |
| `deduct_credit(conn, user_id, op, ref_id)` | app.py ~line 2338 | NOT used for bulk; only for single-lead reveals |
| `require_role(minimum_role)` | app.py | `@require_role('client')` on export endpoint |
| `_is_admin_user(user_id)` | app.py ~line 15550 | Admin bypass for credit check |
| `portal_lead_to_dict(row, revealed)` | app.py | Export uses `revealed=True` for all rows |
| `_get_plan_limits(plan_name)` | app.py ~line 15514 | Export uses `credits_per_month` as max export cap |
| `_get_user_plan(user_id)` | app.py | Fetch plan name for limits lookup |
| `plan_limits.credits_per_month` column | Phase 4 migration | Export cap per plan |
| `GET /api/leads/search` shared-batch WHERE clause | app.py | Same WHERE pattern for export query |
| `batches.is_shared = TRUE` filter | app.py | Required in export query JOIN |
| `client_token` fixture | tests/conftest.py | New test files use same fixture |

---

## DB Schema for Phase 5

### New Tables

```sql
-- Niche requests from clients
CREATE TABLE IF NOT EXISTS niche_requests (
    id SERIAL PRIMARY KEY,
    requester_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    niche VARCHAR(200) NOT NULL,
    city VARCHAR(100),
    state VARCHAR(2),
    notes TEXT,
    votes INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- status values: pending, approved, processing, done, rejected
    admin_notes TEXT,
    leads_added INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_niche_requests_status ON niche_requests(status, votes DESC);
CREATE INDEX IF NOT EXISTS idx_niche_requests_user ON niche_requests(requester_user_id);

-- One vote per user per request (prevents double-voting)
CREATE TABLE IF NOT EXISTS niche_request_votes (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    niche_request_id INTEGER NOT NULL REFERENCES niche_requests(id) ON DELETE CASCADE,
    voted_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, niche_request_id)
);
```

### No New Columns on Existing Tables

Phase 4 already added `credits_per_month` to `plan_limits`. Phase 5 reads it but does not modify the schema. The `plan_limits` seed for 'free'=10, 'pro'=200, 'enterprise'=999999 is already applied.

---

## API Endpoints Summary

### Client Endpoints

| Method | Path | Auth | Rate Limit | Description |
|--------|------|------|------------|-------------|
| `GET` | `/api/client/leads/export` | client+ | 10/hour | Export filtered leads as CSV or JSON, debits credits |
| `POST` | `/api/client/niche-requests` | client+ | 5/hour | Submit or vote on a niche request |
| `GET` | `/api/client/niche-requests` | client+ | 30/minute | List own niche requests |

### Admin Endpoints

| Method | Path | Auth | Rate Limit | Description |
|--------|------|------|------------|-------------|
| `GET` | `/api/admin/niche-requests` | admin | 30/minute | All requests sorted by votes desc |
| `POST` | `/api/admin/niche-requests/<id>/approve` | admin | 10/hour | Approve and trigger extraction |
| `POST` | `/api/admin/niche-requests/<id>/reject` | admin | 10/hour | Reject with optional admin_notes |

---

## Frontend Pages Summary

| Page | Route | Role | What It Does |
|------|-------|------|--------------|
| Export button + modal | `/portal` (existing) | client | Add "Exportar" button to portal.tsx, modal shows credit cost + format choice |
| Niche request form | `/request-niche` | client | Form (niche, city, state, notes) + list of popular pending requests with vote counts + "Votar" button |
| Admin niche queue | `/admin/niche-requests` | admin | Table with columns: Nicho, Cidade, Votos, Usuário, Status, Data, Ações (Aprovar/Rejeitar) |

---

## Validation Architecture

`nyquist_validation` is not explicitly set to `false` in `.planning/config.json`, so validation is enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing, `pytest.ini` at project root) |
| Config file | `pytest.ini` |
| Quick run command | `python -m pytest tests/test_export.py tests/test_niche_requests.py -v --tb=short` |
| Full suite command | `python -m pytest tests/ -q --tb=short` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| P5-EXPORT-AUTH | `GET /api/client/leads/export` returns 401 without token | smoke | `pytest tests/test_export.py::test_export_requires_auth -x` | Wave 0 |
| P5-EXPORT-CREDITS | Export debits credits equal to leads returned | integration | `pytest tests/test_export.py::test_export_debits_credits -x` | Wave 0 |
| P5-EXPORT-FORMAT | CSV and JSON formats return correct Content-Type | smoke | `pytest tests/test_export.py::test_export_csv_format -x` | Wave 0 |
| P5-EXPORT-CAP | Export respects plan credit cap (cannot export more than balance) | integration | `pytest tests/test_export.py::test_export_respects_cap -x` | Wave 0 |
| P5-NICHE-CREATE | `POST /api/client/niche-requests` creates a new request | smoke | `pytest tests/test_niche_requests.py::test_niche_request_created -x` | Wave 0 |
| P5-NICHE-VOTE | Second user requesting same niche increments votes (no duplicate row) | integration | `pytest tests/test_niche_requests.py::test_niche_vote_dedup -x` | Wave 0 |
| P5-NICHE-ADMIN-LIST | `GET /api/admin/niche-requests` returns requests sorted by votes | smoke | `pytest tests/test_niche_requests.py::test_admin_niche_list -x` | Wave 0 |
| P5-NICHE-APPROVE | `POST /api/admin/niche-requests/<id>/approve` sets status=processing | smoke | `pytest tests/test_niche_requests.py::test_admin_approve_niche -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_export.py tests/test_niche_requests.py -q --tb=short`
- **Per wave merge:** `python -m pytest tests/ -q --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_export.py` — covers P5-EXPORT-AUTH, P5-EXPORT-CREDITS, P5-EXPORT-FORMAT, P5-EXPORT-CAP (Wave 0 stubs, skip)
- [ ] `tests/test_niche_requests.py` — covers P5-NICHE-CREATE, P5-NICHE-VOTE, P5-NICHE-ADMIN-LIST, P5-NICHE-APPROVE (Wave 0 stubs, skip)

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Async export job (Celery/RQ) | Synchronous streaming export | N/A — no Redis on VPS | Simplicity; bounded by credit quota |
| Separate votes table from requests | `votes` int column + junction table | This phase | Simpler admin queue sorting; junction prevents double-voting |
| Admin triggers scraping via UI | Admin approves → background thread starts | Phase 4 established the pattern | Consistent daemon-thread model |
| Per-lead credit deduction loop | Bulk single-INSERT to credit_ledger | This phase | Fewer DB round-trips; single ledger event for export |

**Deprecated/outdated:**
- `exports_per_month` column on `plan_limits`: still present from the original Milestone 0 schema. Phase 5 uses `credits_per_month` (added in Phase 4) as the export quota. The old `exports_per_month` column and `_increment_usage()` counter are the operator/admin context; Phase 5 client export uses credits. No conflict — just two parallel systems. Planner should note this to avoid confusion.

---

## Open Questions

1. **Export cap: per-call or per-month running total?**
   - What we know: `credits_per_month` on `plan_limits` is the monthly credit grant. Credits are consumed by both reveals and exports. The same `credit_ledger` balance governs both.
   - What's unclear: Should there be a separate monthly export cap (like the old `exports_per_month`), or is the shared credit balance sufficient? The ROADMAP says "1 crédito por lead exportado" — shared balance is the cap.
   - Recommendation: Use the shared `credit_ledger` balance as the only cap. No separate export counter. Consistent with the credit model.

2. **Admin approve action: call run_daily_pipeline() directly or POST to /api/admin/daily-job/run?**
   - What we know: `run_daily_pipeline()` hardcodes niches from `pipeline_config`. The `POST /api/admin/daily-job/run` endpoint also uses pipeline_config. Neither accepts a niche+city parameter.
   - What's unclear: How to trigger extraction for a specific niche+city that may differ from the configured pipeline niches.
   - Recommendation: The approve endpoint should call `process_massive_search_job()` (or its equivalent) directly in a background thread, passing the niche+city from the request. This reuses the existing massive search worker without going through daily-job/run. The planner should map which exact function to call (the massive search function that accepts niche/city parameters).

3. **Free tier niche requests: allowed or not?**
   - What we know: The existing research (saas-portal.md) recommends 0 niche requests per month for Free tier, 1/month for Starter+.
   - What's unclear: There is no `max_niche_requests_per_month` column on `plan_limits` yet.
   - Recommendation: For MVP simplicity, allow all authenticated clients to submit niche requests regardless of plan. Add plan gating in a future phase. The REQUIREMENTS.md does not specify plan-gating on niche requests.

---

## Sources

### Primary (HIGH confidence)

- `.planning/research/saas-portal.md` — Sections 4.2, 4.3, 5.1–5.4 (credit enforcement patterns, niche request schema, vote dedup logic)
- `app/backend/app.py` lines 2204–2281, 15514–15605 — existing plan_limits schema, `_get_plan_limits()`, `_is_admin_user()`, `_increment_usage()` (directly read from codebase)
- `.planning/phases/04-*/04-01-PLAN.md` and `04-02-PLAN.md` — `deduct_credit()`, `portal_lead_to_dict()`, `user_lead_reveals` schema, `credit_ledger` schema (confirmed implemented)
- Python stdlib docs — `csv.DictWriter`, `io.StringIO`, `json.dumps` (standard, no version concern)

### Secondary (MEDIUM confidence)

- Flask docs — `Response()`, streaming responses pattern (well-established, HIGH stability)
- psycopg2 docs — `executemany()` for batch INSERT (used throughout existing codebase)

### Tertiary (LOW confidence)

- None — all patterns verified against live codebase or official stdlib

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all existing
- Architecture: HIGH — verified against Phase 4 implementation in app.py
- Pitfalls: HIGH — derived from existing patterns in codebase (deduct_credit, portal_lead_to_dict)
- DB schema: HIGH — follows exact same migration pattern used in Phases 1-4

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable stack — no third-party packages changing)
