# Research: SaaS Lead Database Portal — Multi-tenant Access, Pricing & UX Patterns

**Domain:** B2B Lead Database SaaS Portal (client-facing, search + export only)
**Researched:** 2026-03-22
**Overall confidence:** HIGH (pricing verified via multiple sources; UX patterns from direct product documentation)

---

## 1. Competitive Pricing Landscape

### Apollo.io — Reference Benchmark

Apollo is the most relevant comparison because it runs the exact same model: aggregate a giant database, gate access by plan.

| Plan | Price | Email Credits | Phone Credits | Export Credits |
|------|-------|---------------|---------------|----------------|
| Free | $0 | ~250/day (fair use) | 5/month | 10/month |
| Basic | $49/user/mo (annual) | Plan-proportional | 75/month | 75/month |
| Professional | $79/user/mo | More | 150/month | 150/month |
| Organization | $119/user/mo | Most | 300/month | Custom |

Key decisions Apollo made that we should copy:
- **Credits do not roll over** — forces habit formation, prevents stockpiling and churning
- **Free tier exists and is usable** — removes signup friction, creates upgrade pressure organically
- **Phone reveals cost 8x more credits than emails** — phone is scarce/valuable, priced accordingly
- **Overage at $0.20/credit** — monetizes power users who blow their quota rather than locking them out

### Hunter.io — Domain Search Model

Hunter positions around email-finding for a single domain. Not directly comparable, but their free tier teaches us about minimums:
- Free: 25 searches/month + 50 verifications — no export, no bulk, no campaigns
- Paid starts at $34/month for 500 credits

Lesson: **25 searches is enough to get value but not enough to run a real campaign.** Design the free tier to hit that sweet spot.

### Lusha — Per-Reveal Credit Model

Lusha's model is pure per-contact reveal:
- Free: 40 credits/month (1 credit = 1 email reveal, 5 credits = 1 phone reveal)
- Pro: ~$22.45/month (annual) for 3,000 credits/year across 3 seats
- Premium: ~$52.45/month for 7,200 credits/year

Key insight: **Lusha prices phone numbers at 5x emails.** This is the right ratio because phone/WhatsApp data is genuinely harder to obtain and more valuable for Brazilian market outreach.

### Kaspr — European Competitor

Kaspr Business: 2,400 credits for €79/month.
Lusha Business equivalent: 960 credits for the same €79.

Kaspr competes on volume — Lusha competes on accuracy. For a Brazilian market niche portal, accuracy matters more than raw volume.

### Snov.io — Rollover-Friendly Credits

Snov.io allows unused credits to roll over as long as the subscription is active. This is a meaningful differentiator — customers feel less stressed about "losing" credits at month end. Consider this for higher tiers.

### ZoomInfo — Enterprise Anchor

ZoomInfo: $14,995-$40,000/year. Enterprise-only, irrelevant for our pricing, but relevant for positioning — we are "ZoomInfo for Brasil SMBs, at SMB prices."

---

## 2. Recommended Pricing Model for This Portal

Given the stack (Flask/Postgres/VPS), the market (Brazilian SMBs), and the data (leads with email, WhatsApp, CNPJ, site), here is the recommended structure.

### Plan Architecture

**Currency of value: "lead credits"**
- 1 credit = viewing full details of 1 lead (reveals phone/WhatsApp/email when gated)
- 1 credit = exporting 1 lead to CSV/JSON
- Searching and previewing (blurred/partial data) is FREE and unlimited

This matches industry standard and creates the "try before you buy" moment naturally.

### Recommended Tiers

| Plan | Price (BRL) | Credits/month | Leads visible | Export formats | Saved searches | Niche requests |
|------|-------------|---------------|---------------|----------------|----------------|----------------|
| **Free** | R$0 | 20 | Preview only (blurred phone/WhatsApp) | None | 0 | 0 |
| **Starter** | R$47/mo | 200 | Full | CSV | 3 | 1/month |
| **Pro** | R$97/mo | 700 | Full | CSV + JSON | 10 | 3/month |
| **Business** | R$197/mo | 2,000 | Full + bulk | CSV + JSON + marketing export | Unlimited | 10/month |

Pricing rationale:
- R$47 is the Brazilian psychological "it's cheap enough to try" threshold for SMB SaaS
- Credit costs at R$47 = R$0.235/credit. At R$197, R$0.0985/credit — volume discount is built in
- Niche requests on Starter are 1/month so users feel the value immediately but upgrade for more

### Credit Rules

1. **Credits reset monthly** — no rollover on Free/Starter (creates urgency)
2. **Pro and Business get 30-day rollover** up to 1.5x their monthly limit — reduces anxiety for irregular users
3. **Export consumes credits at export time**, not at search time — search is always free
4. **Bulk export** (>50 leads at once) is Pro+ feature
5. **Overage purchases**: R$29 for 100 extra credits (available to all paid plans, not Free)

---

## 3. UX Patterns for Lead Search Portal

### 3.1 Filter Architecture

**Use a persistent left sidebar with grouped facets** — not a top-bar filter. Apollo, ZoomInfo, and LinkedIn Sales Navigator all use this pattern for one reason: filters are the product, not an afterthought.

Recommended filter groups for this portal:

```
LOCALIZAÇÃO
  Estado [dropdown multi-select]
  Cidade [typeahead multi-select]
  Região [dropdown: Grande Vitória, Grande SP, ...]

NEGÓCIO
  Nicho/Categoria [typeahead multi-select]
  CNPJ Disponível [toggle]
  Site Disponível [toggle]

CONTATO
  Tem Email [toggle]
  Tem Telefone [toggle]
  Tem WhatsApp [toggle]
  Tem Instagram [toggle]

QUALIDADE
  Score mínimo [slider 0-100]
  Verificado em [date range: últimos 30/60/90 dias]
  Status no CRM [multi-select: novo, contatado, ...]

EXCLUSÃO (apenas Business)
  Já exportado por mim [toggle para esconder]
  Já no meu CRM [toggle para esconder]
```

**Implementation rule:** Filters apply client-side for current result set, with debounced API call (300ms) on change. Show result count update in real-time without full page reload.

### 3.2 Results Table Design

Use a table (not cards) for lead results. Tables allow comparison and scanning at the speed sales people work.

Columns (fixed order, user cannot reorder in MVP):
```
[ ] Checkbox | Empresa | Cidade | Nicho | Score | Contatos (icons) | Adicionado | Ações
```

Contact icons approach: Show icons for Email, Phone, WhatsApp, Instagram, Site — filled/colored if available, gray/hollow if not. **Never show the actual values in the table row.** This is the "reveal gate" — clicking an icon or the company name opens a detail drawer that consumes a credit.

**Color code score**: 0-40 red, 41-70 yellow, 71-100 green. Users learn quality at a glance.

### 3.3 Detail Drawer (Credit Reveal Pattern)

When user clicks a lead:
1. Drawer opens on the right (slide-in from right, ~400px wide)
2. Shows company name, city, category, score, source, date added
3. Contact fields show a "Revelar — 1 crédito" button in place of the actual value
4. Clicking reveal: deducts 1 credit, shows value, marks as "revelado" (no second charge for same lead in same session)
5. Credit balance shown in header updates immediately (optimistic UI)

This is exactly how Lusha, Apollo, and ContactOut work. Users accept the model because they can evaluate whether the lead is worth revealing before spending.

**Important**: If user already revealed this lead previously (track in DB per user), re-opening drawer shows data without credit charge. Store `user_lead_reveals` table.

### 3.4 Bulk Select and Export Flow

Bulk select pattern (standard, same as Apollo):
- Checkbox in table header selects current page
- "Selecionar todos os X resultados" appears after selecting all on page
- Max bulk select: 500 for Pro, 2,000 for Business

Export flow:
1. User selects leads (or uses "select all results")
2. Clicks "Exportar" button
3. Modal appears showing: count, credit cost, remaining credits after, format choice
4. User confirms → export starts → file download (or async job for >200 leads with email notification)
5. Credits deducted atomically with export record in DB

**Never deduct credits before the file is ready.** If export fails, credits must not be consumed.

### 3.5 Saved Searches

Allow users to name and save filter combinations. This is one of the highest-value sticky features:
- Saved searches appear in sidebar under "Minhas Buscas"
- One-click to reapply all filters
- Optional: "Notify me when new leads match this search" (email notification, weekly digest)
- Limit by plan: 3/10/unlimited

The notification feature turns the product into a recurring habit driver — users check email, see "23 novos leads para Clínica Médica em Vitória", click back in.

---

## 4. Plan/Quota Enforcement in Flask

### 4.1 Schema

Add to PostgreSQL:

```sql
-- Plan definitions (admin-managed)
CREATE TABLE plans (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,                  -- 'free', 'starter', 'pro', 'business'
    credits_per_month INTEGER NOT NULL,
    max_saved_searches INTEGER NOT NULL DEFAULT 0,
    max_niche_requests_per_month INTEGER NOT NULL DEFAULT 0,
    can_bulk_export BOOLEAN NOT NULL DEFAULT FALSE,
    can_export_json BOOLEAN NOT NULL DEFAULT FALSE,
    can_export_marketing BOOLEAN NOT NULL DEFAULT FALSE,
    rollover_max_multiplier DECIMAL(3,1) DEFAULT 1.0,  -- 1.5 = can carry up to 1.5x monthly
    price_brl DECIMAL(10,2)
);

-- User plan assignment
ALTER TABLE users ADD COLUMN plan_id INTEGER REFERENCES plans(id) DEFAULT 1;
ALTER TABLE users ADD COLUMN plan_expires_at TIMESTAMP;
ALTER TABLE users ADD COLUMN extra_credits INTEGER NOT NULL DEFAULT 0;

-- Credit ledger (append-only, never update rows)
CREATE TABLE credit_events (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_type VARCHAR(30) NOT NULL,  -- 'monthly_grant', 'reveal', 'export', 'purchase', 'rollover'
    delta INTEGER NOT NULL,           -- positive = added, negative = consumed
    balance_after INTEGER NOT NULL,   -- denormalized for fast reads
    lead_id INTEGER REFERENCES leads(id),
    export_id INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    metadata JSONB
);

-- Track reveals per user (no double-charge)
CREATE TABLE user_lead_reveals (
    user_id INTEGER NOT NULL REFERENCES users(id),
    lead_id INTEGER NOT NULL REFERENCES leads(id),
    revealed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, lead_id)
);

-- Export records
CREATE TABLE exports (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    lead_count INTEGER NOT NULL,
    credits_charged INTEGER NOT NULL,
    format VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, ready, failed
    file_path VARCHAR(500),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);
```

### 4.2 Credit Enforcement Pattern in Flask

Use a decorator that checks and atomically deducts credits:

```python
def require_credits(cost: int):
    """Decorator: checks balance, deducts atomically, returns 402 if insufficient."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = get_current_user_id()
            conn = get_db_conn()
            try:
                with conn:  # transaction
                    cur = conn.cursor()
                    # Read current balance (last event for this user)
                    cur.execute("""
                        SELECT balance_after FROM credit_events
                        WHERE user_id = %s ORDER BY id DESC LIMIT 1
                        FOR UPDATE  -- row lock prevents concurrent overdraft
                    """, (user_id,))
                    row = cur.fetchone()
                    balance = row[0] if row else 0

                    if balance < cost:
                        return jsonify({
                            "error": "insufficient_credits",
                            "balance": balance,
                            "required": cost
                        }), 402

                    # Deduct
                    cur.execute("""
                        INSERT INTO credit_events (user_id, event_type, delta, balance_after)
                        VALUES (%s, 'reveal', %s, %s)
                    """, (user_id, -cost, balance - cost))

                return fn(*args, **kwargs)
            finally:
                conn.close()
        return wrapper
    return decorator
```

Key points:
- Use `FOR UPDATE` to prevent race conditions with concurrent requests (same user, two tabs)
- The ledger is append-only — never UPDATE credit rows, only INSERT new events
- Balance is denormalized in `balance_after` for O(1) current balance reads
- Return HTTP 402 (Payment Required) for insufficient credits — frontend interprets this as "show upgrade modal"

### 4.3 Monthly Credit Grant (APScheduler)

Add to the existing APScheduler job — run at midnight on the 1st of each month:

```python
def grant_monthly_credits():
    """Grants monthly credits to all active users based on plan."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT u.id, p.credits_per_month, p.rollover_max_multiplier,
                   COALESCE((SELECT balance_after FROM credit_events
                             WHERE user_id = u.id ORDER BY id DESC LIMIT 1), 0) as current_balance
            FROM users u
            JOIN plans p ON u.plan_id = p.id
            WHERE u.is_active = TRUE AND (u.plan_expires_at IS NULL OR u.plan_expires_at > NOW())
        """)
        users = cur.fetchall()

        for user_id, monthly_grant, multiplier, current_balance in users:
            # Rollover cap: cannot carry more than multiplier * monthly_grant
            max_carry = int(monthly_grant * multiplier)
            carry = min(current_balance, max_carry)
            new_balance = carry + monthly_grant

            cur.execute("""
                INSERT INTO credit_events (user_id, event_type, delta, balance_after, metadata)
                VALUES (%s, 'monthly_grant', %s, %s, %s)
            """, (user_id, monthly_grant, new_balance,
                  json.dumps({"carry": carry, "grant": monthly_grant})))

        conn.commit()
        print(f"[credits] Monthly grant complete for {len(users)} users")
    finally:
        conn.close()
```

### 4.4 Plan Feature Gate Decorator

Separate from credits — enforce feature access by plan:

```python
def require_plan_feature(feature: str):
    """Check if user's plan has a specific feature enabled."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            plan = get_user_plan(user['id'])  # cached in Redis or in-memory TTL dict
            if not plan.get(feature):
                return jsonify({
                    "error": "plan_feature_required",
                    "feature": feature,
                    "current_plan": plan['name']
                }), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# Usage:
@app.route('/api/leads/export/json')
@require_plan_feature('can_export_json')
@require_credits(cost=lambda: request.json.get('count', 0))
def export_json():
    ...
```

---

## 5. Niche Request Feature

### 5.1 User Flow

1. Client opens "Solicitar Nicho" page (sidebar menu item, visible to Starter+)
2. Form: Nicho (text + autocomplete from existing categories), Cidade (typeahead), Estado, Observações (optional)
3. Submit → enters queue, user sees "Solicitação enviada. Prazo estimado: 3 dias úteis."
4. Admin sees queue in admin panel: pending requests, sorted by frequency (if multiple users request same niche)
5. Admin clicks "Executar" → triggers existing `POST /api/admin/daily-job/run` with the requested niche/region
6. When extraction completes and leads are added, notify user by email

### 5.2 Schema

```sql
CREATE TABLE niche_requests (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    niche VARCHAR(200) NOT NULL,
    city VARCHAR(100),
    state VARCHAR(2),
    notes TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, queued, processing, done, rejected
    priority INTEGER NOT NULL DEFAULT 0,            -- admin can bump priority
    admin_notes TEXT,
    leads_added INTEGER,                            -- filled when done
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);
```

### 5.3 Admin Queue UX

Admin panel table with columns: Nicho | Cidade | Usuário | Plano | Data | Outros pedindo mesmo | Status | Ações

"Outros pedindo mesmo" is a computed count — if 5 clients request "Clínica Médica, Curitiba", it auto-bumps to top. This is both a prioritization tool and a business signal (where to expand coverage).

Admin actions: Executar Agora | Agendar para Amanhã | Rejeitar (com motivo)

When rejected, the user gets a refund of their niche request slot for the month.

### 5.4 Dedup Logic

Before inserting, check if an equivalent request exists (pending or done in last 30 days):
```sql
SELECT COUNT(*) FROM niche_requests
WHERE niche ILIKE %s AND city ILIKE %s AND status IN ('pending', 'queued', 'processing', 'done')
AND created_at > NOW() - INTERVAL '30 days'
```
If match found, increment a `vote_count` on the existing request instead of creating a new one.

---

## 6. Product Stickiness Mechanisms

These are the features that make a lead database product hard to leave:

### 6.1 Freshness Indicators (HIGH VALUE)

Show when each lead was last verified or added. In the results table, add a "Adicionado" column with relative time (e.g., "há 2 dias", "há 3 meses").

Color code freshness:
- Green: added/verified in last 30 days
- Yellow: 31-90 days
- Red: >90 days

In detail drawer, add: "Verificado em: 15 mar 2026" and source badge (e.g., "Google Maps", "Diretório BR").

This directly attacks the main objection to paying for a lead database: "are these current?"

### 6.2 Quality Score (Visible and Explained)

Show the score prominently (e.g., 87/100 in green). More importantly, show why:

```
Score: 87/100
+ Tem email verificado (+20)
+ Tem WhatsApp (+20)
+ Tem site funcional (+15)
+ CNPJ confirmado via BrasilAPI (+20)
+ Adicionado há 12 dias (+12)
- Sem Instagram (-0)
```

Transparency in scoring builds trust. Users who understand the score learn to filter by it confidently.

### 6.3 Saved Searches with New Lead Alerts

Already described in Section 3.5. This is the single biggest retention driver. Weekly email digest: "Olá [Nome], 47 novos leads foram adicionados para suas buscas salvas esta semana."

### 6.4 "Exclusive" Data Labeling

For leads captured via sources not commonly available (e.g., extracted via Google Maps Playwright, not from a public directory), tag them as "Dados exclusivos" with a small badge. Implies you won't find this on free tools.

### 6.5 Export History

Show users their export history: what they exported, when, how many credits spent. This creates anchoring — users who have invested credits in previous exports are psychologically more likely to renew and buy more credits.

### 6.6 Monthly Usage Report (Email)

At end of each month, send each paying user an auto-generated email:
- Leads viewed/exported this month
- Top niches they searched
- Credits used vs. available
- "Você ainda tem X créditos disponíveis até [data de renovação]"

This surfaces value to users who might not log in frequently, reducing passive churn.

---

## 7. Role-Based Access Control (RBAC)

### 7.1 Role Definitions

| Role | Description | What They Can Do |
|------|-------------|-----------------|
| `admin` | System owner (you) | Everything: pipeline control, user management, all leads, all exports, niche queue management, plan management |
| `operator` | Staff/VA | Run extractions, manage lead quality, see all leads, approve niche requests, cannot manage users or plans |
| `client` | Paying customer | Search the aggregated database, reveal contacts (credit-gated), export (credit-gated), save searches, submit niche requests. Cannot see other users' data, cannot trigger extractions |

### 7.2 Implementation Pattern in Flask

Add `role` column to `users` table:

```sql
ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'client';
-- Valid values: 'admin', 'operator', 'client'
```

Decorator for role checking:

```python
ROLE_HIERARCHY = {'admin': 3, 'operator': 2, 'client': 1}

def require_role(minimum_role: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            user_level = ROLE_HIERARCHY.get(user.get('role', 'client'), 0)
            required_level = ROLE_HIERARCHY.get(minimum_role, 999)
            if user_level < required_level:
                return jsonify({"error": "forbidden", "required_role": minimum_role}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# Usage:
@app.route('/api/admin/daily-job/run', methods=['POST'])
@require_role('operator')
def run_daily_job():
    ...

@app.route('/api/admin/users', methods=['GET'])
@require_role('admin')
def list_users():
    ...
```

### 7.3 Client Data Isolation

Clients must never see:
- Raw scraping job details (jobs, batches, search_jobs tables)
- Other clients' export history or saved searches
- Pipeline configuration or logs
- Admin dashboard

Client-facing endpoints operate entirely on the `leads` table (public aggregated data), with the user's own `credit_events`, `user_lead_reveals`, `exports`, `saved_searches`, and `niche_requests` tables.

Enforce at the query level — never pass `user_id` from the client request to raw lead queries without filtering by the authenticated user's own data for private tables.

### 7.4 Frontend Route Guard

In Next.js (static export), implement a client-side route guard in `_app.tsx`:

```typescript
const ROLE_ROUTES: Record<string, string[]> = {
  '/admin': ['admin'],
  '/admin/users': ['admin'],
  '/admin/pipeline': ['admin', 'operator'],
  '/massive-search': ['admin', 'operator'],
  '/portal': ['client', 'admin', 'operator'],
};
```

This is cosmetic security only — the real enforcement is in the Flask API. The frontend guard prevents accidental navigation and provides correct UX.

---

## 8. Key Architecture Additions to Existing System

The existing system has: `users`, `sessions`, `leads`, `jobs`, `batches`, `search_jobs`, `api_configs`, `api_usage`, `daily_jobs`.

New tables needed for the portal:

| Table | Purpose |
|-------|---------|
| `plans` | Plan definitions (admin-editable) |
| `credit_events` | Append-only credit ledger |
| `user_lead_reveals` | Track reveals per user (no double-charge) |
| `exports` | Export job records |
| `saved_searches` | Saved filter combinations per user |
| `niche_requests` | Client niche requests + admin queue |

New API endpoints needed:

| Endpoint | Role | Description |
|----------|------|-------------|
| `GET /api/portal/leads` | client | Search leads (no scraping triggers, read-only) |
| `POST /api/portal/leads/:id/reveal` | client | Reveal contact, deducts 1 credit |
| `GET /api/portal/credits` | client | Current balance + event history |
| `POST /api/portal/export` | client | Async export, deducts credits on completion |
| `GET /api/portal/export/:id/status` | client | Poll export status |
| `GET /api/portal/saved-searches` | client | List saved searches |
| `POST /api/portal/saved-searches` | client | Create saved search |
| `DELETE /api/portal/saved-searches/:id` | client | Delete saved search |
| `GET /api/portal/niche-requests` | client | My niche requests |
| `POST /api/portal/niche-requests` | client | Submit niche request |
| `GET /api/admin/niche-requests` | operator | Admin queue view |
| `PUT /api/admin/niche-requests/:id` | operator | Update status, trigger extraction |

---

## 9. Critical Pitfalls

### 9.1 Race Condition on Credit Deduction

**Problem**: Two simultaneous export requests can both pass the "do you have credits?" check before either deducts.
**Solution**: `SELECT FOR UPDATE` on the ledger row inside a transaction. Do not use application-level locks.

### 9.2 Export Atomicity

**Problem**: Export file is generated, credits are deducted, file upload to storage fails → user loses credits without getting file.
**Solution**: Only deduct credits after the file is confirmed ready (or saved to VPS). Use a two-phase approach: reserve credits (mark as pending), generate file, then confirm deduction. If file fails, roll back reservation.

### 9.3 Free Tier Abuse

**Problem**: Users create many free accounts to get unlimited free reveals.
**Solution**: Rate-limit account creation by IP. Require email verification before any reveals. Consider requiring a verified phone number for free tier (via Twilio or WhatsApp OTP).

### 9.4 Double-Charge on Reveal

**Problem**: User opens drawer, credit deducted, closes, reopens — charged again.
**Solution**: `user_lead_reveals` table with `PRIMARY KEY (user_id, lead_id)`. Before deducting, check this table. If already revealed, show data without charging. This is also a value signal — users discover they can freely re-access what they already paid for.

### 9.5 Niche Request Duplication

**Problem**: 10 users request "Dentistas em Curitiba", 10 records created, admin confused about priority.
**Solution**: Dedup + vote count as described in Section 5.4. UI shows "8 outros usuários também pediram isto."

### 9.6 Stale Rate Limits (Existing Tech Debt)

**Problem**: Flask-Limiter without Redis gives per-worker limits. With 2 Gunicorn workers, effective limit is 2x the configured limit.
**Solution for portal launch**: This is acceptable for credits (DB-based, exact) but problematic for rate limits on free scraping endpoints. Since portal clients cannot trigger scraping, this tech debt does not affect the portal's credit system. Document and accept for now.

### 9.7 Leads Table Ownership Ambiguity

**Problem**: `leads` table currently belongs to admin/operator context (has `batch_id`, `crm_status` per-user fields). Clients browsing the same table may see internal fields (notes, crm_status) set by the operator.
**Solution**: Create a portal view that exposes only the public subset of fields. Either a PostgreSQL VIEW or a dedicated serialization layer in the Flask route.

```sql
CREATE VIEW portal_leads AS
SELECT
    id, company_name, city, state, category,
    CASE WHEN email IS NOT NULL THEN '***@***.***' ELSE NULL END as email_hint,
    CASE WHEN phone IS NOT NULL THEN TRUE ELSE FALSE END as has_phone,
    CASE WHEN whatsapp IS NOT NULL THEN TRUE ELSE FALSE END as has_whatsapp,
    website, instagram, lead_score, source, created_at
FROM leads
WHERE email IS NOT NULL OR phone IS NOT NULL OR whatsapp IS NOT NULL;
```

Actual values are returned only via the `/reveal` endpoint after credit deduction.

---

## 10. MVP Scope Recommendation

Build the portal in this exact sequence to generate revenue fastest:

**Phase 1 — Foundation (1 week)**
- `plans` table + seed 4 plans
- `credit_events` ledger
- `role` column on users
- Monthly credit grant via APScheduler
- `GET /api/portal/leads` with filters (read-only, no reveal yet)
- Portal frontend page: search + filter sidebar + results table (blurred contact fields)

**Phase 2 — Monetization (1 week)**
- `user_lead_reveals` table
- `POST /api/portal/leads/:id/reveal` with credit deduction
- `GET /api/portal/credits` — balance + history
- Upgrade modal triggered on 402 responses
- Free tier enforced (20 credits/month)

**Phase 3 — Export (1 week)**
- `exports` table
- `POST /api/portal/export` — async, deducts on completion
- Export polling + download
- Credit confirmation modal before export

**Phase 4 — Stickiness (1 week)**
- Saved searches (table + CRUD endpoints + frontend)
- New lead alert emails (weekly digest via APScheduler)
- Export history page
- Monthly usage email

**Phase 5 — Niche Requests (1 week)**
- `niche_requests` table
- Client submit flow
- Admin queue page
- Email notification on completion

---

## Sources

- [Apollo.io Pricing](https://www.apollo.io/pricing) — plan tiers and credit system
- [Apollo Pricing 2026 Full Breakdown — Warmly](https://www.warmly.ai/p/blog/apollo-pricing)
- [Hunter.io Pricing Guide 2025 — BookYourData](https://www.bookyourdata.com/blog/hunter-io-pricing)
- [Lusha vs Kaspr 2025 — AppVizer](https://www.appvizer.com/magazine/customer/customer-prospecting/kaspr-vs-lusha)
- [Snov.io Pricing 2025 — Fullenrich](https://fullenrich.com/content/snov-io-pricing)
- [ZoomInfo Pricing 2025 — ZoomInfo Pipeline](https://pipeline.zoominfo.com/sales/how-much-does-zoominfo-cost)
- [Filter UX Design Best Practices — Eleken](https://www.eleken.co/blog-posts/filter-ux-and-ui-for-saas)
- [Apollo Search Filters Overview](https://knowledge.apollo.io/hc/en-us/articles/4412665755661-Search-Filters-Overview)
- [SaaS Credits System Guide 2026 — ColorWhistle](https://colorwhistle.com/saas-credits-system-guide/)
- [PostgreSQL SaaS Subscription Modeling — Axel Larsson](https://axellarsson.com/blog/modeling-saas-subscriptions-in-postgres/)
- [Flask RBAC Developer Guide — Aserto](https://www.aserto.com/blog/flask-rbac-demystified-a-developer-s-guide)
- [Advanced RBAC in Flask — Medium, Dec 2024](https://medium.com/@oludakevin/advanced-features-for-flask-rbac-implementation-320761937e9a)
- [API Rate Limits Best Practices 2025 — Zuplo](https://zuplo.com/learning-center/10-best-practices-for-api-rate-limiting-in-2025)
- [Usage-Based Billing SaaS Guide — HubiFi](https://www.hubifi.com/blog/usage-based-billing-saas-guide)
- [SaaS 35 Import/Export Design Examples — SaaSFrame](https://www.saasframe.io/categories/import-export)
- [Sales Navigator Alerts (saved search notification pattern)](https://www.linkedin.com/help/sales-navigator/answer/a105133)
