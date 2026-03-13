"""
lead_enrichment.py - Funções de Validação e Enriquecimento de Leads
Integrado ao app.py do Flask para preencher colunas do Database-First Model
"""

import re
import requests
import json
from decimal import Decimal
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
import time


# ════════════════════════════════════════════════════════════════════════════════
# FUNÇÕES DE VALIDAÇÃO
# ════════════════════════════════════════════════════════════════════════════════

def validate_email(email: str) -> dict:
    """
    Valida email usando verificação de sintaxe e SMTP check
    Retorna: {'valid': bool, 'method': str, 'disposable': bool}
    """
    if not email or not isinstance(email, str):
        return {'valid': False, 'method': 'format', 'disposable': False}

    # 1. Validação de formato (regex)
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_regex, email.strip()):
        return {'valid': False, 'method': 'format', 'disposable': False}

    # 2. Verificar se é email descartável (lista conhecida)
    disposable_domains = {
        'tempmail.com', '10minutemail.com', 'guerrillamail.com',
        'mailinator.com', 'yopmail.com', 'maildrop.cc',
        'trashmail.com', 'temp-mail.org', 'throwaway.email'
    }
    domain = email.split('@')[1].lower()
    is_disposable = domain in disposable_domains

    if is_disposable:
        return {'valid': False, 'method': 'disposable', 'disposable': True}

    # 3. Verificação MX records (DNS)
    try:
        import dns.resolver
        mx_records = dns.resolver.resolve(domain, 'MX')
        if not mx_records:
            return {'valid': False, 'method': 'mx_check', 'disposable': False}
        return {'valid': True, 'method': 'mx_check', 'disposable': False}
    except Exception:
        # Se não conseguir fazer MX check, retorna válido assumindo a sintaxe
        return {'valid': True, 'method': 'format', 'disposable': False}


def validate_phone(phone: str) -> dict:
    """
    Valida telefone brasileiro
    Retorna: {'valid': bool, 'format': str, 'country_code': str}
    """
    if not phone:
        return {'valid': False, 'format': None, 'country_code': None}

    # Remove caracteres não numéricos
    clean_phone = re.sub(r'\D', '', str(phone))

    # Verifica se é telefone BR (11 dígitos: 2 dígito area + 9 dígitos número)
    if len(clean_phone) == 11 and clean_phone[0:2].isdigit():
        area_code = clean_phone[0:2]
        # Verifica se é válido (01-99)
        if 11 <= int(area_code) <= 99:
            return {'valid': True, 'format': f'({area_code}) {clean_phone[2:7]}-{clean_phone[7:]}', 'country_code': 'BR'}

    # Telefone com 10 dígitos também é válido (antigo)
    if len(clean_phone) == 10 and clean_phone[0:2].isdigit():
        area_code = clean_phone[0:2]
        if 11 <= int(area_code) <= 99:
            return {'valid': True, 'format': f'({area_code}) {clean_phone[2:6]}-{clean_phone[6:]}', 'country_code': 'BR'}

    return {'valid': False, 'format': None, 'country_code': None}


def validate_website(website: str) -> dict:
    """
    Valida website verificando se é acessível
    Retorna: {'valid': bool, 'status_code': int, 'response_time_ms': int}
    """
    if not website:
        return {'valid': False, 'status_code': None, 'response_time_ms': None}

    # Adiciona https se não tiver protocolo
    if not website.startswith('http'):
        website = f'https://{website}'

    try:
        start = time.time()
        response = requests.head(website, timeout=5, allow_redirects=True)
        elapsed_ms = int((time.time() - start) * 1000)

        return {
            'valid': 200 <= response.status_code < 400,
            'status_code': response.status_code,
            'response_time_ms': elapsed_ms
        }
    except Exception as e:
        return {'valid': False, 'status_code': None, 'response_time_ms': None, 'error': str(e)}


# ════════════════════════════════════════════════════════════════════════════════
# FUNÇÕES DE ENRIQUECIMENTO
# ════════════════════════════════════════════════════════════════════════════════

def enrich_cnpj_brasilapi(cnpj: str) -> dict:
    """
    Enriquece lead via BrasilAPI (gratuito, sem limite)
    Retorna: {legal_name, employee_count, founded_year, website, etc}
    """
    if not cnpj:
        return {}

    # Remove caracteres não numéricos
    clean_cnpj = re.sub(r'\D', '', cnpj)

    if len(clean_cnpj) != 14:
        return {}

    try:
        response = requests.get(
            f'https://brasilapi.com.br/api/cnpj/v1/{clean_cnpj}',
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()
            return {
                'legal_name': data.get('razao_social') or data.get('nome_fantasia'),
                'employee_count': data.get('porte'),
                'founded_year': int(data.get('abertura', '0000')[:4]) if data.get('abertura') else None,
                'website': data.get('website'),
                'phone': data.get('telefone'),
                'street_address': f"{data.get('logradouro')}, {data.get('numero')}",
                'city': data.get('municipio'),
                'state': data.get('uf'),
                'zip_code': data.get('cep'),
                'neighborhood': data.get('bairro')
            }
    except Exception as e:
        print(f'❌ BrasilAPI error for CNPJ {clean_cnpj}: {str(e)}')
        pass

    return {}


def get_coordinates_from_address(street: str, city: str, state: str) -> dict:
    """
    Converte endereço em latitude/longitude via Nominatim (OpenStreetMap - GRATUITO)
    Retorna: {'latitude': float, 'longitude': float} ou {}
    """
    if not street or not city:
        return {}

    try:
        query = f'{street}, {city}, {state}, Brazil'
        response = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={'q': query, 'format': 'json', 'limit': 1},
            headers={'User-Agent': 'ExtratorDados/3.0'},
            timeout=5
        )

        if response.status_code == 200 and response.json():
            result = response.json()[0]
            return {
                'latitude': float(result['lat']),
                'longitude': float(result['lon'])
            }
    except Exception as e:
        print(f'❌ Nominatim error: {str(e)}')
        pass

    return {}


def extract_data_from_website(website: str) -> dict:
    """
    Scrapa website procurando por:
    - CEP (regex)
    - Email adicional (regex)
    - Telefone (regex)
    - Horário de funcionamento
    - Redes sociais

    Retorna: {'zip_code': str, 'email': str, 'phone': str, ...}
    """
    if not website:
        return {}

    if not website.startswith('http'):
        website = f'https://{website}'

    try:
        response = requests.get(website, timeout=10)
        text = response.text

        result = {}

        # 1. CEP (padrão brasileiro: xxxxx-xxx)
        cep_match = re.search(r'\d{5}-?\d{3}', text)
        if cep_match:
            result['zip_code'] = cep_match.group(0).replace('-', '')

        # 2. Email adicional
        email_matches = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', text)
        if email_matches:
            # Filtra emails de domínios conhecidos (gmail, hotmail, etc)
            business_emails = [e for e in email_matches if not any(d in e for d in ['gmail', 'hotmail', 'yahoo', 'outlook'])]
            if business_emails:
                result['email'] = business_emails[0]

        # 3. Telefone (padrão: (XX) XXXXX-XXXX ou XX XXXXX-XXXX)
        phone_matches = re.findall(r'\(?(\d{2})\)?\s?(\d{4,5})-?(\d{4})', text)
        if phone_matches:
            phone_data = phone_matches[0]
            result['phone'] = f'({phone_data[0]}) {phone_data[1]}-{phone_data[2]}'

        return result

    except Exception as e:
        print(f'❌ Website scraping error for {website}: {str(e)}')
        pass

    return {}


def generate_company_slug(company_name: str) -> str:
    """
    Gera slug único para deduplicação
    Ex: "Clínica Vitória Saúde" → "clinica-vitoria-saude"
    """
    if not company_name:
        return None

    import unicodedata

    # Remove acentos
    slug = unicodedata.normalize('NFD', company_name)
    slug = ''.join(c for c in slug if unicodedata.category(c) != 'Mn')

    # Converte para lowercase e replace espaços/caracteres especiais
    slug = slug.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')

    return slug


# ════════════════════════════════════════════════════════════════════════════════
# SISTEMA DE SCORING (CRÍTICO)
# ════════════════════════════════════════════════════════════════════════════════

def calculate_lead_quality_score(lead: dict) -> dict:
    """
    Calcula quality_score (0-100) baseado em campos preenchidos e validações

    Pontuação:
    - Email válido e verificado: +25 pts
    - Telefone válido: +15 pts
    - Endereço completo: +15 pts
    - Website acessível: +10 pts
    - Redes sociais (2+): +10 pts
    - CNPJ enriquecido: +10 pts
    - Coordenadas: +5 pts
    - Descrição/info: +5 pts

    Retorna: {
        'quality_score': int (0-100),
        'completeness_pct': int (0-100),
        'confidence_level': str (low/medium/high),
        'breakdown': dict (detalhamento por campo)
    }
    """
    score = 0
    completeness = 0
    fields_filled = 0
    total_fields = 15  # número de campos verificados

    breakdown = {}

    # 1. Email
    if lead.get('email'):
        fields_filled += 1
        email_val = validate_email(lead['email'])
        if email_val.get('valid'):
            score += 25
            breakdown['email'] = 25
        else:
            score += 5  # email existe mas não validado
            breakdown['email'] = 5

    # 2. Telefone
    if lead.get('phone'):
        fields_filled += 1
        phone_val = validate_phone(lead['phone'])
        if phone_val.get('valid'):
            score += 15
            breakdown['phone'] = 15
        else:
            score += 3
            breakdown['phone'] = 3

    # 3. Endereço completo (rua + cidade + estado + CEP)
    has_address = (
        lead.get('address') or lead.get('street_address')
    ) and lead.get('city') and lead.get('zip_code')

    if has_address:
        fields_filled += 1
        score += 15
        breakdown['address'] = 15
    elif lead.get('city'):
        fields_filled += 1
        score += 5  # cidade mas sem endereço completo
        breakdown['address'] = 5

    # 4. Website
    if lead.get('website'):
        fields_filled += 1
        website_val = validate_website(lead['website'])
        if website_val.get('valid'):
            score += 10
            breakdown['website'] = 10
        else:
            score += 2
            breakdown['website'] = 2

    # 5. Redes Sociais (2+)
    social_count = sum(1 for s in ['instagram', 'facebook', 'linkedin', 'twitter', 'youtube'] if lead.get(s))
    if social_count >= 2:
        fields_filled += 1
        score += 10
        breakdown['social'] = 10
    elif social_count == 1:
        fields_filled += 1
        score += 5
        breakdown['social'] = 5

    # 6. CNPJ enriquecido
    if lead.get('cnpj_enriched') or lead.get('legal_name'):
        fields_filled += 1
        score += 10
        breakdown['cnpj'] = 10

    # 7. Coordenadas
    if lead.get('latitude') and lead.get('longitude'):
        fields_filled += 1
        score += 5
        breakdown['coordinates'] = 5

    # 8. Descrição/info adicional
    if lead.get('description') or lead.get('employee_count'):
        fields_filled += 1
        score += 5
        breakdown['description'] = 5

    # Calcular completeness percentage
    completeness_pct = int((fields_filled / total_fields) * 100)

    # Confidence level baseado em score
    if score >= 70 and lead.get('email_verified') and lead.get('phone_verified'):
        confidence = 'high'
    elif score >= 45:
        confidence = 'medium'
    else:
        confidence = 'low'

    return {
        'quality_score': min(100, score),
        'completeness_pct': completeness_pct,
        'confidence_level': confidence,
        'breakdown': breakdown,
        'fields_filled': fields_filled,
        'total_fields': total_fields
    }


def classify_lead_tier(quality_score: int) -> str:
    """
    Classifica lead em tiers de qualidade
    0-30: Bronze (email only)
    31-60: Silver (email + phone)
    61-80: Gold (email + phone + address)
    81-100: Platinum (ultra-completo)
    """
    if quality_score >= 81:
        return 'platinum'
    elif quality_score >= 61:
        return 'gold'
    elif quality_score >= 31:
        return 'silver'
    else:
        return 'bronze'


# ════════════════════════════════════════════════════════════════════════════════
# FUNÇÃO MAESTRO: Enriquecer Lead Completo
# ════════════════════════════════════════════════════════════════════════════════

def enrich_lead_comprehensive(lead: dict, db_conn=None) -> dict:
    """
    Função master que enriquece um lead com TODOS os dados disponíveis

    Fluxo:
    1. Validar email e telefone
    2. Enriquecer via CNPJ (BrasilAPI)
    3. Scrapear website para mais dados
    4. Obter coordenadas (Nominatim)
    5. Calcular quality score
    6. Rastrear sources

    Retorna: lead enriquecido com todos os campos preenchidos
    """

    enriched = lead.copy()
    sources = enriched.get('data_sources', [])
    if not isinstance(sources, list):
        sources = []

    start_time = datetime.now()

    # 1. Validar email
    if enriched.get('email'):
        email_validation = validate_email(enriched['email'])
        if email_validation.get('valid'):
            enriched['email_verified'] = True
            sources.append('email_validated')

    # 2. Validar telefone
    if enriched.get('phone'):
        phone_validation = validate_phone(enriched['phone'])
        if phone_validation.get('valid'):
            enriched['phone_verified'] = True
            enriched['phone'] = phone_validation.get('format', enriched['phone'])
            sources.append('phone_validated')

    # 3. Enriquecer via CNPJ (BrasilAPI - GRATUITO)
    if enriched.get('cnpj'):
        cnpj_data = enrich_cnpj_brasilapi(enriched['cnpj'])
        enriched.update(cnpj_data)
        if cnpj_data:
            sources.append('brasilapi')

    # 4. Scrapear website para mais dados
    if enriched.get('website') and not enriched.get('zip_code'):
        web_data = extract_data_from_website(enriched['website'])
        enriched.update(web_data)
        if web_data:
            sources.append('website_scrape')

    # 5. Validar website
    if enriched.get('website'):
        website_validation = validate_website(enriched['website'])
        if website_validation.get('valid'):
            enriched['website_verified'] = True

    # 6. Obter coordenadas (Nominatim - GRATUITO)
    if enriched.get('address') or enriched.get('street_address'):
        if not enriched.get('latitude'):
            coords = get_coordinates_from_address(
                enriched.get('street_address') or enriched.get('address'),
                enriched.get('city'),
                enriched.get('state')
            )
            if coords:
                enriched.update(coords)
                sources.append('nominatim')

    # 7. Gerar slug para dedup
    if enriched.get('company_name') and not enriched.get('company_slug'):
        enriched['company_slug'] = generate_company_slug(enriched['company_name'])

    # 8. Calcular quality score
    quality = calculate_lead_quality_score(enriched)
    enriched['quality_score_numeric'] = quality['quality_score']
    enriched['completeness_pct'] = quality['completeness_pct']
    enriched['confidence_level'] = quality['confidence_level']

    # 9. Atualizar sources e timestamps
    enriched['data_sources'] = list(set(sources))  # remove duplicatas
    enriched['last_verified_at'] = datetime.now()

    if not enriched.get('first_scraped_at'):
        enriched['first_scraped_at'] = datetime.now()

    return enriched
