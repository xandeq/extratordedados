import os
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Debug do erro 409 no update
"""

import sys
import io
import requests

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_BASE_URL = "https://api.alexandrequeiroz.com.br"

# Login
response = requests.post(f"{API_BASE_URL}/api/v1/auth/login", json={
    "email": "admin@alexandrequeiroz.com.br",
    "password": os.environ.get("ADMIN_PASSWORD", "")
})

token = response.json().get('token')
headers = {'Authorization': f'Bearer {token}'}

# Buscar o lead "Home" (contato@bateleur.com.br)
response = requests.get(
    f"{API_BASE_URL}/api/v1/leads",
    headers=headers,
    params={'pageSize': 100}
)

data = response.json()
leads = data if isinstance(data, list) else data.get('data', data.get('items', []))

# Encontrar o lead Home
lead_home = None
for lead in leads:
    if lead.get('email') == 'contato@bateleur.com.br':
        lead_home = lead
        break

if not lead_home:
    print("❌ Lead não encontrado")
    sys.exit(1)

print("Lead encontrado:")
print(f"  ID: {lead_home.get('id')}")
print(f"  Name: {lead_home.get('name')}")
print(f"  CompanyName: {lead_home.get('companyName')}")
print(f"  Email: {lead_home.get('email')}")
print()

# Tentar atualizar
print("Tentando atualizar para 'Bateleur'...")
response = requests.put(
    f"{API_BASE_URL}/api/v1/customers/{lead_home.get('id')}",
    headers=headers,
    json={
        'name': 'Bateleur',
        'companyName': 'Bateleur'
    }
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
