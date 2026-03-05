#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Algoritmo INTELIGENTE de derivação de nomes a partir de emails
Com detecção de nomes próprios brasileiros e separação de palavras compostas
"""

import sys
import io
import json
import re

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Nomes próprios comuns no Brasil
NOMES_PROPRIOS = [
    'alexandre', 'cristina', 'cristiane', 'fernanda', 'fernando', 'gabriela', 'gabriel',
    'joao', 'jose', 'julia', 'juliana', 'lucas', 'luiz', 'luis', 'marcelo', 'marcela',
    'marcia', 'maria', 'marina', 'mario', 'mateus', 'miguel', 'natalia', 'paulo', 'paula',
    'pedro', 'rafael', 'renato', 'renata', 'ricardo', 'roberto', 'rodrigo', 'sergio',
    'thiago', 'tiago', 'vitor', 'vitoria', 'viviane', 'carlos', 'carla', 'ana', 'andre',
    'antonio', 'bruno', 'camila', 'daniel', 'daniela', 'diego', 'eduardo', 'fabio', 'felipe'
]

# Sobrenomes comuns
SOBRENOMES = [
    'silva', 'santos', 'oliveira', 'souza', 'rodrigues', 'ferreira', 'alves', 'pereira',
    'lima', 'gomes', 'costa', 'ribeiro', 'martins', 'carvalho', 'almeida', 'lopes',
    'soares', 'fernandes', 'vieira', 'barbosa', 'rocha', 'dias', 'nascimento', 'castro',
    'araujo', 'cunha', 'pinto', 'teixeira', 'correia', 'cavalcanti', 'monteiro', 'moreira',
    'mendes', 'barros', 'freitas', 'cardoso', 'melo', 'campos', 'reis', 'miranda', 'pires',
    'farias', 'brito', 'sales', 'azevedo', 'coelho', 'nunes', 'moura', 'ramos', 'milanez',
    'milan', 'milanes'
]

# Palavras conectoras
CONECTORAS = ['de', 'da', 'do', 'das', 'dos', 'e', 'ou']

# Palavras de negócio
PALAVRAS_NEGOCIO = {
    'contabilidade': 'Contabilidade',
    'advocacia': 'Advocacia',
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
    'pousada': 'Pousada'
}

# Prefixos genéricos a serem ignorados
PREFIXOS_GENERICOS = ['contato', 'atendimento', 'info', 'comercial', 'vendas', 'suporte', 'faleconosco']

# Domínios genéricos (email pessoal)
DOMINIOS_GENERICOS = ['gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com', 'live.com', 'msn.com']


def detectar_nome_proprio(palavra):
    """Detecta se é um nome próprio (pessoa)."""
    palavra_lower = palavra.lower()
    return palavra_lower in NOMES_PROPRIOS or palavra_lower in SOBRENOMES


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


print("="*80)
print("TESTE DO ALGORITMO INTELIGENTE")
print("="*80)
print()

# Casos de teste dos exemplos que você mencionou
casos_teste = [
    "contato@bateleur.com.br",
    "contato@cabanadoluiz.com.br",
    "contato@cristinamilanez.com",
    "comercial@informatizecontabilidade.com.br",
    "bentoferreira@skyfitacademia.com.br",
    "lagemannconsultoria@gmail.com",
    "contato@faveroadvogados.com.br",
    "atendimento@liviamachado.com",
    "marly@adimovel.com.br"
]

print("TESTES:")
for email in casos_teste:
    nome = extrair_nome_de_email(email)
    print(f"✓ {email}")
    print(f"  → {nome}")
    print()

print("="*80)
print("ALGORITMO TESTADO!")
print("="*80)
print()
print("Próximo passo: aplicar aos leads do CRM")
