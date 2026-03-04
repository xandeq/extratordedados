# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visao Geral
Sistema web de extracao automatizada de leads empresariais (emails, telefones, WhatsApp, redes sociais, CNPJ). Permite scraping de URLs, busca por motores de busca, importacao JSON, extracao de texto e colagem direta. Inclui CRM basico, export multi-formato e dashboard analitico.

**Metodos de extracao**: Scraping tradicional (requests+BeautifulSoup), Playwright (Google Maps, LinkedIn), Instagram API (instaloader), Busca em motores (DuckDuckGo, Bing), APIs de enrichment (Hunter.io, Snov.io)

## Arquitetura

### Backend
- **Framework**: Flask (Python 3) - monolito em `project/backend/app.py` (~4200 linhas)
- **Banco**: PostgreSQL 16 (Docker container na VPS)
- **Pool**: psycopg2 SimpleConnectionPool (1-10 conexoes)
- **Rate Limiting**: Flask-Limiter (200/hour default, memory storage)
- **CORS**: Flask-CORS (aberto)
- **Proxy**: Traefik reverse proxy -> Gunicorn (2 workers, 120s timeout)
- **Background Jobs**: threading.Thread(daemon=True) com conexao dedicada ao DB
- **Scraping Basico**: requests + BeautifulSoup4 + lxml
- **Scraping Avancado**: Playwright (Chromium headless) + Instaloader
- **Anti-blocking**: User-Agent rotation, delays entre requests, CAPTCHA detection, SafetyTracker

### Frontend
- **Framework**: Next.js 13.4 (Pages Router, static export)
- **UI**: Tailwind CSS 3.4, Lucide React icons, Framer Motion
- **Charts**: Recharts
- **HTTP**: Axios com interceptor de token
- **Build**: `output: 'export'` (HTML estatico) + `trailingSlash: true`

### Infraestrutura
- **VPS**: 185.173.110.180 (root SSH)
- **Backend URL**: https://api.extratordedados.com.br
- **Frontend URL**: https://extratordedados.com.br (HostGator, FTP)
- **Banco**: PostgreSQL em Docker (porta 5432, db: extrator, user: extrator)

## Estrutura de Arquivos

```
project/
  backend/
    app.py              # Monolito Flask (~2000+ linhas)
    requirements.txt    # Flask, psycopg2, beautifulsoup4, lxml, gunicorn, etc.
  frontend/
    pages/
      _app.tsx          # Layout global, Head, ToastProvider
      login.tsx         # Autenticacao
      dashboard.tsx     # Analytics com Recharts
      scrape.tsx        # Hub de extracao (tabs: busca, url, json, texto, colar)
      leads.tsx         # CRM com filtros, bulk actions, drawer
      batch/[id].tsx    # Progresso e resultados de batch
      results/[id].tsx  # Resultados de job individual
    components/
      Layout.tsx        # Wrapper com keyboard shortcuts, transitions
      Sidebar.tsx       # Navegacao lateral, dark mode toggle
      ExportModal.tsx   # Modal de exportacao (CSV, JSON, WhatsApp, etc.)
    lib/
      api.ts            # Axios instance, baseURL, token interceptor
    styles/
      globals.css       # Dark mode com CSS raw (NAO usar @apply)
    public/
      logo.png          # 800x200 horizontal
      favicon.png       # 512x512 cube
    next.config.js      # output: 'export', trailingSlash: true
    tailwind.config.js  # darkMode: 'class', cores primary blue
    package.json        # Next 13.4, React 18, Tailwind 3.4
_test_python/
  ssh_deploy_batch.py   # Deploy backend via SSH
  ftp_deploy_frontend.py # Deploy frontend via FTP
```

## Database Schema

### Tabelas Principais
- **users**: id, username, password_hash (SHA-256), is_admin, created_at
- **sessions**: id, user_id, token (64 chars), created_at, expires_at (7 dias)
- **jobs**: id, user_id, url, status, results_count, timestamps
- **emails**: id, job_id, email, source_url, context, extracted_at
- **batches**: id, user_id, name, status, total_urls, processed_urls, total_leads, timestamps
- **leads**: id, batch_id, company_name, email, phone, website, source_url, city, state, category, source, instagram, facebook, linkedin, twitter, youtube, whatsapp, cnpj, address, crm_status, tags, notes, contact_name, quality_score, extra_data, extracted_at, updated_at
- **search_jobs**: id, batch_id, user_id, query, engine, niche, city, state, region, max_pages, status, total_results, processed_results, total_leads, timestamps, error_message
- **search_logs**: id, search_job_id, log_type, url, status_code, message, duration_ms, created_at

### Constraints
- UNIQUE(batch_id, email) em leads
- UNIQUE(job_id, email) em emails
- CRM statuses: novo, contatado, interessado, negociando, cliente, descartado

## Rotas API

### Auth
- POST /api/login - Login (username, password) -> token
- POST /api/register - Registro (admin only)
- GET /api/me - Dados do usuario autenticado

### Extracao
- POST /api/scrape - Job unico (url)
- POST /api/batch - Batch de URLs (urls[], name, deep_crawl, category, city, state)
- GET /api/batch/<id>/progress - Progresso do batch (polling 3s)
- POST /api/leads/import - Importacao direta de leads (leads[])

### Busca em Motores
- POST /api/search - Busca por nicho+cidade (niche, city, state, region, max_pages)
- GET /api/search/<batch_id>/progress - Progresso com sub-jobs por cidade
- GET /api/search/<batch_id>/logs - Logs de execucao
- GET /api/regions - Regioes pre-configuradas

### Leads / CRM
- GET /api/leads - Listagem com paginacao, filtros (search, city, state, source, batch_id, crm_status, quality)
- PUT /api/leads/<id> - Atualizar lead (crm_status, tags, notes)
- PUT /api/leads/bulk-status - Atualizar status em massa
- PUT /api/leads/bulk-tag - Adicionar tag em massa
- DELETE /api/leads/<id> - Deletar lead individual
- POST /api/leads/bulk-delete - Deletar leads em massa (max 500)
- GET /api/leads/export/csv - Export CSV
- GET /api/leads/export/json - Export JSON
- POST /api/leads/export/marketing - Export marketing (WhatsApp, email, telemarketing)
- GET /api/leads/stats - Estatisticas

### Scrapers Avancados
- POST /api/scrape/google-maps - Google Maps scraping (Playwright, rate limit 5/hour)
- POST /api/scrape/instagram - Instagram business profiles (Instaloader, rate limit 3/hour)
- POST /api/scrape/linkedin - LinkedIn companies (Playwright, rate limit 2/hour)

### Dashboard
- GET /api/dashboard - Metricas gerais
- GET /api/health - Health check

## Convencoes de Codigo

### Backend (Python)
- Monolito em app.py - NAO criar arquivos separados
- Funcoes de scraping sao sync (requests, nao async)
- Background jobs via threading.Thread(daemon=True) com conexao DB dedicada
- Rate limiting via decorador @limiter.limit()
- Auth via verify_token(get_auth_header())
- Sempre tratar psycopg2.errors.DuplicateColumn no ALTER TABLE com conn.rollback()
- Delays obrigatorios entre requests: DELAY_BETWEEN_DOMAINS=2s, DELAY_BETWEEN_SUBPAGES=1s
- Logs com print() (capturados pelo Gunicorn)

### Frontend (TypeScript/React)
- Pages Router (NAO App Router)
- Static export: `output: 'export'` - sem SSR, sem API routes
- Componentes em PascalCase
- Dark mode: `darkMode: 'class'` no Tailwind, toggle via class no <html>
- **CRITICO**: Em globals.css, usar CSS raw (color: #xxx) - NUNCA @apply com classes Tailwind (causa dependencia circular)
- Axios interceptor em lib/api.ts adiciona Bearer token automaticamente
- Redirect para /login em 401
- TypeScript: Sempre tipar retorno de `.match()` como `string[]` para evitar tipo `never`
- Icones: Lucide React (importar individualmente)
- Animacoes: Framer Motion para page transitions no Layout
- Toast: Context provider em _app.tsx

### Deploy
1. Backend: `python _test_python/ssh_deploy_batch.py` (SSH para VPS)
   - Copia app.py -> /opt/extrator-api/
   - Restart Gunicorn: `systemctl restart extrator-api`
2. Frontend: `npx next build` + `python _test_python/ftp_deploy_frontend.py`
   - Build gera /out/ (HTML estatico)
   - FTP para HostGator: /extratordedados.com.br
   - **CRITICO**: Recriar .htaccess no /out/ ANTES do FTP (build apaga o diretorio)

### .htaccess (obrigatorio)
```apache
RewriteEngine On
# Handle Next.js dynamic routes
RewriteRule ^batch/(.+)$ /batch/[id].html [L]
RewriteRule ^results/(.+)$ /results/[id].html [L]
# If file/directory doesn't exist, try .html extension
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteCond %{REQUEST_FILENAME}.html -f
RewriteRule ^(.*)$ $1.html [L]
```

## Regras Anti-Blocking (SEGURANCA #1)

### Principios
- NUNCA usar Google Search (bloqueio imediato)
- DuckDuckGo HTML (html.duckduckgo.com/html/) como motor primario
- Bing como fallback
- Delays OBRIGATORIOS: 5-15s entre paginas de busca, 3-8s entre sites crawlados, 10-20s entre cidades
- User-Agent rotation (30+ agents variados)
- CAPTCHA detection -> pause automatico
- SafetyTracker com backoff exponencial
- Max 2-3 paginas de resultados por busca
- Skip domains: redes sociais, marketplaces, governo

### Skip Domains
facebook.com, instagram.com, twitter.com, linkedin.com, youtube.com, tiktok.com, pinterest.com, mercadolivre.com.br, olx.com.br, amazon.com.br, gov.br, wikipedia.org, tripadvisor.com

### Regioes Pre-configuradas
- Grande Vitoria-ES: Vitoria, Vila Velha, Serra, Cariacica, Viana, Guarapari, Fundao
- Grande SP, Grande RJ, Grande BH (expansivel)

## Verificacao Pos-Deploy

1. Health: `curl https://api.extratordedados.com.br/api/health`
2. Login: POST /api/login com admin credentials
3. Frontend: Abrir https://extratordedados.com.br no browser
4. Build: `cd project/frontend && npx next build` deve ter 0 erros
5. Rotas dinamicas: /batch/123 e /results/123 devem carregar (via .htaccess)

## Erros Comuns

- **`Property X does not exist on type 'never'`**: Tipar retorno de `.match()` como `string[]`
- **Dark mode circular dependency**: Usar CSS raw em globals.css, nunca @apply
- **404 em rotas dinamicas**: .htaccess ausente no build output
- **CORS errors**: Flask-CORS ja configurado, verificar se URL da API esta correta
- **DuplicateColumn no ALTER TABLE**: Tratar com try/except + conn.rollback()
- **Gunicorn timeout**: Padrao 120s, jobs longos usam threading (daemon)
