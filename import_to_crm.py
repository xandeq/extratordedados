#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Importar leads da Apify para o CRM Alexandre Queiroz
Endpoint: POST /api/v1/customers/import
Source: 11 (GoogleMaps)
"""

import sys
import io
import json
import requests

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# URL da API do CRM
API_BASE_URL = "https://api.alexandrequeiroz.com.br"

def map_apify_to_crm(apify_item: dict) -> dict:
    """Converte um item do Apify Google Maps para o formato do CRM."""
    name = (
        apify_item.get("title")
        or apify_item.get("name")
        or apify_item.get("company_name")
        or apify_item.get("companyName")
        or "Sem nome"
    )

    email = (
        apify_item.get("email")
        or (apify_item.get("emails", [None])[0] if apify_item.get("emails") else None)
        or ""
    )

    phone = (
        apify_item.get("phone")
        or apify_item.get("phoneUnformatted")
        or ""
    )

    website = apify_item.get("website") or ""
    address = apify_item.get("address") or apify_item.get("street") or ""
    category = apify_item.get("categoryName") or apify_item.get("category") or ""
    city = apify_item.get("city") or ""
    state = apify_item.get("state") or ""
    rating = apify_item.get("rating") or apify_item.get("totalScore") or None

    # Criar notes com informações úteis
    notes_parts = []
    if website:
        notes_parts.append(f"Website: {website}")
    if address:
        notes_parts.append(f"Endereco: {address}")
    if category:
        notes_parts.append(f"Categoria: {category}")
    if city and state:
        notes_parts.append(f"Localizacao: {city}, {state}")
    if rating:
        notes_parts.append(f"Avaliacao: {rating}/5")

    return {
        "name": name[:100],  # Limite de segurança
        "email": email[:100] if email else "",
        "phone": phone[:50] if phone else "",
        "whatsApp": phone[:50] if phone else "",
        "companyName": name[:100],
        "notes": " | ".join(notes_parts)[:500],  # Limite de segurança
        "tags": "google-maps,apify,grande-vitoria-es",
    }


def import_leads_to_crm(apify_results: list) -> dict:
    """Importa uma lista de resultados do Apify para o CRM."""

    print(f"Transformando {len(apify_results)} leads para o formato do CRM...")
    customers = [map_apify_to_crm(item) for item in apify_results]

    # Remover leads sem nome válido
    customers = [c for c in customers if c["name"] and c["name"] != "Sem nome"]

    print(f"✅ {len(customers)} leads válidos após filtro")
    print()

    payload = {
        "customers": customers,
        "source": 11,  # LeadSource.GoogleMaps
    }

    print(f"📤 Enviando para {API_BASE_URL}/api/v1/customers/import...")
    print(f"   Source: 11 (GoogleMaps)")
    print(f"   Total: {len(customers)} leads")
    print()

    response = requests.post(
        f"{API_BASE_URL}/api/v1/customers/import",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        },
        timeout=120,
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"❌ Erro HTTP {response.status_code}")
        print(response.text)
        response.raise_for_status()


def main():
    print("="*80)
    print("🚀 IMPORTAÇÃO PARA CRM ALEXANDRE QUEIROZ")
    print("="*80)
    print()

    # Carregar leads do arquivo JSON
    input_file = "vitoria_leads_com_emails.json"

    print(f"📂 Carregando leads de {input_file}...")
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            apify_results = json.load(f)
        print(f"✅ {len(apify_results)} leads carregados")
    except FileNotFoundError:
        print(f"❌ Arquivo {input_file} não encontrado!")
        return
    except json.JSONDecodeError as e:
        print(f"❌ Erro ao ler JSON: {e}")
        return

    print()

    # Filtrar leads com EMAIL ou telefone
    leads_validos = [
        l for l in apify_results
        if l.get('phone') or l.get('email') or (l.get('emails') and len(l.get('emails', [])) > 0)
    ]
    leads_com_email = [
        l for l in leads_validos
        if l.get('email') or (l.get('emails') and len(l.get('emails', [])) > 0)
    ]

    print(f"📊 Leads válidos: {len(leads_validos)}/{len(apify_results)}")
    print(f"   📧 Com EMAIL: {len(leads_com_email)}")
    print(f"   📱 Com telefone: {sum(1 for l in leads_validos if l.get('phone'))}")
    print()

    if not leads_validos:
        print("⚠️  Nenhum lead válido encontrado. Importação cancelada.")
        return

    # Mostrar preview
    if leads_validos:
        print("📋 Preview do primeiro lead:")
        sample = leads_validos[0]
        print(f"   Nome: {sample.get('title')}")
        print(f"   Telefone: {sample.get('phone')}")
        print(f"   Website: {sample.get('website')}")
        print(f"   Cidade: {sample.get('city')}, {sample.get('state')}")
        print(f"   Categoria: {sample.get('categoryName')}")
        print()

    # Importar
    try:
        result = import_leads_to_crm(leads_validos)

        print("="*80)
        print("✅ IMPORTAÇÃO CONCLUÍDA!")
        print("="*80)
        print(f"Total de registros: {result.get('totalRecords', 0)}")
        print(f"✅ Importados com sucesso: {result.get('successCount', 0)}")
        print(f"❌ Falharam: {result.get('failedCount', 0)}")
        print()

        if result.get('failedCount', 0) > 0 and result.get('errors'):
            print("⚠️  Erros:")
            for error in result.get('errors', [])[:10]:  # Mostrar no máximo 10
                print(f"   - Linha {error.get('rowNumber')}: {error.get('errorMessage')}")
            if len(result.get('errors', [])) > 10:
                print(f"   ... e mais {len(result['errors']) - 10} erros")

        print()
        print("🔗 Acesse: https://crm.alexandrequeiroz.com.br")
        print("="*80)

        return result

    except requests.exceptions.RequestException as e:
        print(f"❌ Erro na requisição: {e}")
        return None


if __name__ == "__main__":
    main()
