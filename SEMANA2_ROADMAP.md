# Semana 2 Roadmap — Experience & Admin Interfaces

**Status**: 📋 Planning
**Start Date**: After Semana 1 validation
**Duration**: 1 week
**Focus**: Admin UI, saved filters, lead scoring foundation

---

## 🎯 Semana 2 Goals

1. **Admin Pages**: Create `/admin/users` and `/admin/plans` UI
2. **Saved Filters**: Per-plan feature to save and reuse lead filters
3. **Lead Scoring**: Foundation for quality metrics (visible Semana 3)
4. **Client Experience**: Smooth workflow improvements

---

## 📋 Feature Breakdown

### Feature 1: Admin Users Management Page
**Path**: `/admin/users`
**Time**: ~4 hours

#### What It Shows
- [ ] Table of all users with columns:
  - Username
  - Plan (with badge color)
  - Created date
  - Current usage (leads/exports)
  - Usage % bars
  - Actions dropdown

#### Actions Available
- [ ] **Change Plan**: Open modal to select new plan
- [ ] **View Usage**: Show detailed usage history
- [ ] **Reset Usage**: Manually reset monthly counters (for testing/support)
- [ ] **Deactivate User**: Soft-delete (future)

#### Components Needed
- [ ] `AdminUsersPage.tsx` — Main page
- [ ] `UserTable.tsx` — Sortable user list
- [ ] `ChangePlanModal.tsx` — Plan selector + confirmation
- [ ] `UserUsageDetail.tsx` — Detailed usage breakdown

#### Database Queries
```sql
-- Get all users with current usage
SELECT
  u.id, u.username, u.plan, u.created_at,
  ut.leads_viewed, ut.leads_exported,
  pl.leads_per_month, pl.exports_per_month
FROM users u
LEFT JOIN usage_tracking ut ON u.id = ut.user_id AND ut.month_year = '2026-03'
LEFT JOIN plan_limits pl ON u.plan = pl.plan_name
ORDER BY u.created_at DESC;
```

#### UI Mockup
```
┌─ Gerenciar Usuários ──────────────────────────────────────┐
│                                                             │
│ Usuario              Plan    Criado em   Leads   Acoes     │
├─────────────────────────────────────────────────────────────┤
│ john                 Free    2026-03-01  45/100  ▼ Change   │
│ jane                 Pro     2026-02-15  4200/5K ▼ Change   │
│ admin_user           Ent     2025-01-01  999/∞   ▼ Change   │
│ test_free            Free    2026-03-10  0/100   ▼ Change   │
└─────────────────────────────────────────────────────────────┘
```

#### Backend Enhancement Needed
- [ ] Add `/api/admin/users/{id}/usage-history` (detailed monthly breakdown)
- [ ] Add `/api/admin/users/{id}/reset-usage` (manual reset)
- [ ] Endpoint already exists: `/api/admin/users`, `/api/admin/users/<id>/plan`

---

### Feature 2: Admin Plans Configuration Page
**Path**: `/admin/plans`
**Time**: ~3 hours

#### What It Shows
- [ ] Cards for each plan (Free, Pro, Enterprise)
- [ ] Plan details:
  - Name & price
  - Leads/month limit
  - Exports/month limit
  - Feature list (as bullets)
  - Number of users on plan
  - Edit button

#### Edit Plan Modal
- [ ] Change leads_per_month
- [ ] Change exports_per_month
- [ ] Change price_monthly
- [ ] Update features JSONB
- [ ] Confirmation: "Update plan for X existing users?"

#### Components Needed
- [ ] `AdminPlansPage.tsx` — Main page
- [ ] `PlanCard.tsx` — (NEW, different from client PlanCard) Shows admin view
- [ ] `EditPlanModal.tsx` — Edit form

#### UI Mockup
```
┌─ Planos & Limites ────────────────────────────────────────┐
│                                                             │
│ ┌─ Plano Grátis ────┐   ┌─ Plano Pro ──────┐   ┌─ Ent ───┐
│ │ R$0/mês           │   │ R$99/mês          │   │ Custom  │
│ │ 100 leads/mês     │   │ 5,000 leads/mês   │   │ ∞       │
│ │ 1 export/mês      │   │ 20 exports/mês    │   │ ∞       │
│ │ ─────────────────   │   │ ─────────────────── │   │ ────── │
│ │ ✓ Basic filters   │   │ ✓ Adv. filters    │   │ ✓ API  │
│ │ ✓ Email/Phone     │   │ ✓ Saved filters   │   │ ✓ All  │
│ │ ✗ Saved filters   │   │ ✓ Bulk actions    │   │ ✓ All  │
│ │ ✗ Bulk actions    │   │ ✗ API access      │   │        │
│ │ ─────────────────   │   │ ─────────────────── │   │ ────── │
│ │ 42 users          │   │ 5 users           │   │ 1 user │
│ │ [Edit]            │   │ [Edit]            │   │ [Edit] │
│ └─────────────────────┘   └────────────────────┘   └────────┘
└─────────────────────────────────────────────────────────────┘
```

#### Backend Enhancement Needed
- [ ] Add `/api/admin/plans/{plan_name}` PUT endpoint (update plan)
- [ ] Add `/api/admin/plans-stats` GET endpoint (users per plan)

---

### Feature 3: Saved Filters (Client)
**Path**: `/leads` with saved filter UI
**Time**: ~5 hours

#### What It Is
- [ ] Save current filter combination as a named segment
- [ ] Pro plan: up to 5 saved filters
- [ ] Enterprise: up to 20 saved filters
- [ ] Free plan: no saved filters

#### UI Components
- [ ] **Save Filter Button**: Below filters, when filter is active
  - Input modal for filter name: "High-value leads", "Recent contacts", etc.
  - Confirmation: saves to database

- [ ] **Load Filter Dropdown**: Shows saved filters
  - Click to apply → resets filters to saved state
  - Delete button (trash icon) to remove

- [ ] **Badge on Active Filter**: "📌 Recent Contacts" indicator

#### New Database Table
```sql
CREATE TABLE saved_filters (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  name VARCHAR(100) NOT NULL,
  filters JSONB NOT NULL,  -- {status, tag, city, state, search, batch_id, sort}
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(user_id, name)
);
```

#### Backend Endpoints Needed
- [ ] `POST /api/leads/saved-filters` — Save current filter
  - Payload: { name: "string", filters: {status, tag, city, state, search, batch_id, sort} }
  - Check plan allows (free=0, pro=5, ent=20)
  - Return 403 if limit reached

- [ ] `GET /api/leads/saved-filters` — List saved filters
  - Returns: array of {id, name, filters, created_at}

- [ ] `DELETE /api/leads/saved-filters/{id}` — Delete saved filter

- [ ] `POST /api/leads/saved-filters/{id}/apply` — Apply saved filter
  - Returns: filtered leads (same as GET /api/leads with those filters)

#### Frontend Components
- [ ] `SaveFilterButton.tsx` — Save current filters
- [ ] `SavedFiltersList.tsx` — Dropdown/sidebar showing saved filters
- [ ] Integration in leads.tsx

#### UI Mockup
```
Leads CRM

Filtros de Localização
┌─────────────────────────────────────────────────┐
│ [Cidade ▼] [Estado ▼] [Status ▼] [Tag ▼]      │
│ [🔍 Buscar...] [📌 Salvar filtro] [❌ Limpar]   │
│                                                  │
│ Filtros Salvos:                                │
│ ↓ ✓ High-Value Leads (estado=SP)   [⋯ Delete] │
│ ↓ ✓ Recent Contacts (status=novo)   [⋯ Delete] │
│ ↓ + Criar novo filtro...                        │
└─────────────────────────────────────────────────┘
```

---

### Feature 4: Lead Scoring Foundation
**Path**: `/leads` with score column + `/api/leads/enrich-score`
**Time**: ~4 hours

#### What It Is
- [ ] Each lead gets a score (0-100) based on:
  - Email present (20 pts)
  - Phone present (15 pts)
  - WhatsApp present (15 pts)
  - CNPJ enriched (15 pts)
  - Contact name present (10 pts)
  - Address present (10 pts)
  - Website present (5 pts)
  - LinkedIn/Instagram/Facebook (5 pts each)

#### Score Display
- [ ] New column in leads table: "Score" with color coding
  - 0-30: Red (low quality)
  - 31-70: Yellow (medium)
  - 71-100: Green (high quality)

- [ ] Sort by score

- [ ] Filter by score range (Semana 3)

#### Backend Endpoint
- [ ] `POST /api/leads/enrich-score` — Calculate + update scores
  - Recalculate all leads for user
  - Or batch by ID
  - Update `lead_score` column
  - Return count updated

#### SQL Schema Change
```sql
ALTER TABLE leads ADD COLUMN lead_score INTEGER DEFAULT 0;
CREATE INDEX idx_leads_score ON leads(lead_score DESC);
```

#### Frontend Changes
- [ ] Add Score column to leads table
- [ ] Color-code score cells
- [ ] Add score to lead drawer/detail view
- [ ] Add "Calculate Scores" button in bulk actions

---

## 📊 Semana 2 Implementation Timeline

| Task | Est. Hours | Start | End | Status |
|------|-----------|-------|-----|--------|
| Admin Users Page | 4 | Day 1 | Day 1 | 🔲 |
| Admin Plans Page | 3 | Day 1 | Day 2 | 🔲 |
| Saved Filters (Backend) | 2.5 | Day 2 | Day 2 | 🔲 |
| Saved Filters (Frontend) | 2.5 | Day 2 | Day 3 | 🔲 |
| Lead Scoring (Backend) | 2 | Day 3 | Day 3 | 🔲 |
| Lead Scoring (Frontend) | 2 | Day 3 | Day 4 | 🔲 |
| Testing & Bug Fixes | 3 | Day 4 | Day 5 | 🔲 |
| Deployment | 1 | Day 5 | Day 5 | 🔲 |
| **Total** | **20 hours** | — | — | — |

---

## 🔄 Dependencies

**Semana 1 → Semana 2**:
- ✅ Plan system (already done)
- ✅ Usage tracking (already done)
- ✅ Admin/client separation (already done)

**Semana 2 → Semana 3**:
- [ ] Lead scoring (foundation)
- [ ] Saved filters (foundation)
- [ ] Lead enrichment API (existing, just integrate)

---

## 🎨 Design Decisions

### Saved Filters Limit
- Free: 0 (no saved filters)
- Pro: 5
- Enterprise: 20

**Why**: Encourages upgrade, Pro feels like a "power user" feature

### Lead Score Algorithm
- Simple points system (no ML yet)
- Extensible for Semana 3 (AI-based ranking)
- Visible but not blocking (just info, not filtering yet)

### Admin Pages
- Separate from client UX
- Admin nav shows "Gerenciar Usuários" + "Planos & Limites"
- Future: audit logs, system health dashboard

---

## 🚀 What's NOT in Semana 2

- ❌ Payment integration (Stripe) — Semana 4
- ❌ Billing dashboard — Semana 4
- ❌ Webhook/API access for Enterprise — Semana 5
- ❌ Batch operations with ACL — Semana 5
- ❌ AI-based lead scoring — Semana 6 (optional)
- ❌ CRM sync improvements — Semana 5

---

## ✅ Definition of Done (Semana 2)

- [ ] All features implemented in backend + frontend
- [ ] No TypeScript errors
- [ ] Next.js builds clean
- [ ] API endpoints tested with curl/Postman
- [ ] UI responsive (desktop + mobile)
- [ ] Dark mode working
- [ ] No console errors
- [ ] Deployed to staging
- [ ] Validation checklist completed
- [ ] Code reviewed

---

## 📝 Notes

- Each admin/client page should follow existing design (same sidebar, header, spacing)
- Reuse existing components where possible (StatCard, StatusBadge, etc.)
- Maintain dark mode compatibility
- Performance: keep list queries under 200ms
- Mobile: test all pages on mobile before deploy

---

**Ready to start Semana 2 after validation passes ✅**
