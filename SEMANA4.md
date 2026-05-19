# Semana 4 — Escopo e Prioridades

**Base**: semana3 branch (PR pendente → main)
**Status ao entrar**: Email Campaigns + Image Gen estáveis, 16/17 smoke tests ✅

---

## Objetivo da Semana 4

Evoluir de "features funcionando" para "features utilizáveis em produção por clientes reais":
validar fluxos end-to-end com dados reais, adicionar controles operacionais que faltam,
e entregar visibilidade aos usuários sobre o que está acontecendo com seus envios.

---

## P0 — Merge e Estabilidade Base

| Item | Ação |
|------|------|
| PR semana3 → main | Abrir e aprovar (já limpo, 16/17 testes ✅) |
| Regression test para double-send | Capturar o timing: enviar → polling até status=`active` → reenviar → esperar 409 |
| Testar envio real com lead real | 1 campanha de teste com 3 leads reais → verificar entrega, abertura, unsubscribe |

---

## P1 — Observabilidade e Controles

| Item | Justificativa |
|------|--------------|
| **Endpoint GET /api/campaigns/<id>/log** | Usuário precisa ver o progresso em tempo real: quantos enviados, quando, qual provider |
| **Webhook de bounces (Brevo + Resend)** | Bounces não tratados queimam a reputação do domínio. Receber `hard_bounce` → marcar lead como `bounced` |
| **Alertas de quota** | Enviar notificação (toast + log) quando provider chegar em 80% do limite diário |
| **Admin dashboard básico** | Tabela com sends por provider por dia (usar `email_provider_usage`) |

---

## P2 — Qualidade dos Envios

| Item | Justificativa |
|------|--------------|
| **Sender name personalizado por campanha** | Hoje é fixo `"Extrator DIAX"` — permitir customização no create/update |
| **Preview do email antes de enviar** | Modal com render HTML do body antes de confirmar o envio |
| **Segmento por `quality_grade`** | UI já tem campo, mas não usa no filtro do `target_filter` quando vazio |
| **Descadastro global** | Hoje unsubscribe é por campanha; deve ser global (não receber de nenhuma campanha) |

---

## P3 — Modularização Contínua (app.py)

| Extração | Bloqueios |
|----------|-----------|
| `email_campaigns.py` Blueprint (rotas + DB workers) | Requer `db_utils.py` para evitar circular import |
| `db_utils.py` (get_db, DB_CONFIG, get_pool) | App.py usa ~200 `with get_db()` calls — trocar para import |
| `stripe_routes.py` Blueprint | Menor risco, ~200 linhas, sem dependências cruzadas |

**Ordem recomendada**: db_utils.py → email_campaigns Blueprint → stripe_routes Blueprint

---

## P4 — Image Generation (quando email estiver estável)

| Item | Justificativa |
|------|--------------|
| Histórico de imagens geradas (DB) | Usuário não consegue recuperar imagens anteriores |
| Estimativa de custo antes de gerar | Mostrar `~$X.XX` com base no modelo selecionado |
| Download direto (proxy via API) | FAL URLs expiram; salvar no S3/R2 ou proxy para persistência |

---

## Riscos Conhecidos

| Risco | Mitigação |
|-------|-----------|
| Domain reputation: enviar para leads F-grade via fallback filter | Validação `quality_grade != 'F'` já no SQL; testar antes de escalar |
| 2 Gunicorn workers disparando automation | Advisory lock implementado (`pg_try_advisory_lock`); monitorar logs `[EMAIL-AUTO] Skipping` |
| Provider tokens expirados (SendPulse OAuth) | Refresh automático no `send_via_sendpulse`; adicionar retry se token expirou (401) |
| Rate limit do HostGator FTP | Deploy lento (~150s); aceitável por ora. Alternativa: rsync ou S3 |
| Image gen: FAL.AI URLs expiram em 24h | Não salvar FAL URLs no BD sem proxy — tarefa P4 acima |

---

## Métricas de Sucesso para Semana 4

- [ ] 1 campanha com envio real validado (entrega + abertura + unsubscribe)
- [ ] PR semana3 mergeado em main
- [ ] Endpoint de log de campanha funcionando
- [ ] Webhook de bounces configurado em pelo menos 1 provider
- [ ] db_utils.py extraído, app.py < 19.500 linhas
