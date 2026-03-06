import os
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EXTRAÇÃO MASSIVA - Grande Vitória-ES
Usando TODOS os métodos disponíveis simultaneamente
"""

import sys
import io
import json
import requests
import time
from datetime import datetime

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_BASE_URL = "https://api.extratordedados.com.br"

print("="*80)
print("🚀 EXTRAÇÃO MASSIVA - GRANDE VITÓRIA-ES")
print("="*80)
print(f"⏰ Início: {datetime.now().strftime('%H:%M:%S')}")
print()

# ============================================================
# LOGIN
# ============================================================
print("🔐 Fazendo login...")
response = requests.post(f"{API_BASE_URL}/api/login", json={
    "username": "admin",
    "password": os.environ.get("ADMIN_PASSWORD", "")
})

if response.status_code != 200:
    print(f"❌ Erro no login: {response.status_code}")
    sys.exit(1)

token = response.json().get('token')
headers = {'Authorization': f'Bearer {token}'}
print("✅ Login bem-sucedido!")
print()

# ============================================================
# CONFIGURAÇÃO DE BUSCAS
# ============================================================

# Cidades da Grande Vitória
CIDADES = ["Vitoria", "Vila Velha", "Serra", "Cariacica", "Viana", "Guarapari", "Fundao"]

# Nichos prioritários
NICHOS = [
    "clinica medica",
    "clinica odontologica",
    "clinica veterinaria",
    "escritorio advocacia",
    "escritorio contabilidade",
    "consultoria empresarial",
    "escola particular",
    "imobiliaria"
]

# ============================================================
# MÉTODO 1: API ENRICHMENT (Hunter.io / Snov.io)
# ============================================================
print("="*80)
print("📧 MÉTODO 1: API ENRICHMENT (Hunter.io / Snov.io)")
print("="*80)
print("Rate Limit: 3 buscas/hora")
print()

api_enrichment_jobs = []

# Executar 3 buscas (máximo por hora)
buscas_api = [
    {"niche": "clinica odontologica", "city": "Vitoria", "state": "ES"},
    {"niche": "escritorio contabilidade", "city": "Vila Velha", "state": "ES"},
    {"niche": "consultoria empresarial", "city": "Serra", "state": "ES"}
]

for i, busca in enumerate(buscas_api, 1):
    print(f"[{i}/3] API Enrichment: {busca['niche']} em {busca['city']}-{busca['state']}")

    try:
        response = requests.post(
            f"{API_BASE_URL}/api/search-api",
            headers=headers,
            json={
                "niche": busca['niche'],
                "city": busca['city'],
                "state": busca['state'],
                "max_pages": 2
            },
            timeout=120
        )

        if response.status_code == 200:
            result = response.json()
            batch_id = result.get('batch_id')
            api_enrichment_jobs.append({
                'batch_id': batch_id,
                'niche': busca['niche'],
                'city': busca['city']
            })
            print(f"  ✅ Job criado: batch_id={batch_id}")
        else:
            print(f"  ❌ Erro {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"  ❌ Exceção: {str(e)}")

    print()
    time.sleep(3)

print(f"📊 API Enrichment: {len(api_enrichment_jobs)} jobs criados")
print()

# ============================================================
# MÉTODO 2: BUSCA EM MOTORES (DuckDuckGo / Bing)
# ============================================================
print("="*80)
print("🔍 MÉTODO 2: BUSCA EM MOTORES (DuckDuckGo / Bing)")
print("="*80)
print("Rate Limit: 3 buscas/hora")
print()

search_engine_jobs = []

# Executar 3 buscas por região
buscas_motores = [
    {"niche": "clinica medica", "region": "Grande Vitoria-ES"},
    {"niche": "escritorio advocacia", "region": "Grande Vitoria-ES"},
    {"niche": "imobiliaria", "region": "Grande Vitoria-ES"}
]

for i, busca in enumerate(buscas_motores, 1):
    print(f"[{i}/3] Busca Motores: {busca['niche']} - {busca['region']}")

    try:
        response = requests.post(
            f"{API_BASE_URL}/api/search",
            headers=headers,
            json={
                "niche": busca['niche'],
                "region": busca['region'],
                "max_pages": 2
            },
            timeout=120
        )

        if response.status_code == 200:
            result = response.json()
            batch_id = result.get('batch_id')
            search_engine_jobs.append({
                'batch_id': batch_id,
                'niche': busca['niche'],
                'region': busca['region']
            })
            print(f"  ✅ Job criado: batch_id={batch_id}")
        else:
            print(f"  ❌ Erro {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"  ❌ Exceção: {str(e)}")

    print()
    time.sleep(3)

print(f"📊 Busca Motores: {len(search_engine_jobs)} jobs criados")
print()

# ============================================================
# MÉTODO 3: GOOGLE MAPS PLAYWRIGHT
# ============================================================
print("="*80)
print("🗺️ MÉTODO 3: GOOGLE MAPS PLAYWRIGHT")
print("="*80)
print("Rate Limit: 5 buscas/hora")
print()

google_maps_jobs = []

# Executar 5 buscas (máximo por hora)
queries_gmaps = [
    "clinica medica Vitoria ES",
    "dentista Vila Velha ES",
    "advocacia Serra ES",
    "contabilidade Cariacica ES",
    "consultoria Vitoria ES"
]

for i, query in enumerate(queries_gmaps, 1):
    print(f"[{i}/5] Google Maps: {query}")

    try:
        response = requests.post(
            f"{API_BASE_URL}/api/scrape/google-maps",
            headers=headers,
            json={
                "query": query,
                "maxPlaces": 20
            },
            timeout=120
        )

        if response.status_code == 200:
            result = response.json()
            job_id = result.get('job_id')
            google_maps_jobs.append({
                'job_id': job_id,
                'query': query
            })
            print(f"  ✅ Job criado: job_id={job_id}")
        else:
            print(f"  ❌ Erro {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"  ❌ Exceção: {str(e)}")

    print()
    time.sleep(2)

print(f"📊 Google Maps: {len(google_maps_jobs)} jobs criados")
print()

# ============================================================
# MÉTODO 4: INSTAGRAM BUSINESS PROFILES
# ============================================================
print("="*80)
print("📸 MÉTODO 4: INSTAGRAM BUSINESS PROFILES")
print("="*80)
print("Rate Limit: 3 buscas/hora")
print()

instagram_jobs = []

# Perfis Instagram de negócios da região (exemplos)
perfis_instagram = [
    "clinicavitoriaes",
    "odontologiavv",
    "advocaciaes"
]

for i, profile in enumerate(perfis_instagram, 1):
    print(f"[{i}/3] Instagram: @{profile}")

    try:
        response = requests.post(
            f"{API_BASE_URL}/api/scrape/instagram",
            headers=headers,
            json={
                "username": profile
            },
            timeout=120
        )

        if response.status_code == 200:
            result = response.json()
            job_id = result.get('job_id')
            instagram_jobs.append({
                'job_id': job_id,
                'profile': profile
            })
            print(f"  ✅ Job criado: job_id={job_id}")
        else:
            print(f"  ❌ Erro {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"  ❌ Exceção: {str(e)}")

    print()
    time.sleep(3)

print(f"📊 Instagram: {len(instagram_jobs)} jobs criados")
print()

# ============================================================
# MÉTODO 5: LINKEDIN COMPANIES
# ============================================================
print("="*80)
print("💼 MÉTODO 5: LINKEDIN COMPANIES")
print("="*80)
print("Rate Limit: 2 buscas/hora")
print()

linkedin_jobs = []

# Empresas LinkedIn da região (exemplos)
empresas_linkedin = [
    "clinica-vitoria-es",
    "advocacia-espirito-santo"
]

for i, company in enumerate(empresas_linkedin, 1):
    print(f"[{i}/2] LinkedIn: {company}")

    try:
        response = requests.post(
            f"{API_BASE_URL}/api/scrape/linkedin",
            headers=headers,
            json={
                "company": company
            },
            timeout=120
        )

        if response.status_code == 200:
            result = response.json()
            job_id = result.get('job_id')
            linkedin_jobs.append({
                'job_id': job_id,
                'company': company
            })
            print(f"  ✅ Job criado: job_id={job_id}")
        else:
            print(f"  ❌ Erro {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"  ❌ Exceção: {str(e)}")

    print()
    time.sleep(3)

print(f"📊 LinkedIn: {len(linkedin_jobs)} jobs criados")
print()

# ============================================================
# RESUMO DOS JOBS CRIADOS
# ============================================================
print("="*80)
print("📋 RESUMO DOS JOBS CRIADOS")
print("="*80)
print()
print(f"✅ API Enrichment (Hunter/Snov): {len(api_enrichment_jobs)} jobs")
print(f"✅ Busca em Motores (DuckDuckGo/Bing): {len(search_engine_jobs)} jobs")
print(f"✅ Google Maps Playwright: {len(google_maps_jobs)} jobs")
print(f"✅ Instagram Business: {len(instagram_jobs)} jobs")
print(f"✅ LinkedIn Companies: {len(linkedin_jobs)} jobs")
print()
print(f"🎯 TOTAL: {len(api_enrichment_jobs) + len(search_engine_jobs) + len(google_maps_jobs) + len(instagram_jobs) + len(linkedin_jobs)} jobs em execução")
print()

# Salvar IDs dos jobs para monitoramento
jobs_data = {
    'timestamp': datetime.now().isoformat(),
    'api_enrichment': api_enrichment_jobs,
    'search_engines': search_engine_jobs,
    'google_maps': google_maps_jobs,
    'instagram': instagram_jobs,
    'linkedin': linkedin_jobs
}

with open('jobs_extracao_massiva.json', 'w', encoding='utf-8') as f:
    json.dump(jobs_data, f, ensure_ascii=False, indent=2)

print("💾 IDs dos jobs salvos em: jobs_extracao_massiva.json")
print()

# ============================================================
# AGUARDAR EXECUÇÃO (3 minutos)
# ============================================================
print("="*80)
print("⏳ AGUARDANDO EXECUÇÃO DOS JOBS...")
print("="*80)
print("Jobs em background vão processar nos próximos minutos.")
print("Aguardando 3 minutos antes de verificar resultados...")
print()

for i in range(180, 0, -30):
    print(f"⏱️  {i} segundos restantes...")
    time.sleep(30)

print()
print("✅ Tempo de espera concluído!")
print()

# ============================================================
# VERIFICAR RESULTADOS
# ============================================================
print("="*80)
print("📊 VERIFICANDO RESULTADOS")
print("="*80)
print()

total_leads = 0

# Verificar API Enrichment
print("📧 API Enrichment:")
for job in api_enrichment_jobs:
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/search/{job['batch_id']}/progress",
            headers=headers,
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            leads_count = data.get('total_leads', 0)
            total_leads += leads_count
            print(f"  ✅ {job['niche']} em {job['city']}: {leads_count} leads")
    except Exception as e:
        print(f"  ❌ Erro ao verificar batch {job['batch_id']}")
print()

# Verificar Search Engines
print("🔍 Busca em Motores:")
for job in search_engine_jobs:
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/search/{job['batch_id']}/progress",
            headers=headers,
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            leads_count = data.get('total_leads', 0)
            total_leads += leads_count
            print(f"  ✅ {job['niche']} - {job['region']}: {leads_count} leads")
    except Exception as e:
        print(f"  ❌ Erro ao verificar batch {job['batch_id']}")
print()

# Verificar Google Maps
print("🗺️ Google Maps:")
for job in google_maps_jobs:
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/results/{job['job_id']}",
            headers=headers,
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            leads_count = data.get('results_count', 0)
            total_leads += leads_count
            print(f"  ✅ {job['query']}: {leads_count} leads")
    except Exception as e:
        print(f"  ❌ Erro ao verificar job {job['job_id']}")
print()

# ============================================================
# RESUMO FINAL
# ============================================================
print("="*80)
print("🎉 EXTRAÇÃO MASSIVA CONCLUÍDA!")
print("="*80)
print()
print(f"⏰ Término: {datetime.now().strftime('%H:%M:%S')}")
print()
print(f"📊 TOTAL DE LEADS EXTRAÍDOS: {total_leads}")
print()
print("🔗 Acesse o CRM para ver todos os leads:")
print("   • https://extratordedados.com.br/leads")
print("   • https://crm.alexandrequeiroz.com.br")
print()
print("="*80)
