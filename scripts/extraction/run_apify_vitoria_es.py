import os
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para fazer run do actor Apify - GRANDE VITÓRIA - ES
Busca leads com emails em todas as cidades da região
"""

import sys
import io
from apify_client import ApifyClient
import json

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Inicializar cliente Apify
client = ApifyClient(os.environ.get('APIFY_TOKEN', ''))

# Cidades da Grande Vitória - ES (conforme CLAUDE.md)
CIDADES_GRANDE_VITORIA = [
    "Vitória, ES, Brasil",
    "Vila Velha, ES, Brasil",
    "Serra, ES, Brasil",
    "Cariacica, ES, Brasil",
    "Viana, ES, Brasil",
    "Guarapari, ES, Brasil",
    "Fundão, ES, Brasil"
]

# Nichos relevantes para busca (negócios locais)
NICHOS = [
    "advogado",
    "dentista",
    "restaurante",
    "academia",
    "clínica médica",
    "imobiliária",
    "contabilidade",
    "consultoria",
    "escola",
    "pet shop"
]

# Gerar queries combinando nicho + cidade
search_queries = []
for niche in NICHOS:
    for city in CIDADES_GRANDE_VITORIA:
        search_queries.append(f"{niche} em {city}")

print("="*70)
print("🚀 APIFY - GRANDE VITÓRIA - ES")
print("="*70)
print(f"📍 Cidades: {len(CIDADES_GRANDE_VITORIA)}")
print(f"🏢 Nichos: {len(NICHOS)}")
print(f"🔍 Total de buscas: {len(search_queries)}")
print(f"📊 Estimativa: {len(search_queries) * 20} = {len(search_queries) * 20} leads potenciais")
print("="*70)
print()

# Mostrar preview das buscas
print("📋 Preview das buscas (primeiras 10):")
for i, query in enumerate(search_queries[:10], 1):
    print(f"   {i}. {query}")
print(f"   ... (+{len(search_queries) - 10} buscas)\n")

# Confirmar execução
print("⚠️  ATENÇÃO: Esta run vai consumir créditos da Apify!")
print(f"💰 Custo estimado: ~${(len(search_queries) * 20 * 4) / 1000:.2f} USD")
print()

# Configurar input para buscar leads
run_input = {
    "searchStringsArray": search_queries[:20],  # LIMITANDO A 20 BUSCAS POR ENQUANTO (teste)
    "maxCrawledPlacesPerSearch": 20,
    "language": "pt-BR",
    "scrapeContactFromWebsite": True,  # IMPORTANTE: extrai emails do website
    "scrapeReviews": False,  # Economizar tempo
    "onlyDataFromReviews": False,
    "maxPagesPerSite": 10,  # Quantas páginas visitar por site
    "validateEmails": False  # Acelerar (validar depois se necessário)
}

print(f"🚀 Iniciando run do actor...")
print(f"📊 Configuração:")
print(f"   - Buscas nesta run: {len(run_input['searchStringsArray'])}")
print(f"   - Max por busca: {run_input['maxCrawledPlacesPerSearch']}")
print(f"   - Total estimado: {len(run_input['searchStringsArray']) * run_input['maxCrawledPlacesPerSearch']} leads")
print(f"   - Extração de emails: {'SIM' if run_input['scrapeContactFromWebsite'] else 'NÃO'}")
print()

# Executar actor
print("⏳ Executando... (pode demorar alguns minutos)")
run = client.actor("scraper-mind/google-maps-email-scraper-unlimited").call(run_input=run_input)

# Pegar info da run
run_id = run["id"]
dataset_id = run["defaultDatasetId"]
status = run["status"]

print()
print("="*70)
print("✅ RUN COMPLETADA!")
print("="*70)
print(f"Run ID: {run_id}")
print(f"Dataset ID: {dataset_id}")
print(f"Status: {status}")
print()
print(f"📊 URL da Run: https://console.apify.com/view/runs/{run_id}")
print(f"📦 URL do Dataset: https://api.apify.com/v2/datasets/{dataset_id}/items?format=json")
print("="*70)
print()

# Pegar resultados
print("📥 Baixando resultados...")
results = []
for item in client.dataset(dataset_id).iterate_items():
    results.append(item)

print(f"✅ {len(results)} leads extraídos!")
print()

# Estatísticas
with_email = sum(1 for r in results if r.get('scraped_emails'))
with_phone = sum(1 for r in results if r.get('phone'))
with_both = sum(1 for r in results if r.get('scraped_emails') and r.get('phone'))

print("📊 ESTATÍSTICAS:")
print(f"   📧 Com email: {with_email} ({with_email/len(results)*100:.1f}%)")
print(f"   📞 Com telefone: {with_phone} ({with_phone/len(results)*100:.1f}%)")
print(f"   ✅ Com ambos: {with_both} ({with_both/len(results)*100:.1f}%)")
print()

# Salvar JSON local
output_file = "apify_vitoria_es_leads.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"💾 Resultados salvos em: {output_file}")

# Mostrar amostra com email
leads_com_email = [r for r in results if r.get('scraped_emails')]
if leads_com_email:
    print()
    print("📋 AMOSTRA - Lead com email:")
    sample = leads_com_email[0]
    print(f"   Nome: {sample.get('name')}")
    print(f"   Telefone: {sample.get('phone')}")
    print(f"   Website: {sample.get('website')}")
    print(f"   Cidade: {sample.get('city')}")
    print(f"   Emails: {[e['email'] for e in sample.get('scraped_emails', [])]}")
    print(f"   Rating: {sample.get('avg_rating')}")
    print()

# Informações para importar no CRM
print("="*70)
print("🔗 INFORMAÇÕES PARA IMPORTAR NO CRM:")
print("="*70)
print(f"URL da Run (Automático): https://console.apify.com/view/runs/{run_id}")
print(f"URL do JSON (API): https://api.apify.com/v2/datasets/{dataset_id}/items?format=json")
print(f"Arquivo JSON Local: {output_file}")
print("="*70)
print()
print("✅ Pronto para importar em: https://crm.alexandrequeiroz.com.br/leads/import/")
