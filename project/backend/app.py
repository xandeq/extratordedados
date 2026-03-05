#!/usr/bin/env python3
"""
Extrator de Dados - Backend Flask
API para scraping automatizado de emails, telefones e dados empresariais
PostgreSQL + Rate Limiting + Deduplicacao + Batch Processing + Deep Crawl
+ Redes Sociais + CNPJ + WhatsApp + Endereco (Fase 3)
"""
import sys
import os
import io
import csv
import threading
import random
import time
from urllib.parse import urlparse, urljoin, quote as requests_quote

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json
import hashlib
import secrets
from datetime import datetime, timedelta
import requests as http_requests
from bs4 import BeautifulSoup
import re
import psycopg2
from psycopg2 import pool
from contextlib import contextmanager

app = Flask(__name__)
app.config['PROPAGATE_EXCEPTIONS'] = True

# Trust X-Forwarded-For from Traefik reverse proxy
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

CORS(app)

# ============= Rate Limiting =============

def get_real_ip():
    """Get real client IP behind Traefik proxy."""
    return request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

limiter = Limiter(
    app=app,
    key_func=get_real_ip,
    default_limits=["200/hour"],
    storage_uri="memory://",
)

# ============= Config =============

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'port': int(os.environ.get('DB_PORT', 5432)),
    'dbname': os.environ.get('DB_NAME', 'extrator'),
    'user': os.environ.get('DB_USER', 'extrator'),
    'password': os.environ.get('DB_PASSWORD', 'Extr4t0r_S3cur3_2026!'),
}

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = hashlib.sha256("1982Xandeq1982#".encode()).hexdigest()

# ============= Anti-Blocking =============

USER_AGENTS = [
    # Chrome (Windows)
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    # Chrome (Mac)
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    # Chrome (Linux)
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    # Firefox (Windows)
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    # Firefox (Mac)
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0',
    # Firefox (Linux)
    'Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0',
    # Safari (Mac)
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    # Edge (Windows)
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0',
    # Edge (Mac)
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    # Opera
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0',
    # Brave (same as Chrome UA)
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
]

# ============= Search Engine Config =============

SEARCH_REGIONS = {
    'grande_vitoria_es': {
        'name': 'Grande Vitoria - ES',
        'state': 'ES',
        'cities': ['Vitoria', 'Vila Velha', 'Serra', 'Cariacica', 'Viana', 'Guarapari', 'Fundao'],
    },
    'grande_sp': {
        'name': 'Grande Sao Paulo - SP',
        'state': 'SP',
        'cities': ['Sao Paulo', 'Guarulhos', 'Osasco', 'Santo Andre', 'Sao Bernardo do Campo', 'Diadema', 'Maua', 'Barueri'],
    },
    'grande_rj': {
        'name': 'Grande Rio de Janeiro - RJ',
        'state': 'RJ',
        'cities': ['Rio de Janeiro', 'Niteroi', 'Sao Goncalo', 'Duque de Caxias', 'Nova Iguacu', 'Petropolis'],
    },
    'grande_bh': {
        'name': 'Grande Belo Horizonte - MG',
        'state': 'MG',
        'cities': ['Belo Horizonte', 'Contagem', 'Betim', 'Ribeirao das Neves', 'Santa Luzia', 'Sabara'],
    },
}

SKIP_DOMAINS = {
    'facebook.com', 'instagram.com', 'twitter.com', 'x.com', 'linkedin.com',
    'youtube.com', 'tiktok.com', 'pinterest.com', 'reddit.com',
    'mercadolivre.com.br', 'olx.com.br', 'amazon.com.br', 'magazineluiza.com.br',
    'gov.br', 'wikipedia.org', 'tripadvisor.com', 'tripadvisor.com.br',
    'reclameaqui.com.br', 'yelp.com', 'glassdoor.com',
    'google.com', 'google.com.br', 'bing.com', 'duckduckgo.com',
    'yahoo.com', 'uol.com.br', 'globo.com', 'terra.com.br',
}

# ============= Email Quality Filters =============

# Agregadores, diretórios e plataformas que não são leads reais
EMAIL_AGGREGATOR_DOMAINS = {
    'doctoralia.com.br', 'doctoralia.es', 'doctoralia.com',
    'zhihu.com', 'stackoverflow.com', 'quora.com',
    'listamais.com.br', 'guiafacil.com', 'encontrasp.com.br',
    'forum-pet.de', 'forum-pet.com',
    'hospitales-privados.es', 'quironsalud.es', 'quironsalud.com',
    'sentry.io', 'wixpress.com', 'wix.com',
    'hostinger.com', 'vercel.com', 'netlify.com',
    'nesx.co', 'weebly.com', 'squarespace.com',
    'sjd.es', 'vithas.es', 'sanitas.es',
}

# Padrões de emails genéricos/inválidos
EMAIL_INVALID_PATTERNS = [
    r'@(example|test|domain|email|company|yourdomain|yourcompany|site|website)\.',
    r'(noreply|no-reply|donotreply)@',
    r'@(localhost|127\.0\.0\.1)',
    r'@(placeholder|dummy|fake|sample)\.',
    r'^(image|img|photo|foto|icon|banner|logo)@',
    r'@(svg|png|jpg|jpeg|gif|webp|ico)\.',
    r'\.(jpg|jpeg|png|svg|gif|webp|ico|pdf|doc|zip)$',
    r'^[0-9]+@',  # Email começa só com números
    r'@[0-9]+\.',  # Domínio começa só com números
    r'javascript:|mailto:$|void\(0\)',
]

# Emails genéricos de baixa qualidade (podem ser reais mas não são decisores)
EMAIL_LOW_QUALITY_PATTERNS = [
    r'^(webmaster|postmaster|hostmaster|abuse|spam)@',
    r'^(root|admin|administrator|system|daemon)@',
    r'^(info|contact|contato|atendimento|suporte|support|sales|vendas)@',
    r'^(newsletter|news|noticias|updates|marketing)@',
    r'^(financeiro|rh|recursos-humanos|fiscal|comercial|recepcao|portaria)@',
    r'^(contabilidade|vendas|sac|ouvidoria|diretoria|gestao)@',
]

# Sufixos empresariais comuns para limpeza de nomes
CORPORATE_SUFFIXES = [
    ' LTDA', ' S/A', ' SA', ' EIRELI', ' ME', ' EPP', ' MEI',
    ' LIMITADA', ' SERVICOS', ' SERVICE', ' SOLUTIONS', ' CONSULTORIA',
    ' ASSESSORIA', ' EMPREENDIMENTOS', ' PARTICIPACOES',
]

# TLDs de países irrelevantes (quando busca é Brasil)
EMAIL_FOREIGN_TLDS = {
    '.es', '.de', '.fr', '.it', '.uk', '.cn', '.jp', '.kr', '.ru',
    '.pt',  # Portugal pode ser irrelevante dependendo do contexto
}

# Search safety delays (seconds)
SEARCH_DELAY_BETWEEN_PAGES = (5, 15)      # Between search result pages
SEARCH_DELAY_BETWEEN_SITES = (3, 8)       # Between crawled sites
SEARCH_DELAY_BETWEEN_CITIES = (10, 20)    # Between city searches

CONTACT_PATHS = [
    '/contato', '/contact', '/contacto',
    '/sobre', '/about', '/quem-somos',
    '/empresa', '/institucional', '/fale-conosco',
]

SITEMAP_KEYWORDS = ['contato', 'contact', 'about', 'sobre', 'empresa', 'institucional', 'fale-conosco', 'quem-somos']

DELAY_BETWEEN_DOMAINS = 2
DELAY_BETWEEN_SUBPAGES = 1
REQUEST_TIMEOUT = 10
MAX_SITEMAP_URLS = 20

# ============= Connection Pool =============

db_pool = None

def get_pool():
    global db_pool
    if db_pool is None or db_pool.closed:
        db_pool = pool.SimpleConnectionPool(1, 10, **DB_CONFIG)
    return db_pool

@contextmanager
def get_db():
    """Get a database connection from the pool."""
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)

# ============= Database =============

def init_db():
    """Initialize database tables"""
    with get_db() as conn:
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(64) NOT NULL,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            token VARCHAR(64) UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            expires_at TIMESTAMP NOT NULL
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS jobs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            results_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            started_at TIMESTAMP,
            finished_at TIMESTAMP
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS emails (
            id SERIAL PRIMARY KEY,
            job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
            email VARCHAR(320) NOT NULL,
            source_url TEXT,
            context TEXT,
            extracted_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(job_id, email)
        )''')

        # Batch processing tables
        c.execute('''CREATE TABLE IF NOT EXISTS batches (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(255),
            status VARCHAR(20) DEFAULT 'pending',
            total_urls INTEGER DEFAULT 0,
            processed_urls INTEGER DEFAULT 0,
            total_leads INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            started_at TIMESTAMP,
            finished_at TIMESTAMP
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS leads (
            id SERIAL PRIMARY KEY,
            batch_id INTEGER REFERENCES batches(id) ON DELETE CASCADE,
            company_name VARCHAR(255),
            email VARCHAR(320),
            phone VARCHAR(50),
            website VARCHAR(500),
            source_url TEXT,
            city VARCHAR(100),
            state VARCHAR(50),
            category VARCHAR(100),
            source VARCHAR(50) DEFAULT 'website_crawl',
            extracted_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(batch_id, email)
        )''')

        # Phase 3: Add new columns if they don't exist
        new_columns = [
            ('instagram', 'VARCHAR(255)'),
            ('facebook', 'VARCHAR(255)'),
            ('linkedin', 'VARCHAR(255)'),
            ('twitter', 'VARCHAR(255)'),
            ('youtube', 'VARCHAR(255)'),
            ('whatsapp', 'VARCHAR(50)'),
            ('cnpj', 'VARCHAR(20)'),
            ('address', 'TEXT'),
        ]

        # Phase 4: CRM columns
        new_columns += [
            ('crm_status', "VARCHAR(30) DEFAULT 'novo'"),
            ('tags', 'TEXT'),
            ('notes', 'TEXT'),
            ('contact_name', 'VARCHAR(255)'),
            ('updated_at', 'TIMESTAMP'),
        ]

        # Phase 7: Search + Quality columns
        new_columns += [
            ('quality_score', "VARCHAR(20) DEFAULT 'basico'"),
            ('extra_data', 'JSONB'),
        ]

        for col_name, col_type in new_columns:
            try:
                c.execute(f'ALTER TABLE leads ADD COLUMN {col_name} {col_type}')
            except psycopg2.errors.DuplicateColumn:
                conn.rollback()

        # Search jobs table
        c.execute('''CREATE TABLE IF NOT EXISTS search_jobs (
            id SERIAL PRIMARY KEY,
            batch_id INTEGER REFERENCES batches(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            query TEXT,
            engine VARCHAR(30),
            niche VARCHAR(100),
            city VARCHAR(100),
            state VARCHAR(10),
            region VARCHAR(50),
            max_pages INTEGER DEFAULT 2,
            status VARCHAR(20) DEFAULT 'pending',
            total_results INTEGER DEFAULT 0,
            processed_results INTEGER DEFAULT 0,
            total_leads INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            error_message TEXT
        )''')

        # Search logs table
        c.execute('''CREATE TABLE IF NOT EXISTS search_logs (
            id SERIAL PRIMARY KEY,
            search_job_id INTEGER REFERENCES search_jobs(id) ON DELETE CASCADE,
            log_type VARCHAR(30),
            url TEXT,
            status_code INTEGER,
            message TEXT,
            duration_ms INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        )''')

        # API configs table (stores API keys per user per provider)
        c.execute('''CREATE TABLE IF NOT EXISTS api_configs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR(30) NOT NULL,
            api_key VARCHAR(500),
            api_secret VARCHAR(500),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP,
            UNIQUE(user_id, provider)
        )''')

        # API usage tracking (monthly credits)
        c.execute('''CREATE TABLE IF NOT EXISTS api_usage (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR(30) NOT NULL,
            month_year VARCHAR(7) NOT NULL,
            credits_used INTEGER DEFAULT 0,
            credits_limit INTEGER DEFAULT 0,
            last_reset_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, provider, month_year)
        )''')

        # API cache (avoid re-querying same domain within 30 days)
        c.execute('''CREATE TABLE IF NOT EXISTS api_cache (
            id SERIAL PRIMARY KEY,
            domain VARCHAR(255) NOT NULL,
            provider VARCHAR(30) NOT NULL,
            response_data JSONB,
            credits_cost INTEGER DEFAULT 1,
            queried_at TIMESTAMP DEFAULT NOW(),
            expires_at TIMESTAMP NOT NULL,
            UNIQUE(domain, provider)
        )''')

        # enrichment_source column on search_jobs
        try:
            c.execute("ALTER TABLE search_jobs ADD COLUMN enrichment_source VARCHAR(30) DEFAULT 'scraping'")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        # Indexes
        c.execute('CREATE INDEX IF NOT EXISTS idx_emails_job_id ON emails(job_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_batches_user_id ON batches(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_leads_batch_id ON leads(batch_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_leads_crm_status ON leads(crm_status)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_search_jobs_batch_id ON search_jobs(batch_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_search_logs_job_id ON search_logs(search_job_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_leads_quality ON leads(quality_score)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_api_configs_user ON api_configs(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_api_usage_user_month ON api_usage(user_id, month_year)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_api_cache_domain ON api_cache(domain, provider)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_api_cache_expires ON api_cache(expires_at)')

        # Insert admin user if not exists
        c.execute('SELECT id FROM users WHERE username = %s', (ADMIN_USERNAME,))
        if not c.fetchone():
            c.execute(
                'INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (%s, %s, %s, %s)',
                (ADMIN_USERNAME, ADMIN_PASSWORD_HASH, True, datetime.now())
            )

# ============= Auth =============

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_session(user_id):
    """Create auth token for user"""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(days=7)

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'INSERT INTO sessions (user_id, token, created_at, expires_at) VALUES (%s, %s, %s, %s)',
            (user_id, token, datetime.now(), expires_at)
        )

    return token

def verify_token(token):
    """Verify token and return user_id"""
    if not token:
        return None

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'SELECT user_id FROM sessions WHERE token = %s AND expires_at > %s',
            (token, datetime.now())
        )
        result = c.fetchone()

    return result[0] if result else None

def get_auth_header():
    """Extract token from Authorization header"""
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth[7:]
    return None

# ============= Email Normalization =============

INVALID_EMAIL_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp',
    '.css', '.js', '.woff', '.woff2', '.ttf', '.eot',
}

def calculate_email_quality_score(email_str):
    """
    Calculate quality score for email (0-100).
    Returns: (score, is_valid, rejection_reason)

    Score ranges:
    - 80-100: High quality (nome@empresa.com.br, contato corporativo real)
    - 50-79: Medium quality (emails genéricos mas válidos)
    - 0-49: Low quality / Invalid
    """
    email_lower = email_str.lower().strip()

    # Validação básica de formato
    if '@' not in email_lower or '.' not in email_lower.split('@')[-1]:
        return 0, False, 'formato_invalido'

    if len(email_lower) > 320:
        return 0, False, 'email_muito_longo'

    # Extrair domínio
    try:
        local_part, domain = email_lower.split('@')
    except ValueError:
        return 0, False, 'formato_invalido'

    # Check 1: Agregadores e diretórios (BLOQUEIO TOTAL)
    for aggregator_domain in EMAIL_AGGREGATOR_DOMAINS:
        if aggregator_domain in domain:
            return 0, False, f'agregador:{aggregator_domain}'

    # Check 2: Padrões inválidos (BLOQUEIO TOTAL)
    for pattern in EMAIL_INVALID_PATTERNS:
        if re.search(pattern, email_lower):
            return 0, False, f'padrao_invalido:{pattern[:30]}'

    # Check 3: TLDs estrangeiros (BLOQUEIO se não é .br)
    for foreign_tld in EMAIL_FOREIGN_TLDS:
        if email_lower.endswith(foreign_tld):
            return 0, False, f'tld_estrangeiro:{foreign_tld}'

    # Check 4: Extensões de arquivo inválidas
    for ext in INVALID_EMAIL_EXTENSIONS:
        if email_lower.endswith(ext):
            return 0, False, f'extensao_arquivo:{ext}'

    # A partir daqui, o email é VÁLIDO, mas calculamos qualidade
    score = 100

    # Penalização: Emails genéricos de baixa qualidade (-30 pontos)
    for pattern in EMAIL_LOW_QUALITY_PATTERNS:
        if re.search(pattern, email_lower):
            score -= 30
            break

    # Penalização: Domínios de email gratuito (-20 pontos)
    free_email_domains = ['gmail.com', 'hotmail.com', 'yahoo.com', 'outlook.com',
                          'bol.com.br', 'ig.com.br', 'uol.com.br', 'terra.com.br']
    if any(free_domain in domain for free_domain in free_email_domains):
        score -= 20

    # Bônus: Email corporativo com nome real (+10 pontos)
    # Exemplo: joao.silva@empresa.com.br (tem ponto no local_part)
    if '.' in local_part and len(local_part) > 5:
        score += 10

    # Bônus: Domínio .com.br ou .med.br (email brasileiro corporativo)
    if domain.endswith('.com.br') or domain.endswith('.med.br'):
        score += 10

    # Garantir range 0-100
    score = max(0, min(100, score))

    return score, True, None

def normalize_email(email_str):
    """
    Normalize and validate an email address with quality filtering.
    Returns the normalized email or None if invalid/low-quality.
    """
    email_str = email_str.strip().lower()
    email_str = email_str.rstrip('.')

    score, is_valid, rejection_reason = calculate_email_quality_score(email_str)

    # BLOQUEIO: Rejeitar emails inválidos ou de agregadores
    if not is_valid:
        print(f"[email_filter] REJECTED: {email_str} - {rejection_reason}")
        return None

    # BLOQUEIO: Rejeitar emails com score muito baixo (<40)
    if score < 40:
        print(f"[email_filter] LOW QUALITY: {email_str} - score {score}")
        return None

    return email_str

# ============= Phone Extraction =============

PHONE_PATTERN = re.compile(
    r'(?:\+55\s?)?(?:\(?\d{2}\)?\s?)?\d{4,5}[-.\s]?\d{4}'
)

def extract_phones(text):
    """Extract Brazilian phone numbers from text."""
    raw_phones = PHONE_PATTERN.findall(text)
    phones = []
    for phone in raw_phones:
        digits = re.sub(r'\D', '', phone)
        if 8 <= len(digits) <= 13:
            phones.append(phone.strip())
    return list(set(phones))

# ============= CNPJ Extraction =============

CNPJ_PATTERN = re.compile(
    r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}'
)

def extract_cnpj(text):
    """Extract Brazilian CNPJ numbers from text."""
    found = CNPJ_PATTERN.findall(text)
    return list(set(found))

# ============= WhatsApp Extraction =============

WHATSAPP_LINK_PATTERN = re.compile(
    r'(?:https?://)?(?:wa\.me|api\.whatsapp\.com/send\?phone=|chat\.whatsapp\.com/)[\w/+?=&%-]*',
    re.IGNORECASE
)

WHATSAPP_NUMBER_PATTERN = re.compile(
    r'wa\.me/(\+?\d{10,15})'
)

def extract_whatsapp(soup, text):
    """Extract WhatsApp numbers from links and text."""
    whatsapp_numbers = set()

    # From wa.me and api.whatsapp.com links
    for tag in soup.find_all('a', href=True):
        href = tag['href'].lower()
        if 'wa.me/' in href or 'whatsapp.com' in href:
            # Extract phone number from URL
            match = re.search(r'(\+?\d{10,15})', href)
            if match:
                whatsapp_numbers.add(match.group(1))

    # From text (wa.me links in plain text)
    for match in WHATSAPP_NUMBER_PATTERN.findall(text):
        whatsapp_numbers.add(match)

    return list(whatsapp_numbers)

# ============= Social Media Extraction =============

SOCIAL_PATTERNS = {
    'instagram': re.compile(
        r'(?:https?://)?(?:www\.)?instagram\.com/([a-zA-Z0-9_.]{1,30})/?(?:\?[^\s"\']*)?',
        re.IGNORECASE
    ),
    'facebook': re.compile(
        r'(?:https?://)?(?:www\.)?(?:facebook\.com|fb\.com)/([a-zA-Z0-9._/-]{1,100})/?(?:\?[^\s"\']*)?',
        re.IGNORECASE
    ),
    'linkedin': re.compile(
        r'(?:https?://)?(?:www\.)?linkedin\.com/(?:company|in)/([a-zA-Z0-9_-]{1,100})/?(?:\?[^\s"\']*)?',
        re.IGNORECASE
    ),
    'twitter': re.compile(
        r'(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/([a-zA-Z0-9_]{1,30})/?(?:\?[^\s"\']*)?',
        re.IGNORECASE
    ),
    'youtube': re.compile(
        r'(?:https?://)?(?:www\.)?youtube\.com/(?:@|channel/|c/)?([a-zA-Z0-9_-]{1,100})/?(?:\?[^\s"\']*)?',
        re.IGNORECASE
    ),
}

# Social media usernames to ignore (generic pages)
SOCIAL_IGNORE = {
    'share', 'sharer', 'intent', 'login', 'signup', 'help',
    'about', 'privacy', 'terms', 'legal', 'policies', 'settings',
    'explore', 'search', 'hashtag', 'home', 'feed', 'watch',
    'trending', 'results', 'company', 'in', 'pub', 'tr',
}

def extract_social_media(soup):
    """Extract social media profile URLs from page links."""
    socials = {
        'instagram': None,
        'facebook': None,
        'linkedin': None,
        'twitter': None,
        'youtube': None,
    }

    for tag in soup.find_all('a', href=True):
        href = tag['href'].strip()
        if not href:
            continue

        for platform, pattern in SOCIAL_PATTERNS.items():
            if socials[platform]:
                continue  # Already found
            match = pattern.search(href)
            if match:
                username = match.group(1).strip('/').split('/')[0].split('?')[0]
                if username.lower() not in SOCIAL_IGNORE and len(username) > 1:
                    # Store the full cleaned URL
                    if platform == 'instagram':
                        socials[platform] = f'https://instagram.com/{username}'
                    elif platform == 'facebook':
                        socials[platform] = f'https://facebook.com/{username}'
                    elif platform == 'linkedin':
                        link_type = 'company' if '/company/' in href else 'in'
                        socials[platform] = f'https://linkedin.com/{link_type}/{username}'
                    elif platform == 'twitter':
                        socials[platform] = f'https://x.com/{username}'
                    elif platform == 'youtube':
                        prefix = '@' if '@' in href else 'channel/' if 'channel/' in href else 'c/'
                        socials[platform] = f'https://youtube.com/{prefix}{username}'

    return socials

# ============= Address / CEP Extraction =============

CEP_PATTERN = re.compile(
    r'\d{5}-?\d{3}'
)

# Brazilian state abbreviations
BR_STATES = {
    'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA',
    'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN',
    'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO',
}

ADDRESS_KEYWORDS = [
    'rua ', 'av ', 'av.', 'avenida ', 'alameda ', 'travessa ',
    'rodovia ', 'estrada ', 'praça ', 'praca ', 'largo ',
]

def extract_address_info(text):
    """Extract CEP and address hints from text."""
    # Extract CEPs
    ceps = list(set(CEP_PATTERN.findall(text)))

    # Try to find city/state patterns like "São Paulo - SP" or "Curitiba/PR"
    city = None
    state = None

    # Pattern: City - UF or City/UF or City, UF
    city_state_pattern = re.compile(
        r'([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú]?[a-zà-ú]+)*)\s*[-/,]\s*([A-Z]{2})\b'
    )
    matches = city_state_pattern.findall(text)
    for match_city, match_state in matches:
        if match_state in BR_STATES:
            city = match_city.strip()
            state = match_state
            break

    # Try to find address lines
    address = None
    text_lower = text.lower()
    for keyword in ADDRESS_KEYWORDS:
        idx = text_lower.find(keyword)
        if idx >= 0:
            # Grab up to 120 chars from the keyword start
            snippet = text[idx:idx+120]
            # Clean up: take until newline or common end markers
            snippet = snippet.split('\n')[0].strip()
            if len(snippet) > 10:
                address = snippet[:200]
                break

    return {
        'ceps': ceps,
        'city': city,
        'state': state,
        'address': address,
    }

# ============= Company Name Extraction =============

TITLE_SUFFIXES = [
    ' - Home', ' | Home', ' - Inicio', ' | Inicio',
    ' - Site Oficial', ' | Site Oficial',
    ' - Pagina Inicial', ' | Pagina Inicial',
    ' - Bem-vindo', ' | Bem-vindo',
]

def extract_company_name(soup, url):
    """Extract company name from page metadata."""
    # Try og:site_name first
    og_site = soup.find('meta', property='og:site_name')
    if og_site and og_site.get('content', '').strip():
        return og_site['content'].strip()[:255]

    # Try title tag
    if soup.title and soup.title.string:
        name = soup.title.string.strip()
        for suffix in TITLE_SUFFIXES:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
        # Take first part before common separators
        for sep in [' | ', ' - ', ' :: ', ' » ']:
            if sep in name:
                name = name.split(sep)[0].strip()
                break
        if name and len(name) < 200:
            return name[:255]

    # Fallback: domain name
    parsed = urlparse(url)
    domain = parsed.hostname or ''
    domain = domain.replace('www.', '')
    if domain:
        return domain

    return None

# ============= Deep Crawl Logic =============

def fetch_page(url, session=None):
    """Fetch a single page with random User-Agent."""
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    try:
        if session:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, verify=False, headers=headers)
        else:
            resp = http_requests.get(url, timeout=REQUEST_TIMEOUT, verify=False, headers=headers)
        resp.encoding = 'utf-8'
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        print(f"[crawl] Error fetching {url}: {e}")
    return None

def parse_sitemap(base_url, session=None):
    """Parse sitemap.xml for relevant URLs."""
    relevant_urls = []
    parsed = urlparse(base_url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

    html = fetch_page(sitemap_url, session)
    if not html:
        return relevant_urls

    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(html)
        ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

        for url_elem in root.findall('.//sm:loc', ns):
            loc = url_elem.text
            if loc:
                loc_lower = loc.lower()
                if any(kw in loc_lower for kw in SITEMAP_KEYWORDS):
                    relevant_urls.append(loc)
                    if len(relevant_urls) >= MAX_SITEMAP_URLS:
                        break

        # Also try without namespace (some sitemaps don't use it)
        if not relevant_urls:
            for url_elem in root.iter():
                if url_elem.tag.endswith('loc') and url_elem.text:
                    loc = url_elem.text
                    loc_lower = loc.lower()
                    if any(kw in loc_lower for kw in SITEMAP_KEYWORDS):
                        relevant_urls.append(loc)
                        if len(relevant_urls) >= MAX_SITEMAP_URLS:
                            break
    except Exception as e:
        print(f"[sitemap] Error parsing {sitemap_url}: {e}")

    return relevant_urls

def extract_data_from_html(html, url):
    """Extract emails, phones, social media, CNPJ, WhatsApp, and address from HTML."""
    soup = BeautifulSoup(html, 'html.parser')

    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    # Extract emails from text
    text = soup.get_text()
    found_emails = set(re.findall(email_pattern, text))

    # Extract from mailto links
    for tag in soup.find_all('a'):
        href = tag.get('href', '')
        if 'mailto:' in href:
            raw_email = href.replace('mailto:', '').split('?')[0]
            found_emails.add(raw_email)

    # Normalize emails
    emails = []
    for em in found_emails:
        normalized = normalize_email(em)
        if normalized:
            emails.append(normalized)

    # Extract phones
    phones = extract_phones(text)

    # Extract company name
    company_name = extract_company_name(soup, url)

    # Phase 3: Extract social media profiles
    socials = extract_social_media(soup)

    # Phase 3: Extract CNPJ
    cnpjs = extract_cnpj(text)

    # Phase 3: Extract WhatsApp numbers
    whatsapp_numbers = extract_whatsapp(soup, text)

    # Phase 3: Extract address info
    addr_info = extract_address_info(text)

    return {
        'emails': list(set(emails)),
        'phones': phones,
        'company_name': company_name,
        'instagram': socials.get('instagram'),
        'facebook': socials.get('facebook'),
        'linkedin': socials.get('linkedin'),
        'twitter': socials.get('twitter'),
        'youtube': socials.get('youtube'),
        'cnpj': cnpjs[0] if cnpjs else None,
        'whatsapp': whatsapp_numbers[0] if whatsapp_numbers else None,
        'address': addr_info.get('address'),
        'city': addr_info.get('city'),
        'state': addr_info.get('state'),
    }

def deep_crawl_domain(url, session=None):
    """Deep crawl a domain: main page + contact paths + sitemap."""
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    all_emails = set()
    all_phones = set()
    company_name = None
    pages_crawled = []

    # Phase 3: Aggregated new fields (first non-None wins)
    agg = {
        'instagram': None, 'facebook': None, 'linkedin': None,
        'twitter': None, 'youtube': None,
        'cnpj': None, 'whatsapp': None,
        'address': None, 'city': None, 'state': None,
    }

    def merge_data(data):
        """Merge extracted data into aggregated fields."""
        nonlocal company_name
        all_emails.update(data['emails'])
        all_phones.update(data['phones'])
        if not company_name and data.get('company_name'):
            company_name = data['company_name']
        # Merge Phase 3 fields (first non-None wins)
        for key in agg:
            if agg[key] is None and data.get(key):
                agg[key] = data[key]

    # 1. Main page
    html = fetch_page(url, session)
    if html:
        data = extract_data_from_html(html, url)
        merge_data(data)
        pages_crawled.append(url)

    # 2. Contact paths
    for path in CONTACT_PATHS:
        contact_url = base_url + path
        if contact_url in pages_crawled:
            continue
        time.sleep(DELAY_BETWEEN_SUBPAGES)
        html = fetch_page(contact_url, session)
        if html:
            data = extract_data_from_html(html, contact_url)
            merge_data(data)
            pages_crawled.append(contact_url)

    # 3. Sitemap
    sitemap_urls = parse_sitemap(base_url, session)
    for surl in sitemap_urls:
        if surl in pages_crawled:
            continue
        time.sleep(DELAY_BETWEEN_SUBPAGES)
        html = fetch_page(surl, session)
        if html:
            data = extract_data_from_html(html, surl)
            merge_data(data)
            pages_crawled.append(surl)

    return {
        'emails': list(all_emails),
        'phones': list(all_phones),
        'company_name': company_name,
        'website': url,
        'pages_crawled': len(pages_crawled),
        **agg,  # Phase 3: all new fields
    }

# ============= Search Engine Functions =============

class SafetyTracker:
    """Track search engine responses to detect blocking and auto-pause."""

    def __init__(self):
        self.consecutive_errors = 0
        self.total_requests = 0
        self.blocked_count = 0
        self.captcha_count = 0
        self.base_delay = 5  # seconds
        self.max_delay = 120  # seconds
        self.is_paused = False

    def record_success(self):
        self.consecutive_errors = 0
        self.total_requests += 1

    def record_error(self, error_type='generic'):
        self.consecutive_errors += 1
        self.total_requests += 1
        if error_type == 'blocked':
            self.blocked_count += 1
        elif error_type == 'captcha':
            self.captcha_count += 1
        if self.consecutive_errors >= 5:
            self.is_paused = True

    def get_delay(self):
        """Exponential backoff based on consecutive errors."""
        if self.consecutive_errors == 0:
            return self.base_delay
        delay = self.base_delay * (2 ** min(self.consecutive_errors, 6))
        return min(delay, self.max_delay)

    def reset_for_new_city(self):
        """Reset error counters for a new city search (keep blocked/captcha counts but be more lenient)."""
        self.consecutive_errors = 0
        self.is_paused = False

    def should_continue(self):
        """Check if we should keep going or stop."""
        if self.is_paused:
            return False
        if self.blocked_count >= 3:
            return False
        if self.captcha_count >= 2:
            return False
        return True


def is_valid_result_url(url):
    """Check if a search result URL is worth crawling."""
    if not url or not url.startswith('http'):
        return False
    try:
        parsed = urlparse(url)
        domain = parsed.hostname or ''
        domain = domain.lower().replace('www.', '')
        # Skip blocked domains
        for skip in SKIP_DOMAINS:
            if skip in domain:
                return False
        # Skip file URLs
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.zip', '.rar', '.jpg', '.png', '.gif']):
            return False
        return True
    except Exception:
        return False


def search_duckduckgo_api(query, max_results=20, safety=None):
    """Search DuckDuckGo using the official duckduckgo-search library (API-based, no HTML scraping).
    This method uses DDG's JSON API endpoints, which are less likely to be CAPTCHA-blocked."""
    results = []
    try:
        from duckduckgo_search import DDGS
        print(f"[search] DDGS API: buscando '{query}' (max_results={max_results})...")
        with DDGS() as ddgs:
            search_results = list(ddgs.text(query, region='br-pt', max_results=max_results))
        for item in search_results:
            url = item.get('href', '')
            if url and is_valid_result_url(url):
                results.append({'url': url, 'title': item.get('title', '')})
        if safety:
            safety.record_success()
        print(f"[search] DDGS API: {len(results)} resultados validos encontrados")
    except ImportError:
        print("[search] DDGS API: biblioteca duckduckgo-search nao instalada")
    except Exception as e:
        error_str = str(e).lower()
        if 'ratelimit' in error_str or '429' in error_str or 'captcha' in error_str:
            print(f"[search] DDGS API: rate limit/CAPTCHA: {e}")
            if safety:
                safety.record_error('captcha')
        else:
            print(f"[search] DDGS API: erro: {e}")
            if safety:
                safety.record_error('generic')
    return results


def search_duckduckgo(query, max_pages=2, safety=None):
    """Search DuckDuckGo HTML version and extract result URLs."""
    results = []
    url = 'https://html.duckduckgo.com/html/'

    session = http_requests.Session()
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://duckduckgo.com/',
    }

    form_data = {'q': query, 'b': ''}

    for page in range(max_pages):
        try:
            start_time = time.time()

            if page == 0:
                resp = session.post(url, data=form_data, headers=headers, timeout=15)
            else:
                # For next pages, use the "next" form data
                resp = session.post(url, data=form_data, headers=headers, timeout=15)

            duration_ms = int((time.time() - start_time) * 1000)

            if resp.status_code != 200:
                if safety:
                    safety.record_error('blocked' if resp.status_code == 403 else 'generic')
                print(f"[search] DDG page {page+1} returned {resp.status_code}")
                break

            # Check for CAPTCHA - specific markers to avoid false positives
            text_lower = resp.text.lower()
            captcha_markers = ['captcha', '/challenge', 'are you a robot', 'robot check',
                             'unusual traffic', 'automated queries', 'verify you are human',
                             'please verify', 'security check', 'blocked', 'rate limit']
            detected_marker = None
            for marker in captcha_markers:
                if marker in text_lower:
                    detected_marker = marker
                    break
            if detected_marker:
                if safety:
                    safety.record_error('captcha')
                # Log HTML snippet for debugging
                html_snippet = resp.text[:500].replace('\n', ' ')
                print(f"[search] DDG CAPTCHA detected on page {page+1} (marker: '{detected_marker}')")
                print(f"[search] DDG HTML snippet: {html_snippet}")
                break

            soup = BeautifulSoup(resp.text, 'html.parser')

            # Extract result links
            page_results = []
            for link in soup.select('a.result__a'):
                href = link.get('href', '')
                if href and is_valid_result_url(href):
                    title = link.get_text(strip=True)
                    page_results.append({'url': href, 'title': title})

            # Also try alternative selector
            if not page_results:
                for link in soup.select('.result__url'):
                    href = link.get('href', '')
                    if not href:
                        # Try the text content as URL
                        text_url = link.get_text(strip=True)
                        if text_url and not text_url.startswith('http'):
                            text_url = 'https://' + text_url
                        href = text_url
                    if href and is_valid_result_url(href):
                        page_results.append({'url': href, 'title': ''})

            if safety:
                safety.record_success()

            results.extend(page_results)
            print(f"[search] DDG page {page+1}: {len(page_results)} results")

            if not page_results:
                break  # No more results

            # Find next page form data
            next_form = soup.select_one('input[name="dc"]')
            if next_form and page < max_pages - 1:
                form_data = {'q': query, 'dc': next_form.get('value', ''), 's': str((page + 1) * 30)}
                # Delay between search pages
                delay = random.uniform(*SEARCH_DELAY_BETWEEN_PAGES)
                time.sleep(delay)
            else:
                break

        except Exception as e:
            print(f"[search] DDG error page {page+1}: {e}")
            if safety:
                safety.record_error('generic')
            break

    return results


def search_bing(query, max_pages=2, safety=None):
    """Search Bing and extract result URLs (fallback engine)."""
    results = []

    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    }

    for page in range(max_pages):
        try:
            start_time = time.time()
            offset = page * 10
            url = f'https://www.bing.com/search?q={requests_quote(query)}&first={offset + 1}'

            resp = http_requests.get(url, headers=headers, timeout=15)
            duration_ms = int((time.time() - start_time) * 1000)

            if resp.status_code != 200:
                if safety:
                    safety.record_error('blocked' if resp.status_code == 403 else 'generic')
                print(f"[search] Bing page {page+1} returned {resp.status_code}")
                break

            # Check for CAPTCHA - specific markers to avoid false positives
            text_lower = resp.text.lower()
            bing_captcha_markers = ['captcha', '/challenge', 'unusual traffic', 'verify you are human',
                                   'automated queries', 'bot detection', 'blocked']
            detected_marker = None
            for marker in bing_captcha_markers:
                if marker in text_lower:
                    detected_marker = marker
                    break
            if detected_marker:
                if safety:
                    safety.record_error('captcha')
                html_snippet = resp.text[:500].replace('\n', ' ')
                print(f"[search] Bing CAPTCHA detected on page {page+1} (marker: '{detected_marker}')")
                print(f"[search] Bing HTML snippet: {html_snippet}")
                break

            soup = BeautifulSoup(resp.text, 'html.parser')

            page_results = []
            for item in soup.select('li.b_algo h2 a'):
                href = item.get('href', '')
                if href and is_valid_result_url(href):
                    title = item.get_text(strip=True)
                    page_results.append({'url': href, 'title': title})

            if safety:
                safety.record_success()

            results.extend(page_results)
            print(f"[search] Bing page {page+1}: {len(page_results)} results")

            if not page_results:
                break

            if page < max_pages - 1:
                delay = random.uniform(*SEARCH_DELAY_BETWEEN_PAGES)
                time.sleep(delay)

        except Exception as e:
            print(f"[search] Bing error page {page+1}: {e}")
            if safety:
                safety.record_error('generic')
            break

    return results


# ============= Official Search APIs (no CAPTCHA!) =============

def search_bing_api(query, api_key, max_results=10):
    """Search using official Bing Web Search API v7 - no CAPTCHA, 1000/month free!"""
    url = 'https://api.bing.microsoft.com/v7.0/search'
    headers = {'Ocp-Apim-Subscription-Key': api_key}
    params = {
        'q': query,
        'count': min(max_results, 50),
        'mkt': 'pt-BR',
        'responseFilter': 'Webpages',
    }
    try:
        start = time.time()
        print(f"[bing_api] REQUEST: GET {url}?q={query[:50]}...&count={params['count']}")
        resp = http_requests.get(url, headers=headers, params=params, timeout=15)
        duration = int((time.time() - start) * 1000)
        print(f"[bing_api] RESPONSE: status={resp.status_code}, duration={duration}ms, body_size={len(resp.text)}")

        if resp.status_code == 401:
            print(f"[bing_api] ERRO: Chave invalida ou expirada (401)")
            return [], 'invalid_key', duration
        if resp.status_code == 403:
            print(f"[bing_api] ERRO: Cota excedida ou acesso negado (403)")
            return [], 'quota_exceeded', duration
        if resp.status_code == 429:
            print(f"[bing_api] ERRO: Rate limited (429)")
            return [], 'rate_limited', duration
        if resp.status_code != 200:
            print(f"[bing_api] ERRO: HTTP {resp.status_code}")
            return [], f'http_{resp.status_code}', duration

        data = resp.json()
        results = []
        for page in data.get('webPages', {}).get('value', []):
            result_url = page.get('url', '')
            if result_url and is_valid_result_url(result_url):
                results.append({'url': result_url, 'title': page.get('name', '')})

        print(f"[bing_api] RESULTADO: {len(results)} URLs validas encontradas")
        for r in results[:3]:
            print(f"[bing_api]   -> {r['url']}")
        return results, None, duration
    except Exception as e:
        print(f"[bing_api] EXCECAO: {e}")
        return [], str(e)[:200], 0


def search_google_custom(query, api_key, cx, max_results=10):
    """Search using Google Custom Search API - no CAPTCHA, 100/day free!"""
    url = 'https://www.googleapis.com/customsearch/v1'
    params = {
        'key': api_key,
        'cx': cx,
        'q': query,
        'num': min(max_results, 10),
        'lr': 'lang_pt',
        'gl': 'br',
    }
    try:
        start = time.time()
        print(f"[google_cse] REQUEST: GET customsearch?q={query[:50]}...&num={params['num']}")
        resp = http_requests.get(url, params=params, timeout=15)
        duration = int((time.time() - start) * 1000)
        print(f"[google_cse] RESPONSE: status={resp.status_code}, duration={duration}ms, body_size={len(resp.text)}")

        if resp.status_code == 400:
            err_msg = resp.json().get('error', {}).get('message', '')
            print(f"[google_cse] ERRO: Bad request - {err_msg[:200]}")
            return [], f'bad_request: {err_msg[:100]}', duration
        if resp.status_code == 401 or resp.status_code == 403:
            print(f"[google_cse] ERRO: Chave invalida ou API nao habilitada ({resp.status_code})")
            return [], 'invalid_key', duration
        if resp.status_code == 429:
            print(f"[google_cse] ERRO: Cota diaria excedida (429)")
            return [], 'quota_exceeded', duration
        if resp.status_code != 200:
            print(f"[google_cse] ERRO: HTTP {resp.status_code}")
            return [], f'http_{resp.status_code}', duration

        data = resp.json()
        results = []
        for item in data.get('items', []):
            result_url = item.get('link', '')
            if result_url and is_valid_result_url(result_url):
                results.append({'url': result_url, 'title': item.get('title', '')})

        print(f"[google_cse] RESULTADO: {len(results)} URLs validas encontradas")
        for r in results[:3]:
            print(f"[google_cse]   -> {r['url']}")
        return results, None, duration
    except Exception as e:
        print(f"[google_cse] EXCECAO: {e}")
        return [], str(e)[:200], 0


# ============= Directory Scraping (BR Directories) =============

def scrape_guiamais(niche, city, state, session=None):
    """Scrape GuiaMais.com.br directory for business listings."""
    leads = []
    domains = set()
    import unicodedata
    def slugify(text):
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
        return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

    city_slug = slugify(city)
    state_slug = state.upper()
    niche_slug = slugify(niche)
    url = f'https://www.guiamais.com.br/busca/{niche_slug}+em+{city_slug}-{state_slug}'
    print(f"[guiamais] Buscando: {url}")

    try:
        s = session or http_requests.Session()
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'pt-BR,pt;q=0.9',
        }
        resp = s.get(url, headers=headers, timeout=15)
        print(f"[guiamais] Response: status={resp.status_code}, size={len(resp.text)}")
        if resp.status_code != 200:
            return leads, domains

        soup = BeautifulSoup(resp.text, 'html.parser')

        # Try multiple selectors for GuiaMais listing items
        items = soup.select('.companyItem') or soup.select('.result-item') or soup.select('.listing-item') or soup.select('[itemtype*="LocalBusiness"]')

        for item in items:
            lead = {}
            # Company name
            name_el = item.select_one('h2 a, h3 a, .companyName, .company-name, [itemprop="name"]')
            if name_el:
                lead['company_name'] = name_el.get_text(strip=True)
            # Phone
            phone_el = item.select_one('.phone, .tel, [itemprop="telephone"], a[href^="tel:"]')
            if phone_el:
                phone_text = phone_el.get_text(strip=True) or phone_el.get('href', '').replace('tel:', '')
                if phone_text:
                    lead['phone'] = re.sub(r'[^\d\+\(\)\-\s]', '', phone_text).strip()
            # Address
            addr_el = item.select_one('.address, .endereco, [itemprop="address"]')
            if addr_el:
                lead['address'] = addr_el.get_text(strip=True)
            # Website
            for a_tag in item.select('a[href]'):
                href = a_tag.get('href', '')
                if href and 'http' in href and 'guiamais' not in href:
                    lead['website'] = href
                    try:
                        d = urlparse(href).hostname
                        if d:
                            domains.add(d.replace('www.', ''))
                    except Exception:
                        pass
                    break

            if lead.get('company_name') or lead.get('phone'):
                lead['city'] = city
                lead['state'] = state
                lead['source'] = 'guiamais'
                leads.append(lead)

        print(f"[guiamais] Encontrou {len(leads)} empresas, {len(domains)} dominios")
    except Exception as e:
        print(f"[guiamais] Erro: {e}")

    return leads, domains


def scrape_telelistas(niche, city, state, session=None):
    """Scrape TeleListas.net directory for business listings."""
    leads = []
    domains = set()
    import unicodedata
    def slugify(text):
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
        return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

    city_slug = slugify(city)
    state_slug = state.upper()
    niche_slug = niche.lower().replace(' ', '+')
    url = f'https://www.telelistas.net/busca/{state_slug}/{city_slug}/{niche_slug}'
    print(f"[telelistas] Buscando: {url}")

    try:
        s = session or http_requests.Session()
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'pt-BR,pt;q=0.9',
        }
        resp = s.get(url, headers=headers, timeout=15)
        print(f"[telelistas] Response: status={resp.status_code}, size={len(resp.text)}")
        if resp.status_code != 200:
            return leads, domains

        soup = BeautifulSoup(resp.text, 'html.parser')

        items = soup.select('.result-item') or soup.select('.listing-item') or soup.select('.company-card') or soup.select('article.listing') or soup.select('[itemtype*="LocalBusiness"]')

        for item in items:
            lead = {}
            name_el = item.select_one('h2, h3, .company-name, .title, [itemprop="name"]')
            if name_el:
                lead['company_name'] = name_el.get_text(strip=True)
            phone_el = item.select_one('.phone, .tel, [itemprop="telephone"], a[href^="tel:"]')
            if phone_el:
                phone_text = phone_el.get_text(strip=True) or phone_el.get('href', '').replace('tel:', '')
                if phone_text:
                    lead['phone'] = re.sub(r'[^\d\+\(\)\-\s]', '', phone_text).strip()
            addr_el = item.select_one('.address, .endereco, [itemprop="address"]')
            if addr_el:
                lead['address'] = addr_el.get_text(strip=True)
            for a_tag in item.select('a[href]'):
                href = a_tag.get('href', '')
                if href and 'http' in href and 'telelistas' not in href:
                    lead['website'] = href
                    try:
                        d = urlparse(href).hostname
                        if d:
                            domains.add(d.replace('www.', ''))
                    except Exception:
                        pass
                    break

            if lead.get('company_name') or lead.get('phone'):
                lead['city'] = city
                lead['state'] = state
                lead['source'] = 'telelistas'
                leads.append(lead)

        print(f"[telelistas] Encontrou {len(leads)} empresas, {len(domains)} dominios")
    except Exception as e:
        print(f"[telelistas] Erro: {e}")

    return leads, domains


def scrape_apontador(niche, city, state, session=None):
    """Scrape Apontador.com.br directory for business listings."""
    leads = []
    domains = set()
    import unicodedata
    def slugify(text):
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
        return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

    city_slug = slugify(city)
    state_slug = state.lower()
    niche_slug = slugify(niche)
    url = f'https://www.apontador.com.br/local/{state_slug}/{city_slug}/{niche_slug}.html'
    print(f"[apontador] Buscando: {url}")

    try:
        s = session or http_requests.Session()
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'pt-BR,pt;q=0.9',
        }
        resp = s.get(url, headers=headers, timeout=15)
        print(f"[apontador] Response: status={resp.status_code}, size={len(resp.text)}")
        if resp.status_code != 200:
            return leads, domains

        soup = BeautifulSoup(resp.text, 'html.parser')

        items = soup.select('.card') or soup.select('.listing') or soup.select('.result-item') or soup.select('.place-card') or soup.select('[itemtype*="LocalBusiness"]')

        for item in items:
            lead = {}
            name_el = item.select_one('h2, h3, .place-name, .title, [itemprop="name"]')
            if name_el:
                lead['company_name'] = name_el.get_text(strip=True)
            phone_el = item.select_one('.phone, .tel, [itemprop="telephone"], a[href^="tel:"]')
            if phone_el:
                phone_text = phone_el.get_text(strip=True) or phone_el.get('href', '').replace('tel:', '')
                if phone_text:
                    lead['phone'] = re.sub(r'[^\d\+\(\)\-\s]', '', phone_text).strip()
            addr_el = item.select_one('.address, .endereco, [itemprop="address"], .place-address')
            if addr_el:
                lead['address'] = addr_el.get_text(strip=True)
            for a_tag in item.select('a[href]'):
                href = a_tag.get('href', '')
                if href and 'http' in href and 'apontador' not in href:
                    lead['website'] = href
                    try:
                        d = urlparse(href).hostname
                        if d:
                            domains.add(d.replace('www.', ''))
                    except Exception:
                        pass
                    break

            if lead.get('company_name') or lead.get('phone'):
                lead['city'] = city
                lead['state'] = state
                lead['source'] = 'apontador'
                leads.append(lead)

        print(f"[apontador] Encontrou {len(leads)} empresas, {len(domains)} dominios")
    except Exception as e:
        print(f"[apontador] Erro: {e}")

    return leads, domains


def scrape_all_directories(niche, city, state, session=None):
    """Scrape all BR directories and merge results."""
    all_leads = []
    all_domains = set()

    for scraper_fn, name in [
        (scrape_guiamais, 'GuiaMais'),
        (scrape_telelistas, 'TeleListas'),
        (scrape_apontador, 'Apontador'),
    ]:
        try:
            leads, domains = scraper_fn(niche, city, state, session)
            all_leads.extend(leads)
            all_domains.update(domains)
            if leads:
                print(f"[diretorios] {name}: {len(leads)} empresas encontradas!")
            # Small delay between directories
            time.sleep(random.uniform(1, 2))
        except Exception as e:
            print(f"[diretorios] Erro em {name}: {e}")

    # Deduplicate leads by company name
    seen_names = set()
    unique_leads = []
    for lead in all_leads:
        name_key = (lead.get('company_name', '') or '').lower().strip()
        if name_key and name_key not in seen_names:
            seen_names.add(name_key)
            unique_leads.append(lead)
        elif not name_key:
            unique_leads.append(lead)

    print(f"[diretorios] TOTAL: {len(unique_leads)} empresas unicas, {len(all_domains)} dominios de {len(all_leads)} resultados brutos")
    return unique_leads, all_domains


# ============= Multi-Source Search with Fallback =============

def search_with_fallback(query, max_pages=2, safety=None, cursor=None, user_id=None, search_job_id=None):
    """Multi-source domain search with detailed logging.
    Priority: Bing API (oficial) -> Google CSE -> DDG scraping -> Bing scraping"""
    engine_used = 'duckduckgo'
    results = []

    print(f"\n[WEBSEARCH] Iniciando busca web multi-fonte para: '{query}'")

    # 1. Try Bing Web Search API (official, no CAPTCHA, 1000/month)
    if not results and cursor and user_id:
        bing_config = get_api_config(cursor, user_id, 'bing_api')
        if bing_config:
            bing_credits = get_api_credits_remaining(cursor, user_id, 'bing_api')
            if bing_credits > 0:
                print(f"[WEBSEARCH] Fonte 1: Bing API oficial ({bing_credits} creditos restantes)...")
                api_results, error, duration = search_bing_api(query, bing_config['api_key'], max_results=max_pages * 10)
                if api_results:
                    record_api_usage(cursor, user_id, 'bing_api', 1)
                    engine_used = 'bing_api'
                    results = api_results
                    print(f"[WEBSEARCH] Bing API: {len(results)} resultados em {duration}ms!")
                    if search_job_id:
                        log_search(cursor, search_job_id, 'search_ok',
                                  message=f'Bing API oficial achou {len(results)} resultados em {duration}ms! Sem CAPTCHA!',
                                  duration_ms=duration)
                elif error == 'invalid_key':
                    cursor.execute('UPDATE api_configs SET is_active = FALSE WHERE user_id = %s AND provider = %s',
                                  (user_id, 'bing_api'))
                    print(f"[WEBSEARCH] Bing API: chave invalida! Desativada.")
                    if search_job_id:
                        log_search(cursor, search_job_id, 'api_error',
                                  message=f'Bing API: chave invalida, desativada automaticamente')
                elif error:
                    print(f"[WEBSEARCH] Bing API falhou: {error}")
                    if search_job_id:
                        log_search(cursor, search_job_id, 'api_error',
                                  message=f'Bing API falhou: {error}')
            else:
                print(f"[WEBSEARCH] Bing API: sem creditos restantes")
        else:
            print(f"[WEBSEARCH] Bing API: nao configurada")

    # 2. Try Google Custom Search API (no CAPTCHA, 100/day)
    if not results and cursor and user_id:
        google_config = get_api_config(cursor, user_id, 'google_cse')
        if google_config and google_config.get('api_secret'):
            google_credits = get_api_credits_remaining(cursor, user_id, 'google_cse')
            if google_credits > 0:
                print(f"[WEBSEARCH] Fonte 2: Google Custom Search ({google_credits} creditos restantes)...")
                api_results, error, duration = search_google_custom(
                    query, google_config['api_key'], google_config['api_secret'], max_results=10)
                if api_results:
                    record_api_usage(cursor, user_id, 'google_cse', 1)
                    engine_used = 'google_cse'
                    results = api_results
                    print(f"[WEBSEARCH] Google CSE: {len(results)} resultados em {duration}ms!")
                    if search_job_id:
                        log_search(cursor, search_job_id, 'search_ok',
                                  message=f'Google Custom Search achou {len(results)} resultados em {duration}ms!',
                                  duration_ms=duration)
                elif error == 'invalid_key':
                    cursor.execute('UPDATE api_configs SET is_active = FALSE WHERE user_id = %s AND provider = %s',
                                  (user_id, 'google_cse'))
                    print(f"[WEBSEARCH] Google CSE: chave invalida! Desativada.")
                    if search_job_id:
                        log_search(cursor, search_job_id, 'api_error',
                                  message=f'Google CSE: chave/cx invalida, desativada automaticamente')
                elif error:
                    print(f"[WEBSEARCH] Google CSE falhou: {error}")
                    if search_job_id:
                        log_search(cursor, search_job_id, 'api_error',
                                  message=f'Google CSE falhou: {error}')
            else:
                print(f"[WEBSEARCH] Google CSE: sem creditos restantes hoje")
        else:
            print(f"[WEBSEARCH] Google CSE: nao configurada")

    # 3. DDG API (duckduckgo-search library - API JSON, sem HTML scraping)
    if not results:
        print(f"[WEBSEARCH] Fonte 3: DuckDuckGo API (biblioteca duckduckgo-search)...")
        if search_job_id and cursor:
            log_search(cursor, search_job_id, 'search_attempt',
                      message=f'APIs oficiais falharam/nao configuradas. Tentando DDG API (biblioteca)...')
        results = search_duckduckgo_api(query, max_results=max_pages * 10, safety=safety)
        if results:
            engine_used = 'ddgs_api'
            print(f"[WEBSEARCH] DDG API: {len(results)} URLs encontradas!")
            if search_job_id and cursor:
                log_search(cursor, search_job_id, 'search_ok',
                          message=f'DDG API (biblioteca) achou {len(results)} resultados!')
        else:
            print(f"[WEBSEARCH] DDG API: sem resultados")

    # 4. DDG HTML scraping fallback
    if not results:
        print(f"[WEBSEARCH] Fonte 4: DuckDuckGo HTML scraping (max_pages={max_pages})...")
        if search_job_id and cursor:
            log_search(cursor, search_job_id, 'search_attempt',
                      message=f'DDG API falhou. Tentando DDG HTML scraping...')
        results = search_duckduckgo(query, max_pages, safety)
        engine_used = 'duckduckgo'
        print(f"[WEBSEARCH] DDG scraping resultado: {len(results)} URLs encontradas")

    # 5. Bing scraping fallback
    if not results:
        delay = random.uniform(3, 6)
        print(f"[WEBSEARCH] Fonte 5: Bing scraping (esperando {delay:.1f}s)...")
        if search_job_id and cursor:
            log_search(cursor, search_job_id, 'search_attempt',
                      message=f'Todas as fontes anteriores falharam. Ultima tentativa: Bing scraping...')
        engine_used = 'bing'
        time.sleep(delay)
        results = search_bing(query, max_pages, safety)
        print(f"[WEBSEARCH] Bing scraping resultado: {len(results)} URLs encontradas")

    # Deduplicate by domain
    seen_domains = set()
    unique_results = []
    for r in results:
        try:
            domain = urlparse(r['url']).hostname.replace('www.', '')
            if domain not in seen_domains:
                seen_domains.add(domain)
                unique_results.append(r)
        except Exception:
            unique_results.append(r)

    return unique_results, engine_used


def calculate_quality_score(lead_data):
    """Calculate lead quality: basico, medio, or premium."""
    score = 0
    if lead_data.get('email'):
        score += 1
    if lead_data.get('phone'):
        score += 1
    if lead_data.get('whatsapp'):
        score += 1
    if lead_data.get('instagram') or lead_data.get('facebook') or lead_data.get('linkedin'):
        score += 1
    if lead_data.get('cnpj'):
        score += 1

    if score >= 4:
        return 'premium'
    elif score >= 2:
        return 'medio'
    return 'basico'


def log_search(conn_cursor, search_job_id, log_type, url=None, status_code=None, message='', duration_ms=0):
    """Insert a search log entry."""
    try:
        conn_cursor.execute(
            '''INSERT INTO search_logs (search_job_id, log_type, url, status_code, message, duration_ms, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s)''',
            (search_job_id, log_type, url, status_code, message[:500] if message else '', duration_ms, datetime.now())
        )
    except Exception as e:
        print(f"[search_log] Error: {e}")


def process_search_job(batch_id, search_jobs_data, user_id):
    """Background thread: run search queries, deep-crawl results, save leads."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True

    try:
        c = conn.cursor()
        c.execute('UPDATE batches SET status = %s, started_at = %s WHERE id = %s',
                  ('processing', datetime.now(), batch_id))

        safety = SafetyTracker()
        session = http_requests.Session()
        total_leads_found = 0

        for job_idx, job_data in enumerate(search_jobs_data):
            search_job_id = job_data['search_job_id']
            niche = job_data['niche']
            city = job_data['city']
            state = job_data['state']
            max_pages = job_data.get('max_pages', 2)

            # Update search job status
            query = f'{niche} {city} {state}'
            c.execute('UPDATE search_jobs SET status = %s, started_at = %s, query = %s WHERE id = %s',
                      ('processing', datetime.now(), query, search_job_id))

            log_search(c, search_job_id, 'start', message=f'Buscando: {query}')

            if not safety.should_continue():
                c.execute('UPDATE search_jobs SET status = %s, error_message = %s, finished_at = %s WHERE id = %s',
                          ('paused', 'Anti-blocking safety pause', datetime.now(), search_job_id))
                log_search(c, search_job_id, 'safety_pause', message='Pausa de seguranca ativada')
                continue

            try:
                # Search
                start_time = time.time()
                results, engine_used = search_with_fallback(query, max_pages, safety)
                search_duration = int((time.time() - start_time) * 1000)

                c.execute('UPDATE search_jobs SET engine = %s, total_results = %s WHERE id = %s',
                          (engine_used, len(results), search_job_id))

                log_search(c, search_job_id, 'search_complete',
                          message=f'{engine_used}: {len(results)} resultados em {search_duration}ms',
                          duration_ms=search_duration)

                # Deep-crawl each result
                job_leads = 0
                for i, result in enumerate(results):
                    if not safety.should_continue():
                        log_search(c, search_job_id, 'safety_pause', message='Pausa durante crawl')
                        break

                    result_url = result['url']
                    log_search(c, search_job_id, 'crawl_start', url=result_url,
                              message=f'Crawling {i+1}/{len(results)}')

                    try:
                        crawl_start = time.time()
                        crawl_data = deep_crawl_domain(result_url, session)
                        crawl_duration = int((time.time() - crawl_start) * 1000)

                        # Calculate quality
                        quality = calculate_quality_score(crawl_data)

                        # Override city/state from search query if not found on page
                        if not crawl_data.get('city'):
                            crawl_data['city'] = city
                        if not crawl_data.get('state'):
                            crawl_data['state'] = state

                        # Save leads
                        now = datetime.now()
                        first_phone = crawl_data['phones'][0] if crawl_data['phones'] else None

                        if crawl_data['emails']:
                            for email in crawl_data['emails']:
                                try:
                                    # Calcular quality score baseado no email
                                    email_score, _, _ = calculate_email_quality_score(email)
                                    # Usar categorias antigas para compatibilidade
                                    if email_score >= 70:
                                        quality = 'premium'
                                    elif email_score >= 50:
                                        quality = 'medio'
                                    else:
                                        quality = 'basico'

                                    c.execute(
                                        '''INSERT INTO leads
                                           (batch_id, company_name, email, phone, website, source_url, source,
                                            instagram, facebook, linkedin, twitter, youtube,
                                            whatsapp, cnpj, address, city, state, category,
                                            quality_score, extracted_at)
                                           VALUES (%s, %s, %s, %s, %s, %s, %s,
                                                   %s, %s, %s, %s, %s,
                                                   %s, %s, %s, %s, %s, %s,
                                                   %s, %s)
                                           ON CONFLICT (batch_id, email) DO NOTHING''',
                                        (batch_id, crawl_data['company_name'], email, first_phone,
                                         crawl_data['website'], result_url, 'search_engine',
                                         crawl_data.get('instagram'), crawl_data.get('facebook'),
                                         crawl_data.get('linkedin'), crawl_data.get('twitter'), crawl_data.get('youtube'),
                                         crawl_data.get('whatsapp'), crawl_data.get('cnpj'),
                                         crawl_data.get('address'), crawl_data.get('city'), crawl_data.get('state'),
                                         niche, quality, now)
                                    )
                                    job_leads += 1
                                    print(f"[search] Lead inserido: {email} (quality: {quality}, score: {email_score})")
                                except Exception as e:
                                    print(f"[search] Lead insert error: {e}")

                        log_search(c, search_job_id, 'crawl_complete', url=result_url,
                                  message=f'{len(crawl_data["emails"])} emails, {len(crawl_data["phones"])} phones, quality={quality}',
                                  duration_ms=crawl_duration)

                        safety.record_success()

                    except Exception as e:
                        log_search(c, search_job_id, 'crawl_error', url=result_url,
                                  message=str(e)[:200])
                        safety.record_error('generic')

                    # Update progress
                    c.execute('UPDATE search_jobs SET processed_results = %s WHERE id = %s',
                              (i + 1, search_job_id))

                    # Delay between sites
                    if i < len(results) - 1:
                        delay = random.uniform(*SEARCH_DELAY_BETWEEN_SITES)
                        time.sleep(delay)

                # Finalize search job
                c.execute('SELECT COUNT(*) FROM leads WHERE batch_id = %s', (batch_id,))
                total_leads_found = c.fetchone()[0]

                c.execute('UPDATE search_jobs SET status = %s, total_leads = %s, finished_at = %s WHERE id = %s',
                          ('completed', job_leads, datetime.now(), search_job_id))

                log_search(c, search_job_id, 'complete',
                          message=f'{job_leads} leads encontrados para {city}/{state}')

            except Exception as e:
                print(f"[search] Error in search job {search_job_id}: {e}")
                c.execute('UPDATE search_jobs SET status = %s, error_message = %s, finished_at = %s WHERE id = %s',
                          ('failed', str(e)[:500], datetime.now(), search_job_id))
                log_search(c, search_job_id, 'error', message=str(e)[:200])

            # Update batch progress
            c.execute('UPDATE batches SET processed_urls = %s, total_leads = %s WHERE id = %s',
                      (job_idx + 1, total_leads_found, batch_id))

            # Delay between cities
            if job_idx < len(search_jobs_data) - 1:
                delay = random.uniform(*SEARCH_DELAY_BETWEEN_CITIES)
                time.sleep(delay)

        # Final batch update
        c.execute('SELECT COUNT(*) FROM leads WHERE batch_id = %s', (batch_id,))
        final_count = c.fetchone()[0]
        c.execute('UPDATE batches SET status = %s, total_leads = %s, finished_at = %s WHERE id = %s',
                  ('completed', final_count, datetime.now(), batch_id))

    except Exception as e:
        print(f"[search] Fatal error batch {batch_id}: {e}")
        try:
            c = conn.cursor()
            c.execute('UPDATE batches SET status = %s, finished_at = %s WHERE id = %s',
                      ('failed', datetime.now(), batch_id))
        except Exception:
            pass
    finally:
        conn.close()

# ============= API Search Background Job =============

def process_api_search_job(batch_id, search_jobs_data, user_id):
    """Background thread: search for domains -> enrich via API -> fallback to scraping.
    Now with SUPER detailed logging for every step!"""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n{'='*60}")
    print(f"[JOB] Iniciando busca API! batch={batch_id}, cidades={len(search_jobs_data)}")
    print(f"{'='*60}")

    try:
        c = conn.cursor()
        c.execute('UPDATE batches SET status = %s, started_at = %s WHERE id = %s',
                  ('processing', datetime.now(), batch_id))

        # Log API config status upfront
        provider_names = {'bing_api': 'Bing API (busca)', 'google_cse': 'Google CSE (busca)',
                         'hunter': 'Hunter.io (emails)', 'snov': 'Snov.io (emails)'}
        for prov in ('bing_api', 'google_cse', 'hunter', 'snov'):
            cfg = get_api_config(c, user_id, prov)
            credits = get_api_credits_remaining(c, user_id, prov) if cfg else 0
            prov_label = provider_names.get(prov, prov)
            status = f"ativa, {credits} creditos restantes" if cfg else "NAO configurada"
            print(f"[JOB] {prov_label}: {status}")
            log_search(c, search_jobs_data[0]['search_job_id'], 'config_check',
                      message=f'{prov_label}: {status}')
        log_search(c, search_jobs_data[0]['search_job_id'], 'config_check',
                  message=f'Diretorios BR (GuiaMais, TeleListas, Apontador): sempre ativo, sem limites!')

        session = http_requests.Session()
        total_leads_found = 0

        for job_idx, job_data in enumerate(search_jobs_data):
            search_job_id = job_data['search_job_id']
            niche = job_data['niche']
            city = job_data['city']
            state = job_data['state']
            max_pages = job_data.get('max_pages', 2)

            query = f'{niche} {city} {state}'
            print(f"\n{'─'*50}")
            print(f"[CIDADE {job_idx+1}/{len(search_jobs_data)}] {city}/{state} - query: '{query}'")
            print(f"{'─'*50}")
            c.execute('UPDATE search_jobs SET status = %s, started_at = %s, query = %s WHERE id = %s',
                      ('processing', datetime.now(), query, search_job_id))
            log_search(c, search_job_id, 'start',
                      message=f'Partiu! Buscando "{niche}" em {city}/{state} (max {max_pages} pags)')

            # Fresh safety tracker per city
            safety = SafetyTracker()

            try:
                job_leads = 0
                job_source = 'scraping'

                # ─── Phase 0: Directory Scraping (GuiaMais, TeleListas, Apontador) ───
                log_search(c, search_job_id, 'phase0',
                          message=f'FASE 0: Vasculhando diretorios BR (GuiaMais, TeleListas, Apontador) para "{niche}" em {city}/{state}...')
                print(f"\n[FASE 0] Scraping de diretorios BR para {niche} em {city}/{state}")

                dir_start = time.time()
                dir_leads, dir_domains = scrape_all_directories(niche, city, state, session)
                dir_duration = int((time.time() - dir_start) * 1000)

                dir_saved = 0
                if dir_leads:
                    now = datetime.now()
                    for dl in dir_leads:
                        # Save directory leads (they may not have email but have phone/company)
                        email = normalize_email(dl.get('email', '')) if dl.get('email') else None
                        phone = dl.get('phone') or None
                        company = dl.get('company_name') or ''
                        website = dl.get('website') or None
                        if not email and not phone:
                            continue

                        # For leads without email, create a placeholder using phone as dedup
                        dedup_email = email or f"phone_{re.sub(r'[^0-9]', '', phone or '')}@directory.local"
                        lead_data = {'email': email or '', 'phone': phone or '', 'company_name': company,
                                    'whatsapp': phone}
                        quality = calculate_quality_score(lead_data)
                        try:
                            c.execute(
                                '''INSERT INTO leads
                                   (batch_id, company_name, email, phone, website, source_url, source,
                                    address, city, state, category, quality_score, extracted_at)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s,
                                           %s, %s, %s, %s, %s, %s)
                                   ON CONFLICT (batch_id, email) DO NOTHING''',
                                (batch_id, company, dedup_email, phone, website,
                                 website or '', f'diretorio_{dl.get("source", "br")}',
                                 dl.get('address'), city, state, niche, quality, now)
                            )
                            dir_saved += 1
                            job_leads += 1
                        except Exception as e:
                            print(f"[SAVE] Erro salvando lead de diretorio: {e}")

                log_search(c, search_job_id, 'dir_done',
                          message=f'Diretorios BR: {len(dir_leads)} empresas encontradas, {dir_saved} salvas, {len(dir_domains)} dominios descobertos ({dir_duration}ms)',
                          duration_ms=dir_duration)
                print(f"[FASE 0] Diretorios: {len(dir_leads)} empresas, {dir_saved} salvas, {len(dir_domains)} dominios")

                # ─── Phase 1: Domain Discovery via Web Search (multi-source) ───
                log_search(c, search_job_id, 'phase1',
                          message=f'FASE 1: Cacando mais dominios via Bing API/Google CSE/DDG/Bing para "{query}"...')

                start_time = time.time()
                results, engine_used = search_with_fallback(query, max_pages, safety,
                                                            cursor=c, user_id=user_id, search_job_id=search_job_id)
                search_duration = int((time.time() - start_time) * 1000)

                # Merge directory domains into search results
                for dd in dir_domains:
                    already_has = any(dd in (urlparse(r['url']).hostname or '').replace('www.', '') for r in results)
                    if not already_has:
                        results.append({'url': f'https://{dd}', 'title': f'(diretorio: {dd})'})

                c.execute('UPDATE search_jobs SET engine = %s, total_results = %s WHERE id = %s',
                          (engine_used, len(results), search_job_id))

                if results:
                    domains_found = [urlparse(r['url']).hostname for r in results if urlparse(r['url']).hostname]
                    log_search(c, search_job_id, 'search_ok',
                              message=f'Boa! {engine_used} + diretorios = {len(results)} dominios em {search_duration}ms: {", ".join(domains_found[:5])}{"..." if len(domains_found) > 5 else ""}',
                              duration_ms=search_duration)
                    print(f"[BUSCA] {engine_used} + diretorios = {len(results)} resultados em {search_duration}ms")
                    for r in results[:5]:
                        print(f"[BUSCA]   -> {r['url']}")
                else:
                    if dir_saved > 0:
                        log_search(c, search_job_id, 'search_partial',
                                  message=f'Busca web retornou 0, mas diretorios ja salvaram {dir_saved} leads! Continuando...',
                                  duration_ms=search_duration)
                    else:
                        log_search(c, search_job_id, 'search_blocked',
                                  message=f'Todas as fontes falharam para {city}! Busca web: 0 resultados, diretorios: 0 empresas.',
                                  duration_ms=search_duration)
                    print(f"[BUSCA] Sem dominios encontrados.")

                # ─── Phase 2: Enrich via API (Hunter/Snov) + Scraping Fallback ───
                if results:
                    log_search(c, search_job_id, 'phase2',
                              message=f'FASE 2: Enriquecendo {len(results)} dominios via Hunter.io / Snov.io...')

                for i, result in enumerate(results):
                    result_url = result['url']
                    domain = urlparse(result_url).hostname
                    if domain:
                        domain = domain.replace('www.', '')

                    print(f"\n[DOMINIO {i+1}/{len(results)}] {domain}")
                    log_search(c, search_job_id, 'domain_start', url=result_url,
                              message=f'[{i+1}/{len(results)}] Investigando {domain}...')

                    # Try API enrichment first
                    api_leads, source = enrich_domain_with_fallback(c, domain, user_id, search_job_id)

                    if api_leads:
                        # Save API-sourced leads
                        if source in ('hunter', 'snov'):
                            job_source = f'api_{source}'
                        elif '_cache' in source:
                            job_source = f'api_{source.replace("_cache", "")}'
                        now = datetime.now()
                        org_name = ''
                        for prov in ('hunter', 'snov'):
                            cached = check_api_cache(c, domain, prov)
                            if cached and cached.get('organization'):
                                org_name = cached['organization']
                                break

                        saved_count = 0
                        for api_lead in api_leads:
                            email = normalize_email(api_lead.get('email', ''))
                            if not email:
                                continue
                            contact_name = ' '.join(filter(None, [
                                api_lead.get('first_name', ''),
                                api_lead.get('last_name', '')
                            ])).strip()
                            phone = api_lead.get('phone', '') or ''
                            company = org_name or derive_company_name(email)

                            # Intelligent contact name extraction
                            if not contact_name:
                                contact_name = derive_contact_name(email)

                            lead_data = {'email': email, 'phone': phone, 'company_name': company}
                            quality = calculate_quality_score(lead_data)
                            try:
                                c.execute(
                                    '''INSERT INTO leads
                                       (batch_id, company_name, email, phone, website, source_url, source,
                                        city, state, category, contact_name, quality_score,
                                        extra_data, extracted_at)
                                       VALUES (%s, %s, %s, %s, %s, %s, %s,
                                               %s, %s, %s, %s, %s, %s, %s)
                                       ON CONFLICT (batch_id, email) DO NOTHING''',
                                    (batch_id, company, email, phone or None,
                                     f'https://{domain}', result_url, job_source,
                                     city, state, niche, contact_name or None, quality,
                                     json.dumps({'position': api_lead.get('position', ''),
                                                 'confidence': api_lead.get('confidence', 0),
                                                 'source_api': source}),
                                     now)
                                )
                                saved_count += 1
                                job_leads += 1
                            except Exception as e:
                                print(f"[SAVE] Erro ao salvar lead: {e}")

                        log_search(c, search_job_id, 'leads_saved', url=result_url,
                                  message=f'Salvos {saved_count} leads de {domain} via {source}! (org: {org_name or "N/A"})')
                        print(f"[SAVE] {saved_count} leads salvos de {domain}")

                    else:
                        # Fallback: deep crawl (scraping)
                        log_search(c, search_job_id, 'scrape_fallback', url=result_url,
                                  message=f'APIs nao acharam emails em {domain}. Tentando scraping direto...')

                        if not safety.should_continue():
                            log_search(c, search_job_id, 'safety_pause', url=result_url,
                                      message=f'Scraping pausado por seguranca (muitos erros). Pulando {domain}')
                        else:
                            try:
                                crawl_start = time.time()
                                crawl_data = deep_crawl_domain(result_url, session)
                                crawl_duration = int((time.time() - crawl_start) * 1000)

                                quality = calculate_quality_score(crawl_data)
                                if not crawl_data.get('city'):
                                    crawl_data['city'] = city
                                if not crawl_data.get('state'):
                                    crawl_data['state'] = state

                                now = datetime.now()
                                first_phone = crawl_data['phones'][0] if crawl_data['phones'] else None
                                emails_found = crawl_data.get('emails', [])

                                if emails_found:
                                    for email in emails_found:
                                        try:
                                            # Calcular quality score baseado no email
                                            email_score, _, _ = calculate_email_quality_score(email)
                                            if email_score >= 70:
                                                quality = 'premium'
                                            elif email_score >= 50:
                                                quality = 'medio'
                                            else:
                                                quality = 'basico'

                                            c.execute(
                                                '''INSERT INTO leads
                                                   (batch_id, company_name, email, phone, website, source_url, source,
                                                    instagram, facebook, linkedin, twitter, youtube,
                                                    whatsapp, cnpj, address, city, state, category,
                                                    quality_score, extracted_at)
                                                   VALUES (%s, %s, %s, %s, %s, %s, %s,
                                                           %s, %s, %s, %s, %s,
                                                           %s, %s, %s, %s, %s, %s,
                                                           %s, %s)
                                                   ON CONFLICT (batch_id, email) DO NOTHING''',
                                                (batch_id, crawl_data['company_name'], email, first_phone,
                                                 crawl_data['website'], result_url, 'search_engine',
                                                 crawl_data.get('instagram'), crawl_data.get('facebook'),
                                                 crawl_data.get('linkedin'), crawl_data.get('twitter'),
                                                 crawl_data.get('youtube'), crawl_data.get('whatsapp'),
                                                 crawl_data.get('cnpj'), crawl_data.get('address'),
                                                 crawl_data.get('city'), crawl_data.get('state'),
                                                 niche, quality, now)
                                            )
                                            job_leads += 1
                                        except Exception as e:
                                            print(f"[SAVE] Erro scrape lead: {e}")

                                log_search(c, search_job_id, 'scrape_done', url=result_url,
                                          message=f'Scraping de {domain}: {len(emails_found)} emails, empresa="{crawl_data.get("company_name", "?")}", quality={quality} ({crawl_duration}ms)',
                                          duration_ms=crawl_duration)
                                safety.record_success()

                            except Exception as e:
                                log_search(c, search_job_id, 'scrape_error', url=result_url,
                                          message=f'Scraping falhou em {domain}: {str(e)[:150]}')
                                safety.record_error('generic')

                    # Update progress
                    c.execute('UPDATE search_jobs SET processed_results = %s WHERE id = %s',
                              (i + 1, search_job_id))

                    # Delay between domains
                    if i < len(results) - 1:
                        if source in ('hunter', 'snov', 'hunter_cache', 'snov_cache'):
                            delay = random.uniform(0.5, 1.5)
                        else:
                            delay = random.uniform(*SEARCH_DELAY_BETWEEN_SITES)
                        time.sleep(delay)

                # ─── Finalize search job ───
                c.execute('SELECT COUNT(*) FROM leads WHERE batch_id = %s', (batch_id,))
                total_leads_found = c.fetchone()[0]

                c.execute('UPDATE search_jobs SET status = %s, total_leads = %s, finished_at = %s, enrichment_source = %s WHERE id = %s',
                          ('completed', job_leads, datetime.now(), job_source, search_job_id))

                sources_used = []
                if dir_saved > 0:
                    sources_used.append(f'diretorios({dir_saved})')
                if job_source != 'scraping':
                    sources_used.append(job_source)
                if not sources_used:
                    sources_used.append('scraping')
                source_str = ' + '.join(sources_used)

                summary_msg = f'Fim! {city}/{state}: {job_leads} leads via {source_str}'
                if job_leads == 0 and not results and dir_saved == 0:
                    summary_msg = f'Fim! {city}/{state}: 0 leads (todas as fontes falharam - configure Bing API ou Google CSE!)'
                elif job_leads == 0 and results:
                    summary_msg = f'Fim! {city}/{state}: 0 leads ({len(results)} dominios testados, nenhum tinha emails)'
                elif job_leads > 0:
                    summary_msg = f'Fim! {city}/{state}: {job_leads} leads encontrados! Fontes: {source_str}'
                log_search(c, search_job_id, 'complete', message=summary_msg)
                print(f"[FIM] {summary_msg}")

            except Exception as e:
                print(f"[ERRO] Falha na cidade {city}: {e}")
                import traceback
                traceback.print_exc()
                c.execute('UPDATE search_jobs SET status = %s, error_message = %s, finished_at = %s WHERE id = %s',
                          ('failed', str(e)[:500], datetime.now(), search_job_id))
                log_search(c, search_job_id, 'error', message=f'Erro fatal em {city}: {str(e)[:200]}')

            # Update batch progress
            c.execute('UPDATE batches SET processed_urls = %s, total_leads = %s WHERE id = %s',
                      (job_idx + 1, total_leads_found, batch_id))

            # Delay between cities
            if job_idx < len(search_jobs_data) - 1:
                delay = random.uniform(*SEARCH_DELAY_BETWEEN_CITIES)
                print(f"[DELAY] Esperando {delay:.1f}s antes da proxima cidade...")
                time.sleep(delay)

        # Final batch update
        c.execute('SELECT COUNT(*) FROM leads WHERE batch_id = %s', (batch_id,))
        final_count = c.fetchone()[0]
        c.execute('UPDATE batches SET status = %s, total_leads = %s, finished_at = %s WHERE id = %s',
                  ('completed', final_count, datetime.now(), batch_id))
        print(f"\n{'='*60}")
        print(f"[JOB] CONCLUIDO! batch={batch_id}, total_leads={final_count}")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"[FATAL] Erro fatal no batch {batch_id}: {e}")
        import traceback
        traceback.print_exc()
        try:
            c = conn.cursor()
            c.execute('UPDATE batches SET status = %s, finished_at = %s WHERE id = %s',
                      ('failed', datetime.now(), batch_id))
        except Exception:
            pass
    finally:
        conn.close()


# ============= Background Batch Worker =============

def process_batch(batch_id, urls):
    """Process batch of URLs in background thread."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True

    try:
        c = conn.cursor()
        c.execute('UPDATE batches SET status = %s, started_at = %s WHERE id = %s',
                  ('processing', datetime.now(), batch_id))

        session = http_requests.Session()

        for i, url in enumerate(urls):
            try:
                # Normalize URL
                if not url.startswith('http'):
                    url = 'https://' + url

                # Deep crawl
                result = deep_crawl_domain(url, session)

                # Insert leads for each email found
                now = datetime.now()
                first_phone = result['phones'][0] if result['phones'] else None

                for email in result['emails']:
                    c.execute(
                        '''INSERT INTO leads
                           (batch_id, company_name, email, phone, website, source_url, source,
                            instagram, facebook, linkedin, twitter, youtube,
                            whatsapp, cnpj, address, city, state, extracted_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s,
                                   %s, %s, %s, %s, %s,
                                   %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (batch_id, email) DO NOTHING''',
                        (batch_id, result['company_name'], email, first_phone,
                         result['website'], url, 'website_crawl',
                         result.get('instagram'), result.get('facebook'),
                         result.get('linkedin'), result.get('twitter'), result.get('youtube'),
                         result.get('whatsapp'), result.get('cnpj'),
                         result.get('address'), result.get('city'), result.get('state'), now)
                    )

                # If no emails but phones found, still record the company
                if not result['emails'] and (result['phones'] or result['company_name']):
                    # Insert a placeholder lead without email (won't conflict on UNIQUE)
                    pass  # Skip - leads require email for dedup

                # Update progress
                c.execute('SELECT COUNT(*) FROM leads WHERE batch_id = %s', (batch_id,))
                lead_count = c.fetchone()[0]
                c.execute(
                    'UPDATE batches SET processed_urls = %s, total_leads = %s WHERE id = %s',
                    (i + 1, lead_count, batch_id)
                )

            except Exception as e:
                print(f"[batch {batch_id}] Error processing {url}: {e}")
                # Update progress even on error
                c.execute(
                    'UPDATE batches SET processed_urls = %s WHERE id = %s',
                    (i + 1, batch_id)
                )

            # Delay between domains
            if i < len(urls) - 1:
                time.sleep(DELAY_BETWEEN_DOMAINS)

        # Final count and status
        c.execute('SELECT COUNT(*) FROM leads WHERE batch_id = %s', (batch_id,))
        final_count = c.fetchone()[0]
        c.execute(
            'UPDATE batches SET status = %s, total_leads = %s, finished_at = %s WHERE id = %s',
            ('completed', final_count, datetime.now(), batch_id)
        )

    except Exception as e:
        print(f"[batch {batch_id}] Fatal error: {e}")
        try:
            c = conn.cursor()
            c.execute('UPDATE batches SET status = %s, finished_at = %s WHERE id = %s',
                      ('failed', datetime.now(), batch_id))
        except Exception:
            pass
    finally:
        conn.close()

# ============= API Routes =============

@app.route('/api/health', methods=['GET'])
@limiter.limit("60/minute")
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat(), 'db': 'postgresql'})

@app.route('/api/login', methods=['POST'])
@limiter.limit("5/minute")
def login():
    """Login endpoint"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT id, password_hash, is_admin FROM users WHERE username = %s', (username,))
        user = c.fetchone()

    if not user or hash_password(password) != user[1]:
        return jsonify({'error': 'Invalid credentials'}), 401

    token = create_session(user[0])
    return jsonify({'token': token, 'user_id': user[0], 'is_admin': user[2]})

@app.route('/api/scrape', methods=['POST'])
@limiter.limit("10/hour")
def start_scrape():
    """Start scraping job (single URL, synchronous)"""
    token = get_auth_header()
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    url = data.get('url') if data else None

    if not url:
        return jsonify({'error': 'URL required'}), 400

    # Create job
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'INSERT INTO jobs (user_id, url, status, results_count, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id',
            (user_id, url, 'pending', 0, datetime.now())
        )
        job_id = c.fetchone()[0]

    # Start scraping
    try:
        emails = scrape_emails_from_url(url)

        with get_db() as conn:
            c = conn.cursor()
            now = datetime.now()
            c.execute(
                'UPDATE jobs SET status = %s, results_count = %s, started_at = %s, finished_at = %s WHERE id = %s',
                ('completed', len(emails), now, now, job_id)
            )

            for email_data in emails:
                normalized = normalize_email(email_data['email'])
                if normalized:
                    c.execute(
                        'INSERT INTO emails (job_id, email, source_url, extracted_at) VALUES (%s, %s, %s, %s) ON CONFLICT (job_id, email) DO NOTHING',
                        (job_id, normalized, email_data['url'], now)
                    )

            c.execute('SELECT COUNT(*) FROM emails WHERE job_id = %s', (job_id,))
            actual_count = c.fetchone()[0]
            c.execute('UPDATE jobs SET results_count = %s WHERE id = %s', (actual_count, job_id))

    except Exception as e:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('UPDATE jobs SET status = %s, finished_at = %s WHERE id = %s', ('failed', datetime.now(), job_id))
        return jsonify({'error': str(e)}), 500

    return jsonify({'job_id': job_id, 'status': 'completed', 'results_count': actual_count})

@app.route('/api/results/<int:job_id>', methods=['GET'])
@limiter.limit("30/minute")
def get_results(job_id):
    """Get scraping results"""
    token = get_auth_header()
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()

        c.execute('SELECT id, user_id, url, status, results_count, created_at, started_at, finished_at FROM jobs WHERE id = %s AND user_id = %s', (job_id, user_id))
        job = c.fetchone()

        if not job:
            return jsonify({'error': 'Job not found'}), 404

        c.execute('SELECT email, source_url, extracted_at FROM emails WHERE job_id = %s ORDER BY email', (job_id,))
        emails = c.fetchall()

    return jsonify({
        'job_id': job_id,
        'url': job[2],
        'status': job[3],
        'results_count': job[4],
        'created_at': job[5].isoformat() if job[5] else None,
        'emails': [{'email': e[0], 'source_url': e[1], 'extracted_at': e[2].isoformat() if e[2] else None} for e in emails]
    })

@app.route('/api/results/<int:job_id>/export', methods=['GET'])
@limiter.limit("20/minute")
def export_results_csv(job_id):
    """Export scraping results as CSV"""
    token = get_auth_header()
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()

        c.execute('SELECT id FROM jobs WHERE id = %s AND user_id = %s', (job_id, user_id))
        if not c.fetchone():
            return jsonify({'error': 'Job not found'}), 404

        c.execute('SELECT email, source_url, extracted_at FROM emails WHERE job_id = %s ORDER BY email', (job_id,))
        emails = c.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Email', 'URL Origem', 'Data Extracao'])
    for e in emails:
        writer.writerow([e[0], e[1], e[2].isoformat() if e[2] else ''])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=emails_{job_id}.csv'}
    )

@app.route('/api/results', methods=['GET'])
@limiter.limit("30/minute")
def list_results():
    """List all scraping jobs for user"""
    token = get_auth_header()
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'SELECT id, url, status, results_count, created_at FROM jobs WHERE user_id = %s ORDER BY created_at DESC',
            (user_id,)
        )
        jobs = c.fetchall()

    return jsonify({
        'jobs': [{'id': j[0], 'url': j[1], 'status': j[2], 'results_count': j[3], 'created_at': j[4].isoformat() if j[4] else None} for j in jobs]
    })

# ============= Batch API Routes =============

@app.route('/api/batch', methods=['POST'])
@limiter.limit("5/hour")
def create_batch():
    """Create and start a batch scraping job."""
    token = get_auth_header()
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    name = data.get('name', '').strip()
    raw_urls = data.get('urls', [])

    if not name:
        return jsonify({'error': 'Batch name required'}), 400

    if not raw_urls or not isinstance(raw_urls, list):
        return jsonify({'error': 'URLs array required'}), 400

    # Parse URLs: accept strings or {"website": "..."} objects
    urls = []
    for item in raw_urls:
        if isinstance(item, str):
            url = item.strip()
        elif isinstance(item, dict):
            url = (item.get('website') or item.get('url') or '').strip()
        else:
            continue
        if url:
            if not url.startswith('http'):
                url = 'https://' + url
            urls.append(url)

    if not urls:
        return jsonify({'error': 'No valid URLs found'}), 400

    if len(urls) > 500:
        return jsonify({'error': 'Maximum 500 URLs per batch'}), 400

    # Create batch record
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'INSERT INTO batches (user_id, name, status, total_urls, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id',
            (user_id, name, 'pending', len(urls), datetime.now())
        )
        batch_id = c.fetchone()[0]

    # Start background processing
    thread = threading.Thread(target=process_batch, args=(batch_id, urls), daemon=True)
    thread.start()

    # AUTO-SYNC: Start background thread to sync leads to alexandrequeiroz.com.br
    sync_thread = threading.Thread(target=auto_sync_new_leads_background, args=(batch_id,), daemon=True)
    sync_thread.start()

    return jsonify({
        'batch_id': batch_id,
        'name': name,
        'total_urls': len(urls),
        'status': 'processing',
    })

@app.route('/api/batch', methods=['GET'])
@limiter.limit("30/minute")
def list_batches():
    """List all batches for user."""
    token = get_auth_header()
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            '''SELECT id, name, status, total_urls, processed_urls, total_leads, created_at
               FROM batches WHERE user_id = %s ORDER BY created_at DESC''',
            (user_id,)
        )
        batches = c.fetchall()

    return jsonify({
        'batches': [{
            'id': b[0], 'name': b[1], 'status': b[2],
            'total_urls': b[3], 'processed_urls': b[4], 'total_leads': b[5],
            'created_at': b[6].isoformat() if b[6] else None,
        } for b in batches]
    })

@app.route('/api/batch/<int:batch_id>', methods=['GET'])
@limiter.limit("30/minute")
def get_batch(batch_id):
    """Get batch details with all leads."""
    token = get_auth_header()
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()

        c.execute(
            '''SELECT id, name, status, total_urls, processed_urls, total_leads, created_at, started_at, finished_at
               FROM batches WHERE id = %s AND user_id = %s''',
            (batch_id, user_id)
        )
        batch = c.fetchone()

        if not batch:
            return jsonify({'error': 'Batch not found'}), 404

        c.execute(
            '''SELECT company_name, email, phone, website, source_url, city, state, category, extracted_at,
                      instagram, facebook, linkedin, twitter, youtube, whatsapp, cnpj, address
               FROM leads WHERE batch_id = %s ORDER BY company_name, email''',
            (batch_id,)
        )
        leads = c.fetchall()

    return jsonify({
        'batch_id': batch[0],
        'name': batch[1],
        'status': batch[2],
        'total_urls': batch[3],
        'processed_urls': batch[4],
        'total_leads': batch[5],
        'created_at': batch[6].isoformat() if batch[6] else None,
        'started_at': batch[7].isoformat() if batch[7] else None,
        'finished_at': batch[8].isoformat() if batch[8] else None,
        'leads': [{
            'company_name': l[0], 'email': l[1], 'phone': l[2],
            'website': l[3], 'source_url': l[4],
            'city': l[5], 'state': l[6], 'category': l[7],
            'extracted_at': l[8].isoformat() if l[8] else None,
            'instagram': l[9], 'facebook': l[10], 'linkedin': l[11],
            'twitter': l[12], 'youtube': l[13], 'whatsapp': l[14],
            'cnpj': l[15], 'address': l[16],
        } for l in leads]
    })

@app.route('/api/batch/<int:batch_id>/progress', methods=['GET'])
@limiter.limit("60/minute")
def batch_progress(batch_id):
    """Lightweight polling endpoint for batch progress."""
    token = get_auth_header()
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'SELECT status, total_urls, processed_urls, total_leads FROM batches WHERE id = %s AND user_id = %s',
            (batch_id, user_id)
        )
        batch = c.fetchone()

    if not batch:
        return jsonify({'error': 'Batch not found'}), 404

    return jsonify({
        'status': batch[0],
        'total_urls': batch[1],
        'processed_urls': batch[2],
        'total_leads': batch[3],
    })

@app.route('/api/batch/<int:batch_id>/export', methods=['GET'])
@limiter.limit("20/minute")
def export_batch(batch_id):
    """Export batch leads in CSV, JSON, or text format."""
    token = get_auth_header()
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    fmt = request.args.get('format', 'csv')

    with get_db() as conn:
        c = conn.cursor()

        c.execute('SELECT id, name FROM batches WHERE id = %s AND user_id = %s', (batch_id, user_id))
        batch = c.fetchone()
        if not batch:
            return jsonify({'error': 'Batch not found'}), 404

        c.execute(
            '''SELECT company_name, email, phone, website, source_url, city, state, category, extracted_at,
                      instagram, facebook, linkedin, twitter, youtube, whatsapp, cnpj, address
               FROM leads WHERE batch_id = %s ORDER BY company_name, email''',
            (batch_id,)
        )
        leads = c.fetchall()

    batch_name = batch[1] or f'batch_{batch_id}'

    if fmt == 'json':
        leads_json = [{
            'company_name': l[0] or '', 'email': l[1] or '', 'phone': l[2] or '',
            'website': l[3] or '', 'source_url': l[4] or '',
            'city': l[5] or '', 'state': l[6] or '', 'category': l[7] or '',
            'extracted_at': l[8].isoformat() if l[8] else '',
            'instagram': l[9] or '', 'facebook': l[10] or '', 'linkedin': l[11] or '',
            'twitter': l[12] or '', 'youtube': l[13] or '',
            'whatsapp': l[14] or '', 'cnpj': l[15] or '', 'address': l[16] or '',
        } for l in leads]
        return Response(
            json.dumps(leads_json, ensure_ascii=False, indent=2),
            mimetype='application/json',
            headers={'Content-Disposition': f'attachment; filename={batch_name}.json'}
        )

    elif fmt == 'text':
        lines = []
        for l in leads:
            parts = [l[1] or '']  # email
            if l[2]:
                parts.append(l[2])  # phone
            if l[0]:
                parts.append(l[0])  # company
            if l[14]:
                parts.append(f'WA:{l[14]}')  # whatsapp
            lines.append(' | '.join(parts))
        return Response(
            '\n'.join(lines),
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename={batch_name}.txt'}
        )

    else:  # csv (default)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Empresa', 'Email', 'Telefone', 'WhatsApp', 'CNPJ',
                          'Instagram', 'Facebook', 'LinkedIn', 'Twitter', 'YouTube',
                          'Endereco', 'Cidade', 'Estado', 'Website', 'Origem', 'Tags'])
        for l in leads:
            writer.writerow([
                l[0] or '',   # company_name
                l[1] or '',   # email
                l[2] or '',   # phone
                l[14] or '',  # whatsapp
                l[15] or '',  # cnpj
                l[9] or '',   # instagram
                l[10] or '',  # facebook
                l[11] or '',  # linkedin
                l[12] or '',  # twitter
                l[13] or '',  # youtube
                l[16] or '',  # address
                l[5] or '',   # city
                l[6] or '',   # state
                l[3] or '',   # website
                l[4] or '',   # source_url
                l[7] or '',   # category as Tags
            ])
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={batch_name}.csv'}
        )

# ============= Search API Routes =============

@app.route('/api/regions', methods=['GET'])
@limiter.limit("60/minute")
def get_regions():
    """Get pre-configured search regions."""
    regions = []
    for key, data in SEARCH_REGIONS.items():
        regions.append({
            'id': key,
            'name': data['name'],
            'state': data['state'],
            'cities': data['cities'],
        })
    return jsonify({'regions': regions})


@app.route('/api/search', methods=['POST'])
@limiter.limit("3/hour")
def start_search():
    """Start a search engine scraping job."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    niche = (data.get('niche') or '').strip()
    region_id = (data.get('region') or '').strip()
    city = (data.get('city') or '').strip()
    state = (data.get('state') or '').strip()
    max_pages = min(3, max(1, int(data.get('max_pages', 2))))

    if not niche:
        return jsonify({'error': 'Nicho obrigatorio'}), 400

    # Build cities list
    cities_to_search = []
    if region_id and region_id in SEARCH_REGIONS:
        region_data = SEARCH_REGIONS[region_id]
        for c_name in region_data['cities']:
            cities_to_search.append({
                'city': c_name,
                'state': region_data['state'],
                'region': region_id,
            })
    elif city and state:
        cities_to_search.append({
            'city': city,
            'state': state,
            'region': 'manual',
        })
    else:
        return jsonify({'error': 'Selecione uma regiao ou informe cidade/estado'}), 400

    # Create batch
    batch_name = f'Busca: {niche}'
    if region_id and region_id in SEARCH_REGIONS:
        batch_name += f' - {SEARCH_REGIONS[region_id]["name"]}'
    elif city:
        batch_name += f' - {city}/{state}'

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'INSERT INTO batches (user_id, name, status, total_urls, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id',
            (user_id, batch_name, 'pending', len(cities_to_search), datetime.now())
        )
        batch_id = c.fetchone()[0]

        # Create search jobs for each city
        search_jobs_data = []
        for city_data in cities_to_search:
            c.execute(
                '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                (batch_id, user_id, niche, city_data['city'], city_data['state'],
                 city_data['region'], max_pages, 'pending', datetime.now())
            )
            search_job_id = c.fetchone()[0]
            search_jobs_data.append({
                'search_job_id': search_job_id,
                'niche': niche,
                'city': city_data['city'],
                'state': city_data['state'],
                'max_pages': max_pages,
            })

    # Start background processing
    thread = threading.Thread(
        target=process_search_job,
        args=(batch_id, search_jobs_data, user_id),
        daemon=True
    )
    thread.start()

    # AUTO-SYNC: Start background thread to sync leads to alexandrequeiroz.com.br
    sync_thread = threading.Thread(target=auto_sync_new_leads_background, args=(batch_id,), daemon=True)
    sync_thread.start()

    return jsonify({
        'batch_id': batch_id,
        'name': batch_name,
        'total_cities': len(cities_to_search),
        'status': 'processing',
        'search_type': 'region' if region_id else 'manual',
    })


@app.route('/api/search/<int:batch_id>/progress', methods=['GET'])
@limiter.limit("60/minute")
def search_progress(batch_id):
    """Get search progress with per-city sub-jobs."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()

        # Get batch info
        c.execute(
            'SELECT status, total_urls, processed_urls, total_leads, name FROM batches WHERE id = %s AND user_id = %s',
            (batch_id, user_id)
        )
        batch = c.fetchone()
        if not batch:
            return jsonify({'error': 'Batch not found'}), 404

        # Get search sub-jobs
        c.execute(
            '''SELECT id, city, state, engine, status, total_results, processed_results, total_leads,
                      started_at, finished_at, error_message, enrichment_source
               FROM search_jobs WHERE batch_id = %s ORDER BY id''',
            (batch_id,)
        )
        jobs = c.fetchall()

    sub_jobs = []
    for j in jobs:
        sub_jobs.append({
            'id': j[0], 'city': j[1], 'state': j[2], 'engine': j[3] or '',
            'status': j[4], 'total_results': j[5], 'processed_results': j[6],
            'total_leads': j[7],
            'started_at': j[8].isoformat() if j[8] else None,
            'finished_at': j[9].isoformat() if j[9] else None,
            'error_message': j[10],
            'enrichment_source': j[11] if len(j) > 11 else None,
        })

    return jsonify({
        'status': batch[0],
        'total_cities': batch[1],
        'processed_cities': batch[2],
        'total_leads': batch[3],
        'name': batch[4],
        'search_jobs': sub_jobs,
        'is_search': len(sub_jobs) > 0,
    })


@app.route('/api/search/<int:batch_id>/logs', methods=['GET'])
@limiter.limit("30/minute")
def search_logs(batch_id):
    """Get search execution logs."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()

        # Verify ownership
        c.execute('SELECT id FROM batches WHERE id = %s AND user_id = %s', (batch_id, user_id))
        if not c.fetchone():
            return jsonify({'error': 'Batch not found'}), 404

        # Get logs from all search jobs in this batch (increased limit, chronological order)
        c.execute(
            '''SELECT sl.id, sl.log_type, sl.url, sl.status_code, sl.message, sl.duration_ms, sl.created_at,
                      sj.city, sj.state
               FROM search_logs sl
               JOIN search_jobs sj ON sl.search_job_id = sj.id
               WHERE sj.batch_id = %s
               ORDER BY sl.created_at ASC
               LIMIT 500''',
            (batch_id,)
        )
        logs = c.fetchall()

    return jsonify({
        'logs': [{
            'id': l[0], 'type': l[1], 'url': l[2], 'status_code': l[3],
            'message': l[4], 'duration_ms': l[5],
            'created_at': l[6].isoformat() if l[6] else None,
            'city': l[7], 'state': l[8],
        } for l in logs]
    })


# ============= Advanced Scraping API Routes =============

@app.route('/api/scrape/google-maps', methods=['POST'])
@limiter.limit("5/hour")
def scrape_google_maps_endpoint():
    """Scrape Google Maps para buscar empresas locais."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    niche = (data.get('niche') or '').strip()
    city = (data.get('city') or '').strip()
    state = (data.get('state') or '').strip()
    max_results = min(50, max(10, int(data.get('max_results', 20))))

    if not niche or not city or not state:
        return jsonify({'error': 'Nicho, cidade e estado são obrigatórios'}), 400

    # Criar batch
    with get_db() as conn:
        c = conn.cursor()
        batch_name = f"Google Maps: {niche} em {city}, {state}"
        c.execute(
            '''INSERT INTO batches (user_id, name, status, total_urls, processed_urls, total_leads, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (user_id, batch_name, 'processing', max_results, 0, 0, datetime.now())
        )
        batch_id = c.fetchone()[0]

    # Executar scraping em thread
    def run_google_maps_scraping():
        with get_db() as conn:
            c = conn.cursor()
            try:
                leads = scrape_google_maps(niche, city, state, max_results)

                # Salvar leads
                for lead in leads:
                    try:
                        email = lead.get('email')
                        if email:
                            email_score, is_valid, _ = calculate_email_quality_score(email)
                            if not is_valid or email_score < 40:
                                continue

                        c.execute(
                            '''INSERT INTO leads (batch_id, company_name, email, phone, website, address,
                                                  city, state, source, source_url, quality_score, extracted_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                               ON CONFLICT (batch_id, email) DO NOTHING''',
                            (batch_id, lead.get('company_name'), lead.get('email'), lead.get('phone'),
                             lead.get('website'), lead.get('address'), city, state,
                             'google_maps', lead.get('website') or f"maps:{lead.get('company_name')}",
                             lead.get('rating') or 'medio', datetime.now())
                        )
                    except Exception as e:
                        print(f"[GoogleMaps] Erro ao inserir lead: {e}")

                # Atualizar batch
                c.execute(
                    '''UPDATE batches SET status = %s, processed_urls = %s, total_leads = %s
                       WHERE id = %s''',
                    ('completed', max_results, len(leads), batch_id)
                )

            except Exception as e:
                print(f"[GoogleMaps] Erro no scraping: {e}")
                c.execute('UPDATE batches SET status = %s WHERE id = %s', ('failed', batch_id))

    thread = threading.Thread(target=run_google_maps_scraping, daemon=True)
    thread.start()

    return jsonify({'batch_id': batch_id, 'message': 'Google Maps scraping iniciado'})


@app.route('/api/scrape/instagram', methods=['POST'])
@limiter.limit("3/hour")
def scrape_instagram_endpoint():
    """Scrape Instagram para buscar perfis de negócios."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    niche = (data.get('niche') or '').strip()
    city = (data.get('city') or '').strip()
    state = (data.get('state') or '').strip()
    max_results = min(100, max(20, int(data.get('max_results', 50))))

    if not niche or not city or not state:
        return jsonify({'error': 'Nicho, cidade e estado são obrigatórios'}), 400

    # Criar batch
    with get_db() as conn:
        c = conn.cursor()
        batch_name = f"Instagram: {niche} em {city}, {state}"
        c.execute(
            '''INSERT INTO batches (user_id, name, status, total_urls, processed_urls, total_leads, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (user_id, batch_name, 'processing', max_results, 0, 0, datetime.now())
        )
        batch_id = c.fetchone()[0]

    # Executar scraping em thread
    def run_instagram_scraping():
        with get_db() as conn:
            c = conn.cursor()
            try:
                leads = scrape_instagram_business(niche, city, state, max_results)

                # Salvar leads
                for lead in leads:
                    try:
                        email = lead.get('email')
                        if email:
                            email_score, is_valid, _ = calculate_email_quality_score(email)
                            if not is_valid or email_score < 40:
                                email = None  # Não bloquear lead, apenas limpar email inválido

                        c.execute(
                            '''INSERT INTO leads (batch_id, company_name, email, phone, website, instagram,
                                                  city, state, source, source_url, quality_score, extracted_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                               ON CONFLICT (batch_id, email) DO NOTHING''',
                            (batch_id, lead.get('company_name'), email, lead.get('phone'),
                             lead.get('website'), lead.get('instagram'), city, state,
                             'instagram', lead.get('instagram'), 'medio', datetime.now())
                        )
                    except Exception as e:
                        print(f"[Instagram] Erro ao inserir lead: {e}")

                # Atualizar batch
                c.execute(
                    '''UPDATE batches SET status = %s, processed_urls = %s, total_leads = %s
                       WHERE id = %s''',
                    ('completed', max_results, len(leads), batch_id)
                )

            except Exception as e:
                print(f"[Instagram] Erro no scraping: {e}")
                c.execute('UPDATE batches SET status = %s WHERE id = %s', ('failed', batch_id))

    thread = threading.Thread(target=run_instagram_scraping, daemon=True)
    thread.start()

    return jsonify({'batch_id': batch_id, 'message': 'Instagram scraping iniciado'})


@app.route('/api/scrape/linkedin', methods=['POST'])
@limiter.limit("2/hour")
def scrape_linkedin_endpoint():
    """Scrape LinkedIn para buscar empresas (uso com cuidado - anti-scraping forte)."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    niche = (data.get('niche') or '').strip()
    city = (data.get('city') or '').strip()
    state = (data.get('state') or '').strip()
    max_results = min(50, max(10, int(data.get('max_results', 30))))

    if not niche or not city or not state:
        return jsonify({'error': 'Nicho, cidade e estado são obrigatórios'}), 400

    # Criar batch
    with get_db() as conn:
        c = conn.cursor()
        batch_name = f"LinkedIn: {niche} em {city}, {state}"
        c.execute(
            '''INSERT INTO batches (user_id, name, status, total_urls, processed_urls, total_leads, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (user_id, batch_name, 'processing', max_results, 0, 0, datetime.now())
        )
        batch_id = c.fetchone()[0]

    # Executar scraping em thread
    def run_linkedin_scraping():
        with get_db() as conn:
            c = conn.cursor()
            try:
                leads = scrape_linkedin_companies(niche, city, state, max_results)

                # Salvar leads
                for lead in leads:
                    try:
                        c.execute(
                            '''INSERT INTO leads (batch_id, company_name, linkedin, address,
                                                  city, state, source, source_url, quality_score, extracted_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                               ON CONFLICT (batch_id, email) DO NOTHING''',
                            (batch_id, lead.get('company_name'), lead.get('linkedin'), lead.get('address'),
                             city, state, 'linkedin', lead.get('linkedin'), 'premium', datetime.now())
                        )
                    except Exception as e:
                        print(f"[LinkedIn] Erro ao inserir lead: {e}")

                # Atualizar batch
                c.execute(
                    '''UPDATE batches SET status = %s, processed_urls = %s, total_leads = %s
                       WHERE id = %s''',
                    ('completed', max_results, len(leads), batch_id)
                )

            except Exception as e:
                print(f"[LinkedIn] Erro no scraping: {e}")
                c.execute('UPDATE batches SET status = %s WHERE id = %s', ('failed', batch_id))

    thread = threading.Thread(target=run_linkedin_scraping, daemon=True)
    thread.start()

    return jsonify({'batch_id': batch_id, 'message': 'LinkedIn scraping iniciado (pode demorar)', 'warning': 'LinkedIn tem proteção anti-scraping forte'})


# ============= API Config & Search Endpoints =============

@app.route('/api/api-config', methods=['POST'])
@limiter.limit("10/minute")
def save_api_config_endpoint():
    """Save or update API configuration for a provider."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    provider = (data.get('provider') or '').strip().lower()
    api_key = (data.get('api_key') or '').strip()
    api_secret = (data.get('api_secret') or '').strip()

    if provider not in ('hunter', 'snov', 'bing_api', 'google_cse'):
        return jsonify({'error': 'Provider invalido (hunter, snov, bing_api ou google_cse)'}), 400
    if not api_key:
        return jsonify({'error': 'API key obrigatoria'}), 400
    if provider == 'snov' and not api_secret:
        return jsonify({'error': 'Client Secret obrigatorio para Snov.io'}), 400
    if provider == 'google_cse' and not api_secret:
        return jsonify({'error': 'Search Engine ID (cx) obrigatorio para Google Custom Search'}), 400

    # Validate key
    valid = False
    if provider == 'hunter':
        try:
            resp = http_requests.get(f'https://api.hunter.io/v2/account?api_key={api_key}', timeout=10)
            valid = resp.status_code == 200
        except Exception:
            pass
    elif provider == 'snov':
        token = get_snov_access_token(api_key, api_secret)
        valid = token is not None
    elif provider == 'bing_api':
        try:
            resp = http_requests.get('https://api.bing.microsoft.com/v7.0/search',
                                     headers={'Ocp-Apim-Subscription-Key': api_key},
                                     params={'q': 'test', 'count': 1}, timeout=10)
            valid = resp.status_code == 200
        except Exception:
            pass
    elif provider == 'google_cse':
        try:
            resp = http_requests.get('https://www.googleapis.com/customsearch/v1',
                                     params={'key': api_key, 'cx': api_secret, 'q': 'test', 'num': 1},
                                     timeout=10)
            valid = resp.status_code == 200
        except Exception:
            pass

    if not valid:
        return jsonify({'error': f'Chave de API invalida para {provider}. Verifique as credenciais.'}), 400

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            '''INSERT INTO api_configs (user_id, provider, api_key, api_secret, is_active, created_at, updated_at)
               VALUES (%s, %s, %s, %s, TRUE, %s, %s)
               ON CONFLICT (user_id, provider)
               DO UPDATE SET api_key = %s, api_secret = %s, is_active = TRUE, updated_at = %s''',
            (user_id, provider, api_key, api_secret or None, datetime.now(), datetime.now(),
             api_key, api_secret or None, datetime.now())
        )
    return jsonify({'message': f'Configuracao {provider} salva com sucesso', 'provider': provider, 'valid': True})


@app.route('/api/api-config', methods=['GET'])
@limiter.limit("30/minute")
def get_api_configs_endpoint():
    """Get API configurations and credit usage for the user."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()
        configs = []
        for provider in ('hunter', 'snov', 'bing_api', 'google_cse'):
            # Use daily period for google_cse, monthly for others
            if provider == 'google_cse':
                period = datetime.now().strftime('%Y-%m-%d')
            else:
                period = datetime.now().strftime('%Y-%m')

            c.execute(
                'SELECT api_key, api_secret, is_active, updated_at FROM api_configs WHERE user_id = %s AND provider = %s',
                (user_id, provider)
            )
            config_row = c.fetchone()

            c.execute(
                'SELECT credits_used, credits_limit FROM api_usage WHERE user_id = %s AND provider = %s AND month_year = %s',
                (user_id, provider, period)
            )
            usage_row = c.fetchone()

            limit = API_CREDIT_LIMITS.get(provider, 0)
            configs.append({
                'provider': provider,
                'configured': config_row is not None,
                'is_active': config_row[2] if config_row else False,
                'has_key': bool(config_row[0]) if config_row else False,
                'updated_at': config_row[3].isoformat() if config_row and config_row[3] else None,
                'credits_used': usage_row[0] if usage_row else 0,
                'credits_limit': usage_row[1] if usage_row else limit,
                'credits_remaining': max(0, (usage_row[1] if usage_row else limit) - (usage_row[0] if usage_row else 0)),
                'period': period,
                'period_type': 'daily' if provider == 'google_cse' else 'monthly',
            })

    return jsonify({'configs': configs})


@app.route('/api/api-config/<provider>', methods=['DELETE'])
@limiter.limit("10/minute")
def delete_api_config_endpoint(provider):
    """Remove API config for a provider."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    if provider not in ('hunter', 'snov', 'bing_api', 'google_cse'):
        return jsonify({'error': 'Provider invalido'}), 400

    with get_db() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM api_configs WHERE user_id = %s AND provider = %s', (user_id, provider))

    return jsonify({'message': f'Configuracao {provider} removida'})


@app.route('/api/search-api', methods=['POST'])
@limiter.limit("3/hour")
def start_api_search():
    """Start search + API enrichment job."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    niche = (data.get('niche') or '').strip()
    region_id = (data.get('region') or '').strip()
    city = (data.get('city') or '').strip()
    state = (data.get('state') or '').strip()
    max_pages = min(3, max(1, int(data.get('max_pages', 2))))

    if not niche:
        return jsonify({'error': 'Nicho obrigatorio'}), 400

    # Build cities list
    cities_to_search = []
    if region_id and region_id in SEARCH_REGIONS:
        region_data = SEARCH_REGIONS[region_id]
        for c_name in region_data['cities']:
            cities_to_search.append({'city': c_name, 'state': region_data['state'], 'region': region_id})
    elif city and state:
        cities_to_search.append({'city': city, 'state': state, 'region': 'manual'})
    else:
        return jsonify({'error': 'Selecione uma regiao ou informe cidade/estado'}), 400

    # Check which APIs are configured
    has_apis = False
    api_status = {}
    with get_db() as conn:
        c = conn.cursor()
        for provider in ('bing_api', 'google_cse', 'hunter', 'snov'):
            config = get_api_config(c, user_id, provider)
            if config and get_api_credits_remaining(c, user_id, provider) > 0:
                has_apis = True
                api_status[provider] = True

    batch_name = f'Busca API: {niche}'
    if region_id and region_id in SEARCH_REGIONS:
        batch_name += f' - {SEARCH_REGIONS[region_id]["name"]}'
    elif city:
        batch_name += f' - {city}/{state}'

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'INSERT INTO batches (user_id, name, status, total_urls, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id',
            (user_id, batch_name, 'pending', len(cities_to_search), datetime.now())
        )
        batch_id = c.fetchone()[0]

        search_jobs_data = []
        for city_data in cities_to_search:
            c.execute(
                '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, enrichment_source, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                (batch_id, user_id, niche, city_data['city'], city_data['state'],
                 city_data['region'], max_pages, 'pending', 'api', datetime.now())
            )
            sj_id = c.fetchone()[0]
            search_jobs_data.append({
                'search_job_id': sj_id,
                'niche': niche,
                'city': city_data['city'],
                'state': city_data['state'],
                'max_pages': max_pages,
            })

    thread = threading.Thread(
        target=process_api_search_job,
        args=(batch_id, search_jobs_data, user_id),
        daemon=True
    )
    thread.start()

    # AUTO-SYNC: Start background thread to sync leads
    sync_thread = threading.Thread(target=auto_sync_new_leads_background, args=(batch_id,), daemon=True)
    sync_thread.start()

    return jsonify({
        'batch_id': batch_id,
        'name': batch_name,
        'total_cities': len(cities_to_search),
        'status': 'processing',
        'search_type': 'api',
        'has_api_keys': has_apis,
    })


# ============= CRM API Routes (Phase 4) =============

CRM_STATUSES = ['novo', 'contatado', 'interessado', 'negociando', 'cliente', 'descartado']

LEADS_SELECT = '''SELECT l.id, l.company_name, l.email, l.phone, l.website, l.source_url,
                         l.city, l.state, l.category, l.extracted_at,
                         l.instagram, l.facebook, l.linkedin, l.twitter, l.youtube,
                         l.whatsapp, l.cnpj, l.address,
                         l.crm_status, l.tags, l.notes, l.contact_name, l.updated_at,
                         b.name as batch_name, l.batch_id
                  FROM leads l JOIN batches b ON l.batch_id = b.id
                  WHERE b.user_id = %s'''

def lead_row_to_dict(row):
    """Convert a lead row tuple to dict."""
    return {
        'id': row[0], 'company_name': row[1], 'email': row[2], 'phone': row[3],
        'website': row[4], 'source_url': row[5], 'city': row[6], 'state': row[7],
        'category': row[8], 'extracted_at': row[9].isoformat() if row[9] else None,
        'instagram': row[10], 'facebook': row[11], 'linkedin': row[12],
        'twitter': row[13], 'youtube': row[14], 'whatsapp': row[15],
        'cnpj': row[16], 'address': row[17],
        'crm_status': row[18] or 'novo', 'tags': row[19] or '', 'notes': row[20] or '',
        'contact_name': row[21] or '',
        'updated_at': row[22].isoformat() if row[22] else None,
        'batch_name': row[23], 'batch_id': row[24],
    }

@app.route('/api/leads', methods=['GET'])
@limiter.limit("30/minute")
def list_leads():
    """List all leads with search, filter, sort and pagination."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    # Query params
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '').strip()
    tag = request.args.get('tag', '').strip()
    batch_id = request.args.get('batch_id', '').strip()
    sort = request.args.get('sort', 'newest')
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(100, max(10, int(request.args.get('per_page', 50))))

    query = LEADS_SELECT
    params = [user_id]

    # Filters
    if search:
        query += ''' AND (l.company_name ILIKE %s OR l.email ILIKE %s
                     OR l.phone ILIKE %s OR l.website ILIKE %s
                     OR l.contact_name ILIKE %s OR l.cnpj ILIKE %s OR l.tags ILIKE %s)'''
        like = f'%{search}%'
        params.extend([like, like, like, like, like, like, like])

    if status and status in CRM_STATUSES:
        query += ' AND l.crm_status = %s'
        params.append(status)

    if tag:
        query += ' AND l.tags ILIKE %s'
        params.append(f'%{tag}%')

    if batch_id:
        query += ' AND l.batch_id = %s'
        params.append(int(batch_id))

    # Count total
    count_query = f'SELECT COUNT(*) FROM ({query}) sub'
    with get_db() as conn:
        c = conn.cursor()
        c.execute(count_query, params)
        total = c.fetchone()[0]

        # Sort
        if sort == 'oldest':
            query += ' ORDER BY l.extracted_at ASC'
        elif sort == 'company':
            query += ' ORDER BY l.company_name ASC NULLS LAST'
        elif sort == 'status':
            query += ' ORDER BY l.crm_status ASC, l.company_name ASC'
        elif sort == 'updated':
            query += ' ORDER BY l.updated_at DESC NULLS LAST'
        else:  # newest
            query += ' ORDER BY l.extracted_at DESC'

        # Pagination
        offset = (page - 1) * per_page
        query += ' LIMIT %s OFFSET %s'
        params.extend([per_page, offset])

        c.execute(query, params)
        rows = c.fetchall()

        # Get status counts
        c.execute('''SELECT COALESCE(l.crm_status, 'novo') as status, COUNT(*)
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.user_id = %s
                     GROUP BY COALESCE(l.crm_status, 'novo')''', (user_id,))
        status_counts = {row[0]: row[1] for row in c.fetchall()}

        # Get all unique tags
        c.execute('''SELECT DISTINCT unnest(string_to_array(l.tags, ','))
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.user_id = %s AND l.tags IS NOT NULL AND l.tags != ''
                     ORDER BY 1''', (user_id,))
        all_tags = [row[0].strip() for row in c.fetchall() if row[0].strip()]

    leads = [lead_row_to_dict(row) for row in rows]

    return jsonify({
        'leads': leads,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': max(1, (total + per_page - 1) // per_page),
        'status_counts': status_counts,
        'all_tags': all_tags,
    })

@app.route('/api/leads/<int:lead_id>', methods=['GET'])
@limiter.limit("60/minute")
def get_lead(lead_id):
    """Get single lead details."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()
        c.execute(LEADS_SELECT + ' AND l.id = %s', (user_id, lead_id))
        row = c.fetchone()

    if not row:
        return jsonify({'error': 'Lead not found'}), 404

    return jsonify(lead_row_to_dict(row))

@app.route('/api/leads/<int:lead_id>', methods=['PUT'])
@limiter.limit("30/minute")
def update_lead(lead_id):
    """Update lead CRM fields (status, tags, notes, contact_name)."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    # Verify ownership
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''SELECT l.id FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE l.id = %s AND b.user_id = %s''', (lead_id, user_id))
        if not c.fetchone():
            return jsonify({'error': 'Lead not found'}), 404

        # Build update
        updates = []
        params = []

        if 'crm_status' in data:
            status_val = data['crm_status']
            if status_val not in CRM_STATUSES:
                return jsonify({'error': f'Invalid status. Must be one of: {", ".join(CRM_STATUSES)}'}), 400
            updates.append('crm_status = %s')
            params.append(status_val)

        if 'tags' in data:
            updates.append('tags = %s')
            params.append(data['tags'][:500])

        if 'notes' in data:
            updates.append('notes = %s')
            params.append(data['notes'][:2000])

        if 'contact_name' in data:
            updates.append('contact_name = %s')
            params.append(data['contact_name'][:255])

        if 'company_name' in data:
            updates.append('company_name = %s')
            params.append(data['company_name'][:255])

        if not updates:
            return jsonify({'error': 'No fields to update'}), 400

        updates.append('updated_at = %s')
        params.append(datetime.now())
        params.append(lead_id)

        c.execute(f"UPDATE leads SET {', '.join(updates)} WHERE id = %s", params)

    return jsonify({'message': 'Lead updated', 'lead_id': lead_id})

@app.route('/api/leads/bulk-status', methods=['PUT'])
@limiter.limit("10/minute")
def bulk_update_status():
    """Bulk update lead statuses."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    lead_ids = data.get('lead_ids', [])
    new_status = data.get('crm_status', '')

    if not lead_ids or not isinstance(lead_ids, list):
        return jsonify({'error': 'lead_ids array required'}), 400
    if new_status not in CRM_STATUSES:
        return jsonify({'error': f'Invalid status. Must be one of: {", ".join(CRM_STATUSES)}'}), 400
    if len(lead_ids) > 200:
        return jsonify({'error': 'Maximum 200 leads per bulk update'}), 400

    with get_db() as conn:
        c = conn.cursor()
        placeholders = ','.join(['%s'] * len(lead_ids))
        c.execute(
            f'''UPDATE leads SET crm_status = %s, updated_at = %s
                WHERE id IN ({placeholders})
                AND batch_id IN (SELECT id FROM batches WHERE user_id = %s)''',
            [new_status, datetime.now()] + lead_ids + [user_id]
        )
        updated = c.rowcount

    return jsonify({'message': f'{updated} leads updated', 'updated': updated})

@app.route('/api/leads/bulk-tag', methods=['PUT'])
@limiter.limit("10/minute")
def bulk_add_tag():
    """Bulk add a tag to leads."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    lead_ids = data.get('lead_ids', [])
    tag = data.get('tag', '').strip()

    if not lead_ids or not isinstance(lead_ids, list):
        return jsonify({'error': 'lead_ids array required'}), 400
    if not tag:
        return jsonify({'error': 'tag required'}), 400
    if len(lead_ids) > 200:
        return jsonify({'error': 'Maximum 200 leads per bulk update'}), 400

    with get_db() as conn:
        c = conn.cursor()
        # For each lead, append tag if not already present
        for lid in lead_ids:
            c.execute(
                '''UPDATE leads SET
                     tags = CASE
                       WHEN tags IS NULL OR tags = '' THEN %s
                       WHEN tags NOT ILIKE %s THEN tags || ',' || %s
                       ELSE tags
                     END,
                     updated_at = %s
                   WHERE id = %s
                   AND batch_id IN (SELECT id FROM batches WHERE user_id = %s)''',
                (tag, f'%{tag}%', tag, datetime.now(), lid, user_id)
            )

    return jsonify({'message': f'Tag "{tag}" added to {len(lead_ids)} leads'})

@app.route('/api/leads/<int:lead_id>', methods=['DELETE'])
@limiter.limit("30/minute")
def delete_lead(lead_id):
    """Delete a single lead."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()
        # Verify ownership and delete
        c.execute(
            '''DELETE FROM leads
               WHERE id = %s
               AND batch_id IN (SELECT id FROM batches WHERE user_id = %s)''',
            (lead_id, user_id)
        )
        deleted = c.rowcount

    if deleted == 0:
        return jsonify({'error': 'Lead not found or unauthorized'}), 404

    return jsonify({'message': 'Lead deleted', 'lead_id': lead_id})

@app.route('/api/leads/bulk-delete', methods=['POST'])
@limiter.limit("10/minute")
def bulk_delete_leads():
    """Bulk delete leads."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    lead_ids = data.get('lead_ids', [])

    if not lead_ids or not isinstance(lead_ids, list):
        return jsonify({'error': 'lead_ids array required'}), 400
    if len(lead_ids) > 500:
        return jsonify({'error': 'Maximum 500 leads per bulk delete'}), 400

    with get_db() as conn:
        c = conn.cursor()
        placeholders = ','.join(['%s'] * len(lead_ids))
        c.execute(
            f'''DELETE FROM leads
                WHERE id IN ({placeholders})
                AND batch_id IN (SELECT id FROM batches WHERE user_id = %s)''',
            lead_ids + [user_id]
        )
        deleted = c.rowcount

    return jsonify({'message': f'{deleted} leads deleted', 'deleted': deleted})

# ============= Advanced Scraping Methods =============

# Credenciais para scrapers autenticados
INSTAGRAM_USERNAME = "vaganagringa.dev"
INSTAGRAM_PASSWORD = "1982Xandeq1982#"
LINKEDIN_USERNAME = "acq2002@hotmail.com"
LINKEDIN_PASSWORD = "1982Xandeq1982#"

def scrape_google_maps(query, city, state, max_results=20):
    """
    Scrape Google Maps para buscar empresas locais.
    Retorna lista de leads com nome, endereço, telefone, website, avaliações.
    """
    from playwright.sync_api import sync_playwright

    leads = []
    search_query = f"{query} em {city}, {state}, Brasil"

    print(f"[GoogleMaps] Iniciando busca: {search_query}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=random.choice(USER_AGENTS)
            )
            page = context.new_page()

            # Buscar no Google Maps
            maps_url = f"https://www.google.com/maps/search/{requests_quote(search_query)}"
            page.goto(maps_url, timeout=30000)
            time.sleep(3)

            # Scroll para carregar mais resultados
            for _ in range(3):
                page.keyboard.press('PageDown')
                time.sleep(1)

            # Extrair resultados
            results = page.query_selector_all('[role="article"]')
            print(f"[GoogleMaps] {len(results)} resultados encontrados")

            for idx, result in enumerate(results[:max_results]):
                try:
                    # Clicar no resultado para abrir detalhes
                    result.click()
                    time.sleep(2)

                    # Extrair dados
                    company_name = None
                    address = None
                    phone = None
                    website = None
                    rating = None

                    # Nome da empresa
                    name_elem = page.query_selector('h1')
                    if name_elem:
                        company_name = name_elem.inner_text().strip()

                    # Telefone
                    phone_button = page.query_selector('[data-item-id*="phone"]')
                    if phone_button:
                        phone_text = phone_button.inner_text()
                        phone_match = re.search(r'[\d\s\(\)\-]+', phone_text)
                        if phone_match:
                            phone = phone_match.group().strip()

                    # Website
                    website_button = page.query_selector('[data-item-id*="authority"]')
                    if website_button:
                        website_text = website_button.inner_text()
                        if website_text and not website_text.startswith('http'):
                            website = f"https://{website_text}"
                        else:
                            website = website_text

                    # Endereço
                    address_button = page.query_selector('[data-item-id*="address"]')
                    if address_button:
                        address = address_button.inner_text().strip()

                    # Avaliação
                    rating_elem = page.query_selector('[role="img"][aria-label*="estrelas"]')
                    if rating_elem:
                        rating_text = rating_elem.get_attribute('aria-label')
                        rating_match = re.search(r'([\d,\.]+)\s*estrelas', rating_text)
                        if rating_match:
                            rating = rating_match.group(1)

                    if company_name:
                        lead = {
                            'company_name': company_name,
                            'phone': phone,
                            'website': website,
                            'address': address,
                            'city': city,
                            'state': state,
                            'rating': rating,
                            'source': 'google_maps'
                        }
                        leads.append(lead)
                        print(f"[GoogleMaps] Lead {idx+1}: {company_name}")

                except Exception as e:
                    print(f"[GoogleMaps] Erro ao processar resultado {idx+1}: {e}")
                    continue

            browser.close()

    except Exception as e:
        print(f"[GoogleMaps] Erro geral: {e}")

    print(f"[GoogleMaps] Total de {len(leads)} leads extraídos")
    return leads


def scrape_instagram_business(niche, city, state, max_results=50):
    """
    Scrape Instagram para buscar perfis de negócios locais.
    Usa hashtags e localização para encontrar empresas.
    """
    import instaloader

    leads = []
    L = instaloader.Instaloader()

    print(f"[Instagram] Fazendo login como {INSTAGRAM_USERNAME}...")

    try:
        # Login
        L.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)

        # Buscar por hashtags relacionadas ao nicho + cidade
        hashtags = [
            f"{niche.replace(' ', '').lower()}{city.lower()}",
            f"{niche.replace(' ', '').lower()}{state.lower()}",
            f"{city.lower()}{niche.replace(' ', '').lower()}"
        ]

        for hashtag in hashtags[:2]:  # Limitar a 2 hashtags para não demorar muito
            print(f"[Instagram] Buscando #{hashtag}...")

            try:
                posts = instaloader.Hashtag.from_name(L.context, hashtag).get_posts()

                processed = 0
                for post in posts:
                    if processed >= max_results // 2:
                        break

                    try:
                        profile = post.owner_profile

                        # Apenas perfis de negócios
                        if profile.is_business_account:
                            email = profile.business_email if hasattr(profile, 'business_email') else None
                            phone = profile.business_phone_number if hasattr(profile, 'business_phone_number') else None

                            lead = {
                                'company_name': profile.full_name or profile.username,
                                'instagram': f"https://instagram.com/{profile.username}",
                                'email': email,
                                'phone': phone,
                                'website': profile.external_url,
                                'city': city,
                                'state': state,
                                'bio': profile.biography[:200] if profile.biography else None,
                                'followers': profile.followers,
                                'source': 'instagram'
                            }

                            leads.append(lead)
                            print(f"[Instagram] Lead: @{profile.username} - {profile.full_name}")
                            processed += 1

                            time.sleep(2)  # Rate limiting

                    except Exception as e:
                        print(f"[Instagram] Erro ao processar post: {e}")
                        continue

            except Exception as e:
                print(f"[Instagram] Erro na hashtag #{hashtag}: {e}")
                continue

    except Exception as e:
        print(f"[Instagram] Erro geral: {e}")

    print(f"[Instagram] Total de {len(leads)} leads extraídos")
    return leads


def scrape_linkedin_companies(niche, city, state, max_results=30):
    """
    Scrape LinkedIn para buscar empresas.
    ATENÇÃO: LinkedIn tem proteção anti-scraping muito forte.
    Usar com cuidado e delays longos.
    """
    from playwright.sync_api import sync_playwright

    leads = []
    search_query = f"{niche} {city} {state}"

    print(f"[LinkedIn] Iniciando busca: {search_query}")
    print(f"[LinkedIn] ⚠️  ATENÇÃO: LinkedIn pode bloquear. Usando delays longos...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)  # headless=False para evitar detecção
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=random.choice(USER_AGENTS)
            )
            page = context.new_page()

            # Login no LinkedIn
            print(f"[LinkedIn] Fazendo login...")
            page.goto('https://www.linkedin.com/login', timeout=30000)
            time.sleep(2)

            page.fill('input[name="session_key"]', LINKEDIN_USERNAME)
            page.fill('input[name="session_password"]', LINKEDIN_PASSWORD)
            page.click('button[type="submit"]')
            time.sleep(5)

            # Verificar se login funcionou
            if 'feed' not in page.url and 'checkpoint' in page.url:
                print("[LinkedIn] ⚠️  CAPTCHA ou verificação detectada. Abortando...")
                browser.close()
                return leads

            print(f"[LinkedIn] Login OK. Buscando empresas...")

            # Buscar empresas
            search_url = f"https://www.linkedin.com/search/results/companies/?keywords={requests_quote(search_query)}"
            page.goto(search_url, timeout=30000)
            time.sleep(5)

            # Scroll para carregar resultados
            for _ in range(3):
                page.keyboard.press('PageDown')
                time.sleep(2)

            # Extrair resultados
            company_cards = page.query_selector_all('.entity-result')
            print(f"[LinkedIn] {len(company_cards)} empresas encontradas")

            for idx, card in enumerate(company_cards[:max_results]):
                try:
                    # Nome da empresa
                    name_elem = card.query_selector('.entity-result__title-text a')
                    if not name_elem:
                        continue

                    company_name = name_elem.inner_text().strip()
                    company_url = name_elem.get_attribute('href')

                    # Localização
                    location_elem = card.query_selector('.entity-result__secondary-subtitle')
                    location = location_elem.inner_text().strip() if location_elem else None

                    # Descrição
                    desc_elem = card.query_selector('.entity-result__summary')
                    description = desc_elem.inner_text().strip() if desc_elem else None

                    lead = {
                        'company_name': company_name,
                        'linkedin': company_url,
                        'city': city,
                        'state': state,
                        'address': location,
                        'description': description[:200] if description else None,
                        'source': 'linkedin'
                    }

                    leads.append(lead)
                    print(f"[LinkedIn] Lead {idx+1}: {company_name}")

                    time.sleep(random.uniform(3, 6))  # Delay longo para evitar bloqueio

                except Exception as e:
                    print(f"[LinkedIn] Erro ao processar empresa {idx+1}: {e}")
                    continue

            browser.close()

    except Exception as e:
        print(f"[LinkedIn] Erro geral: {e}")

    print(f"[LinkedIn] Total de {len(leads)} leads extraídos")
    return leads

# ============= API Enrichment Functions =============

API_CREDIT_LIMITS = {'hunter': 25, 'snov': 50, 'bing_api': 1000, 'google_cse': 100}

def get_api_config(cursor, user_id, provider):
    """Get active API config for a user and provider."""
    cursor.execute(
        'SELECT api_key, api_secret, is_active FROM api_configs WHERE user_id = %s AND provider = %s',
        (user_id, provider)
    )
    row = cursor.fetchone()
    if row and row[2]:
        return {'api_key': row[0], 'api_secret': row[1]}
    return None


def get_api_credits_remaining(cursor, user_id, provider):
    """Get remaining API credits for current period (daily for google_cse, monthly for others)."""
    if provider == 'google_cse':
        period = datetime.now().strftime('%Y-%m-%d')  # Daily limit
    else:
        period = datetime.now().strftime('%Y-%m')  # Monthly limit
    cursor.execute(
        'SELECT credits_used, credits_limit FROM api_usage WHERE user_id = %s AND provider = %s AND month_year = %s',
        (user_id, provider, period)
    )
    row = cursor.fetchone()
    if not row:
        return API_CREDIT_LIMITS.get(provider, 0)
    return max(0, row[1] - row[0])


def record_api_usage(cursor, user_id, provider, cost=1):
    """Record API credit usage for current period (upsert)."""
    if provider == 'google_cse':
        period = datetime.now().strftime('%Y-%m-%d')  # Daily limit
    else:
        period = datetime.now().strftime('%Y-%m')  # Monthly limit
    limit = API_CREDIT_LIMITS.get(provider, 0)
    cursor.execute(
        '''INSERT INTO api_usage (user_id, provider, month_year, credits_used, credits_limit)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (user_id, provider, month_year)
           DO UPDATE SET credits_used = api_usage.credits_used + %s''',
        (user_id, provider, period, cost, limit, cost)
    )


def check_api_cache(cursor, domain, provider):
    """Check cache for recent API results on domain."""
    cursor.execute(
        'SELECT response_data FROM api_cache WHERE domain = %s AND provider = %s AND expires_at > %s',
        (domain, provider, datetime.now())
    )
    row = cursor.fetchone()
    return row[0] if row else None


def save_api_cache(cursor, domain, provider, response_data):
    """Cache API response for domain (30 days)."""
    expires_at = datetime.now() + timedelta(days=30)
    cursor.execute(
        '''INSERT INTO api_cache (domain, provider, response_data, queried_at, expires_at)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (domain, provider)
           DO UPDATE SET response_data = %s, queried_at = %s, expires_at = %s''',
        (domain, provider, json.dumps(response_data), datetime.now(), expires_at,
         json.dumps(response_data), datetime.now(), expires_at)
    )


def enrich_domain_hunter(domain, api_key):
    """Call Hunter.io Domain Search API - with full request/response logging."""
    req_url = f'https://api.hunter.io/v2/domain-search?domain={domain}&api_key={api_key[:8]}...'
    full_url = f'https://api.hunter.io/v2/domain-search?domain={domain}&api_key={api_key}'
    print(f"[hunter] Batendo na porta do Hunter.io para '{domain}' ...")
    print(f"[hunter] REQUEST: GET {req_url}")
    try:
        start = time.time()
        resp = http_requests.get(full_url, timeout=15, headers={'User-Agent': random.choice(USER_AGENTS)})
        duration = int((time.time() - start) * 1000)
        # Log response details
        resp_preview = resp.text[:300] if resp.text else '(vazio)'
        print(f"[hunter] RESPONSE: status={resp.status_code}, duration={duration}ms, body_size={len(resp.text)}")
        print(f"[hunter] BODY PREVIEW: {resp_preview}")

        if resp.status_code == 401:
            print(f"[hunter] ERRO: Chave invalida! O Hunter disse 'quem eh voce?' (401)")
            return {'error': 'invalid_key', 'status': 401, 'duration': duration, 'raw_response': resp_preview}
        if resp.status_code == 429:
            print(f"[hunter] ERRO: Limite excedido! Hunter pediu calma (429)")
            return {'error': 'rate_limited', 'status': 429, 'duration': duration, 'raw_response': resp_preview}
        if resp.status_code != 200:
            print(f"[hunter] ERRO: Resposta inesperada HTTP {resp.status_code}")
            return {'error': f'http_{resp.status_code}', 'status': resp.status_code, 'duration': duration, 'raw_response': resp_preview}

        data = resp.json().get('data', {})
        leads = []
        for email_obj in data.get('emails', []):
            lead = {
                'email': email_obj.get('value', ''),
                'first_name': email_obj.get('first_name', ''),
                'last_name': email_obj.get('last_name', ''),
                'position': email_obj.get('position', ''),
                'confidence': email_obj.get('confidence', 0),
                'phone': email_obj.get('phone_number') or '',
            }
            if lead['email']:
                leads.append(lead)

        org = data.get('organization', '')
        print(f"[hunter] RESULTADO: {len(leads)} emails encontrados, org='{org}', domain='{domain}'")
        if leads:
            for i, l in enumerate(leads[:3]):
                print(f"[hunter]   Lead {i+1}: {l['email']} ({l['first_name']} {l['last_name']}) - {l['position']}")

        return {
            'leads': leads,
            'organization': org,
            'domain': domain,
            'status': 200,
            'duration': duration,
            'raw_response': resp_preview,
        }
    except Exception as e:
        print(f"[hunter] EXCECAO: {e}")
        return {'error': str(e)[:200], 'status': 0, 'duration': 0, 'raw_response': str(e)[:200]}


def get_snov_access_token(client_id, client_secret):
    """Get Snov.io OAuth2 access token - with logging."""
    print(f"[snov] Pedindo token OAuth ao Snov.io (client_id={client_id[:8]}...)")
    try:
        resp = http_requests.post('https://api.snov.io/v1/oauth/access_token', json={
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret,
        }, timeout=10)
        print(f"[snov] Token response: status={resp.status_code}, body={resp.text[:200]}")
        if resp.status_code == 200:
            token = resp.json().get('access_token')
            print(f"[snov] Token obtido com sucesso! (len={len(token) if token else 0})")
            return token
        print(f"[snov] ERRO ao obter token! Status={resp.status_code}")
        return None
    except Exception as e:
        print(f"[snov] EXCECAO no token: {e}")
        return None


def enrich_domain_snov(domain, client_id, client_secret):
    """Call Snov.io Domain Search API - with full request/response logging."""
    print(f"[snov] Acordando o Snov.io para '{domain}' ...")
    token = get_snov_access_token(client_id, client_secret)
    if not token:
        print(f"[snov] Snov se recusou a dar o token! Auth falhou")
        return {'error': 'auth_failed', 'status': 401, 'duration': 0, 'raw_response': 'token_failed'}

    try:
        req_body = {'domain': domain, 'type': 'all', 'limit': 10}
        print(f"[snov] REQUEST: POST https://api.snov.io/v2/domain-emails-with-info")
        print(f"[snov] BODY: {json.dumps(req_body)}")
        start = time.time()
        resp = http_requests.post('https://api.snov.io/v2/domain-emails-with-info', json=req_body,
                                  headers={'Authorization': f'Bearer {token[:15]}...'}, timeout=15)
        duration = int((time.time() - start) * 1000)
        resp_preview = resp.text[:400] if resp.text else '(vazio)'
        print(f"[snov] RESPONSE: status={resp.status_code}, duration={duration}ms, body_size={len(resp.text)}")
        print(f"[snov] BODY PREVIEW: {resp_preview}")

        if resp.status_code != 200:
            print(f"[snov] ERRO: Snov retornou HTTP {resp.status_code}")
            return {'error': f'http_{resp.status_code}', 'status': resp.status_code, 'duration': duration, 'raw_response': resp_preview}

        data = resp.json()
        if not data.get('success', True) and 'error' in data:
            print(f"[snov] ERRO na resposta: {data['error']}")
            return {'error': data['error'], 'status': resp.status_code, 'duration': duration, 'raw_response': resp_preview}

        leads = []
        for email_obj in data.get('emails', []):
            lead = {
                'email': email_obj.get('email', ''),
                'first_name': email_obj.get('first_name', ''),
                'last_name': email_obj.get('last_name', ''),
                'position': email_obj.get('position', ''),
                'confidence': 0,
                'phone': '',
            }
            if lead['email']:
                leads.append(lead)

        org = data.get('name', '') or data.get('companyName', '')
        print(f"[snov] RESULTADO: {len(leads)} emails encontrados, org='{org}', domain='{domain}'")
        if leads:
            for i, l in enumerate(leads[:3]):
                print(f"[snov]   Lead {i+1}: {l['email']} ({l['first_name']} {l['last_name']})")

        return {
            'leads': leads,
            'organization': org,
            'domain': domain,
            'status': 200,
            'duration': duration,
            'raw_response': resp_preview,
        }
    except Exception as e:
        print(f"[snov] EXCECAO: {e}")
        return {'error': str(e)[:200], 'status': 0, 'duration': 0, 'raw_response': str(e)[:200]}


def enrich_domain_with_fallback(cursor, domain, user_id, search_job_id=None):
    """Enrich domain using fallback chain: cache -> Hunter -> Snov -> empty.
    Returns (leads_list, source_name).
    FIX: Only cache results WITH leads. 0-lead cache was blocking Snov from being tried."""

    print(f"[enrich] === Iniciando enriquecimento para '{domain}' ===")

    # 1. Check cache - but ONLY return cache hits that have leads
    for provider in ('hunter', 'snov'):
        cached = check_api_cache(cursor, domain, provider)
        if cached:
            cached_leads = cached.get('leads', [])
            if cached_leads:
                if search_job_id:
                    log_search(cursor, search_job_id, 'api_cache',
                              url=f'https://{domain}',
                              message=f'Cache com leads! ({provider}) {domain}: {len(cached_leads)} leads - pulando API')
                print(f"[enrich] Cache HIT com leads ({provider}) para {domain}: {len(cached_leads)} leads")
                return cached_leads, provider + '_cache'
            else:
                print(f"[enrich] Cache existe ({provider}) para {domain} mas com 0 leads - ignorando, vou tentar outra API")

    # 2. Try Hunter.io
    hunter_config = get_api_config(cursor, user_id, 'hunter')
    hunter_credits = get_api_credits_remaining(cursor, user_id, 'hunter') if hunter_config else 0
    print(f"[enrich] Hunter.io: config={'SIM' if hunter_config else 'NAO'}, creditos_restantes={hunter_credits}")

    if hunter_config and hunter_credits > 0:
        result = enrich_domain_hunter(domain, hunter_config['api_key'])
        if result.get('status') == 200 and result.get('leads'):
            record_api_usage(cursor, user_id, 'hunter', 1)
            save_api_cache(cursor, domain, 'hunter', result)
            if search_job_id:
                log_search(cursor, search_job_id, 'api_hunter_ok', url=f'https://{domain}',
                          status_code=200,
                          message=f'Hunter achou ouro! {len(result["leads"])} leads em {domain} ({result.get("duration", 0)}ms)',
                          duration_ms=result.get('duration', 0))
            return result['leads'], 'hunter'
        elif result.get('error') == 'invalid_key':
            cursor.execute('UPDATE api_configs SET is_active = FALSE WHERE user_id = %s AND provider = %s',
                          (user_id, 'hunter'))
            if search_job_id:
                log_search(cursor, search_job_id, 'api_error', url=f'https://{domain}',
                          status_code=401,
                          message=f'Hunter rejeitou a chave! API key desativada automaticamente')
        elif result.get('error') == 'rate_limited':
            if search_job_id:
                log_search(cursor, search_job_id, 'api_error', url=f'https://{domain}',
                          status_code=429,
                          message=f'Hunter pediu calma! Rate limited (429)')
        elif result.get('status') == 200:
            # 0 leads - charge credit but DON'T cache (so Snov can try later)
            record_api_usage(cursor, user_id, 'hunter', 1)
            if search_job_id:
                log_search(cursor, search_job_id, 'api_hunter_empty', url=f'https://{domain}',
                          status_code=200,
                          message=f'Hunter respondeu mas 0 leads para {domain} ({result.get("duration", 0)}ms) - tentando Snov...',
                          duration_ms=result.get('duration', 0))
        else:
            err = result.get('error', 'desconhecido')
            if search_job_id:
                log_search(cursor, search_job_id, 'api_error', url=f'https://{domain}',
                          status_code=result.get('status', 0),
                          message=f'Hunter deu erro: {err} (status={result.get("status", 0)})')
    elif hunter_config and hunter_credits <= 0:
        if search_job_id:
            log_search(cursor, search_job_id, 'api_skip', url=f'https://{domain}',
                      message=f'Hunter sem creditos! 0 restantes este mes - pulando')
    elif not hunter_config:
        if search_job_id:
            log_search(cursor, search_job_id, 'api_skip', url=f'https://{domain}',
                      message=f'Hunter nao configurado - pulando')

    # 3. Try Snov.io (ALWAYS try if Hunter didn't find leads)
    snov_config = get_api_config(cursor, user_id, 'snov')
    snov_credits = get_api_credits_remaining(cursor, user_id, 'snov') if snov_config else 0
    print(f"[enrich] Snov.io: config={'SIM' if snov_config else 'NAO'}, creditos_restantes={snov_credits}")

    if snov_config and snov_credits > 0:
        result = enrich_domain_snov(domain, snov_config['api_key'], snov_config['api_secret'])
        if result.get('status') == 200 and result.get('leads'):
            record_api_usage(cursor, user_id, 'snov', 1)
            save_api_cache(cursor, domain, 'snov', result)
            if search_job_id:
                log_search(cursor, search_job_id, 'api_snov_ok', url=f'https://{domain}',
                          status_code=200,
                          message=f'Snov salvou o dia! {len(result["leads"])} leads em {domain} ({result.get("duration", 0)}ms)',
                          duration_ms=result.get('duration', 0))
            return result['leads'], 'snov'
        elif result.get('error') == 'auth_failed':
            cursor.execute('UPDATE api_configs SET is_active = FALSE WHERE user_id = %s AND provider = %s',
                          (user_id, 'snov'))
            if search_job_id:
                log_search(cursor, search_job_id, 'api_error', url=f'https://{domain}',
                          status_code=401,
                          message=f'Snov nao reconheceu as credenciais! Config desativada')
        elif result.get('status') == 200:
            # 0 leads from Snov too
            record_api_usage(cursor, user_id, 'snov', 1)
            if search_job_id:
                log_search(cursor, search_job_id, 'api_snov_empty', url=f'https://{domain}',
                          status_code=200,
                          message=f'Snov tambem 0 leads para {domain} ({result.get("duration", 0)}ms) - dominio seco!',
                          duration_ms=result.get('duration', 0))
        else:
            err = result.get('error', 'desconhecido')
            if search_job_id:
                log_search(cursor, search_job_id, 'api_error', url=f'https://{domain}',
                          status_code=result.get('status', 0),
                          message=f'Snov deu erro: {err} (status={result.get("status", 0)})')
    elif snov_config and snov_credits <= 0:
        if search_job_id:
            log_search(cursor, search_job_id, 'api_skip', url=f'https://{domain}',
                      message=f'Snov sem creditos! 0 restantes este mes')
    elif not snov_config:
        if search_job_id:
            log_search(cursor, search_job_id, 'api_skip', url=f'https://{domain}',
                      message=f'Snov nao configurado - pulando')

    # 4. No API results - caller will fallback to scraping
    return [], 'scraping'


# ============= Company Name Derivation from Email =============

GENERIC_EMAIL_PROVIDERS = {
    'gmail.com', 'googlemail.com', 'outlook.com', 'outlook.com.br',
    'hotmail.com', 'hotmail.com.br', 'yahoo.com', 'yahoo.com.br',
    'live.com', 'msn.com', 'aol.com', 'icloud.com', 'me.com',
    'protonmail.com', 'proton.me', 'zoho.com', 'mail.com', 'gmx.com',
    'uol.com.br', 'bol.com.br', 'terra.com.br', 'ig.com.br',
    'r7.com', 'globo.com', 'globomail.com', 'zipmail.com.br',
    'oi.com.br', 'veloxmail.com.br',
}

def derive_company_name(email):
    """Derive a company name from an email address domain.
    Aggressively cleans common corporate suffixes and symbols.
    """
    if not email or '@' not in email:
        return ''
    _, domain = email.lower().split('@', 1)
    if not domain or domain in GENERIC_EMAIL_PROVIDERS:
        return ''

    # Get main domain part (e.g. acme.com.br -> acme)
    name = domain.split('.')[0]

    import re as _re
    name = _re.sub(r'\d+$', '', name)           # remove trailing numbers
    name = _re.sub(r'[._\-]+', ' ', name)      # dots/underscores/hyphens -> spaces
    name = name.upper()

    # Advanced cleaning: Remove corporate suffixes
    for suffix in CORPORATE_SUFFIXES:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
            break

    name = _re.sub(r'\s+', ' ', name).strip()   # collapse spaces
    if not name or len(name) < 2:
        return ''

    return ' '.join(w.capitalize() for w in name.split())

def derive_contact_name(email):
    """Derive a human contact name from the local part of an email.
    Example: joao.silva@gmail.com -> Joao Silva
    Returns empty string if it looks like a generic/department email.
    """
    if not email or '@' not in email:
        return ''
    local_part, _ = email.lower().split('@', 1)

    # Skip department/generic prefixes
    import re as _re
    for pattern in EMAIL_LOW_QUALITY_PATTERNS:
        if _re.search(pattern, local_part + '@'):
            return ''

    # Basic cleaning
    name = _re.sub(r'\d+$', '', local_part)
    name = _re.sub(r'[._\-]+', ' ', name)
    name = _re.sub(r'\s+', ' ', name).strip()

    if not name or len(name) < 3:
        return ''

    # Heuristic: human names usually have at least one space if they use dots/underscores
    # or follow common baptismal name lengths.
    words = name.split()
    if len(words) == 1 and len(words[0]) < 4: # too short for a name
        return ''

    return ' '.join(w.capitalize() for w in words)


# ============= Import Leads from Text Extraction =============

@app.route('/api/leads/import', methods=['POST'])
@limiter.limit("20/minute")
def import_leads():
    """Import leads extracted from pasted text (emails, phones, names)."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    contacts = data.get('contacts', [])
    batch_name = data.get('batch_name', '').strip()

    if not contacts:
        return jsonify({'error': 'Nenhum contato para importar'}), 400
    if not batch_name:
        batch_name = f'Importacao Texto - {datetime.now().strftime("%d/%m/%Y %H:%M")}'

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO batches (user_id, name, total_urls, status) VALUES (%s, %s, %s, 'completed') RETURNING id",
            (user_id, batch_name, len(contacts))
        )
        batch_id = cur.fetchone()[0]

        imported = 0
        skipped = 0
        for c in contacts:
            email = (c.get('email') or '').strip().lower()
            phone = (c.get('phone') or '').strip()
            company = (c.get('company_name') or '').strip()
            if not company and email:
                company = derive_company_name(email)
            website = (c.get('website') or '').strip()
            whatsapp = (c.get('whatsapp') or phone or '').strip()
            contact_name = (c.get('contact_name') or '').strip()

            # Intelligent contact name extraction
            if not contact_name and email:
                contact_name = derive_contact_name(email)

            if not email and not phone:
                skipped += 1
                continue

            # Check duplicate by email within same user
            if email:
                cur.execute(
                    "SELECT id FROM leads WHERE email = %s AND batch_id IN (SELECT id FROM batches WHERE user_id = %s) LIMIT 1",
                    (email, user_id)
                )
                if cur.fetchone():
                    skipped += 1
                    continue

            cur.execute(
                """INSERT INTO leads (batch_id, email, phone, company_name, website, whatsapp, contact_name, source_url, crm_status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'novo')""",
                (batch_id, email or None, phone or None, company or None, website or None,
                 whatsapp or None, contact_name or None, website or None)
            )
            imported += 1

        # Update batch count
        cur.execute("UPDATE batches SET total_urls = %s WHERE id = %s", (imported, batch_id))
        conn.commit()

        # AUTO-SYNC: Start background thread to sync leads
        sync_thread = threading.Thread(target=auto_sync_new_leads_background, args=(batch_id,), daemon=True)
        sync_thread.start()

        return jsonify({
            'batch_id': batch_id,
            'imported': imported,
            'skipped': skipped,
            'total': len(contacts),
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============= Export for Marketing =============

@app.route('/api/leads/export', methods=['GET'])
@limiter.limit("10/minute")
def export_leads():
    """Export leads in multiple formats for marketing tools.
    Formats: csv, mailchimp, whatsapp, whatsapp_txt, vcard, json
    Filters: status, tag, batch_id, search, ids (comma-separated)
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    fmt = request.args.get('format', 'csv').strip().lower()
    if fmt not in ('csv', 'mailchimp', 'whatsapp', 'whatsapp_txt', 'vcard', 'json'):
        return jsonify({'error': 'Invalid format. Use: csv, mailchimp, whatsapp, whatsapp_txt, vcard, json'}), 400

    # Build query with same filters as list_leads
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '').strip()
    tag = request.args.get('tag', '').strip()
    batch_id = request.args.get('batch_id', '').strip()
    ids = request.args.get('ids', '').strip()

    query = LEADS_SELECT
    params = [user_id]

    if ids:
        id_list = [int(x) for x in ids.split(',') if x.strip().isdigit()]
        if id_list:
            query += f' AND l.id IN ({",".join(["%s"] * len(id_list))})'
            params.extend(id_list)

    if search:
        query += ''' AND (l.company_name ILIKE %s OR l.email ILIKE %s
                     OR l.phone ILIKE %s OR l.website ILIKE %s
                     OR l.contact_name ILIKE %s OR l.cnpj ILIKE %s OR l.tags ILIKE %s)'''
        like = f'%{search}%'
        params.extend([like, like, like, like, like, like, like])

    if status and status in CRM_STATUSES:
        query += ' AND l.crm_status = %s'
        params.append(status)

    if tag:
        query += ' AND l.tags ILIKE %s'
        params.append(f'%{tag}%')

    if batch_id:
        query += ' AND l.batch_id = %s'
        params.append(int(batch_id))

    query += ' ORDER BY l.extracted_at DESC'

    with get_db() as conn:
        c = conn.cursor()
        c.execute(query, params)
        rows = c.fetchall()

    leads = [lead_row_to_dict(row) for row in rows]

    if not leads:
        return jsonify({'error': 'No leads to export'}), 404

    # --- Format: CSV (generic, all fields) ---
    if fmt == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Empresa', 'Email', 'Telefone', 'WhatsApp', 'CNPJ', 'Contato',
                         'Instagram', 'Facebook', 'LinkedIn', 'Twitter', 'YouTube',
                         'Endereco', 'Cidade', 'Estado', 'Website', 'Status', 'Tags', 'Notas', 'Lote'])
        for l in leads:
            writer.writerow([
                l.get('company_name', ''), l.get('email', ''), l.get('phone', ''),
                l.get('whatsapp', ''), l.get('cnpj', ''), l.get('contact_name', ''),
                l.get('instagram', ''), l.get('facebook', ''), l.get('linkedin', ''),
                l.get('twitter', ''), l.get('youtube', ''), l.get('address', ''),
                l.get('city', ''), l.get('state', ''), l.get('website', ''),
                l.get('crm_status', ''), l.get('tags', ''), l.get('notes', ''), l.get('batch_name', ''),
            ])
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=leads_export.csv'}
        )

    # --- Format: Mailchimp (ready for import) ---
    if fmt == 'mailchimp':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Email Address', 'First Name', 'Last Name', 'Phone Number', 'Company', 'Tags'])
        for l in leads:
            name = l.get('contact_name', '') or l.get('company_name', '') or ''
            parts = name.split(' ', 1)
            first_name = parts[0] if parts else ''
            last_name = parts[1] if len(parts) > 1 else ''
            tags_str = l.get('tags', '') or ''
            writer.writerow([
                l.get('email', ''), first_name, last_name,
                l.get('phone', '') or l.get('whatsapp', '') or '',
                l.get('company_name', ''), tags_str,
            ])
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=leads_mailchimp.csv'}
        )

    # --- Format: WhatsApp CSV (for bulk messaging) ---
    if fmt == 'whatsapp':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Phone', 'Name', 'Company', 'Email', 'Website'])
        for l in leads:
            phone = l.get('whatsapp', '') or l.get('phone', '') or ''
            if not phone:
                continue
            # Clean phone: keep only digits
            clean = re.sub(r'\D', '', phone)
            # Add +55 if Brazilian and missing country code
            if len(clean) == 10 or len(clean) == 11:
                clean = '55' + clean
            if len(clean) < 10:
                continue
            writer.writerow([
                '+' + clean,
                l.get('contact_name', '') or l.get('company_name', '') or '',
                l.get('company_name', ''),
                l.get('email', ''),
                l.get('website', ''),
            ])
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=leads_whatsapp.csv'}
        )

    # --- Format: WhatsApp TXT (one number per line) ---
    if fmt == 'whatsapp_txt':
        lines = []
        for l in leads:
            phone = l.get('whatsapp', '') or l.get('phone', '') or ''
            if not phone:
                continue
            clean = re.sub(r'\D', '', phone)
            if len(clean) == 10 or len(clean) == 11:
                clean = '55' + clean
            if len(clean) < 10:
                continue
            lines.append('+' + clean)
        return Response(
            '\n'.join(lines),
            mimetype='text/plain',
            headers={'Content-Disposition': 'attachment; filename=leads_whatsapp.txt'}
        )

    # --- Format: vCard (.vcf) ---
    if fmt == 'vcard':
        vcards = []
        for l in leads:
            name = l.get('contact_name', '') or l.get('company_name', '') or 'Lead'
            parts = name.split(' ', 1)
            first = parts[0]
            last = parts[1] if len(parts) > 1 else ''
            vcard = f'''BEGIN:VCARD
VERSION:3.0
N:{last};{first};;;
FN:{name}
ORG:{l.get('company_name', '')}
EMAIL;TYPE=INTERNET:{l.get('email', '')}'''
            phone = l.get('phone', '') or l.get('whatsapp', '') or ''
            if phone:
                clean = re.sub(r'\D', '', phone)
                if len(clean) == 10 or len(clean) == 11:
                    clean = '55' + clean
                vcard += f'\nTEL;TYPE=CELL:+{clean}'
            if l.get('website'):
                vcard += f'\nURL:{l["website"]}'
            if l.get('address') or l.get('city'):
                addr = l.get('address', '') or ''
                city = l.get('city', '') or ''
                state = l.get('state', '') or ''
                vcard += f'\nADR;TYPE=WORK:;;{addr};{city};{state};;BR'
            if l.get('notes'):
                vcard += f'\nNOTE:{l["notes"][:200]}'
            vcard += '\nEND:VCARD'
            vcards.append(vcard)

        return Response(
            '\n'.join(vcards),
            mimetype='text/vcard',
            headers={'Content-Disposition': 'attachment; filename=leads_contacts.vcf'}
        )

    # --- Format: JSON ---
    if fmt == 'json':
        export_data = []
        for l in leads:
            export_data.append({
                'company_name': l.get('company_name', ''),
                'contact_name': l.get('contact_name', ''),
                'email': l.get('email', ''),
                'phone': l.get('phone', ''),
                'whatsapp': l.get('whatsapp', ''),
                'cnpj': l.get('cnpj', ''),
                'website': l.get('website', ''),
                'instagram': l.get('instagram', ''),
                'facebook': l.get('facebook', ''),
                'linkedin': l.get('linkedin', ''),
                'twitter': l.get('twitter', ''),
                'youtube': l.get('youtube', ''),
                'address': l.get('address', ''),
                'city': l.get('city', ''),
                'state': l.get('state', ''),
                'status': l.get('crm_status', ''),
                'tags': l.get('tags', ''),
                'notes': l.get('notes', ''),
            })
        return Response(
            json.dumps(export_data, indent=2, ensure_ascii=False),
            mimetype='application/json',
            headers={'Content-Disposition': 'attachment; filename=leads_export.json'}
        )

@app.route('/api/analytics', methods=['GET'])
@limiter.limit("30/minute")
def get_analytics():
    """Dashboard analytics: stats, trends, quality metrics."""
    token = get_auth_header()
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()

        # Total leads (from batches)
        c.execute('SELECT COALESCE(SUM(total_leads), 0) FROM batches WHERE user_id = %s', (user_id,))
        total_batch_leads = c.fetchone()[0]

        # Total leads from individual jobs
        c.execute('SELECT COALESCE(SUM(results_count), 0) FROM jobs WHERE user_id = %s', (user_id,))
        total_job_leads = c.fetchone()[0]

        total_leads = total_batch_leads + total_job_leads

        # Total batches
        c.execute('SELECT COUNT(*) FROM batches WHERE user_id = %s', (user_id,))
        total_batches = c.fetchone()[0]

        # Completed vs failed batches
        c.execute("SELECT COUNT(*) FROM batches WHERE user_id = %s AND status = 'completed'", (user_id,))
        completed_batches = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM batches WHERE user_id = %s AND status = 'failed'", (user_id,))
        failed_batches = c.fetchone()[0]

        # Unique emails from leads table
        c.execute('''SELECT COUNT(DISTINCT l.email) FROM leads l
                     JOIN batches b ON l.batch_id = b.id
                     WHERE b.user_id = %s''', (user_id,))
        unique_emails = c.fetchone()[0]

        # Leads this week
        week_ago = datetime.now() - timedelta(days=7)
        c.execute('''SELECT COUNT(*) FROM leads l
                     JOIN batches b ON l.batch_id = b.id
                     WHERE b.user_id = %s AND l.extracted_at >= %s''', (user_id, week_ago))
        leads_this_week = c.fetchone()[0]

        # Leads this month
        month_ago = datetime.now() - timedelta(days=30)
        c.execute('''SELECT COUNT(*) FROM leads l
                     JOIN batches b ON l.batch_id = b.id
                     WHERE b.user_id = %s AND l.extracted_at >= %s''', (user_id, month_ago))
        leads_this_month = c.fetchone()[0]

        # Leads by day (last 30 days) - for LineChart
        c.execute('''SELECT DATE(l.extracted_at) as day, COUNT(*) as count
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.user_id = %s AND l.extracted_at >= %s
                     GROUP BY DATE(l.extracted_at) ORDER BY day''', (user_id, month_ago))
        leads_by_day_raw = c.fetchall()

        # Fill missing days with 0
        leads_by_day = []
        day_map = {row[0].isoformat(): row[1] for row in leads_by_day_raw}
        for i in range(30, -1, -1):
            d = (datetime.now() - timedelta(days=i)).date()
            leads_by_day.append({'date': d.isoformat(), 'leads': day_map.get(d.isoformat(), 0)})

        # Top batches by leads (top 10) - for BarChart
        c.execute('''SELECT name, total_leads FROM batches
                     WHERE user_id = %s AND total_leads > 0
                     ORDER BY total_leads DESC LIMIT 10''', (user_id,))
        top_batches = [{'name': row[0][:30], 'leads': row[1]} for row in c.fetchall()]

        # Data quality: leads with email only, with phone, with both
        c.execute('''SELECT
                       COUNT(*) FILTER (WHERE l.phone IS NOT NULL AND l.phone != '') as with_phone,
                       COUNT(*) FILTER (WHERE l.phone IS NULL OR l.phone = '') as email_only,
                       COUNT(*) FILTER (WHERE l.whatsapp IS NOT NULL AND l.whatsapp != '') as with_whatsapp,
                       COUNT(*) FILTER (WHERE l.cnpj IS NOT NULL AND l.cnpj != '') as with_cnpj,
                       COUNT(*) FILTER (WHERE l.instagram IS NOT NULL AND l.instagram != ''
                                        OR l.facebook IS NOT NULL AND l.facebook != ''
                                        OR l.linkedin IS NOT NULL AND l.linkedin != '') as with_social
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.user_id = %s''', (user_id,))
        quality_row = c.fetchone()
        with_phone = quality_row[0] if quality_row else 0
        email_only = quality_row[1] if quality_row else 0
        with_whatsapp = quality_row[2] if quality_row else 0
        with_cnpj = quality_row[3] if quality_row else 0
        with_social = quality_row[4] if quality_row else 0

    success_rate = round((completed_batches / total_batches * 100)) if total_batches > 0 else 0

    return jsonify({
        'total_leads': total_leads,
        'total_batches': total_batches,
        'unique_emails': unique_emails,
        'leads_this_week': leads_this_week,
        'leads_this_month': leads_this_month,
        'completed_batches': completed_batches,
        'failed_batches': failed_batches,
        'success_rate': success_rate,
        'leads_by_day': leads_by_day,
        'top_batches': top_batches,
        'data_quality': {
            'with_phone': with_phone,
            'email_only': email_only,
            'with_whatsapp': with_whatsapp,
            'with_cnpj': with_cnpj,
            'with_social': with_social,
        },
    })

@app.route('/api/batch/<int:batch_id>', methods=['DELETE'])
@limiter.limit("10/minute")
def delete_batch(batch_id):
    """Delete a batch and all its leads."""
    token = get_auth_header()
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()

        c.execute('SELECT id, status FROM batches WHERE id = %s AND user_id = %s', (batch_id, user_id))
        batch = c.fetchone()
        if not batch:
            return jsonify({'error': 'Batch not found'}), 404

        if batch[1] == 'processing':
            return jsonify({'error': 'Cannot delete batch while processing'}), 409

        c.execute('DELETE FROM batches WHERE id = %s', (batch_id,))

    return jsonify({'message': 'Batch deleted'})

# ============= Scraping Logic (Legacy single-URL) =============

def scrape_emails_from_url(url):
    """Extract emails from URL with normalization (legacy single-URL scrape)."""
    emails = []

    try:
        response = http_requests.get(url, timeout=10, verify=False, headers={
            'User-Agent': random.choice(USER_AGENTS)
        })
        response.encoding = 'utf-8'

        soup = BeautifulSoup(response.text, 'html.parser')

        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

        text = soup.get_text()
        found_emails = set(re.findall(email_pattern, text))

        for email in found_emails:
            normalized = normalize_email(email)
            if normalized:
                emails.append({'email': normalized, 'url': url})

        for tag in soup.find_all(['a', 'img', 'script']):
            for attr in ['href', 'src', 'data-email']:
                val = tag.get(attr, '')
                if 'mailto:' in val:
                    raw_email = val.replace('mailto:', '').split('?')[0]
                    normalized = normalize_email(raw_email)
                    if normalized:
                        emails.append({'email': normalized, 'url': url})

    except Exception as e:
        print(f"Scraping error: {e}")

    unique = {e['email']: e for e in emails}
    return list(unique.values())

# ============= Init =============

# Run init_db on module load (works with both Gunicorn and direct run)
try:
    init_db()
except Exception as e:
    print(f"[init_db] Warning: {e}")

# ============= Main =============

if __name__ == '__main__':
    app.run(debug=False)
"""
MASSIVE SEARCH ENDPOINT - To be added to app.py
Endpoint para busca massiva usando TODOS os métodos disponíveis
"""

# Add this after line ~3400 (after /api/search-api endpoint)

@app.route('/api/search/massive', methods=['POST'])
@limiter.limit("10/hour")  # 10 buscas massivas por hora
def start_massive_search():
    """
    Start a massive search using ALL available methods:
    - API Enrichment (Hunter.io/Snov.io)
    - Search Engines (DuckDuckGo/Bing)
    - Google Maps Playwright
    - Instagram Business
    - LinkedIn Companies
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    # Parameters
    niches = data.get('niches', [])  # Lista de nichos
    region_id = (data.get('region') or '').strip()
    city = (data.get('city') or '').strip()
    state = (data.get('state') or '').strip()
    methods = data.get('methods', ['api_enrichment', 'search_engines', 'google_maps'])  # Métodos selecionados
    max_pages = min(3, max(1, int(data.get('max_pages', 2))))

    if not niches or len(niches) == 0:
        return jsonify({'error': 'Pelo menos um nicho é obrigatório'}), 400

    # Build cities list
    cities_to_search = []
    if region_id and region_id in SEARCH_REGIONS:
        region_data = SEARCH_REGIONS[region_id]
        for c_name in region_data['cities']:
            cities_to_search.append({
                'city': c_name,
                'state': region_data['state'],
                'region': region_id,
            })
    elif city and state:
        cities_to_search.append({
            'city': city,
            'state': state,
            'region': 'manual',
        })
    else:
        return jsonify({'error': 'Selecione uma região ou informe cidade/estado'}), 400

    # Create master batch
    batch_name = f'Busca Massiva - {region_id or city}'
    if len(niches) > 1:
        batch_name += f' ({len(niches)} nichos)'

    with get_db() as conn:
        c = conn.cursor()

        # Calculate total jobs
        total_jobs = 0
        if 'api_enrichment' in methods:
            total_jobs += len(niches) * len(cities_to_search)
        if 'search_engines' in methods:
            total_jobs += len(niches)
        if 'google_maps' in methods:
            total_jobs += len(niches) * len(cities_to_search)

        c.execute(
            'INSERT INTO batches (user_id, name, status, total_urls, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id',
            (user_id, batch_name, 'pending', total_jobs, datetime.now())
        )
        batch_id = c.fetchone()[0]

        # ===========================================================
        # METHOD 1: API ENRICHMENT (Hunter.io / Snov.io)
        # ===========================================================
        api_enrichment_jobs = []
        if 'api_enrichment' in methods:
            for niche in niches[:3]:  # Max 3 por rate limit
                for city_data in cities_to_search[:1]:  # 1 cidade por nicho para não explodir
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, enrichment_source, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data['region'], max_pages, 'pending', 'hunter+snov', datetime.now())
                    )
                    search_job_id = c.fetchone()[0]
                    api_enrichment_jobs.append({
                        'search_job_id': search_job_id,
                        'niche': niche,
                        'city': city_data['city'],
                        'state': city_data['state'],
                        'max_pages': max_pages,
                    })

        # ===========================================================
        # METHOD 2: SEARCH ENGINES (DuckDuckGo / Bing)
        # ===========================================================
        search_engine_jobs = []
        if 'search_engines' in methods:
            for niche in niches[:3]:  # Max 3 por rate limit
                c.execute(
                    '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                    (batch_id, user_id, niche, None, None, region_id, max_pages, 'pending', 'duckduckgo', datetime.now())
                )
                search_job_id = c.fetchone()[0]
                search_engine_jobs.append({
                    'search_job_id': search_job_id,
                    'niche': niche,
                    'region': region_id,
                    'max_pages': max_pages,
                })

        # ===========================================================
        # METHOD 3: GOOGLE MAPS (via existing endpoint)
        # Note: Google Maps não usa search_jobs, cria jobs separados
        # Vamos apenas salvar referência para tracking
        # ===========================================================
        google_maps_jobs = []
        if 'google_maps' in methods:
            for niche in niches[:2]:  # Max 2 para não saturar
                for city_data in cities_to_search[:2]:  # Max 2 cidades
                    # Criar entry de tracking
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         0, 'pending', 'google_maps', datetime.now())
                    )
                    search_job_id = c.fetchone()[0]
                    google_maps_jobs.append({
                        'search_job_id': search_job_id,
                        'niche': niche,
                        'city': city_data['city'],
                        'state': city_data['state'],
                    })

    # ============================================================
    # START BACKGROUND THREADS FOR EACH METHOD
    # ============================================================

    # Thread 1: API Enrichment
    if api_enrichment_jobs:
        thread1 = threading.Thread(
            target=process_api_search_job,
            args=(batch_id, api_enrichment_jobs, user_id),
            daemon=True
        )
        thread1.start()

    # Thread 2: Search Engines
    if search_engine_jobs:
        thread2 = threading.Thread(
            target=process_search_job,
            args=(batch_id, search_engine_jobs, user_id),
            daemon=True
        )
        thread2.start()

    # Thread 3: Google Maps (precisa ser chamado via requests internos)
    if google_maps_jobs:
        thread3 = threading.Thread(
            target=process_google_maps_massive,
            args=(batch_id, google_maps_jobs, user_id, token),
            daemon=True
        )
        thread3.start()

    # AUTO-SYNC: Start background thread to sync leads to alexandrequeiroz.com.br
    sync_thread = threading.Thread(target=auto_sync_new_leads_background, args=(batch_id,), daemon=True)
    sync_thread.start()

    return jsonify({
        'batch_id': batch_id,
        'name': batch_name,
        'total_jobs': total_jobs,
        'methods': {
            'api_enrichment': len(api_enrichment_jobs),
            'search_engines': len(search_engine_jobs),
            'google_maps': len(google_maps_jobs),
        },
        'status': 'processing',
        'message': f'Busca massiva iniciada com {total_jobs} jobs em {len(methods)} métodos'
    })


def process_google_maps_massive(batch_id, jobs_data, user_id, token):
    """Process Google Maps jobs for massive search."""
    with get_db() as conn:
        c = conn.cursor()

        for job_data in jobs_data:
            search_job_id = job_data['search_job_id']
            niche = job_data['niche']
            city = job_data['city']
            state = job_data['state']

            try:
                # Update status to running
                c.execute(
                    'UPDATE search_jobs SET status = %s, started_at = %s WHERE id = %s',
                    ('running', datetime.now(), search_job_id)
                )
                conn.commit()

                # Chamar scraper de Google Maps internamente
                # (Playwright já implementado em outro endpoint)
                results = scrape_google_maps_playwright(f"{niche} {city} {state}", max_places=20)

                if results and len(results) > 0:
                    # Inserir leads no batch
                    for result in results:
                        email = result.get('email', '')
                        phone = result.get('phone', '')
                        website = result.get('website', '')

                        if email or phone or website:
                            c.execute(
                                '''INSERT INTO leads (batch_id, company_name, email, phone, website, city, state, source, extracted_at)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                   ON CONFLICT (batch_id, email) DO NOTHING''',
                                (batch_id, result.get('name', 'Lead sem nome'), email, phone, website,
                                 city, state, 'google_maps', datetime.now())
                            )

                    conn.commit()

                    # Update status to completed
                    c.execute(
                        'UPDATE search_jobs SET status = %s, finished_at = %s, total_leads = %s WHERE id = %s',
                        ('completed', datetime.now(), len(results), search_job_id)
                    )
                    conn.commit()
                else:
                    # No results
                    c.execute(
                        'UPDATE search_jobs SET status = %s, finished_at = %s, total_leads = %s WHERE id = %s',
                        ('completed', datetime.now(), 0, search_job_id)
                    )
                    conn.commit()

            except Exception as e:
                # Error handling
                c.execute(
                    'UPDATE search_jobs SET status = %s, error_message = %s, finished_at = %s WHERE id = %s',
                    ('failed', str(e)[:500], datetime.now(), search_job_id)
                )
                conn.commit()

            # Delay entre jobs para evitar rate limit
            time.sleep(10)

        # Update batch final status
        c.execute(
            '''SELECT COUNT(*) FROM search_jobs
               WHERE batch_id = %s AND status IN ('pending', 'running')''',
            (batch_id,)
        )
        remaining = c.fetchone()[0]

        if remaining == 0:
            c.execute(
                'UPDATE batches SET status = %s WHERE id = %s',
                ('completed', batch_id)
            )
            conn.commit()


# ============================================================
# EXTERNAL APIs INTEGRATION (Apollo.io, PDL, FindThatLead)
# ============================================================

def search_apollo_io(company_name, domain=None, api_key=None):
    """
    Search for leads using Apollo.io API
    Free tier: 50 emails/month
    """
    if not api_key:
        return None

    url = "https://api.apollo.io/v1/people/match"
    headers = {
        'Cache-Control': 'no-cache',
        'Content-Type': 'application/json',
        'X-Api-Key': api_key
    }

    payload = {
        "first_name": "",
        "last_name": "",
        "organization_name": company_name,
    }

    if domain:
        payload['domain'] = domain

    try:
        response = http_requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            person = data.get('person', {})
            return {
                'email': person.get('email'),
                'phone': person.get('phone_numbers', [{}])[0].get('raw_number') if person.get('phone_numbers') else None,
                'name': f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
                'title': person.get('title'),
                'company': person.get('organization', {}).get('name'),
                'source': 'apollo.io'
            }
    except Exception as e:
        print(f"Apollo.io error: {e}")

    return None


def search_pdl(company_name, domain=None, api_key=None):
    """
    Search for leads using PDL (People Data Labs) API
    Free tier: 1000 credits/month
    """
    if not api_key:
        return None

    url = "https://api.peopledatalabs.com/v5/company/enrich"
    headers = {
        'X-Api-Key': api_key
    }

    params = {
        'name': company_name,
    }

    if domain:
        params['website'] = domain

    try:
        response = http_requests.get(url, params=params, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            company = data.get('data', {})
            return {
                'email': company.get('emails', [None])[0],
                'phone': company.get('phone'),
                'website': company.get('website'),
                'company': company.get('name'),
                'location': company.get('location'),
                'source': 'pdl'
            }
    except Exception as e:
        print(f"PDL error: {e}")

    return None


def search_findthatlead(domain, api_key=None):
    """
    Search for leads using FindThatLead API
    Free tier: 50 emails/month
    """
    if not api_key:
        return None

    url = f"https://api.findthatlead.com/v1/companies/{domain}"
    headers = {
        'Authorization': f'Bearer {api_key}'
    }

    try:
        response = http_requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            company = data.get('company', {})
            emails = company.get('emails', [])
            return {
                'email': emails[0] if emails else None,
                'phone': company.get('phone'),
                'website': company.get('website'),
                'company': company.get('name'),
                'source': 'findthatlead'
            }
    except Exception as e:
        print(f"FindThatLead error: {e}")

    return None


@app.route('/api/enrich/external', methods=['POST'])
@limiter.limit("50/hour")
def enrich_with_external_apis():
    """
    Enrich a lead using external APIs (Apollo.io, PDL, FindThatLead)
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    company_name = data.get('company_name', '').strip()
    domain = data.get('domain', '').strip()

    # API keys (can be stored in DB or env vars)
    apollo_key = os.environ.get('APOLLO_API_KEY')
    pdl_key = os.environ.get('PDL_API_KEY')
    findthatlead_key = os.environ.get('FINDTHATLEAD_API_KEY')

    results = []

    # Try Apollo.io
    if apollo_key:
        result = search_apollo_io(company_name, domain, apollo_key)
        if result:
            results.append(result)

    # Try PDL
    if pdl_key:
        result = search_pdl(company_name, domain, pdl_key)
        if result:
            results.append(result)

    # Try FindThatLead
    if findthatlead_key and domain:
        result = search_findthatlead(domain, findthatlead_key)
        if result:
            results.append(result)

    return jsonify({
        'results': results,
        'total': len(results)
    })
"""
AUTO-SYNC TO ALEXANDREQUEIROZ.COM.BR API
Add this code to app.py after line ~300 (after DB connection pool setup)
"""

# ============= Alexandre Queiroz API Sync =============

ALEXANDREQUEIROZ_API = 'https://api.alexandrequeiroz.com.br'
ALEXANDREQUEIROZ_EMAIL = 'admin@alexandrequeiroz.com.br'
ALEXANDREQUEIROZ_PASSWORD = '1982Xandeq1982#'

# Global token cache (expires in 6 hours)
_alexandrequeiroz_token = None
_alexandrequeiroz_token_expires = None

def get_alexandrequeiroz_token():
    """Get or refresh API token for alexandrequeiroz.com.br"""
    global _alexandrequeiroz_token, _alexandrequeiroz_token_expires

    # Check if token is still valid (with 1 minute buffer)
    if _alexandrequeiroz_token and _alexandrequeiroz_token_expires:
        if datetime.now() < (_alexandrequeiroz_token_expires - timedelta(minutes=1)):
            return _alexandrequeiroz_token

    # Login to get new token
    try:
        response = http_requests.post(
            f'{ALEXANDREQUEIROZ_API}/api/v1/auth/login',
            json={
                'email': ALEXANDREQUEIROZ_EMAIL,
                'password': ALEXANDREQUEIROZ_PASSWORD
            },
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            _alexandrequeiroz_token = data.get('token')
            # Token expires in 6 hours
            _alexandrequeiroz_token_expires = datetime.now() + timedelta(hours=6)
            print(f"[SYNC] Obtained new token for alexandrequeiroz.com.br")
            return _alexandrequeiroz_token
        else:
            print(f"[SYNC] Login failed: {response.status_code} - {response.text[:200]}")
            return None
    except Exception as e:
        print(f"[SYNC] Login error: {e}")
        return None


def sync_lead_to_alexandrequeiroz(lead_data):
    """
    Sync a single lead to alexandrequeiroz.com.br API
    Returns: (success: bool, message: str, customer_id: str or None)
    """
    token = get_alexandrequeiroz_token()
    if not token:
        return False, "Failed to obtain API token", None

    # Extract and validate data
    email = (lead_data.get('email') or '').strip()
    if not email or '@' not in email:
        return False, "Invalid email", None

    company_name = lead_data.get('company_name') or lead_data.get('name') or 'Lead sem nome'
    phone = lead_data.get('phone') or None
    website = lead_data.get('website') or None
    city = lead_data.get('city') or None
    state = lead_data.get('state') or None

    # Build payload matching alexandrequeiroz.com.br schema
    payload = {
        'name': company_name,
        'companyName': company_name,
        'email': email,
        'phone': phone,
        'website': website,
    }

    # Optional fields
    if city and state:
        # API may accept address field or separate city/state
        payload['notes'] = f"Origem: Extrator de Dados\nCidade: {city}\nEstado: {state}"

    # Add source information
    source = lead_data.get('source', 'extrator-dados')
    if source:
        if 'notes' in payload:
            payload['notes'] += f"\nFonte: {source}"
        else:
            payload['notes'] = f"Origem: Extrator de Dados\nFonte: {source}"

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    try:
        # First, check if lead already exists (GET with email filter)
        check_response = http_requests.get(
            f'{ALEXANDREQUEIROZ_API}/api/v1/customers',
            headers=headers,
            params={'search': email, 'pageSize': 1},
            timeout=10
        )

        if check_response.status_code == 200:
            data = check_response.json()
            items = data.get('items', [])

            # If lead exists, check if it's the same email
            if items and len(items) > 0:
                existing_lead = items[0]
                existing_email = (existing_lead.get('email') or '').strip().lower()
                if existing_email == email.lower():
                    customer_id = existing_lead.get('id')
                    return True, f"Lead already exists (skipped)", customer_id

        # Lead doesn't exist, create it
        create_response = http_requests.post(
            f'{ALEXANDREQUEIROZ_API}/api/v1/customers',
            headers=headers,
            json=payload,
            timeout=15
        )

        if create_response.status_code in [200, 201]:
            result = create_response.json()
            customer_id = result.get('id')
            print(f"[SYNC] ✅ Created lead: {email} -> ID: {customer_id}")
            return True, "Lead created successfully", customer_id
        elif create_response.status_code == 409:
            # Conflict - lead already exists
            return True, "Lead already exists (409)", None
        else:
            error_msg = create_response.text[:200]
            print(f"[SYNC] ❌ Failed to create lead: {create_response.status_code} - {error_msg}")
            return False, f"API error: {create_response.status_code}", None

    except Exception as e:
        print(f"[SYNC] ❌ Exception syncing lead: {e}")
        return False, f"Exception: {str(e)[:100]}", None


def sync_leads_batch_to_alexandrequeiroz(leads_list, max_leads=100):
    """
    Sync multiple leads to alexandrequeiroz.com.br
    Returns: (total_synced: int, total_skipped: int, total_errors: int)
    """
    synced = 0
    skipped = 0
    errors = 0

    for lead in leads_list[:max_leads]:
        success, message, customer_id = sync_lead_to_alexandrequeiroz(lead)

        if success:
            if "already exists" in message or "skipped" in message:
                skipped += 1
            else:
                synced += 1
        else:
            errors += 1

        # Small delay to avoid rate limiting
        time.sleep(0.2)

    print(f"[SYNC] Batch sync complete: {synced} created, {skipped} skipped, {errors} errors")
    return synced, skipped, errors


def auto_sync_new_leads_background(batch_id):
    """
    Background thread to automatically sync new leads from a batch
    to alexandrequeiroz.com.br API
    """
    print(f"[SYNC] Starting auto-sync for batch {batch_id}")

    # Wait 5 seconds to let the extraction process start
    time.sleep(5)

    # Get dedicated DB connection for this thread
    conn = psycopg2.connect(**DB_CONFIG)
    c = conn.cursor()

    try:
        # Wait up to 10 minutes for batch to complete
        max_wait = 600  # 10 minutes
        elapsed = 0

        while elapsed < max_wait:
            # Check batch status
            c.execute('SELECT status FROM batches WHERE id = %s', (batch_id,))
            row = c.fetchone()

            if not row:
                print(f"[SYNC] Batch {batch_id} not found")
                return

            status = row[0]

            if status == 'completed':
                break
            elif status == 'failed':
                print(f"[SYNC] Batch {batch_id} failed, aborting sync")
                return

            # Wait 10 seconds before checking again
            time.sleep(10)
            elapsed += 10

        # Get all leads from this batch
        c.execute(
            '''SELECT company_name, email, phone, website, city, state, source
               FROM leads
               WHERE batch_id = %s AND email IS NOT NULL AND email != \'\'
               ORDER BY extracted_at DESC''',
            (batch_id,)
        )
        rows = c.fetchall()

        if not rows:
            print(f"[SYNC] No leads with email found for batch {batch_id}")
            return

        leads_to_sync = []
        for row in rows:
            leads_to_sync.append({
                'company_name': row[0],
                'email': row[1],
                'phone': row[2],
                'website': row[3],
                'city': row[4],
                'state': row[5],
                'source': row[6] or 'extrator-dados',
            })

        print(f"[SYNC] Found {len(leads_to_sync)} leads to sync for batch {batch_id}")

        # Sync in batches of 50
        synced, skipped, errors = sync_leads_batch_to_alexandrequeiroz(leads_to_sync, max_leads=200)

        print(f"[SYNC] ✅ Batch {batch_id} sync complete: {synced} created, {skipped} skipped, {errors} errors")

    except Exception as e:
        print(f"[SYNC] ❌ Error in auto-sync for batch {batch_id}: {e}")
    finally:
        c.close()
        conn.close()


# IMPORTANT: Add these lines in the endpoints that create leads:
# - After creating a batch in /api/batch
# - After creating a batch in /api/search
# - After importing leads in /api/leads/import
#
# Example:
# threading.Thread(target=auto_sync_new_leads_background, args=(batch_id,), daemon=True).start()
