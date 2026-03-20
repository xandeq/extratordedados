# Semana 1 Validation Checklist

**Status**: ✅ Deployed to Production
**Date**: 2026-03-13
**Phase**: Validation & QA

---

## 🔍 Pre-Validation Setup

### Access Credentials
You'll need test accounts with different plans:
- **Free Account**: Test with 100 leads/month limit
- **Pro Account**: Test with 5,000 leads/month limit
- **Admin Account**: Test user management panel

### Admin Setup
1. SSH to VPS: `ssh root@185.173.110.180`
2. Connect to PostgreSQL: `psql -U extrator -d extrator`
3. Check data:
   ```sql
   SELECT username, plan, created_at FROM users;
   SELECT * FROM plan_limits;
   SELECT * FROM usage_tracking;
   ```

---

## ✅ Validation Tests

### Part 1: Backend API Tests

#### 1.1 Database Schema
- [ ] `users` table has `plan` column (VARCHAR, DEFAULT 'free')
- [ ] `usage_tracking` table exists with proper structure
- [ ] `plan_limits` table has 3 rows (free, pro, enterprise)
- [ ] Indexes created: idx_usage_tracking_user_month, idx_users_plan

**Command**:
```sql
\d users;
\d usage_tracking;
\d plan_limits;
\di;
```

#### 1.2 GET /api/client/usage
- [ ] Endpoint returns 200 with plan data
- [ ] Response includes: plan, limits, usage, usage_percent
- [ ] `leads_per_month` matches plan (free=100, pro=5000, enterprise=999999)
- [ ] `exports_per_month` matches plan (free=1, pro=20, enterprise=999999)
- [ ] Usage counters start at 0 for new month

**Test with curl**:
```bash
curl -H "Authorization: Bearer {token}" \
  https://api.extratordedados.com.br/api/client/usage | jq
```

**Expected response**:
```json
{
  "plan": "free",
  "limits": {
    "leads_per_month": 100,
    "exports_per_month": 1,
    "price_monthly": 0
  },
  "usage": {
    "leads_viewed": 0,
    "leads_exported": 0,
    "month_year": "2026-03"
  },
  "usage_percent": {
    "leads": 0,
    "exports": 0
  }
}
```

#### 1.3 GET /api/leads (with usage tracking)
- [ ] Endpoint still returns leads normally
- [ ] Response now includes `plan`, `usage`, `usage_percent` fields
- [ ] Viewing a page increments `leads_viewed` counter
- [ ] Second view increments counter again

**Test flow**:
```bash
# First call
curl -H "Authorization: Bearer {token}" \
  "https://api.extratordedados.com.br/api/leads?page=1" | jq '.usage'

# Should show: leads_viewed: 50 (or however many on page)

# Second call - counter should increase
curl -H "Authorization: Bearer {token}" \
  "https://api.extratordedados.com.br/api/leads?page=1" | jq '.usage'

# Should show: leads_viewed: 100 (50 more)
```

#### 1.4 GET /api/leads/export (with limit check)
- [ ] Free plan can export 1 time per month
- [ ] Second export attempt returns 403 Forbidden
- [ ] Error message includes plan and upgrade suggestion
- [ ] Pro plan allows 20 exports per month
- [ ] Enterprise allows unlimited exports

**Test free plan**:
```bash
# First export - should work
curl -H "Authorization: Bearer {free_token}" \
  "https://api.extratordedados.com.br/api/leads/export?format=csv" \
  -o leads1.csv

# Check status
echo $?  # Should be 0

# Second export - should fail
curl -H "Authorization: Bearer {free_token}" \
  "https://api.extratordedados.com.br/api/leads/export?format=csv"

# Should return 403 with error message
```

#### 1.5 GET /api/admin/users (admin-only)
- [ ] Only admin can access endpoint
- [ ] Returns list of all users with plan info
- [ ] Each user shows: id, username, plan, usage, limits
- [ ] Non-admin gets 403 Forbidden

**Test**:
```bash
# Admin - should work
curl -H "Authorization: Bearer {admin_token}" \
  https://api.extratordedados.com.br/api/admin/users | jq

# Client - should fail
curl -H "Authorization: Bearer {client_token}" \
  https://api.extratordedados.com.br/api/admin/users

# Should return 403
```

#### 1.6 PUT /api/admin/users/<id>/plan (change plan)
- [ ] Admin can update user plan
- [ ] Plan changes immediately reflected in /api/client/usage
- [ ] Non-admin gets 403 Forbidden
- [ ] Invalid plan name returns 400

**Test**:
```bash
# Change user 2 from free to pro
curl -X PUT \
  -H "Authorization: Bearer {admin_token}" \
  -H "Content-Type: application/json" \
  -d '{"plan":"pro"}' \
  https://api.extratordedados.com.br/api/admin/users/2/plan

# Verify change
curl -H "Authorization: Bearer {token_for_user_2}" \
  https://api.extratordedados.com.br/api/client/usage | jq '.plan'

# Should return: "pro"
```

#### 1.7 GET /api/admin/plans
- [ ] Admin can view all plans
- [ ] Returns 3 plans: free, pro, enterprise
- [ ] Each plan includes: name, leads_per_month, exports_per_month, price_monthly, features
- [ ] Non-admin gets 403 Forbidden

**Test**:
```bash
curl -H "Authorization: Bearer {admin_token}" \
  https://api.extratordedados.com.br/api/admin/plans | jq '.plans[0]'

# Should show free plan with 100 leads, 1 export, $0
```

---

### Part 2: Frontend UI Tests

#### 2.1 Header Component
- [ ] Header appears at top of all authenticated pages
- [ ] Shows page title (e.g., "Dashboard", "Leads CRM")
- [ ] Shows admin/client indicator
- [ ] Mobile hamburger menu appears on small screens
- [ ] Menu toggle works on mobile

**Steps**:
1. Visit https://extratordedados.com.br/dashboard
2. Check header is sticky (scrolls with content)
3. On mobile (resize to <768px), hamburger should appear
4. Click hamburger and sidebar should open

#### 2.2 UserMenu Dropdown
- [ ] Click username/badge in header
- [ ] Dropdown opens showing:
  - [ ] Username
  - [ ] Plan badge (with correct color: gray=free, blue=pro, purple=enterprise)
  - [ ] Usage bars (leads and exports with mini progress bars)
  - [ ] Settings link
  - [ ] Upgrade button (if not enterprise)
  - [ ] Logout button
- [ ] Clicking outside closes dropdown
- [ ] Upgrade button is clickable (shows placeholder alert)

**Steps**:
1. Login as free user
2. Click username in header top right
3. Verify all elements present
4. Check plan badge color (gray)
5. Check usage bars show 0/100 and 0/1
6. Login as pro user and verify blue badge
7. Login as enterprise and verify no upgrade button

#### 2.3 Sidebar Navigation
- [ ] Sidebar shows different nav based on user role
- [ ] **Client sees**: Dashboard, Nova Extracao, Busca Massiva, Leads
- [ ] **Admin sees**: Dashboard, Leads Database, Gerenciar Usuários, Planos & Limites, System Logs
- [ ] Active link is highlighted (blue background)
- [ ] Dark mode toggle button present
- [ ] No logout button (moved to UserMenu)

**Steps**:
1. Login as client → check client nav items
2. Login as admin → check admin nav items
3. Click each nav item and verify page loads
4. Verify active link styling

#### 2.4 Dashboard Plan Card
- [ ] PlanCard displays on dashboard above analytics
- [ ] Shows plan name (Plano Grátis, Plano Pro, Plano Enterprise)
- [ ] Shows leads usage bar: "X / Y"
- [ ] Shows exports usage bar: "X / Y"
- [ ] Color coding:
  - [ ] Green progress bar (0-79%)
  - [ ] Yellow progress bar (80-99%)
  - [ ] Red progress bar (100%+)
- [ ] Upgrade button appears when near limit (>80%)
- [ ] Lock icon when limit exceeded

**Steps**:
1. Login as free user
2. View dashboard
3. Check PlanCard shows "100 / 100" leads, "1 / 1" exports
4. Verify green progress bars
5. Create another user, set to pro
6. Check pro plan shows "5000 / 5000" leads

#### 2.5 Leads Page Limit Banners
- [ ] **Red banner** when export limit reached (message: "Limite de exportação atingido")
- [ ] **Orange banner** when viewing limit reached (message: "Limite de visualização atingido")
- [ ] **Yellow banner** when >80% usage (message: "Próximo do limite")
- [ ] Banners only show when applicable
- [ ] Free user with 1 export = red banner after first export

**Test flow**:
1. Login as free user
2. Export leads once → banner should NOT appear yet
3. Try to export again → RED BANNER should appear
4. Message should say: "Você exportou 1 de 1 listas neste mês"
5. Export button should be disabled
6. Tooltip on button should say "Limite atingido"

#### 2.6 Leads Page Export Button
- [ ] Normal state: "Exportar" button, enabled, blue
- [ ] At limit: "Exportar (Limite)" button, disabled, gray
- [ ] Clicking when disabled shows toast: "Você atingiu o limite de exportações para este mês"
- [ ] Tooltip changes based on limit status

**Test**:
1. Login as free user
2. View leads page
3. Click export → should work, modal opens
4. Close modal and try export again → toast appears, button doesn't open modal
5. Button text changes to "Exportar (Limite)"

#### 2.7 Sidebar Mobile Responsiveness
- [ ] On mobile (<768px): hamburger in header
- [ ] Click hamburger → sidebar slides in
- [ ] Click overlay → sidebar closes
- [ ] Click nav item → sidebar closes
- [ ] Dark mode toggle visible in sidebar footer

**Test**:
1. Open DevTools (F12)
2. Toggle mobile device toolbar (Ctrl+Shift+M)
3. Verify hamburger appears
4. Click hamburger → sidebar should slide in from left
5. Click outside → sidebar should close

#### 2.8 Dark Mode
- [ ] Toggle button in sidebar footer
- [ ] Clicking toggles dark/light mode
- [ ] Theme persists on page reload
- [ ] Header, sidebar, main content all follow theme
- [ ] All components (PlanCard, UserMenu, banners) support dark mode

**Test**:
1. Click dark mode toggle
2. Check all UI changes to dark theme
3. Refresh page → should stay in dark theme
4. Check localStorage: `localStorage.getItem('theme')` should return 'dark'

---

### Part 3: Data Flow Tests

#### 3.1 Usage Counter Flow
- [ ] View leads page with 50 leads → `leads_viewed` increments by 50
- [ ] View another page with 25 leads → counter increases to 75
- [ ] Counter resets each month (next month should start at 0)

**Test**:
1. Check `/api/client/usage` → leads_viewed: 0
2. Load `/leads?page=1` (50 items) → counter: 50
3. Load `/leads?page=2` (50 items) → counter: 100
4. Load `/leads?page=3` (25 items) → counter: 125

#### 3.2 Export Counter Flow
- [ ] First export increments `leads_exported` by 1
- [ ] Second export increments by 1 again
- [ ] Counter stops incrementing when limit reached (403)

**Test**:
1. Free user, usage shows 0/1 exports
2. Export CSV → counter becomes 1/1
3. Try export again → 403 returned, counter stays at 1/1

#### 3.3 Monthly Reset
- [ ] Create usage entry for current month
- [ ] Manually update database to simulate next month
- [ ] Call `/api/client/usage` → new usage_tracking entry created
- [ ] Counters reset to 0

**SQL Test**:
```sql
-- Check current month entry
SELECT * FROM usage_tracking WHERE user_id = 1 AND month_year = '2026-03';

-- Manually check next month (should be empty)
SELECT * FROM usage_tracking WHERE user_id = 1 AND month_year = '2026-04';

-- Call API for next month scenario (update system date or manually insert)
INSERT INTO usage_tracking (user_id, month_year, leads_viewed, leads_exported)
VALUES (1, '2026-04', 0, 0);

-- Verify it was created and fetched
SELECT * FROM usage_tracking WHERE user_id = 1;
```

---

### Part 4: Permission Tests

#### 4.1 Admin-Only Endpoints
- [ ] `/api/admin/users` returns 403 for non-admin
- [ ] `/api/admin/users/<id>/plan` returns 403 for non-admin
- [ ] `/api/admin/plans` returns 403 for non-admin

**Test**:
```bash
# As client user
curl -H "Authorization: Bearer {client_token}" \
  https://api.extratordedados.com.br/api/admin/users

# Should return:
# {"error":"Forbidden: Admin access required"}
```

#### 4.2 Client-Specific Data
- [ ] Free user can only see their own leads
- [ ] Pro user can only see their own leads
- [ ] Admin sees all system data (not implemented yet, future)

---

### Part 5: Edge Cases

#### 5.1 Exactly at Limit
- [ ] Free user with 100 leads viewed → still can view more (counter increments)
- [ ] Free user with 1 export used → next export blocked

**Expected**: Limit check is `<=` so exactly at limit still blocks

#### 5.2 Over Limit
- [ ] User manually set to negative usage (SQL) → should still work
- [ ] User with 0 exports can export
- [ ] User with 1 export cannot export twice

#### 5.3 Plan Changes Mid-Month
- [ ] User on free, 50 leads viewed
- [ ] Admin upgrades to pro
- [ ] Usage stays at 50 (doesn't reset)
- [ ] New limit is 5000, so user can view 4950 more

**Test**:
```bash
# User has viewed 50
curl -H "Authorization: Bearer {token}" \
  https://api.extratordedados.com.br/api/client/usage | jq '.usage.leads_viewed'
# Returns: 50

# Admin upgrades to pro
curl -X PUT -H "Authorization: Bearer {admin_token}" \
  -d '{"plan":"pro"}' \
  https://api.extratordedados.com.br/api/admin/users/2/plan

# Check usage again - should still be 50 but limit is now 5000
curl -H "Authorization: Bearer {token}" \
  https://api.extratordedados.com.br/api/client/usage | jq '.'
# Returns: leads_viewed: 50, leads_limit: 5000
```

---

## 🐛 Known Issues / Placeholder Features

- [ ] Upgrade button shows placeholder alert (not connected to payment)
- [ ] `/admin/users` page not yet created (use API)
- [ ] `/admin/plans` page not yet created (use API)
- [ ] Saved filters not yet implemented (Semana 2)
- [ ] Lead scoring not yet visible (Semana 2)

---

## ✅ Sign-Off Checklist

**Test Results**:
- [ ] All API endpoints responding correctly
- [ ] Usage counters incrementing properly
- [ ] Limit enforcement working (403 on exceeded)
- [ ] Monthly reset creating new entries
- [ ] Admin/client separation working
- [ ] UI displaying plan info correctly
- [ ] Banners showing at right times
- [ ] Export button disabling at limit
- [ ] Dark mode working
- [ ] Mobile responsive
- [ ] No TypeScript errors
- [ ] No console errors in browser
- [ ] Health check passing

**Data Integrity**:
- [ ] Database indexes created
- [ ] No orphaned records
- [ ] Foreign keys working
- [ ] Unique constraints enforced

**Performance**:
- [ ] API responses <200ms
- [ ] Frontend load <2s
- [ ] No memory leaks
- [ ] No database connection issues

---

## 📝 Notes for Tester

1. **Test with real data**: Create multiple users and test across different plans
2. **Check logs**: SSH to VPS and check `/var/log/gunicorn.log` for errors
3. **Monitor database**: Use `psql` to verify data consistency
4. **Browser console**: Open DevTools (F12) and check for any JS errors
5. **Network tab**: Check API calls are returning expected data
6. **Mobile testing**: Test on actual mobile device or use DevTools device emulation

---

**Expected Result**: ✅ All checks pass, ready for Semana 2 development
