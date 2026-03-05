#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para importar leads da Apify na aplicação local
"""

import sys
import io
import json
import requests

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Configurações
API_URL = "https://api.extratordedados.com.br/api"  # Backend na VPS
JSON_FILE = "apify_leads.json"

def login():
    """Faz login e retorna o token"""
    print("🔐 Fazendo login...")

    # Credenciais fornecidas
    username = "admin"
    password = "1982Xandeq1982#"

    response = requests.post(f"{API_URL}/login", json={
        "username": username,
        "password": password
    })

    if response.status_code == 200:
        token = response.json().get("token")
        print(f"✅ Login bem-sucedido! Token: {token[:20]}...")
        return token
    else:
        print(f"❌ Erro no login: {response.status_code}")
        print(response.text)
        return None

def transform_apify_to_leads(apify_data):
    """Transforma dados da Apify para o formato da aplicação"""
    leads = []

    for item in apify_data:
        # Pegar primeiro email (se existir)
        email = None
        if item.get("scraped_emails") and len(item["scraped_emails"]) > 0:
            email = item["scraped_emails"][0]["email"]

        # Pegar telefone (prioriza do Google Maps)
        phone = item.get("phone")
        if not phone and item.get("scraped_phones"):
            phone = item["scraped_phones"][0]

        # Extrair redes sociais
        instagram = None
        facebook = None
        linkedin = None
        twitter = None

        for social in item.get("scraped_social_media", []):
            platform = social.get("platform", "").lower()
            url = social.get("url", "")

            if "instagram" in platform:
                instagram = url
            elif "facebook" in platform:
                facebook = url
            elif "linkedin" in platform:
                linkedin = url
            elif "twitter" in platform or "x.com" in url:
                twitter = url

        # Criar lead (formato simplificado para a API)
        lead = {
            "company_name": item.get("name"),
            "email": email,
            "phone": phone,
            "website": item.get("website"),
            "whatsapp": phone,  # Usar o mesmo phone como WhatsApp
            "contact_name": ""  # Não temos nome de contato
        }

        # Só adicionar se tiver email OU telefone
        if email or phone:
            leads.append(lead)

    return leads

def import_leads(token, leads):
    """Importa leads usando a API"""
    print(f"\n📥 Importando {len(leads)} leads...")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # A API espera "contacts" e "batch_name"
    response = requests.post(
        f"{API_URL}/leads/import",
        headers=headers,
        json={
            "contacts": leads,
            "batch_name": "Importação Apify - Google Maps"
        }
    )

    if response.status_code == 200:
        result = response.json()
        print(f"\n✅ Importação concluída!")
        print(f"   📊 Total enviado: {result.get('total', 0)}")
        print(f"   ✅ Importados: {result.get('imported', 0)}")
        print(f"   ⚠️  Duplicados: {result.get('duplicates', 0)}")
        print(f"   ❌ Erros: {result.get('errors', 0)}")
        return True
    else:
        print(f"❌ Erro na importação: {response.status_code}")
        print(response.text)
        return False

def main():
    print("="*60)
    print("🚀 IMPORTAÇÃO DE LEADS DA APIFY")
    print("="*60)

    # 1. Login
    token = login()
    if not token:
        print("\n❌ Não foi possível fazer login. Verifique as credenciais.")
        return

    # 2. Carregar dados da Apify
    print(f"\n📂 Carregando dados de {JSON_FILE}...")
    try:
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            apify_data = json.load(f)
        print(f"✅ {len(apify_data)} leads carregados do arquivo")
    except FileNotFoundError:
        print(f"❌ Arquivo {JSON_FILE} não encontrado!")
        return
    except json.JSONDecodeError as e:
        print(f"❌ Erro ao ler JSON: {e}")
        return

    # 3. Transformar dados
    print("\n🔄 Transformando dados para o formato da aplicação...")
    leads = transform_apify_to_leads(apify_data)
    print(f"✅ {len(leads)} leads transformados")

    # Mostrar amostra
    if leads:
        print("\n📋 Amostra do primeiro lead:")
        sample = leads[0]
        print(f"   Empresa: {sample.get('company_name')}")
        print(f"   Email: {sample.get('email')}")
        print(f"   Telefone: {sample.get('phone')}")
        print(f"   Website: {sample.get('website')}")
        print(f"   Cidade: {sample.get('city')}, {sample.get('state')}")
        print(f"   Qualidade: {sample.get('quality_score')}/100")

    # 4. Importar
    success = import_leads(token, leads)

    if success:
        print("\n" + "="*60)
        print("🎉 IMPORTAÇÃO CONCLUÍDA COM SUCESSO!")
        print("="*60)
        print("\n💡 Acesse http://localhost:3000/leads para ver os leads importados")
    else:
        print("\n❌ Falha na importação")

if __name__ == "__main__":
    main()
