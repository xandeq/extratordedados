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

def normalize_email(email_str):
    """Normalize and validate an email address."""
    email_str = email_str.strip().lower()
    email_str = email_str.rstrip('.')
    for ext in INVALID_EMAIL_EXTENSIONS:
        if email_str.endswith(ext):
            return None
    if '@' not in email_str or '.' not in email_str.split('@')[-1]:
        return None
    if len(email_str) > 320:
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

            # Check for CAPTCHA
            if 'captcha' in resp.text.lower() or 'robot' in resp.text.lower():
                if safety:
                    safety.record_error('captcha')
                print(f"[search] DDG CAPTCHA detected on page {page+1}")
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

            if 'captcha' in resp.text.lower():
                if safety:
                    safety.record_error('captcha')
                print(f"[search] Bing CAPTCHA detected on page {page+1}")
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


def search_with_fallback(query, max_pages=2, safety=None):
    """Search DuckDuckGo first, fallback to Bing if no results. Detailed logging!"""
    engine_used = 'duckduckgo'
    print(f"\n[WEBSEARCH] Iniciando busca web para: '{query}'")
    print(f"[WEBSEARCH] Tentativa 1: DuckDuckGo (max_pages={max_pages})")
    results = search_duckduckgo(query, max_pages, safety)
    print(f"[WEBSEARCH] DDG resultado: {len(results)} URLs encontradas")

    if not results:
        delay = random.uniform(3, 6)
        print(f"[WEBSEARCH] DDG falhou! Esperando {delay:.1f}s antes de tentar Bing...")
        engine_used = 'bing'
        time.sleep(delay)
        print(f"[WEBSEARCH] Tentativa 2: Bing")
        results = search_bing(query, max_pages, safety)
        print(f"[WEBSEARCH] Bing resultado: {len(results)} URLs encontradas")

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
        for prov in ('hunter', 'snov'):
            cfg = get_api_config(c, user_id, prov)
            credits = get_api_credits_remaining(c, user_id, prov) if cfg else 0
            status = f"ativa, {credits} creditos restantes" if cfg else "NAO configurada"
            print(f"[JOB] API {prov}: {status}")
            log_search(c, search_jobs_data[0]['search_job_id'], 'config_check',
                      message=f'API {prov}: {status}')

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
                # ─── Phase 1: Domain Discovery via Web Search ───
                log_search(c, search_job_id, 'phase1',
                          message=f'FASE 1: Cacando dominios no DuckDuckGo/Bing para "{query}"...')

                start_time = time.time()
                results, engine_used = search_with_fallback(query, max_pages, safety)
                search_duration = int((time.time() - start_time) * 1000)

                c.execute('UPDATE search_jobs SET engine = %s, total_results = %s WHERE id = %s',
                          (engine_used, len(results), search_job_id))

                if results:
                    domains_found = [urlparse(r['url']).hostname for r in results if urlparse(r['url']).hostname]
                    log_search(c, search_job_id, 'search_ok',
                              message=f'Boa! {engine_used} achou {len(results)} dominios em {search_duration}ms: {", ".join(domains_found[:5])}{"..." if len(domains_found) > 5 else ""}',
                              duration_ms=search_duration)
                    print(f"[BUSCA] {engine_used} retornou {len(results)} resultados em {search_duration}ms")
                    for r in results[:5]:
                        print(f"[BUSCA]   -> {r['url']}")
                else:
                    log_search(c, search_job_id, 'search_blocked',
                              message=f'Bloqueado! {engine_used} retornou 0 resultados em {search_duration}ms (CAPTCHA/IP bloqueado). Sem dominios para enriquecer via API.',
                              duration_ms=search_duration)
                    print(f"[BUSCA] BLOQUEADO! {engine_used} = 0 resultados. DDG e Bing com CAPTCHA.")

                    # Log skip reason - no candidate domain generation
                    log_search(c, search_job_id, 'search_skip',
                              message=f'Sem dominios reais encontrados. APIs precisam de dominios reais para buscar emails. Pulando {city}.')

                # ─── Phase 2: Enrich via API (Hunter/Snov) + Scraping Fallback ───
                if results:
                    log_search(c, search_job_id, 'phase2',
                              message=f'FASE 2: Enriquecendo {len(results)} dominios via Hunter.io / Snov.io...')

                job_leads = 0
                job_source = 'scraping'
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

                summary_msg = f'Fim! {city}/{state}: {job_leads} leads encontrados via {job_source}'
                if job_leads == 0 and not results:
                    summary_msg = f'Fim! {city}/{state}: 0 leads (busca web bloqueada, sem dominios para APIs)'
                elif job_leads == 0 and results:
                    summary_msg = f'Fim! {city}/{state}: 0 leads ({len(results)} dominios testados, nenhum tinha emails)'
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

    if provider not in ('hunter', 'snov'):
        return jsonify({'error': 'Provider invalido (hunter ou snov)'}), 400
    if not api_key:
        return jsonify({'error': 'API key obrigatoria'}), 400
    if provider == 'snov' and not api_secret:
        return jsonify({'error': 'Client Secret obrigatorio para Snov.io'}), 400

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

    month_year = datetime.now().strftime('%Y-%m')

    with get_db() as conn:
        c = conn.cursor()
        configs = []
        for provider in ('hunter', 'snov'):
            c.execute(
                'SELECT api_key, api_secret, is_active, updated_at FROM api_configs WHERE user_id = %s AND provider = %s',
                (user_id, provider)
            )
            config_row = c.fetchone()

            c.execute(
                'SELECT credits_used, credits_limit FROM api_usage WHERE user_id = %s AND provider = %s AND month_year = %s',
                (user_id, provider, month_year)
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
                'month': month_year,
            })

    return jsonify({'configs': configs})


@app.route('/api/api-config/<provider>', methods=['DELETE'])
@limiter.limit("10/minute")
def delete_api_config_endpoint(provider):
    """Remove API config for a provider."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    if provider not in ('hunter', 'snov'):
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

    # Check if user has any API configured
    has_apis = False
    with get_db() as conn:
        c = conn.cursor()
        for provider in ('hunter', 'snov'):
            config = get_api_config(c, user_id, provider)
            if config and get_api_credits_remaining(c, user_id, provider) > 0:
                has_apis = True
                break

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

# ============= API Enrichment Functions =============

API_CREDIT_LIMITS = {'hunter': 25, 'snov': 50}

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
    """Get remaining API credits for current month."""
    month_year = datetime.now().strftime('%Y-%m')
    cursor.execute(
        'SELECT credits_used, credits_limit FROM api_usage WHERE user_id = %s AND provider = %s AND month_year = %s',
        (user_id, provider, month_year)
    )
    row = cursor.fetchone()
    if not row:
        return API_CREDIT_LIMITS.get(provider, 0)
    return max(0, row[1] - row[0])


def record_api_usage(cursor, user_id, provider, cost=1):
    """Record API credit usage for current month (upsert)."""
    month_year = datetime.now().strftime('%Y-%m')
    limit = API_CREDIT_LIMITS.get(provider, 0)
    cursor.execute(
        '''INSERT INTO api_usage (user_id, provider, month_year, credits_used, credits_limit)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (user_id, provider, month_year)
           DO UPDATE SET credits_used = api_usage.credits_used + %s''',
        (user_id, provider, month_year, cost, limit, cost)
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
    """Derive a company/contact name from an email address.
    For business domains: uses the domain name (e.g., contato@acme.com.br -> Acme)
    For generic providers: uses the local part (e.g., joao.silva@gmail.com -> Joao Silva)
    """
    if not email or '@' not in email:
        return ''
    local_part, domain = email.lower().split('@', 1)
    if not domain:
        return ''

    def normalize(raw):
        import re as _re
        name = _re.sub(r'\d+$', '', raw)           # remove trailing numbers
        name = _re.sub(r'[._\-]+', ' ', name)      # dots/underscores/hyphens -> spaces
        name = _re.sub(r'\s+', ' ', name).strip()   # collapse spaces
        if not name:
            return ''
        return ' '.join(w.capitalize() for w in name.split())

    if domain in GENERIC_EMAIL_PROVIDERS:
        return normalize(local_part)
    else:
        domain_name = domain.split('.')[0]
        return normalize(domain_name)


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
