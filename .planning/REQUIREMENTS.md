# REQUIREMENTS.md — Extrator de Dados

> Gerado em: 2026-03-22 | Baseado em: PROJECT.md + 4 research reports

---

## Milestone 1 — Pipeline Autônomo + Qualidade + Fontes

**Objetivo**: Base de leads crescendo sozinha, com qualidade auditável, sem intervenção manual.

---

### Fase 1 — Pipeline 100% Automático

**Goal**: Operador abre o sistema de manhã e vê relatório do que rodou à noite.

#### Backend
- [ ] Tabela `pipeline_config` (key/value, JSON) para armazenar nichos ativos, região ativa, hora de execução
- [ ] `GET/PUT /api/admin/pipeline/config` — ler e atualizar configuração (nichos, região, hora, ativo/inativo)
- [ ] `run_daily_pipeline()` lê nichos/região do DB em vez de constantes hardcoded
- [ ] `scheduler.reschedule_job()` chamado quando admin altera hora de execução
- [ ] `GET /api/admin/pipeline/health` — retorna: última execução, status, leads capturados, taxa de sucesso 30 dias, próxima execução
- [ ] `_generate_pipeline_report()` no final da execução: leads capturados, erros, por método
- [ ] Envio do relatório via Brevo email após pipeline (usa `tools/brevo` do AWS SM)
- [ ] Ping para healthchecks.io ao final de execução bem-sucedida (dead-man's-switch, free tier)

#### Frontend
- [ ] Página `/admin/pipeline-config` — editar nichos ativos, região, hora de execução, toggle ativo
- [ ] Card de health na página admin: última execução, próxima, leads ontem, status verde/amarelo/vermelho
- [ ] Histórico dos últimos 30 dias de execução (tabela com data, leads, status, duração)

#### Critérios de aceite
- Pipeline roda sem intervenção manual
- Email de relatório chega após cada execução
- Admin consegue alterar nichos sem editar código
- Health endpoint retorna estado correto

---

### Fase 2 — Qualidade de Leads

**Goal**: Cada lead tem um score A-F auditável. Emails inválidos não entram na base.

#### Backend
- [ ] Instalar: `email-validator`, `dnspython`, `disposable-email-domains`, `phonenumbers`
- [ ] `validate_email_free(email)` → 3 camadas: formato (email-validator) + MX record (dnspython, cached por domínio) + disposable blocklist
- [ ] `normalize_phone_br(phone)` via `phonenumbers` → E.164 + DDD válido + mobile vs landline + WhatsApp ID (`55DD9XXXXXXXX@c.us`)
- [ ] Score 6 dimensões (retorna A/B/C/D/F + score numérico 0-100):
  - Email válido (30%) — formato + MX + não-disposable
  - Telefone completo (20%) — E.164 normalizado, DDD válido
  - Completeness (20%) — website + empresa + cidade/estado preenchidos
  - Freshness (15%) — age-decay: fresh(0-60d)=1.0, aging(61-180d)=0.7, stale(181-365d)=0.4, very-stale(365d+)=0.1
  - CNPJ enriched (10%) — dados da Receita Federal presentes
  - Source quality (5%) — Google Maps > diretórios > scraping genérico
- [ ] Migrations DB: colunas `captured_at`, `last_verified_at`, `freshness_score`, `quality_grade` (A/B/C/D/F) na tabela `leads`
- [ ] `POST /api/leads/validate-batch` — revalidar lote de leads e atualizar scores
- [ ] Deduplicação cross-batch: UNIQUE constraint em `email` (sem restrição de batch_id)
- [ ] Botão "Verificar Email" no lead drawer — consome 1 crédito ZeroBounce (100 grátis/mês, AWS SM)

#### Frontend
- [ ] Badge de qualidade (A/B/C/D/F) na lista de leads e no drawer
- [ ] Filtro por quality grade na página de leads
- [ ] Indicador de freshness: ícone verde/amarelo/vermelho por recência
- [ ] Coluna "Qualidade" na tabela de leads (ordenável)

#### Critérios de aceite
- Leads com MX inválido não são salvos
- Telefones normalizados para E.164
- Score calculado automaticamente em cada inserção
- Dedup funciona entre batches diferentes

---

### Fase 3 — Novas Fontes (Receita Federal + Outscraper)

**Goal**: Base enriquecida com dados oficiais, novos leads de fontes não usadas antes.

#### Backend
- [ ] Script de importação do dataset CNPJ da Receita Federal (ESTABELECIMENTOS.zip, ~15GB) para tabela `cnpj_rf` local
- [ ] `enrich_from_rf_local(cnpj)` — lookup no PostgreSQL local, retorna email, telefone, nome fantasia, CNAE, porte
- [ ] Substituir chamadas BrasilAPI por lookup local quando CNPJ disponível (BrasilAPI como fallback para CNPJs recentes)
- [ ] Deploy Minha Receita no VPS (Docker container na porta 3000, apenas rede interna)
- [ ] Integração Outscraper API (500 leads/mês free) como método adicional no massive search
- [ ] Integração Prospeo Social URL API (LinkedIn URL → email verificado, 75/mês free)
- [ ] Fallback chain CNPJ: `cnpj_rf_local` → BrasilAPI → ReceitaWS → CNPJ.ws

#### Scripts
- [ ] `scripts/import/import_receita_federal.py` — download + parsing + insert do dataset RF
- [ ] Documentação do processo em `docs/RECEITA_FEDERAL_IMPORT.md`

#### Critérios de aceite
- Lookup CNPJ local mais rápido que BrasilAPI (< 10ms)
- Taxa de fill de email/telefone do dataset RF medida e documentada
- Outscraper aparece como 8º método no massive search

---

## Milestone 2 — Portal de Clientes

**Objetivo**: 1º cliente pagando para acessar a base de leads.

---

### Fase 4 — Tier Cliente + Reveal Gate

**Goal**: Clientes se cadastram e acessam base mascarada com sistema de créditos.

#### Backend
- [ ] Role `client` no sistema de usuários (além de `admin` e `operator`)
- [ ] Tabela `credit_ledger` (user_id, amount, operation, reference_id, created_at)
- [ ] `deduct_credit(user_id, operation, ref_id)` com `SELECT FOR UPDATE` — previne race condition
- [ ] `POST /api/leads/reveal/<id>` — revela email/phone de um lead (-1 crédito)
- [ ] `GET /api/client/credits` — saldo atual e histórico
- [ ] `GET /api/leads/search` — busca avançada para clientes: nicho, cidade, estado, quality_grade mínimo, has_email, has_phone, has_whatsapp, has_website, has_cnpj
- [ ] Campos mascarados no response para clientes: email = `"jo***@gmail.com"`, phone = `"27 9****-5678"`
- [ ] Rate limit de busca por cliente (ex: 100 buscas/hora)
- [ ] Planos: Free (10 créditos/mês), Básico (200/mês), Pro (1000/mês), Enterprise (ilimitado)

#### Frontend
- [ ] Página `/leads` para clientes: UI diferente do admin — sem bulk actions, sem export direto
- [ ] Lead card com campos mascarados + botão "Revelar" com contador de créditos
- [ ] Filtros avançados: segmento, cidade, estado, qualidade mínima, campos presentes
- [ ] Sidebar com saldo de créditos + histórico
- [ ] Página `/plans` com comparativo de planos e botão de upgrade (Stripe futuro, manual agora)

#### Critérios de aceite
- Cliente não consegue ver email/phone sem gastar crédito
- Deduct é atômico (sem double-spend)
- Busca retorna resultados em < 500ms com 100k+ leads

---

### Fase 5 — Export + Niche Request Queue

**Goal**: Clientes exportam listas e solicitam novos nichos.

#### Backend
- [ ] `GET /api/client/leads/export` — exporta CSV/JSON respeitando cota do plano (ex: 500 leads/mês)
- [ ] Export debita créditos: 1 crédito por lead exportado
- [ ] Tabela `niche_requests` (user_id, niche, city, state, votes, status, created_at)
- [ ] `POST /api/client/niche-requests` — criar solicitação
- [ ] `POST /api/client/niche-requests/<id>/vote` — votar em solicitação existente (evita duplicatas)
- [ ] `GET /api/admin/niche-requests` — admin vê lista ordenada por votos
- [ ] `POST /api/admin/niche-requests/<id>/approve` — aprova e adiciona à fila de extração

#### Frontend
- [ ] Botão "Exportar Selecionados" para clientes (com aviso de créditos)
- [ ] Página `/request-niche` — formulário de solicitação + lista de solicitações populares com votos
- [ ] Admin: `/admin/niche-requests` — tabela com votos, status, botão aprovar/rejeitar

#### Critérios de aceite
- Export respeita limite do plano
- Voto não duplica (1 voto por user por nicho+cidade)
- Aprovação de nicho dispara extração automática

---

### Fase 6 — Saved Searches + Notificações

**Goal**: Clientes recebem email quando chegam novos leads nos seus filtros salvos.

#### Backend
- [ ] Tabela `saved_searches` (user_id, name, filters JSONB, last_notified_at, notify_email)
- [ ] `POST/GET/DELETE /api/client/saved-searches`
- [ ] Job APScheduler diário às 08:00 — compara leads novos (desde `last_notified_at`) contra filtros salvos
- [ ] Email de notificação via Brevo: "X novos leads em Clínicas em Vitória/ES"
- [ ] Máximo 1 email/dia por saved search (mesmo que haja múltiplos novos lotes)

#### Frontend
- [ ] Botão "Salvar Busca" na página de busca para clientes
- [ ] Página `/saved-searches` — listar, nomear, deletar, toggle notificação

#### Critérios de aceite
- Notificação chega dentro de 24h após novos leads no filtro
- Sem duplicatas de email

---

---

## Milestone v1.1 — Lead Quality Engine

**Objetivo**: Base de leads de altíssima qualidade. Apenas leads com email válido OR WhatsApp válido entram. Pipeline roda automaticamente por todos os nichos e cidades do ES.

**Contexto**: Milestones v1.0 (Phases 1-6) 100% completos. Agora é escalar qualidade e volume.

---

### Fase 7 — Qualidade de Leads Avançada (QUAL-01 a QUAL-06)

**Goal**: Zero leads ruins na base. Cada lead que entra tem email válido ou WhatsApp válido, sem duplicatas com o CRM, sem emails estrangeiros ou slogans.

#### Backend
- [ ] **QUAL-01**: Expandir `validate_email_free()` — rejeitar emails bounceáveis conhecidos (disposable + domínios de baixa reputação), integrar lista de bounce domains atualizada
- [ ] **QUAL-02**: Filtro de TLD estrangeiro em `save_lead_to_db()` — rejeitar `.es`, `.pt`, `.pl`, `.com.ar`, `.mx`, `.co`, `.uk`, `.de`, `.fr`, `.it` e outros TLDs não-BR
- [ ] **QUAL-03**: Detector de email-slogan — regex + heurística: email com 4+ palavras, contém verbos, frases (ex: `contato@faleconoscoagora.com.br` OK, `venhaserfeliz@empresa.com` → rejeitar)
- [ ] **QUAL-04**: Dedup contra CRM — antes do CRM sync, verificar se email/telefone já existe via `GET /api/crm/check` ou lookup local em cache; não re-enviar leads já no CRM
- [ ] **QUAL-05**: Validar WhatsApp com `phonenumbers` — verificar DDD válido BR (11-99 para celular), formato correto, comprimento mínimo; rejeitar números claramente inválidos
- [ ] **QUAL-06**: Gate CRM — `auto_sync_new_leads_background()` só envia leads que têm email válido (quality_grade != 'F' no campo email) OR whatsapp não-nulo e válido
- [ ] Novo campo `rejection_reason` (varchar) em `leads` — registra motivo de rejeição quando lead é descartado
- [ ] Endpoint `GET /api/admin/quality-stats` — métricas: taxa de rejeição por motivo, leads aceitos/rejeitados por dia

#### Frontend
- [ ] Card de qualidade no admin dashboard: "N leads rejeitados hoje / motivo mais comum"
- [ ] Filtro na página de leads: "Rejeitados" / "Aceitos" / "Todos"

#### Critérios de aceite
- Nenhum email com TLD estrangeiro entra na base após a fase
- Taxa de rejeição por email-slogan < 5% (evita over-rejection)
- 0 duplicatas enviadas ao CRM (leads já existentes não re-enviados)
- Leads sem email válido E sem WhatsApp válido não chegam ao CRM

---

### Fase 8 — Catálogo de Nichos (NICHE-01 a NICHE-04)

**Goal**: Pipeline roda automaticamente por 200+ nichos e subnichos. Admin seleciona "todos" ou subsets via UI.

#### Backend
- [x] **NICHE-01**: Tabela `niches` (id, name, category, subcategory, keywords[], active, priority, created_at) — catálogo completo de nichos BR relevantes
- [x] **NICHE-02**: `get_pipeline_config()` lê nichos ativos da tabela `niches` (não mais `pipeline_config.nichos`) para rotação diária
- [x] **NICHE-03**: Script `scripts/import/populate_niches.sql` — INSERT de 150+ nichos + subnichos organizados por categoria (saúde, beleza, alimentação, serviços, educação, etc.)
- [ ] `GET /api/admin/niches` — lista todos os nichos com status ativo/inativo
- [ ] `PUT /api/admin/niches/bulk` — ativar/desativar múltiplos nichos de uma vez
- [ ] Pipeline rotaciona: em vez de rodar todos os nichos em 1 dia, rotaciona grupos de 20 nichos/dia

#### Frontend
- [x] **NICHE-04**: Botão "Selecionar todos / Desselecionar todos" na página de busca massiva
- [ ] Página `/admin/niches` — lista categorizada de nichos, toggle ativo, prioridade

#### Critérios de aceite
- 150+ nichos cadastrados no banco após execução do script
- Pipeline usa nichos do banco (zero hardcoded)
- "Selecionar todos" funciona em 1 clique na busca massiva

---

### Fase 9 — Expansão Regional ES (REG-01 a REG-02)

**Goal**: Pipeline cobre todo o Espírito Santo progressivamente, não só Grande Vitória.

#### Backend
- [x] **REG-01**: Tabela `regions` (id, name, city, state, ibge_code, priority, active) — todas as 78 cidades do ES
- [x] Script `scripts/import/populate_es_cities.sql` — INSERT das 78 cidades do ES com dados IBGE
- [x] **REG-02**: `run_daily_pipeline()` rotaciona por cidades do ES em grupos de 5-10/dia (round-robin por `last_used_at`)
- [x] `GET /api/admin/regions` — listar regiões com última execução, leads capturados
- [x] `PUT /api/admin/regions/bulk` — ativar/desativar regiões

#### Frontend
- [ ] Mapa ou lista de cidades na página de pipeline config — verde = executado nos últimos 7 dias
- [ ] Seletor de região na busca massiva atualizado com todas as cidades do ES

#### Critérios de aceite
- 78 cidades do ES disponíveis (não só Grande Vitória)
- Pipeline rotaciona automaticamente, sem repetir cidades na mesma semana
- Admin vê quais cidades foram cobertas e quando

---

### Fase 10 — Novas Fontes (SRC-01 a SRC-04)

**Goal**: Mais volume de leads de qualidade via fontes novas e melhorias nas existentes.

#### Backend
- [ ] **SRC-01**: Apple Maps scraper — `process_apple_maps_massive()` usando API não-oficial ou Playwright; integrar como Thread 17 no massive search
- [ ] **SRC-02**: Pesquisar e avaliar top 5 APIs de leads BR (FindThatLead, Snov.io, Hunter.io, Apollo, Lusha BR) — implementar a melhor opção gratuita/low-cost; integrar como método adicional
- [ ] **SRC-03**: Melhorar `process_outscraper_massive()` — retry com backoff, cursor-based pagination, aumentar max_results por query de 20 → 100, usar `search_queries` em batch
- [ ] **SRC-04**: Melhorar `process_search_job()` — adicionar 5 templates de query por nicho (ex: `"[nicho] [cidade] contato"`, `"[nicho] [cidade] email"`, `"[nicho] [cidade] whatsapp"`, `site:*.com.br "[nicho]" "[cidade]"`, `"[nicho]" "[cidade]" OR "[cidade vizinha]"`)
- [ ] Novo endpoint `GET /api/admin/source-stats` — leads capturados por fonte nos últimos 30 dias

#### Frontend
- [ ] Gráfico de barras no admin dashboard: leads por fonte (Google Maps, Apple Maps, diretórios, etc.)

#### Critérios de aceite
- Apple Maps gera leads em teste piloto com Grande Vitória
- Google Maps (Outscraper) aumenta volume ≥ 50% vs baseline
- Cada nicho tem ≥ 5 variações de query na busca por motores

---

## Backlog (não neste milestone)

| Ideia | Razão |
|-------|-------|
| Stripe para pagamentos | Manual por enquanto (cliente solicita, admin libera créditos) |
| API pública para clientes | Após portal estabilizar |
| Mobile app | Web-first |
| WhatsApp notification (Meta API) | Brevo email suficiente por agora |
| Celery/RQ para jobs | Requer Redis — desnecessário para 1 job/dia |
| LinkedIn Sales Navigator | Custo alto, scraping atual suficiente |
| MillionVerifier bulk validation | Pago — implementar como feature de plano pago |
| Expansão para outros estados (SP, RJ, MG) | Após ES coberto 100% |

---

*Last updated: 2026-03-24 — Milestone v1.1 Lead Quality Engine requirements added*
