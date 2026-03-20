import os
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Importar leads COM EMAILS extraídos do Google Maps para o CRM
"""

import sys
import io
import json
import requests

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Config
API_BASE_URL = "https://api.alexandrequeiroz.com.br"
JSON_FILE = "vitoria_leads_com_emails.json"

print("="*80)
print("IMPORTAÇÃO DE LEADS COM EMAIL PARA O CRM")
print("="*80)
print()

# 1. Login
print("🔐 Fazendo login...")
response = requests.post(f"{API_BASE_URL}/api/v1/auth/login", json={
    "email": "admin",
    "password": os.environ.get("ADMIN_PASSWORD", "")
})

if response.status_code != 200:
    print(f"❌ Erro no login: {response.status_code}")
    print(response.text)
    sys.exit(1)

token = response.json().get("token")
print(f"✅ Login bem-sucedido!")
print()

# 2. Carregar leads
print(f"📂 Carregando leads de {JSON_FILE}...")
with open(JSON_FILE, "r", encoding="utf-8") as f:
    leads_data = json.load(f)

print(f"✅ {len(leads_data)} leads carregados")
print()

# 3. Filtrar só leads COM email
leads_com_email = [l for l in leads_data if l.get('emails') and len(l.get('emails', [])) > 0]
print(f"📧 Leads COM email: {len(leads_com_email)}")
print()

if not leads_com_email:
    print("❌ Nenhum lead com email encontrado!")
    sys.exit(0)

# 4. Transformar para formato do CRM
customers = []
for lead in leads_com_email:
    # Pegar primeiro email
    emails = lead.get('emails', [])
    primary_email = emails[0] if emails else ""

    # Nome da empresa
    company_name = lead.get('title', '').strip()

    # Telefone
    phone = lead.get('phone', '').strip()

    # Website
    website = lead.get('website', '').strip()

    # Endereço
    address = lead.get('address', '').strip()

    # Cidade/Estado
    city = lead.get('city', '').strip()
    state = lead.get('state', '').strip()

    # Categoria
    category = lead.get('categoryName', '').strip()

    # Rating
    rating = lead.get('totalScore', 0)

    # Notas
    notes_parts = []
    if category:
        notes_parts.append(f"Categoria: {category}")
    if rating:
        notes_parts.append(f"Rating: {rating}/5")
    if address:
        notes_parts.append(f"Endereço: {address}")
    if website:
        notes_parts.append(f"Website: {website}")

    notes = " | ".join(notes_parts)

    customer = {
        "name": company_name[:100],
        "email": primary_email[:100] if primary_email else "",
        "phone": phone[:50] if phone else "",
        "whatsApp": phone[:50] if phone else "",
        "companyName": company_name[:100],
        "notes": notes[:500],
        "tags": "google-maps,apify,vitoria-es,com-email",
    }

    customers.append(customer)

print(f"✅ {len(customers)} leads transformados para importação")
print()

# Mostrar amostra
if customers:
    print("📋 AMOSTRA:")
    for i, customer in enumerate(customers[:5], 1):
        print(f"  {i}. {customer['name']}")
        print(f"     📧 {customer['email']}")
        print(f"     📱 {customer['phone']}")
        print()

# 5. Importar
print("📤 Importando para o CRM...")
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

payload = {
    "customers": customers,
    "source": 11,  # LeadSource.GoogleMaps
}

response = requests.post(
    f"{API_BASE_URL}/api/v1/customers/import",
    headers=headers,
    json=payload
)

if response.status_code == 200:
    result = response.json()
    print()
    print("="*80)
    print("✅ IMPORTAÇÃO CONCLUÍDA COM SUCESSO!")
    print("="*80)
    print(f"📊 Total enviado: {len(customers)}")
    print(f"✅ Importados: {result.get('imported', 0)}")
    print(f"⚠️  Duplicados: {result.get('duplicates', 0)}")
    print(f"❌ Erros: {result.get('errors', 0)}")
    print("="*80)
    print()
    print(f"🔗 Acesse: {API_BASE_URL.replace('api.', 'crm.')}/leads")
else:
    print(f"❌ Erro na importação: {response.status_code}")
    print(response.text)
