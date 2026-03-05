#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Atualizar nomes (company_name) dos leads no CRM usando o endpoint PUT /api/leads/<id>
"""

import sys
import io
import json
import requests

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_BASE_URL = "https://api.extratordedados.com.br"

print("="*80)
print("ATUALIZAÇÃO DE NOMES NO CRM")
print("="*80)
print()

# Carregar leads enriquecidos (com nomes derivados)
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

# Login no CRM
print("🔐 Fazendo login...")
response = requests.post(f"{API_BASE_URL}/api/login", json={
    "username": "admin",
    "password": "1982Xandeq1982#"
})

if response.status_code != 200:
    print(f"❌ Erro no login: {response.status_code}")
    print(response.text)
    sys.exit(1)

token = response.json().get('token')
print("✅ Login bem-sucedido!")
print()

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

# Buscar TODOS os leads do CRM (paginação)
print("📥 Buscando leads no CRM...")
all_crm_leads = []
page = 1
limit = 100

while True:
    response = requests.get(
        f"{API_BASE_URL}/api/leads",
        headers=headers,
        params={'page': page, 'limit': limit}
    )

    if response.status_code != 200:
        print(f"❌ Erro ao buscar leads: {response.status_code}")
        break

    data = response.json()
    leads_page = data.get('leads', [])

    if not leads_page:
        break

    all_crm_leads.extend(leads_page)
    print(f"   Página {page}: {len(leads_page)} leads")

    # Se retornou menos que o limit, é a última página
    if len(leads_page) < limit:
        break

    page += 1

print(f"✅ Total de leads no CRM: {len(all_crm_leads)}")
print()

# Filtrar leads que TÊM email e que estão no nosso mapa
leads_para_atualizar = []
for crm_lead in all_crm_leads:
    email = crm_lead.get('email', '').strip().lower()
    if email and email in email_to_name:
        # Verificar se o nome derivado é diferente do atual
        nome_atual = crm_lead.get('company_name', '').strip()
        nome_novo = email_to_name[email]

        if nome_novo and nome_novo != nome_atual:
            leads_para_atualizar.append({
                'id': crm_lead['id'],
                'email': email,
                'nome_atual': nome_atual,
                'nome_novo': nome_novo
            })

print(f"📊 Leads que precisam de atualização: {len(leads_para_atualizar)}")
print()

if not leads_para_atualizar:
    print("✅ Todos os leads já estão com os nomes corretos!")
    sys.exit(0)

# Mostrar sample
print("📋 SAMPLE - Atualizações a fazer:")
for i, lead in enumerate(leads_para_atualizar[:10], 1):
    print(f"  {i}. ID: {lead['id']}")
    print(f"     Email: {lead['email']}")
    print(f"     Nome atual: '{lead['nome_atual']}'")
    print(f"     Nome novo: '{lead['nome_novo']}'")
    print()

if len(leads_para_atualizar) > 10:
    print(f"... e mais {len(leads_para_atualizar) - 10} leads")
    print()

# Confirmar
print("="*80)
input(f"Pressione ENTER para atualizar {len(leads_para_atualizar)} leads... (Ctrl+C para cancelar)")
print()

# Atualizar cada lead
print("📤 Atualizando leads...")
atualizados = 0
erros = 0

for i, lead in enumerate(leads_para_atualizar, 1):
    response = requests.put(
        f"{API_BASE_URL}/api/leads/{lead['id']}",
        headers=headers,
        json={'company_name': lead['nome_novo']}
    )

    if response.status_code == 200:
        atualizados += 1
        if i % 10 == 0:
            print(f"   {i}/{len(leads_para_atualizar)} atualizados...")
    else:
        erros += 1
        print(f"   ❌ Erro ao atualizar lead {lead['id']}: {response.status_code}")

print()
print("="*80)
print("✅ ATUALIZAÇÃO CONCLUÍDA!")
print("="*80)
print(f"✅ Atualizados: {atualizados}")
print(f"❌ Erros: {erros}")
print("="*80)
print()
print(f"🔗 Acesse: https://extratordedados.com.br/leads")
print()
print("Exemplos de nomes atualizados:")
for lead in leads_para_atualizar[:5]:
    print(f"  - {lead['email']} -> '{lead['nome_novo']}'")
