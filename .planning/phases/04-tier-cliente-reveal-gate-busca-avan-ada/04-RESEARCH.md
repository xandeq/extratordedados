# Phase 4: Tier Cliente + Reveal Gate + Busca Avançada — Research

**Researched:** 2026-03-23
**Domain:** SaaS credit-per-reveal portal, RBAC, masked data access, PostgreSQL ledger
**Confidence:** HIGH

---

## Summary

Phase 4 transforms the existing operator-facing lead database into a client-facing SaaS portal. The core mechanism is a credit ledger: clients browse a masked view of all leads, spend 1 credit per reveal, and cannot bulk-export without credits.

The existing codebase already has partial SaaS infrastructure — `plan`, `usage_tracking`, `plan_limits` tables, and a `is_admin` boolean for access control — but it lacks the key Phase 4 requirements: a `role` column (to distinguish `client` from `admin`/`operator`), a credit ledger (`credit_ledger` table replacing the simpler usage counting), the reveal endpoint, and the masked response logic. None of these exist yet.

The existing `GET /api/leads` endpoint (the operator view) shows full unmasked data and supports filters for `search`, `status`, `tag`, `batch_id`, `city`, `state`, `quality`, `source`, `min_score`. Phase 4's `GET /api/leads/search` for clients needs to add new boolean filters (`has_email`, `has_phone`, `has_whatsapp`, `has_website`, `has_cnpj`, `category`/nicho) and must return masked responses by default — the reveal endpoint unmasks per-field.

The `SELECT FOR UPDATE` pattern for atomic credit deduction is already documented in `.planning/research/saas-portal.md` with full code examples. The implementation is a straight lift: append-only `credit_ledger` table, lock the latest row with `FOR UPDATE`, insert new row if balance ≥ cost, return HTTP 402 if not.

**Primary recommendation:** Build Phase 4 in 3 waves: (1) DB migrations + role column + credit_ledger + grant scheduler; (2) reveal endpoint + search endpoint with masking; (3) frontend client portal page + plans page update.

---

## Standard Stack

### Core (all already installed on VPS)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask | 2.x (current) | Backend framework | Already in use |
| psycopg2 | 2.x (current) | PostgreSQL driver | Already in use |
| APScheduler | 3.x (current) | Monthly credit grant cron | Already running pipeline scheduler |
| Next.js | 13.4 (current) | Frontend framework | Already in use |
| Tailwind CSS | 3.4 (current) | UI styling | Already in use |
| Framer Motion | current | Page transitions | Already in use |
| Lucide React | current | Icons | Already in use |

### No new packages required
All Phase 4 functionality uses existing dependencies. No `pip install` or `npm install` needed.

---

## Architecture Patterns

### Recommended Project Structure (new additions only)

```
app/backend/app.py              # All new endpoints go here (monolith convention)
app/frontend/pages/
├── portal.tsx                  # New: client-facing lead search (masked)
└── plans.tsx                   # Existing: update with credit-based plan data
app/frontend/components/
├── RevealButton.tsx             # New: "Revelar — 1 crédito" button
├── CreditBalance.tsx            # New: sidebar credit widget
└── LeadDrawerClient.tsx         # New: client version of drawer (no bulk, masked)
tests/
└── test_portal.py               # New: Phase 4 smoke tests
```

### Pattern 1: Append-Only Credit Ledger

**What:** Every credit change is an INSERT (never UPDATE). The last row per user stores the running balance as `balance_after`.
**When to use:** Any time credits are consumed (reveal, future export) or granted (monthly, admin top-up).

```python
# Source: .planning/research/saas-portal.md §4.2 — verified pattern
def deduct_credit(conn, user_id, operation, ref_id=None):
    """
    Atomically deduct 1 credit. Returns (success: bool, new_balance: int).
    Must be called inside an open transaction (conn not committed yet).
    """
    cur = conn.cursor()
    # Lock last ledger row to prevent concurrent overdraft (two-tab race condition)
    cur.execute("""
        SELECT id, balance_after FROM credit_ledger
        WHERE user_id = %s ORDER BY id DESC LIMIT 1
        FOR UPDATE
    """, (user_id,))
    row = cur.fetchone()
    balance = row[1] if row else 0

    if balance < 1:
        return False, balance  # caller returns HTTP 402

    new_balance = balance - 1
    cur.execute("""
        INSERT INTO credit_ledger (user_id, amount, operation, ref_id, balance_after)
        VALUES (%s, -1, %s, %s, %s)
    """, (user_id, operation, ref_id, new_balance))
    return True, new_balance
```

**Key rule:** `deduct_credit()` must be called inside `with conn:` (transaction block). The `FOR UPDATE` lock is only held within the transaction.

### Pattern 2: Masked Response Serialization

**What:** Client-facing endpoints return masked values for sensitive fields. A separate `user_lead_reveals` table tracks what each client has already revealed (so re-opens don't re-charge).

```python
# Email masking: jo***@gmail.com
def mask_email(email):
    if not email:
        return None
    local, domain = email.split('@', 1)
    shown = local[:2] if len(local) >= 2 else local[0]
    return f"{shown}***@{domain}"

# Phone masking: 27 9****-5678
def mask_phone(phone):
    if not phone or len(phone) < 6:
        return None
    return phone[:3] + '****' + phone[-4:]
```

**Check for already-revealed leads before masking:**

```python
def get_revealed_leads(conn, user_id, lead_ids):
    """Return set of lead_ids already revealed by this user."""
    cur = conn.cursor()
    cur.execute(
        "SELECT lead_id FROM user_lead_reveals WHERE user_id = %s AND lead_id = ANY(%s)",
        (user_id, lead_ids)
    )
    return {row[0] for row in cur.fetchall()}
```

### Pattern 3: Role-Based Access (additive to existing is_admin)

**What:** Add `role` column to `users` (`admin`, `operator`, `client`). Existing `is_admin=True` users map to `admin`. All new registrations default to `client`.

**Migration safe pattern** (follows Phase 1-3 ADD COLUMN IF NOT EXISTS convention):

```python
# In init_db() ALTER TABLE section
c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'client'")
# Backfill: existing admins get role='admin'
c.execute("UPDATE users SET role = 'admin' WHERE is_admin = TRUE AND role = 'client'")
```

**Decorator for route guarding:**

```python
ROLE_HIERARCHY = {'admin': 3, 'operator': 2, 'client': 1}

def require_role(minimum_role):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = verify_token(get_auth_header())
            if not user_id:
                return jsonify({'error': 'Unauthorized'}), 401
            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT role FROM users WHERE id = %s', (user_id,))
                row = c.fetchone()
                user_role = row[0] if row else 'client'
            if ROLE_HIERARCHY.get(user_role, 0) < ROLE_HIERARCHY.get(minimum_role, 999):
                return jsonify({'error': 'forbidden', 'required_role': minimum_role}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
```

### Pattern 4: Monthly Credit Grant via APScheduler

**What:** On 1st of month at 00:05, grant each active user their plan's monthly credit allocation by inserting into `credit_ledger`.

```python
# Add to existing scheduler setup (already has pipeline job at 02:00 and crm sync at 09:00)
scheduler.add_job(
    grant_monthly_credits,
    'cron', day=1, hour=0, minute=5,
    id='monthly_credit_grant',
    replace_existing=True,
    timezone=pytz.timezone('America/Sao_Paulo')
)
```

### Anti-Patterns to Avoid

- **Using `UPDATE credit_ledger SET balance`:** Ledger rows are append-only. Never modify an existing row. Only INSERT new events.
- **Checking balance without `FOR UPDATE`:** Without the lock, two concurrent requests can both read balance=1 and both succeed — user gets 2 reveals for 1 credit.
- **Masking in the database view:** Do masking in Python serialization, not in a SQL VIEW. Views complicate queries and cannot be easily toggled per-user-per-reveal.
- **Using existing `usage_tracking` table for credits:** `usage_tracking` counts views/exports but has no balance-after concept and no `FOR UPDATE` semantics. It cannot prevent overdraft. Keep it for plan enforcement on the operator side; use new `credit_ledger` for client credits.
- **Deducting credits in background threads:** Reveal is a synchronous user action. Never defer credit deduction to a background thread — the user must know immediately if they have sufficient balance.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Concurrent credit deduction | Application-level lock (threading.Lock) | PostgreSQL `SELECT FOR UPDATE` | DB transaction handles cross-process concurrency (2 Gunicorn workers) |
| Email masking | Regex from scratch | Simple `split('@')` + string slice | No edge cases for valid email format (email already validated by Phase 2) |
| Monthly reset scheduling | Custom cron daemon | APScheduler (already installed) | Already scheduling pipeline at 02:00; add `day=1` job to same scheduler |
| Plan feature lookup | Hard-coded `if plan == 'pro'` | `plan_limits` table (already exists) | Already seeded with free/pro/enterprise; add `credits_per_month` column |
| Role checking | `is_admin` boolean check everywhere | `require_role()` decorator | Centralizes RBAC, avoids scattered `if is_admin` patterns |

**Key insight:** The existing codebase has 40+ instances of `SELECT is_admin FROM users WHERE id = %s` inline in routes. Phase 4 should introduce `require_role()` decorator to avoid adding more inline checks, but does NOT need to refactor the existing pattern — only new Phase 4 routes use the decorator.

---

## Codebase State — What Exists vs. What's Needed

### Users Table (current state)
```sql
-- Current columns in users table:
id SERIAL PRIMARY KEY
username VARCHAR(100) UNIQUE NOT NULL
password_hash VARCHAR(64) NOT NULL
is_admin BOOLEAN DEFAULT FALSE
plan VARCHAR(20) DEFAULT 'free'   -- 'free', 'pro', 'enterprise'
created_at TIMESTAMP DEFAULT NOW()
```
**Phase 4 needs:** `role VARCHAR(20) DEFAULT 'client'` column added via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

### Plan System (current state)
- `plan_limits` table exists with columns: `plan_name`, `leads_per_month`, `exports_per_month`, `price_monthly`, `features JSONB`
- Seeded with: `free` (100 leads/mo, 1 export), `pro` (5000 leads/mo, 20 exports, R$99), `enterprise` (unlimited)
- `usage_tracking` table: tracks `leads_viewed`, `leads_exported` per user per month
- **Phase 4 needs:** Add `credits_per_month INTEGER` column to `plan_limits`. Seed values: free=10, basico=200, pro=1000, enterprise=999999.

### Current plans.tsx (current state)
- Static hardcoded plan display (Free, Pro, Enterprise)
- No credit concept, no credit balance display
- CTAs are mailto links (no Stripe)
- **Phase 4 needs:** Update to show credit amounts per plan. Add credit balance widget. Keep mailto CTAs (Stripe is out of scope).

### Current GET /api/leads (current state)
Supports: `search`, `status`, `tag`, `batch_id`, `city`, `state`, `quality`, `source`, `min_score`, `sort`, `page`, `per_page`.
Returns: full unmasked data including `email`, `phone`, `whatsapp`, etc.
Uses `SHARED_LEADS_SELECT` which joins `leads` with `batches WHERE is_shared = TRUE`.
**Phase 4 needs:** New `GET /api/leads/search` endpoint for clients with:
- New filters: `category`, `has_email`, `has_phone`, `has_whatsapp`, `has_website`, `has_cnpj`
- Masked response by default (email → `jo***@gmail.com`)
- Check `user_lead_reveals` to show unmasked if already revealed
- Rate limit: 100 req/hour for clients

### Current verify_token() (current state)
Returns `user_id` (integer) only — NOT role or plan. All routes that need role info do a second query.
**Phase 4 impact:** Continue the same pattern. `require_role()` decorator does its own role query. No need to change `verify_token()`.

### Current Sidebar.tsx (current state)
Uses `GET /api/me` → checks `response.data.is_admin` to switch between `clientNavItems` and `adminNavItems`.
Client nav: Dashboard, Leads, Planos.
**Phase 4 needs:** Add "Portal" item to `clientNavItems` (the new masked client search page). Add credit balance widget to sidebar (alongside existing usage meter).

### Current /api/me (current state)
Returns: `{ id, username, is_admin, plan }`.
**Phase 4 needs:** Add `role` to response once column exists. Frontend can use `role === 'client'` for UI branching.

---

## DB Schema — New Tables for Phase 4

### credit_ledger
```sql
CREATE TABLE IF NOT EXISTS credit_ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,              -- positive = credit added, negative = consumed
    operation VARCHAR(30) NOT NULL,       -- 'monthly_grant', 'reveal', 'admin_grant'
    ref_id INTEGER,                       -- lead_id for 'reveal' ops
    balance_after INTEGER NOT NULL,       -- denormalized: current balance after this event
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_credit_ledger_user ON credit_ledger(user_id, id DESC);
```

### user_lead_reveals
```sql
CREATE TABLE IF NOT EXISTS user_lead_reveals (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    revealed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, lead_id)
);
```

**Naming note:** The ROADMAP and REQUIREMENTS use `credit_ledger` as the table name. The existing `.planning/research/saas-portal.md` uses `credit_events` as an alternative name. Use `credit_ledger` to match the spec.

---

## Common Pitfalls

### Pitfall 1: Double-Charge on Re-Open
**What goes wrong:** User opens lead drawer (1 credit deducted), closes it, reopens — charged again.
**Why it happens:** Reveal endpoint doesn't check if user already paid for this lead.
**How to avoid:** Before deducting, check `user_lead_reveals`. If row exists, return full data without charging. Insert into `user_lead_reveals` only on first reveal.
**Warning signs:** User complains credits drop 2x for same lead; `credit_ledger` shows multiple 'reveal' rows for same `(user_id, ref_id)` pair.

### Pitfall 2: Race Condition on Concurrent Reveals
**What goes wrong:** User has 1 credit, opens two tabs, clicks Revelar simultaneously in both — both succeed, balance goes to -1.
**Why it happens:** Both requests read `balance=1` before either inserts the deduction row.
**How to avoid:** `SELECT FOR UPDATE` on `credit_ledger` (locks the row until transaction commits). This serializes concurrent deductions for the same user.
**Warning signs:** `balance_after` goes negative in `credit_ledger`.

### Pitfall 3: init_db Transaction Bug (learned from Phase 3)
**What goes wrong:** `ALTER TABLE users ADD COLUMN IF NOT EXISTS role ...` inside a multi-column ADD COLUMN loop fails silently if inside a transaction that already has an error.
**Why it happens:** psycopg2 silently aborts statements after a transaction error without explicit `ROLLBACK`.
**How to avoid:** Follow Phase 3 fix: each `ADD COLUMN IF NOT EXISTS` is in its own `try/except` block with `conn.rollback()` on exception. This is already the pattern in `init_db()`.

### Pitfall 4: is_admin vs role Inconsistency
**What goes wrong:** `is_admin=True` but `role='client'` (or vice versa) after migration — admin user can't access admin routes.
**Why it happens:** Backfill SQL runs but new users created before migration get `role='client'` even if `is_admin=True`.
**How to avoid:** Backfill SQL `UPDATE users SET role='admin' WHERE is_admin=TRUE` in init_db. Add logic to `require_role()` to also accept `is_admin=True` as equivalent to `role='admin'` for backward compat.
**Warning signs:** Admin user gets 403 on admin endpoints after migration.

### Pitfall 5: Client Accessing Internal Fields
**What goes wrong:** `GET /api/leads/search` returns `crm_status`, `batch_name`, `batch_id`, `notes` — internal operator fields that clients should not see.
**Why it happens:** Reusing `lead_row_to_dict()` or `SHARED_LEADS_SELECT` unchanged.
**How to avoid:** Create a separate `portal_lead_to_dict()` serializer that only exposes: `id`, `company_name`, `city`, `state`, `category`, `lead_score`, `quality_grade`, `source`, `captured_at`, `has_email`, `has_phone`, `has_whatsapp`, `has_website`, `has_cnpj` — plus masked values or revealed values depending on `user_lead_reveals`.

### Pitfall 6: plan_limits Not Having credits_per_month
**What goes wrong:** `grant_monthly_credits()` tries to read `credits_per_month` from `plan_limits` but column doesn't exist — APScheduler job crashes silently.
**Why it happens:** Forgot to add column before seeding the grant scheduler.
**How to avoid:** Add `ALTER TABLE plan_limits ADD COLUMN IF NOT EXISTS credits_per_month INTEGER DEFAULT 0` in init_db, then seed values before the scheduler starts.

### Pitfall 7: APScheduler Double-Fire (learned from Phase 1)
**What goes wrong:** Monthly credit grant fires twice at midnight on 1st because Gunicorn has 2 workers.
**Why it happens:** Both workers start their own APScheduler instance.
**How to avoid:** Same pattern as pipeline guard: check `credit_ledger` for a `monthly_grant` event in the last 5 minutes for any user before inserting. If found, skip the run. Add a `UNIQUE(user_id, DATE_TRUNC('month', created_at))` partial index or a simple guard query.

---

## Code Examples

### Reveal Endpoint

```python
# Source: pattern derived from saas-portal.md §4.2 + existing Flask patterns in app.py
@app.route('/api/leads/reveal/<int:lead_id>', methods=['POST'])
@limiter.limit("60/hour")
def reveal_lead(lead_id):
    """Reveal full contact details for a lead. Costs 1 credit. Free if already revealed."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()

        # Check if already revealed (no double-charge)
        c.execute(
            'SELECT 1 FROM user_lead_reveals WHERE user_id = %s AND lead_id = %s',
            (user_id, lead_id)
        )
        already_revealed = c.fetchone() is not None

        if not already_revealed:
            # Atomically deduct 1 credit (SELECT FOR UPDATE inside with conn: block)
            success, new_balance = deduct_credit(conn, user_id, 'reveal', lead_id)
            if not success:
                return jsonify({
                    'error': 'insufficient_credits',
                    'balance': new_balance,
                    'required': 1
                }), 402
            # Record the reveal
            c.execute(
                'INSERT INTO user_lead_reveals (user_id, lead_id) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                (user_id, lead_id)
            )
        else:
            # Fetch current balance without deducting
            c.execute(
                'SELECT balance_after FROM credit_ledger WHERE user_id = %s ORDER BY id DESC LIMIT 1',
                (user_id,)
            )
            row = c.fetchone()
            new_balance = row[0] if row else 0

        # Fetch full lead data
        c.execute('SELECT email, phone, whatsapp FROM leads WHERE id = %s', (lead_id,))
        row = c.fetchone()
        if not row:
            return jsonify({'error': 'lead_not_found'}), 404

        return jsonify({
            'lead_id': lead_id,
            'email': row[0],
            'phone': row[1],
            'whatsapp': row[2],
            'credits_remaining': new_balance,
            'already_revealed': already_revealed
        }), 200
```

### Client Credits Endpoint

```python
@app.route('/api/client/credits', methods=['GET'])
@limiter.limit("30/minute")
def client_credits():
    """Get client's credit balance and recent history."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()
        # Current balance (last event)
        c.execute(
            'SELECT balance_after FROM credit_ledger WHERE user_id = %s ORDER BY id DESC LIMIT 1',
            (user_id,)
        )
        row = c.fetchone()
        balance = row[0] if row else 0

        # Recent history (last 20 events)
        c.execute("""
            SELECT amount, operation, ref_id, balance_after, created_at
            FROM credit_ledger
            WHERE user_id = %s
            ORDER BY id DESC LIMIT 20
        """, (user_id,))
        history = [
            {'amount': r[0], 'operation': r[1], 'ref_id': r[2],
             'balance_after': r[3], 'created_at': r[4].isoformat()}
            for r in c.fetchall()
        ]

    return jsonify({'balance': balance, 'history': history}), 200
```

### Search Endpoint with Masking

```python
@app.route('/api/leads/search', methods=['GET'])
@limiter.limit("100/hour")
def client_search_leads():
    """Client-facing lead search. Returns masked data by default."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    # Parse client-specific filters
    category = request.args.get('category', '').strip()
    city = request.args.get('city', '').strip()
    state = request.args.get('state', '').strip()
    quality_grade = request.args.get('quality_grade', '').strip()  # min grade A/B/C/D/F
    has_email = request.args.get('has_email', '').lower() == 'true'
    has_phone = request.args.get('has_phone', '').lower() == 'true'
    has_whatsapp = request.args.get('has_whatsapp', '').lower() == 'true'
    has_website = request.args.get('has_website', '').lower() == 'true'
    has_cnpj = request.args.get('has_cnpj', '').lower() == 'true'
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(50, max(10, int(request.args.get('per_page', 20))))

    query = """
        SELECT l.id, l.company_name, l.city, l.state, l.category,
               l.email, l.phone, l.whatsapp, l.website, l.cnpj,
               l.lead_score, l.quality_grade, l.source, l.captured_at
        FROM leads l JOIN batches b ON l.batch_id = b.id
        WHERE b.is_shared = TRUE
    """
    params = []

    if category:
        query += ' AND l.category ILIKE %s'
        params.append(f'%{category}%')
    if city:
        query += ' AND l.city ILIKE %s'
        params.append(f'%{city}%')
    if state:
        query += ' AND l.state ILIKE %s'
        params.append(f'%{state}%')
    if quality_grade in ('A', 'B', 'C', 'D', 'F'):
        # Return leads at or better than requested grade (A > B > C > D > F)
        grade_order = {'A': 1, 'B': 2, 'C': 3, 'D': 4, 'F': 5}
        min_order = grade_order[quality_grade]
        allowed_grades = [g for g, o in grade_order.items() if o <= min_order]
        query += f" AND l.quality_grade = ANY(%s)"
        params.append(allowed_grades)
    if has_email:
        query += ' AND l.email IS NOT NULL AND l.email != %s'
        params.append('')
    if has_phone:
        query += ' AND l.phone IS NOT NULL AND l.phone != %s'
        params.append('')
    if has_whatsapp:
        query += ' AND l.whatsapp IS NOT NULL AND l.whatsapp != %s'
        params.append('')
    if has_website:
        query += ' AND l.website IS NOT NULL AND l.website != %s'
        params.append('')
    if has_cnpj:
        query += ' AND l.cnpj IS NOT NULL AND l.cnpj != %s'
        params.append('')

    with get_db() as conn:
        c = conn.cursor()
        # Count
        c.execute(f'SELECT COUNT(*) FROM ({query}) sub', params)
        total = c.fetchone()[0]

        # Fetch page
        query += ' ORDER BY l.lead_score DESC NULLS LAST LIMIT %s OFFSET %s'
        params.extend([per_page, (page - 1) * per_page])
        c.execute(query, params)
        rows = c.fetchall()

        # Get already-revealed leads for this user
        lead_ids = [row[0] for row in rows]
        revealed = set()
        if lead_ids:
            c.execute(
                'SELECT lead_id FROM user_lead_reveals WHERE user_id = %s AND lead_id = ANY(%s)',
                (user_id, lead_ids)
            )
            revealed = {r[0] for r in c.fetchall()}

    leads = []
    for row in rows:
        lead_id = row[0]
        is_revealed = lead_id in revealed
        leads.append({
            'id': lead_id,
            'company_name': row[1],
            'city': row[2],
            'state': row[3],
            'category': row[4],
            'email': row[5] if is_revealed else mask_email(row[5]),
            'phone': row[6] if is_revealed else mask_phone(row[6]),
            'whatsapp': row[7] if is_revealed else mask_phone(row[7]),
            'website': row[8],   # website not gated (not sensitive)
            'cnpj': row[9] if is_revealed else (row[9][:4] + '****' if row[9] else None),
            'lead_score': row[10],
            'quality_grade': row[11],
            'source': row[12],
            'captured_at': row[13].isoformat() if row[13] else None,
            'has_email': row[5] is not None,
            'has_phone': row[6] is not None,
            'has_whatsapp': row[7] is not None,
            'has_website': row[8] is not None,
            'has_cnpj': row[9] is not None,
            'revealed': is_revealed,
        })

    return jsonify({'leads': leads, 'total': total, 'page': page, 'per_page': per_page}), 200
```

### Frontend: useClientCredits hook

```typescript
// app/frontend/lib/useClientCredits.ts
import { useState, useEffect, useCallback } from 'react'
import api from './api'

interface CreditEvent {
  amount: number
  operation: string
  ref_id: number | null
  balance_after: number
  created_at: string
}

interface UseClientCreditsReturn {
  balance: number | null
  history: CreditEvent[]
  loading: boolean
  refetch: () => Promise<void>
}

export const useClientCredits = (): UseClientCreditsReturn => {
  const [balance, setBalance] = useState<number | null>(null)
  const [history, setHistory] = useState<CreditEvent[]>([])
  const [loading, setLoading] = useState(true)

  const fetchCredits = useCallback(async () => {
    try {
      const res = await api.get('/api/client/credits')
      setBalance(res.data.balance)
      setHistory(res.data.history)
    } catch {
      // silently fail — balance stays null
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchCredits()
  }, [fetchCredits])

  return { balance, history, loading, refetch: fetchCredits }
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `is_admin` boolean for access control | `role` column with RBAC hierarchy | Phase 4 (this phase) | Supports 3-tier access: admin > operator > client |
| `usage_tracking` table for usage counting | `credit_ledger` append-only table | Phase 4 (this phase) | Atomic credit deduction, race-condition safe |
| Operator-only `/api/leads` with full data | Client-facing `/api/leads/search` with masking | Phase 4 (this phase) | Clients see masked data; reveal gate monetizes |
| Static hardcoded plan limits | `plan_limits` table with `credits_per_month` | Phase 4 (additive) | Admin can update credit allotments without code change |

**Deprecated/outdated for Phase 4:**
- Inline `SELECT is_admin FROM users WHERE id = %s` in routes: still valid for existing admin routes (don't refactor), but new client routes use `require_role()` decorator.

---

## Open Questions

1. **Enterprise plan credit count**
   - What we know: Spec says "Enterprise (ilimitado)". Database `plan_limits` has `enterprise` seeded with 999999 leads/month.
   - What's unclear: Should `credits_per_month` for Enterprise be 999999 (a large number) or handled with a special `is_unlimited` flag?
   - Recommendation: Use 999999 (consistent with existing `leads_per_month` pattern). `balance_after >= 999999` can be treated as unlimited in the UI.

2. **Admin/operator credit bypass**
   - What we know: Admins currently bypass `usage_tracking` limits via `_is_admin_user()`.
   - What's unclear: Should admins be exempt from credit system entirely, or have separate unlimited balance?
   - Recommendation: Exempt admins from reveal credit checks entirely (add `if _is_admin_user(user_id): return full_data` before credit check in reveal endpoint). They are operators, not clients.

3. **Existing /api/leads endpoint for clients**
   - What we know: Current `GET /api/leads` shows full unmasked data to all authenticated users (no role check).
   - What's unclear: Should `/api/leads` be restricted to admin/operator once `/api/leads/search` exists for clients?
   - Recommendation: Keep `/api/leads` unchanged for backward compat (operators/admins use it). Add new `/api/leads/search` for clients. Do NOT remove or restrict the old endpoint in this phase.

4. **Plan name alignment**
   - What we know: Existing DB has plans `free`, `pro`, `enterprise`. The ROADMAP spec says `Free(10cr/mês), Básico(200), Pro(1000), Enterprise(ilimitado)`. The research doc says `Free`, `Starter`, `Pro`, `Business`.
   - What's unclear: Does adding "Básico" require a new row in `plan_limits`, or should the existing `free/pro/enterprise` trio map directly?
   - Recommendation: Keep existing 3 plan names (`free`, `pro`, `enterprise`) and update `credits_per_month` for each. Adding "Básico" as a 4th plan is a future concern. Map: free=10, pro=200, enterprise=999999. (Planner should confirm this with product owner if needed.)

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (configured in `pytest.ini`) |
| Config file | `pytest.ini` at project root |
| Quick run command | `pytest tests/test_portal.py -v --tb=short` |
| Full suite command | `pytest tests/ -v --tb=short` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| P4-01 | `POST /api/leads/reveal/<id>` returns 401 without token | smoke | `pytest tests/test_portal.py::test_reveal_requires_auth -x` | Wave 0 |
| P4-02 | `POST /api/leads/reveal/<id>` returns 402 when balance=0 | smoke | `pytest tests/test_portal.py::test_reveal_insufficient_credits -x` | Wave 0 |
| P4-03 | `POST /api/leads/reveal/<id>` deducts 1 credit and returns email | smoke | `pytest tests/test_portal.py::test_reveal_success_deducts_credit -x` | Wave 0 |
| P4-04 | Re-revealing same lead does NOT deduct second credit | smoke | `pytest tests/test_portal.py::test_reveal_idempotent -x` | Wave 0 |
| P4-05 | `GET /api/client/credits` returns balance and history | smoke | `pytest tests/test_portal.py::test_credits_endpoint -x` | Wave 0 |
| P4-06 | `GET /api/leads/search` returns masked email for client | smoke | `pytest tests/test_portal.py::test_search_returns_masked_email -x` | Wave 0 |
| P4-07 | `GET /api/leads/search` filters by `has_email=true` | smoke | `pytest tests/test_portal.py::test_search_has_email_filter -x` | Wave 0 |
| P4-08 | `GET /api/leads/search` filters by `category` | smoke | `pytest tests/test_portal.py::test_search_category_filter -x` | Wave 0 |
| P4-09 | `GET /api/leads/search` without token returns 401 | smoke | `pytest tests/test_portal.py::test_search_requires_auth -x` | Wave 0 |
| P4-10 | Monthly credit grant inserts row in `credit_ledger` | smoke | `pytest tests/test_portal.py::test_monthly_grant_inserts_ledger -x` | Wave 0 |
| P4-11 | `role` column exists on `users` table | smoke | `pytest tests/test_portal.py::test_role_column_exists -x` | Wave 0 |
| P4-12 | Admin user bypasses credit check on reveal | smoke | `pytest tests/test_portal.py::test_admin_reveal_no_credit_deduction -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_portal.py -v --tb=short`
- **Per wave merge:** `pytest tests/ -v --tb=short`
- **Phase gate:** Full suite (48 existing + new portal tests) green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_portal.py` — covers P4-01 through P4-12 (all 12 tests)
- [ ] `tests/conftest.py` update — add `client_token` fixture (creates a test user with `role='client'` and grants seed credits)

*(Existing test infrastructure — pytest.ini, conftest.py base, AWS SM credential loading — is already in place. Only new test file and conftest fixture needed.)*

---

## Sources

### Primary (HIGH confidence)
- `app/backend/app.py` — direct code inspection of `verify_token()`, `init_db()`, `SHARED_LEADS_SELECT`, `_get_user_plan()`, `_get_plan_limits()`, `client_usage()`, existing schema
- `.planning/research/saas-portal.md` — credit ledger pattern, `SELECT FOR UPDATE`, RBAC decorator, masking pattern (all verified against codebase patterns)
- `app/frontend/components/Sidebar.tsx` — current `is_admin` check, nav structure
- `app/frontend/pages/plans.tsx` — current plan page structure
- `app/frontend/lib/useClientPlan.ts` — existing plan hook pattern to extend

### Secondary (MEDIUM confidence)
- `.planning/REQUIREMENTS.md` — Phase 4 requirements (Fase 4 section)
- `.planning/ROADMAP.md` — scope and out-of-scope decisions

### Tertiary (LOW confidence — no verification needed)
- PostgreSQL documentation for `SELECT FOR UPDATE` behavior — well-established, no verification required

---

## Metadata

**Confidence breakdown:**
- DB schema (what exists): HIGH — direct code inspection
- Credit ledger pattern: HIGH — already in research doc + matches existing Flask patterns
- Masking functions: HIGH — trivial string operations, verified approach
- Frontend patterns: HIGH — inspected Sidebar.tsx, useClientPlan.ts, _app.tsx
- APScheduler monthly grant: HIGH — already running same pattern for pipeline/crm jobs

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (30 days — stable stack)
