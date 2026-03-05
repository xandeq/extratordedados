#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CORREÇÃO DO MERGE - Normaliza URLs antes de comparar
"""

import sys
import io
import json
from urllib.parse import urlparse

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def normalize_url(url):
    """
    Normaliza URL para comparação:
    - Remove http/https
    - Remove www.
    - Remove trailing slash
    - Remove paths
    - Lowercase
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]

        # Remove www.
        domain = domain.replace('www.', '')

        # Lowercase
        domain = domain.lower().strip()

        return domain
    except:
        return url.lower().strip()

print("="*80)
print("MERGE CORRIGIDO - EMAILS + GOOGLE MAPS DATA")
print("="*80)
print()

# 1. Carregar leads originais do Google Maps
print("📂 Carregando leads do Google Maps...")
with open("vitoria_es_leads_final.json", "r", encoding="utf-8") as f:
    leads = json.load(f)

leads_com_website = [l for l in leads if l.get('website')]
print(f"   Total de leads: {len(leads)}")
print(f"   Com website: {len(leads_com_website)}")
print()

# 2. Carregar resultados da extração de emails
print("📂 Carregando emails extraídos...")

# Tentar carregar do arquivo que o último script deveria ter salvo
try:
    with open("email_extraction_results.json", "r", encoding="utf-8") as f:
        email_results = json.load(f)
    print(f"   ✅ {len(email_results)} resultados carregados")
except FileNotFoundError:
    print("   ⚠️  Arquivo email_extraction_results.json não encontrado")
    print("   Tentando extrair emails novamente da última run da Apify...")
    from apify_client import ApifyClient

    client = ApifyClient("apify_api_dOvao4PhSMHPSNSIaUIarXpW1N736q2e3QDm")

    # Pegar última run (você pode substituir pelo dataset_id específico se souber)
    print("   Checando últimas runs...")
    email_results = []
    # Este é um placeholder - você precisaria do dataset_id correto
    print("   ❌ Dataset ID necessário. Execute extract_emails_from_websites.py primeiro.")
    sys.exit(1)

print()

# 3. Criar mapeamento normalizado: domain -> emails
print("🔧 Criando mapeamento de domínios -> emails...")
domain_emails = {}

for item in email_results:
    url = item.get('url')
    emails = item.get('emails', [])

    if url and emails:
        normalized = normalize_url(url)
        if normalized:
            domain_emails[normalized] = emails

print(f"   Domínios mapeados: {len(domain_emails)}")
print()

# Mostrar sample do mapeamento
print("📋 Sample do mapeamento:")
sample_domains = list(domain_emails.items())[:5]
for domain, emails in sample_domains:
    print(f"   {domain} -> {emails}")
print()

# 4. Fazer merge com normalização
print("🔀 Fazendo merge com normalização de URLs...")
leads_enriquecidos = []

for lead in leads_com_website:
    website = lead.get('website')
    normalized = normalize_url(website)

    emails = domain_emails.get(normalized, [])

    if emails:
        lead_enriquecido = lead.copy()
        lead_enriquecido['extracted_emails'] = emails
        lead_enriquecido['primary_email'] = emails[0] if emails else None
        leads_enriquecidos.append(lead_enriquecido)

print(f"   ✅ Leads enriquecidos com email: {len(leads_enriquecidos)}")
print()

# 5. Salvar
output_file = "vitoria_leads_COM_EMAILS_FINAL.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(leads_enriquecidos, f, ensure_ascii=False, indent=2)

print(f"✅ Arquivo salvo: {output_file}")
print()

# 6. Estatísticas
if leads_enriquecidos:
    print("📊 ESTATÍSTICAS:")
    print(f"   Total de leads com email: {len(leads_enriquecidos)}")

    # Contar emails únicos
    all_emails = []
    for lead in leads_enriquecidos:
        all_emails.extend(lead.get('extracted_emails', []))

    unique_emails = list(set(all_emails))
    print(f"   Emails únicos encontrados: {len(unique_emails)}")
    print(f"   Taxa de emails/websites: {len(leads_enriquecidos)/len(leads_com_website)*100:.1f}%")
    print()

    # Sample
    print("📋 SAMPLE - Primeiros 10 leads com email:")
    for i, lead in enumerate(leads_enriquecidos[:10], 1):
        print(f"   {i}. {lead.get('title')}")
        print(f"      📧 Email: {lead.get('primary_email')}")
        print(f"      📱 Telefone: {lead.get('phone')}")
        print(f"      🌐 Website: {lead.get('website')}")
        print(f"      📍 {lead.get('city')}, {lead.get('state')}")
        print()

print("="*80)
print("✅ MERGE CONCLUÍDO!")
print("="*80)
print(f"Arquivo: {output_file}")
print(f"Total: {len(leads_enriquecidos)} leads com email")
print("="*80)
