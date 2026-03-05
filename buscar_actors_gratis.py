#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Buscar actors GRATUITOS na Apify para extração de emails
"""

import sys
import io
from apify_client import ApifyClient
import json

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

client = ApifyClient("apify_api_dOvao4PhSMHPSNSIaUIarXpW1N736q2e3QDm")

print("="*80)
print("BUSCANDO ACTORS GRATUITOS PARA EXTRAÇÃO DE EMAILS")
print("="*80)
print()

# Lista de actors gratuitos conhecidos para testar
actors_para_testar = [
    "s-r/free-email-domain-scraper",
    "ib4ngz/email-scraper",
    "gordian/email-extractor",
    "dtrungtin/email-extractor",
    "curious_coder/email-extractor"
]

print("Testando actors gratuitos:")
print()

actors_disponiveis = []

for actor_id in actors_para_testar:
    try:
        # Tentar obter informações do actor
        actor_info = client.actor(actor_id).get()

        nome = actor_info.get('name')
        descricao = actor_info.get('description', '')[:100]
        username = actor_info.get('username')

        print(f"✅ {username}/{nome}")
        print(f"   Descrição: {descricao}")
        print()

        actors_disponiveis.append({
            'id': actor_id,
            'name': nome,
            'username': username,
            'description': descricao
        })

    except Exception as e:
        print(f"❌ {actor_id}: {str(e)[:50]}")

print()
print("="*80)
print(f"Actors disponíveis: {len(actors_disponiveis)}")
print("="*80)

if actors_disponiveis:
    print()
    print("Vou testar o primeiro actor com um domínio simples...")
    print()

    # Testar com um domínio
    test_actor = actors_disponiveis[0]
    print(f"Testando: {test_actor['id']}")

    # Configuração de teste (minimalista para economizar créditos)
    test_input = {
        "startUrls": [{"url": "https://informatizecontabilidade.com.br"}],
        "maxDepth": 1,
        "maxPagesPerDomain": 3
    }

    print(f"Input: {test_input}")
    print()

    try:
        print("Executando teste...")
        run = client.actor(test_actor['id']).call(run_input=test_input)

        dataset_id = run["defaultDatasetId"]

        # Baixar resultados
        results = []
        for item in client.dataset(dataset_id).iterate_items():
            results.append(item)

        print(f"✅ Sucesso! {len(results)} resultados")

        if results:
            print()
            print("Sample:")
            print(json.dumps(results[0], indent=2, ensure_ascii=False)[:500])

    except Exception as e:
        print(f"❌ Erro ao testar: {e}")
        print()
        print("Verificando saldo da conta...")
        try:
            user_info = client.user().get()
            print(f"Saldo: ${user_info.get('usage', {}).get('monthlyCredits', 0)}")
        except:
            pass

print()
print("="*80)
print("RECOMENDAÇÃO:")
print("="*80)
print()
print("Para extrair emails da Grande Vitória-ES COM NOMES, recomendo:")
print()
print("1. Usar o scraper interno do sistema (Google Maps + Playwright)")
print("2. OU fazer upgrade da conta Apify ($49/mês)")
print("3. OU usar APIs de enrichment:")
print("   - Hunter.io: $49/mês (1000 emails)")
print("   - Snov.io: $39/mês (1000 créditos)")
print("   - Apollo.io: Plano gratuito (50 emails/mês)")
print()
print("Actors gratuitos na Apify são MUITO limitados e não garantem nomes.")
