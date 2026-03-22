# 🚀 DEPLOY - BUSCA MASSIVA + APIs EXTERNAS

## 📋 O QUE FOI IMPLEMENTADO

### 1. **Backend (Flask/Python)**
- ✅ Endpoint `/api/search/massive` - Busca massiva com múltiplos métodos
- ✅ Endpoint `/api/enrich/external` - Integração com APIs externas (Apollo.io, PDL, FindThatLead)
- ✅ Funções auxiliares para processar Google Maps em massa

### 2. **Frontend (Next.js/React)**
- ✅ Página `/massive-search` - Interface completa de busca massiva
- ✅ Atualização do Sidebar com link para "Busca Massiva"
- ✅ Seleção de múltiplos nichos
- ✅ Seleção de região
- ✅ Seleção de métodos de extração
- ✅ Resumo em tempo real de jobs estimados

---

## 🔧 PASSO A PASSO DO DEPLOY

### **ETAPA 1: BACKEND (VPS Hostinger)**

#### 1.1. Parar o servidor backend
```bash
ssh root@185.173.110.180
cd /opt/extrator-api
systemctl stop extrator-api
```

#### 1.2. Backup do arquivo atual
```bash
cp app.py app.py.backup_$(date +%Y%m%d_%H%M%S)
```

#### 1.3. Adicionar o novo código ao app.py

**Localização:** Após a linha ~3400 (após o endpoint `/api/search-api`)

**Arquivo de referência:** `massive_search_endpoint.py`

**Copiar manualmente** o conteúdo de `massive_search_endpoint.py` e adicionar no `app.py` na VPS:

```bash
# Na sua máquina local
cat massive_search_endpoint.py

# Copiar o output e colar no app.py da VPS
nano /opt/extrator-api/app.py
# (Colar após linha 3400)
```

**OU usar SCP para copiar:**
```bash
# Na sua máquina local
scp massive_search_endpoint.py root@185.173.110.180:/tmp/
```

Então na VPS:
```bash
# Adicionar ao app.py
# (Copiar manualmente o conteúdo após linha 3400)
```

#### 1.4. Configurar variáveis de ambiente para APIs externas (OPCIONAL)

Se quiser usar as APIs externas (Apollo.io, PDL, FindThatLead), adicione as chaves:

```bash
nano /opt/extrator-api/.env
```

Adicionar:
```env
APOLLO_API_KEY=your_apollo_key_here
PDL_API_KEY=your_pdl_key_here
FINDTHATLEAD_API_KEY=your_findthatlead_key_here
```

#### 1.5. Reiniciar o serviço
```bash
systemctl restart extrator-api
systemctl status extrator-api
```

#### 1.6. Verificar logs
```bash
tail -f /opt/extrator-api/app.log
# ou
journalctl -u extrator-api -f
```

#### 1.7. Testar endpoint
```bash
curl https://api.extratordedados.com.br/api/health
```

---

### **ETAPA 2: FRONTEND (HostGator via FTP)**

#### 2.1. Build do frontend
Na sua máquina local:

```bash
cd project/frontend
npx next build
```

**Verificar se build foi sucesso** (0 erros):
```
✓ Compiled successfully
✓ Collecting page data
✓ Generating static pages
```

#### 2.2. Criar .htaccess no /out/

**IMPORTANTE:** O build apaga o diretório `/out/`, então precisamos recriar o `.htaccess`:

```bash
cat > out/.htaccess << 'EOF'
RewriteEngine On
# Handle Next.js dynamic routes
RewriteRule ^batch/(.+)$ /batch/[id].html [L]
RewriteRule ^results/(.+)$ /results/[id].html [L]
RewriteRule ^massive-search$ /massive-search.html [L]

# If file/directory doesn't exist, try .html extension
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteCond %{REQUEST_FILENAME}.html -f
RewriteRule ^(.*)$ $1.html [L]
EOF
```

#### 2.3. Deploy via FTP

**Opção A: Script Python automático**
```bash
python _test_python/ftp_deploy_frontend.py
```

**Opção B: FTP Manual**
1. Conectar via FileZilla/WinSCP
2. Host: ftp.extratordedados.com.br
3. Usuário: (seu usuário HostGator)
4. Senha: (sua senha)
5. Fazer upload de **TODOS** os arquivos da pasta `project/frontend/out/` para `/public_html/`

#### 2.4. Verificar arquivos no servidor

Certifique-se que estes arquivos existem:
- `/public_html/massive-search.html` ✅
- `/public_html/.htaccess` ✅
- `/public_html/dashboard.html`
- `/public_html/leads.html`
- `/public_html/scrape.html`

---

## ✅ VERIFICAÇÃO PÓS-DEPLOY

### 1. Testar Backend

```bash
# Health check
curl https://api.extratordedados.com.br/api/health

# Login
curl -X POST https://api.extratordedados.com.br/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"1982Xandeq1982#"}'

# Pegar o token e testar endpoint massivo (substituir TOKEN)
curl -X POST https://api.extratordedados.com.br/api/search/massive \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TOKEN" \
  -d '{
    "niches": ["clinica medica"],
    "region": "grande-vitoria-es",
    "methods": ["api_enrichment"],
    "max_pages": 2
  }'
```

### 2. Testar Frontend

Abra no navegador:
- ✅ https://extratordedados.com.br
- ✅ https://extratordedados.com.br/dashboard
- ✅ https://extratordedados.com.br/massive-search ⭐ NOVA PÁGINA

Verificar:
- [ ] Página carrega sem erros 404
- [ ] Sidebar mostra "Busca Massiva" com ícone de raio ⚡
- [ ] É possível selecionar nichos
- [ ] É possível selecionar região
- [ ] É possível selecionar métodos
- [ ] Contador de jobs estimados funciona
- [ ] Botão "Iniciar Busca Massiva" está ativo

### 3. Testar Busca Massiva End-to-End

1. Fazer login em https://extratordedados.com.br
2. Clicar em "Busca Massiva" no sidebar
3. Selecionar 2-3 nichos (ex: Clínica Médica, Clínica Odontológica)
4. Selecionar região "Grande Vitória-ES"
5. Deixar apenas "API Enrichment" ativado (para não saturar rate limits)
6. Clicar em "Iniciar Busca Massiva"
7. Verificar:
   - [ ] Redireciona para `/batch/{id}`
   - [ ] Progresso aparece em tempo real
   - [ ] Jobs são executados em background
   - [ ] Leads são importados automaticamente

---

## 📁 ARQUIVOS CRIADOS/MODIFICADOS

### Novos Arquivos:
```
massive_search_endpoint.py          # Backend: Código a ser adicionado ao app.py
project/frontend/pages/massive-search.tsx   # Frontend: Nova página
DEPLOY_BUSCA_MASSIVA.md            # Este arquivo
RELATORIO_FINAL_EXTRACAO_MASSIVA.md # Relatório de execução
```

### Arquivos Modificados:
```
project/frontend/components/Sidebar.tsx     # Adicionado link "Busca Massiva"
project/backend/app.py                      # (será modificado no deploy)
```

---

## 🔥 TROUBLESHOOTING

### Erro 404 na página /massive-search

**Causa:** `.htaccess` não foi criado ou FTP não fez upload

**Solução:**
```bash
cd project/frontend/out
cat > .htaccess << 'EOF'
RewriteEngine On
RewriteRule ^batch/(.+)$ /batch/[id].html [L]
RewriteRule ^results/(.+)$ /results/[id].html [L]
RewriteRule ^massive-search$ /massive-search.html [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteCond %{REQUEST_FILENAME}.html -f
RewriteRule ^(.*)$ $1.html [L]
EOF

# Re-fazer deploy FTP
python ../_test_python/ftp_deploy_frontend.py
```

### Erro 500 no endpoint /api/search/massive

**Causa:** Código não foi adicionado corretamente ao app.py

**Solução:**
1. SSH na VPS: `ssh root@185.173.110.180`
2. Verificar logs: `tail -f /opt/extrator-api/app.log`
3. Verificar sintaxe: `cd /opt/extrator-api && python3 -m py_compile app.py`
4. Se erro de sintaxe, restaurar backup: `cp app.py.backup_* app.py`
5. Reiniciar: `systemctl restart extrator-api`

### Rate Limit Exceeded

**Causa:** Múltiplas execuções na mesma hora

**Solução:**
- Aguardar 1 hora para reset
- Ou usar apenas "API Enrichment" (rate limit mais alto)
- Ou desabilitar rate limit temporariamente (linha `@limiter.limit("1/hour")`)

### Jobs não aparecem no batch

**Causa:** Background thread falhou

**Solução:**
1. Verificar logs do backend
2. Verificar se PostgreSQL está rodando: `systemctl status postgresql`
3. Verificar conexões ao DB: `psql -U extrator -d extrator -c "SELECT COUNT(*) FROM batches;"`

---

## 🎯 PRÓXIMOS PASSOS

Após deploy bem-sucedido:

### 1. Cadastrar APIs Externas (Opcional)

Cadastre-se gratuitamente em:
- **Apollo.io** - https://www.apollo.io (50 emails/month)
- **PDL (People Data Labs)** - https://www.peopledatalabs.com (1000 credits/month)
- **FindThatLead** - https://findthatlead.com (50 emails/month)

Adicione as chaves em `/opt/extrator-api/.env`

### 2. Monitorar Performance

```bash
# Verificar uso de CPU/RAM
htop

# Verificar disco
df -h

# Verificar logs em tempo real
tail -f /opt/extrator-api/app.log
```

### 3. Executar Busca Massiva de Teste

Execute uma busca massiva pequena para validar:
- 1-2 nichos
- 1 região
- Apenas API Enrichment
- max_pages = 1

### 4. Escalar Gradualmente

Depois do teste:
- Aumentar para 3-5 nichos
- Ativar múltiplos métodos
- max_pages = 2-3

---

## 📞 SUPORTE

Em caso de dúvidas ou problemas:

1. **Verificar logs:**
   - Backend: `tail -f /opt/extrator-api/app.log`
   - Frontend: Console do navegador (F12)

2. **Restaurar backup:**
   - Backend: `cp app.py.backup_* app.py && systemctl restart extrator-api`
   - Frontend: Re-fazer deploy

3. **Health check:**
   - API: https://api.extratordedados.com.br/api/health
   - Frontend: https://extratordedados.com.br/dashboard

---

## 🎉 CONCLUSÃO

Após este deploy, você terá:

✅ **Interface de Busca Massiva** completa e intuitiva
✅ **Endpoint `/api/search/massive`** funcional
✅ **Suporte a múltiplos métodos** simultaneamente
✅ **Integração com APIs externas** (Apollo.io, PDL, FindThatLead)
✅ **Deduplicação automática** de leads
✅ **Progresso em tempo real** por método

**Potencial:** +50-100 leads com email por busca massiva! 🚀

---

**Data:** 04/03/2026
**Versão:** 1.0.0
**Autor:** Claude Code
