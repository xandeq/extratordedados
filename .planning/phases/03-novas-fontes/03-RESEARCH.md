---
phase: 3
slug: novas-fontes
type: research
created: 2026-03-23
---

# Phase 3 Research — Novas Fontes (Receita Federal + Outscraper)

**Researched:** 2026-03-23
**Domain:** Brazilian CNPJ data ingestion, local enrichment, Google Maps API alternative, LinkedIn-to-email enrichment
**Confidence:** HIGH (primary sources verified from official RF metadata PDF, GitHub project, and API docs)

---

## 1. Receita Federal — Dados Abertos CNPJ

### Source

- **Portal oficial:** https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-da-pessoa-juridica---cnpj
- **Mirror direto (mais rápido):** https://arquivos.receitafederal.gov.br/cnpj/dados_abertos_cnpj/
- **Metadata / schema oficial:** https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf
- **Licença:** Domínio público (Lei de Acesso à Informação — LAI). Uso irrestrito.

### Volume e Estrutura

O dataset é distribuído em múltiplos arquivos ZIP. As tabelas principais relevantes para este projeto:

| Arquivo | Conteúdo | Volume estimado |
|---------|----------|-----------------|
| `Estabelecimentos*.zip` | Dados cadastrais por CNPJ (14 dígitos) | ~8-10 GB comprimido, ~15 GB descomprimido |
| `Empresas*.zip` | Razão social, natureza jurídica, capital social, porte | ~2-3 GB |
| `Socios*.zip` | QSA — quadro de sócios e administradores | ~1-2 GB |
| `CNAE*.zip` | Tabela de CNAEs (código → descrição) | Pequeno |
| `Municipios*.zip` | Tabela de municípios RF (código → nome) | Pequeno |

**Frequência de atualização:** Mensal (publicação na virada do mês).

### Campos no arquivo ESTABELECIMENTOS (relevantes para o projeto)

```
cnpj_basico, cnpj_ordem, cnpj_dv    → formam o CNPJ de 14 dígitos
identificador_matriz_filial          → 1=matriz, 2=filial
nome_fantasia
situacao_cadastral                   → 1=nula, 2=ativa, 3=suspensa, 4=inapta, 8=baixada
data_situacao_cadastral
cnae_fiscal_principal
logradouro, numero, complemento, bairro, cep, uf, municipio (código RF)
ddd_1, telefone_1                    → telefone principal
ddd_2, telefone_2                    → telefone secundário
ddd_fax, fax
email                                → email oficial (nem todas as empresas preenchem)
```

**Ponto crítico:** O campo `email` e os campos de telefone (`ddd_1`, `telefone_1`, `ddd_2`, `telefone_2`) estão no arquivo ESTABELECIMENTOS, não em EMPRESAS. O join é feito pelo `cnpj_basico` (8 dígitos).

**Estimativa de cobertura de email:** Não há dado oficial de percentual. Para fins de planejamento, esperar cobertura baixa a moderada — empresas maiores e mais formais tendem a preencher. Para micro-MEI, o campo frequentemente está vazio. Ainda assim, para 60M de CNPJs, mesmo 10% de cobertura = 6M emails oficiais.

### Tooling de Import Existente

**GitHub:** https://github.com/aphonsoar/Receita_Federal_do_Brasil_-_Dados_Publicos_CNPJ

Este projeto Python já resolve o download + parse + insert para PostgreSQL. Pode ser adaptado ou usado como referência. O script principal faz:
1. Download dos ZIPs diretamente do mirror RF
2. Extração e leitura linha a linha (arquivos CSV com separador `;`, encoding `latin-1`)
3. Insert em batch no PostgreSQL

**Ponto de atenção:** O encoding dos arquivos RF é `latin-1` (ISO-8859-1), não UTF-8. Qualquer leitura sem especificar encoding vai corromper acentos.

### Schema Proposto — Tabela `cnpj_rf`

Manter apenas os campos úteis para enriquecimento de leads. Não importar tudo — o volume total exigiria 50+ GB em disco:

```sql
CREATE TABLE cnpj_rf (
    cnpj            CHAR(14) PRIMARY KEY,   -- 14 dígitos sem formatação
    razao_social    TEXT,
    nome_fantasia   TEXT,
    situacao        SMALLINT,               -- 2=ativa
    cnae_principal  VARCHAR(7),
    logradouro      TEXT,
    numero          VARCHAR(10),
    complemento     TEXT,
    bairro          TEXT,
    cep             VARCHAR(8),
    municipio_cod   INTEGER,                -- código RF, join com tabela municipios
    uf              CHAR(2),
    ddd1            VARCHAR(3),
    telefone1       VARCHAR(9),
    ddd2            VARCHAR(3),
    telefone2       VARCHAR(9),
    email           TEXT,
    data_abertura   DATE,
    porte           SMALLINT,               -- 1=ME, 3=EPP, 5=demais
    matriz_filial   SMALLINT                -- 1=matriz, 2=filial
);

CREATE INDEX idx_cnpj_rf_cnpj ON cnpj_rf (cnpj);   -- lookup por CNPJ (PRIMARY já cobre)
CREATE INDEX idx_cnpj_rf_uf_municipio ON cnpj_rf (uf, municipio_cod) WHERE situacao = 2;
CREATE INDEX idx_cnpj_rf_cnae ON cnpj_rf (cnae_principal) WHERE situacao = 2;
```

**Índice principal:** `cnpj` como PRIMARY KEY garante lookup em < 10ms com PostgreSQL B-tree.

### Estimativa de Disco Necessário no VPS

| Item | Estimativa |
|------|-----------|
| ZIPs RF durante download | ~12-15 GB (temporário) |
| Tabela `cnpj_rf` com índices (todos CNPJs) | ~25-35 GB |
| Tabela `cnpj_rf` apenas CNPJs ativos (situacao=2) | ~12-18 GB |
| PostgreSQL WAL e overhead | +20% |

**Recomendação:** Importar apenas `situacao = 2` (ativas) para reduzir volume. Isso elimina ~60% dos registros (empresas baixadas/inativas).

**Verificar antes de iniciar:** Espaço livre no VPS com `df -h`. Se disco < 30 GB livre, importar apenas ativos.

---

## 2. Minha Receita — Self-Hosted CNPJ API

### Projeto

- **GitHub:** https://github.com/cuducos/minha-receita
- **Linguagem:** Go (compilado, binário único, sem dependências de runtime)
- **Licença:** MIT
- **Campos servidos:** 47+ campos dos dados oficiais RF
- **Rate limits:** Nenhum (self-hosted)
- **Status:** Projeto estabelecido e mantido ativamente

### Como Funciona

O Minha Receita:
1. Faz download dos dados RF (mesmo dataset da seção 1)
2. Popula um banco PostgreSQL próprio (ou pode usar o banco já existente)
3. Sobe um servidor HTTP Go na porta configurável
4. Serve `GET /33.000.167/0001-01` (CNPJ formatado) → JSON com 47 campos

### Deploy no VPS (Docker)

O projeto disponibiliza imagem Docker. Padrão recomendado para o VPS:

```bash
# docker-compose.yml (porta 3000 interna — não exposta externamente)
version: "3.8"
services:
  minhareceita:
    image: cuducos/minha-receita:latest
    ports:
      - "127.0.0.1:3000:8080"   # apenas localhost — não expor na internet
    environment:
      - DATABASE_URL=postgres://extrator:SENHA@localhost:5432/extrator
    volumes:
      - ./data:/data
    restart: unless-stopped
```

**Uso interno no Flask:**
```python
resp = http_requests.get(f"http://localhost:3000/{cnpj_formatado}", timeout=3)
```

### Decisão Arquitetural: Minha Receita vs. Tabela `cnpj_rf` direta

| Abordagem | Prós | Contras |
|-----------|------|---------|
| Tabela `cnpj_rf` + `enrich_from_rf_local()` | Sem processo extra, lookup via SQL nativo, zero latência de rede | Importação manual, manutenção de schema |
| Minha Receita (Docker) | API REST pronta, 47 campos ricos, atualizável com um comando | Processo adicional no VPS, porta 3000, Go + download duplicado do dataset |

**Recomendação:** Implementar a tabela `cnpj_rf` direta primeiro (é o que o ROADMAP especifica e é suficiente para o objetivo). O Minha Receita fica como fase posterior se o VPS tiver capacidade. O ROADMAP confirma: "Deploy Minha Receita no VPS (Docker, porta 3000 interna)" como item de escopo, mas "Minha Receita como API pública" está fora de escopo.

**Portanto:** Implementar os dois — `cnpj_rf` local para `enrich_from_rf_local()`, e Minha Receita como API HTTP interna como segunda fonte da fallback chain (antes de BrasilAPI).

---

## 3. Outscraper API

### Visão Geral

- **URL:** https://outscraper.com
- **Documentação API:** https://app.outscraper.com/api-docs
- **Python client:** `pip install outscraper`
- **GitHub:** https://github.com/outscraper/outscraper-python

### Free Tier

- **500 registros/mês** — reseta mensalmente, sem cartão de crédito
- **Dados incluídos:** nome, email, telefone, website, endereço, avaliação, categorias, horários
- **Cobertura:** 100M+ empresas, 249 países

### Pricing Acima do Free

- $3/1.000 registros até 100k
- $1/1.000 registros acima de 100k

### Padrão de Uso via Python Client

```python
from outscraper import ApiClient

client = ApiClient(api_key=OUTSCRAPER_API_KEY)

results = client.google_maps_search(
    ["clinica medica vitoria es"],
    limit=20,
    language="pt",
    region="BR",
    fields=["name", "phone", "email", "full_address", "site", "category"]
)
# results é lista de listas — results[0] é a lista de businesses para a query
```

**Modo assíncrono (para volumes maiores):**
```python
# Usa tasks — retorna task_id, depois faz polling
task = client.google_maps_search(["clinica vitoria es"], async_request=True)
# Depois: client.get_task(task_id)
```

### Integração como 8º Método no Massive Search

O Outscraper será o **método 8** (`outscraper_maps`) em `POST /api/search/massive`. O padrão é idêntico aos demais métodos massivos:

1. Thread daemon com `_massive_retry()` wrapper
2. `process_outscraper_massive(batch_id, jobs_data, user_id)`
3. Flag `quota_exceeded` quando 500 registros/mês esgotados
4. Insert via `_insert_lead_safe()` — mesmo pipeline de dedup/qualidade

### Armazenamento da API Key

A chave Outscraper vai no AWS SM, chave `tools/outscraper` → `OUTSCRAPER_API_KEY`. O padrão do projeto para leitura:

```python
def _get_outscraper_key():
    """Fetch Outscraper API key from AWS SM (with env fallback)."""
    key = os.environ.get('OUTSCRAPER_API_KEY')
    if not key:
        try:
            import boto3
            sm = boto3.client('secretsmanager', region_name='us-east-1')
            secret = sm.get_secret_value(SecretId='tools/outscraper')
            key = json.loads(secret['SecretString']).get('OUTSCRAPER_API_KEY')
        except Exception as e:
            print(f"[outscraper] AWS SM error: {e}")
    return key
```

Seguir exatamente o mesmo padrão de `_get_rapidapi_key()` já existente no app.py.

---

## 4. Prospeo Social URL API

### Visão Geral

- **URL:** https://prospeo.io
- **Documentação API:** https://prospeo.io/api
- **Free tier:** 75 créditos/mês (sem cartão de crédito)
- **Precision:** 16.9% find rate (benchmark independente Set/2025 — lower than competitors but verified)

### Endpoints Relevantes

**Social URL Enrichment** (o mais útil para este projeto — LinkedIn URL → email):

```
POST https://api.prospeo.io/social-url-enrichment
Headers:
  Content-Type: application/json
  X-KEY: {API_KEY}
Body:
  {"url": "https://www.linkedin.com/in/joao-silva-123"}
Response:
  {"email": {"value": "joao@empresa.com.br", "type": "professional", "status": "verified"}}
```

**Domain Search** (domínio → emails encontrados):

```
POST https://api.prospeo.io/domain-search
Body:
  {"domain": "empresa.com.br", "limit": 5}
```

### Fluxo de Integração

O Prospeo complementa o scraping LinkedIn existente. O fluxo proposto:

1. `scrape_linkedin_companies()` (já existe) → retorna leads com `linkedin` URL preenchido
2. `enrich_linkedin_prospeo(linkedin_url)` (novo) → POST para `/social-url-enrichment` → preenche `email` se vazio

A função é chamada durante `process_linkedin_massive()` para leads que tenham `linkedin` preenchido mas `email` vazio.

### Armazenamento da API Key

AWS SM `tools/prospeo` → `PROSPEO_API_KEY`. Mesmo padrão de `_get_outscraper_key()` acima.

---

## 5. CNPJ Fallback Chain

### Comportamento Atual (antes da Phase 3)

O código atual usa dois pontos de enriquecimento CNPJ:

1. **`enrich_cnpj_brasilapi(cnpj)`** — usado em `POST /api/leads/enrich-cnpj` (endpoint manual)
2. **`publica.cnpj.ws/cnpj/{cnpj}`** — usado diretamente em `search_cnpj_open()` e `search_receita_ws()`

Não há fallback chain formal. Se BrasilAPI falha, não há retry para outro provider.

### Fallback Chain Proposta (após Phase 3)

```
enrich_cnpj(cnpj):
  1. cnpj_rf local (PostgreSQL) → < 10ms, sem rede, sem rate limit
  2. Minha Receita local (http://localhost:3000) → < 5ms via loopback
  3. BrasilAPI (brasilapi.com.br/api/cnpj/v1/{cnpj}) → free, sem auth
  4. ReceitaWS (receitaws.com.br/v1/cnpj/{cnpj}) → 3 req/min free
  5. CNPJ.ws (publica.cnpj.ws/cnpj/{cnpj}) → já em uso
```

**Implementação:** Uma função `enrich_cnpj_with_fallback(cnpj)` que substitui todas as chamadas diretas ao BrasilAPI e CNPJ.ws. Cada nível tem timeout curto (3s para locais, 8s para externos). Retorna no primeiro sucesso.

### Normalização de Resposta

Cada provider retorna campos com nomes diferentes. A função `enrich_cnpj_with_fallback()` deve normalizar para o schema interno:

```python
{
    'razao_social': str,
    'nome_fantasia': str,
    'situacao': str,       # 'ativa', 'baixada', etc.
    'cnae': str,           # código 7 dígitos
    'cnae_desc': str,
    'email': str,
    'telefone': str,       # formato: (DDD) XXXXX-XXXX
    'logradouro': str,
    'numero': str,
    'bairro': str,
    'cep': str,
    'municipio': str,
    'uf': str,
    'data_abertura': str,
    'capital_social': float,
    'porte': str,          # 'ME', 'EPP', 'DEMAIS'
    'socios': list,
}
```

---

## 6. Implementation Decisions

### Decisão 1: Importar todos os CNPJs ou apenas ativos?

**Recomendação:** Apenas ativos (`situacao = 2`). Reduz volume em ~60%. CNPJs baixados/inativos têm valor marginal para geração de leads.

Impacto: ~18 GB de dados vs ~35 GB para base completa.

### Decisão 2: `cnpj_rf` no mesmo banco ou banco separado?

**Recomendação:** Mesmo banco PostgreSQL (`extrator`, container `extrator-postgres`). Simplifica o stack — não há necessidade de um segundo container só para isso. O lookup é via `psycopg2` com a mesma `DB_CONFIG` já existente.

### Decisão 3: Script de import — como executar?

O script `scripts/import/import_receita_federal.py` roda **no VPS** (não no Windows local), pois o download é de ~15 GB e o PostgreSQL está no VPS. Fluxo:

```bash
# No VPS, não na máquina local
ssh root@185.173.110.180
python scripts/import/import_receita_federal.py
```

O script faz download direto do mirror RF no servidor. Estima ~2-4 horas para download + import completo (depende da banda do VPS).

### Decisão 4: Minha Receita — implementar agora ou depois?

**Recomendação:** Implementar como etapa separada do plano (Wave 2 ou Wave 3). O Docker no VPS requer verificação de recursos disponíveis antes. Se o disco estiver apertado após importar `cnpj_rf`, pular Minha Receita desta fase.

A fallback chain funciona perfeitamente sem Minha Receita — o nível 1 (SQL local) já resolve o objetivo principal.

### Decisão 5: Outscraper — método independente ou substituto do Google Maps Playwright?

**Recomendação:** Método adicional independente (8º). O Playwright (método `google_maps`) continua funcionando — usa cota gratuita diferente. O Outscraper complementa quando o Playwright falha por CAPTCHA ou quando se quer escalar além do Playwright.

### Decisão 6: Onde guardar API keys de Outscraper e Prospeo?

**Recomendação:** AWS SM, seguindo o padrão obrigatório do projeto:
- `tools/outscraper` → chave `OUTSCRAPER_API_KEY`
- `tools/prospeo` → chave `PROSPEO_API_KEY`

Criar os secrets antes de implementar as funções.

---

## 7. Risks & Pitfalls

### Pitfall 1: Disco insuficiente no VPS

**O que vai errar:** O download dos ZIPs RF (~15 GB) + descompressão + insert vai encher o disco e matar o processo no meio.

**Prevenção:** Verificar `df -h` no VPS antes de iniciar. Script deve verificar espaço livre e abortar com mensagem clara se < 30 GB disponíveis. Deletar ZIPs após import com sucesso.

**Sintoma:** PostgreSQL para de responder, Gunicorn cai por OOM ou I/O.

### Pitfall 2: Encoding latin-1 nos arquivos RF

**O que vai errar:** Acentos em razão social, nome fantasia, endereço aparecem como `?` ou levantam `UnicodeDecodeError`.

**Prevenção:** Abrir arquivos RF explicitamente com `encoding='latin-1'`. Converter para UTF-8 antes de inserir no PostgreSQL.

```python
with open(filepath, encoding='latin-1', errors='replace') as f:
    reader = csv.reader(f, delimiter=';')
```

### Pitfall 3: Import interminável sem progresso visível

**O que vai errar:** O script roda por horas sem feedback. Se o terminal fechar (SSH timeout), o processo morre.

**Prevenção:** Usar `nohup` ou `screen`/`tmux` no VPS. O script deve logar progresso a cada N linhas (ex: a cada 100.000 linhas).

```bash
nohup python scripts/import/import_receita_federal.py > /tmp/rf_import.log 2>&1 &
tail -f /tmp/rf_import.log
```

### Pitfall 4: CNPJ de 14 dígitos vs. 8 dígitos (cnpj_basico)

**O que vai errar:** Os arquivos RF usam `cnpj_basico` (8 dígitos) + `cnpj_ordem` (4) + `cnpj_dv` (2). O CNPJ completo que o projeto usa tem 14 dígitos sem formatação.

**Prevenção:** O script de import deve concatenar os três campos: `cnpj_basico + cnpj_ordem + cnpj_dv` ao fazer o insert. A normalização de lookup deve remover formatação (pontos, barra, hífen) antes de consultar.

```python
cnpj = re.sub(r'\D', '', cnpj_raw)  # remove tudo que não é dígito
assert len(cnpj) == 14
```

### Pitfall 5: Outscraper quota_exceeded no meio de um job massivo

**O que vai errar:** O Outscraper retorna `429` ou mensagem de quota após alguns requests. Se não tratado, o job massivo pode parar ou logar erros confusos.

**Prevenção:** Seguir o padrão `quota_exceeded` já estabelecido no projeto. Quando detectar limite (HTTP 429 ou resposta com `"details": "quota"`), setar flag `quota_exceeded = True` e fazer `continue` no loop. Nunca `raise`.

### Pitfall 6: Minha Receita baixando o dataset RF de novo

**O que vai errar:** Minha Receita tem seu próprio processo de download do dataset RF. Se implantado após a tabela `cnpj_rf` já existir, vai baixar os mesmos ~15 GB de novo e usar disco extra.

**Prevenção:** Configurar Minha Receita para usar o banco PostgreSQL existente se possível, ou aceitar o custo de disco duplicado. Verificar a documentação do projeto para a flag `--database` antes de provisionar.

### Pitfall 7: Import recriando a tabela e apagando dados

**O que vai errar:** Se o script de import rodar uma segunda vez (ex: atualização mensal), pode dropar e recriar a tabela, apagando 25+ GB de dados e precisando reimportar tudo.

**Prevenção:** Usar `INSERT ... ON CONFLICT DO NOTHING` ou `INSERT ... ON CONFLICT (cnpj) DO UPDATE`. Para atualização mensal, usar `UPSERT` — não `TRUNCATE + INSERT`.

### Pitfall 8: Prospeo — 75 créditos esgotam rápido

**O que vai errar:** Com 75 créditos/mês e o pipeline diário rodando todo dia, os 75 créditos acabam em 2-3 dias se não houver controle.

**Prevenção:** Limitar Prospeo a leads de alta qualidade (quality_grade A/B e que vieram do LinkedIn com URL preenchido mas email vazio). Não chamar para todos os leads. Monitorar créditos via API antes de cada chamada.

---

## 8. Code Examples — Padrões do Projeto

### `enrich_from_rf_local(cnpj)` — lookup SQL

```python
def enrich_from_rf_local(cnpj_raw):
    """
    Lookup CNPJ na tabela cnpj_rf (importada da Receita Federal).
    Retorna dict com campos normalizados ou {} se não encontrado.
    Tempo esperado: < 10ms.
    """
    cnpj = re.sub(r'\D', '', cnpj_raw or '')
    if len(cnpj) != 14:
        return {}
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as c:
            c.execute(
                """
                SELECT razao_social, nome_fantasia, situacao,
                       cnae_principal, logradouro, numero, bairro,
                       cep, municipio_cod, uf, ddd1, telefone1, email,
                       porte
                FROM cnpj_rf
                WHERE cnpj = %s
                """,
                (cnpj,)
            )
            row = c.fetchone()
        conn.close()
        if not row:
            return {}
        situacao_map = {2: 'ativa', 3: 'suspensa', 4: 'inapta', 8: 'baixada'}
        telefone = f"({row[10]}) {row[11]}" if row[10] and row[11] else ''
        return {
            'razao_social': row[0],
            'nome_fantasia': row[1],
            'situacao': situacao_map.get(row[2], str(row[2])),
            'cnae': row[3],
            'logradouro': row[4],
            'numero': row[5],
            'bairro': row[6],
            'cep': row[7],
            'uf': row[9],
            'telefone': telefone,
            'email': row[12] or '',
            'source': 'rf_local',
        }
    except Exception as e:
        print(f"[rf_local] Erro CNPJ {cnpj}: {e}")
        return {}
```

### `process_outscraper_massive()` — thread daemon (padrão do projeto)

```python
@_persist_thread_errors('outscraper')
def process_outscraper_massive(batch_id, jobs_data, user_id):
    """Outscraper Google Maps — 8º método massivo. 500 records/mês free."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    api_key = _get_outscraper_key()
    if not api_key:
        print("[outscraper] API key não encontrada — pulando")
        return

    from outscraper import ApiClient
    client = ApiClient(api_key=api_key)
    quota_exceeded = False

    for job in jobs_data:
        if quota_exceeded:
            _update_search_job_status(conn, job['id'], 'failed', 0, 'quota_exceeded')
            continue
        niche = job['niche']
        city = job['city']
        state = job['state']
        query = f"{niche} {city} {state}"
        try:
            results = _massive_retry(
                lambda q=query: client.google_maps_search([q], limit=20, language="pt", region="BR"),
                'outscraper', query
            )
            leads = []
            for biz in (results[0] if results else []):
                leads.append({
                    'company_name': biz.get('name', ''),
                    'email': biz.get('email', ''),
                    'phone': biz.get('phone', ''),
                    'website': biz.get('site', ''),
                    'address': biz.get('full_address', ''),
                    'category': niche,
                    'source': 'outscraper',
                    'source_url': biz.get('url', ''),
                })
            _insert_leads_batch(conn, leads, batch_id, user_id)
            _update_search_job_status(conn, job['id'], 'completed', len(leads))
        except Exception as e:
            msg = str(e).lower()
            if '429' in msg or 'quota' in msg or 'limit' in msg:
                quota_exceeded = True
                print("[outscraper] Quota esgotada — marcando jobs restantes")
            _update_search_job_status(conn, job['id'], 'failed', 0)
    conn.close()
```

### Script de import RF — estrutura central

```python
# scripts/import/import_receita_federal.py
import csv, os, re, zipfile, requests, psycopg2

RF_MIRROR = "https://arquivos.receitafederal.gov.br/cnpj/dados_abertos_cnpj/2026-02/"
BATCH_SIZE = 10_000
ONLY_ACTIVE = True   # situacao = 2

def download_file(url, dest):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

def import_estabelecimentos(filepath, conn):
    c = conn.cursor()
    batch = []
    total = 0
    with open(filepath, encoding='latin-1', errors='replace') as f:
        reader = csv.reader(f, delimiter=';')
        for row in reader:
            # row[4] = situacao_cadastral
            if ONLY_ACTIVE and row[4] != '02':
                continue
            cnpj = row[0] + row[1] + row[2]  # basico+ordem+dv
            record = (
                cnpj, row[6], row[4],  # nome_fantasia, situacao
                row[11],               # cnae_principal
                row[15], row[16], row[17], row[18],  # logradouro, num, compl, bairro
                row[19], row[20], row[21],  # cep, uf, municipio
                row[22], row[23],      # ddd1, tel1
                row[24], row[25],      # ddd2, tel2
                row[27],               # email
            )
            batch.append(record)
            total += 1
            if len(batch) >= BATCH_SIZE:
                c.executemany(
                    "INSERT INTO cnpj_rf (cnpj, nome_fantasia, situacao, cnae_principal, "
                    "logradouro, numero, complemento, bairro, cep, uf, municipio_cod, "
                    "ddd1, telefone1, ddd2, telefone2, email) VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (cnpj) DO NOTHING",
                    batch
                )
                conn.commit()
                batch = []
                print(f"  [import] {total:,} linhas inseridas...")
    if batch:
        c.executemany("INSERT INTO cnpj_rf ...", batch)
        conn.commit()
    print(f"[import] Total: {total:,} registros")
```

**Nota:** Os índices de coluna acima são aproximados baseados na estrutura do metadata RF. Validar com o PDF oficial antes de usar em produção: https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf

---

## Sources

### Primary (HIGH confidence)
- **Receita Federal Dados Abertos** — https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-da-pessoa-juridica---cnpj — schema e campos verificados
- **RF CNPJ Metadata PDF** — https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf — campos ESTABELECIMENTOS incluindo email e telefone confirmados
- **Minha Receita GitHub** — https://github.com/cuducos/minha-receita — projeto Go, MIT, self-hosted
- **GitHub RF importer** — https://github.com/aphonsoar/Receita_Federal_do_Brasil_-_Dados_Publicos_CNPJ — tooling de import Python
- **Outscraper Python client** — https://github.com/outscraper/outscraper-python — API e free tier confirmados
- **Prospeo API Docs** — https://prospeo.io/api — endpoints Social URL Enrichment e Domain Search

### Secondary (MEDIUM confidence)
- **Outscraper Pricing** — https://outscraper.com/pricing/ — 500 records/month free tier (verificado via pesquisa)
- **Prospeo Free Tier** — https://prospeo.io/email-finder — 75 créditos/mês (verificado em benchmark Set/2025)
- **CNPJ.ws** — https://publica.cnpj.ws/cnpj/{cnpj} — já em uso no código do projeto (`app.py` linha 8722)
- **ReceitaWS** — https://receitaws.com.br/v1/cnpj/{cnpj} — já em uso no código do projeto (`app.py` linha 8985)

### Tertiary (LOW confidence)
- Estimativa de percentual de emails preenchidos no dataset RF — baseada em observação geral; o percentual real só é conhecido após o import
- Índices de coluna nos CSVs RF — precisam ser validados contra o PDF de metadados antes do código de import ir a produção

---

## Metadata

**Confidence breakdown:**
- RF dataset e schema: HIGH — verificado no portal oficial e metadata PDF
- Minha Receita: HIGH — projeto GitHub estabelecido, bem documentado
- Outscraper: HIGH — API docs e Python client no GitHub, free tier confirmado
- Prospeo: HIGH — free tier confirmado em múltiplas fontes, API docs disponíveis
- Estimativas de volume/disco: MEDIUM — baseadas em reportes da comunidade, não medição direta
- Índices de coluna nos CSVs RF: MEDIUM — estrutura conhecida, posições exatas requerem validação no PDF

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (dados RF são mensais; APIs Outscraper/Prospeo podem mudar free tier com menor aviso)
