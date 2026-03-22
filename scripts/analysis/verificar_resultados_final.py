import os
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verificar TODOS os resultados da extração massiva
e consolidar no CRM
"""

import sys
import io
import json
import requests

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_BASE_URL = "https://api.extratordedados.com.br"

print("="*80)
print("📊 VERIFICAÇÃO FINAL - RESULTADOS DA EXTRAÇÃO MASSIVA")
print("="*80)
print()

# Login
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

# Carregar IDs dos jobs
try:
    with open('jobs_extracao_massiva.json', 'r', encoding='utf-8') as f:
        jobs_data = json.load(f)
except FileNotFoundError:
    print("❌ Arquivo jobs_extracao_massiva.json não encontrado")
    sys.exit(1)

print("="*80)
print("📋 VERIFICANDO RESULTADOS DE CADA MÉTODO")
print("="*80)
print()

total_leads_geral = 0

# ============================================================
# 1. API ENRICHMENT
# ============================================================
print("📧 1. API ENRICHMENT (Hunter.io / Snov.io)")
print("-" * 60)

api_enrichment_jobs = jobs_data.get('api_enrichment', [])
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
            status = data.get('status', 'unknown')
            total_leads_geral += leads_count
            print(f"  ✅ {job['niche']} em {job['city']}")
            print(f"     Status: {status} | Leads: {leads_count}")
        else:
            print(f"  ❌ Erro ao verificar batch {job['batch_id']}: {response.status_code}")
    except Exception as e:
        print(f"  ❌ Exceção: {str(e)}")
print()

# ============================================================
# 2. SEARCH ENGINES
# ============================================================
print("🔍 2. BUSCA EM MOTORES (DuckDuckGo / Bing)")
print("-" * 60)

search_engine_jobs = jobs_data.get('search_engines', [])
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
            status = data.get('status', 'unknown')
            total_leads_geral += leads_count
            print(f"  ✅ {job['niche']} - {job['region']}")
            print(f"     Status: {status} | Leads: {leads_count}")
        else:
            print(f"  ❌ Erro ao verificar batch {job['batch_id']}: {response.status_code}")
    except Exception as e:
        print(f"  ❌ Exceção: {str(e)}")
print()

# ============================================================
# 3. GOOGLE MAPS
# ============================================================
print("🗺️ 3. GOOGLE MAPS PLAYWRIGHT")
print("-" * 60)

google_maps_jobs = jobs_data.get('google_maps', [])
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
            status = data.get('status', 'unknown')
            total_leads_geral += leads_count
            print(f"  ✅ {job['query']}")
            print(f"     Status: {status} | Leads: {leads_count}")
        else:
            print(f"  ❌ Erro ao verificar job {job['job_id']}: {response.status_code}")
    except Exception as e:
        print(f"  ❌ Exceção: {str(e)}")
print()

# ============================================================
# 4. INSTAGRAM
# ============================================================
print("📸 4. INSTAGRAM BUSINESS PROFILES")
print("-" * 60)

instagram_jobs = jobs_data.get('instagram', [])
for job in instagram_jobs:
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/results/{job['job_id']}",
            headers=headers,
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            leads_count = data.get('results_count', 0)
            status = data.get('status', 'unknown')
            total_leads_geral += leads_count
            print(f"  ✅ @{job['profile']}")
            print(f"     Status: {status} | Leads: {leads_count}")
        else:
            print(f"  ❌ Erro ao verificar job {job['job_id']}: {response.status_code}")
    except Exception as e:
        print(f"  ❌ Exceção: {str(e)}")
print()

# ============================================================
# 5. LINKEDIN
# ============================================================
print("💼 5. LINKEDIN COMPANIES")
print("-" * 60)

linkedin_jobs = jobs_data.get('linkedin', [])
for job in linkedin_jobs:
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/results/{job['job_id']}",
            headers=headers,
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            leads_count = data.get('results_count', 0)
            status = data.get('status', 'unknown')
            total_leads_geral += leads_count
            print(f"  ✅ {job['company']}")
            print(f"     Status: {status} | Leads: {leads_count}")
        else:
            print(f"  ❌ Erro ao verificar job {job['company']}: {response.status_code}")
    except Exception as e:
        print(f"  ❌ Exceção: {str(e)}")
print()

# ============================================================
# VERIFICAR STATUS ATUAL DO CRM
# ============================================================
print("="*80)
print("💾 STATUS ATUAL DO CRM")
print("="*80)
print()

try:
    response = requests.get(
        f"{API_BASE_URL}/api/leads",
        headers=headers,
        params={'limit': 1},
        timeout=30
    )

    if response.status_code == 200:
        data = response.json()
        total_crm = data.get('total', 0)
        print(f"📊 TOTAL DE LEADS NO CRM: {total_crm}")
        print()

        # Filtrar por email
        response_email = requests.get(
            f"{API_BASE_URL}/api/leads",
            headers=headers,
            params={'limit': 10000},
            timeout=60
        )

        if response_email.status_code == 200:
            leads_data = response_email.json()
            leads = leads_data.get('leads', [])
            leads_com_email = [l for l in leads if l.get('email') and '@' in l.get('email', '')]

            print(f"📧 LEADS COM EMAIL: {len(leads_com_email)} ({len(leads_com_email)/total_crm*100:.1f}%)")
            print()
except Exception as e:
    print(f"❌ Erro ao verificar CRM: {str(e)}")
    print()

# ============================================================
# RESUMO FINAL
# ============================================================
print("="*80)
print("🎉 RESUMO FINAL DA EXTRAÇÃO MASSIVA")
print("="*80)
print()
print(f"📊 Total de leads extraídos nesta rodada: {total_leads_geral}")
print()
print("✅ Métodos executados:")
print(f"   • API Enrichment: {len(api_enrichment_jobs)} buscas")
print(f"   • Search Engines: {len(search_engine_jobs)} buscas")
print(f"   • Google Maps: {len(google_maps_jobs)} buscas")
print(f"   • Instagram: {len(instagram_jobs)} perfis")
print(f"   • LinkedIn: {len(linkedin_jobs)} empresas")
print()
print(f"🎯 TOTAL DE JOBS EXECUTADOS: {len(api_enrichment_jobs) + len(search_engine_jobs) + len(google_maps_jobs) + len(instagram_jobs) + len(linkedin_jobs)}")
print()
print("🔗 Acesse o CRM:")
print("   • https://extratordedados.com.br/leads")
print("   • https://crm.alexandrequeiroz.com.br")
print()
print("="*80)
