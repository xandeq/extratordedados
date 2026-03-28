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

#### Milestone v1.0 — Completed ✓

##### Pipeline & Automação
- [x] Pipeline diário executa nichos configuráveis (não hardcoded) — Validated in Phase 1: pipeline-100-automatico
- [x] Relatório automático pós-pipeline enviado por email (Brevo) — Validated in Phase 1: pipeline-100-automatico
- [x] Painel de health do pipeline: última execução, leads capturados, erros, próxima execução — Validated in Phase 1: pipeline-100-automatico
- [x] Configuração de nichos e regiões por interface (sem editar código) — Validated in Phase 1: pipeline-100-automatico

##### Qualidade de Leads
- [x] Validação de email em tempo real antes de salvar (verificar formato + MX record) — Validated in Phase 2: qualidade-de-leads
- [x] Score de qualidade aprimorado: penalizar leads sem telefone/email/website — Validated in Phase 2: qualidade-de-leads
- [x] Deduplicação cross-batch (detectar email duplicado entre batches diferentes) — Validated in Phase 2: qualidade-de-leads

##### Portal de Clientes
- [x] Tier de acesso "cliente" — vê base agregada, não pode disparar extrações — Validated in Phase 4
- [x] Busca avançada: nicho, cidade, estado, segmento, score mínimo, tem WhatsApp/email/site — Validated in Phase 4
- [x] Exportação com cota por plano (ex: 500 leads/mês no plano básico) — Validated in Phase 5
- [x] Solicitação de novo nicho: cliente pede nicho+cidade, entra na fila de extração — Validated in Phase 5
- [x] Buscas salvas com notificação por email de novos leads — Validated in Phase 6

#### Milestone v1.1 — Lead Quality Engine (Active)

##### Qualidade de Leads Avançada
- [ ] QUAL-01: Lead com email inválido/bounceável é rejeitado antes de entrar na base
- [ ] QUAL-02: Lead com TLD estrangeiro (.es, .pt, .pl, .com.ar, etc.) é rejeitado automaticamente
- [ ] QUAL-03: Lead com email no estilo slogan/frase é detectado e rejeitado
- [ ] QUAL-04: Lead duplicado já existente no CRM (por email ou telefone) não é re-inserido
- [ ] QUAL-05: Número de WhatsApp é validado antes de salvar (formato + DD válido BR)
- [ ] QUAL-06: Apenas leads com email válido OR WhatsApp válido são enviados ao CRM

##### Novas Fontes de Extração
- [ ] SRC-01: Apple Maps integrado na busca massiva como nova fonte
- [ ] SRC-02: Pesquisa e integração das melhores APIs de leads disponíveis (avaliação + integração)
- [ ] SRC-03: Google Maps melhorado (mais resultados por nicho, menos bloqueios, retry inteligente)
- [ ] SRC-04: Busca no Google melhorada com mais variações de query por nicho

##### Catálogo de Nichos
- [ ] NICHE-01: Catálogo completo de nichos + subnichos pesquisado e armazenado no banco (tabela niches)
- [ ] NICHE-02: Pipeline automático usa nichos do banco (não hardcoded) para rotação
- [ ] NICHE-03: Script/SQL para popular e atualizar catálogo de nichos facilmente
- [ ] NICHE-04: Botão "Selecionar todos / Desselecionar todos" na busca massiva

##### Expansão Regional
- [ ] REG-01: Todas as cidades do Espírito Santo disponíveis no pipeline (tabela ou config)
- [ ] REG-02: Pipeline automático rotaciona pelas cidades do ES progressivamente (não só Grande Vitória)

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
| Nichos hardcoded no código | Tech debt — mover para DB/config | ⚠️ Revisit → Milestone v1.1 NICHE-01/02/03 |

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
*Last updated: 2026-03-28 — Milestone v1.0 complete (6 phases, 20 plans). Milestone v1.1 Lead Quality Engine: Phase 7 complete — QUAL-01/02/03/04/05/06 active, email quality guards + CRM dedup cache + quality-stats endpoint live.*
