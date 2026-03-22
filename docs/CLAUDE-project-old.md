# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão Geral
Sistema web de extração automatizada de leads empresariais (emails, telefones, WhatsApp, redes sociais, CNPJ). Permite scraping de URLs, busca por motores de busca, importação JSON, extração de texto e colagem direta. Inclui CRM básico, CRM sync externo, export multi-formato, dashboard analítico, busca massiva (7 métodos paralelos) e pipeline diário automatizado.

**Métodos de extração**: Scraping tradicional (requests+BeautifulSoup), Playwright (Google Maps, LinkedIn), Instagram API (instaloader), Busca em motores (DuckDuckGo, Bing), APIs de enrichment (Hunter.io, Snov.io), Local Business Data (RapidAPI), Diretórios BR (empresas.com.br, Páginas Amarelas, Catálogo.br, GuiaMais, TeleListas, Apontador)

## Arquitetura

### Backend
- **Framework**: Flask (Python 3) — monolito em `backend/app.py` (~9200 linhas)
- **Banco**: PostgreSQL 16 (Docker container na VPS)
- **Pool**: psycopg2 SimpleConnectionPool (1-10 conexões)
- **Rate Limiting**: Flask-Limiter (200/hour default, memory storage)
- **CORS**: Flask-CORS (aberto)
- **Proxy**: Traefik → Gunicorn (2 workers, 120s timeout)
- **Background Jobs**: `threading.Thread(daemon=True)` com conexão dedicada ao DB
- **Scheduler**: APScheduler `BackgroundScheduler` — pipeline diário às 02:00 (pytz America/Sao_Paulo)
- **Scraping Básico**: requests + BeautifulSoup4 + lxml
- **Scraping Avançado**: Playwright (Chromium headless) + Instaloader
- **Anti-blocking**: User-Agent rotation (30+ agents), delays obrigatórios, CAPTCHA detection, SafetyTracker

### Frontend
- **Framework**: Next.js 13.4 (Pages Router, `output: 'export'`)
- **UI**: Tailwind CSS 3.4, Lucide React icons, Framer Motion
- **Charts**: Recharts
- **HTTP**: Axios com interceptor de token (Bearer)
- **Build**: HTML estático no `/out/`, `trailingSlash: true`, imagens `unoptimized`

### Infraestrutura
- **VPS**: 185.173.110.180 (root SSH) — Flask/Gunicorn + PostgreSQL
- **Backend URL**: https://api.extratordedados.com.br
- **Frontend URL**: https://extratordedados.com.br (HostGator FTP)
- **Banco**: PostgreSQL em Docker (porta 5432, db: extrator, user: extrator)
- **CRM Externo**: https://api.alexandrequeiroz.com.br (xandeq@gmail.com)
- **Credenciais**: AWS SM `extratordedados/prod` (primário) → `.deploy.env` (fallback)

## Comandos de Desenvolvimento

```bash
# Deploy completo (backend + frontend)
python deploy.py

# Deploy seletivo
python deploy.py backend
python deploy.py frontend

# Build frontend local (gera /out/)
cd frontend && npx next build

# Health check
curl https://api.extratordedados.com.br/api/health
```

**Skill de deploy**: `/deploy` (`.claude/commands/deploy.md`) — executa `deploy.py` automaticamente.

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
      leads.tsx         # CRM com filtros, bulk actions, drawer, Sanitizar button
      massive-search.tsx # Busca massiva 7 métodos — PÁGINA PRINCIPAL
      batch/[id].tsx    # Progresso e resultados de batch
      results/[id].tsx  # Resultados de job individual
    components/
      Layout.tsx        # Wrapper com keyboard shortcuts, transitions
      Sidebar.tsx       # Navegação lateral, dark mode toggle
      ExportModal.tsx   # Modal de exportação (CSV, JSON, WhatsApp, etc.)
      InfoBox.tsx       # Caixas informativas com ícones Lucide
      Tooltip.tsx       # Tooltips de hover para rate limits/descrições
    lib/
      api.ts            # Axios instance, baseURL, token interceptor, redirect 401
    styles/
      globals.css       # Dark mode com CSS raw (NUNCA @apply)
    public/
      logo.png          # 800x200 horizontal
      favicon.png       # 512x512 cube
    next.config.js      # output: 'export', trailingSlash: true, images unoptimized
    tailwind.config.js  # darkMode: 'class', cores primary blue
    package.json        # Next 13.4, React 18, Tailwind 3.4
deploy.py               # Deploy unificado (SSH backend + FTP frontend)
.deploy.env             # Credenciais (gitignored) — VPS_PASS, DB_PASS, FTP_PASS
.claude/commands/
  deploy.md             # Skill /deploy
```

## Database Schema (12 tabelas)

| Tabela | Propósito |
|--------|-----------|
| **users** | id, username, password_hash (SHA-256), is_admin, created_at |
| **sessions** | id, user_id, token (64 chars), created_at, expires_at (7 dias) |
| **jobs** | Scraping de URL único — id, user_id, url, status, results_count |
| **emails** | Emails extraídos — id, job_id, email, source_url, context |
| **batches** | Batches de URLs — id, user_id, name, status, total_urls, total_leads |
| **leads** | Leads master — company_name, email, phone, website, city, state, category, source, social_media, cnpj, address, crm_status, tags, notes, quality_score, cnpj_enriched, lead_score, extra_data (JSONB). UNIQUE(batch_id, email) |
| **search_jobs** | Tarefas de busca — id, batch_id, niche, city, state, engine, status, total_results, total_leads |
| **search_logs** | Logs de execução — id, search_job_id, log_type, url, status_code, duration_ms |
| **api_configs** | Chaves de API por usuário — user_id, provider, api_key, api_secret |
| **api_usage** | Créditos mensais por provider — user_id, provider, month_year, credits_used |
| **api_cache** | Cache de domínios (30 dias) — domain, provider, response_data, expires_at |
| **daily_jobs** | Histórico do pipeline diário — started_at, finished_at, status, batch_id, leads_found, leads_sanitized, leads_synced, niches_used, region_used |

## Rotas API

### Auth / Config
- `POST /api/login` — username + password → token
- `GET /api/me` — usuário autenticado
- `GET/POST /api/api-config` — gerenciar chaves (hunter, snov, bing_api, google_cse)
- `DELETE /api/api-config/<provider>`

### Extração Básica
- `POST /api/scrape` — job único (url)
- `GET /api/results/<job_id>` — resultados + export
- `GET /api/results` — listar jobs
- `POST /api/batch` — batch de URLs (urls[], name, deep_crawl, category, city, state)
- `GET /api/batch` — listar batches
- `GET /api/batch/<id>/progress` — progresso (polling 3s)
- `GET /api/batch/<id>/export` — exportar
- `DELETE /api/batch/<id>` — deletar

### Busca em Motores
- `POST /api/search` — busca por nicho+cidade (3/hour)
- `GET /api/search/<batch_id>/progress` — progresso com sub-jobs
- `GET /api/search/<batch_id>/logs` — logs de execução
- `GET /api/regions` — regiões pré-configuradas
- `POST /api/search-api` — busca + API enrichment (Hunter/Snov) (3/hour)

### Busca Massiva ⭐ (feature principal)
- `POST /api/search/massive` — 7 métodos paralelos em threads (10/hour)
  - Métodos: `api_enrichment`, `search_engines`, `google_maps`, `directories`, `instagram`, `linkedin`, `local_business_data`
  - Params: `niches[]`, `region` ou `city`/`state`, `methods[]`, `max_pages`
  - Limits internos: api_enrichment 3×1, search_engines 3 niches, google_maps 2×2, directories 5×5, instagram 2×2, linkedin 2×2, local_business_data 5×3
  - Inicia 7 threads daemon + auto-sync CRM ao final

### Scrapers Avançados
- `POST /api/scrape/google-maps` — Playwright Google Maps (5/hour)
- `POST /api/scrape/instagram` — Instaloader Instagram (3/hour)
- `POST /api/scrape/linkedin` — Playwright LinkedIn (2/hour)

### Leads / CRM
- `GET /api/leads` — listagem com filtros, paginação, sort
- `GET /api/leads/<id>` — lead individual
- `PUT /api/leads/<id>` — atualizar (crm_status, tags, notes, contact_name)
- `DELETE /api/leads/<id>` — deletar
- `PUT /api/leads/bulk-status` — status em massa
- `PUT /api/leads/bulk-tag` — tag em massa
- `POST /api/leads/bulk-delete` — deletar em massa (max 500)
- `POST /api/leads/import` — importar leads JSON diretamente
- `POST /api/leads/sanitize` — limpar encoding, validar emails, dedup (5/min)
- `POST /api/leads/fuzzy-dedup` — deduplicação fuzzy (rapidfuzz)
- `POST /api/leads/auto-tag` — auto-categorização por nome
- `POST /api/leads/enrich-cnpj` — enriquecimento via BrasilAPI
- `GET /api/leads/export/csv` — Export CSV
- `GET /api/leads/export/json` — Export JSON
- `POST /api/leads/export/marketing` — Export marketing (WhatsApp, email, telemarketing)
- `GET /api/leads/stats` — estatísticas (deprecated, usar /api/analytics)

### CRM Sync Externo
- `GET /api/crm/status` — status da conexão com api.alexandrequeiroz.com.br
- `POST /api/crm/sync-all` — sincronizar todos os leads (2/hour, max 200 por run)
- `POST /api/crm/refine` — sanitizar + sincronizar em uma etapa (2/hour)

### Pipeline Diário (Admin)
- `GET /api/admin/daily-job/status` — histórico últimas 10 execuções
- `POST /api/admin/daily-job/run` — disparar manualmente (2/hour)

### Dashboard / Misc
- `GET /api/analytics` — métricas do dashboard
- `GET /api/health` — health check
- `POST /api/enrich/external` — enriquecimento via APIs externas

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
| `/api/leads/sanitize` | 5/minute |
| `/api/crm/sync-all` | 2/hour |
| `/api/crm/refine` | 2/hour |
| `/api/admin/daily-job/run` | 2/hour |

## Funções de Scraping Chave

```python
# Motores de busca
search_duckduckgo(query, max_pages=2, safety)         # DDG HTML (primário)
search_bing(query, max_pages=2, safety)               # Bing HTML (fallback)
search_with_fallback(query, ...)                      # Orchestrador com retry

# Scrapers avançados
scrape_google_maps(niche, city, state, max_results=20)  # Playwright
scrape_instagram_business(niche, city, state, ...)      # Instaloader
scrape_linkedin_companies(niche, city, state, ...)      # Playwright

# Diretórios BR
scrape_empresas_com_br(niche, city, state, max_pages=2)
scrape_paginas_amarelas(niche, city, max_pages=2)
scrape_catalogo_br(niche, city, state, max_pages=2)
scrape_all_directories(niche, city, state, session)     # Orchestrador

# RapidAPI
search_local_business_data(niche, city, state, max_results=3)  # Free tier 500/mês
get_rapidapi_key()                                              # Busca do AWS SM com cache

# Enrichment
enrich_domain_hunter(domain, api_key)                   # Hunter.io
enrich_cnpj_brasilapi(cnpj)                             # BrasilAPI (gratuito)
```

## Pipeline Diário (APScheduler)

- **Agendado**: 02:00 America/Sao_Paulo
- **Guard de double-fire**: verifica `daily_jobs` nos últimos 5 min (evita disparo duplo com Gunicorn 2 workers)
- **Padrão**: niches=[Clinica Medica, Clinica Odontologica, Clinica Veterinaria], região=grande_vitoria_es
- **Sequência**: massive search (7 threads) → aguarda → sanitize → sync CRM → registra em `daily_jobs`
- **Trigger manual**: `POST /api/admin/daily-job/run`

## CRM Sync

- Auto-sync disparado após cada batch/search completado (`auto_sync_new_leads_background()`)
- Destino: `https://api.alexandrequeiroz.com.br`
- Credenciais: `CRM_EMAIL=xandeq@gmail.com`, `CRM_PASS` (AWS SM `extratordedados/prod`)
- Max 200 leads por sync, deduplica antes de enviar

## Convenções de Código

### Backend (Python)
- Monolito em `backend/app.py` — **não criar arquivos separados**
- Funções de scraping são `sync` (requests, não async)
- Background jobs via `threading.Thread(daemon=True)` com conexão DB dedicada
- Rate limiting via `@limiter.limit()`
- Auth via `verify_token(get_auth_header())`
- Tratar `psycopg2.errors.DuplicateColumn` no `ALTER TABLE` com `conn.rollback()`
- Logs com `print()` (capturados pelo Gunicorn)
- **Lambda closure**: usar default args `lambda n=niche, c=city, s=state:` para evitar late-binding

### Resiliência em Jobs Massivos
- `_massive_retry(fn, provider, query, max_attempts=3)` — retry com backoff, nunca raise
- Flag `quota_exceeded=True` → jobs restantes marcados como `failed/quota_exceeded` e pulados com `continue` (nunca para o loop)
- `try/except` em cada update de DB para não quebrar o fluxo
- **Regra**: jobs de busca sempre chegam ao final, independente de falhas individuais

### Frontend (TypeScript/React)
- Pages Router — **não** App Router
- Static export: sem SSR, sem API routes
- **CRÍTICO**: Em `globals.css`, usar CSS raw (`color: #xxx`) — **NUNCA `@apply`** (causa dependência circular)
- TypeScript: Tipar retorno de `.match()` como `string[]` para evitar tipo `never`
- Ícones: Lucide React (importar individualmente)
- Animações: Framer Motion para page transitions no `Layout`
- Dark mode: `darkMode: 'class'` no Tailwind, toggle via class no `<html>`

### Deploy
- **Script unificado**: `deploy.py` na raiz
- Backend: SSH/SFTP → VPS → `systemctl restart extrator-api`
- Frontend: `npx next build` → cria `.htaccess` no `/out/` → FTP para HostGator
- **CRÍTICO**: `.htaccess` é recriado pelo `deploy.py` antes do FTP (o build apaga o diretório `/out/`)
- Credenciais: AWS SM `extratordedados/prod` (timeout 10s) → fallback `.deploy.env`

### .htaccess (obrigatório no /out/)
```apache
RewriteEngine On
RewriteRule ^batch/(.+)$ /batch/[id].html [L]
RewriteRule ^results/(.+)$ /results/[id].html [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteCond %{REQUEST_FILENAME}.html -f
RewriteRule ^(.*)$ $1.html [L]
```

## Regras Anti-Blocking

- **NUNCA** usar Google Search direto (bloqueio imediato)
- DuckDuckGo HTML (`html.duckduckgo.com/html/`) como motor primário
- Bing como fallback
- Delays **obrigatórios**: 5-15s entre páginas de busca, 3-8s entre sites crawlados, 10-20s entre cidades
- User-Agent rotation (30+ agents)
- CAPTCHA detection → pause automático
- SafetyTracker com backoff exponencial
- Max 2-3 páginas de resultados por busca
- **Skip domains**: facebook.com, instagram.com, twitter.com, linkedin.com, youtube.com, tiktok.com, pinterest.com, mercadolivre.com.br, olx.com.br, amazon.com.br, gov.br, wikipedia.org, tripadvisor.com

## Regiões Pré-configuradas

- Grande Vitória-ES: Vitória, Vila Velha, Serra, Cariacica, Viana, Guarapari, Fundão
- Grande SP, Grande RJ, Grande BH (expansível em `SEARCH_REGIONS`)

## Verificação Pós-Deploy

```bash
# Backend
curl https://api.extratordedados.com.br/api/health
# Espera: {"status":"ok","db":"postgresql","timestamp":"..."}

# Frontend — abrir no browser
https://extratordedados.com.br

# Build sem erros
cd frontend && npx next build
```

## Erros Comuns

| Erro | Causa | Fix |
|------|-------|-----|
| `Property X does not exist on type 'never'` | `.match()` sem tipo | Tipar como `string[]` |
| Dark mode circular dependency | `@apply` em globals.css | Usar CSS raw |
| 404 em rotas dinâmicas (`/batch/123`) | `.htaccess` ausente | `deploy.py` recria automaticamente |
| `DuplicateColumn` no `ALTER TABLE` | Coluna já existe | `try/except` + `conn.rollback()` |
| Gunicorn double-fire APScheduler | 2 workers, 1 scheduler | Guard na tabela `daily_jobs` (5 min) |
| Lambda late-binding em closures | `lambda: fn(var)` em loop | `lambda v=var: fn(v)` |
| `name 'fn' is not defined` em threads | Nome de função errado | Verificar nome exato da função no módulo |
| `quota_exceeded` RapidAPI | 500 leads/mês esgotados | Flag no loop, nunca para o workflow |
| AWS SM timeout no Windows | boto3 lento | Timeout 5-10s + fallback `.deploy.env` |
