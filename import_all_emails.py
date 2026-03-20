#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Importar TODOS os 31 leads com email (29 antigos + 2 novos)
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
print("IMPORTAÇÃO DE TODOS OS LEADS COM EMAIL")
print("="*80)
print()

# Carregar leads enriquecidos (com nomes derivados) + leads novos completos
print("📂 Carregando leads...")

with open('vitoria_leads_enriquecidos.json', 'r', encoding='utf-8') as f:
    leads_enriquecidos = json.load(f)

with open('vitoria_leads_com_emails.json', 'r', encoding='utf-8') as f:
    leads_novos = json.load(f)

print(f"✅ {len(leads_enriquecidos)} leads enriquecidos (nomes derivados do email)")
print(f"✅ {len(leads_novos)} leads novos completos")
print()

# Combinar todos os leads
all_leads = leads_enriquecidos + leads_novos

# Filtrar APENAS os que têm email
leads_com_email = []
for lead in all_leads:
    email = lead.get('email')
    emails = lead.get('emails', [])

    primeiro_email = email or (emails[0] if emails else None)

    if primeiro_email and '@' in str(primeiro_email):
        leads_com_email.append(lead)

print(f"📧 Total de leads COM EMAIL: {len(leads_com_email)}")
print()

# Transformar para formato CRM
customers = []
for lead in leads_com_email:
    # Email
    email = lead.get('email')
    emails = lead.get('emails', [])
    primeiro_email = email or (emails[0] if emails else "")

    # Nome
    nome = (
        lead.get('title') or
        lead.get('name') or
        lead.get('company_name') or
        lead.get('companyName') or
        "Lead sem nome"
    ).strip()

    # Telefone (pode ser vazio)
    phone = (lead.get('phone') or lead.get('phoneUnformatted') or "").strip()

    # Website
    website = (lead.get('website') or "").strip()

    # Endereço
    address = (lead.get('address') or lead.get('street') or "").strip()

    # Cidade/Estado
    city = (lead.get('city') or "").strip()
    state = (lead.get('state') or "").strip()

    # Categoria
    category = (lead.get('categoryName') or lead.get('category') or "").strip()

    # Rating
    rating = lead.get('rating') or lead.get('totalScore') or 0

    # Notas
    notes_parts = []
    if category:
        notes_parts.append(f"Categoria: {category}")
    if rating:
        notes_parts.append(f"Rating: {rating}/5")
    if address:
        notes_parts.append(f"Endereco: {address}")
    if website:
        notes_parts.append(f"Website: {website}")

    notes = " | ".join(notes_parts)

    customer = {
        "name": nome[:100],
        "email": primeiro_email[:100],
        "phone": phone[:50] if phone else "",  # Pode ser vazio
        "whatsApp": phone[:50] if phone else "",  # Pode ser vazio
        "companyName": nome[:100],
        "notes": notes[:500] if notes else "",
        "tags": "google-maps,apify,vitoria-es,com-email",
    }

    customers.append(customer)

print(f"✅ {len(customers)} leads transformados")
print()

# Sample
print("📋 SAMPLE (primeiros 5 com email):")
for i, c in enumerate(customers[:5], 1):
    print(f"  {i}. {c['name']}")
    print(f"     Email: {c['email']}")
    print(f"     Telefone: {c['phone'] or '(sem telefone)'}")
    print()

# Importar
print("📤 Importando para o CRM...")
payload = {
    "customers": customers,
    "source": 11,  # LeadSource.GoogleMaps
}

response = requests.post(
    f"{API_BASE_URL}/api/v1/customers/import",
    json=payload,
    headers={"Content-Type": "application/json"}
)

print()
if response.status_code == 200:
    result = response.json()
    print("="*80)
    print("✅ IMPORTAÇÃO CONCLUÍDA!")
    print("="*80)
    print(f"📊 Total enviado: {len(customers)}")
    print(f"✅ Importados: {result.get('imported', 0)}")
    print(f"⚠️  Duplicados: {result.get('duplicates', 0)}")
    print(f"❌ Erros: {result.get('errors', 0)}")
    print("="*80)
    print()
    print(f"🔗 Acesse: https://crm.alexandrequeiroz.com.br")
else:
    print(f"❌ Erro: {response.status_code}")
    print(response.text)
    print()
    print("Tentando verificar se o endpoint está correto...")
    print(f"URL usada: {API_BASE_URL}/api/v1/customers/import")
