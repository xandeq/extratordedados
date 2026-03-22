---
phase: 01-pipeline-100-automatico
plan: 03
type: execute
wave: 3
depends_on:
  - "01-PLAN"
  - "02-PLAN"
files_modified:
  - app/frontend/pages/admin/pipeline-config.tsx
  - app/frontend/pages/admin/index.tsx
autonomous: false
requirements:
  - FASE1-FRONT-01
  - FASE1-FRONT-02
  - FASE1-FRONT-03

must_haves:
  truths:
    - "Admin can navigate to /admin/pipeline-config from the admin index page"
    - "On /admin/pipeline-config, admin sees the current active niches list, can add/remove niches via checkboxes or input, pick region from a dropdown, and set execution hour"
    - "Clicking Save on /admin/pipeline-config calls PUT /api/admin/pipeline-config and shows a success toast"
    - "Admin index page shows a pipeline health card with: last run status (green/yellow/red), leads found yesterday, next scheduled run time, and a link to /admin/pipeline-config"
    - "Admin index pipeline card shows a 30-day history table with date, status, leads_found, duration columns"
  artifacts:
    - path: "app/frontend/pages/admin/pipeline-config.tsx"
      provides: "Pipeline config editor page"
      min_lines: 150
    - path: "app/frontend/pages/admin/index.tsx"
      provides: "Updated admin dashboard with pipeline health card"
  key_links:
    - from: "app/frontend/pages/admin/pipeline-config.tsx"
      to: "/api/admin/pipeline-config"
      via: "api.get() on mount, api.put() on save"
      pattern: "api\\.put.*pipeline-config"
    - from: "app/frontend/pages/admin/index.tsx"
      to: "/api/admin/pipeline/health"
      via: "api.get() on mount"
      pattern: "pipeline/health"
---

<objective>
Build the admin frontend pages: a pipeline config editor at /admin/pipeline-config (niche selector, region picker, hour input, notify email, healthcheck URL, Save button) and an updated admin index page with a pipeline health card showing last run status and 30-day history.

Purpose: This delivers the UI that makes the "operador abre o sistema de manhã" goal visible and actionable. Without these pages the backend work is invisible to users.

Output: Two .tsx files using existing patterns (Pages Router, Tailwind, Lucide icons, api.ts axios instance, dark mode via CSS class).
</objective>

<execution_context>
@C:/Users/acq20/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/acq20/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phases/01-pipeline-100-automatico/01-PLAN-SUMMARY.md
@.planning/phases/01-pipeline-100-automatico/02-PLAN-SUMMARY.md

<interfaces>
<!-- API contracts from Plans 01 and 02. Use these exactly. -->

GET /api/admin/pipeline-config response:
```json
{
  "niches":          ["restaurante", "academia", ...],
  "region":          "grande_vitoria_es",
  "hour":            3,
  "minute":          0,
  "notify_email":    "xandeq@gmail.com",
  "healthcheck_url": null
}
```

PUT /api/admin/pipeline-config request body (all fields optional):
```json
{
  "niches":          ["restaurante", "academia"],
  "region":          "grande_vitoria_es",
  "hour":            3,
  "minute":          0,
  "notify_email":    "xandeq@gmail.com",
  "healthcheck_url": "https://hc-ping.com/uuid"
}
```
PUT response: `{"success": true}`

GET /api/admin/pipeline/health response:
```json
{
  "last_run": {
    "id": 42,
    "status": "completed",
    "started_at": "2026-03-22T02:00:00",
    "finished_at": "2026-03-22T05:30:00",
    "leads_found": 340,
    "leads_sanitized": 280,
    "leads_synced": 210,
    "error_message": null,
    "region_used": "grande_vitoria_es",
    "duration_min": 210.0
  },
  "next_scheduled": "03:00 America/Sao_Paulo",
  "stats_30d": {
    "total": 25,
    "successful": 23,
    "avg_leads": 287.5,
    "max_leads": 560
  },
  "scheduler_running": true,
  "config": {
    "niches": ["restaurante", "academia"],
    "region": "grande_vitoria_es",
    "hour":   3
  }
}
```

GET /api/admin/daily-job/status response (existing — for 30-day history table):
```json
{
  "jobs": [
    {
      "id": 42,
      "started_at": "2026-03-22T02:00:00",
      "finished_at": "2026-03-22T05:30:00",
      "status": "completed",
      "leads_found": 340,
      "leads_sanitized": 280,
      "leads_synced": 210,
      "region": "grande_vitoria_es",
      "niches": ["restaurante"]
    }
  ],
  "next_scheduled": "03:00 (America/Sao_Paulo)",
  "default_region": "grande_vitoria_es"
}
```

Existing frontend patterns (from app/frontend/pages/admin/index.tsx and massive-search.tsx):
```typescript
import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/router'
import api from '../../lib/api'           // axios with Bearer token
import { useToast } from '../../components/Toast'
import { formatDate, formatNumber } from '../../lib/formatters'
// Dark mode: use className strings directly — NEVER @apply in globals.css
// Tailwind dark: prefix, e.g.: "bg-white dark:bg-gray-900"
// Icons: import individually from 'lucide-react'
```

Available regions (hardcoded in frontend — matches SEARCH_REGIONS backend keys):
```typescript
const REGIONS = [
  { id: 'grande_vitoria_es', label: 'Grande Vitória (ES)' },
  { id: 'grande_sp',         label: 'Grande São Paulo (SP)' },
  { id: 'grande_rj',         label: 'Grande Rio de Janeiro (RJ)' },
  { id: 'grande_bh',         label: 'Grande Belo Horizonte (MG)' },
]
```

PREDEFINED_NICHES (same pattern as massive-search.tsx):
```typescript
const PIPELINE_NICHES = [
  'restaurante', 'academia', 'clinica medica', 'dentista', 'advocacia',
  'contabilidade', 'imobiliaria', 'salao de beleza', 'farmacia', 'supermercado',
  'pizzaria', 'auto pecas', 'mecanica', 'escola', 'hotel', 'pousada',
  'sorveteria', 'padaria', 'pet shop',
]
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create /admin/pipeline-config page (config editor)</name>
  <files>app/frontend/pages/admin/pipeline-config.tsx</files>

  <read_first>
    - app/frontend/pages/admin/massive-search.tsx lines 1-100 (page structure, niche selection pattern, dark mode classes)
    - app/frontend/pages/admin/index.tsx lines 1-80 (admin auth redirect pattern, api call pattern)
    - app/frontend/styles/globals.css (confirm no @apply — CSS raw only)
    - app/frontend/lib/api.ts (confirm axios baseURL and interceptor)
  </read_first>

  <action>
Create `app/frontend/pages/admin/pipeline-config.tsx` with the following structure and behavior:

**Imports:**
```typescript
import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import {
  Settings, Save, RefreshCw, Clock, MapPin, Hash,
  Mail, Link as LinkIcon, CheckSquare, Square, Plus, X, AlertCircle
} from 'lucide-react'
import api from '../../lib/api'
import { useToast } from '../../components/Toast'
```

**State:**
```typescript
interface PipelineConfig {
  niches: string[]
  region: string
  hour: number
  minute: number
  notify_email: string | null
  healthcheck_url: string | null
}
```

**On mount:** `api.get('/api/admin/pipeline-config')` → populate form state. Auth redirect: if 401 → `router.push('/login')`.

**Form sections:**

1. **Niches section** — Show `PIPELINE_NICHES` as a grid of toggle buttons (checkbox-style). Selected niches highlighted in `bg-blue-600 text-white`, unselected in `bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300`. Also an "Add custom niche" input (text + Enter key or Add button) to append to the list.

2. **Region section** — `<select>` dropdown with `REGIONS` options.

3. **Schedule section** — Hour input (number, 0-23) and Minute input (number, 0-59). Label: "Horário de execução (America/Sao_Paulo)".

4. **Notifications section** — Email input (type="email") for notify_email. Text input for healthcheck_url with placeholder "https://hc-ping.com/uuid". Small helper text: "Deixe em branco para desativar".

5. **Save button** — Calls `api.put('/api/admin/pipeline-config', formData)`. On success: `toast.success('Configuração salva')`. On error: `toast.error('Erro ao salvar')`.

**Dark mode:** All containers use `bg-white dark:bg-gray-800`, text uses `text-gray-900 dark:text-gray-100`, borders use `border-gray-200 dark:border-gray-700`.

**CRITICAL styling rules:**
- Use Tailwind classes only — no inline style tags, no CSS modules
- NEVER use `@apply` — this is a .tsx file so irrelevant, but avoid any custom style imports
- globals.css is NOT modified by this task

**Page layout:** Standard admin layout matching existing pages — full-width max-w-4xl container, page title with icon, section cards with rounded border, spacing consistent with index.tsx.

**Back link:** `<Link href="/admin">← Admin</Link>` at the top.
  </action>

  <verify>
    <automated>cd "C:/Users/acq20/Desktop/Trabalho/Alexandre Queiroz Marketing Digital/DIAX/extrator-de-dados/app/frontend" && npx tsc --noEmit --skipLibCheck 2>&1 | grep -E "pipeline-config|error TS" | head -20</automated>
  </verify>

  <acceptance_criteria>
    - File exists: app/frontend/pages/admin/pipeline-config.tsx
    - grep confirms `api.get('/api/admin/pipeline-config')` in the file
    - grep confirms `api.put('/api/admin/pipeline-config'` in the file
    - grep confirms `PIPELINE_NICHES` constant array in the file
    - grep confirms `REGIONS` constant array in the file
    - grep confirms `notify_email` state/form field in the file
    - grep confirms `healthcheck_url` state/form field in the file
    - grep confirms `dark:bg-gray-800` or similar dark mode class (not @apply)
    - TypeScript check: `npx tsc --noEmit --skipLibCheck` produces no errors for this file
    - File is at least 150 lines (substantive implementation, not stub)
  </acceptance_criteria>

  <done>Pipeline config editor page at /admin/pipeline-config: loads config from API, shows niche toggles, region picker, schedule inputs, notification fields, Save button.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>
    Backend endpoints (Plans 01-02): GET/PUT /api/admin/pipeline-config, GET /api/admin/pipeline/health, Brevo email report, healthchecks.io ping, pipeline_config DB table.

    Frontend (Task 1 of this plan): /admin/pipeline-config editor page.
  </what-built>

  <how-to-verify>
    1. Deploy backend: `python deploy.py backend` then `curl https://api.extratordedados.com.br/api/health` — expect {"status":"ok"}

    2. Test config endpoint (replace TOKEN with a valid admin token from login):
       ```
       curl -H "Authorization: Bearer TOKEN" https://api.extratordedados.com.br/api/admin/pipeline-config
       ```
       Expect: JSON with keys niches, region, hour, minute, notify_email, healthcheck_url

    3. Test health endpoint:
       ```
       curl -H "Authorization: Bearer TOKEN" https://api.extratordedados.com.br/api/admin/pipeline/health
       ```
       Expect: JSON with keys last_run, next_scheduled, stats_30d, scheduler_running

    4. Deploy frontend: `python deploy.py frontend`

    5. Visit https://extratordedados.com.br/admin/pipeline-config — log in if needed
       - Confirm niches grid is visible with toggleable buttons
       - Confirm region dropdown shows all 4 regions
       - Confirm hour/minute inputs are present
       - Confirm notify_email and healthcheck_url fields are present
       - Toggle 2-3 niches, change the hour, click Save — confirm success toast appears
       - Reload page — confirm the saved changes are persisted (niches and hour match what was saved)

    6. Put a valid email in notify_email, save, then manually trigger a test pipeline run:
       ```
       curl -X POST -H "Authorization: Bearer TOKEN" https://api.extratordedados.com.br/api/admin/daily-job/run
       ```
       (This is a quick check that the pipeline still starts — full email verification takes hours)
  </how-to-verify>

  <resume-signal>Type "approved" if all checks pass, or describe specific issues found</resume-signal>
</task>

<task type="auto">
  <name>Task 3: Add pipeline health card + 30-day history to admin index page</name>
  <files>app/frontend/pages/admin/index.tsx</files>

  <read_first>
    - app/frontend/pages/admin/index.tsx (full file — understand existing state, data fetching, QUICK_LINKS, card layout)
    - app/frontend/pages/admin/pipeline-config.tsx (the page just created — link to it)
  </read_first>

  <action>
Update `app/frontend/pages/admin/index.tsx` to:

**Step 1: Add health data fetching**

Add a new state interface and fetch:
```typescript
interface PipelineHealth {
  last_run: {
    status: string
    started_at: string
    finished_at: string | null
    leads_found: number
    leads_sanitized: number
    leads_synced: number
    error_message: string | null
    region_used: string
    duration_min: number | null
  } | null
  next_scheduled: string
  stats_30d: {
    total: number
    successful: number
    avg_leads: number
    max_leads: number
  }
  scheduler_running: boolean
  config: {
    region: string
    hour: number
    niches: string[]
  }
}
```

In the existing `useEffect` (or a new one), add:
```typescript
api.get('/api/admin/pipeline/health')
  .then(res => setPipelineHealth(res.data))
  .catch(() => setPipelineHealth(null))
```

Also fetch 30-day history:
```typescript
api.get('/api/admin/daily-job/status')
  .then(res => setPipelineJobs(res.data.jobs || []))
  .catch(() => setPipelineJobs([]))
```

**Step 2: Add Pipeline Config link to QUICK_LINKS**

Add to the QUICK_LINKS array:
```typescript
{
  href: '/admin/pipeline-config',
  label: 'Pipeline Automático',
  description: 'Nichos, região, horário e relatórios',
  icon: Settings,           // import Settings from lucide-react
  color: 'text-orange-600 dark:text-orange-400',
  bg: 'bg-orange-50 dark:bg-orange-900/20',
},
```

**Step 3: Add health card to the page JSX**

Insert a new card section after the existing summary stats grid and before the quick links. The card has:

- **Header**: "Pipeline Automático" title + `<Link href="/admin/pipeline-config">Configurar</Link>` button
- **Status row**: colored badge based on `last_run.status`:
  - `completed` → green badge "Concluído"
  - `failed` → red badge "Falhou"
  - `running` → yellow badge "Rodando..."
  - null (never ran) → gray badge "Nunca executou"
- **Metrics row** (4 mini cards): "Leads ontem" (last_run.leads_found), "Próxima execução" (next_scheduled), "Taxa 30d" (successful/total × 100 %), "Média leads" (stats_30d.avg_leads)
- **History table** (last 10 runs from pipelineJobs state):
  - Columns: Data, Região, Leads, Sanitizados, Sincronizados, Status, Duração
  - Status colored: completed=green, failed=red, running=yellow
  - Date formatted with `formatDate(job.started_at)`
  - Duration: `job.finished_at && job.started_at` → compute minutes or show "—"
  - Empty state: "Nenhuma execução registrada"

Dark mode classes: consistent with rest of file (`bg-white dark:bg-gray-800`, etc.)

Do NOT break existing page functionality — only ADD new state variables, imports, and JSX sections.
  </action>

  <verify>
    <automated>cd "C:/Users/acq20/Desktop/Trabalho/Alexandre Queiroz Marketing Digital/DIAX/extrator-de-dados/app/frontend" && npx tsc --noEmit --skipLibCheck 2>&1 | grep -E "admin/index|error TS" | head -20</automated>
  </verify>

  <acceptance_criteria>
    - grep confirms `pipeline/health` in app/frontend/pages/admin/index.tsx (API call)
    - grep confirms `pipeline-config` href in QUICK_LINKS or JSX link in the file
    - grep confirms `stats_30d` or `pipelineHealth` state usage in JSX (health data rendered)
    - grep confirms `pipelineJobs` state with history table rows (or similar variable name)
    - grep confirms status badge logic: `completed` mapped to green color class
    - TypeScript check produces no errors for admin/index.tsx
    - Existing QUICK_LINKS still intact (users, plans, leads, logs links not removed)
  </acceptance_criteria>

  <done>Admin index shows pipeline health card with last run status, 4 metrics, 30-day history table, and link to /admin/pipeline-config.</done>
</task>

</tasks>

<verification>
After all tasks and checkpoint:

```bash
# TypeScript
cd app/frontend && npx tsc --noEmit --skipLibCheck 2>&1 | head -20

# File existence
ls app/frontend/pages/admin/pipeline-config.tsx
grep -c "api.put.*pipeline-config" app/frontend/pages/admin/pipeline-config.tsx

# Admin index updated
grep -n "pipeline/health" app/frontend/pages/admin/index.tsx
grep -n "pipeline-config" app/frontend/pages/admin/index.tsx

# Full build
cd app/frontend && npx next build 2>&1 | tail -20
```
</verification>

<success_criteria>
- /admin/pipeline-config page renders, loads config from API, saves changes, shows success toast
- Saving niches/hour via UI calls PUT /api/admin/pipeline-config and change is reflected on page reload
- Admin index page shows pipeline health card with status color, leads count, next run time
- Admin index history table shows last 10 pipeline runs with status, leads, duration
- `npx next build` completes without errors
- All existing admin pages still work (users, plans, logs)
</success_criteria>

<output>
After completion, create `.planning/phases/01-pipeline-100-automatico/03-PLAN-SUMMARY.md` with:
- What was implemented
- Pages created and key features
- Any deviations from the plan
- Deploy command to apply changes
</output>
