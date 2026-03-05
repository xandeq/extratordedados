#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Atualizar nomes dos leads no CRM alexandrequeiroz.com.br
Endpoint: PUT /api/v1/customers/{id}
"""

import sys
import io
import json
import requests

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_BASE_URL = "https://api.alexandrequeiroz.com.br"

print("="*80)
print("ATUALIZAÇÃO DE NOMES - CRM")
print("="*80)
print()

# Carregar leads enriquecidos
print("📂 Carregando leads enriquecidos...")

with open('vitoria_leads_enriquecidos.json', 'r', encoding='utf-8') as f:
    leads_enriquecidos = json.load(f)

with open('vitoria_leads_com_emails.json', 'r', encoding='utf-8') as f:
    leads_novos = json.load(f)

all_leads = leads_enriquecidos + leads_novos

# Criar mapa: email -> nome derivado
email_to_name = {}
for lead in all_leads:
    email = lead.get('email') or (lead.get('emails', [None])[0] if lead.get('emails') else None)
    nome = lead.get('title') or 'Sem nome'
    if email and '@' in email:
        email_to_name[email.lower()] = nome

print(f"✅ {len(email_to_name)} emails com nomes derivados")
print()

# Mostrar sample dos nomes
print("📋 Sample de nomes derivados:")
for i, (email, nome) in enumerate(list(email_to_name.items())[:5], 1):
    print(f"  {i}. {email} -> '{nome}'")
print()

# Login
print("🔐 Fazendo login como admin@alexandrequeiroz.com.br...")
response = requests.post(f"{API_BASE_URL}/api/v1/auth/login", json={
    "email": "admin@alexandrequeiroz.com.br",
    "password": "1982Xandeq1982#"
})

if response.status_code != 200:
    print(f"❌ Erro no login: {response.status_code}")
    print(response.text)
    sys.exit(1)

token = response.json().get('token')
print("✅ Login OK!")
print()

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

# Buscar leads
print("📥 Buscando leads no CRM...")
response = requests.get(
    f"{API_BASE_URL}/api/v1/leads",
    headers=headers,
    params={'page': 1, 'pageSize': 200}
)

if response.status_code != 200:
    print(f"❌ Erro: {response.status_code}")
    print(response.text[:500])
    sys.exit(1)

data = response.json()

# Tentar diferentes formatos de resposta
if isinstance(data, list):
    all_crm_leads = data
elif 'data' in data:
    all_crm_leads = data['data']
elif 'items' in data:
    all_crm_leads = data['items']
else:
    print(f"Formato: {list(data.keys())}")
    all_crm_leads = []

print(f"✅ {len(all_crm_leads)} leads encontrados")
print()

# Filtrar os que precisam atualização
leads_para_atualizar = []

for crm_lead in all_crm_leads:
    email = (crm_lead.get('email') or '').strip().lower()
    nome_atual = (crm_lead.get('name') or crm_lead.get('companyName') or '').strip()

    if email and email in email_to_name:
        nome_novo = email_to_name[email]
        if 'Lead sem nome' in nome_atual or (nome_novo and nome_novo != nome_atual):
            leads_para_atualizar.append({
                'id': crm_lead['id'],
                'email': email,
                'nome_atual': nome_atual,
                'nome_novo': nome_novo,
                'data': crm_lead
            })

print(f"📊 Leads para atualizar: {len(leads_para_atualizar)}")
print()

if not leads_para_atualizar:
    print("✅ Todos OK!")
    sys.exit(0)

# Mostrar
for i, lead in enumerate(leads_para_atualizar[:10], 1):
    print(f"{i}. {lead['email']}")
    print(f"   '{lead['nome_atual']}' -> '{lead['nome_novo']}'")
print()

if len(leads_para_atualizar) > 10:
    print(f"... e mais {len(leads_para_atualizar) - 10} leads")
    print()

input("ENTER para atualizar...")

# Atualizar
print()
print("📤 Atualizando leads...")
atualizados = 0
erros = 0

for i, lead in enumerate(leads_para_atualizar, 1):
    body = {
        "name": lead['nome_novo'],
        "email": lead['data'].get('email'),
        "personType": lead['data'].get('personType', 0),
        "companyName": lead['nome_novo'],
        "document": lead['data'].get('document'),
        "phone": lead['data'].get('phone'),
        "whatsApp": lead['data'].get('whatsApp'),
        "secondaryEmail": lead['data'].get('secondaryEmail'),
        "website": lead['data'].get('website'),
        "source": lead['data'].get('source', 11),
        "sourceDetails": lead['data'].get('sourceDetails'),
        "notes": lead['data'].get('notes'),
        "tags": lead['data'].get('tags')
    }

    response = requests.put(
        f"{API_BASE_URL}/api/v1/customers/{lead['id']}",
        headers=headers,
        json=body
    )

    if response.status_code in [200, 204]:
        atualizados += 1
        if i % 5 == 0:
            print(f"   ✅ {i}/{len(leads_para_atualizar)}")
    else:
        erros += 1
        print(f"   ❌ {lead['email']}: {response.status_code}")

print()
print("="*80)
print("✅ ATUALIZAÇÃO CONCLUÍDA!")
print("="*80)
print(f"✅ Atualizados: {atualizados}/{len(leads_para_atualizar)}")
print(f"❌ Erros: {erros}")
print("="*80)
print()
print("🔗 Acesse: https://crm.alexandrequeiroz.com.br/leads")
print()
print("✅ Exemplos de nomes atualizados:")
for lead in leads_para_atualizar[:5]:
    print(f"  - {lead['email']}")
    print(f"    '{lead['nome_atual']}' -> '{lead['nome_novo']}'")
