# Extrator de Dados — Lead Aggregation Platform

## What This Is

Sistema web de extração e agregação automatizada de leads empresariais brasileiros. Usa 7 métodos paralelos (Apify, Google Maps, scraping, diretórios BR, Instagram, LinkedIn, RapidAPI) para alimentar uma base de dados centralizada de leads qualificados. A base alimenta CRM próprio e, em breve, um portal onde clientes pagam para acessar, buscar e exportar leads por nicho/região.

## Core Value

**Pipeline 100% automático** — a base de leads cresce sozinha todo dia, sem intervenção manual, com qualidade e volume crescentes.

## Requirements

### Validated

- ✓ Extração por 7 métodos paralelos (massive search) — existente
- ✓ Lead storage com deduplicação e sanitização — existente
- ✓ Scheduler diário APScheduler (02:00 + 09:00 CRM sync) — existente
- ✓ CRM sync externo (api.alexandrequeiroz.com.br) — existente
- ✓ Multi-usuário com planos e limites — existente
- ✓ UI de busca, filtro e exportação (CSV/JSON) — existente
- ✓ Admin dashboard com controle de pipeline — existente
- ✓ Logs e diagnóstico (app-logs) — existente
- ✓ CNPJ enrichment via BrasilAPI — existente
- ✓ Lead scoring básico e auto-tag — existente

### Active

#### Pipeline & Automação
- [x] Pipeline diário executa nichos configuráveis (não hardcoded) — Validated in Phase 1: pipeline-100-automatico
- [x] Relatório automático pós-pipeline enviado por email (Brevo) — Validated in Phase 1: pipeline-100-automatico
- [x] Painel de health do pipeline: última execução, leads capturados, erros, próxima execução — Validated in Phase 1: pipeline-100-automatico
- [x] Configuração de nichos e regiões por interface (sem editar código) — Validated in Phase 1: pipeline-100-automatico

#### Qualidade de Leads
- [ ] Validação de email em tempo real antes de salvar (verificar formato + MX record)
- [ ] Score de qualidade aprimorado: penalizar leads sem telefone/email/website
- [ ] Deduplicação cross-batch (detectar email duplicado entre batches diferentes)

#### Portal de Clientes
- [ ] Tier de acesso "cliente" — vê base agregada, não pode disparar extrações
- [ ] Busca avançada: nicho, cidade, estado, segmento, score mínimo, tem WhatsApp/email/site
- [ ] Exportação com cota por plano (ex: 500 leads/mês no plano básico)
- [ ] Solicitação de novo nicho: cliente pede nicho+cidade, entra na fila de extração

### Out of Scope

| Feature | Reason |
|---------|--------|
| Clientes rodando próprias extrações | Segurança, custo, complexidade — acesso à base apenas |
| Envio de email/WhatsApp dentro do sistema | Ferramenta de coleta, não de disparo — integra com ferramentas externas |
| App mobile | Web-first, mobile later |
| API pública para clientes | v2 — após portal estabilizar |
| Scraping em tempo real por demanda do cliente | Alto custo computacional — apenas fila assíncrona |

## Context

- **Stack**: Flask monolito (`app/backend/app.py`), Next.js 13.4 static export, PostgreSQL Docker no VPS
- **Infraestrutura**: VPS 185.173.110.180 (Gunicorn 2 workers + Traefik), HostGator FTP (frontend estático)
- **Tech debt conhecido**: Rate limits por worker (não global — falta Redis), app.py ~10k linhas
- **Monetização**: Planos de acesso à base de leads — free (limitado), básico, profissional
- **Usuário atual**: Só o dono (acq20) — clientes ainda não têm acesso
- **CRM de destino**: api.alexandrequeiroz.com.br para campanhas de email marketing
- **Região de foco inicial**: Grande Vitória/ES — expansão progressiva para outras regiões/nichos

## Constraints

- **Stack**: Flask + Next.js — manter monolito, não migrar para microserviços
- **Infraestrutura**: VPS existente — sem migração de cloud agora
- **Deploy**: Manual via `python deploy.py` — sem CI/CD automático ainda
- **Custo**: Priorizar fontes gratuitas/low-cost (DDG, BrasilAPI, diretórios) antes de APIs pagas

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Clientes acessam base, não fazem scraping | Segurança + custo controlado | — Pending |
| Monolito Flask continua | Evitar reescrita — incrementar | — Pending |
| Pipeline diário às 02:00 (APScheduler) | Sem tráfego, não compete com usuários | ✓ Good |
| DuckDuckGo como motor primário | Evitar bloqueio do Google | ✓ Good |
| Nichos hardcoded no código | Tech debt — mover para DB/config | ⚠️ Revisit |

## Evolution

Este documento evolui a cada fase completada.

**After each phase transition:**
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone:**
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-23 after Phase 1 completion*
