# ROADMAP.md — Extrator de Dados

> Gerado em: 2026-03-22
> Stack: Flask monolito + Next.js static + PostgreSQL (Docker VPS)
> Deploy: manual via `python deploy.py`

---

## Milestone 1 — Pipeline Autônomo + Qualidade + Fontes

**Objetivo**: Base de leads crescendo sozinha, com qualidade auditável, sem intervenção manual.
**Horizonte**: ~6 semanas

---

### Phase 1: Pipeline 100% Automático

**Goal**: Operador abre o sistema de manhã e vê relatório do que rodou à noite. Nichos configuráveis sem editar código.

**Value delivered**: Pipeline roda sozinho, relatório chega por email, admin configura via UI.

**Scope**:
- Tabela `pipeline_config` no DB (nichos, região, hora, ativo)
- `GET/PUT /api/admin/pipeline-config`
- `run_daily_pipeline()` lê do DB (não mais hardcoded)
- Reschedule dinâmico via `scheduler.reschedule_job()`
- `GET /api/admin/pipeline/health` — última execução, taxa 30d, próxima
- Relatório pós-pipeline via Brevo email (usa `tools/brevo` do AWS SM)
- Ping healthchecks.io ao final (dead-man's-switch)
- Admin UI: `/admin/pipeline-config` — editar nichos/região/hora
- Admin UI: card de health + histórico 30 dias

**Dependencies**: Brevo API key (já no AWS SM `tools/brevo`)

**Out of scope**: WhatsApp notifications (Fase posterior), Redis

**Plans:** 3/3 plans complete

Plans:
- [x] 01-PLAN.md — DB migration + pipeline_config table + GET/PUT config endpoints + trigger_daily_pipeline() wired to DB
- [x] 02-PLAN.md — GET /api/admin/pipeline/health + Brevo email report + healthchecks.io ping
- [x] 03-PLAN.md — Frontend /admin/pipeline-config editor + admin index health card + 30-day history

---

### Phase 2: Qualidade de Leads

**Goal**: Cada lead tem score A-F auditável. Emails inválidos não entram na base. Telefones normalizados.

**Value delivered**: Base limpa, score confiável para clientes, dedup cross-batch.

**Scope**:
- Instalar: `email-validator`, `dnspython`, `disposable-email-domains`, `phonenumbers`
- `validate_email_free()` — 3 camadas (formato + MX + disposable blocklist)
- `normalize_phone_br()` via phonenumbers → E.164 + WhatsApp ID
- Score 6 dimensões → grade A/B/C/D/F (calculado em cada insert)
- Migrations DB: `captured_at`, `last_verified_at`, `freshness_score`, `quality_grade`
- Dedup cross-batch: UNIQUE em `email` global
- `POST /api/leads/validate-batch`
- Botão "Verificar Email" (ZeroBounce, 100 free/mês)
- Frontend: badge grade, filtro por grade, coluna ordenável, indicador freshness

**Dependencies**: Phase 1 não é pré-requisito. Pode rodar em paralelo.

**Out of scope**: MillionVerifier bulk (pago), Paid email validation tier

**Plans:** 3/3 plans complete

Plans:
- [x] 02-01-PLAN.md — Wave 0 test scaffold + packages in requirements.txt + DB migrations (4 cols) + dedup cross-batch + global partial UNIQUE index on email
- [x] 02-02-PLAN.md — validate_email_free() + normalize_phone_br() + compute_lead_quality_score() + insert/sanitize hooks + POST /api/leads/validate-batch + quality_grade filter
- [x] 02-03-PLAN.md — ZeroBounce AWS SM secret + validate_zerobounce() + POST /api/leads/<id>/verify-email + frontend GradeBadge + FreshnessIndicator + A-F filter

---

### Phase 3: Novas Fontes (Receita Federal + Outscraper)

**Goal**: Base enriquecida com dados oficiais de 60M+ empresas brasileiras. Novos métodos de extração.

**Value delivered**: CNPJ lookup instantâneo sem API externa, novos leads via Outscraper + Prospeo.

**Scope**:
- `scripts/import/import_receita_federal.py` — download + parse + insert dataset RF (~15GB)
- Tabela `cnpj_rf` no PostgreSQL com índice em CNPJ
- `enrich_from_rf_local(cnpj)` — lookup local (< 10ms)
- Deploy Minha Receita no VPS (Docker, porta 3000 interna)
- Fallback chain CNPJ: local → BrasilAPI → ReceitaWS → CNPJ.ws
- Integração Outscraper API (8º método no massive search, 500/mês free)
- Integração Prospeo Social URL API (LinkedIn URL → email, 75/mês free)
- Docs: `docs/RECEITA_FEDERAL_IMPORT.md`

**Dependencies**: Phase 2 recomendada antes (qualidade do enrichment)

**Out of scope**: Minha Receita como API pública, MillionVerifier

**Plans:** 3/3 plans complete

Plans:
- [x] 03-01-PLAN.md — Wave 0 test stubs + cnpj_rf table migration + enrich_from_rf_local() + enrich_cnpj_with_fallback() 5-level chain + import script + RF runbook
- [x] 03-02-PLAN.md — Outscraper AWS SM key + _get_outscraper_key() + process_outscraper_massive() + wire into POST /api/search/massive as outscraper_maps
- [x] 03-03-PLAN.md — Prospeo AWS SM key + enrich_linkedin_prospeo() + POST /api/leads/<id>/enrich-linkedin + LinkedIn thread hook + Minha Receita deploy guide

---

## Milestone 2 — Portal de Clientes

**Objetivo**: 1º cliente pagando para acessar a base de leads.
**Horizonte**: +5 semanas (após Milestone 1)

---

### Phase 4: Tier Cliente + Reveal Gate + Busca Avançada

**Goal**: Clientes se cadastram e acessam base mascarada com sistema de créditos. Reveal gate converte free → paid.

**Value delivered**: Modelo de negócio funcionando. Clientes pagam para ver contatos.

**Scope**:
- Role `client` no sistema de users (além de `admin`, `operator`)
- Tabela `credit_ledger` (user_id, amount, operation, ref_id, created_at)
- `deduct_credit()` com `SELECT FOR UPDATE` (previne race condition)
- `POST /api/leads/reveal/<id>` (-1 crédito)
- `GET /api/client/credits` — saldo + histórico
- `GET /api/leads/search` — busca cliente com filtros: nicho, cidade, estado, quality_grade, has_email, has_phone, has_whatsapp, has_website
- Response mascarado: `"jo***@gmail.com"`, `"27 9****-5678"`
- Planos: Free(10cr/mês), Básico(200), Pro(1000), Enterprise(ilimitado)
- Frontend `/portal` para clientes (sem bulk actions, sem export direto)
- Sidebar créditos, reveal button, filtros avançados
- Página `/plans` com comparativo e créditos por plano

**Dependencies**: Phase 1+2 concluídas (leads com quality grade, pipeline rodando)

**Out of scope**: Stripe (pagamento manual por agora), API keys para clientes

**Plans:** 3/3 plans complete

Plans:
- [x] 04-01-PLAN.md — Wave 0 test stubs + DB migrations (credit_ledger, user_lead_reveals, role col, credits_per_month) + deduct_credit() + grant_monthly_credits() + require_role() + mask_email/phone + portal_lead_to_dict
- [x] 04-02-PLAN.md — POST /api/leads/reveal/<id> + GET /api/client/credits + GET /api/leads/search (masked, filtered)
- [x] 04-03-PLAN.md — Frontend portal.tsx (client search page) + RevealButton component + useClientCredits hook + Sidebar credit widget + plans.tsx credits row

---

### Phase 5: Export com Cotas + Niche Request Queue

**Goal**: Clientes exportam listas pagas. Solicitam nichos que ainda não existem na base.

**Value delivered**: Revenue por export. Flywheel: clientes pedem nichos → base cresce → mais clientes.

**Scope**:
- `GET /api/client/leads/export` — CSV/JSON com cota por plano (débito de créditos)
- Tabela `niche_requests` (user_id, niche, city, state, votes, status)
- `POST /api/client/niche-requests` + vote aggregation
- `GET/POST /api/admin/niche-requests` — admin aprova → dispara extração
- Frontend: botão export para clientes, página `/request-niche`, admin `/admin/niche-requests`

**Dependencies**: Phase 4 (credit ledger já implementado)

**Plans:** 5/5 plans complete

Plans:
- [x] 05-01-PLAN.md — Wave 0 test stubs + niche_requests/niche_request_votes DB tables + _generate_csv_bytes() + GET /api/client/leads/export
- [x] 05-02-PLAN.md — POST/GET /api/client/niche-requests + GET/POST /api/admin/niche-requests (approve + reject) + activate Wave 0 test stubs
- [x] 05-03-PLAN.md — ClientExportModal.tsx + portal.tsx export button + Sidebar nav item + /request-niche page + /admin/niche-requests page
- [x] 05-04-PLAN.md — Gap closure: _trigger_niche_extraction wired to real search pipeline (process_search_job) + Fila de Nichos added to admin sidebar nav
- [x] 05-05-PLAN.md — Gap closure: backend deployed to VPS, health check confirmed OK, Phase 5 endpoints live

---

### Phase 6: Saved Searches + Notificações de Novos Leads

**Goal**: Clientes recebem email quando chegam novos leads nos filtros salvos. Máxima retenção.

**Value delivered**: Clientes voltam toda semana sem precisar lembrar de entrar no sistema.

**Scope**:
- Tabela `saved_searches` (user_id, name, filters JSONB, last_notified_at, notify_email)
- `POST/GET/DELETE/PATCH /api/client/saved-searches`
- APScheduler job 08:00 — detecta novos leads por filtro, envia email via Brevo
- Frontend: "Salvar Busca", página `/saved-searches` com toggle de notificação

**Dependencies**: Phase 5 (busca avançada funcionando)

**Plans:** 3/3 plans complete

Plans:
- [x] 06-01-PLAN.md — Wave 0 test stubs + saved_searches DB migration + _build_portal_filter_query() extracted + send_notification_email()
- [x] 06-02-PLAN.md — POST/GET/DELETE/PATCH /api/client/saved-searches + trigger_saved_search_notifications APScheduler job + activate all 6 tests
- [x] 06-03-PLAN.md — saved-searches.tsx page + Sidebar nav link + portal.tsx "Salvar Busca" button + modal + frontend deploy

---

## Milestone v1.1 — Lead Quality Engine

**Objetivo**: Base de leads de altíssima qualidade. Apenas leads com email válido OR WhatsApp válido entram. Pipeline roda automaticamente por todos os nichos e cidades do ES.

**Contexto**: Milestones v1.0 (Phases 1-6) 100% completos. Agora é escalar qualidade e volume.

---

### Phase 7: Qualidade de Leads Avançada

**Goal**: Zero leads ruins na base — emails inválidos, TLDs estrangeiros, slogans e duplicatas de CRM são bloqueados na entrada.

**Value delivered**: CRM recebe apenas leads acionáveis. Taxa de bounce no email marketing cai. Nenhum lead já existente no CRM é re-enviado.

**Scope**:
- Expandir `validate_email_free()` com lista de bounce domains atualizada (QUAL-01)
- Filtro de TLD estrangeiro em `save_lead_to_db()` — rejeitar `.es`, `.pt`, `.pl`, `.com.ar` etc. (QUAL-02)
- Detector de email-slogan via regex + heurística (QUAL-03)
- Dedup contra CRM antes do sync — verificar email/telefone existente, não re-enviar (QUAL-04)
- Validar WhatsApp com `phonenumbers`: DDD válido BR (11-99 para celular), comprimento mínimo (QUAL-05)
- Gate CRM em `auto_sync_new_leads_background()`: enviar somente leads com email válido OR whatsapp válido (QUAL-06)
- Campo `rejection_reason` (varchar) na tabela `leads`
- `GET /api/admin/quality-stats` — taxa de rejeição por motivo, aceitos/rejeitados por dia
- Frontend: card de qualidade no admin dashboard + filtro "Rejeitados/Aceitos/Todos" na página de leads

**Dependencies**: Phase 2 (validate_email_free + quality_grade já existem como base)

**Out of scope**: MillionVerifier bulk, ZeroBounce para validação em lote

**Plans:** 3 plans

Plans:
- [ ] 07-01-PLAN.md — Wave 1: _is_foreign_tld() + _is_slogan_email() + save_lead_to_db() guards (QUAL-01/02/03/05) + test scaffold
- [ ] 07-02-PLAN.md — Wave 2: crm_sent_leads table + cache READ/WRITE in sync_lead_to_alexandrequeiroz() (QUAL-04)
- [ ] 07-03-PLAN.md — Wave 3: QUAL-06 gate in 3 sync functions + GET /api/admin/quality-stats endpoint

---

### Phase 8: Catálogo de Nichos

**Goal**: Pipeline rotaciona automaticamente por 150+ nichos cadastrados no banco. Admin ativa/desativa nichos via UI sem tocar em código.

**Value delivered**: Volume de leads escala com zero esforço manual. Novos nichos entram sem deploy. Busca massiva ganha seleção inteligente de nicho em 1 clique.

**Scope**:
- Tabela `niches` (id, name, category, subcategory, keywords[], active, priority, created_at) (NICHE-01)
- `get_pipeline_config()` lê nichos ativos da tabela `niches` para rotação diária (NICHE-02)
- Script `scripts/import/populate_niches.sql` — 150+ nichos por categoria (saúde, beleza, alimentação, serviços, educação) (NICHE-03)
- `GET /api/admin/niches` + `PUT /api/admin/niches/bulk` — ativar/desativar em lote
- Pipeline rotaciona grupos de 20 nichos/dia em vez de rodar todos de uma vez
- Frontend: botão "Selecionar todos / Desselecionar todos" na busca massiva (NICHE-04)
- Página `/admin/niches` — lista categorizada, toggle ativo, prioridade editável

**Dependencies**: Phase 1 (pipeline_config table e run_daily_pipeline() já existem)

**Out of scope**: Interface para clientes sugerirem nichos (já existe em Phase 5 via niche_requests)

**Plans:** 3/3 plans complete

Plans:
- [x] 08-01-PLAN.md — Wave 0: niches DB migration + populate_niches.sql (150+ entries) + GET /api/admin/niches + PUT /api/admin/niches/bulk
- [x] 08-02-PLAN.md — Wave 1: get_pipeline_config() reads from niches table + daily rotation groups of 20 + wire into run_daily_pipeline()
- [x] 08-03-PLAN.md — Wave 2: /admin/niches page (categorized list + toggle + priority) + "Selecionar todos / Limpar selecao" on busca massiva + frontend deployed to HostGator

---

### Phase 9: Expansão Regional ES

**Goal**: Pipeline cobre progressivamente todas as 78 cidades do Espírito Santo, rotacionando sem repetir na mesma semana.

**Value delivered**: Volume de leads do ES aumenta 10× ao longo do tempo. Admin vê mapa de cobertura e sabe quais cidades já foram trabalhadas.

**Scope**:
- Tabela `regions` (id, name, city, state, ibge_code, priority, active, last_used_at) (REG-01)
- Script `scripts/import/populate_es_cities.sql` — 78 cidades do ES com dados IBGE
- `run_daily_pipeline()` rotaciona por grupos de 5-10 cidades/dia via round-robin em `last_used_at` (REG-02)
- `GET /api/admin/regions` — lista com última execução e leads capturados por cidade
- `PUT /api/admin/regions/bulk` — ativar/desativar regiões
- Frontend: lista de cidades na página de pipeline config com indicador verde/cinza de cobertura
- Seletor de região na busca massiva atualizado com todas as cidades do ES

**Dependencies**: Phase 1 (run_daily_pipeline() e pipeline_config existem), Phase 8 recomendada (nichos do banco disponíveis para combinar com cidades)

**Out of scope**: Expansão para outros estados (SP, RJ, MG) — após ES coberto 100%

**Plans:** 1/3 plans complete

Plans:
- [x] 09-01-PLAN.md — Wave 0: regions DB migration + populate_es_cities.sql (78 cities) + GET /api/admin/regions + PUT /api/admin/regions/bulk
- [ ] 09-02-PLAN.md — Wave 1: round-robin city rotation in run_daily_pipeline() + last_used_at update logic + leads_captured counter per region
- [ ] 09-03-PLAN.md — Wave 2: pipeline-config page city coverage list + busca massiva region selector update + frontend deploy

---

### Phase 10: Novas Fontes de Extração

**Goal**: Volume de leads aumenta via Apple Maps e melhorias nos scrapers existentes. Cada nicho tem 5 variações de query no motor de busca.

**Value delivered**: Outscraper entrega ≥ 50% mais leads por query. Motor de busca explora mais ângulos por nicho. Apple Maps abre nova fonte não usada antes.

**Scope**:
- Apple Maps scraper — `process_apple_maps_massive()` via Playwright; integrar como novo thread no massive search (SRC-01)
- Pesquisar e implementar melhor API de leads BR disponível no free tier (SRC-02)
- Melhorar `process_outscraper_massive()` — retry com backoff, cursor pagination, max_results 20 → 100, batch queries (SRC-03)
- Melhorar `process_search_job()` — 5 templates de query por nicho: `"[nicho] [cidade] contato"`, `"[nicho] [cidade] email"`, `"[nicho] [cidade] whatsapp"`, `site:*.com.br "[nicho]" "[cidade]"`, `"[nicho]" "[cidade]" OR "[cidade vizinha]"` (SRC-04)
- `GET /api/admin/source-stats` — leads por fonte nos últimos 30 dias
- Frontend: gráfico de barras no admin dashboard mostrando leads por fonte

**Dependencies**: Phase 3 (process_outscraper_massive existe), Phase 9 recomendada (cidades do ES disponíveis para teste de volume)

**Out of scope**: LinkedIn Sales Navigator (custo), MillionVerifier bulk

**Plans:** 0/3 plans complete

Plans:
- [ ] 10-01-PLAN.md — Wave 0: Apple Maps Playwright scraper + process_apple_maps_massive() + wire into massive search + GET /api/admin/source-stats
- [ ] 10-02-PLAN.md — Wave 1: Outscraper improvements (retry, pagination, batch, max_results 100) + 5-template query expansion in process_search_job() + leads_by_source tracking
- [ ] 10-03-PLAN.md — Wave 2: best BR leads API integration (SRC-02 research → implement) + source stats bar chart on admin dashboard + frontend deploy

---

## Visão de Futuro (Backlog)

| Feature | Quando considerar |
|---------|------------------|
| Stripe para pagamentos | 3+ clientes ativos |
| WhatsApp notifications (Meta Cloud API, $0.21/mês) | Após Brevo email validado |
| API pública para clientes (v2) | Após portal estabilizar com 5+ clientes |
| MillionVerifier bulk validation (feature paga) | Após credit system rodando |
| Minha Receita como API pública | Se VPS tiver capacidade extra |
| Redis + rate limits globais | Se escalar para 10+ usuários simultâneos |
| Celery/RQ para jobs complexos | Apenas com Redis instalado |
| Expansão para outros estados (SP, RJ, MG) | Após ES coberto 100% |

---

## Estado Atual

```
[✓] Milestone 0 — Base (completo)
    ✓ 7 métodos de extração funcionando
    ✓ Pipeline diário (hardcoded)
    ✓ CRM sync
    ✓ Multi-usuário com planos básicos
    ✓ UI busca/filtro/export

[✓] Milestone 1 — Autonomia + Qualidade + Fontes
    [✓] Phase 1 — Pipeline automático (3/3 plans complete)
    [✓] Phase 2 — Qualidade de leads (3/3 plans complete)
    [✓] Phase 3 — Receita Federal + Outscraper + Prospeo (3/3 plans complete)

[✓] Milestone 2 — Portal de Clientes
    [✓] Phase 4 — Reveal gate + créditos (3/3 plans complete)
    [✓] Phase 5 — Export + niche requests (5/5 plans complete, gaps closed, backend deployed)
    [✓] Phase 6 — Saved searches + notificações (3/3 plans complete)

[ ] Milestone v1.1 — Lead Quality Engine
    [ ] Phase 7 — Qualidade avançada: TLD filter, slogan detector, CRM dedup, WhatsApp gate (0/3 plans)
    [✓] Phase 8 — Catálogo de nichos: 150+ nichos no banco, rotação diária, admin UI (3/3 plans complete)
    [ ] Phase 9 — Expansão regional ES: 78 cidades, round-robin pipeline (1/3 plans)
    [ ] Phase 10 — Novas fontes: Apple Maps, Outscraper melhorado, 5 query templates (0/3 plans)
```

---

## Convenções

- **Phases são atômicas** — cada uma entrega valor sem depender da próxima
- **Deploy** após cada fase via `python deploy.py`
- **Testes** pytest para cada novo endpoint (`tests/`)
- **Monolito** — todo código novo em `app/backend/app.py` ou módulo auxiliar importado por ele

---

*Last updated: 2026-03-24 — Milestone v1.1 Lead Quality Engine roadmap appended (Phases 7-10)*
