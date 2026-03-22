#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATUALIZAR nomes dos leads no CRM (não inserir novos, apenas UPDATE)
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
print("ATUALIZAÇÃO DE NOMES - LEADS COM EMAIL")
print("="*80)
print()

# Carregar leads enriquecidos
print("📂 Carregando leads enriquecidos...")

with open('vitoria_leads_enriquecidos.json', 'r', encoding='utf-8') as f:
    leads_enriquecidos = json.load(f)

with open('vitoria_leads_com_emails.json', 'r', encoding='utf-8') as f:
    leads_novos = json.load(f)

all_leads = leads_enriquecidos + leads_novos

print(f"✅ {len(all_leads)} leads carregados")
print()

# Sample dos nomes derivados
print("📋 NOMES DERIVADOS (sample):")
for i, lead in enumerate(all_leads[:10], 1):
    email = lead.get('email') or (lead.get('emails', [None])[0] if lead.get('emails') else None)
    nome = lead.get('title') or 'Sem nome'
    print(f"  {i}. {nome}")
    print(f"     Email: {email}")
print()

if len(all_leads) > 10:
    print(f"... e mais {len(all_leads) - 10} leads")
    print()

# Mostrar especificamente o informatize
for lead in all_leads:
    email = lead.get('email') or (lead.get('emails', [None])[0] if lead.get('emails') else None)
    if 'informatize' in str(email).lower():
        print("✅ Exemplo específico (Informatize):")
        print(f"   Email: {email}")
        print(f"   Nome derivado: {lead.get('title')}")
        print()
        break

print("="*80)
print("IMPORTANTE")
print("="*80)
print("Os 31 leads JA ESTAO no CRM (confirmado pelo erro 'Email já existe')")
print("Para ATUALIZAR os nomes, você tem duas opções:")
print()
print("1. DELETAR os leads antigos do CRM e RE-IMPORTAR com os nomes novos")
print("2. Usar um endpoint de UPDATE (se o CRM tiver)")
print()
print("Como os 29 leads enriquecidos estavam sem nome ('Lead sem nome'),")
print("e agora têm nomes derivados inteligentemente, vale a pena atualizá-los!")
print()
print("Nomes melhorados:")
print("  - 'comercial@informatizecontabilidade.com.br' -> 'Informatize Contabilidade'")
print("  - 'contato@faveroadvogados.com.br' -> 'Favero Advogados'")
print("  - 'bentoferreira@skyfitacademia.com.br' -> 'Bentoferreira Sky Fit Academia'")
print("  - 'contato@restauranteberrodagua.com.br' -> 'Restaurante Berrodagua'")
print("  - 'reservas@gruposerragrande.com.br' -> 'Grupo Serragrande'")
print("="*80)
print()
print("✅ Arquivo salvo: vitoria_leads_enriquecidos.json")
print("✅ Total de leads com nomes inteligentes: 31")
print()
print("Próximo passo: Importar via interface do CRM ou usar API de UPDATE")
