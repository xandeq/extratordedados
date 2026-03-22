# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão Geral
Sistema web de extração automatizada de leads empresariais (emails, telefones, WhatsApp, redes sociais, CNPJ). Permite scraping de URLs, busca por motores de busca, importação JSON, extração de texto e colagem direta. Inclui CRM básico, CRM sync externo, export multi-formato, dashboard analítico, busca massiva (7 métodos paralelos) e pipeline diário automatizado.

**Métodos de extração**: Scraping tradicional (requests+BeautifulSoup), Playwright (Google Maps, LinkedIn), Instagram API (instaloader), Busca em motores (DuckDuckGo, Bing), APIs de enrichment (Hunter.io, Snov.io), Local Business Data (RapidAPI), Diretórios BR (empresas.com.br, Páginas Amarelas, Catálogo.br, GuiaMais, TeleListas, Apontador), Apify (Google Maps actor: `lukaskrivka~google-maps-with-contact-details`)

## Arquitetura

### Backend
- **Framework**: Flask (Python 3) — monolito em `project/backend/app.py` (~10k+ linhas)
- **Módulos auxiliares**: `lead_enrichment.py` (enrichment externo), `scraping_apify_massive.py` (Apify actor jobs)
- **Banco**: PostgreSQL 16 (Docker container na VPS)
- **Pool**: psycopg2 ThreadedConnectionPool (1-10 conexões) — thread-safe
- **Rate Limiting**: Flask-Limiter (200/hour default, memory storage per worker) — **tech debt**: Redis não instalado no VPS; rate limits são por worker (2×), não globais. Para globalizar: instalar Redis + `pip install flask-limiter[redis]` + `storage_uri="redis://localhost:6379"`
- **CORS**: Flask-CORS restrito a `extratordedados.com.br` e `localhost:3000`
- **Proxy**: Traefik → Gunicorn (2 workers, 120s timeout)
- **Background Jobs**: `threading.Thread(daemon=True)` com conexão dedicada ao DB
- **Scheduler**: APScheduler `BackgroundScheduler` — pipeline diário às 02:00 + CRM sync automático às 09:00 (pytz America/Sao_Paulo)
- **Scraping Básico**: requests + BeautifulSoup4 + lxml
- **Scraping Avançado**: Playwright (Chromium headless) + Instaloader
- **Anti-blocking**: User-Agent rotation (30+ agents), delays obrigatórios, CAPTCHA detection, SafetyTracker

### Frontend
- **Framework**: Next.js 13.4 (Pages Router, `output: 'export'`)
- **UI**: Tailwind CSS 3.4, Lucide React icons, Framer Motion
- **Charts**: Recharts
- **HTTP**: Axios com interceptor de token (Bearer), redirect 401 → /login
- **Build**: HTML estático no `/out/`, `trailingSlash: true`, imagens `unoptimized`

### Infraestrutura
- **VPS**: 185.173.110.180 (root SSH) — Flask/Gunicorn + PostgreSQL Docker
- **Backend URL**: https://api.extratordedados.com.br
- **Frontend URL**: https://extratordedados.com.br (HostGator FTP)
- **Banco**: PostgreSQL em Docker (porta 5432, db: extrator, user: extrator)
- **CRM Externo**: https://api.alexandrequeiroz.com.br (xandeq@gmail.com)
- **Credenciais**: AWS SM `extratordedados/prod` (primário) → `.deploy.env` (fallback)

## Deploy

### Skill `/deploy-extrator` (`.claude/commands/deploy-extrator.md`)
Específica deste projeto — faz deploy do backend para a VPS e do frontend para o HostGator.

**Modos:**
- `/deploy-extrator` ou `/deploy-extrator all` → backend + frontend
- `/deploy-extrator backend` → apenas backend (SSH → VPS)
- `/deploy-extrator frontend` → apenas frontend (build Next.js + FTP)

**O que o script faz:**

| Etapa | Backend | Frontend |
|-------|---------|----------|
| 1 | Backup de `app.py` no VPS | `npx next build` (gera `/out/`) |
| 2 | Upload via SFTP (app.py + requirements.txt) | Recria `.htaccess` no `/out/` |
| 3 | `pip install -r requirements.txt` | Upload FTP recursivo para `/extratordedados.com.br` |
| 4 | `systemctl restart extrator-api` | — |
| 5 | Health check `GET /api/health` | Relatório: N arquivos, N erros |

**Credenciais** (lidas pelo `deploy.py` na raiz):
- AWS SM `extratordedados/prod` (timeout 10s, via boto3)
- Fallback: `.deploy.env` na raiz (gitignored) — formato `KEY=value`
- Chaves usadas: `VPS_HOST`, `VPS_USER`, `VPS_PASS`, `DB_PASS`, `FTP_HOST`, `FTP_USER`, `FTP_PASS`

**Execução direta (sem a skill):**
```bash
python deploy.py          # all (backend + frontend)
python deploy.py backend
python deploy.py frontend
```

**Verificação pós-deploy:**
```bash
curl https://api.extratordedados.com.br/api/health
# Espera: {"status":"ok","db":"postgresql","timestamp":"..."}
```

### .htaccess (obrigatório — recriado automaticamente pelo deploy.py)
```apache
RewriteEngine On
RewriteRule ^batch/(.+)$ /batch/[id].html [L]
RewriteRule ^results/(.+)$ /results/[id].html [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteCond %{REQUEST_FILENAME}.html -f
RewriteRule ^(.*)$ $1.html [L]
```

## Estrutura de Arquivos

```
project/
  backend/
    app.py              # Monolito Flask (~9200 linhas)
    requirements.txt    # Flask, psycopg2, playwright, APScheduler, rapidfuzz, ftfy, etc.
  frontend/
    pages/
      _app.tsx          # Layout global, Head, ToastProvider
      login.tsx         # Autenticação
      dashboard.tsx     # Analytics com Recharts
      scrape.tsx        # Hub de extração (tabs: busca, url, json, texto, colar)
      leads.tsx         # CRM com filtros, bulk actions, drawer, botão Sanitizar, Send to CRM
      massive-search.tsx # Busca massiva 7 métodos — PÁGINA PRINCIPAL
      app-logs.tsx      # Centro de diagnóstico — logs com classificação de erros + AI prompts
      plans.tsx         # Planos e uso (free/paid) — usa useClientPlan hook
      batch/[id].tsx    # Progresso e resultados de batch
      results/[id].tsx  # Resultados de job individual
      admin/
        index.tsx       # Admin dashboard
        users.tsx       # Gerenciamento de usuários
        plans.tsx       # Gerenciamento de planos
        massive-search.tsx  # Admin: busca massiva centralizada
    components/
      Layout.tsx        # Wrapper com keyboard shortcuts, transitions
      Header.tsx        # Cabeçalho com UserMenu
      Sidebar.tsx       # Navegação lateral, dark mode toggle
      UserMenu.tsx      # Menu do usuário logado (avatar, logout)
      ExportModal.tsx   # Modal de exportação (CSV, JSON, WhatsApp, etc.)
      PlanCard.tsx      # Card de plano/uso (limites de leads/exports)
      UpgradeModal.tsx  # Modal de upgrade de plano
      InfoBox.tsx       # Caixas informativas com ícones Lucide
      Tooltip.tsx       # Tooltips de hover para rate limits/descrições
    lib/
      api.ts            # Axios instance, baseURL, token interceptor
      useClientPlan.ts  # Hook: busca /api/client/usage, expõe canViewLeads(), canExport()
    styles/
      globals.css       # Dark mode com CSS raw (NUNCA @apply)
    public/
      logo.png          # 800x200 horizontal
      favicon.png       # 512x512 cube
    next.config.js      # output: 'export', trailingSlash: true, images unoptimized
    tailwind.config.js  # darkMode: 'class', cores primary blue
deploy.py               # Deploy unificado (SSH backend + FTP frontend)
.deploy.env             # Credenciais (gitignored) — VPS_PASS, DB_PASS, FTP_PASS
.claude/commands/
  deploy-extrator.md    # Skill /deploy-extrator (específica deste projeto)
```

## Database Schema (12 tabelas)

| Tabela | Propósito e Colunas Chave |
|--------|--------------------------|
| **users** | id, username, password_hash (SHA-256), is_admin, created_at |
| **sessions** | id, user_id, token (64 chars), expires_at (7 dias) |
| **jobs** | Scraping URL único — id, user_id, url, status, results_count |
| **emails** | Emails extraídos — id, job_id, email, source_url, context |
| **batches** | Batches de URLs — id, user_id, name, status, total_urls, total_leads |
| **leads** | Leads master — company_name, email, phone, website, city, state, category, source, instagram, facebook, linkedin, twitter, youtube, whatsapp, cnpj, address, crm_status, tags, notes, contact_name, quality_score, cnpj_enriched, lead_score, extra_data (JSONB). UNIQUE(batch_id, email) |
| **search_jobs** | Tarefas de busca — id, batch_id, niche, city, state, engine, status, total_results, total_leads |
| **search_logs** | Logs detalhados — id, search_job_id, log_type, url, status_code, duration_ms |
| **api_configs** | Chaves de API por usuário — user_id, provider, api_key, api_secret |
| **api_usage** | Créditos mensais — user_id, provider, month_year, credits_used |
| **api_cache** | Cache de domínios 30 dias — domain, provider, response_data, expires_at |
| **daily_jobs** | Histórico pipeline — started_at, finished_at, status, batch_id, leads_found, leads_sanitized, leads_synced, niches_used, region_used |

**CRM statuses (enum)**: `novo`, `contatado`, `interessado`, `negociando`, `cliente`, `descartado`

## Rotas API

### Auth / Config
- `POST /api/login` — username + password → token (64 chars, 7 dias)
- `GET /api/me` — usuário autenticado
- `GET|POST /api/api-config` — chaves (hunter, snov, bing_api, google_cse)
- `DELETE /api/api-config/<provider>`

### Extração Básica
- `POST /api/scrape` — job único (url)
- `GET /api/results/<job_id>` — resultados + export
- `GET /api/results` — listar jobs
- `POST /api/batch` — batch (urls[], name, deep_crawl, category, city, state)
- `GET /api/batch` / `GET /api/batch/<id>` — listar / detalhar
- `GET /api/batch/<id>/progress` — progresso polling 3s
- `GET /api/batch/<id>/export` — exportar
- `DELETE /api/batch/<id>`

### Busca em Motores
- `POST /api/search` — busca por nicho+cidade (3/hour)
- `GET /api/search/<batch_id>/progress` — progresso + sub-jobs por cidade
- `GET /api/search/<batch_id>/logs` — logs de execução
- `GET /api/regions` — regiões pré-configuradas
- `POST /api/search-api` — busca + API enrichment Hunter/Snov (3/hour)

### Busca Massiva ⭐ (feature principal)
- `POST /api/search/massive` — 7 métodos paralelos em threads (10/hour)
  - Métodos: `api_enrichment`, `search_engines`, `google_maps`, `directories`, `instagram`, `linkedin`, `local_business_data`
  - Params: `niches[]`, `region` ou `city`/`state`, `methods[]`, `max_pages`
  - Limites internos: api 3×1, search_engines 3 niches, google_maps 2×2, directories 5×5, instagram 2×2, linkedin 2×2, local_biz 5×3
  - Inicia 7 threads daemon + auto-sync CRM ao final

### Scrapers Avançados
- `POST /api/scrape/google-maps` — Playwright (5/hour)
- `POST /api/scrape/instagram` — Instaloader (3/hour)
- `POST /api/scrape/linkedin` — Playwright (2/hour)

### Leads / CRM
- `GET /api/leads` — listagem com filtros, paginação, sort
- `GET /api/leads/<id>` — lead individual
- `PUT /api/leads/<id>` — atualizar (crm_status, tags, notes, contact_name)
- `DELETE /api/leads/<id>` — deletar
- `PUT /api/leads/bulk-status` / `PUT /api/leads/bulk-tag` — ações em massa
- `POST /api/leads/bulk-delete` — deletar em massa (max 500)
- `POST /api/leads/import` — importar leads JSON
- `POST /api/leads/sanitize` — fix encoding, validar emails, dedup (5/min)
- `POST /api/leads/fuzzy-dedup` — deduplicação fuzzy (rapidfuzz)
- `POST /api/leads/auto-tag` — auto-categorização por nome
- `POST /api/leads/enrich-cnpj` — CNPJ enrichment via BrasilAPI (gratuito)
- `GET /api/leads/export/csv` / `GET /api/leads/export/json`
- `POST /api/leads/export/marketing` — WhatsApp, email, telemarketing

### CRM Sync Externo
- `GET /api/crm/status` — status da conexão
- `POST /api/crm/sync-all` — sincronizar (2/hour, max 200 por run)
- `POST /api/crm/refine` — sanitizar + sincronizar (2/hour)

### Pipeline Diário (Admin)
- `GET /api/admin/daily-job/status` — últimas 10 execuções
- `POST /api/admin/daily-job/run` — disparar manualmente (2/hour)

### Admin
- `GET /api/admin/users` — listar usuários
- `GET/PUT /api/admin/users/<id>` — detalhar/atualizar usuário
- `GET /api/admin/plans` — listar planos
- `GET /api/admin/massive-search` — histórico de buscas massivas (admin view)

### Client / Plans
- `GET /api/client/usage` — plano atual + limites + uso mensal (leads_viewed, leads_exported)

### Dashboard / Misc
- `GET /api/analytics` — métricas do dashboard
- `GET /api/health` — health check
- `POST /api/enrich/external` — enrichment via APIs externas

## Rate Limits

| Endpoint | Limite |
|----------|--------|
| Default | 200/hour |
| `/api/search` | 3/hour |
| `/api/search/massive` | 10/hour |
| `/api/search-api` | 3/hour |
| `/api/scrape/google-maps` | 5/hour |
| `/api/scrape/instagram` | 3/hour |
| `/api/scrape/linkedin` | 2/hour |
| `/api/leads/sanitize` | 5/min |
| `/api/crm/sync-all` | 2/hour |
| `/api/crm/refine` | 2/hour |
| `/api/admin/daily-job/run` | 2/hour |

## Funções de Scraping Chave

```python
# Motores de busca
search_duckduckgo(query, max_pages=2, safety)          # DDG HTML (primário)
search_bing(query, max_pages=2, safety)                # Bing HTML (fallback)
search_with_fallback(query, ...)                       # Orchestrador com retry

# Scrapers avançados
scrape_google_maps(niche, city, state, max_results=20) # Playwright
scrape_instagram_business(niche, city, state, ...)     # Instaloader
scrape_linkedin_companies(niche, city, state, ...)     # Playwright

# Diretórios BR
scrape_empresas_com_br(niche, city, state, max_pages=2)
scrape_paginas_amarelas(niche, city, max_pages=2)
scrape_catalogo_br(niche, city, state, max_pages=2)
scrape_all_directories(niche, city, state, session)    # Orchestrador

# RapidAPI
search_local_business_data(niche, city, state, max_results=3) # Free 500/mês
get_rapidapi_key()                                             # AWS SM com cache

# Enrichment
enrich_domain_hunter(domain, api_key)  # Hunter.io
enrich_cnpj_brasilapi(cnpj)            # BrasilAPI (gratuito)

# Processadores massivos (cada um é uma thread daemon)
process_api_search_job()                    # Thread 1: API Enrichment
process_search_job()                        # Thread 2: Motores de busca
process_google_maps_massive()               # Thread 3: Google Maps Playwright
process_directories_massive()               # Thread 4: Diretórios BR
process_instagram_massive()                 # Thread 5: Instagram
process_linkedin_massive()                  # Thread 6: LinkedIn
process_local_business_data_massive()       # Thread 7: RapidAPI Local Biz
```

## Pipeline Diário (APScheduler)

- **Agendado**: 02:00 America/Sao_Paulo
- **Guard de double-fire**: verifica `daily_jobs` nos últimos 5 min (evita disparo duplo com Gunicorn 2 workers)
- **Padrão**: niches=[Clinica Medica, Clinica Odontologica, Clinica Veterinaria], região=grande_vitoria_es
- **Sequência**: massive search (7 threads) → aguarda → sanitize → sync CRM → registra em `daily_jobs`
- **Trigger manual**: `POST /api/admin/daily-job/run`

## CRM Sync

- Auto-sync disparado após cada batch/search completado (`auto_sync_new_leads_background()`)
- Sync diário agendado às 09:00 America/Sao_Paulo (APScheduler)
- Destino padrão: `https://api.alexandrequeiroz.com.br` (xandeq@gmail.com)
- "Send to CRM" na página de Leads: permite enviar para CRM externo com URL + token configuráveis
- Credenciais no AWS SM `extratordedados/prod` — chaves `CRM_EMAIL`, `CRM_PASS`
- Normalização de campos antes do sync (branch `feat/crm-sync-normalization`)
- Max 200 leads por sync, deduplica antes de enviar

## Convenções de Código

### Backend (Python)
- Monolito em `backend/app.py` — código novo vai aqui; `lead_enrichment.py` e `scraping_apify_massive.py` são exceções já existentes que podem ser importados
- Funções de scraping são `sync` (requests, não async)
- Background jobs via `threading.Thread(daemon=True)` com conexão DB dedicada
- Rate limiting via `@limiter.limit()`
- Auth via `verify_token(get_auth_header())`
- Tratar `psycopg2.errors.DuplicateColumn` no `ALTER TABLE` com `conn.rollback()`
- Logs com `print()` (capturados pelo Gunicorn)
- **Lambda closure**: usar default args `lambda n=niche, c=city:` para evitar late-binding em loops

### Resiliência em Jobs Massivos (CRÍTICO)
- `_massive_retry(fn, provider, query, max_attempts=3)` — retry com backoff, nunca raise
- Flag `quota_exceeded=True` → jobs restantes marcados como `failed/quota_exceeded` e pulados com `continue` (nunca para o loop)
- `try/except` em cada update de DB para não interromper o fluxo
- **Regra**: a busca massiva **sempre chega ao final**, independente de falhas individuais

### Frontend (TypeScript/React)
- Pages Router — **não** App Router
- Static export: sem SSR, sem API routes
- **CRÍTICO**: Em `globals.css`, usar CSS raw (`color: #xxx`) — **NUNCA `@apply`** (dependência circular)
- TypeScript: Tipar retorno de `.match()` como `string[]` (evita tipo `never`)
- Ícones: Lucide React (importar individualmente)
- Animações: Framer Motion para page transitions no `Layout`
- Dark mode: `darkMode: 'class'` no Tailwind, toggle via class no `<html>`

## Regras Anti-Blocking

- **NUNCA** usar Google Search direto (bloqueio imediato)
- DuckDuckGo HTML (`html.duckduckgo.com/html/`) como motor primário; Bing como fallback
- Delays **obrigatórios**: 5-15s entre páginas de busca, 3-8s entre sites crawlados, 10-20s entre cidades
- User-Agent rotation (30+ agents), CAPTCHA detection → pause automático
- SafetyTracker com backoff exponencial, max 2-3 páginas por busca
- **Skip domains**: facebook.com, instagram.com, twitter.com, linkedin.com, youtube.com, tiktok.com, pinterest.com, mercadolivre.com.br, olx.com.br, amazon.com.br, gov.br, wikipedia.org, tripadvisor.com

## Regiões Pré-configuradas (`SEARCH_REGIONS`)

- **grande_vitoria_es**: Vitória, Vila Velha, Serra, Cariacica, Viana, Guarapari, Fundão
- **grande_sp**, **grande_rj**, **grande_bh** (expansível)

## Erros Comuns

| Erro | Causa | Fix |
|------|-------|-----|
| `Property X does not exist on type 'never'` | `.match()` sem tipo | Tipar como `string[]` |
| Dark mode circular dependency | `@apply` em globals.css | Usar CSS raw |
| 404 em `/batch/123` ou `/results/123` | `.htaccess` ausente no build | `deploy.py` recria automaticamente |
| `DuplicateColumn` no `ALTER TABLE` | Coluna já existe | `try/except` + `conn.rollback()` |
| Double-fire APScheduler | Gunicorn 2 workers | Guard na tabela `daily_jobs` (janela 5 min) |
| Lambda late-binding em closures | `lambda: fn(var)` em loop | `lambda v=var: fn(v)` |
| `name 'fn' is not defined` em threads | Nome de função errado | Verificar nome exato no módulo |
| Quota RapidAPI esgotada | 500 leads/mês free tier | Flag `quota_exceeded`, nunca para o workflow |
| AWS SM timeout no Windows | boto3 lento | Timeout 10s + fallback `.deploy.env` |
| 403 em `/registros` no HostGator | Servidor bloqueia rota por nome | Rota renomeada para `/app-logs` — não voltar para `/registros` |
