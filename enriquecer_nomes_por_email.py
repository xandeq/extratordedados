#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enriquecer leads: derivar nome da empresa a partir do email
Estratégias:
1. Se email corporativo (domínio próprio): usar domínio como nome
2. Se Gmail/Outlook: usar prefixo antes do @
3. Normalizar: remover hífens, underscores, números
4. Capitalizar palavras
"""

import sys
import io
import json
import re

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Domínios genéricos (email pessoal)
GENERIC_DOMAINS = [
    'gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com', 'icloud.com',
    'live.com', 'msn.com', 'aol.com', 'protonmail.com', 'zoho.com'
]

def extrair_nome_de_email(email: str) -> str:
    """
    Extrai um nome inteligente a partir do email.
    """
    if not email or '@' not in email:
        return "Lead sem nome"

    # Separar prefixo e domínio
    prefixo, dominio = email.split('@', 1)

    # Limpar domínio (remover .com.br, .com, etc)
    dominio_limpo = dominio.replace('.com.br', '').replace('.com', '').replace('.net', '')
    dominio_limpo = dominio_limpo.replace('.org', '').replace('.adv.br', '').replace('.edu', '')

    # Se é email genérico (Gmail, Outlook), usar prefixo
    if any(generic in dominio.lower() for generic in GENERIC_DOMAINS):
        nome_base = prefixo
    else:
        # Email corporativo: usar domínio
        nome_base = dominio_limpo

    # Normalizar nome
    nome_normalizado = normalizar_nome(nome_base)

    return nome_normalizado


def normalizar_nome(texto: str) -> str:
    """
    Normaliza um texto para virar nome de empresa:
    - Remove underscores, hífens, pontos
    - Separa palavras compostas
    - Capitaliza corretamente
    - Remove números isolados
    """
    # Substituir separadores por espaços
    texto = texto.replace('_', ' ').replace('-', ' ').replace('.', ' ')

    # Remover números isolados
    texto = re.sub(r'\b\d+\b', '', texto)

    # Separar camelCase (ex: "odontoDreams" -> "odonto Dreams")
    texto = re.sub(r'([a-z])([A-Z])', r'\1 \2', texto)

    # Remover múltiplos espaços
    texto = re.sub(r'\s+', ' ', texto).strip()

    texto_lower = texto.lower()

    # Dicionário de padrões para separar palavras compostas
    # IMPORTANTE: Colocar palavras mais longas PRIMEIRO para evitar match parcial
    padroes = {
        'contabilidade': 'Contabilidade',  # ANTES de 'contabil'
        'imobiliaria': 'Imobiliária',      # ANTES de 'imoveis'
        'consultoria': 'Consultoria',
        'advocacia': 'Advocacia',
        'advogados': 'Advogados',
        'restaurante': 'Restaurante',
        'academia': 'Academia',
        'contabil': 'Contábil',
        'clinica': 'Clínica',
        'odonto': 'Odonto',
        'imoveis': 'Imóveis',
        'grupo': 'Grupo',
        'centro': 'Centro',
        'escola': 'Escola',
        'colegio': 'Colégio',
        'sky': 'Sky',
        'fit': 'Fit',
    }

    # Processar padrões do mais longo para o mais curto (evita match parcial)
    # Exemplo: "contabilidade" deve ser processado ANTES de "contabil"
    for chave, valor in padroes.items():
        if chave in texto_lower:
            # Substituir mantendo capitalização correta
            texto_lower = texto_lower.replace(chave, f'|{valor}|')

    # Separar por pipes
    partes = [p.strip() for p in texto_lower.split('|') if p.strip()]

    # Capitalizar partes que não foram identificadas
    partes_finais = []
    for parte in partes:
        if parte in padroes.values():
            # Já está capitalizado
            partes_finais.append(parte)
        else:
            # Capitalizar normalmente
            palavras = parte.split()
            minusculas = ['de', 'da', 'do', 'das', 'dos', 'e', 'ou', 'a', 'o']
            palavras_cap = []
            for i, pal in enumerate(palavras):
                if len(pal) <= 1:
                    continue
                if i > 0 and pal in minusculas:
                    palavras_cap.append(pal)
                else:
                    palavras_cap.append(pal.capitalize())
            partes_finais.append(' '.join(palavras_cap))

    nome_final = ' '.join(partes_finais).strip()

    # Se ficou vazio, retornar o original capitalizado
    if not nome_final:
        nome_final = texto.strip().capitalize()

    return nome_final


print("="*80)
print("ENRIQUECIMENTO DE LEADS - DERIVAR NOME A PARTIR DO EMAIL")
print("="*80)
print()

# Carregar leads antigos (os que não têm nome)
with open('vitoria_es_leads_final.json', 'r', encoding='utf-8') as f:
    leads_antigos = json.load(f)

# Filtrar leads com email mas sem nome
leads_sem_nome = []
for lead in leads_antigos:
    email = lead.get('email')
    emails = lead.get('emails', [])
    primeiro_email = email or (emails[0] if emails else None)

    nome = lead.get('title') or lead.get('name')

    if primeiro_email and '@' in str(primeiro_email) and not nome:
        leads_sem_nome.append(lead)

print(f"📊 Leads COM email mas SEM nome: {len(leads_sem_nome)}")
print()

# Enriquecer cada lead
leads_enriquecidos = []

for lead in leads_sem_nome:
    email = lead.get('email')
    emails = lead.get('emails', [])
    primeiro_email = email or (emails[0] if emails else None)

    # Derivar nome do email
    nome_derivado = extrair_nome_de_email(primeiro_email)

    # Criar lead enriquecido
    lead_enriquecido = lead.copy()
    lead_enriquecido['title'] = nome_derivado
    lead_enriquecido['derived_from_email'] = True

    leads_enriquecidos.append(lead_enriquecido)

print("✅ Leads enriquecidos!")
print()

# Mostrar sample
print("📋 SAMPLE - Nomes derivados:")
for i, lead in enumerate(leads_enriquecidos[:15], 1):
    email = lead.get('email') or lead.get('emails', [None])[0]
    nome = lead.get('title')
    print(f"{i}. Email: {email}")
    print(f"   Nome derivado: {nome}")
    print()

# Salvar leads enriquecidos
output_file = "vitoria_leads_enriquecidos.json"
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(leads_enriquecidos, f, ensure_ascii=False, indent=2)

print("="*80)
print("✅ ENRIQUECIMENTO CONCLUÍDO!")
print("="*80)
print(f"📁 Arquivo salvo: {output_file}")
print(f"📊 Total de leads enriquecidos: {len(leads_enriquecidos)}")
print()
print("Próximo passo: python import_all_emails.py (vai importar os 29 + 2 = 31 leads)")
print("="*80)
