#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aplicar algoritmo SUPER INTELIGENTE para atualizar TODOS os leads no CRM
que têm nomes mal derivados (Home, Cristinamilanez, Cabanadoluiz, etc.)
"""

import sys
import io
import json
import requests
import re

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_BASE_URL = "https://api.alexandrequeiroz.com.br"

# ============================================================
# ALGORITMO SUPER INTELIGENTE DE DERIVAÇÃO DE NOMES
# ============================================================

# Nomes próprios comuns no Brasil
NOMES_PROPRIOS = [
    'alexandre', 'cristina', 'cristiane', 'fernanda', 'fernando', 'gabriela', 'gabriel',
    'joao', 'jose', 'julia', 'juliana', 'lucas', 'luiz', 'luis', 'marcelo', 'marcela',
    'marcia', 'maria', 'marina', 'mario', 'mateus', 'miguel', 'natalia', 'paulo', 'paula',
    'pedro', 'rafael', 'renato', 'renata', 'ricardo', 'roberto', 'rodrigo', 'sergio',
    'thiago', 'tiago', 'vitor', 'vitoria', 'viviane', 'carlos', 'carla', 'ana', 'andre',
    'antonio', 'bruno', 'camila', 'daniel', 'daniela', 'diego', 'eduardo', 'fabio', 'felipe',
    'livia', 'marly', 'bento', 'lagemann', 'favero'
]

# Sobrenomes comuns
SOBRENOMES = [
    'silva', 'santos', 'oliveira', 'souza', 'rodrigues', 'ferreira', 'alves', 'pereira',
    'lima', 'gomes', 'costa', 'ribeiro', 'martins', 'carvalho', 'almeida', 'lopes',
    'soares', 'fernandes', 'vieira', 'barbosa', 'rocha', 'dias', 'nascimento', 'castro',
    'araujo', 'cunha', 'pinto', 'teixeira', 'correia', 'cavalcanti', 'monteiro', 'moreira',
    'mendes', 'barros', 'freitas', 'cardoso', 'melo', 'campos', 'reis', 'miranda', 'pires',
    'farias', 'brito', 'sales', 'azevedo', 'coelho', 'nunes', 'moura', 'ramos', 'milanez',
    'milan', 'milanes', 'machado', 'lagemann', 'favero'
]

# Palavras de negócio
PALAVRAS_NEGOCIO = {
    'contabilidade': 'Contabilidade',
    'advocacia': 'Advocacia',
    'advogados': 'Advogados',
    'consultoria': 'Consultoria',
    'clinica': 'Clínica',
    'imoveis': 'Imóveis',
    'imobiliaria': 'Imobiliária',
    'restaurante': 'Restaurante',
    'academia': 'Academia',
    'escola': 'Escola',
    'colegio': 'Colégio',
    'cabana': 'Cabana',
    'casa': 'Casa',
    'grupo': 'Grupo',
    'centro': 'Centro',
    'hotel': 'Hotel',
    'pousada': 'Pousada',
    'informatize': 'Informatize',
    'bateleur': 'Bateleur',
    'skyfit': 'Skyfit',
    'altus': 'Altus',
    'formalize': 'Formalize',
    'linear': 'Linear'
}

# Prefixos genéricos a serem ignorados
PREFIXOS_GENERICOS = ['contato', 'atendimento', 'info', 'comercial', 'vendas', 'suporte', 'faleconosco', 'admin', 'orders', 'hello', 'bonjour', 'donuts']

# Domínios genéricos (email pessoal)
DOMINIOS_GENERICOS = ['gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com', 'live.com', 'msn.com']


def separar_palavras_compostas(texto):
    """
    Separa palavras compostas usando:
    1. Detecção de nomes próprios
    2. Palavras de negócio conhecidas
    3. CamelCase
    4. Heurísticas de separação
    """
    texto = texto.lower().strip()

    # Remove números isolados
    texto = re.sub(r'\d+', '', texto)

    # Separar camelCase
    texto = re.sub(r'([a-z])([A-Z])', r'\1 \2', texto)

    palavras_encontradas = []
    posicao = 0

    while posicao < len(texto):
        melhor_match = None
        melhor_tamanho = 0

        # Tentar match com palavras de negócio (mais longas primeiro)
        for palavra_chave in sorted(PALAVRAS_NEGOCIO.keys(), key=len, reverse=True):
            if texto[posicao:].startswith(palavra_chave):
                if len(palavra_chave) > melhor_tamanho:
                    melhor_match = PALAVRAS_NEGOCIO[palavra_chave]
                    melhor_tamanho = len(palavra_chave)

        # Tentar match com nomes próprios
        if not melhor_match:
            for nome in sorted(NOMES_PROPRIOS + SOBRENOMES, key=len, reverse=True):
                if texto[posicao:].startswith(nome):
                    if len(nome) > melhor_tamanho:
                        melhor_match = nome.capitalize()
                        melhor_tamanho = len(nome)

        if melhor_match:
            palavras_encontradas.append(melhor_match)
            posicao += melhor_tamanho
        else:
            # Avançar um caractere
            posicao += 1

    if palavras_encontradas:
        return ' '.join(palavras_encontradas)

    # Fallback: capitalizar o texto original
    return texto.capitalize()


def extrair_nome_de_email(email: str) -> str:
    """
    Extrai um nome inteligente a partir do email.
    """
    if not email or '@' not in email:
        return "Lead sem nome"

    # Separar prefixo e domínio
    prefixo, dominio = email.split('@', 1)
    prefixo = prefixo.lower().strip()

    # Limpar domínio
    dominio_limpo = dominio.replace('.com.br', '').replace('.com', '').replace('.net', '')
    dominio_limpo = dominio_limpo.replace('.org', '').replace('.adv.br', '').replace('.edu', '')

    # Se prefixo é genérico (contato, atendimento, etc), usar domínio
    if prefixo in PREFIXOS_GENERICOS:
        nome_base = dominio_limpo
    # Se é email pessoal (Gmail, Outlook), usar prefixo
    elif any(generic in dominio.lower() for generic in DOMINIOS_GENERICOS):
        nome_base = prefixo
    # Caso contrário, usar domínio (email corporativo)
    else:
        nome_base = dominio_limpo

    # Separar palavras compostas com inteligência
    nome_final = separar_palavras_compostas(nome_base)

    return nome_final.strip() or "Lead sem nome"


# ============================================================
# MAIN SCRIPT
# ============================================================

print("="*80)
print("ATUALIZAÇÃO INTELIGENTE DE NOMES NO CRM")
print("="*80)
print()

# 1. Login
print("🔐 Fazendo login...")
response = requests.post(f"{API_BASE_URL}/api/v1/auth/login", json={
    "email": "admin@alexandrequeiroz.com.br",
    "password": "1982Xandeq1982#"
})

if response.status_code != 200:
    print(f"❌ Erro no login: {response.status_code}")
    print(response.text)
    sys.exit(1)

token = response.json().get('token')
headers = {'Authorization': f'Bearer {token}'}
print("✅ Login bem-sucedido!")
print()

# 2. Buscar TODOS os leads com email
print("📥 Buscando todos os leads com email...")
all_leads = []
page = 1

while True:
    response = requests.get(
        f"{API_BASE_URL}/api/v1/leads",
        headers=headers,
        params={'page': page, 'pageSize': 100}
    )

    if response.status_code != 200:
        break

    data = response.json()

    if isinstance(data, list):
        leads_page = data
    elif 'data' in data:
        leads_page = data['data']
    elif 'items' in data:
        leads_page = data['items']
    else:
        leads_page = []

    if not leads_page:
        break

    all_leads.extend(leads_page)

    if len(leads_page) < 100:
        break

    page += 1

# Filtrar apenas leads COM email
leads_com_email = [l for l in all_leads if l.get('email') and '@' in l.get('email', '')]

print(f"✅ Total de leads: {len(all_leads)}")
print(f"✅ Leads COM EMAIL: {len(leads_com_email)}")
print()

# 3. Para cada lead, derivar nome inteligente e comparar
print("🔍 Analisando nomes...")
print()

leads_para_atualizar = []

for lead in leads_com_email:
    email = lead.get('email', '')
    nome_atual = (lead.get('name') or lead.get('companyName') or '').strip()

    # Derivar nome inteligente
    nome_novo = extrair_nome_de_email(email)

    # Comparar: só atualizar se for diferente E melhor
    if nome_novo != nome_atual and nome_novo != "Lead sem nome":
        # Verificar se é realmente uma melhoria
        # (nome novo tem espaços ou é diferente de nomes genéricos)
        if ' ' in nome_novo or nome_atual in ['Home', 'Lead sem nome', '']:
            leads_para_atualizar.append({
                'id': lead.get('id'),
                'email': email,
                'nome_antigo': nome_atual,
                'nome_novo': nome_novo
            })

print(f"📊 Leads que precisam de atualização: {len(leads_para_atualizar)}")
print()

if not leads_para_atualizar:
    print("✅ Todos os nomes já estão corretos!")
    sys.exit(0)

# Mostrar sample
print("📋 SAMPLE (primeiros 10 a serem atualizados):")
for i, lead in enumerate(leads_para_atualizar[:10], 1):
    print(f"{i}. {lead['email']}")
    print(f"   Antes: {lead['nome_antigo']}")
    print(f"   Depois: {lead['nome_novo']}")
    print()

# 4. Atualizar leads
print("="*80)
print(f"🚀 ATUALIZANDO {len(leads_para_atualizar)} LEADS...")
print("="*80)
print()

atualizados = 0
erros = 0

for i, lead in enumerate(leads_para_atualizar, 1):
    print(f"[{i}/{len(leads_para_atualizar)}] Atualizando {lead['email']}...")
    print(f"  {lead['nome_antigo']} → {lead['nome_novo']}")

    response = requests.put(
        f"{API_BASE_URL}/api/v1/customers/{lead['id']}",
        headers=headers,
        json={
            'name': lead['nome_novo'],
            'companyName': lead['nome_novo']
        }
    )

    if response.status_code == 200:
        print(f"  ✅ Atualizado com sucesso!")
        atualizados += 1
    else:
        print(f"  ❌ Erro: {response.status_code}")
        erros += 1

    print()

# 5. Resumo final
print("="*80)
print("✅ ATUALIZAÇÃO CONCLUÍDA!")
print("="*80)
print()
print(f"📊 Total analisado: {len(leads_com_email)} leads com email")
print(f"✅ Atualizados: {atualizados}")
print(f"❌ Erros: {erros}")
print()
print("="*80)
print()
print("🔗 Acesse: https://crm.alexandrequeiroz.com.br")
print()
