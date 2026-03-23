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
- Frontend `/leads` para clientes (sem bulk actions, sem export direto)
- Sidebar créditos, reveal button, filtros avançados
- Página `/plans` com comparativo

**Dependencies**: Phase 1+2 concluídas (leads com quality grade, pipeline rodando)

**Out of scope**: Stripe (pagamento manual por agora), API keys para clientes

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

---

### Phase 6: Saved Searches + Notificações de Novos Leads

**Goal**: Clientes recebem email quando chegam novos leads nos filtros salvos. Máxima retenção.

**Value delivered**: Clientes voltam toda semana sem precisar lembrar de entrar no sistema.

**Scope**:
- Tabela `saved_searches` (user_id, name, filters JSONB, last_notified_at)
- `POST/GET/DELETE /api/client/saved-searches`
- APScheduler job 08:00 — detecta novos leads por filtro, envia email via Brevo
- Frontend: "Salvar Busca", página `/saved-searches` com toggle de notificação

**Dependencies**: Phase 5 (busca avançada funcionando)

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

[ ] Milestone 2 — Portal de Clientes
    [ ] Phase 4 — Reveal gate + créditos
    [ ] Phase 5 — Export + niche requests
    [ ] Phase 6 — Saved searches + notificações
```

---

## Convenções

- **Phases são atômicas** — cada uma entrega valor sem depender da próxima
- **Deploy** após cada fase via `python deploy.py`
- **Testes** pytest para cada novo endpoint (`tests/`)
- **Monolito** — todo código novo em `app/backend/app.py` ou módulo auxiliar importado por ele

---

*Last updated: 2026-03-23*
