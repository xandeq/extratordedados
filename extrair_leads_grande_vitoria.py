#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extrair leads COM EMAILS da Grande Vitória-ES
Usando scrapers internos do sistema (DuckDuckGo + enrichment)
"""

import sys
import io
import json
import requests
import time

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_BASE_URL = "https://api.extratordedados.com.br"

print("="*80)
print("EXTRAÇÃO DE LEADS COM EMAIL - GRANDE VITÓRIA-ES")
print("="*80)
print()

# Login
print("🔐 Fazendo login...")
response = requests.post(f"{API_BASE_URL}/api/login", json={
    "username": "admin",
    "password": "1982Xandeq1982#"
})

if response.status_code != 200:
    print(f"❌ Erro no login: {response.status_code}")
    sys.exit(1)

token = response.json().get('token')
print("✅ Login OK!")
print()

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

# Nichos para buscar
nichos = [
    "clinica medica",
    "clinica odontologica",
    "clinica veterinaria",
    "escritorio advocacia",
    "escritorio contabilidade",
    "consultoria empresarial",
    "escola particular",
    "colegio particular",
    "imobiliaria"
]

# Cidades da Grande Vitória
cidades = ["Vitoria", "Vila Velha", "Serra", "Cariacica"]

print("📊 Configuração da busca:")
print(f"   Nichos: {len(nichos)}")
print(f"   Cidades: {len(cidades)}")
print(f"   Total de buscas: {len(nichos) * len(cidades)}")
print()

# Criar batch de busca
print("📤 Criando job de busca...")

batch_data = {
    "name": f"Grande Vitória-ES - Múltiplos Nichos - {time.strftime('%d/%m/%Y')}",
    "niche": "multiplos",  # Vamos fazer uma busca por vez
    "cities": cidades,
    "max_pages": 2,  # Limitar para não sobrecarregar
    "extract_emails": True  # Forçar extração de emails
}

# Como o sistema não tem endpoint batch para search, vamos fazer buscas individuais
print("🔍 Iniciando buscas por nicho...")
print()

all_jobs = []

for nicho in nichos:
    print(f"📍 Nicho: {nicho}")

    # Criar busca
    search_data = {
        "niche": nicho,
        "cities": cidades,
        "state": "ES",
        "region": "Grande Vitória-ES",
        "max_pages": 2,
        "engine": "duckduckgo"
    }

    response = requests.post(
        f"{API_BASE_URL}/api/search",
        headers=headers,
        json=search_data
    )

    if response.status_code == 200:
        job = response.json()
        batch_id = job.get('batch_id')
        all_jobs.append({'nicho': nicho, 'batch_id': batch_id})
        print(f"   ✅ Batch ID: {batch_id}")
    else:
        print(f"   ❌ Erro: {response.status_code}")

    # Delay entre buscas para não sobrecarregar
    time.sleep(2)

print()
print(f"✅ {len(all_jobs)} buscas iniciadas!")
print()

# Aguardar conclusão
print("⏳ Aguardando conclusão das buscas...")
print("   (Isso pode levar vários minutos...)")
print()

completed_jobs = []
max_wait = 600  # 10 minutos
start_time = time.time()

while len(completed_jobs) < len(all_jobs) and (time.time() - start_time) < max_wait:
    for job in all_jobs:
        if job in completed_jobs:
            continue

        batch_id = job['batch_id']

        # Verificar progresso
        response = requests.get(
            f"{API_BASE_URL}/api/search/{batch_id}/progress",
            headers=headers
        )

        if response.status_code == 200:
            progress = response.json()
            status = progress.get('status')
            total_leads = progress.get('total_leads', 0)

            if status == 'completed':
                completed_jobs.append(job)
                job['total_leads'] = total_leads
                print(f"✅ {job['nicho']}: {total_leads} leads")
            elif status == 'failed':
                completed_jobs.append(job)
                print(f"❌ {job['nicho']}: FALHOU")

    # Aguardar antes de verificar novamente
    if len(completed_jobs) < len(all_jobs):
        time.sleep(10)

print()
print("="*80)
print("RESULTADO DAS BUSCAS")
print("="*80)

total_leads_found = sum(job.get('total_leads', 0) for job in completed_jobs)
print(f"Total de leads encontrados: {total_leads_found}")
print()

# Baixar todos os leads
print("📥 Baixando todos os leads...")

all_leads = []

for job in completed_jobs:
    if job.get('total_leads', 0) > 0:
        batch_id = job['batch_id']

        # Buscar leads desse batch
        response = requests.get(
            f"{API_BASE_URL}/api/leads",
            headers=headers,
            params={'batch_id': batch_id, 'limit': 1000}
        )

        if response.status_code == 200:
            data = response.json()
            leads = data.get('leads', [])
            all_leads.extend(leads)
            print(f"   {job['nicho']}: {len(leads)} leads baixados")

print()
print(f"✅ Total de leads baixados: {len(all_leads)}")
print()

# Filtrar apenas leads COM email
leads_com_email = [l for l in all_leads if l.get('email') and '@' in l.get('email', '')]

print(f"📧 Leads COM EMAIL: {len(leads_com_email)}")
print()

# Salvar
output_file = "grande_vitoria_leads_com_emails.json"
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(leads_com_email, f, ensure_ascii=False, indent=2)

print(f"✅ Arquivo salvo: {output_file}")
print()

# Estatísticas
if leads_com_email:
    with_phone = sum(1 for l in leads_com_email if l.get('phone'))
    with_website = sum(1 for l in leads_com_email if l.get('website'))

    print("📊 ESTATÍSTICAS:")
    print(f"   Total: {len(leads_com_email)}")
    print(f"   Com telefone: {with_phone}")
    print(f"   Com website: {with_website}")
    print()

    # Sample
    print("📋 SAMPLE (primeiros 5):")
    for i, lead in enumerate(leads_com_email[:5], 1):
        print(f"  {i}. {lead.get('company_name', 'Sem nome')}")
        print(f"     Email: {lead.get('email')}")
        print(f"     Telefone: {lead.get('phone', '(sem telefone)')}")
        print()

print("="*80)
print("✅ EXTRAÇÃO CONCLUÍDA!")
print("="*80)
print()
print("Próximo passo:")
print("  1. Verificar arquivo: grande_vitoria_leads_com_emails.json")
print("  2. Enriquecer nomes (caso necessário)")
print("  3. Importar para o CRM")
