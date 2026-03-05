#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para fazer run do actor Apify e pegar resultados
"""

import sys
import io
from apify_client import ApifyClient
import json

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Inicializar cliente Apify
client = ApifyClient("apify_api_dOvao4PhSMHPSNSIaUIarXpW1N736q2e3QDm")

# Configurar input para buscar leads em Vitória-ES
run_input = {
    "searchStringsArray": [
        "restaurante em Vitória, ES, Brasil",
        "advogado em Vila Velha, ES, Brasil",
        "dentista em Serra, ES, Brasil",
        "academia em Vitória, ES, Brasil",
        "clinica medica em Vila Velha, ES, Brasil"
    ],
    "maxCrawledPlacesPerSearch": 20,  # 20 por busca = 100 leads total (teste)
    "language": "pt-BR",
    "scrapeContactFromWebsite": True,  # IMPORTANTE: extrai emails do website
    "scrapeReviews": False,  # Economizar tempo
    "onlyDataFromReviews": False
}

print("🚀 Iniciando run do actor scraper-mind/google-maps-email-scraper-unlimited...")
print(f"Buscas: {len(run_input['searchStringsArray'])}")
print(f"Max por busca: {run_input['maxCrawledPlacesPerSearch']}")
print(f"Total estimado: {len(run_input['searchStringsArray']) * run_input['maxCrawledPlacesPerSearch']} leads\n")

# Executar actor
run = client.actor("scraper-mind/google-maps-email-scraper-unlimited").call(run_input=run_input)

# Pegar info da run
run_id = run["id"]
dataset_id = run["defaultDatasetId"]
status = run["status"]

print(f"✅ Run completada!")
print(f"Run ID: {run_id}")
print(f"Dataset ID: {dataset_id}")
print(f"Status: {status}")
print(f"\n📊 URL da Run: https://console.apify.com/view/runs/{run_id}")
print(f"📦 URL do Dataset: https://api.apify.com/v2/datasets/{dataset_id}/items?format=json\n")

# Pegar resultados
print("📥 Baixando resultados...")
results = []
for item in client.dataset(dataset_id).iterate_items():
    results.append(item)

print(f"✅ {len(results)} leads extraídos!\n")

# Salvar JSON local
output_file = "apify_leads.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"💾 Resultados salvos em: {output_file}")

# Mostrar amostra
if results:
    print("\n📋 Amostra do primeiro lead:")
    print(json.dumps(results[0], indent=2, ensure_ascii=False)[:500] + "...")

# Informações para importar no CRM
print(f"\n{'='*60}")
print("🔗 INFORMAÇÕES PARA IMPORTAR NO CRM:")
print(f"{'='*60}")
print(f"URL da Run (Automático): https://console.apify.com/view/runs/{run_id}")
print(f"URL do JSON (API): https://api.apify.com/v2/datasets/{dataset_id}/items?format=json")
print(f"Arquivo JSON Local: {output_file}")
print(f"{'='*60}\n")
