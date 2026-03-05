#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contar total de leads com email em todos os arquivos
"""

import sys
import io
import json

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print('='*80)
print('RESUMO TOTAL DE LEADS COM EMAIL')
print('='*80)
print()

# Arquivo com os 2 leads recém-importados
with open('vitoria_leads_com_emails.json', 'r', encoding='utf-8') as f:
    leads_novos = json.load(f)

# Arquivo com os 160 leads anteriores
with open('vitoria_es_leads_final.json', 'r', encoding='utf-8') as f:
    leads_antigos = json.load(f)

# Contar emails nos leads novos
emails_novos = sum(1 for l in leads_novos if l.get('emails') and len(l.get('emails', [])) > 0)

# Contar emails nos leads antigos
emails_antigos = sum(1 for l in leads_antigos if l.get('email') or (l.get('emails') and len(l.get('emails', [])) > 0))

print(f'Leads antigos (vitoria_es_leads_final.json):')
print(f'  Total: {len(leads_antigos)}')
print(f'  Com email: {emails_antigos}')
print()
print(f'Leads novos (vitoria_leads_com_emails.json):')
print(f'  Total: {len(leads_novos)}')
print(f'  Com email: {emails_novos}')
print()
print('='*80)
print(f'TOTAL DE LEADS COM EMAIL: {emails_antigos + emails_novos}')
print('='*80)
print()

# Listar todos os emails encontrados
print('LISTA DE TODOS OS EMAILS:')
print()

all_emails = []

# Emails dos leads antigos
for lead in leads_antigos:
    if lead.get('email'):
        all_emails.append({
            'nome': lead.get('title', 'Sem nome'),
            'email': lead.get('email'),
            'telefone': lead.get('phone', ''),
            'origem': 'antigos'
        })
    elif lead.get('emails'):
        for email in lead.get('emails', []):
            all_emails.append({
                'nome': lead.get('title', 'Sem nome'),
                'email': email,
                'telefone': lead.get('phone', ''),
                'origem': 'antigos'
            })

# Emails dos leads novos
for lead in leads_novos:
    for email in lead.get('emails', []):
        all_emails.append({
            'nome': lead.get('title', 'Sem nome'),
            'email': email,
            'telefone': lead.get('phone', ''),
            'origem': 'novos'
        })

for i, item in enumerate(all_emails, 1):
    print(f'{i}. {item["nome"]}')
    print(f'   Email: {item["email"]}')
    print(f'   Telefone: {item["telefone"]}')
    print(f'   Origem: {item["origem"]}')
    print()

print('='*80)
print(f'TOTAL: {len(all_emails)} emails encontrados em todos os arquivos')
print('='*80)

# Emails únicos
emails_unicos = list(set(item['email'] for item in all_emails))
print()
print(f'Emails UNICOS (sem duplicatas): {len(emails_unicos)}')
