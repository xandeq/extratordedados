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
import queue
import random
import time
import logging
import logging.handlers
import traceback
from urllib.parse import urlparse, urljoin, quote as requests_quote

# ── Structured error logger for scraper ──────────────────────────────────────
_scraper_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scraper_errors.log')
_scraper_logger = logging.getLogger('scraper_errors')
_scraper_logger.setLevel(logging.DEBUG)
if not _scraper_logger.handlers:
    _fh = logging.handlers.RotatingFileHandler(
        _scraper_log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8'
    )
    _fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%dT%H:%M:%S'))
    _scraper_logger.addHandler(_fh)


# ── DB log queue (written by background thread) ────────────────────────────────
_log_queue: queue.Queue = queue.Queue(maxsize=2000)


def _db_log_writer():
    """Daemon thread: drains _log_queue and inserts into system_logs table."""
    import psycopg2 as _pg2
    # Delay until DB_CONFIG is populated (app finishes importing)
    time.sleep(3)
    while True:
        try:
            item = _log_queue.get(timeout=5)
            if item is None:
                break
            # Support both old 6-tuple and new 8-tuple format
            if len(item) == 6:
                level, provider, q_text, message, exc_text, fix_prompt = item
                error_type, extra_json = None, None
            else:
                level, provider, q_text, message, exc_text, fix_prompt, error_type, extra_json = item
            try:
                conn = _pg2.connect(**DB_CONFIG)
                c = conn.cursor()
                c.execute(
                    '''INSERT INTO system_logs (level, provider, query, message, exception, fix_prompt, error_type, extra_data)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                    (level, provider, q_text, message, exc_text, fix_prompt, error_type, extra_json)
                )
                conn.commit()
                conn.close()
            except Exception:
                pass  # never crash the writer
        except queue.Empty:
            continue
        except Exception:
            continue


_db_log_writer_thread = threading.Thread(target=_db_log_writer, daemon=True)
_db_log_writer_thread.start()


APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(APP_DIR)
REPO_ROOT = os.path.dirname(PROJECT_DIR)
SECRETS_CACHE_PATH = os.path.join(REPO_ROOT, '.secrets.cache.json')
LOCAL_SECRET_ENV_FILES = [
    os.path.join(REPO_ROOT, '.deploy.env'),
    os.path.join(REPO_ROOT, '.env'),
    os.path.join(PROJECT_DIR, '.env'),
    os.path.join(APP_DIR, '.env'),
]

_aws_secret_blob_cache = {}
_aws_secret_blob_failures = {}
_local_secret_cache = None

os.environ.setdefault('AWS_EC2_METADATA_DISABLED', 'true')


def _load_env_file_into_environ(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding='utf-8') as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    os.environ.setdefault(key, value)
    except Exception:
        pass


for _env_file in LOCAL_SECRET_ENV_FILES:
    _load_env_file_into_environ(_env_file)


def _normalize_env_aliases():
    alias_pairs = [
        ('DB_PASS', 'DB_PASSWORD'),
        ('CRM_PASSWORD', 'CRM_PASS'),
        ('SYNC_PASSWORD', 'CRM_PASS'),
        ('SYNC_EMAIL', 'CRM_EMAIL'),
        ('APIFY_API_KEY', 'APIFY_TOKEN'),
        ('INSTAGRAM_USERNAME', 'INSTAGRAM_USER'),
        ('INSTAGRAM_PASSWORD', 'INSTAGRAM_PASS'),
        ('LINKEDIN_USERNAME', 'LINKEDIN_USER'),
        ('LINKEDIN_PASSWORD', 'LINKEDIN_PASS'),
    ]
    for source_key, target_key in alias_pairs:
        if os.environ.get(source_key) and not os.environ.get(target_key):
            os.environ[target_key] = os.environ[source_key]


_normalize_env_aliases()


def _load_local_secret_cache():
    global _local_secret_cache
    if _local_secret_cache is not None:
        return _local_secret_cache
    try:
        import json as _json
        with open(SECRETS_CACHE_PATH, encoding='utf-8') as f:
            _local_secret_cache = _json.load(f)
        if not isinstance(_local_secret_cache, dict):
            _local_secret_cache = {}
    except Exception:
        _local_secret_cache = {}
    return _local_secret_cache


def _save_local_secret_cache():
    try:
        import json as _json
        cache = _load_local_secret_cache()
        with open(SECRETS_CACHE_PATH, 'w', encoding='utf-8') as f:
            _json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _cache_secret_blob(secret_id, secret_data):
    if not secret_id or not isinstance(secret_data, dict):
        return
    cache = _load_local_secret_cache()
    cache[secret_id] = secret_data
    _save_local_secret_cache()


def _get_cached_secret_blob(secret_id):
    if not secret_id:
        return None
    cache = _load_local_secret_cache()
    data = cache.get(secret_id)
    return data if isinstance(data, dict) else None


def _fetch_secret_blob_from_aws(secret_id):
    if not secret_id:
        return None
    if secret_id in _aws_secret_blob_cache:
        return _aws_secret_blob_cache[secret_id]

    last_failure = _aws_secret_blob_failures.get(secret_id)
    if last_failure and (time.time() - last_failure) < 300:
        return None

    try:
        import boto3
        import json as _json
        from botocore.config import Config as _BotoConfig

        client = boto3.client(
            'secretsmanager',
            region_name='us-east-1',
            config=_BotoConfig(connect_timeout=2, read_timeout=3, retries={'max_attempts': 1}),
        )
        response = client.get_secret_value(SecretId=secret_id)
        secret_string = response.get('SecretString') or '{}'
        secret_data = _json.loads(secret_string)
        if isinstance(secret_data, dict):
            _aws_secret_blob_cache[secret_id] = secret_data
            _cache_secret_blob(secret_id, secret_data)
            return secret_data
    except Exception:
        _aws_secret_blob_failures[secret_id] = time.time()
    return None


def _read_secret_key_from_blob(secret_blob, candidate_keys):
    if not isinstance(secret_blob, dict):
        return None
    for key in candidate_keys:
        value = secret_blob.get(key)
        if value:
            return value
    return None


def _get_secret_from_db(provider, field='api_key'):
    if not provider or field not in ('api_key', 'api_secret'):
        return None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            f"SELECT {field} FROM api_configs WHERE provider = %s AND is_active = TRUE "
            "ORDER BY updated_at DESC NULLS LAST LIMIT 1",
            (provider,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return None


def resolve_secret_value(key, secret_ids=None, env_keys=None, db_provider=None, db_field='api_key', default=''):
    candidate_keys = []
    if env_keys:
        candidate_keys.extend([k for k in env_keys if k])
    if key and key not in candidate_keys:
        candidate_keys.insert(0, key)

    for env_key in candidate_keys:
        value = os.environ.get(env_key)
        if value:
            return value

    for secret_id in (secret_ids or []):
        live_blob = _fetch_secret_blob_from_aws(secret_id)
        value = _read_secret_key_from_blob(live_blob, candidate_keys)
        if value:
            return value

    for secret_id in (secret_ids or []):
        cached_blob = _get_cached_secret_blob(secret_id)
        value = _read_secret_key_from_blob(cached_blob, candidate_keys)
        if value:
            return value

    if db_provider:
        db_value = _get_secret_from_db(db_provider, db_field)
        if db_value:
            return db_value

    return default


def warm_secrets_cache():
    """Best effort: hydrate local cache while AWS is available."""
    for secret_id in ('extratordedados/prod', 'tools/rapidapi', 'tools/serper', 'tools/apify'):
        _fetch_secret_blob_from_aws(secret_id)


warm_secrets_cache()


def _classify_error(msg, exc_text):
    """Classify error type based on message and exception text."""
    combined = f'{msg or ""} {exc_text or ""}'.lower()
    if any(k in combined for k in ('rate limit', 'rate_limit', 'ratelimit', '429', 'too many requests')):
        return 'rate_limit'
    if any(k in combined for k in ('quota', 'insufficient_quota', 'quotaexceedederror', 'billing', 'credits', 'creditos', '402')):
        return 'quota_exceeded'
    if any(k in combined for k in ('timeout', 'timed out', 'connect timeout', 'read timeout')):
        return 'network_timeout'
    if any(k in combined for k in ('connection', 'connectionerror', 'connection refused', 'dns', 'unreachable')):
        return 'connection_error'
    if any(k in combined for k in ('parse', 'parsing', 'json', 'decode', 'keyerror', 'indexerror', 'attributeerror')):
        return 'parsing_error'
    if any(k in combined for k in ('blocked', 'captcha', 'forbidden', '403', 'access denied')):
        return 'scraping_blocked'
    if any(k in combined for k in ('sem resultados', 'no results', 'noresult', 'empty response')):
        return 'no_results'
    if any(k in combined for k in ('html', 'selector', 'element', 'structure')):
        return 'html_structure_changed'
    if any(k in combined for k in ('unavailable', '503', '502', '500', 'server error', 'internal server')):
        return 'provider_unavailable'
    if any(k in combined for k in ('auth', 'unauthorized', '401', 'invalid key', 'chave invalida')):
        return 'auth_error'
    if any(k in combined for k in ('duplicate', 'unique', 'already exists', 'duplicat')):
        return 'duplicate_error'
    if any(k in combined for k in ('retryerror', 'tentativas esgotadas', 'retry exhausted')):
        return 'retry_exhausted'
    return 'unknown'


def _build_fix_prompt(level, provider, query, msg, exc_text, error_type=None, extra=None):
    """Generate a ready-to-paste Claude fix prompt for this error/warning."""
    import inspect
    frame = inspect.stack()
    caller_fn = frame[2].function if len(frame) > 2 else 'desconhecida'
    caller_file = os.path.basename(frame[2].filename) if len(frame) > 2 else 'desconhecido'
    if not error_type:
        error_type = _classify_error(msg, exc_text)

    extra = extra or {}
    prompt = (
        f"Analise o seguinte erro ocorrido no sistema de scraping de leads.\n\n"
        f"## Informações do Erro\n"
        f"- **Nível**: {level}\n"
        f"- **Tipo de Erro**: {error_type}\n"
        f"- **Provider/Módulo**: {provider}\n"
        f"- **Query/Contexto**: {query}\n"
        f"- **Mensagem**: {msg}\n"
        f"- **Exceção**: {exc_text or 'N/A'}\n"
        f"- **Função**: {caller_fn}\n"
        f"- **Arquivo**: {caller_file}\n"
    )
    if extra.get('endpoint'):
        prompt += f"- **Endpoint**: {extra['endpoint']}\n"
    if extra.get('source_url'):
        prompt += f"- **URL/Fonte**: {extra['source_url']}\n"
    if extra.get('execution_time_ms'):
        prompt += f"- **Tempo de execução**: {extra['execution_time_ms']}ms\n"
    if extra.get('retry_count'):
        prompt += f"- **Tentativas**: {extra['retry_count']}\n"
    if extra.get('request_params'):
        prompt += f"- **Parâmetros**: {extra['request_params']}\n"

    prompt += (
        f"\n## Contexto\n"
        f"O sistema estava realizando {'busca automática de leads' if not extra.get('context') else extra['context']} "
        f"usando o provider {provider}.\n\n"
        f"## Objetivo da análise\n"
        f"1. Identifique a causa raiz do erro\n"
        f"2. Proponha correção no código (mostre o código corrigido)\n"
        f"3. Explique o que causou o problema\n"
        f"4. Sugira melhorias para evitar que o erro aconteça novamente\n"
        f"5. Sugira fallback provider caso este falhe\n"
    )
    return prompt


def scraper_log(level, provider, query, msg, exc=None, **kwargs):
    """Structured log helper. level: DEBUG/INFO/WARNING/ERROR/CRITICAL.
    Always logs to file. Only persists ERROR/WARNING/CRITICAL to DB.
    Optional kwargs: endpoint, source_url, execution_time_ms, retry_count,
    request_params, context (stored as JSON in extra_data column)."""
    record = f'provider={provider} query="{query}" msg={msg}'
    exc_text = None
    if exc:
        exc_text = f'{type(exc).__name__}: {exc}'
        record += f' exc={exc_text}'
    getattr(_scraper_logger, level.lower())(record)
    # Only persist ERROR, WARNING, CRITICAL to DB (not DEBUG/INFO)
    if level.upper() in ('ERROR', 'WARNING', 'CRITICAL'):
        error_type = _classify_error(str(msg), exc_text)
        extra = {k: v for k, v in kwargs.items() if v is not None} if kwargs else {}
        fix_prompt = _build_fix_prompt(level.upper(), provider, query, str(msg), exc_text, error_type, extra)
        import json as _json
        extra_json = _json.dumps(extra, ensure_ascii=False, default=str) if extra else None
        try:
            _log_queue.put_nowait((level.upper(), provider, query, str(msg), exc_text, fix_prompt, error_type, extra_json))
        except queue.Full:
            pass


def persist_system_log(level, provider, query, message, exception_text=None, **kwargs):
    """Persist a structured system log entry to the same queue used by /app-logs."""
    error_type = _classify_error(str(message), exception_text)
    extra = {k: v for k, v in kwargs.items() if v is not None} if kwargs else {}
    fix_prompt = _build_fix_prompt(level.upper(), provider, query, str(message), exception_text, error_type, extra)
    import json as _json
    extra_json = _json.dumps(extra, ensure_ascii=False, default=str) if extra else None
    try:
        _log_queue.put_nowait((
            level.upper(),
            provider,
            query,
            str(message),
            exception_text,
            fix_prompt,
            error_type,
            extra_json,
        ))
    except queue.Full:
        pass


def _stack_trace_text(exc=None):
    if exc and getattr(exc, '__traceback__', None):
        return ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))[:4000]
    return ''.join(traceback.format_stack(limit=20))[-4000:]


def _log_send_to_crm_failure(*, user_id=None, filters=None, lead_ids=None, crm_api_url=None,
                             error_message='', exc=None, stack_text=None, status_code=None,
                             stage=None, response_body=None, total_leads=None, source='backend'):
    stack_text = (stack_text or '').strip() or _stack_trace_text(exc)
    persist_system_log(
        'ERROR',
        'send_leads_to_crm',
        'send_leads_to_crm',
        error_message[:1000],
        stack_text,
        action='send_leads_to_crm',
        timestamp=datetime.now().isoformat(),
        user_id=user_id,
        filters=filters or {},
        lead_ids=lead_ids or [],
        crm_api_url=crm_api_url,
        status_code=status_code,
        stage=stage,
        response_body=response_body[:1000] if isinstance(response_body, str) else response_body,
        total_leads=total_leads,
        source=source,
        endpoint='/api/leads/send-to-crm',
        request_params={
            'filters': filters or {},
            'lead_ids': lead_ids or [],
        },
        context=f'action=send_leads_to_crm stage={stage or "unknown"} user_id={user_id}',
    )


def _persist_thread_errors(provider: str):
    """
    Decorator factory: wraps background thread functions with a top-level
    exception handler that persists any unhandled exception to system_logs.
    Ensures crashes in daemon threads are always recorded in the database.
    """
    import functools
    import traceback as _tb

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                tb_str = _tb.format_exc()
                msg = f'Unhandled exception in {fn.__name__}: {type(exc).__name__}: {exc}'
                print(f'[CRITICAL][{provider.upper()}] {msg}\n{tb_str}')
                # Log via scraper_log (enqueues to DB)
                scraper_log('CRITICAL', provider, str(args[:1]), msg, exc)
                # Also try direct DB insert as fallback (in case queue writer is down)
                try:
                    import psycopg2 as _pg2
                    _error_type = _classify_error(msg, tb_str[:500])
                    _fix_prompt = _build_fix_prompt('CRITICAL', provider, str(args[:1]), msg, tb_str[:500], _error_type)
                    _conn = _pg2.connect(**DB_CONFIG)
                    _c = _conn.cursor()
                    _c.execute(
                        '''INSERT INTO system_logs (level, provider, query, message, exception, fix_prompt, error_type)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                        ('CRITICAL', provider, str(args[:1])[:500], msg[:1000], tb_str[:4000], _fix_prompt[:5000], _error_type)
                    )
                    _conn.commit()
                    _conn.close()
                except Exception:
                    pass  # never let the error handler itself crash
        return wrapper
    return decorator


# ── Scraper custom exceptions ─────────────────────────────────────────────────
class QuotaExceededError(Exception):
    """Rate limit / quota exhausted — safe to retry after backoff."""

class BlockedError(Exception):
    """IP / fingerprint blocked — skip this provider."""

class CaptchaError(Exception):
    """CAPTCHA detected — do not retry immediately."""

class ConfigError(Exception):
    """Missing configuration (API key, credentials) — do NOT retry, fail immediately."""


# ── Tenacity (retry with backoff) ─────────────────────────────────────────────
try:
    from tenacity import (
        retry, stop_after_attempt, wait_exponential,
        retry_if_exception_type, RetryError
    )
    _TENACITY_AVAILABLE = True
except ImportError:
    _TENACITY_AVAILABLE = False
    # Minimal stub so code below works even without tenacity installed
    class RetryError(Exception): pass
    def retry(*a, **kw):
        def decorator(fn):
            return fn
        return decorator
    def stop_after_attempt(n): return None
    def wait_exponential(**kw): return None
    def retry_if_exception_type(t): return None

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

# DNS resolver for MX validation (Phase 1)
try:
    import dns.resolver as _dns_resolver
    _DNS_AVAILABLE = True
except ImportError:
    _DNS_AVAILABLE = False
    _dns_resolver = None

# PDF extraction (Phase 2 — imported lazily per call)
# rapidfuzz for fuzzy dedup (Phase 3 — imported lazily per call)

app = Flask(__name__)
app.config['PROPAGATE_EXCEPTIONS'] = True

# Trust X-Forwarded-For from Traefik reverse proxy
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    import pytz
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    _APSCHEDULER_AVAILABLE = False

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
    'password': os.environ.get('DB_PASSWORD', ''),
}

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = hashlib.sha256(os.environ.get('ADMIN_PASSWORD', '').encode()).hexdigest()

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
    # ---- Sudeste ----
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
    'sp_zona_sul': {
        'name': 'Sao Paulo Zona Sul - SP',
        'state': 'SP',
        'cities': ['Santo Amaro', 'Ipiranga', 'Jabaquara', 'Campo Limpo', 'M Boi Mirim', 'Cidade Ademar', 'Parelheiros'],
        'neighborhood': True,
    },
    'sp_zona_norte': {
        'name': 'Sao Paulo Zona Norte - SP',
        'state': 'SP',
        'cities': ['Santana', 'Tucuruvi', 'Casa Verde', 'Freguesia do O', 'Jaragua', 'Perus', 'Pirituba'],
        'neighborhood': True,
    },
    'sp_zona_leste': {
        'name': 'Sao Paulo Zona Leste - SP',
        'state': 'SP',
        'cities': ['Penha', 'Ermelino Matarazzo', 'Sao Mateus', 'Cidade Tiradentes', 'Itaquera', 'Aricanduva'],
        'neighborhood': True,
    },
    'sp_zona_oeste': {
        'name': 'Sao Paulo Zona Oeste - SP',
        'state': 'SP',
        'cities': ['Lapa', 'Pinheiros', 'Vila Leopoldina', 'Butanta', 'Rio Pequeno', 'Raposo Tavares'],
        'neighborhood': True,
    },
    'grande_rj': {
        'name': 'Grande Rio de Janeiro - RJ',
        'state': 'RJ',
        'cities': ['Rio de Janeiro', 'Niteroi', 'Sao Goncalo', 'Duque de Caxias', 'Nova Iguacu', 'Petropolis'],
    },
    'rj_zona_sul': {
        'name': 'Rio de Janeiro Zona Sul - RJ',
        'state': 'RJ',
        'cities': ['Ipanema', 'Copacabana', 'Botafogo', 'Flamengo', 'Laranjeiras', 'Gavea', 'Barra da Tijuca'],
        'neighborhood': True,
    },
    'grande_bh': {
        'name': 'Grande Belo Horizonte - MG',
        'state': 'MG',
        'cities': ['Belo Horizonte', 'Contagem', 'Betim', 'Ribeirao das Neves', 'Santa Luzia', 'Sabara'],
    },
    'bh_zonas': {
        'name': 'BH Centro e Bairros - MG',
        'state': 'MG',
        'cities': ['Savassi', 'Lourdes', 'Funcionarios', 'Pampulha', 'Santa Efigenia', 'Buritis', 'Venda Nova'],
        'neighborhood': True,
    },
    'grande_campinas': {
        'name': 'Grande Campinas - SP',
        'state': 'SP',
        'cities': ['Campinas', 'Americana', 'Limeira', 'Piracicaba', 'Sumare', 'Hortolandia', 'Indaiatuba'],
    },
    # ---- Sul ----
    'grande_curitiba': {
        'name': 'Grande Curitiba - PR',
        'state': 'PR',
        'cities': ['Curitiba', 'Sao Jose dos Pinhais', 'Colombo', 'Araucaria', 'Campo Largo', 'Pinhais', 'Almirante Tamandare'],
    },
    'grande_porto_alegre': {
        'name': 'Grande Porto Alegre - RS',
        'state': 'RS',
        'cities': ['Porto Alegre', 'Canoas', 'Novo Hamburgo', 'Sao Leopoldo', 'Pelotas', 'Caxias do Sul', 'Gravataí'],
    },
    'grande_florianopolis': {
        'name': 'Grande Florianopolis - SC',
        'state': 'SC',
        'cities': ['Florianopolis', 'Sao Jose', 'Palhoca', 'Biguacu', 'Governador Celso Ramos', 'Tijucas'],
    },
    # ---- Nordeste ----
    'grande_fortaleza': {
        'name': 'Grande Fortaleza - CE',
        'state': 'CE',
        'cities': ['Fortaleza', 'Caucaia', 'Maracanau', 'Juazeiro do Norte', 'Sobral', 'Crato', 'Iguatu'],
    },
    'grande_recife': {
        'name': 'Grande Recife - PE',
        'state': 'PE',
        'cities': ['Recife', 'Olinda', 'Caruaru', 'Petrolina', 'Jaboatao dos Guararapes', 'Camaragibe', 'Paulista'],
    },
    'grande_salvador': {
        'name': 'Grande Salvador - BA',
        'state': 'BA',
        'cities': ['Salvador', 'Feira de Santana', 'Vitoria da Conquista', 'Camacari', 'Ilheus', 'Lauro de Freitas'],
    },
    'grande_natal': {
        'name': 'Grande Natal - RN',
        'state': 'RN',
        'cities': ['Natal', 'Mossoro', 'Caicó', 'Parnamirim', 'Sao Goncalo do Amarante', 'Macaiba'],
    },
    'grande_joao_pessoa': {
        'name': 'Grande Joao Pessoa - PB',
        'state': 'PB',
        'cities': ['Joao Pessoa', 'Campina Grande', 'Santa Rita', 'Bayeux', 'Cabedelo', 'Patos'],
    },
    'grande_maceio': {
        'name': 'Grande Maceio - AL',
        'state': 'AL',
        'cities': ['Maceio', 'Arapiraca', 'Palmeira dos Indios', 'Uniao dos Palmares', 'Rio Largo'],
    },
    # ---- Norte ----
    'grande_manaus': {
        'name': 'Grande Manaus - AM',
        'state': 'AM',
        'cities': ['Manaus', 'Parintins', 'Itacoatiara', 'Manacapuru', 'Coari', 'Tefé'],
    },
    'grande_belem': {
        'name': 'Grande Belem - PA',
        'state': 'PA',
        'cities': ['Belem', 'Ananindeua', 'Santarem', 'Maraba', 'Castanhal', 'Braganca'],
    },
    # ---- Centro-Oeste ----
    'grande_brasilia': {
        'name': 'Grande Brasilia - DF',
        'state': 'DF',
        'cities': ['Brasilia', 'Taguatinga', 'Ceilandia', 'Gama', 'Aguas Claras', 'Planaltina', 'Sobradinho'],
    },
    'grande_goiania': {
        'name': 'Grande Goiania - GO',
        'state': 'GO',
        'cities': ['Goiania', 'Aparecida de Goiania', 'Anapolis', 'Trindade', 'Senador Canedo', 'Rio Verde'],
    },
    'grande_campo_grande': {
        'name': 'Grande Campo Grande - MS',
        'state': 'MS',
        'cities': ['Campo Grande', 'Dourados', 'Tres Lagoas', 'Corumba', 'Ponta Pora'],
    },
    'grande_cuiaba': {
        'name': 'Grande Cuiaba - MT',
        'state': 'MT',
        'cities': ['Cuiaba', 'Varzea Grande', 'Rondonopolis', 'Sinop', 'Tangara da Serra'],
    },
}

# ============= Daily Pipeline Config =============

DAILY_JOB_NICHES = [
    'restaurante', 'academia', 'clinica medica', 'dentista', 'advocacia',
    'contabilidade', 'imobiliaria', 'salao de beleza', 'farmacia',
    'supermercado', 'pizzaria', 'auto pecas', 'mecanica', 'escola',
    'hotel', 'pousada', 'sorveteria', 'padaria', 'pet shop',
]
DAILY_JOB_REGION  = 'grande_vitoria_es'  # região padrão
DAILY_JOB_HOUR    = 3                    # 3h da manhã, horário de Brasília
DAILY_JOB_USER_ID = 1                   # user_id do admin que "roda" o job
DAILY_CRM_SYNC_HOUR = 9                 # 09:00 da manhã para sync CRM automático

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

# ============= MX Record Validation (Phase 1) =============

_MX_CACHE = {}           # domain -> (result: bool|None, timestamp: float)
_MX_CACHE_TTL = 86400    # 24 hours

def has_valid_mx(domain):
    """
    Check if domain has at least one MX record.
    Returns True (has MX), False (no MX = cannot receive email), None (unknown/timeout).
    Cached for 24h to avoid hammering DNS servers during scraping runs.
    """
    if not _DNS_AVAILABLE or not domain:
        return None
    domain = domain.lower().strip().rstrip('.')
    # Skip obviously invalid domains
    if not domain or '.' not in domain or len(domain) < 4:
        return False
    now = time.time()
    if domain in _MX_CACHE:
        result, ts = _MX_CACHE[domain]
        if now - ts < _MX_CACHE_TTL:
            return result
    try:
        _dns_resolver.resolve(domain, 'MX', lifetime=3.0)
        result = True
    except (_dns_resolver.NXDOMAIN, _dns_resolver.NoAnswer, _dns_resolver.NoNameservers):
        result = False
    except Exception:
        result = None  # Network error or timeout — unknown, don't penalize
    _MX_CACHE[domain] = (result, now)
    # Trim oldest entries when cache grows large
    if len(_MX_CACHE) > 3000:
        sorted_keys = sorted(_MX_CACHE, key=lambda k: _MX_CACHE[k][1])
        for k in sorted_keys[:500]:
            _MX_CACHE.pop(k, None)
    return result


# ============= BrasilAPI CNPJ Enrichment (Phase 1) =============

_CNPJ_CACHE = {}             # cnpj_digits -> (data: dict, timestamp: float)
_CNPJ_CACHE_TTL = 86400 * 30 # 30 days — CNPJ data doesn't change often

def enrich_cnpj_brasilapi(cnpj_raw):
    """
    Enrich CNPJ data via BrasilAPI (100% free, no API key needed).
    Returns enrichment dict or {} on failure/not-found.
    BrasilAPI rate limit: ~3 req/s — callers should add delay externally.
    Includes: razao_social, nome_fantasia, phone, address, CNAE, QSA (partners),
              situacao_cadastral, porte, data_abertura, email (when available).
    """
    cnpj = re.sub(r'[^0-9]', '', cnpj_raw or '')
    if len(cnpj) != 14:
        return {}
    now = time.time()
    if cnpj in _CNPJ_CACHE:
        data, ts = _CNPJ_CACHE[cnpj]
        if now - ts < _CNPJ_CACHE_TTL:
            return data
    try:
        url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
        r = http_requests.get(
            url, timeout=8,
            headers={'User-Agent': random.choice(USER_AGENTS), 'Accept': 'application/json'}
        )
        if r.status_code == 200:
            d = r.json()
            phone1 = re.sub(r'[^0-9]', '', d.get('ddd_telefone_1') or '')
            phone2 = re.sub(r'[^0-9]', '', d.get('ddd_telefone_2') or '')
            qsa_names = [
                q.get('nome_socio', '')
                for q in (d.get('qsa') or [])
                if q.get('nome_socio')
            ]
            address_parts = filter(None, [
                d.get('logradouro'), d.get('numero'),
                d.get('complemento'), d.get('bairro')
            ])
            email_rf = (d.get('email') or '').lower().strip() or None
            result = {
                'razao_social': d.get('razao_social'),
                'nome_fantasia': d.get('nome_fantasia'),
                'phone': phone1 if phone1 else (phone2 if phone2 else None),
                'phone2': phone2 if phone1 and phone2 else None,
                'city': d.get('municipio'),
                'state': d.get('uf'),
                'cep': d.get('cep'),
                'address': ' '.join(address_parts).strip(),
                'cnae': d.get('cnae_fiscal_descricao'),
                'cnae_code': str(d.get('cnae_fiscal', '')),
                'situacao': d.get('descricao_situacao_cadastral'),
                'porte': d.get('porte'),
                'abertura': d.get('data_inicio_atividade'),
                'qsa': qsa_names[:5],
                'email_rf': email_rf,
                'natureza': d.get('natureza_juridica'),
                'capital_social': d.get('capital_social'),
            }
            _CNPJ_CACHE[cnpj] = (result, now)
            print(f"[brasilapi] CNPJ {cnpj}: {result.get('razao_social')} | {result.get('situacao')} | CNAE: {result.get('cnae')}")
            return result
        elif r.status_code == 404:
            _CNPJ_CACHE[cnpj] = ({}, now)
            print(f"[brasilapi] CNPJ {cnpj}: não encontrado (404)")
        elif r.status_code == 429:
            print(f"[brasilapi] Rate limit atingido — aguardando 10s")
            time.sleep(10)
    except Exception as e:
        print(f"[brasilapi] Erro CNPJ {cnpj}: {type(e).__name__}: {e}")
    return {}


def build_lead_from_cnpj_enrichment(cnpj_raw, enrichment):
    """
    Converts BrasilAPI enrichment dict into lead field updates.
    Only fills fields that are empty/None in the existing lead.
    """
    if not enrichment:
        return {}
    updates = {}
    # Company name: prefer nome_fantasia, fallback razao_social
    name = enrichment.get('nome_fantasia') or enrichment.get('razao_social')
    if name:
        updates['company_name_cnpj'] = name.title()
    if enrichment.get('phone'):
        updates['phone_cnpj'] = enrichment['phone']
    if enrichment.get('address'):
        updates['address_cnpj'] = enrichment['address']
    if enrichment.get('city'):
        updates['city_cnpj'] = enrichment['city']
    if enrichment.get('state'):
        updates['state_cnpj'] = enrichment['state']
    if enrichment.get('cnae'):
        updates['category_cnpj'] = enrichment['cnae']
    if enrichment.get('email_rf'):
        updates['email_rf'] = enrichment['email_rf']
    if enrichment.get('qsa'):
        updates['qsa'] = enrichment['qsa']
    if enrichment.get('situacao'):
        updates['cnpj_status'] = enrichment['situacao']
    return updates


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
            plan VARCHAR(20) DEFAULT 'free',
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

        # Phase 1 (Foundation): CNPJ enrichment + MX validation columns
        new_columns += [
            ('cnpj_trade_name', 'VARCHAR(255)'),
            ('cnpj_status', 'VARCHAR(50)'),
            ('cnpj_cnae', 'VARCHAR(255)'),
            ('cnpj_abertura', 'VARCHAR(20)'),
            ('cnpj_porte', 'VARCHAR(50)'),
            ('cnpj_qsa', 'TEXT'),
            ('cnpj_enriched', 'BOOLEAN DEFAULT FALSE'),
            ('mx_valid', 'BOOLEAN'),
            ('email_type', 'VARCHAR(20)'),
            ('lead_score', 'INTEGER DEFAULT 0'),
        ]

        # Phase 2: PDF + Email Pattern + Enhanced crawl columns
        new_columns += [
            ('email_pattern', 'VARCHAR(255)'),
            ('team_members', 'TEXT'),
            ('pdf_emails_found', 'BOOLEAN DEFAULT FALSE'),
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

        c.execute('''CREATE TABLE IF NOT EXISTS daily_jobs (
            id SERIAL PRIMARY KEY,
            started_at TIMESTAMP DEFAULT NOW(),
            finished_at TIMESTAMP,
            status VARCHAR(20) DEFAULT 'running',
            batch_id INTEGER,
            niches_used TEXT[],
            region_used VARCHAR(50),
            leads_found INTEGER DEFAULT 0,
            leads_sanitized INTEGER DEFAULT 0,
            leads_synced INTEGER DEFAULT 0,
            leads_skipped INTEGER DEFAULT 0,
            error_message TEXT
        )''')

        # CRM Sync Log — for daily automatic 09:00 sync and manual syncs
        c.execute('''CREATE TABLE IF NOT EXISTS crm_sync_logs (
            id SERIAL PRIMARY KEY,
            started_at TIMESTAMP DEFAULT NOW(),
            finished_at TIMESTAMP,
            status VARCHAR(20) DEFAULT 'running',
            leads_total INTEGER DEFAULT 0,
            leads_synced INTEGER DEFAULT 0,
            leads_skipped INTEGER DEFAULT 0,
            leads_failed INTEGER DEFAULT 0,
            error_message TEXT,
            trigger VARCHAR(20) DEFAULT 'scheduled'
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_crm_sync_logs_started ON crm_sync_logs(started_at DESC)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_crm_sync_logs_status ON crm_sync_logs(status)')

        c.execute('''CREATE TABLE IF NOT EXISTS system_logs (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT NOW(),
            level VARCHAR(10) NOT NULL,
            provider VARCHAR(50),
            query TEXT,
            message TEXT NOT NULL,
            exception TEXT
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_system_logs_created ON system_logs(created_at DESC)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_system_logs_provider ON system_logs(provider)')

        # fix_prompt column on system_logs (added later, migrate safely)
        try:
            c.execute("ALTER TABLE system_logs ADD COLUMN fix_prompt TEXT")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        # error_type + extra_data columns on system_logs (v2 logs)
        try:
            c.execute("ALTER TABLE system_logs ADD COLUMN error_type VARCHAR(50)")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()
        try:
            c.execute("ALTER TABLE system_logs ADD COLUMN extra_data JSONB")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()
        c.execute('CREATE INDEX IF NOT EXISTS idx_system_logs_error_type ON system_logs(error_type)')

        # Custom niches table (user-saved niches for massive search)
        c.execute('''CREATE TABLE IF NOT EXISTS custom_niches (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(name)
        )''')

        # enrichment_source column on search_jobs
        try:
            c.execute("ALTER TABLE search_jobs ADD COLUMN enrichment_source VARCHAR(30) DEFAULT 'scraping'")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        # SaaS Foundation: plan column on users
        try:
            c.execute("ALTER TABLE users ADD COLUMN plan VARCHAR(20) DEFAULT 'free'")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        # SaaS Foundation: usage tracking table
        c.execute('''CREATE TABLE IF NOT EXISTS usage_tracking (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            month_year VARCHAR(7) NOT NULL,
            leads_viewed INTEGER DEFAULT 0,
            leads_exported INTEGER DEFAULT 0,
            reset_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, month_year)
        )''')

        # SaaS Foundation: plan limits configuration
        c.execute('''CREATE TABLE IF NOT EXISTS plan_limits (
            id SERIAL PRIMARY KEY,
            plan_name VARCHAR(20) UNIQUE NOT NULL,
            leads_per_month INTEGER NOT NULL,
            exports_per_month INTEGER NOT NULL,
            price_monthly DECIMAL(10, 2) DEFAULT 0,
            features JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        )''')

        # Initialize plan limits if not exists
        c.execute('SELECT COUNT(*) FROM plan_limits')
        if c.fetchone()[0] == 0:
            c.execute('''INSERT INTO plan_limits (plan_name, leads_per_month, exports_per_month, price_monthly, features)
                VALUES
                    ('free', 100, 1, 0, '{"leads_view": true, "export_csv": true, "filters": ["email", "phone", "city", "state"], "saved_filters": false}'::jsonb),
                    ('pro', 5000, 20, 99, '{"leads_view": true, "export_csv": true, "export_json": true, "filters": ["email", "phone", "city", "state", "category", "crm_status"], "saved_filters": true, "bulk_actions": true}'::jsonb),
                    ('enterprise', 999999, 999999, 0, '{"leads_view": true, "export_csv": true, "export_json": true, "export_whatsapp": true, "filters": ["*"], "saved_filters": true, "bulk_actions": true, "api_access": true}'::jsonb)
            ''')

        # Saved filters (Semana 2)
        c.execute('''CREATE TABLE IF NOT EXISTS saved_filters (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            filters JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, name)
        )''')

        # Indexes
        c.execute('CREATE INDEX IF NOT EXISTS idx_usage_tracking_user_month ON usage_tracking(user_id, month_year)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_usage_tracking_month ON usage_tracking(month_year)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_users_plan ON users(plan)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_saved_filters_user ON saved_filters(user_id)')

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

        # Semana 4: Shared lead base — mark all batches as shared by default
        try:
            c.execute("ALTER TABLE batches ADD COLUMN is_shared BOOLEAN DEFAULT TRUE")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()
        # Backfill: ensure all existing batches are marked as shared
        c.execute("UPDATE batches SET is_shared = TRUE WHERE is_shared IS NULL")
        c.execute('CREATE INDEX IF NOT EXISTS idx_batches_is_shared ON batches(is_shared)')

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

    # Validação MX: domínio sem registro MX não pode receber emails (Phase 1)
    mx_result = has_valid_mx(domain)
    if mx_result is True:
        score += 10   # Bônus: domínio confirmado com servidor de email
    elif mx_result is False:
        return 0, False, f'no_mx_record:{domain}'  # Domínio não aceita email

    # Garantir range 0-100
    score = max(0, min(100, score))

    return score, True, None

def normalize_email(email_str):
    """
    Normalize and validate an email address with quality filtering.
    Returns the normalized email or None if invalid/low-quality.
    """
    email_str = email_str.strip().lower()
    # Remove scraping artifacts prepended to email (e.g. "e-mailcontato@..." → "contato@...")
    email_str = re.sub(r'^(e-mail|email:|mailto:|e\.mail|email\s*[:=])\s*', '', email_str, flags=re.I)
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

    # Extract company name + normalize on extraction
    company_name = extract_company_name(soup, url)
    # Normalize at extraction time (encoding, title case, generic detection)
    # email/website not yet known here; full normalize happens in sanitize_single_lead
    company_name = extract_clean_company_name(company_name) if company_name else company_name

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

# ============= Phase 2: PDF + Email Pattern + Enhanced Extraction =============

try:
    import pdfplumber as _pdfplumber
    _PDF_AVAILABLE = True
except ImportError:
    _pdfplumber = None
    _PDF_AVAILABLE = False

def extract_pdf_emails(pdf_url, session=None):
    """Download a PDF and extract emails from its text content."""
    if not _PDF_AVAILABLE:
        return []
    try:
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        if session:
            resp = session.get(pdf_url, timeout=15, verify=False, headers=headers, stream=True)
        else:
            resp = http_requests.get(pdf_url, timeout=15, verify=False, headers=headers, stream=True)
        if resp.status_code != 200:
            return []
        content_type = resp.headers.get('content-type', '')
        if 'pdf' not in content_type and not pdf_url.lower().endswith('.pdf'):
            return []
        # Limit PDF size to 5MB
        content = b''
        for chunk in resp.iter_content(8192):
            content += chunk
            if len(content) > 5 * 1024 * 1024:
                break
        import io
        found = set()
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        with _pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages[:10]:  # max 10 pages
                text = page.extract_text() or ''
                for em in re.findall(email_pattern, text):
                    found.add(em.lower().strip())
        # Normalize & validate
        result = []
        for em in found:
            normalized = normalize_email(em)
            if normalized:
                result.append(normalized)
        return result
    except Exception as e:
        print(f"[pdf] Error extracting from {pdf_url}: {e}")
        return []


def extract_pdf_links_from_html(soup, base_url):
    """Find PDF links in a page (contact/privacy policy PDFs often have emails)."""
    pdf_links = []
    for tag in soup.find_all('a', href=True):
        href = tag['href'].strip()
        if not href:
            continue
        href_lower = href.lower()
        if href_lower.endswith('.pdf') or 'pdf' in href_lower:
            # Make absolute URL
            if href.startswith('http'):
                pdf_links.append(href)
            elif href.startswith('/'):
                parsed = urlparse(base_url)
                pdf_links.append(f"{parsed.scheme}://{parsed.netloc}{href}")
            if len(pdf_links) >= 3:  # max 3 PDFs per page
                break
    return pdf_links


def detect_email_pattern(emails_list, domain):
    """
    Detect company email naming pattern from 2+ emails on same domain.
    Returns pattern string like 'nome.sobrenome@domain.com' or None.
    """
    if not emails_list or not domain:
        return None
    domain = domain.lower().strip()
    # Filter emails from target domain
    domain_emails = [e for e in emails_list if e.lower().endswith('@' + domain)]
    if len(domain_emails) < 2:
        return None

    locals_list = [e.split('@')[0] for e in domain_emails]

    # Count separators
    dot_count = sum(1 for l in locals_list if '.' in l)
    underscore_count = sum(1 for l in locals_list if '_' in l)

    if dot_count >= 2:
        separator = '.'
    elif underscore_count >= 2:
        separator = '_'
    else:
        # Check if they look like initials (short strings)
        avg_len = sum(len(l) for l in locals_list) / len(locals_list)
        if avg_len <= 4:
            return f'inicial@{domain}'
        return None

    # Build pattern description
    # Determine structure: first.last, first.initial, initial.last
    parts_list = [l.split(separator) for l in locals_list if separator in l]
    if not parts_list:
        return None

    avg_parts = sum(len(p) for p in parts_list) / len(parts_list)
    if avg_parts >= 1.8:
        return f'nome{separator}sobrenome@{domain}'
    else:
        return f'nome@{domain}'


def extract_footer_header_emails(soup):
    """Extract emails specifically from footer and header tags (higher quality)."""
    emails = set()
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    for tag_name in ['footer', 'header']:
        tag = soup.find(tag_name)
        if tag:
            text = tag.get_text()
            for em in re.findall(email_pattern, text):
                emails.add(em.lower().strip())
            # Also check mailto links in footer/header
            for a in tag.find_all('a', href=True):
                href = a['href']
                if 'mailto:' in href:
                    em = href.replace('mailto:', '').split('?')[0].strip().lower()
                    if em:
                        emails.add(em)

    # Also check elements with class/id containing 'footer' or 'contact'
    for cls_kw in ['footer', 'contact', 'rodape', 'contato']:
        for el in soup.find_all(class_=lambda c: c and cls_kw in c.lower()):
            text = el.get_text()
            for em in re.findall(email_pattern, text):
                emails.add(em.lower().strip())
            for a in el.find_all('a', href=True):
                if 'mailto:' in a['href']:
                    em = a['href'].replace('mailto:', '').split('?')[0].strip().lower()
                    if em:
                        emails.add(em)

    result = []
    for em in emails:
        normalized = normalize_email(em)
        if normalized:
            result.append(normalized)
    return result


def extract_team_members(soup):
    """
    Extract team member info (name, role, email) from About/Team sections.
    Returns list of dicts with keys: name, role, email.
    """
    members = []
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    team_keywords = [
        'team', 'equipe', 'nossa-equipe', 'our-team', 'staff', 'time',
        'diretoria', 'diretores', 'socios', 'fundadores', 'founders',
        'lideranca', 'gestores', 'responsaveis',
    ]

    # Find team sections by ID or class
    team_sections = []
    for kw in team_keywords:
        for el in soup.find_all(id=lambda i: i and kw in i.lower()):
            team_sections.append(el)
        for el in soup.find_all(class_=lambda c: c and kw in c.lower()):
            team_sections.append(el)

    # If no specific section found, look for cards/blocks with person-like structure
    if not team_sections:
        for el in soup.find_all(['article', 'div', 'li'], class_=lambda c: c and any(
            kw in c.lower() for kw in ['card', 'member', 'pessoa', 'profile', 'bio']
        )):
            team_sections.append(el)

    seen_names = set()
    for section in team_sections[:5]:  # limit to 5 sections
        # Look for heading (name) + paragraph (role) pattern
        headings = section.find_all(['h1','h2','h3','h4','h5','h6','strong','b'])
        for h in headings[:20]:
            name = h.get_text().strip()
            if not name or len(name) > 80 or len(name) < 3:
                continue
            if name in seen_names:
                continue
            # Role: check next sibling or parent's next sibling
            role = None
            next_sib = h.find_next_sibling()
            if next_sib and next_sib.name in ['p', 'span', 'div']:
                role_text = next_sib.get_text().strip()
                if role_text and len(role_text) < 100:
                    role = role_text
            # Email: look nearby
            parent_text = (h.parent or section).get_text() if h.parent else ''
            found_emails = re.findall(email_pattern, parent_text)
            email = None
            if found_emails:
                em = normalize_email(found_emails[0])
                if em:
                    email = em
            seen_names.add(name)
            members.append({'name': name, 'role': role, 'email': email})

    return members[:10]  # max 10 members


# ============= Phase 2: New Directory Scrapers =============

def scrape_empresas_com_br(niche, city, state, max_pages=2):
    """
    Scrape empresas.com.br for business listings.
    URL format: https://www.empresas.com.br/{state}/{city}/{niche}/
    Returns list of lead dicts.
    """
    leads = []
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    # Normalize for URL
    def slug(s):
        import unicodedata
        s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
        s = re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')
        return s

    state_slug = slug(state) if state else ''
    city_slug = slug(city) if city else ''
    niche_slug = slug(niche) if niche else ''

    try:
        for page in range(1, max_pages + 1):
            if page == 1:
                url = f"https://www.empresas.com.br/{state_slug}/{city_slug}/{niche_slug}/"
            else:
                url = f"https://www.empresas.com.br/{state_slug}/{city_slug}/{niche_slug}/p{page}/"

            headers = {'User-Agent': random.choice(USER_AGENTS)}
            resp = http_requests.get(url, timeout=10, verify=False, headers=headers)
            if resp.status_code != 200:
                break

            soup = BeautifulSoup(resp.text, 'html.parser')
            # Cards with company info
            cards = soup.find_all('div', class_=lambda c: c and any(
                kw in c for kw in ['empresa', 'company', 'listing', 'result', 'card']
            ))
            if not cards:
                # Fallback: try h2/h3 + links pattern
                cards = soup.find_all(['article', 'li'], class_=True)

            for card in cards[:30]:
                text = card.get_text()
                company_name = None
                website = None
                phone = None
                email = None

                # Company name: first heading in card
                h = card.find(['h2','h3','h4','a'])
                if h:
                    company_name = h.get_text().strip()[:255]

                # Website link
                for a in card.find_all('a', href=True):
                    href = a['href']
                    if href.startswith('http') and 'empresas.com.br' not in href:
                        website = href
                        break

                # Phone
                phones = extract_phones(text)
                if phones:
                    phone = phones[0]

                # Email
                em_list = re.findall(email_pattern, text)
                if em_list:
                    em = normalize_email(em_list[0])
                    if em:
                        email = em

                if company_name:
                    leads.append({
                        'company_name': company_name,
                        'email': email,
                        'phone': phone,
                        'website': website,
                        'city': city,
                        'state': state,
                        'category': niche,
                        'source': 'empresas.com.br',
                    })

            time.sleep(3)
    except Exception as e:
        print(f"[empresas.com.br] Error: {e}")

    return leads


def scrape_paginas_amarelas(niche, city, max_pages=2):
    """
    Scrape paginasamarelas.com.br (or similar) for business contacts.
    Returns list of lead dicts.
    """
    leads = []
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    def slug(s):
        import unicodedata
        s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
        s = re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')
        return s

    city_slug = slug(city) if city else ''
    niche_slug = slug(niche) if niche else ''

    try:
        for page in range(1, max_pages + 1):
            url = f"https://www.paginasamarelas.com.br/busca/{niche_slug}/{city_slug}?pagina={page}"
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            resp = http_requests.get(url, timeout=10, verify=False, headers=headers)
            if resp.status_code != 200:
                break

            soup = BeautifulSoup(resp.text, 'html.parser')
            cards = soup.find_all(['div', 'article', 'li'], class_=lambda c: c and any(
                kw in c for kw in ['result', 'listing', 'item', 'empresa', 'business']
            ))

            for card in cards[:30]:
                text = card.get_text()
                company_name = None
                phone = None
                email = None
                website = None
                address = None

                h = card.find(['h2','h3','h4','strong'])
                if h:
                    company_name = h.get_text().strip()[:255]

                phones = extract_phones(text)
                if phones:
                    phone = phones[0]

                em_list = re.findall(email_pattern, text)
                if em_list:
                    em = normalize_email(em_list[0])
                    if em:
                        email = em

                for a in card.find_all('a', href=True):
                    href = a['href']
                    if href.startswith('http') and 'paginasamarelas' not in href:
                        website = href
                        break

                if company_name:
                    leads.append({
                        'company_name': company_name,
                        'email': email,
                        'phone': phone,
                        'website': website,
                        'city': city,
                        'category': niche,
                        'source': 'paginas_amarelas',
                    })

            time.sleep(3)
    except Exception as e:
        print(f"[paginas_amarelas] Error: {e}")

    return leads


def scrape_catalogo_br(niche, city, state, max_pages=2):
    """
    Scrape catalogo.com.br — Brazilian business directory.
    Returns list of lead dicts.
    """
    leads = []
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    def slug(s):
        import unicodedata
        s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
        s = re.sub(r'[^a-z0-9 ]+', '', s.lower()).strip()
        return s.replace(' ', '+')

    query = f"{slug(niche)} {slug(city)}" if city else slug(niche)

    try:
        for page in range(1, max_pages + 1):
            url = f"https://www.catalogo.com.br/busca?q={query.replace(' ', '+')}&pagina={page}"
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            resp = http_requests.get(url, timeout=10, verify=False, headers=headers)
            if resp.status_code != 200:
                break

            soup = BeautifulSoup(resp.text, 'html.parser')
            cards = soup.find_all(['div', 'article'], class_=lambda c: c and any(
                kw in c for kw in ['result', 'company', 'empresa', 'item', 'card', 'listing']
            ))

            for card in cards[:25]:
                text = card.get_text()
                company_name = None
                phone = None
                email = None
                website = None

                h = card.find(['h2','h3','h4','strong','a'])
                if h:
                    company_name = h.get_text().strip()[:255]

                phones = extract_phones(text)
                if phones:
                    phone = phones[0]

                em_list = re.findall(email_pattern, text)
                if em_list:
                    em = normalize_email(em_list[0])
                    if em:
                        email = em

                for a in card.find_all('a', href=True):
                    href = a['href']
                    if href.startswith('http') and 'catalogo.com.br' not in href:
                        website = href
                        break

                if company_name:
                    leads.append({
                        'company_name': company_name,
                        'email': email,
                        'phone': phone,
                        'website': website,
                        'city': city,
                        'state': state,
                        'category': niche,
                        'source': 'catalogo_br',
                    })

            time.sleep(3)
    except Exception as e:
        print(f"[catalogo_br] Error: {e}")

    return leads


# ============= Phase 2: Integration into deep_crawl_domain =============

def deep_crawl_domain_phase2(url, session=None):
    """
    Enhanced crawl: runs deep_crawl_domain + PDF extraction + footer email extraction.
    Returns enriched result dict.
    """
    result = deep_crawl_domain(url, session)

    # Try to enhance with footer/header email extraction from the main page HTML
    try:
        html = fetch_page(url, session)
        if html:
            soup = BeautifulSoup(html, 'html.parser')
            footer_emails = extract_footer_header_emails(soup)
            # Add any new footer emails not already found
            existing = set(result.get('emails', []))
            for em in footer_emails:
                if em not in existing:
                    result['emails'].append(em)
                    existing.add(em)

            # PDF extraction: find PDF links on main page
            pdf_links = extract_pdf_links_from_html(soup, url)
            for pdf_url in pdf_links:
                pdf_emails = extract_pdf_emails(pdf_url, session)
                for em in pdf_emails:
                    if em not in existing:
                        result['emails'].append(em)
                        existing.add(em)

            # Team member extraction
            members = extract_team_members(soup)
            if members:
                result['team_members'] = members
                # If we found team member emails, add them too
                for m in members:
                    if m.get('email') and m['email'] not in existing:
                        result['emails'].append(m['email'])
                        existing.add(m['email'])

            # Email pattern detection
            if result.get('emails'):
                from urllib.parse import urlparse as _urlparse
                parsed_url = _urlparse(url)
                domain = (parsed_url.hostname or '').replace('www.', '')
                pattern = detect_email_pattern(result['emails'], domain)
                if pattern:
                    result['email_pattern'] = pattern
    except Exception as e:
        print(f"[phase2_crawl] Enhancement error for {url}: {e}")

    return result


# ============= Phase 3: Fuzzy Dedup + Auto-Tags =============

try:
    from rapidfuzz import fuzz as _rfuzz
    from rapidfuzz import process as _rfprocess
    _RAPIDFUZZ_AVAILABLE = True
except ImportError:
    _rfuzz = None
    _rfprocess = None
    _RAPIDFUZZ_AVAILABLE = False

def fuzzy_deduplicate_leads(batch_id, conn, threshold=88):
    """Find near-duplicate leads by company name within a batch.
    Marks duplicates with crm_status='duplicado' and tags='duplicado_fuzzy'.
    Returns count of duplicates marked."""
    if not _RAPIDFUZZ_AVAILABLE:
        print("[Phase3] rapidfuzz not available, skipping dedup")
        return 0

    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, company_name FROM leads
            WHERE batch_id = %s AND company_name IS NOT NULL AND company_name != ''
            ORDER BY id
        """, (batch_id,))
        rows = cur.fetchall()
        if not rows:
            return 0

        ids = [r[0] for r in rows]
        names = [r[1] for r in rows]

        seen = {}   # normalized_name -> first_id
        duplicates = []

        for i, (lead_id, name) in enumerate(zip(ids, names)):
            normalized = name.strip().lower()
            if not normalized:
                continue

            # Check against all previously seen names
            if seen:
                seen_names = list(seen.keys())
                match = _rfprocess.extractOne(
                    normalized,
                    seen_names,
                    scorer=_rfuzz.token_sort_ratio,
                    score_cutoff=threshold
                )
                if match:
                    duplicates.append(lead_id)
                    continue

            seen[normalized] = lead_id

        if duplicates:
            cur.execute("""
                UPDATE leads
                SET crm_status = 'duplicado',
                    tags = CASE
                        WHEN tags IS NULL OR tags = '' THEN 'duplicado_fuzzy'
                        ELSE tags || ',duplicado_fuzzy'
                    END,
                    updated_at = NOW()
                WHERE id = ANY(%s)
            """, (duplicates,))
            conn.commit()
            print(f"[Phase3] Dedup batch {batch_id}: {len(duplicates)} duplicates marked")

        return len(duplicates)
    except Exception as e:
        conn.rollback()
        print(f"[Phase3] Dedup error: {e}")
        return 0
    finally:
        cur.close()


_AUTO_TAG_RULES = [
    ('saude', ['clinica', 'medico', 'medica', 'hospital', 'saude', 'farmacia', 'odonto', 'dentista',
                'fisio', 'nutri', 'psico', 'terapia', 'laboratorio', 'exame', 'consulta', 'ortopedia',
                'cardiologia', 'pediatria', 'oftalmologia', 'dermatologia', 'enfermagem', 'veterinaria']),
    ('beleza', ['salao', 'barbearia', 'cabeleireiro', 'estetica', 'spa', 'manicure', 'pedicure',
                'depilacao', 'micropigmentacao', 'maquiagem', 'sobrancelha', 'lash', 'unhas', 'beleza']),
    ('alimentacao', ['restaurante', 'lanchonete', 'pizzaria', 'churrascaria', 'padaria', 'confeitaria',
                     'buffet', 'sorveteria', 'cafe', 'bar ', 'boteco', 'sushi', 'marmita', 'delivery',
                     'alimentacao', 'gastronomia', 'culinaria']),
    ('educacao', ['escola', 'colegio', 'faculdade', 'curso', 'idioma', 'ingles', 'espanhol',
                  'reforco', 'cursinho', 'creche', 'ensino', 'educacao', 'treinamento', 'capacitacao',
                  'master', 'pos-graduacao', 'universitario']),
    ('juridico', ['advogado', 'advocacia', 'juridico', 'juridica', 'direito', 'escritorio de adv',
                  'consultoria juridica', 'tabeliao', 'cartorio', 'notarial']),
    ('contabil', ['contabil', 'contabilidade', 'contador', 'contadora', 'fiscal', 'tributario',
                  'irpf', 'irpj', 'mei', 'abertura de empresa', 'folha de pagamento', 'rh', 'recursos humanos']),
    ('tecnologia', ['tecnologia', 'software', 'sistemas', 'ti ', 'informatica', 'desenvolvimento',
                    'programacao', 'aplicativo', 'app ', 'web ', 'digital', 'startup', 'saas', 'ecommerce',
                    'e-commerce', 'loja virtual', 'marketing digital', 'agencia digital', 'seo']),
    ('imoveis', ['imoveis', 'imobiliaria', 'corretor', 'corretora', 'incorporadora', 'construtora imovel',
                 'aluguel', 'venda de imovel', 'apartamento', 'casa', 'terreno', 'loteamento']),
    ('construcao', ['construcao', 'reforma', 'engenharia', 'arquitetura', 'eletrica', 'hidraulica',
                    'pintura', 'marcenaria', 'marmoraria', 'serralheria', 'vidracaria', 'instalacao',
                    'manutencao', 'impermeabilizacao', 'gesseiro', 'pedreiro']),
    ('varejo', ['loja', 'comercio', 'varejo', 'vendas', 'produto', 'moda', 'roupa', 'calcado',
                'eletronico', 'movel', 'decoracao', 'utilidade', 'pet shop', 'livraria', 'farmacia',
                'supermercado', 'mercado']),
    ('automotivo', ['auto', 'carro', 'veiculo', 'mecanica', 'oficina', 'funilaria', 'pintura auto',
                    'lavagem', 'auto pecas', 'concessionaria', 'moto', 'transporte', 'logistica', 'frete']),
    ('b2b', ['industria', 'industrial', 'distribuidora', 'atacado', 'fornecedor', 'fabricante',
              'representante', 'importadora', 'exportadora', 'comercio exterior', 'b2b']),
    ('turismo', ['turismo', 'viagem', 'agencia de viagem', 'hotel', 'pousada', 'resort', 'hostel',
                 'excursao', 'passeio', 'tour', 'ecoturismo', 'agencia de turismo']),
    ('pet', ['pet', 'animal', 'veterinaria', 'canil', 'gatil', 'racao', 'banho e tosa', 'adestramento']),
    ('religioso', ['igreja', 'religiao', 'pastoral', 'ministerio', 'ong', 'associacao', 'fundacao',
                   'caridade', 'social', 'assistencia social']),
    ('industria', ['industria', 'fabrica', 'metalurgica', 'siderurgica', 'quimica', 'plastico',
                   'textil', 'agro', 'agropecuaria', 'rural', 'producao']),
]


def auto_tag_lead(company_name, category=None, email=None, city=None):
    """Generate automatic tags from keyword matching.
    Returns list of tags (strings) based on company_name and category."""
    tags = set()
    text = ' '.join(filter(None, [
        (company_name or '').lower(),
        (category or '').lower(),
        (email or '').lower().split('@')[0] if email else '',
    ]))

    # Normalize: remove accents for matching
    import unicodedata
    text_norm = unicodedata.normalize('NFD', text)
    text_norm = ''.join(c for c in text_norm if unicodedata.category(c) != 'Mn')

    for tag, keywords in _AUTO_TAG_RULES:
        for kw in keywords:
            kw_norm = unicodedata.normalize('NFD', kw)
            kw_norm = ''.join(c for c in kw_norm if unicodedata.category(c) != 'Mn')
            if kw_norm in text_norm:
                tags.add(tag)
                break

    return list(tags)


def auto_tag_batch(batch_id, conn):
    """Auto-tag all leads in a batch that have no tags yet.
    Returns count of leads tagged."""
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, company_name, category, email, city FROM leads
            WHERE batch_id = %s AND (tags IS NULL OR tags = '')
        """, (batch_id,))
        rows = cur.fetchall()
        if not rows:
            return 0

        tagged = 0
        for lead_id, company_name, category, email, city in rows:
            new_tags = auto_tag_lead(company_name, category, email, city)
            if new_tags:
                cur.execute("""
                    UPDATE leads SET tags = %s, updated_at = NOW()
                    WHERE id = %s
                """, (','.join(new_tags), lead_id))
                tagged += 1

        conn.commit()
        print(f"[Phase3] Auto-tagged {tagged} leads in batch {batch_id}")
        return tagged
    except Exception as e:
        conn.rollback()
        print(f"[Phase3] Auto-tag error: {e}")
        return 0
    finally:
        cur.close()


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

    # Phase 2: wrapper adapters for new scrapers (they return list, not list+domains)
    def _scrape_empresas_compat(niche, city, state, session):
        leads = scrape_empresas_com_br(niche, city, state, max_pages=2)
        domains = set()
        for l in leads:
            if l.get('website'):
                from urllib.parse import urlparse as _up
                domains.add(_up(l['website']).netloc)
        return leads, domains

    def _scrape_amarelas_compat(niche, city, state, session):
        leads = scrape_paginas_amarelas(niche, city, max_pages=2)
        domains = set()
        for l in leads:
            if l.get('website'):
                from urllib.parse import urlparse as _up
                domains.add(_up(l['website']).netloc)
        return leads, domains

    def _scrape_catalogo_compat(niche, city, state, session):
        leads = scrape_catalogo_br(niche, city, state, max_pages=2)
        domains = set()
        for l in leads:
            if l.get('website'):
                from urllib.parse import urlparse as _up
                domains.add(_up(l['website']).netloc)
        return leads, domains

    for scraper_fn, name in [
        (scrape_guiamais, 'GuiaMais'),
        (scrape_telelistas, 'TeleListas'),
        (scrape_apontador, 'Apontador'),
        (_scrape_empresas_compat, 'Empresas.com.br'),
        (_scrape_amarelas_compat, 'PaginasAmarelas'),
        (_scrape_catalogo_compat, 'Catalogo.com.br'),
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


# ============= Yahoo HTML scraping (extra source) =============

def _search_yahoo(query, max_pages=2, safety=None):
    """Search Yahoo using HTML scraping. Extra fallback source beyond DDG/Bing.
    Returns list of results.
    Raises QuotaExceededError on rate limit (429/503) — retry-able.
    Returns empty list on genuine "no results" — NOT retry-able.
    """
    results = []
    ua_list = USER_AGENTS if 'USER_AGENTS' in globals() else [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ]
    headers = {'User-Agent': random.choice(ua_list), 'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8'}
    encoded_query = requests_quote(query)
    for page in range(max_pages):
        start = page * 10
        url = f'https://search.yahoo.com/search?p={encoded_query}&b={start + 1}&pz=10'
        try:
            resp = http_requests.get(url, headers=headers, timeout=10)
            if resp.status_code in (429, 503):
                scraper_log('WARNING', 'yahoo_html', query, f'rate limit status={resp.status_code} page={page}')
                raise QuotaExceededError(f'Yahoo rate limit HTTP {resp.status_code}')
            if resp.status_code != 200:
                scraper_log('WARNING', 'yahoo_html', query, f'status={resp.status_code} page={page}')
                break
            soup = BeautifulSoup(resp.text, 'lxml')
            # Detect CAPTCHA / block page
            page_text = resp.text.lower()
            if 'captcha' in page_text or 'are you a human' in page_text or 'robot' in page_text:
                scraper_log('WARNING', 'yahoo_html', query, f'CAPTCHA detectado page={page}')
                raise QuotaExceededError('Yahoo CAPTCHA/block detectado')
            # Updated selectors: primary + fallback for Yahoo layout changes
            for tag in soup.select('div.algo-sr h3.title a, div#web a.ac-algo, #web li a.d-ib, div.dd a.ac-algo'):
                href = tag.get('href', '')
                # Yahoo sometimes wraps URLs; extract actual URL
                if 'r.search.yahoo.com' in href:
                    import urllib.parse as _up
                    qs = _up.urlparse(href).query
                    params = _up.parse_qs(qs)
                    href = params.get('RU', params.get('u', [href]))[0]
                if href.startswith('http') and is_valid_result_url(href):
                    results.append({'url': href, 'title': tag.get_text(strip=True)})
            if safety:
                safety.record_success()
            time.sleep(random.uniform(2, 4))
        except QuotaExceededError:
            raise  # propagate rate limit errors for retry
        except Exception as e:
            scraper_log('WARNING', 'yahoo_html', query, f'page={page} erro', exc=e)
            if safety:
                safety.record_error('generic')
            break
    return results


# ============= Multi-Source Search with Fallback =============

def search_with_fallback(query, max_pages=2, safety=None, cursor=None, user_id=None, search_job_id=None):
    """Multi-source domain search — runs ALL sources and aggregates results.
    Uses tenacity retry with exponential backoff per provider.
    Logs every attempt/failure to scraper_errors.log.
    Engines: Bing API → Google CSE → DDG API → DDG HTML → Bing HTML → Yahoo HTML
    """
    all_results = []   # accumulate across ALL providers
    engines_used = []  # track which engines contributed
    seen_urls = set()  # global dedup across providers

    def _add_results(new_results, engine_name):
        """Merge new results into all_results, deduplicating by URL."""
        added = 0
        for r in new_results:
            url = r.get('url', '').strip().rstrip('/')
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)
                added += 1
        if added:
            engines_used.append(engine_name)
        return added

    print(f"\n[WEBSEARCH] Iniciando busca TOTAL multi-fonte para: '{query}'")

    # ── Helper: tenacity retry — retries on ANY error except BlockedError/CaptchaError ──
    def _with_retry(fn):
        """3 attempts with exponential backoff. Skips only if BlockedError/CaptchaError."""
        if _TENACITY_AVAILABLE:
            from tenacity import retry as _retry, stop_after_attempt, wait_exponential, retry_if_exception
            decorated = _retry(
                retry=retry_if_exception(lambda e: not isinstance(e, (BlockedError, CaptchaError))),
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=3, max=30),
                before_sleep=lambda rs: scraper_log(
                    'WARNING', 'retry', query,
                    f'tentativa {rs.attempt_number} falhou, aguardando...'),
            )(fn)
            return decorated
        # Without tenacity: manual 3-retry loop
        def _manual_retry(*a, **kw):
            last_exc = None
            for attempt in range(3):
                try:
                    return fn(*a, **kw)
                except (BlockedError, CaptchaError):
                    raise
                except Exception as exc:
                    last_exc = exc
                    scraper_log('WARNING', 'retry', query, f'tentativa {attempt+1} falhou', exc=exc)
                    if attempt < 2:
                        time.sleep(3 * (attempt + 1))
            raise RetryError(f'3 tentativas esgotadas: {last_exc}')
        return _manual_retry

    # ── SOURCE 1: Bing Web Search API (official, no CAPTCHA) ─────────────────
    if cursor and user_id:
        bing_config = get_api_config(cursor, user_id, 'bing_api')
        if bing_config:
            bing_credits = get_api_credits_remaining(cursor, user_id, 'bing_api')
            if bing_credits > 0:
                print(f"[WEBSEARCH] Fonte 1: Bing API oficial ({bing_credits} creditos)...")
                scraper_log('INFO', 'bing_api', query, f'iniciando (creditos={bing_credits})')
                try:
                    _bing_cfg = bing_config  # capture for closure
                    def _call_bing_api():
                        api_results, error, duration = search_bing_api(
                            query, _bing_cfg['api_key'], max_results=max_pages * 10)
                        if error == 'invalid_key':
                            raise BlockedError('invalid_key')  # skip — no retry
                        if error:
                            raise Exception(f'bing_api: {error}')  # retry-able
                        if not api_results:
                            raise QuotaExceededError('sem resultados')
                        return api_results, duration
                    api_results, duration = _with_retry(_call_bing_api)()
                    record_api_usage(cursor, user_id, 'bing_api', 1)
                    added = _add_results(api_results, 'bing_api')
                    print(f"[WEBSEARCH] Bing API: +{added} resultados em {duration}ms")
                    scraper_log('INFO', 'bing_api', query, f'ok added={added} duration={duration}ms')
                    if search_job_id:
                        log_search(cursor, search_job_id, 'search_ok',
                                  message=f'Bing API: {added} resultados em {duration}ms',
                                  duration_ms=duration)
                except BlockedError:
                    cursor.execute('UPDATE api_configs SET is_active = FALSE WHERE user_id = %s AND provider = %s',
                                  (user_id, 'bing_api'))
                    scraper_log('ERROR', 'bing_api', query, 'chave invalida — desativada')
                except RetryError as e:
                    scraper_log('ERROR', 'bing_api', query, '3 tentativas esgotadas', exc=e)
                    print(f"[WEBSEARCH] Bing API: 3 tentativas falharam — proximo provider")
                except Exception as e:
                    scraper_log('ERROR', 'bing_api', query, 'erro inesperado', exc=e)
                    print(f"[WEBSEARCH] Bing API: erro — {e}")
            else:
                print(f"[WEBSEARCH] Bing API: sem creditos")
        else:
            print(f"[WEBSEARCH] Bing API: nao configurada")

    # ── SOURCE 2: Google Custom Search API (no CAPTCHA, 100/day) ─────────────
    if cursor and user_id:
        google_config = get_api_config(cursor, user_id, 'google_cse')
        if google_config and google_config.get('api_secret'):
            google_credits = get_api_credits_remaining(cursor, user_id, 'google_cse')
            if google_credits > 0:
                print(f"[WEBSEARCH] Fonte 2: Google CSE ({google_credits} creditos)...")
                scraper_log('INFO', 'google_cse', query, f'iniciando (creditos={google_credits})')
                try:
                    _goog_cfg = google_config  # capture for closure
                    def _call_google_cse():
                        api_results, error, duration = search_google_custom(
                            query, _goog_cfg['api_key'], _goog_cfg['api_secret'], max_results=10)
                        if error == 'invalid_key':
                            raise BlockedError('invalid_key')
                        if error:
                            raise Exception(f'google_cse: {error}')
                        if not api_results:
                            raise QuotaExceededError('sem resultados')
                        return api_results, duration
                    api_results, duration = _with_retry(_call_google_cse)()
                    record_api_usage(cursor, user_id, 'google_cse', 1)
                    added = _add_results(api_results, 'google_cse')
                    print(f"[WEBSEARCH] Google CSE: +{added} resultados em {duration}ms")
                    scraper_log('INFO', 'google_cse', query, f'ok added={added} duration={duration}ms')
                    if search_job_id:
                        log_search(cursor, search_job_id, 'search_ok',
                                  message=f'Google CSE: {added} resultados em {duration}ms',
                                  duration_ms=duration)
                except BlockedError:
                    cursor.execute('UPDATE api_configs SET is_active = FALSE WHERE user_id = %s AND provider = %s',
                                  (user_id, 'google_cse'))
                    scraper_log('ERROR', 'google_cse', query, 'chave invalida — desativada')
                except RetryError as e:
                    scraper_log('ERROR', 'google_cse', query, '3 tentativas esgotadas', exc=e)
                    print(f"[WEBSEARCH] Google CSE: 3 tentativas falharam — proximo provider")
                except Exception as e:
                    scraper_log('ERROR', 'google_cse', query, 'erro inesperado', exc=e)
                    print(f"[WEBSEARCH] Google CSE: erro — {e}")
            else:
                print(f"[WEBSEARCH] Google CSE: sem creditos hoje")
        else:
            print(f"[WEBSEARCH] Google CSE: nao configurada")

    # ── SOURCE 3: DuckDuckGo API (duckduckgo-search library) ─────────────────
    print(f"[WEBSEARCH] Fonte 3: DuckDuckGo API (biblioteca)...")
    scraper_log('INFO', 'ddgs_api', query, 'iniciando')
    try:
        def _call_ddgs():
            res = search_duckduckgo_api(query, max_results=max_pages * 10, safety=safety)
            if not res:
                raise QuotaExceededError('sem resultados — possivel bloqueio')
            return res
        ddg_results = _with_retry(_call_ddgs)()
        added = _add_results(ddg_results, 'ddgs_api')
        print(f"[WEBSEARCH] DDG API: +{added} URLs")
        scraper_log('INFO', 'ddgs_api', query, f'ok added={added}')
        if search_job_id and cursor:
            log_search(cursor, search_job_id, 'search_ok',
                      message=f'DDG API: {added} resultados adicionados')
    except RetryError as e:
        scraper_log('ERROR', 'ddgs_api', query, '3 tentativas esgotadas', exc=e)
        print(f"[WEBSEARCH] DDG API: 3 tentativas falharam — proximo provider")
    except Exception as e:
        scraper_log('ERROR', 'ddgs_api', query, 'erro inesperado', exc=e)
        print(f"[WEBSEARCH] DDG API: erro — {e}")

    # ── SOURCE 4: DuckDuckGo HTML scraping ───────────────────────────────────
    print(f"[WEBSEARCH] Fonte 4: DuckDuckGo HTML scraping (pages={max_pages})...")
    scraper_log('INFO', 'ddg_html', query, f'iniciando max_pages={max_pages}')
    try:
        def _call_ddg_html():
            res = search_duckduckgo(query, max_pages, safety)
            if not res:
                raise QuotaExceededError('sem resultados')
            return res
        ddg_html_results = _with_retry(_call_ddg_html)()
        added = _add_results(ddg_html_results, 'duckduckgo')
        print(f"[WEBSEARCH] DDG HTML: +{added} URLs")
        scraper_log('INFO', 'ddg_html', query, f'ok added={added}')
    except RetryError as e:
        scraper_log('ERROR', 'ddg_html', query, '3 tentativas esgotadas', exc=e)
        print(f"[WEBSEARCH] DDG HTML: 3 tentativas falharam — proximo provider")
    except Exception as e:
        scraper_log('ERROR', 'ddg_html', query, 'erro inesperado', exc=e)
        print(f"[WEBSEARCH] DDG HTML: erro — {e}")

    # ── SOURCE 5: Bing HTML scraping ──────────────────────────────────────────
    delay = random.uniform(3, 6)
    print(f"[WEBSEARCH] Fonte 5: Bing HTML scraping (delay={delay:.1f}s)...")
    scraper_log('INFO', 'bing_html', query, f'iniciando delay={delay:.1f}s')
    try:
        time.sleep(delay)
        def _call_bing_html():
            res = search_bing(query, max_pages, safety)
            if not res:
                raise QuotaExceededError('sem resultados')
            return res
        bing_html_results = _with_retry(_call_bing_html)()
        added = _add_results(bing_html_results, 'bing')
        print(f"[WEBSEARCH] Bing HTML: +{added} URLs")
        scraper_log('INFO', 'bing_html', query, f'ok added={added}')
    except RetryError as e:
        scraper_log('ERROR', 'bing_html', query, '3 tentativas esgotadas', exc=e)
        print(f"[WEBSEARCH] Bing HTML: 3 tentativas falharam — proximo provider")
    except Exception as e:
        scraper_log('ERROR', 'bing_html', query, 'erro inesperado', exc=e)
        print(f"[WEBSEARCH] Bing HTML: erro — {e}")

    # ── SOURCE 6: Yahoo HTML scraping ─────────────────────────────────────────
    delay2 = random.uniform(2, 5)
    print(f"[WEBSEARCH] Fonte 6: Yahoo HTML scraping (delay={delay2:.1f}s)...")
    scraper_log('INFO', 'yahoo_html', query, f'iniciando delay={delay2:.1f}s')
    try:
        time.sleep(delay2)
        def _call_yahoo():
            # _search_yahoo raises QuotaExceededError on rate limit (retry-able)
            # and returns [] on genuine "no results" (NOT retry-able)
            res = _search_yahoo(query, max_pages, safety)
            if not res:
                # Empty result = Yahoo has no results for this query — don't retry
                scraper_log('INFO', 'yahoo_html', query, 'sem resultados (query sem match no Yahoo)')
                return []
            return res
        yahoo_results = _with_retry(_call_yahoo)()
        if yahoo_results:
            added = _add_results(yahoo_results, 'yahoo')
            print(f"[WEBSEARCH] Yahoo HTML: +{added} URLs")
            scraper_log('INFO', 'yahoo_html', query, f'ok added={added}')
        else:
            print(f"[WEBSEARCH] Yahoo HTML: sem resultados para esta query")
    except RetryError as e:
        scraper_log('ERROR', 'yahoo_html', query, '3 tentativas esgotadas (rate limit)', exc=e)
        print(f"[WEBSEARCH] Yahoo HTML: rate limit — 3 tentativas falharam")
    except Exception as e:
        scraper_log('ERROR', 'yahoo_html', query, 'erro inesperado', exc=e)
        print(f"[WEBSEARCH] Yahoo HTML: erro — {e}")

    # ── Final summary ─────────────────────────────────────────────────────────
    total = len(all_results)
    if total == 0:
        scraper_log('CRITICAL', 'search_with_fallback', query,
                    f'TODOS os {6} providers falharam — nenhum resultado obtido')
        print(f"[WEBSEARCH] CRITICO: Todas as 6 fontes falharam para '{query}'")
        if search_job_id and cursor:
            log_search(cursor, search_job_id, 'search_failed',
                      message='Todos os providers falharam — nenhum resultado')
    else:
        engines_summary = ', '.join(engines_used) if engines_used else 'nenhum'
        print(f"[WEBSEARCH] TOTAL: {total} URLs unicas | Engines: {engines_summary}")
        scraper_log('INFO', 'search_with_fallback', query,
                    f'total={total} engines={engines_summary}')
        if search_job_id and cursor:
            log_search(cursor, search_job_id, 'search_ok',
                      message=f'Total agregado: {total} URLs de [{engines_summary}]')

    # Deduplicate by domain (keep first occurrence per domain)
    seen_domains = set()
    unique_results = []
    for r in all_results:
        try:
            domain = urlparse(r['url']).hostname
            if domain:
                domain = domain.replace('www.', '')
            if domain not in seen_domains:
                seen_domains.add(domain)
                unique_results.append(r)
        except Exception:
            unique_results.append(r)

    engine_used = engines_used[0] if engines_used else 'none'
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


@_persist_thread_errors('search_engines')
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
            city = job_data.get('city') or ''
            state = job_data.get('state') or ''
            region = job_data.get('region') or ''
            max_pages = job_data.get('max_pages', 2)

            # Update search job status
            query_parts = [niche]
            if city:
                query_parts.append(city)
            if state:
                query_parts.append(state)
            if not city and not state and region and region in SEARCH_REGIONS:
                query_parts.append(SEARCH_REGIONS[region]['name'])
            query = ' '.join(query_parts)
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
                        crawl_data = deep_crawl_domain_phase2(result_url, session)
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

        # Phase 3: Auto-tag + Fuzzy dedup
        try:
            tagged = auto_tag_batch(batch_id, conn)
            print(f"[search] Phase3 auto-tagged {tagged} leads in batch {batch_id}")
        except Exception as e3:
            print(f"[search] Phase3 auto-tag error: {e3}")
        try:
            dupes = fuzzy_deduplicate_leads(batch_id, conn)
            print(f"[search] Phase3 dedup: {dupes} duplicates in batch {batch_id}")
        except Exception as e3:
            print(f"[search] Phase3 dedup error: {e3}")

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

@_persist_thread_errors('api_enrichment')
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
                                crawl_data = deep_crawl_domain_phase2(result_url, session)
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

        # Phase 3: Auto-tag + Fuzzy dedup
        try:
            tagged = auto_tag_batch(batch_id, conn)
            print(f"[api_search] Phase3 auto-tagged {tagged} leads in batch {batch_id}")
        except Exception as e3:
            print(f"[api_search] Phase3 auto-tag error: {e3}")
        try:
            dupes = fuzzy_deduplicate_leads(batch_id, conn)
            print(f"[api_search] Phase3 dedup: {dupes} duplicates in batch {batch_id}")
        except Exception as e3:
            print(f"[api_search] Phase3 dedup error: {e3}")

        # Phase 1: Auto-enrich CNPJs found in this batch (background, non-blocking)
        try:
            c.execute(
                '''SELECT b.user_id FROM batches b WHERE b.id = %s''', (batch_id,)
            )
            uid_row = c.fetchone()
            if uid_row:
                t_enrich = threading.Thread(
                    target=_run_cnpj_enrichment,
                    args=(uid_row[0], None),
                    kwargs={},
                    daemon=True
                )
                t_enrich.start()
                print(f"[cnpj_enrich] Enriquecimento CNPJ iniciado em background para batch {batch_id}")
        except Exception as enrich_err:
            print(f"[cnpj_enrich] Aviso: nao foi possivel iniciar enrichment: {enrich_err}")

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

                # Deep crawl (Phase 2: enhanced with PDF + footer + team member extraction)
                result = deep_crawl_domain_phase2(url, session)

                # Insert leads for each email found
                now = datetime.now()
                first_phone = result['phones'][0] if result['phones'] else None
                # Phase 2: extra fields
                email_pattern_val = result.get('email_pattern')
                team_members_val = json.dumps(result.get('team_members', []), ensure_ascii=False) if result.get('team_members') else None
                pdf_emails_found = bool(result.get('pdf_emails_found'))

                for email in result['emails']:
                    c.execute(
                        '''INSERT INTO leads
                           (batch_id, company_name, email, phone, website, source_url, source,
                            instagram, facebook, linkedin, twitter, youtube,
                            whatsapp, cnpj, address, city, state, extracted_at,
                            email_pattern, team_members, pdf_emails_found)
                           VALUES (%s, %s, %s, %s, %s, %s, %s,
                                   %s, %s, %s, %s, %s,
                                   %s, %s, %s, %s, %s, %s,
                                   %s, %s, %s)
                           ON CONFLICT (batch_id, email) DO NOTHING''',
                        (batch_id, result['company_name'], email, first_phone,
                         result['website'], url, 'website_crawl',
                         result.get('instagram'), result.get('facebook'),
                         result.get('linkedin'), result.get('twitter'), result.get('youtube'),
                         result.get('whatsapp'), result.get('cnpj'),
                         result.get('address'), result.get('city'), result.get('state'), now,
                         email_pattern_val, team_members_val, pdf_emails_found)
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

        # Phase 3: Auto-tag + Fuzzy dedup
        try:
            tagged = auto_tag_batch(batch_id, conn)
            print(f"[batch {batch_id}] Phase3 auto-tagged {tagged} leads")
        except Exception as e3:
            print(f"[batch {batch_id}] Phase3 auto-tag error: {e3}")
        try:
            dupes = fuzzy_deduplicate_leads(batch_id, conn)
            print(f"[batch {batch_id}] Phase3 dedup: {dupes} duplicates")
        except Exception as e3:
            print(f"[batch {batch_id}] Phase3 dedup error: {e3}")

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

@app.route('/api/me', methods=['GET'])
@limiter.limit("60/minute")
def get_me():
    """Get current authenticated user info (id, username, is_admin, plan)"""
    try:
        token = get_auth_header()
        user_id = verify_token(token)
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id, username, is_admin, plan FROM users WHERE id = %s', (user_id,))
            row = c.fetchone()
            if not row:
                return jsonify({'error': 'User not found'}), 404
            return jsonify({
                'id': row[0],
                'username': row[1],
                'is_admin': row[2],
                'plan': row[3]
            }), 200
    except Exception as e:
        print(f'[ERROR] /api/me: {e}')
        return jsonify({'error': str(e)}), 500

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

    # AUTO-SANITIZE + SYNC: sanitiza leads ao completar, depois sincroniza com CRM
    threading.Thread(target=auto_sanitize_background, args=(batch_id,), daemon=True).start()

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

    # AUTO-SANITIZE + SYNC: sanitiza leads ao completar, depois sincroniza com CRM
    threading.Thread(target=auto_sanitize_background, args=(batch_id,), daemon=True).start()

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

    # AUTO-SANITIZE + SYNC: sanitiza leads ao completar, depois sincroniza com CRM
    threading.Thread(target=auto_sanitize_background, args=(batch_id,), daemon=True).start()

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
                         b.name as batch_name, l.batch_id, COALESCE(l.lead_score, 0) as lead_score
                  FROM leads l JOIN batches b ON l.batch_id = b.id
                  WHERE b.user_id = %s'''

# Semana 4: Shared base — clients see all shared leads, not just their own
SHARED_LEADS_SELECT = '''SELECT l.id, l.company_name, l.email, l.phone, l.website, l.source_url,
                                l.city, l.state, l.category, l.extracted_at,
                                l.instagram, l.facebook, l.linkedin, l.twitter, l.youtube,
                                l.whatsapp, l.cnpj, l.address,
                                l.crm_status, l.tags, l.notes, l.contact_name, l.updated_at,
                                b.name as batch_name, l.batch_id, COALESCE(l.lead_score, 0) as lead_score
                         FROM leads l JOIN batches b ON l.batch_id = b.id
                         WHERE b.is_shared = TRUE'''

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
        'lead_score': row[25] if row[25] is not None else 0,
    }


# ======= Lead Scoring =======

GENERIC_COMPANY_NAMES = {
    'sem nome', 'unknown', 'n/a', 'na', 'empresa', 'company', 'test', 'teste',
    'nome', 'name', 'business', 'negocio', 'negócio', '-', 'null', 'none'
}

def _calculate_lead_score(lead: dict) -> int:
    """Calculate a deterministic quality score 0-100 for a lead.

    Scoring rubric:
      +30  email válido presente
      +15  nome de empresa presente e não genérico
      +15  nome de contato (pessoa) presente
      +10  cidade presente
      +10  telefone presente
      +10  website presente
       +5  estado presente
       +5  categoria/segmento presente
    Penalty:
      -15  nome de empresa genérico ou suspeito
    Range enforced: 0–100
    """
    score = 0

    # Email (+30)
    email = (lead.get('email') or '').strip()
    if email and '@' in email and '.' in email.split('@')[-1]:
        score += 30

    # Company name (+15 or -15)
    company = (lead.get('company_name') or '').strip()
    company_lower = company.lower()
    if company and company_lower not in GENERIC_COMPANY_NAMES and len(company) > 2:
        score += 15
    elif company_lower in GENERIC_COMPANY_NAMES:
        score -= 15

    # Contact name (+15)
    contact = (lead.get('contact_name') or '').strip()
    if contact and len(contact) > 2:
        score += 15

    # City (+10)
    if (lead.get('city') or '').strip():
        score += 10

    # Phone (+10)
    if (lead.get('phone') or '').strip():
        score += 10

    # Website (+10)
    if (lead.get('website') or '').strip():
        score += 10

    # State (+5)
    if (lead.get('state') or '').strip():
        score += 5

    # Category (+5)
    if (lead.get('category') or '').strip():
        score += 5

    return max(0, min(100, score))

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
    city = request.args.get('city', '').strip()
    state = request.args.get('state', '').strip()
    sort = request.args.get('sort', 'newest')
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(100, max(10, int(request.args.get('per_page', 50))))

    # Semana 4: use shared base — all authenticated users see the central lead pool
    query = SHARED_LEADS_SELECT
    params = []

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

    if city:
        query += ' AND l.city ILIKE %s'
        params.append(f'%{city}%')

    if state:
        query += ' AND l.state ILIKE %s'
        params.append(f'%{state}%')

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
        elif sort == 'score':
            query += ' ORDER BY COALESCE(l.lead_score, 0) DESC'
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

        # Get status counts (shared base)
        c.execute('''SELECT COALESCE(l.crm_status, 'novo') as status, COUNT(*)
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE
                     GROUP BY COALESCE(l.crm_status, 'novo')''')
        status_counts = {row[0]: row[1] for row in c.fetchall()}

        # Get all unique tags (shared base)
        c.execute('''SELECT DISTINCT unnest(string_to_array(l.tags, ','))
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE AND l.tags IS NOT NULL AND l.tags != ''
                     ORDER BY 1''')
        all_tags = [row[0].strip() for row in c.fetchall() if row[0].strip()]

    leads = [lead_row_to_dict(row) for row in rows]

    # SaaS: Track usage and check limits
    plan = _get_user_plan(user_id)
    limits = _get_plan_limits(plan)
    usage = _get_usage_stats(user_id)

    # Count leads being viewed on this page
    leads_count = len(leads)

    # Check if user is approaching or exceeding limit
    response_data = {
        'leads': leads,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': max(1, (total + per_page - 1) // per_page),
        'status_counts': status_counts,
        'all_tags': all_tags,
        'plan': plan,
        'usage': {
            'leads_viewed': usage['leads_viewed'],
            'leads_limit': limits['leads_per_month'],
            'usage_percent': (usage['leads_viewed'] / limits['leads_per_month'] * 100) if limits['leads_per_month'] > 0 else 0
        }
    }

    # Increment view counter
    if leads_count > 0:
        _increment_usage(user_id, 'leads_viewed', leads_count)

    return jsonify(response_data)

@app.route('/api/leads/locations/available', methods=['GET'])
@limiter.limit("60/minute")
def get_available_locations():
    """Get all available cities and states for lead filtering."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()

        # Get unique cities from shared base
        c.execute('''SELECT DISTINCT TRIM(l.city) as city
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE AND l.city IS NOT NULL AND l.city != ''
                     ORDER BY city''')
        cities = [row[0] for row in c.fetchall() if row[0]]

        # Get unique states from shared base
        c.execute('''SELECT DISTINCT TRIM(l.state) as state
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE AND l.state IS NOT NULL AND l.state != ''
                     ORDER BY state''')
        states = [row[0] for row in c.fetchall() if row[0]]

    return jsonify({
        'cities': cities,
        'states': states,
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
        c.execute(SHARED_LEADS_SELECT + ' AND l.id = %s', (lead_id,))
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


@app.route('/api/leads/delete-all', methods=['POST'])
@limiter.limit("5/hour")
def delete_all_leads():
    """Delete ALL leads for the authenticated user. Irreversible."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    if not data.get('confirm'):
        return jsonify({'error': 'confirm: true is required'}), 400

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            '''DELETE FROM leads
               WHERE batch_id IN (SELECT id FROM batches WHERE user_id = %s)''',
            (user_id,)
        )
        deleted = c.rowcount

    return jsonify({'message': f'{deleted} leads deletados', 'deleted': deleted})


@app.route('/api/leads/sync-and-delete', methods=['POST'])
@limiter.limit("3/hour")
def sync_and_delete_leads():
    """
    Sync ALL leads to alexandrequeiroz.com.br CRM (synchronously),
    then delete all leads for the user. Irreversible.
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    if not data.get('confirm'):
        return jsonify({'error': 'confirm: true is required'}), 400

    # Step 1: Fetch all leads with email for sync
    conn = psycopg2.connect(**DB_CONFIG)
    c = conn.cursor()
    try:
        c.execute(
            '''SELECT company_name, email, phone, website, city, state, source
               FROM leads
               WHERE email IS NOT NULL AND email != ''
               AND batch_id IN (SELECT id FROM batches WHERE user_id = %s)
               ORDER BY extracted_at DESC''',
            (user_id,)
        )
        rows = c.fetchall()
        leads_to_sync = [
            {
                'company_name': row[0],
                'email': row[1],
                'phone': row[2],
                'website': row[3],
                'city': row[4],
                'state': row[5],
                'source': row[6] or 'extrator-dados',
            }
            for row in rows
        ]
    finally:
        c.close()
        conn.close()

    # Step 2: Sync synchronously (wait for completion before deleting)
    synced, skipped, errors = 0, 0, 0
    if leads_to_sync:
        print(f"[SYNC-DELETE] Syncing {len(leads_to_sync)} leads to CRM before delete...")
        synced, skipped, errors = sync_leads_batch_to_alexandrequeiroz(
            leads_to_sync, max_leads=len(leads_to_sync)
        )
        print(f"[SYNC-DELETE] Sync done: {synced} created, {skipped} skipped, {errors} errors")

    # Step 3: Delete all leads for user
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            '''DELETE FROM leads
               WHERE batch_id IN (SELECT id FROM batches WHERE user_id = %s)''',
            (user_id,)
        )
        deleted = c.rowcount

    print(f"[SYNC-DELETE] Deleted {deleted} leads for user {user_id}")

    return jsonify({
        'message': f'{synced} sincronizados, {skipped} já existiam, {errors} erros. {deleted} leads deletados.',
        'synced': synced,
        'skipped': skipped,
        'errors': errors,
        'deleted': deleted,
    })


# ============================================================
# LEAD SANITIZATION ENGINE
# ============================================================

# Domínios de baixa reputação / spam conhecidos
SPAM_DOMAINS = {
    'guerrillamail.com', 'mailinator.com', 'tempmail.com', 'throwaway.email',
    'sharklasers.com', 'guerrillamailblock.com', 'grr.la', 'guerrillamail.info',
    'spam4.me', 'trashmail.com', 'yopmail.com', 'dispostable.com',
    'fakeinbox.com', 'maildrop.cc', 'mailnull.com', 'spamgourmet.com',
    'trashmail.at', 'mailnesia.com', 'mailnull.com', 'spamhereplease.com',
    'spamherelots.com', 'dispostable.com',
}

# Extensões de domínio claramente incorretas (resultado de scraping ruim)
BAD_DOMAIN_EXTENSIONS = [
    r'\.com\.brav\b', r'\.com\.brhor\b', r'\.com\.brs\b', r'\.com\.brm\b',
    r'\.coom\b', r'\.con\b', r'\.com\.b$', r'\.com\.br\.',
    r'\.net\.bra\b', r'\.org\.bra\b', r'\.cmo\b', r'\.ocm\b',
    r'\.(com|net|org)\.[a-z]{3,}br\b',  # .com.XYZbr patterns
]

# Prefixos genéricos (não pessoais) para classificação de tipo de email
GENERIC_EMAIL_PREFIXES = {
    'contato', 'contact', 'info', 'atendimento', 'suporte', 'support',
    'vendas', 'sales', 'comercial', 'financeiro', 'rh', 'recursos-humanos',
    'marketing', 'adm', 'admin', 'administracao', 'recepcao', 'portaria',
    'ouvidoria', 'sac', 'faleconosco', 'contatos', 'comunicacao',
    'newsletter', 'noticias', 'secretaria', 'gestao', 'diretoria',
    'ti', 'fiscal', 'juridico', 'compras', 'logistica', 'operacional',
    'cobranca', 'pos-venda', 'posvenda', 'relacionamento',
}

# Palavras que indicam nome pessoal no email (letras + ponto + letras)
_PERSONAL_EMAIL_RE = re.compile(r'^[a-z]{2,}\.[a-z]{2,}(@|$)')


try:
    import ftfy as _ftfy
    _FTFY_AVAILABLE = True
except ImportError:
    _ftfy = None
    _FTFY_AVAILABLE = False

def fix_text_encoding(text):
    """
    Corrige problemas comuns de encoding/acentuação em textos scrapeados.
    Prioriza ftfy (especializado em mojibake), depois fallbacks manuais.
    """
    if not text:
        return text

    # Estratégia 0: ftfy (melhor para mojibake como Ã© -> é, Ã³ -> ó)
    if _FTFY_AVAILABLE:
        try:
            fixed = _ftfy.fix_text(text)
            if fixed and fixed != text:
                return fixed.strip()
        except Exception:
            pass

    # Estratégia 1: latin-1 bytes reinterpretados como utf-8
    try:
        fixed = text.encode('latin-1').decode('utf-8')
        return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    # Estratégia 2: cp1252 -> utf-8
    try:
        fixed = text.encode('cp1252').decode('utf-8')
        return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    # Estratégia 3: remover replacement chars e controles
    try:
        import unicodedata
        normalized = unicodedata.normalize('NFKC', text)
        cleaned = ''.join(
            c for c in normalized
            if unicodedata.category(c) not in ('Cc', 'Cf') or c in '\n\t '
        )
        # Remove U+FFFD (replacement char) que indica info perdida
        cleaned = cleaned.replace('\ufffd', '')
        return cleaned.strip()
    except Exception:
        pass

    return text


# ── Nomes genéricos que devem ser substituídos por nome derivado do domínio ──
_GENERIC_NAMES = {
    'home', 'index', 'inicio', 'início', 'pagina inicial', 'página inicial',
    'page', 'main', 'welcome', 'untitled', 'default', 'site', 'website',
    'null', 'none', 'n/a', 'na', '-', '—', 'sem nome',
    # Fontes de busca (não são nomes de empresa)
    'jusbrasil', 'guiamais', 'guia mais', 'telelistas', 'apontador',
    'yellowpages', 'paginas amarelas', 'páginas amarelas', 'catalogo',
    'empresas', 'google', 'bing', 'linkedin', 'facebook', 'instagram',
}

# Conjunções/preposições que ficam minúsculas em title case
_LOWERCASE_CONJUNCTIONS = {
    'de', 'da', 'do', 'das', 'dos', 'e', 'em', 'para', 'com', 'por',
    'na', 'no', 'nas', 'nos', 'a', 'o', 'ao', 'aos', 'à', 'às',
}

# Siglas de estados + sufixos jurídicos que ficam MAIÚSCULOS
_UPPERCASE_TOKENS = {
    'es', 'sp', 'rj', 'mg', 'rs', 'sc', 'pr', 'ba', 'pe', 'ce',
    'am', 'pa', 'go', 'df', 'rn', 'pb', 'al', 'se', 'pi', 'ma',
    'to', 'ac', 'ro', 'rr', 'ap', 'mt', 'ms', 'pi',
    'ltda', 'me', 'eireli', 'sa', 'epp', 'mei', 'ss', 'sl',
}


def smart_title_case(text):
    """Title case inteligente: respeita conjunções minúsculas, siglas e estados em MAIÚSCULO."""
    if not text:
        return text
    text = text.strip()
    # Se já tem capitalização mista correta (ex: 'Clínica Saúde'), não mexer
    # Só corrige se tudo maiúsculo, tudo minúsculo, ou começa com minúscula
    if not (text.isupper() or text.islower() or (text and text[0].islower())):
        # Garante pelo menos a primeira letra maiúscula
        return text[0].upper() + text[1:] if text else text

    tokens = re.split(r'(\s+|-)', text)
    result = []
    word_index = 0
    for tok in tokens:
        if re.match(r'\s+|-', tok):
            result.append(tok)
            continue
        tok_lower = tok.lower()
        if tok_lower in _UPPERCASE_TOKENS:
            result.append(tok.upper())
        elif word_index > 0 and tok_lower in _LOWERCASE_CONJUNCTIONS:
            result.append(tok_lower)
        else:
            result.append(tok.capitalize())
        word_index += 1
    return ''.join(result)


def _derive_name_from_domain(domain_str):
    """Converte slug de domínio em nome legível. Ex: 'bicho-mimado-es' -> 'Bicho Mimado ES'."""
    if not domain_str:
        return None
    # Remove extensões de domínio (.com.br, .net, .org, etc.)
    slug = re.sub(r'\.(com|net|org|br|io|co|info|biz)(\.\w+)?$', '', domain_str, flags=re.I)
    slug = slug.strip('/-.')
    if not slug or len(slug) < 3:
        return None
    # Substituir hifens/underscores por espaço
    name = re.sub(r'[-_]', ' ', slug)
    return smart_title_case(name)


def extract_clean_company_name(name, email=None, website=None):
    """
    Pipeline completo de normalização do nome da empresa:
    1. Fix encoding (mojibake, replacement chars)
    2. Extrair nome de contexto multi-linha (ex: 'Jusbrasil\\nAdvogados...\\nemail@...')
    3. Limpar artefatos de título de página (ex: 'Home | Empresa' -> 'Empresa')
    4. Se nome genérico/vazio, derivar do domínio do email ou website
    5. Aplicar smart title case
    """
    # 1. Fix encoding
    name = fix_text_encoding(name or '')

    # 2. Extrair de contexto multi-linha
    if name and ('\n' in name or len(name) > 120):
        lines = [l.strip() for l in name.split('\n') if l.strip()]
        candidates = []
        for line in lines:
            # Ignorar linhas que são emails, URLs, longas demais, ou contexto de busca
            if '@' in line:
                continue
            if re.match(r'https?://', line, re.I):
                continue
            if re.match(r'[\w.-]+\.(com|br|net|org|io|co)(\.\w+)?/?$', line, re.I):
                continue
            if len(line) > 80:
                continue
            candidates.append(line)
        name = candidates[0] if candidates else (lines[0] if lines else name)

    # 3. Limpar artefatos de título de página
    if name:
        # "Home | Clínica Saúde" -> "Clínica Saúde" (ou vice-versa)
        # "Index - Empresa ABC"  -> "Empresa ABC"
        for sep in [' | ', ' - ', ' – ', ' — ', ' :: ', ' » ', ' > ']:
            if sep in name:
                parts = [p.strip() for p in name.split(sep) if p.strip()]
                # Pega a parte que não é genérica
                non_generic = [p for p in parts if p.lower().strip() not in _GENERIC_NAMES]
                if non_generic:
                    name = non_generic[0]
                    break
                elif parts:
                    name = parts[-1]  # pega a última
                    break
        # Remove sufixos comuns de títulos de página
        name = re.sub(r'\s*[-|–]\s*(Home|Index|Início|Welcome|Página Inicial)$', '', name, flags=re.I).strip()

    # 4. Detectar nome genérico/inútil e derivar do email/website
    name_check = (name or '').strip().lower()
    is_generic = (
        not name_check
        or name_check in _GENERIC_NAMES
        or len(name_check) <= 2
        or re.match(r'^[\d\s\-\/\\]+$', name_check)  # só números/símbolos
    )

    if is_generic:
        derived = None
        # Tentar derivar do email
        if email and '@' in email:
            domain = email.split('@')[1]
            slug = domain.split('.')[0]  # altefrezende de altefrezende.com.br
            derived = _derive_name_from_domain(slug)
        # Tentar derivar do website
        if not derived and website:
            clean_url = re.sub(r'https?://', '', website).split('/')[0]  # remove protocolo e path
            slug = clean_url.split('.')[0]
            derived = _derive_name_from_domain(slug)
        if derived:
            name = derived

    # 5. Smart title case
    name = smart_title_case(name or '')

    return name.strip() if name else ''


_GARBAGE_NAME_RE = re.compile(
    r'(clique aqui|saiba mais|leia mais|acesse|entre em contato|fale conosco'
    r'|nosso site|nossa empresa|telefone|whatsapp|endereço|horário'
    r'|copyright|todos os direitos|\d{2}/\d{2}/\d{4}'
    r'|https?://|www\.|\.com|\.br)',
    re.I
)

def is_garbage_name(name):
    """
    Retorna True se o nome é claramente um fragmento de texto/frase, não um nome de empresa.
    Casos rejeitados:
    - Muito curto (< 3 caracteres)
    - Mais de 6 palavras (provavelmente uma frase)
    - Contém URLs, datas, palavras de marketing típicas
    - Contém apenas números e símbolos
    """
    if not name:
        return True
    name = name.strip()
    if len(name) < 3:
        return True
    # Apenas números / símbolos
    if re.match(r'^[\d\s\-\/\\\.,:;!?@#$%&*()\[\]]+$', name):
        return True
    # Demasiadas palavras = frase
    word_count = len(name.split())
    if word_count > 6:
        return True
    # Padrões de lixo de scraping
    if _GARBAGE_NAME_RE.search(name):
        return True
    return False


def classify_email_type(email):
    """
    Classifica o email como 'generico' ou 'pessoal'.
    Retorna: 'pessoal', 'generico' ou 'desconhecido'
    """
    if not email or '@' not in email:
        return 'desconhecido'
    local = email.split('@')[0].lower()
    # Check prefixo genérico
    if local in GENERIC_EMAIL_PREFIXES:
        return 'generico'
    # Padrão nome.sobrenome
    if _PERSONAL_EMAIL_RE.match(local):
        return 'pessoal'
    # Se tem número e texto (joao123, maria.2023)
    if re.match(r'^[a-z]{2,}[0-9]{1,4}$', local):
        return 'pessoal'
    return 'desconhecido'


def has_bad_domain_extension(email):
    """Detecta extensões de domínio incorretas resultantes de scraping ruim."""
    if not email:
        return False
    domain_part = email.split('@')[-1] if '@' in email else email
    for pattern in BAD_DOMAIN_EXTENSIONS:
        if re.search(pattern, domain_part):
            return True
    return False


def is_spam_domain(email):
    """Detecta domínios de spam/temporários."""
    if not email or '@' not in email:
        return False
    domain = email.split('@')[-1].lower().strip()
    return domain in SPAM_DOMAINS


def sanitize_single_lead(lead_dict):
    """
    Aplica todas as regras de sanitização a um lead.
    Retorna (sanitized_dict, issues_list, is_valid_bool).
    """
    issues = []
    lead = dict(lead_dict)

    # 1a. Normalizar company_name (encoding + extração de contexto + title case + derivação)
    original_name = lead.get('company_name') or ''
    clean_name = extract_clean_company_name(
        original_name,
        email=lead.get('email'),
        website=lead.get('website'),
    )
    if clean_name and clean_name != original_name:
        issues.append('company_name_normalized')
        lead['company_name'] = clean_name

    # 1b. Corrigir encoding de outros campos de texto
    for field in ('address', 'city', 'state', 'contact_name', 'notes'):
        val = lead.get(field)
        if val and isinstance(val, str):
            fixed = fix_text_encoding(val)
            if fixed != val:
                issues.append(f'encoding_corrected:{field}')
                lead[field] = fixed

    # 1c. Smart title case em city e state também
    for field in ('city', 'state'):
        val = lead.get(field)
        if val and isinstance(val, str):
            cased = smart_title_case(val)
            if cased != val:
                lead[field] = cased

    # 2. Validar e sanitizar email
    email = (lead.get('email') or '').strip().lower()
    email_valid = False
    email_type = 'desconhecido'

    if email and not email.endswith(('@directory.local', '@instagram.local', '@linkedin.local')):
        # 2a. Detecção de extensão de domínio ruim
        if has_bad_domain_extension(email):
            issues.append(f'bad_domain_extension:{email}')
            lead['email'] = None
        # 2b. Domínio de spam
        elif is_spam_domain(email):
            issues.append(f'spam_domain:{email}')
            lead['email'] = None
        else:
            # 2c. Validação via função existente
            score, is_valid, reason = calculate_email_quality_score(email)
            if not is_valid:
                issues.append(f'email_invalid:{reason}:{email[:50]}')
                lead['email'] = None
            elif score < 40:
                issues.append(f'email_low_quality:score={score}:{email[:50]}')
                lead['email'] = None
            else:
                email_valid = True
                email_type = classify_email_type(email)
                lead['email_type'] = email_type

    # 3. Recalcular quality_score com dados atualizados
    lead['quality_score'] = calculate_quality_score(lead)

    # Lead é válido se tem pelo menos email ou telefone ou rede social
    has_contact = bool(lead.get('email') or lead.get('phone') or
                       lead.get('instagram') or lead.get('linkedin') or
                       lead.get('whatsapp'))

    return lead, issues, has_contact


@app.route('/api/leads/sanitize', methods=['POST'])
@limiter.limit("5/minute")
def sanitize_leads():
    """
    Sanitize leads in DB: fix encoding, validate emails, remove duplicates,
    classify email types, recalculate quality scores.
    Accepts: { lead_ids: [...] } for selected, or {} for all user leads.
    Returns: summary report.
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    lead_ids = data.get('lead_ids', [])  # empty = all leads

    with get_db() as conn:
        c = conn.cursor()

        # Fetch leads to sanitize
        if lead_ids:
            placeholders = ','.join(['%s'] * len(lead_ids))
            c.execute(
                f'''SELECT l.id, l.company_name, l.email, l.phone, l.website, l.address,
                           l.city, l.state, l.source, l.instagram, l.linkedin, l.facebook,
                           l.whatsapp, l.cnpj, l.contact_name, l.notes, l.crm_status,
                           l.quality_score, l.batch_id
                    FROM leads l
                    JOIN batches b ON b.id = l.batch_id
                    WHERE l.id IN ({placeholders}) AND b.user_id = %s''',
                lead_ids + [user_id]
            )
        else:
            c.execute(
                '''SELECT l.id, l.company_name, l.email, l.phone, l.website, l.address,
                          l.city, l.state, l.source, l.instagram, l.linkedin, l.facebook,
                          l.whatsapp, l.cnpj, l.contact_name, l.notes, l.crm_status,
                          l.quality_score, l.batch_id
                   FROM leads l
                   JOIN batches b ON b.id = l.batch_id
                   WHERE b.user_id = %s
                   ORDER BY l.id''',
                (user_id,)
            )

        rows = c.fetchall()
        cols = ['id', 'company_name', 'email', 'phone', 'website', 'address',
                'city', 'state', 'source', 'instagram', 'linkedin', 'facebook',
                'whatsapp', 'cnpj', 'contact_name', 'notes', 'crm_status',
                'quality_score', 'batch_id']
        leads_raw = [dict(zip(cols, row)) for row in rows]

        total_analyzed = len(leads_raw)
        invalid_emails = 0
        encoding_corrected = 0
        spam_detected = 0
        duplicates_removed = 0
        quality_updated = 0
        no_contact_removed = 0
        ids_to_delete = []
        seen_emails = {}  # email -> lead_id (keep first/best, delete rest)

        # Pass 1: sanitize each lead
        sanitized_leads = []
        for lead in leads_raw:
            original_email = lead.get('email') or ''
            sanitized, issues, has_contact = sanitize_single_lead(lead)

            if any('encoding_corrected' in i for i in issues):
                encoding_corrected += 1
            if any('email_invalid' in i or 'bad_domain' in i or 'email_low_quality' in i for i in issues):
                invalid_emails += 1
            if any('spam_domain' in i for i in issues):
                spam_detected += 1

            # Remove leads without any valid contact method
            if not has_contact:
                ids_to_delete.append(lead['id'])
                no_contact_removed += 1
                continue

            sanitized_leads.append(sanitized)

        # Pass 2: detect duplicates by normalized email
        email_map = {}
        for lead in sanitized_leads:
            email = (lead.get('email') or '').strip().lower()
            if not email:
                continue
            if email in email_map:
                # Keep the one with more data (higher quality_score or more fields)
                existing = email_map[email]
                existing_score = sum(1 for f in ('phone', 'website', 'instagram', 'whatsapp', 'cnpj') if existing.get(f))
                new_score = sum(1 for f in ('phone', 'website', 'instagram', 'whatsapp', 'cnpj') if lead.get(f))
                if new_score > existing_score:
                    ids_to_delete.append(existing['id'])
                    email_map[email] = lead
                else:
                    ids_to_delete.append(lead['id'])
                duplicates_removed += 1
            else:
                email_map[email] = lead

        # Pass 3: apply updates to DB
        for lead in sanitized_leads:
            if lead['id'] in ids_to_delete:
                continue  # Will be deleted
            try:
                new_email = lead.get('email') or None
                new_quality = lead.get('quality_score', 'basico')
                new_company = lead.get('company_name') or None
                new_address = lead.get('address') or None
                new_city = lead.get('city') or None
                new_notes = lead.get('notes') or None
                email_type = lead.get('email_type') or None

                # Build tags addition for email_type
                existing_tags = (lead.get('notes') or '')

                c.execute(
                    '''UPDATE leads SET
                         email = %s,
                         company_name = %s,
                         address = %s,
                         city = %s,
                         quality_score = %s,
                         notes = %s,
                         updated_at = %s
                       WHERE id = %s''',
                    (new_email, new_company, new_address, new_city,
                     new_quality, new_notes, datetime.now(), lead['id'])
                )
                quality_updated += 1
            except Exception as e:
                print(f"[sanitize] Erro update lead {lead['id']}: {e}")

        # Delete duplicates
        if ids_to_delete:
            placeholders = ','.join(['%s'] * len(ids_to_delete))
            c.execute(
                f'DELETE FROM leads WHERE id IN ({placeholders})',
                ids_to_delete
            )

        conn.commit()

    return jsonify({
        'success': True,
        'report': {
            'analyzed': total_analyzed,
            'invalid_emails': invalid_emails,
            'encoding_corrected': encoding_corrected,
            'spam_detected': spam_detected,
            'duplicates_removed': duplicates_removed,
            'no_contact_removed': no_contact_removed,
            'quality_updated': quality_updated,
            'ids_deleted': len(ids_to_delete),
        }
    })


# ============= AI Name/Email Normalizer =============

def _get_llm_key_for_normalize():
    """Returns (provider, api_key) — tries OpenRouter first, then Groq."""
    blob = _fetch_secret_blob_from_aws('tools/openrouter')
    if blob:
        key = _read_secret_key_from_blob(blob, ['OPENROUTER_API_KEY'])
        if key:
            return 'openrouter', key
    blob = _fetch_secret_blob_from_aws('tools/groq')
    if blob:
        key = _read_secret_key_from_blob(blob, ['GROQ_API_KEY'])
        if key:
            return 'groq', key
    return None, None


def _call_llm_normalize(prompt, provider, api_key):
    """Call LLM and return parsed JSON. Raises on failure."""
    import requests as _req
    import json as _json

    if provider == 'openrouter':
        url = 'https://openrouter.ai/api/v1/chat/completions'
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        payload = {'model': 'deepseek/deepseek-chat', 'messages': [{'role': 'user', 'content': prompt}], 'temperature': 0.1, 'max_tokens': 4000}
    elif provider == 'groq':
        url = 'https://api.groq.com/openai/v1/chat/completions'
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        payload = {'model': 'llama-3.1-8b-instant', 'messages': [{'role': 'user', 'content': prompt}], 'temperature': 0.1, 'max_tokens': 4000}
    else:
        raise ValueError(f'Unknown provider: {provider}')

    resp = _req.post(url, headers=headers, json=payload, timeout=45)
    resp.raise_for_status()
    resp_json = resp.json()
    content = resp_json['choices'][0]['message']['content'].strip()
    usage = resp_json.get('usage', {})
    # Strip markdown code fences if present
    if content.startswith('```'):
        content = re.sub(r'^```[a-z]*\n?', '', content)
        content = re.sub(r'\n?```$', '', content)
    import json as _json2
    parsed = _json2.loads(content)
    # Attach usage metadata to result
    if isinstance(parsed, dict):
        parsed['_usage'] = {
            'provider': provider,
            'prompt_tokens': usage.get('prompt_tokens', 0),
            'completion_tokens': usage.get('completion_tokens', 0),
            'total_tokens': usage.get('total_tokens', 0),
        }
    return parsed


def _ai_normalize_batch(leads_batch):
    """
    Send a batch of leads to LLM for normalization.
    Returns (results_list, error_str).
    results_list items: {id, company_name, email, contact_name}
    """
    import json as _json

    provider, api_key = _get_llm_key_for_normalize()
    if not api_key:
        return None, 'Chave LLM não disponível (configure OpenRouter ou Groq no AWS SM)'

    leads_input = [
        {
            'id': l['id'],
            'company_name': (l.get('company_name') or '').strip(),
            'email': (l.get('email') or '').strip(),
            'contact_name': (l.get('contact_name') or '').strip(),
        }
        for l in leads_batch
    ]

    prompt = f"""Você é um especialista em limpeza e normalização de dados de leads empresariais brasileiros. Siga as instruções abaixo com precisão.

━━ CAMPO: company_name ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Remova sufixos jurídicos: LTDA, ME, EIRELI, S/A, EPP, SS, S.S., LTDA ME, LTDA EPP, S.A., SA, MICRO EMPRESA, MICROEMPRESA, SOCIEDADE SIMPLES.
2. Substitua hifens usados como separadores por espaços (ex: "Clínica-Saúde" → "Clínica Saúde", "Auto-Peças" → "Auto Peças").
3. Se o nome for um slogan, frase de marketing ou título de categoria de diretório, substitua pelo nome derivado do domínio do email (se disponível) ou retorne "".
   Identifique como INVÁLIDO (não é nome de empresa) quando:
   a) Contém verbos/palavras de marketing: "seja", "venha", "conheça", "bem-vindo", "confira", "clique", "acesse", "saiba mais", "qualidade", "excelência", "ligue", "entre em contato".
   b) É um título de categoria de diretório: padrão "[Categoria] em [Cidade/Estado]" ou "[Categoria] e [Categoria] em [Cidade]".
      Exemplos: "Oficinas Mecânicas em Vila Velha", "Restaurantes e Lanchonetes em São Paulo", "Clínicas Odontológicas em Vitória/ES".
   c) É um título de artigo/listicle com número ordinal ou superlativo: padrão "N Melhores [X] em [Y]", "Top N [X]", "Os Melhores [X] de [Y]", "Lista de [X]", "Melhores [X] em [Y]".
      Exemplos: "10 Melhores Oficinas Mecânicas em Vila Velha", "Top 5 Restaurantes em SP", "Os Melhores Dentistas de Vitória".
   d) É uma descrição genérica de segmento sem nome próprio: "Oficina Mecânica", "Restaurante", "Clínica Médica" (sem nome próprio após).
   e) Contém CNPJ embutido no início ou no meio (padrão XX.XXX.XXX/XXXX-XX): remova o CNPJ e processe o restante normalmente.
4b. Se o nome começa com um nome próprio de empresa seguido de descrição de categoria+localidade (padrão "[NomeEmpresa] [Categoria] [Cidade/Estado]"), extraia apenas o nome próprio inicial e descarte o restante.
    Exemplos:
    - "Financial Contabilidade Escritório de Contabilidade Vitória/ES" → "Financial Contabilidade"
    - "Sorriso Feliz Clínica Odontológica em Vila Velha ES" → "Sorriso Feliz"
    - "Auto Center Silva Oficina Mecânica Cariacica" → "Auto Center Silva"
   - Se houver email disponível: derive o nome a partir do email seguindo este processo:
     a) Se o domínio for corporativo (não gmail/hotmail/yahoo/outlook/bol/uol/terra): use o domínio (ex: `facilittacont.com.br` → "Facilitta Cont", `w3contabilidade.com.br` → "W3 Contabilidade").
     b) Se o domínio for pessoal (gmail/hotmail/yahoo/outlook/bol/uol/terra): use o local-part (antes do @), removendo PRIMEIRO os sufixos genéricos no final (contato, info, comercial, vendas, atendimento, faleconosco, email, empresa, comercial01, comercial02) e DEPOIS os prefixos genéricos no início (contato, info, comercial).
        Exemplo: "ateliepatriciaalmeidacontato@gmail.com" → remove sufixo "contato" → "ateliepatriciaalmeida" → "Ateliê Patricia Almeida"
        Exemplo: "anizioautopecas@gmail.com" → sem sufixo/prefixo genérico → "Anizio Auto Peças"
        Exemplo: "contato@gmail.com" → local-part é puramente genérico → retorne ""
     c) Processo de separação de palavras concatenadas: detecte transições de minúscula→maiúscula (camelCase), pontos, hifens, números entre letras, ou padrões semânticos óbvios (ex: "autocenter" → "Auto Center", "clinicasorriso" → "Clínica Sorriso").
     d) Aplique Title Case e corrija acentuação óbvia: pecas→peças, clinica→clínica, odonto→Odonto, atelie→Ateliê, joao→João, etc.
   - Se o email não existir e não houver como derivar nome: retorne "".
4. Aplique Title Case correto para português: preposições "de", "da", "do", "e", "das", "dos", "no", "na", "em", "com", "por", "para" em minúsculas quando no meio do nome.
5. Remova fragmentos de URL, CNPJ (padrão XX.XXX.XXX/XXXX-XX), números de telefone, ou texto genérico como "Página Inicial", "Home", "Site", "Empresa", "Nossa Empresa".
6. Se, após a limpeza, a string estiver vazia ou tiver menos de 2 caracteres, retorne "".

Exemplos:
- "CLÍNICA SORRISO LTDA" → "Clínica Sorriso"
- "Auto-Center-Vitória ME" → "Auto Center Vitória"
- "Oficinas Mecânicas e Mecânicas Automotivas em Vila Velha" + email "anizioautopecas@gmail.com" → "Anizio Auto Peças"
- "10 Melhores Oficinas Mecânicas em Vila Velha" + email "ativesite@gmail.com" → "Ative Site"
- "Top 5 Clínicas Odontológicas em Vitória" + email "contato@sorrisoperfeito.com.br" → "Sorriso Perfeito"
- "Restaurantes em São Paulo" + email "joao@restaurantedobem.com.br" → "Restaurante do Bem"
- "Escritório de Contabilidade em Vitória-ES" + email "contato@facilittacont.com.br" → "Facilitta Cont"
- "Escritório de Contabilidade em Vitória/ES" + email "contato@w3contabilidade.com.br" → "W3 Contabilidade"
- "Financial Contabilidade Escritório de Contabilidade Vitória/ES" → "Financial Contabilidade"
- "13.122.119/0001-89 Escritório de Contabilidade em Vitória" + email "contato@facilittacont.com.br" → "Facilitta Cont"
- "Salões de Beleza em Vitória" + email "ateliepatriciaalmeidacontato@gmail.com" → "Ateliê Patricia Almeida"
- "Seja bem-vindo!" + email "contato@enzoodonto.com.br" → "Enzo Odonto"
- "12.345.678/0001-90 Restaurante do João" → "Restaurante do João"
- "Clínicas Odontológicas em Vitória" + sem email → ""
- "Home" → ""

━━ CAMPO: email ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Remova artefatos de scraping colados antes do email:
   - Prefixos como "e-mail", "email:", "mailto:", "E-mail:", "Email:" grudados antes do endereço (ex: "e-mailcontato@empresa.com.br" → "contato@empresa.com.br", "mailto:info@site.com" → "info@site.com")
2. Corrija typos óbvios no domínio:
   - gmaiil / gmaill / gmai.com → gmail.com
   - hotmai / hotnail / hotmali → hotmail.com
   - .cmo / .ocm / .con / .coml → .com
   - .corn → .com
   - outloo / outlok → outlook.com
   - yahooo / yaho → yahoo.com.br
   - .con.br / .cpm.br → .com.br
3. Remova espaços dentro do email.
3. Converta para lowercase.
4. Retorne "" para emails claramente inválidos:
   - Sem "@" ou com múltiplos "@"
   - Domínio sem ponto (ex: "joao@empresa")
   - Terminações sem sentido (.c, .br1, .com2)
   - Contém caracteres especiais inválidos fora do padrão RFC
5. Se já estiver correto, retorne o valor original sem alteração.

Preferência de prefixo (quando houver dúvida): contato@ > comunicacao@ > marketing@ > faleconosco@ > comercial@ > vendas@

━━ CAMPO: contact_name ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Aplique Title Case correto para português.
2. Mantenha títulos: "Dr.", "Dra.", "Prof.", "Profa.", "Sr.", "Sra.", "Eng.", "Adv."
3. Se o valor for claramente um nome de empresa ou razão social (não de uma pessoa física), retorne "".
4. Se o campo estiver vazio, retorne "".

━━ CAMPO ESPECIAL: discard ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Retorne discard=true quando o lead NÃO serve para marketing no Brasil:
1. Empresa estrangeira sem operação no Brasil: domínio de email internacional (.com sem .br) de empresa claramente americana/europeia/asiática (ex: rollingstone.com, gettyimages.com, pmc.com, wrightsmedia.com, nytimes.com, bbc.co.uk).
2. Mídia/veículo de imprensa internacional que apareceu por erro de scraping.
3. Email claramente corporativo de empresa multinacional sem relação com o nicho local brasileiro buscado.
ATENÇÃO: NÃO descartar emails pessoais (gmail, hotmail, yahoo) nem empresas brasileiras com .com. Só descartar quando o domínio for de empresa estrangeira reconhecida.
Quando discard=true, preencha discard_reason com uma frase curta em português (ex: "Empresa americana - Rolling Stone EUA").

━━ FORMATO DE SAÍDA ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RETORNE SOMENTE JSON VÁLIDO. Sem markdown, sem texto antes ou depois.
Inclua todos os leads recebidos. Mantenha os IDs originais.

{{"results": [{{"id": 123, "company_name": "Nome Limpo", "email": "email@dominio.com", "contact_name": "Nome Pessoa", "discard": false, "discard_reason": ""}}]}}

━━ LEADS PARA NORMALIZAR ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{_json.dumps(leads_input, ensure_ascii=False)}"""

    try:
        result = _call_llm_normalize(prompt, provider, api_key)
        if result and 'results' in result:
            usage = result.pop('_usage', {})
            return result['results'], None, usage
        return None, 'LLM retornou formato inesperado', {}
    except Exception as e:
        # Auto-fallback to Groq if OpenRouter failed
        if provider == 'openrouter':
            blob = _fetch_secret_blob_from_aws('tools/groq')
            if blob:
                groq_key = _read_secret_key_from_blob(blob, ['GROQ_API_KEY'])
                if groq_key:
                    try:
                        result = _call_llm_normalize(prompt, 'groq', groq_key)
                        if result and 'results' in result:
                            usage = result.pop('_usage', {})
                            return result['results'], None, usage
                    except Exception as e2:
                        return None, f'OpenRouter: {e} | Groq: {e2}', {}
        return None, str(e), {}


@app.route('/api/leads/ai-normalize', methods=['POST'])
@limiter.limit("5/hour")
def ai_normalize_leads():
    """
    AI-powered normalization of company names, emails and contact names.
    Fixes: legal suffixes, hyphens, slogans, email typos, capitalization.
    Processes up to 500 leads in batches of 25 per LLM call.
    """
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    lead_ids = data.get('lead_ids')  # Optional list of specific lead IDs

    with get_db() as conn:
        c = conn.cursor()
        if lead_ids:
            placeholders = ','.join(['%s'] * len(lead_ids))
            c.execute(
                f'SELECT id, company_name, email, contact_name FROM leads '
                f'WHERE id IN ({placeholders}) AND batch_id IN '
                f'(SELECT id FROM batches WHERE user_id = %s)',
                lead_ids + [user_id]
            )
        else:
            c.execute(
                'SELECT id, company_name, email, contact_name FROM leads '
                'WHERE batch_id IN (SELECT id FROM batches WHERE user_id = %s) '
                'ORDER BY id DESC LIMIT 500',
                (user_id,)
            )
        leads_raw = [{'id': r[0], 'company_name': r[1], 'email': r[2], 'contact_name': r[3]}
                     for r in c.fetchall()]

    if not leads_raw:
        return jsonify({'success': True, 'report': {'analyzed': 0, 'normalized': 0, 'name_fixed': 0, 'email_fixed': 0, 'contact_fixed': 0}})

    BATCH_SIZE = 25
    all_results = []
    errors = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    llm_provider_used = None

    for i in range(0, len(leads_raw), BATCH_SIZE):
        batch = leads_raw[i:i + BATCH_SIZE]
        results, err, usage = _ai_normalize_batch(batch)
        if err:
            errors.append(err)
            break
        if results:
            all_results.extend(results)
        if usage:
            total_prompt_tokens     += usage.get('prompt_tokens', 0)
            total_completion_tokens += usage.get('completion_tokens', 0)
            if not llm_provider_used:
                llm_provider_used = usage.get('provider', 'unknown')

    total_tokens = total_prompt_tokens + total_completion_tokens
    # Cost estimate: DeepSeek via OpenRouter ~$0.14/M input + $0.28/M output; Groq free
    if llm_provider_used == 'openrouter':
        cost_usd = (total_prompt_tokens / 1_000_000 * 0.14) + (total_completion_tokens / 1_000_000 * 0.28)
    else:
        cost_usd = 0.0  # Groq free tier

    if not all_results and errors:
        return jsonify({'error': f'Normalização falhou: {errors[0]}'}), 500

    # Apply updates
    orig_map = {l['id']: l for l in leads_raw}
    normalized = name_fixed = email_fixed = contact_fixed = discarded_foreign = 0

    with get_db() as conn:
        c = conn.cursor()
        for r in all_results:
            lead_id = r.get('id')
            if not lead_id:
                continue
            orig = orig_map.get(lead_id, {})

            new_name    = (r.get('company_name') or '').strip() or None
            new_email   = (r.get('email') or '').strip() or None
            new_contact = (r.get('contact_name') or '').strip() or None

            orig_name    = (orig.get('company_name') or '').strip()
            orig_email   = (orig.get('email') or '').strip()
            orig_contact = (orig.get('contact_name') or '').strip()

            should_discard   = r.get('discard', False)
            discard_reason   = (r.get('discard_reason') or '').strip()

            changed = False
            if should_discard:
                # Mark as descartado + add tag 'lead_internacional'
                normalized += 1
                changed = True
                try:
                    c.execute(
                        """UPDATE leads
                           SET crm_status='descartado',
                               tags=array(SELECT DISTINCT unnest(COALESCE(tags, ARRAY[]::text[]) || ARRAY['lead_internacional'])),
                               notes=CASE WHEN notes IS NULL OR notes='' THEN %s ELSE notes || ' | ' || %s END,
                               updated_at=NOW()
                           WHERE id=%s""",
                        (discard_reason or 'Descartado: empresa estrangeira',
                         discard_reason or 'Descartado: empresa estrangeira',
                         lead_id)
                    )
                    discarded_foreign += 1
                except Exception as ue:
                    print(f'[ai-normalize] discard error lead {lead_id}: {ue}')
                continue

            if new_name is not None and new_name != orig_name:
                name_fixed += 1
                changed = True
            if new_email is not None and new_email != orig_email:
                email_fixed += 1
                changed = True
            if new_contact is not None and new_contact != orig_contact:
                contact_fixed += 1
                changed = True

            if changed:
                normalized += 1
                try:
                    c.execute(
                        'UPDATE leads SET company_name=%s, email=%s, contact_name=%s, updated_at=NOW() WHERE id=%s',
                        (
                            new_name    if new_name    is not None else orig.get('company_name'),
                            new_email   if new_email   is not None else orig.get('email'),
                            new_contact if new_contact is not None else orig.get('contact_name'),
                            lead_id,
                        )
                    )
                except Exception as ue:
                    print(f'[ai-normalize] update error lead {lead_id}: {ue}')
        conn.commit()

    return jsonify({
        'success': True,
        'report': {
            'analyzed':          len(leads_raw),
            'normalized':        normalized,
            'name_fixed':        name_fixed,
            'email_fixed':       email_fixed,
            'contact_fixed':     contact_fixed,
            'discarded_foreign': discarded_foreign,
            'batches_processed': (len(leads_raw) + BATCH_SIZE - 1) // BATCH_SIZE,
            'errors':            errors[:3],
            'tokens': {
                'prompt':     total_prompt_tokens,
                'completion': total_completion_tokens,
                'total':      total_tokens,
                'provider':   llm_provider_used or 'unknown',
                'cost_usd':   round(cost_usd, 5),
            },
        }
    })


# ============= CNPJ Enrichment Endpoint (Phase 1) =============

def _run_cnpj_enrichment(user_id, lead_ids=None):
    """
    Background: enriches leads that have CNPJ but haven't been enriched yet.
    Fetches BrasilAPI for each unique CNPJ, updates lead fields.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    c = conn.cursor()
    try:
        if lead_ids:
            placeholders = ','.join(['%s'] * len(lead_ids))
            c.execute(
                f'''SELECT l.id, l.cnpj, l.company_name, l.phone, l.address,
                           l.city, l.state, l.category, l.email, l.extra_data
                    FROM leads l JOIN batches b ON b.id = l.batch_id
                    WHERE l.id IN ({placeholders}) AND b.user_id = %s
                      AND l.cnpj IS NOT NULL AND l.cnpj != ''
                      AND (l.cnpj_enriched IS NULL OR l.cnpj_enriched = FALSE)''',
                lead_ids + [user_id]
            )
        else:
            c.execute(
                '''SELECT l.id, l.cnpj, l.company_name, l.phone, l.address,
                          l.city, l.state, l.category, l.email, l.extra_data
                   FROM leads l JOIN batches b ON b.id = l.batch_id
                   WHERE b.user_id = %s
                     AND l.cnpj IS NOT NULL AND l.cnpj != ''
                     AND (l.cnpj_enriched IS NULL OR l.cnpj_enriched = FALSE)
                   ORDER BY l.id DESC LIMIT 500''',
                (user_id,)
            )
        rows = c.fetchall()
        enriched_count = 0
        phone_added = 0
        category_added = 0
        email_added = 0

        for row in rows:
            lead_id, cnpj, company_name, phone, address, city, state, category, email, extra_data = row
            enrichment = enrich_cnpj_brasilapi(cnpj)
            if not enrichment:
                # Mark as attempted even if empty
                c.execute('UPDATE leads SET cnpj_enriched = TRUE WHERE id = %s', (lead_id,))
                continue

            # Build update fields — only fill empty ones
            update_fields = []
            update_vals = []

            trade_name = enrichment.get('nome_fantasia') or enrichment.get('razao_social')
            if trade_name:
                update_fields.append('cnpj_trade_name = %s')
                update_vals.append(trade_name[:255])
                # Fill company_name if empty
                if not company_name or company_name.strip() == '':
                    update_fields.append('company_name = %s')
                    update_vals.append(trade_name[:255])

            if enrichment.get('situacao'):
                update_fields.append('cnpj_status = %s')
                update_vals.append(enrichment['situacao'][:50])

            if enrichment.get('cnae'):
                update_fields.append('cnpj_cnae = %s')
                update_vals.append(enrichment['cnae'][:255])
                if not category:
                    update_fields.append('category = %s')
                    update_vals.append(enrichment['cnae'][:100])
                    category_added += 1

            if enrichment.get('abertura'):
                update_fields.append('cnpj_abertura = %s')
                update_vals.append(str(enrichment['abertura'])[:20])

            if enrichment.get('porte'):
                update_fields.append('cnpj_porte = %s')
                update_vals.append(enrichment['porte'][:50])

            if enrichment.get('qsa'):
                update_fields.append('cnpj_qsa = %s')
                update_vals.append(', '.join(enrichment['qsa'])[:500])

            if enrichment.get('phone') and not phone:
                update_fields.append('phone = %s')
                update_vals.append(enrichment['phone'][:50])
                phone_added += 1

            if enrichment.get('email_rf') and not email:
                normalized = normalize_email(enrichment['email_rf'])
                if normalized:
                    update_fields.append('email = %s')
                    update_vals.append(normalized)
                    email_added += 1

            if enrichment.get('address') and not address:
                update_fields.append('address = %s')
                update_vals.append(enrichment['address'][:500])

            if enrichment.get('city') and not city:
                update_fields.append('city = %s')
                update_vals.append(enrichment['city'][:100])

            if enrichment.get('state') and not state:
                update_fields.append('state = %s')
                update_vals.append(enrichment['state'][:50])

            # Always mark as enriched
            update_fields.append('cnpj_enriched = TRUE')
            update_fields.append('updated_at = %s')
            update_vals.append(datetime.now())
            update_vals.append(lead_id)

            if len(update_fields) > 2:  # more than just the flags
                c.execute(
                    f"UPDATE leads SET {', '.join(update_fields)} WHERE id = %s",
                    update_vals
                )
                enriched_count += 1

            # BrasilAPI rate limit: ~3 req/s, we do 1 per 0.5s = safe
            time.sleep(0.5)

        print(f"[cnpj_enrich] Done: {enriched_count}/{len(rows)} enriched | phone+{phone_added} | cat+{category_added} | email+{email_added}")
        return {'enriched': enriched_count, 'total': len(rows), 'phone_added': phone_added,
                'category_added': category_added, 'email_added': email_added}
    except Exception as e:
        print(f"[cnpj_enrich] Error: {e}")
        return {'error': str(e)}
    finally:
        conn.close()


@app.route('/api/leads/fuzzy-dedup', methods=['POST'])
@limiter.limit("10/hour")
def api_fuzzy_dedup():
    """Phase 3: Fuzzy-deduplicate leads by company name within a batch.
    Body: { batch_id: int, threshold: int (optional, default 88) }
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    batch_id = data.get('batch_id')
    threshold = int(data.get('threshold', 88))

    if not batch_id:
        return jsonify({'error': 'batch_id required'}), 400

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        dupes = fuzzy_deduplicate_leads(batch_id, conn, threshold=threshold)
        return jsonify({'duplicates_marked': dupes, 'batch_id': batch_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/leads/auto-tag', methods=['POST'])
@limiter.limit("10/hour")
def api_auto_tag():
    """Phase 3: Auto-tag leads in a batch using keyword rules.
    Body: { batch_id: int }
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    batch_id = data.get('batch_id')

    if not batch_id:
        return jsonify({'error': 'batch_id required'}), 400

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        tagged = auto_tag_batch(batch_id, conn)
        return jsonify({'tagged': tagged, 'batch_id': batch_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/leads/enrich-cnpj', methods=['POST'])
@limiter.limit("10/hour")
def enrich_leads_cnpj():
    """
    Trigger CNPJ enrichment via BrasilAPI for leads with CNPJ not yet enriched.
    POST body: { lead_ids: [...] } for specific leads, or {} for all user leads.
    Runs in background thread, returns job estimate immediately.
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    lead_ids = data.get('lead_ids', [])
    background = data.get('background', True)

    if background:
        t = threading.Thread(
            target=_run_cnpj_enrichment,
            args=(user_id, lead_ids if lead_ids else None),
            daemon=True
        )
        t.start()
        return jsonify({
            'status': 'started',
            'message': 'Enriquecimento CNPJ iniciado em background via BrasilAPI',
            'lead_ids': lead_ids or 'todos com CNPJ não enriquecido (max 500)',
        })
    else:
        result = _run_cnpj_enrichment(user_id, lead_ids if lead_ids else None)
        return jsonify({'status': 'done', **result})


# ============= Advanced Scraping Methods =============

# Credenciais para scrapers autenticados
INSTAGRAM_USERNAME = resolve_secret_value(
    'INSTAGRAM_USER',
    secret_ids=['extratordedados/prod'],
    env_keys=['INSTAGRAM_USER', 'INSTAGRAM_USERNAME'],
)
INSTAGRAM_PASSWORD = resolve_secret_value(
    'INSTAGRAM_PASS',
    secret_ids=['extratordedados/prod'],
    env_keys=['INSTAGRAM_PASS', 'INSTAGRAM_PASSWORD'],
)
LINKEDIN_USERNAME = resolve_secret_value(
    'LINKEDIN_USER',
    secret_ids=['extratordedados/prod'],
    env_keys=['LINKEDIN_USER', 'LINKEDIN_USERNAME'],
)
LINKEDIN_PASSWORD = resolve_secret_value(
    'LINKEDIN_PASS',
    secret_ids=['extratordedados/prod'],
    env_keys=['LINKEDIN_PASS', 'LINKEDIN_PASSWORD'],
)

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


# ============================================================
# LOCAL BUSINESS DATA — RapidAPI (Google Maps via API, sem browser)
# Free tier: 500 businesses/month — usa max_results=3 por query
# ============================================================

_rapidapi_key_cache = None
_rapidapi_key_failed = False  # Evita retry quando AWS SM já falhou nesta sessão

def get_rapidapi_key():
    """Busca RapidAPI key com fallback robusto: env -> AWS -> cache local -> DB."""
    global _rapidapi_key_cache, _rapidapi_key_failed
    if _rapidapi_key_cache:
        return _rapidapi_key_cache
    if _rapidapi_key_failed:
        return None
    _rapidapi_key_cache = resolve_secret_value(
        'RAPIDAPI_KEY',
        secret_ids=['tools/rapidapi', 'extratordedados/prod'],
        env_keys=['RAPIDAPI_KEY'],
        db_provider='rapidapi',
    )
    if _rapidapi_key_cache:
        return _rapidapi_key_cache
    _rapidapi_key_failed = True
    print(f"[RAPIDAPI] Todas as fontes de key falharam — provider será desabilitado nesta sessão")
    return None


def search_local_business_data(niche, city, state, max_results=3):
    """
    Busca empresas locais via Local Business Data (RapidAPI).
    Free tier: 500 businesses/month — use max_results=3 para conservar quota.
    Retorna lista de leads compatível com schema do batch.
    Lança exceção em caso de falha (para _massive_retry capturar e tentar novamente).
    """
    api_key = get_rapidapi_key()
    if not api_key:
        raise ConfigError("[LOCAL_BIZ] RapidAPI key não disponível — verifique AWS SM tools/rapidapi ou env RAPIDAPI_KEY")

    query = f"{niche} {city} {state} Brasil"
    url = "https://local-business-data.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "local-business-data.p.rapidapi.com"
    }
    params = {
        "query": query,
        "limit": max_results,
        "language": "pt",
        "country": "br",
        "extract_emails_and_contacts": "true"
    }

    resp = http_requests.get(url, headers=headers, params=params, timeout=30)

    if resp.status_code == 429:
        raise RuntimeError("[LOCAL_BIZ] Quota RapidAPI excedida (429) — aguardando próxima janela")
    if resp.status_code == 403:
        raise RuntimeError("[LOCAL_BIZ] Não autorizado (403) — verifique assinatura no RapidAPI")
    resp.raise_for_status()

    data = resp.json()
    if data.get('status') != 'OK':
        msg = (data.get('error') or {}).get('message', 'resposta inesperada')
        raise RuntimeError(f"[LOCAL_BIZ] API retornou erro: {msg}")

    leads = []
    for item in data.get('data', []):
        contacts  = item.get('emails_and_contacts') or {}
        emails    = contacts.get('emails') or []
        website   = item.get('website') or ''

        # Se o website é do Instagram, mover para campo instagram
        instagram = contacts.get('instagram')
        if not instagram and 'instagram.com' in website.lower():
            instagram = website
            website   = ''

        lead = {
            'company_name': (item.get('name') or '').strip(),
            'phone':        item.get('phone_number') or '',
            'website':      website,
            'address':      item.get('address') or '',
            'city':         item.get('city') or city,
            'state':        item.get('state') or state,
            'category':     item.get('type') or niche,
            'source':       'local_business_data',
            'source_url':   item.get('place_link') or '',
            'instagram':    instagram,
            'facebook':     contacts.get('facebook'),
            'twitter':      contacts.get('twitter'),
            'linkedin':     contacts.get('linkedin'),
            'youtube':      contacts.get('youtube'),
            'extra_data':   {
                'rating':   item.get('rating'),
                'reviews':  item.get('review_count'),
                'verified': item.get('verified'),
                'google_id': item.get('google_id'),
                'subtypes': item.get('subtypes') or [],
                'district': item.get('district'),
                'zipcode':  item.get('zipcode'),
            },
        }
        if emails:
            lead['email'] = emails[0]

        if lead['company_name']:
            leads.append(lead)

    print(f"[LOCAL_BIZ] '{query}': {len(leads)} leads retornados")
    return leads


# ============================================================
# NEW METHODS — Google Email Harvest, Website Crawler,
#   OpenCNPJ, Serper.dev, Apify Maps
# ============================================================

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

# Domínios de email inválidos para scraping (noise)
_NOISE_EMAIL_DOMAINS = {
    'example.com', 'sentry.io', 'wixpress.com', 'email.com', 'domain.com',
    'yoursite.com', 'yourdomain.com', 'test.com', 'sample.com',
    'wordpress.org', 'w3.org', 'schema.org', 'json-ld.org',
    'googleusercontent.com', 'googleapis.com', 'gstatic.com',
}


def _extract_emails_from_html(html_text):
    """Extrai emails de um HTML, removendo noise e duplicatas."""
    raw = set(EMAIL_RE.findall(html_text.lower()))
    valid = []
    for em in raw:
        domain = em.split('@')[1] if '@' in em else ''
        if domain in _NOISE_EMAIL_DOMAINS:
            continue
        if domain.endswith(('.png', '.jpg', '.gif', '.svg', '.css', '.js')):
            continue
        if len(em) > 100 or len(em) < 6:
            continue
        valid.append(em)
    return list(set(valid))


def _crawl_single_url_for_emails(url, timeout=12):
    """Faz GET em uma URL e retorna lista de emails encontrados."""
    try:
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        resp = http_requests.get(url, timeout=timeout, verify=False, headers=headers,
                                 allow_redirects=True)
        if resp.status_code != 200:
            return []
        return _extract_emails_from_html(resp.text)
    except Exception:
        return []


def _crawl_site_deep(base_url, max_pages=5):
    """Crawl profundo: homepage + páginas de contato/sobre para extrair emails."""
    from urllib.parse import urljoin, urlparse
    found_emails = set()
    visited = set()
    # Priorizar páginas de contato
    contact_paths = [
        '', '/contato', '/contact', '/sobre', '/about', '/about-us',
        '/fale-conosco', '/quem-somos', '/contatos', '/contact-us',
    ]
    parsed = urlparse(base_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    pages_crawled = 0
    for path in contact_paths:
        if pages_crawled >= max_pages:
            break
        url = urljoin(base, path)
        if url in visited:
            continue
        visited.add(url)
        pages_crawled += 1
        emails = _crawl_single_url_for_emails(url)
        found_emails.update(emails)
        time.sleep(random.uniform(1, 2))

    return list(found_emails)


# ---- METHOD 1: Google Email Harvest (Playwright) ----
def google_email_harvest(niche, city, state, max_results=20):
    """
    Playwright: busca no Google com dorks para encontrar emails.
    1. Busca: "@gmail.com" OR "@hotmail.com" [niche] [city] [state]
    2. Extrai emails dos snippets do SERP (sem clicar)
    3. Visita os top resultados e extrai emails de cada site
    Retorna lista de leads compatíveis com schema do batch.
    """
    from playwright.sync_api import sync_playwright as _sp

    dork_queries = [
        f'"@gmail.com" OR "@hotmail.com" OR "@outlook.com" {niche} {city} {state}',
        f'{niche} {city} {state} email contato site:.com.br',
        f'{niche} {city} email telefone',
    ]

    all_leads = []
    seen_emails = set()

    with _sp() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1280, 'height': 800}
        )
        page = ctx.new_page()

        for qi, dork in enumerate(dork_queries):
            if len(all_leads) >= max_results:
                break
            try:
                search_url = f'https://www.google.com/search?q={dork}&num=20&hl=pt-BR'
                page.goto(search_url, timeout=20000, wait_until='domcontentloaded')
                time.sleep(random.uniform(2, 4))

                # Extrair emails dos snippets do SERP
                serp_html = page.content()
                serp_emails = _extract_emails_from_html(serp_html)
                for em in serp_emails:
                    if em not in seen_emails and len(all_leads) < max_results:
                        seen_emails.add(em)
                        all_leads.append({
                            'email': em,
                            'company_name': '',
                            'city': city,
                            'state': state,
                            'category': niche,
                            'source': 'google_email_harvest',
                            'source_url': 'google.com/search',
                        })

                # Extrair URLs dos resultados e visitar cada uma
                links = page.eval_on_selector_all(
                    'div#search a[href^="http"]',
                    '(els) => els.map(e => e.href).filter(h => !h.includes("google.") && !h.includes("youtube.") && !h.includes("facebook.") && !h.includes("instagram."))'
                )

                for link in links[:15]:
                    if len(all_leads) >= max_results:
                        break
                    try:
                        if not is_valid_result_url(link):
                            continue
                        site_emails = _crawl_single_url_for_emails(link)
                        for em in site_emails:
                            if em not in seen_emails:
                                seen_emails.add(em)
                                all_leads.append({
                                    'email': em,
                                    'company_name': '',
                                    'website': link,
                                    'city': city,
                                    'state': state,
                                    'category': niche,
                                    'source': 'google_email_harvest',
                                    'source_url': link,
                                })
                        time.sleep(random.uniform(1, 3))
                    except Exception:
                        continue

                # Delay entre queries para evitar CAPTCHA
                if qi < len(dork_queries) - 1:
                    time.sleep(random.uniform(8, 15))

            except Exception as e:
                print(f"[GOOGLE_HARVEST] Erro na query {qi+1}: {e}")
                continue

        browser.close()

    print(f"[GOOGLE_HARVEST] '{niche} {city}': {len(all_leads)} leads")
    return all_leads


# ---- METHOD 2: Website Email Crawler (Deep Crawl) ----
def search_and_crawl_for_emails(niche, city, state, max_sites=15):
    """
    Busca DuckDuckGo por [niche] [city] contato, visita cada site
    e faz deep crawl em /contato, /sobre, /about para extrair emails.
    Retorna lista de leads.
    """
    query = f"{niche} {city} {state} contato email"
    results = search_duckduckgo(query, max_pages=2) or []

    all_leads = []
    seen_emails = set()
    sites_crawled = 0

    for result in results:
        if sites_crawled >= max_sites:
            break
        url = result.get('url', '')
        if not url or not is_valid_result_url(url):
            continue

        sites_crawled += 1
        emails = _crawl_site_deep(url, max_pages=4)
        for em in emails:
            if em not in seen_emails:
                seen_emails.add(em)
                all_leads.append({
                    'email': em,
                    'company_name': result.get('title', ''),
                    'website': url,
                    'city': city,
                    'state': state,
                    'category': niche,
                    'source': 'website_email_crawler',
                    'source_url': url,
                })
        time.sleep(random.uniform(2, 5))

    print(f"[WEB_CRAWLER] '{niche} {city}': {len(all_leads)} leads de {sites_crawled} sites")
    return all_leads


# ---- METHOD 3: OpenCNPJ Search ----
_opencnpj_cache = {}

def search_opencnpj_by_directory(niche, city, state, max_results=20):
    """
    Estratégia: busca empresas nos diretórios CNPJ (cnpj.biz, listacnae).
    Depois enriquece cada CNPJ via OpenCNPJ API para pegar email/telefone registrado.
    OpenCNPJ é 100% grátis (50 req/seg).
    """
    leads = []
    seen_cnpjs = set()

    # Fase 1: Coletar CNPJs via busca na web
    query = f"cnpj {niche} {city} {state} site:cnpj.biz OR site:listacnae.com.br"
    results = search_duckduckgo(query, max_pages=1) or []

    cnpj_pattern = re.compile(r'\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}')
    collected_cnpjs = []

    for result in results[:10]:
        url = result.get('url', '')
        if not url:
            continue
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            resp = http_requests.get(url, timeout=10, verify=False, headers=headers)
            if resp.status_code == 200:
                found = cnpj_pattern.findall(resp.text)
                for cnpj_raw in found:
                    cnpj_clean = re.sub(r'[.\-/]', '', cnpj_raw)
                    if len(cnpj_clean) == 14 and cnpj_clean not in seen_cnpjs:
                        seen_cnpjs.add(cnpj_clean)
                        collected_cnpjs.append(cnpj_clean)
            time.sleep(random.uniform(1, 2))
        except Exception:
            continue

    print(f"[OPENCNPJ] Coletados {len(collected_cnpjs)} CNPJs para '{niche} {city}'")

    # Fase 2: Enriquecer cada CNPJ via OpenCNPJ API
    for cnpj in collected_cnpjs[:max_results]:
        if cnpj in _opencnpj_cache:
            data = _opencnpj_cache[cnpj]
        else:
            try:
                resp = http_requests.get(
                    f'https://publica.cnpj.ws/cnpj/{cnpj}',
                    timeout=10,
                    headers={'Accept': 'application/json'}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    _opencnpj_cache[cnpj] = data
                elif resp.status_code == 429:
                    print(f"[OPENCNPJ] Rate limited — aguardando 5s")
                    time.sleep(5)
                    continue
                else:
                    continue
            except Exception:
                continue

        email = (data.get('estabelecimento') or {}).get('email') or ''
        phone1 = (data.get('estabelecimento') or {}).get('telefone1') or ''
        phone2 = (data.get('estabelecimento') or {}).get('telefone2') or ''
        nome = data.get('razao_social') or (data.get('estabelecimento') or {}).get('nome_fantasia') or ''
        est = data.get('estabelecimento') or {}
        cidade = est.get('cidade', {}).get('nome', city) if isinstance(est.get('cidade'), dict) else city
        uf = est.get('estado', {}).get('sigla', state) if isinstance(est.get('estado'), dict) else state
        website = est.get('dominio') or ''

        # Montar telefone
        ddd1 = (data.get('estabelecimento') or {}).get('ddd1') or ''
        phone = f"({ddd1}){phone1}" if ddd1 and phone1 else phone1 or phone2

        if email or phone:
            leads.append({
                'company_name': nome,
                'email': email.lower() if email else '',
                'phone': phone,
                'website': website,
                'address': est.get('logradouro', ''),
                'city': cidade,
                'state': uf,
                'category': niche,
                'source': 'cnpj_open',
                'source_url': f'https://publica.cnpj.ws/cnpj/{cnpj}',
                'extra_data': {'cnpj': cnpj},
            })
        time.sleep(random.uniform(0.3, 0.8))

    print(f"[OPENCNPJ] '{niche} {city}': {len(leads)} leads com email/telefone")
    return leads


# ---- METHOD 4: Serper.dev Google Search API ----
_serper_api_key_cache = None
_serper_key_failed = False

def _get_serper_key():
    """Busca Serper.dev API key com fallback robusto: env -> AWS -> cache local -> DB."""
    global _serper_api_key_cache, _serper_key_failed
    if _serper_api_key_cache:
        return _serper_api_key_cache
    if _serper_key_failed:
        return None
    _serper_api_key_cache = resolve_secret_value(
        'SERPER_API_KEY',
        secret_ids=['tools/serper', 'extratordedados/prod'],
        env_keys=['SERPER_API_KEY'],
        db_provider='serper',
    )
    if _serper_api_key_cache:
        return _serper_api_key_cache
    _serper_key_failed = True
    return None


def serper_email_search(niche, city, state, max_results=20):
    """
    Serper.dev: 2500 buscas grátis/mês. Retorna resultados estruturados do Google.
    Busca por emails nos snippets e visita os top sites.
    """
    api_key = _get_serper_key()
    if not api_key:
        raise ConfigError("[SERPER] API key não disponível — cadastre em serper.dev (grátis) e salve em AWS SM tools/serper")

    queries = [
        f'{niche} {city} {state} email contato',
        f'"@" {niche} {city} {state}',
    ]

    all_leads = []
    seen_emails = set()

    for query in queries:
        if len(all_leads) >= max_results:
            break
        try:
            resp = http_requests.post(
                'https://google.serper.dev/search',
                json={'q': query, 'gl': 'br', 'hl': 'pt-br', 'num': 20},
                headers={'X-API-KEY': api_key, 'Content-Type': 'application/json'},
                timeout=15,
            )
            if resp.status_code == 429:
                raise RuntimeError("[SERPER] Quota mensal esgotada (429)")
            resp.raise_for_status()
            data = resp.json()

            # Extrair emails dos snippets
            for item in data.get('organic', []):
                snippet = (item.get('snippet') or '') + ' ' + (item.get('title') or '')
                snippet_emails = _extract_emails_from_html(snippet)
                for em in snippet_emails:
                    if em not in seen_emails and len(all_leads) < max_results:
                        seen_emails.add(em)
                        all_leads.append({
                            'email': em,
                            'company_name': item.get('title', ''),
                            'website': item.get('link', ''),
                            'city': city,
                            'state': state,
                            'category': niche,
                            'source': 'serper_google',
                            'source_url': item.get('link', ''),
                        })

            # Visitar URLs sem email no snippet
            for item in data.get('organic', []):
                if len(all_leads) >= max_results:
                    break
                link = item.get('link', '')
                if not link or not is_valid_result_url(link):
                    continue
                site_emails = _crawl_single_url_for_emails(link)
                for em in site_emails:
                    if em not in seen_emails:
                        seen_emails.add(em)
                        all_leads.append({
                            'email': em,
                            'company_name': item.get('title', ''),
                            'website': link,
                            'city': city,
                            'state': state,
                            'category': niche,
                            'source': 'serper_google',
                            'source_url': link,
                        })
                time.sleep(random.uniform(0.5, 1.5))

        except Exception as e:
            if '429' in str(e) or 'quota' in str(e).lower():
                raise
            print(f"[SERPER] Erro na query: {e}")
            continue

    print(f"[SERPER] '{niche} {city}': {len(all_leads)} leads")
    return all_leads


# ---- METHOD 5: Apify Google Maps with Emails ----
def apify_google_maps_search(niche, city, state, max_results=20):
    """
    Apify Google Maps Scraper: roda o actor compass/crawler-google-places.
    Free tier: $5/mês de crédito (~1250 businesses/mês).
    Extrai nome, telefone, website, email, endereço, rating.
    """
    apify_token = resolve_secret_value(
        'APIFY_TOKEN',
        secret_ids=['extratordedados/prod', 'tools/apify'],
        env_keys=['APIFY_TOKEN', 'APIFY_API_KEY'],
        db_provider='apify',
    )
    if not apify_token:
        raise ConfigError("[APIFY] Token não disponível — configure em env, cache local ou AWS SM")

    query = f"{niche} em {city} {state}"
    run_input = {
        "searchStringsArray": [query],
        "maxCrawledPlacesPerSearch": max_results,
        "language": "pt",
        "countryCode": "br",
        "includeWebResults": False,
        "exportPlaceUrls": False,
        "deeperCityScrape": False,
        "scrapeContacts": True,
    }

    # Iniciar actor run (sincrono — espera resultado)
    actor_id = 'lukaskrivka~google-maps-with-contact-details'
    start_url = f'https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items'
    resp = http_requests.post(
        start_url,
        params={'token': apify_token, 'timeout': 120},
        json=run_input,
        timeout=150,
    )

    if resp.status_code == 402:
        raise RuntimeError("[APIFY] Créditos esgotados (402)")
    if resp.status_code == 404:
        raise ConfigError("[APIFY] Actor não encontrado — verifique ID")
    resp.raise_for_status()

    items = resp.json() if isinstance(resp.json(), list) else []
    leads = []
    for item in items:
        emails = []
        # Tentar extrair email do campo contact
        if item.get('email'):
            emails.append(item['email'])
        if item.get('emails'):
            emails.extend(item['emails'] if isinstance(item['emails'], list) else [])

        lead = {
            'company_name': (item.get('title') or item.get('name') or '').strip(),
            'phone': item.get('phone') or '',
            'website': item.get('website') or item.get('url') or '',
            'email': emails[0] if emails else '',
            'address': item.get('address') or item.get('street') or '',
            'city': item.get('city') or city,
            'state': state,
            'category': item.get('categoryName') or niche,
            'source': 'apify_maps',
            'source_url': item.get('url') or item.get('placeUrl') or '',
            'extra_data': {
                'rating': item.get('totalScore') or item.get('rating'),
                'reviews': item.get('reviewsCount'),
                'google_id': item.get('placeId'),
            },
        }

        # Se tem website mas não tem email, crawl rápido
        if lead['website'] and not lead['email']:
            site_emails = _crawl_single_url_for_emails(lead['website'])
            if site_emails:
                lead['email'] = site_emails[0]

        if lead['company_name']:
            leads.append(lead)

    print(f"[APIFY_MAPS] '{query}': {len(leads)} leads ({sum(1 for l in leads if l.get('email'))} com email)")
    return leads


# ---- METHOD 6: ReceitaWS CNPJ Search ----
def search_receita_ws(niche, city, state, max_results=10):
    """
    ReceitaWS: busca empresas ativas via API pública da Receita Federal.
    Endpoint search: https://receitaws.com.br/v1/search (3 req/min free)
    Enriquece cada CNPJ via publica.cnpj.ws para pegar email/telefone oficial.
    """
    leads = []
    seen_cnpjs = set()

    # Slugify state para ReceitaWS (espera sigla de 2 letras)
    state_uf = state.upper()[:2] if state else ''
    city_clean = city.strip()

    queries = [
        {'query': niche, 'uf': state_uf, 'municipio': city_clean},
    ]

    for q_params in queries:
        if len(leads) >= max_results:
            break
        try:
            resp = http_requests.get(
                'https://receitaws.com.br/v1/search',
                params={**q_params, 'status': 'A'},
                timeout=15,
                headers={'Accept': 'application/json'},
            )
            if resp.status_code == 429:
                print(f"[RECEITA_WS] Rate limit — aguardando 20s")
                time.sleep(20)
                continue
            if resp.status_code != 200:
                continue
            data = resp.json()
            cnpjs_found = []
            # Resposta pode ser lista de CNPJs ou dict com 'activities'
            if isinstance(data, list):
                for item in data:
                    cnpj = item.get('cnpj') or item.get('CNPJ') or ''
                    cnpj_clean = re.sub(r'[.\-/]', '', cnpj)
                    if len(cnpj_clean) == 14 and cnpj_clean not in seen_cnpjs:
                        seen_cnpjs.add(cnpj_clean)
                        cnpjs_found.append(cnpj_clean)
            elif isinstance(data, dict):
                for item in data.get('activities', []) + data.get('companies', []):
                    cnpj = item.get('cnpj') or item.get('CNPJ') or ''
                    cnpj_clean = re.sub(r'[.\-/]', '', str(cnpj))
                    if len(cnpj_clean) == 14 and cnpj_clean not in seen_cnpjs:
                        seen_cnpjs.add(cnpj_clean)
                        cnpjs_found.append(cnpj_clean)

            # Enriquecer cada CNPJ via publica.cnpj.ws
            for cnpj in cnpjs_found[:max_results]:
                if len(leads) >= max_results:
                    break
                try:
                    enrich = http_requests.get(
                        f'https://publica.cnpj.ws/cnpj/{cnpj}',
                        timeout=10,
                        headers={'Accept': 'application/json'},
                    )
                    if enrich.status_code == 429:
                        time.sleep(5)
                        continue
                    if enrich.status_code != 200:
                        continue
                    d = enrich.json()
                    est = d.get('estabelecimento') or {}
                    email = est.get('email') or ''
                    ddd1 = est.get('ddd1') or ''
                    tel1 = est.get('telefone1') or ''
                    phone = f"({ddd1}){tel1}" if ddd1 and tel1 else tel1
                    nome = d.get('razao_social') or est.get('nome_fantasia') or ''
                    cidade = est.get('cidade', {}).get('nome', city) if isinstance(est.get('cidade'), dict) else city
                    uf = est.get('estado', {}).get('sigla', state) if isinstance(est.get('estado'), dict) else state
                    website = est.get('dominio') or ''
                    if email or phone:
                        leads.append({
                            'company_name': nome,
                            'email': email.lower() if email else '',
                            'phone': phone,
                            'website': website,
                            'address': est.get('logradouro', ''),
                            'city': cidade,
                            'state': uf,
                            'category': niche,
                            'source': 'receita_ws',
                            'source_url': f'https://publica.cnpj.ws/cnpj/{cnpj}',
                            'extra_data': {'cnpj': cnpj},
                        })
                    time.sleep(random.uniform(0.5, 1.0))
                except Exception as e:
                    print(f"[RECEITA_WS] Enrich CNPJ {cnpj} erro: {e}")
                    continue

            # Rate limit: 3 req/min no search endpoint
            time.sleep(20)
        except Exception as e:
            print(f"[RECEITA_WS] Erro na busca: {e}")
            continue

    print(f"[RECEITA_WS] '{niche} {city}': {len(leads)} leads")
    return leads


# ---- METHOD 7: OLX Service Ads Scraper ----
_OLX_STATE_SLUGS = {
    'AC': 'acre', 'AL': 'alagoas', 'AP': 'amapa', 'AM': 'amazonas',
    'BA': 'bahia', 'CE': 'ceara', 'DF': 'distrito-federal', 'ES': 'espirito-santo',
    'GO': 'goias', 'MA': 'maranhao', 'MT': 'mato-grosso', 'MS': 'mato-grosso-do-sul',
    'MG': 'minas-gerais', 'PA': 'para', 'PB': 'paraiba', 'PR': 'parana',
    'PE': 'pernambuco', 'PI': 'piaui', 'RJ': 'rio-de-janeiro', 'RN': 'rio-grande-do-norte',
    'RS': 'rio-grande-do-sul', 'RO': 'rondonia', 'RR': 'roraima', 'SC': 'santa-catarina',
    'SP': 'sao-paulo', 'SE': 'sergipe', 'TO': 'tocantins',
}

def scrape_olx_ads(niche, city, state, max_results=20):
    """
    OLX Service Ads: scrapa anúncios de serviços no OLX.
    Extrai números WhatsApp (wa.me links) e telefone de anúncios.
    Usa requests + BeautifulSoup (sem Playwright).
    """
    state_uf = state.upper()[:2] if state else ''
    state_slug = _OLX_STATE_SLUGS.get(state_uf, state_uf.lower())
    city_q = city.strip().lower().replace(' ', '+')
    niche_q = niche.strip().lower().replace(' ', '+')

    url = f"https://www.olx.com.br/servicos/estado-{state_slug}?q={niche_q}+{city_q}"
    leads = []
    wa_pattern = re.compile(r'wa\.me/(\d+)', re.IGNORECASE)
    phone_pattern = re.compile(r'(?:\+55\s?)?(?:\(?\d{2}\)?\s?)(?:9\s?)?\d{4}[-\s]?\d{4}')

    try:
        headers = {'User-Agent': random.choice(USER_AGENTS), 'Accept-Language': 'pt-BR,pt;q=0.9'}
        resp = http_requests.get(url, headers=headers, timeout=15, verify=False)
        if resp.status_code != 200:
            print(f"[OLX_ADS] HTTP {resp.status_code} para {url}")
            return leads

        soup = BeautifulSoup(resp.text, 'lxml')

        # Links de anúncios individuais
        ad_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/servicos/' in href and 'olx.com.br' in href and href not in ad_links:
                ad_links.append(href)
            if len(ad_links) >= max_results:
                break

        print(f"[OLX_ADS] Encontrados {len(ad_links)} anúncios para '{niche} {city}'")

        seen_wa = set()
        for ad_url in ad_links[:max_results]:
            try:
                ad_resp = http_requests.get(ad_url, headers=headers, timeout=10, verify=False)
                if ad_resp.status_code != 200:
                    continue

                page_text = ad_resp.text
                ad_soup = BeautifulSoup(page_text, 'lxml')

                # Extrair título/empresa
                title_el = ad_soup.find('h1') or ad_soup.find('title')
                company = title_el.get_text(strip=True)[:100] if title_el else ''

                # Buscar wa.me links
                wa_numbers = wa_pattern.findall(page_text)
                phones = phone_pattern.findall(page_text)

                wa_formatted = None
                if wa_numbers:
                    raw = wa_numbers[0]
                    # Garantir formato 55 + número
                    if not raw.startswith('55'):
                        raw = '55' + raw
                    wa_formatted = f"https://wa.me/{raw}"
                    phone_from_wa = raw[2:] if raw.startswith('55') else raw
                else:
                    phone_from_wa = None

                phone_clean = phones[0] if phones else phone_from_wa

                if (wa_formatted or phone_clean) and wa_formatted not in seen_wa:
                    seen_wa.add(wa_formatted)
                    leads.append({
                        'company_name': company,
                        'phone': phone_clean,
                        'whatsapp': wa_formatted,
                        'city': city,
                        'state': state,
                        'category': niche,
                        'source': 'olx_ads',
                        'source_url': ad_url,
                    })

                time.sleep(random.uniform(2, 4))
            except Exception as e:
                print(f"[OLX_ADS] Erro ao processar anúncio: {e}")
                continue

    except Exception as e:
        print(f"[OLX_ADS] Erro geral: {e}")

    print(f"[OLX_ADS] '{niche} {city}': {len(leads)} leads com WhatsApp/telefone")
    return leads


# ---- METHOD 8: WhatsApp Dorks via Serper ----
def search_whatsapp_dorks(niche, city, state, max_results=15):
    """
    WhatsApp Discovery via Serper dorks.
    Busca por links wa.me/55 relacionados ao nicho e cidade.
    Extrai números WhatsApp formatados.
    """
    api_key = _get_serper_key()
    if not api_key:
        raise ConfigError("[WA_DORKS] Serper API key não disponível")

    dorks = [
        f'"wa.me/55" "{niche}" "{city}"',
        f'site:wa.me "55" {niche} {city}',
        f'whatsapp {niche} {city} {state} contato',
    ]

    wa_pattern = re.compile(r'wa\.me/(\d+)', re.IGNORECASE)
    leads = []
    seen_wa = set()

    for dork in dorks:
        if len(leads) >= max_results:
            break
        try:
            resp = http_requests.post(
                'https://google.serper.dev/search',
                json={'q': dork, 'gl': 'br', 'hl': 'pt-br', 'num': 20},
                headers={'X-API-KEY': api_key, 'Content-Type': 'application/json'},
                timeout=15,
            )
            if resp.status_code == 429:
                raise RuntimeError("[WA_DORKS] Quota Serper esgotada (429)")
            resp.raise_for_status()
            data = resp.json()

            for item in data.get('organic', []):
                # Extrair wa.me do snippet + link
                text = (item.get('snippet') or '') + ' ' + (item.get('link') or '')
                wa_numbers = wa_pattern.findall(text)
                for raw in wa_numbers:
                    if not raw.startswith('55'):
                        raw = '55' + raw
                    wa_url = f"https://wa.me/{raw}"
                    if wa_url not in seen_wa and len(leads) < max_results:
                        seen_wa.add(wa_url)
                        leads.append({
                            'company_name': item.get('title', ''),
                            'whatsapp': wa_url,
                            'phone': raw[2:] if raw.startswith('55') else raw,
                            'website': item.get('link', ''),
                            'city': city,
                            'state': state,
                            'category': niche,
                            'source': 'whatsapp_dorks',
                            'source_url': item.get('link', ''),
                        })

            # Crawl top URLs que podem ter wa.me links embutidos
            for item in data.get('organic', [])[:5]:
                if len(leads) >= max_results:
                    break
                link = item.get('link', '')
                if not link or not is_valid_result_url(link):
                    continue
                try:
                    headers = {'User-Agent': random.choice(USER_AGENTS)}
                    page_resp = http_requests.get(link, headers=headers, timeout=8, verify=False)
                    if page_resp.status_code == 200:
                        found = wa_pattern.findall(page_resp.text)
                        for raw in found:
                            if not raw.startswith('55'):
                                raw = '55' + raw
                            wa_url = f"https://wa.me/{raw}"
                            if wa_url not in seen_wa and len(leads) < max_results:
                                seen_wa.add(wa_url)
                                leads.append({
                                    'company_name': item.get('title', ''),
                                    'whatsapp': wa_url,
                                    'phone': raw[2:] if raw.startswith('55') else raw,
                                    'website': link,
                                    'city': city,
                                    'state': state,
                                    'category': niche,
                                    'source': 'whatsapp_dorks',
                                    'source_url': link,
                                })
                except Exception:
                    pass
                time.sleep(random.uniform(0.5, 1.5))

            time.sleep(random.uniform(1, 2))
        except Exception as e:
            if '429' in str(e) or 'quota' in str(e).lower():
                raise
            print(f"[WA_DORKS] Erro no dork: {e}")
            continue

    print(f"[WA_DORKS] '{niche} {city}': {len(leads)} leads com WhatsApp")
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

        # AUTO-SANITIZE + SYNC: sanitiza leads ao completar, depois sincroniza com CRM
        threading.Thread(target=auto_sanitize_background, args=(batch_id,), daemon=True).start()

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


# ============= Lead Scoring (Semana 2) =============

@app.route('/api/leads/enrich-score', methods=['POST'])
@limiter.limit("5/hour")
def enrich_lead_score():
    """Recalculate lead_score for all leads of the current user (admin) or a batch.
    Admin: recalculates all leads in the system.
    Client: recalculates their own leads.
    """
    try:
        token = get_auth_header()
        user_id = verify_token(token)
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401

        data = request.json or {}
        lead_ids = data.get('lead_ids')  # optional: limit to specific IDs

        with get_db() as conn:
            c = conn.cursor()

            # Check if admin
            c.execute('SELECT is_admin FROM users WHERE id = %s', (user_id,))
            row = c.fetchone()
            is_admin = row and row[0]

            # Build query to fetch leads to score
            if lead_ids:
                placeholders = ','.join(['%s'] * len(lead_ids))
                if is_admin:
                    c.execute(f'''SELECT l.id, l.company_name, l.email, l.phone, l.website,
                                         l.city, l.state, l.category, l.contact_name, l.whatsapp
                                  FROM leads l WHERE l.id IN ({placeholders})''', lead_ids)
                else:
                    c.execute(f'''SELECT l.id, l.company_name, l.email, l.phone, l.website,
                                         l.city, l.state, l.category, l.contact_name, l.whatsapp
                                  FROM leads l JOIN batches b ON l.batch_id = b.id
                                  WHERE b.user_id = %s AND l.id IN ({placeholders})''',
                              [user_id] + list(lead_ids))
            elif is_admin:
                c.execute('''SELECT l.id, l.company_name, l.email, l.phone, l.website,
                                    l.city, l.state, l.category, l.contact_name, l.whatsapp
                             FROM leads l''')
            else:
                c.execute('''SELECT l.id, l.company_name, l.email, l.phone, l.website,
                                    l.city, l.state, l.category, l.contact_name, l.whatsapp
                             FROM leads l JOIN batches b ON l.batch_id = b.id
                             WHERE b.user_id = %s''', (user_id,))

            rows = c.fetchall()
            updated = 0
            for row in rows:
                lead_dict = {
                    'id': row[0], 'company_name': row[1], 'email': row[2],
                    'phone': row[3], 'website': row[4], 'city': row[5],
                    'state': row[6], 'category': row[7], 'contact_name': row[8],
                    'whatsapp': row[9]
                }
                score = _calculate_lead_score(lead_dict)
                c.execute('UPDATE leads SET lead_score = %s WHERE id = %s', (score, row[0]))
                updated += 1

            conn.commit()
            print(f'[INFO] enrich_lead_score: updated {updated} leads (user_id={user_id}, is_admin={is_admin})')
            return jsonify({'updated': updated, 'message': f'{updated} leads com score atualizado'}), 200
    except Exception as e:
        print(f'[ERROR] /api/leads/enrich-score: {e}')
        return jsonify({'error': str(e)}), 500


# ============= Saved Filters (Semana 2) =============

SAVED_FILTERS_LIMIT = {'free': 0, 'pro': 5, 'enterprise': 20}

@app.route('/api/leads/saved-filters', methods=['GET'])
def list_saved_filters():
    """List saved filters for the current user"""
    try:
        token = get_auth_header()
        user_id = verify_token(token)
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401

        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT id, name, filters, created_at FROM saved_filters WHERE user_id = %s ORDER BY created_at DESC',
                (user_id,)
            )
            filters = []
            for row in c.fetchall():
                filters.append({
                    'id': row[0],
                    'name': row[1],
                    'filters': row[2],
                    'created_at': row[3].isoformat() if row[3] else None
                })
            return jsonify({'filters': filters}), 200
    except Exception as e:
        print(f'[ERROR] GET /api/leads/saved-filters: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/leads/saved-filters', methods=['POST'])
def create_saved_filter():
    """Save a filter combination for the current user"""
    try:
        token = get_auth_header()
        user_id = verify_token(token)
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401

        data = request.json or {}
        name = (data.get('name') or '').strip()
        filters = data.get('filters')

        if not name:
            return jsonify({'error': 'Filter name is required'}), 400
        if not filters:
            return jsonify({'error': 'Filters payload is required'}), 400
        if len(name) > 100:
            return jsonify({'error': 'Filter name too long (max 100 chars)'}), 400

        with get_db() as conn:
            c = conn.cursor()

            # Check plan limit
            plan = _get_user_plan(user_id, conn)
            max_filters = SAVED_FILTERS_LIMIT.get(plan, 0)
            if max_filters == 0:
                return jsonify({'error': 'Seu plano não permite filtros salvos. Faça upgrade para Pro ou Enterprise.', 'upgrade_required': True}), 403

            c.execute('SELECT COUNT(*) FROM saved_filters WHERE user_id = %s', (user_id,))
            count = c.fetchone()[0]
            if count >= max_filters:
                return jsonify({'error': f'Limite de {max_filters} filtros salvos atingido para o plano {plan.title()}. Remova um filtro ou faça upgrade.', 'limit_reached': True}), 403

            # Upsert by name
            c.execute('''
                INSERT INTO saved_filters (user_id, name, filters)
                VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (user_id, name)
                DO UPDATE SET filters = EXCLUDED.filters
                RETURNING id, name, filters, created_at
            ''', (user_id, name, json.dumps(filters)))
            row = c.fetchone()
            conn.commit()

            return jsonify({
                'filter': {
                    'id': row[0],
                    'name': row[1],
                    'filters': row[2],
                    'created_at': row[3].isoformat() if row[3] else None
                }
            }), 201
    except Exception as e:
        print(f'[ERROR] POST /api/leads/saved-filters: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/leads/saved-filters/<int:filter_id>', methods=['DELETE'])
def delete_saved_filter(filter_id):
    """Delete a saved filter (owner only)"""
    try:
        token = get_auth_header()
        user_id = verify_token(token)
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401

        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'DELETE FROM saved_filters WHERE id = %s AND user_id = %s RETURNING id',
                (filter_id, user_id)
            )
            deleted = c.fetchone()
            if not deleted:
                return jsonify({'error': 'Filter not found'}), 404
            conn.commit()
            return jsonify({'deleted': True}), 200
    except Exception as e:
        print(f'[ERROR] DELETE /api/leads/saved-filters/{filter_id}: {e}')
        return jsonify({'error': str(e)}), 500


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

    # SaaS: Check export limit
    plan = _get_user_plan(user_id)
    limits = _get_plan_limits(plan)
    usage = _get_usage_stats(user_id)

    if usage['leads_exported'] >= limits['exports_per_month']:
        return jsonify({
            'error': f'Export limit reached for {plan} plan',
            'limit': limits['exports_per_month'],
            'used': usage['leads_exported'],
            'plan': plan,
            'message': f'You have reached your monthly export limit ({limits["exports_per_month"]} exports). Upgrade your plan to export more.'
        }), 403

    fmt = request.args.get('format', 'csv').strip().lower()
    if fmt not in ('csv', 'mailchimp', 'whatsapp', 'whatsapp_txt', 'vcard', 'json'):
        return jsonify({'error': 'Invalid format. Use: csv, mailchimp, whatsapp, whatsapp_txt, vcard, json'}), 400

    # Build query with same filters as list_leads
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '').strip()
    tag = request.args.get('tag', '').strip()
    batch_id = request.args.get('batch_id', '').strip()
    ids = request.args.get('ids', '').strip()

    # Semana 4: export from shared base
    query = SHARED_LEADS_SELECT
    params = []

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

    # SaaS: Increment export counter
    _increment_usage(user_id, 'leads_exported', 1)

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


# ============= Send Leads to CRM (Extrator → DIAX CRM) =============

@app.route('/api/leads/send-to-crm', methods=['POST'])
@limiter.limit("10/minute")
def send_leads_to_crm():
    """
    Send selected leads or filtered leads to DIAX CRM.
    Accepts lead_ids, filters, CRM URL and token.
    Returns: {success, sent_count, failed_count, errors}
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    lead_ids = data.get('lead_ids', [])
    filters = data.get('filters', {}) if isinstance(data.get('filters', {}), dict) else {}
    crm_api_url = data.get('crm_api_url', '').strip()
    crm_auth_token = data.get('crm_auth_token', '').strip()

    # Validation
    if not crm_api_url or not crm_auth_token:
        _log_send_to_crm_failure(
            user_id=user_id,
            filters=filters,
            lead_ids=lead_ids,
            crm_api_url=crm_api_url,
            error_message='CRM URL and token are required',
            status_code=400,
            stage='validation',
            source='backend',
        )
        return jsonify({'success': False, 'error': 'CRM URL and token are required'}), 400

    # SSRF Prevention: validate CRM URL
    parsed = urlparse(crm_api_url)
    hostname = parsed.hostname or ''
    if not (hostname == 'localhost' or hostname == '127.0.0.1' or parsed.scheme == 'https'):
        _log_send_to_crm_failure(
            user_id=user_id,
            filters=filters,
            lead_ids=lead_ids,
            crm_api_url=crm_api_url,
            error_message='Invalid CRM URL. Only http://localhost, http://127.0.0.1, or https:// URLs are allowed',
            status_code=400,
            stage='validation',
            source='backend',
        )
        return jsonify({
            'success': False,
            'error': 'Invalid CRM URL. Only http://localhost, http://127.0.0.1, or https:// URLs are allowed'
        }), 400

    # Build query to fetch leads
    query = SHARED_LEADS_SELECT
    params = []

    if lead_ids:
        id_list = [int(x) for x in lead_ids if isinstance(x, int) or (isinstance(x, str) and x.isdigit())]
        if id_list:
            query += f' AND l.id IN ({",".join(["%s"] * len(id_list))})'
            params.extend(id_list)
    else:
        # Apply filters if no specific lead_ids
        search = filters.get('search', '').strip()
        status = filters.get('status', '').strip()
        tag = filters.get('tag', '').strip()
        city = filters.get('city', '').strip()
        state = filters.get('state', '').strip()

        if search:
            query += ''' AND (l.company_name ILIKE %s OR l.email ILIKE %s
                         OR l.phone ILIKE %s OR l.website ILIKE %s
                         OR l.contact_name ILIKE %s OR l.cnpj ILIKE %s)'''
            like = f'%{search}%'
            params.extend([like, like, like, like, like, like])

        if status and status in CRM_STATUSES:
            query += ' AND l.crm_status = %s'
            params.append(status)

        if tag:
            query += ' AND l.tags ILIKE %s'
            params.append(f'%{tag}%')

        if city:
            query += ' AND l.city ILIKE %s'
            params.append(f'%{city}%')

        if state:
            query += ' AND l.state ILIKE %s'
            params.append(f'%{state}%')

    query += ' ORDER BY l.extracted_at DESC LIMIT 500'

    with get_db() as conn:
        c = conn.cursor()
        c.execute(query, params)
        rows = c.fetchall()

    if not rows:
        _log_send_to_crm_failure(
            user_id=user_id,
            filters=filters,
            lead_ids=lead_ids,
            crm_api_url=crm_api_url,
            error_message='No leads found matching criteria',
            status_code=404,
            stage='load_leads',
            source='backend',
        )
        return jsonify({
            'success': False,
            'error': 'No leads found matching criteria',
            'sent_count': 0,
            'failed_count': 0
        }), 404

    leads = [lead_row_to_dict(row) for row in rows]

    # Deduplicate by email
    seen_emails = {}
    unique_leads = []
    for lead in leads:
        email = (lead.get('email') or '').strip().lower()
        if email and email not in seen_emails:
            seen_emails[email] = True
            unique_leads.append(lead)

    if not unique_leads:
        _log_send_to_crm_failure(
            user_id=user_id,
            filters=filters,
            lead_ids=lead_ids,
            crm_api_url=crm_api_url,
            error_message='No leads with valid emails found',
            status_code=404,
            stage='prepare_payload',
            total_leads=len(leads),
            source='backend',
        )
        return jsonify({
            'success': False,
            'error': 'No leads with valid emails found',
            'sent_count': 0,
            'failed_count': 0
        }), 404

    # Format leads for CRM API
    customers = []
    for lead in unique_leads:
        contact_name = lead.get('contact_name') or lead.get('company_name') or 'Lead'
        email = (lead.get('email') or '').strip()
        phone = lead.get('phone') or None
        whatsapp = lead.get('whatsapp') or None
        company_name = lead.get('company_name') or 'N/A'
        tags = lead.get('tags') or ''
        notes = lead.get('notes') or ''

        # Combine notes with tags for the CRM notes field
        combined_notes = f"{notes}{',' if notes and tags else ''}{tags}"

        customer = {
            'name': contact_name[:100],  # Limit to 100 chars
            'email': email,
            'phone': phone,
            'whatsApp': whatsapp,
            'companyName': company_name[:100],
            'notes': combined_notes[:500] if combined_notes else '',
            'tags': tags
        }
        customers.append(customer)

    # Send to CRM API
    # The CRM endpoint expects flat JSON: { "customers": [...], "source": <int> }
    # 'source' is an integer enum (0 = default/import). Sending it as a string
    # causes JSON binding to fail entirely, which is why previous attempts
    # produced "request field is required" (the [FromBody] parameter went null).
    payload = {
        'customers': customers,
        'source': 0,
    }

    headers = {
        'Authorization': f'Bearer {crm_auth_token}',
        'Content-Type': 'application/json'
    }

    try:
        crm_endpoint = f'{crm_api_url}/api/v1/customers/import'
        response = http_requests.post(
            crm_endpoint,
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code in [200, 201, 202]:
            result = response.json()
            sent_count = result.get('created', len(customers))
            failed_count = result.get('failed', 0)
            return jsonify({
                'success': True,
                'sent_count': sent_count,
                'failed_count': failed_count,
                'total_leads': len(unique_leads),
                'message': f'Successfully sent {sent_count} leads to CRM'
            }), 200
        else:
            error_msg = response.text[:200] if response.text else f'HTTP {response.status_code}'
            _log_send_to_crm_failure(
                user_id=user_id,
                filters=filters,
                lead_ids=lead_ids,
                crm_api_url=crm_api_url,
                error_message=f'CRM API error: {error_msg}',
                status_code=response.status_code,
                stage='crm_api_request',
                response_body=response.text,
                total_leads=len(unique_leads),
                source='backend',
            )
            return jsonify({
                'success': False,
                'error': f'CRM API error: {error_msg}',
                'sent_count': 0,
                'failed_count': len(unique_leads)
            }), response.status_code

    except Exception as e:
        error_str = str(e)[:200]
        _log_send_to_crm_failure(
            user_id=user_id,
            filters=filters,
            lead_ids=lead_ids,
            crm_api_url=crm_api_url,
            error_message=f'Failed to send leads to CRM: {error_str}',
            exc=e,
            status_code=500,
            stage='crm_api_request',
            total_leads=len(unique_leads),
            source='backend',
        )
        return jsonify({
            'success': False,
            'error': f'Failed to send leads to CRM: {error_str}',
            'sent_count': 0,
            'failed_count': len(unique_leads)
        }), 500


@app.route('/api/client-logs/send-to-crm-error', methods=['POST'])
@limiter.limit("30/minute")
def client_log_send_to_crm_error():
    """Persist frontend send-to-CRM failures into system_logs."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    filters = data.get('filters', {}) if isinstance(data.get('filters', {}), dict) else {}
    lead_ids = data.get('lead_ids', [])
    crm_api_url = (data.get('crm_api_url') or '').strip()
    error_message = (data.get('error') or 'Frontend send-to-CRM error').strip()
    stack = (data.get('stack') or '').strip()
    stage = (data.get('stage') or 'frontend').strip()
    status_code = data.get('status_code')

    _log_send_to_crm_failure(
        user_id=user_id,
        filters=filters,
        lead_ids=lead_ids,
        crm_api_url=crm_api_url,
        error_message=error_message,
        stack_text=stack,
        status_code=status_code,
        stage=stage,
        response_body=data.get('response_data'),
        total_leads=data.get('total_leads'),
        source='frontend',
    )

    return jsonify({'ok': True}), 202


@app.route('/api/analytics', methods=['GET'])
@limiter.limit("30/minute")
def get_analytics():
    """Dashboard analytics: shared base metrics for SaaS clients."""
    token = get_auth_header()
    user_id = verify_token(token)

    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()

        # Total leads in shared base
        c.execute('''SELECT COUNT(*) FROM leads l
                     JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE''')
        total_leads = c.fetchone()[0]

        # Average lead score
        c.execute('''SELECT COALESCE(AVG(COALESCE(l.lead_score, 0)), 0) FROM leads l
                     JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE AND l.lead_score IS NOT NULL AND l.lead_score > 0''')
        avg_score = round(float(c.fetchone()[0]), 1)

        # Total distinct cities
        c.execute('''SELECT COUNT(DISTINCT TRIM(l.city)) FROM leads l
                     JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE AND l.city IS NOT NULL AND l.city != '' ''')
        total_cities = c.fetchone()[0]

        # Total distinct categories
        c.execute('''SELECT COUNT(DISTINCT TRIM(l.category)) FROM leads l
                     JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE AND l.category IS NOT NULL AND l.category != '' ''')
        total_categories = c.fetchone()[0]

        # Leads added this week
        week_ago = datetime.now() - timedelta(days=7)
        c.execute('''SELECT COUNT(*) FROM leads l
                     JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE AND l.extracted_at >= %s''', (week_ago,))
        leads_this_week = c.fetchone()[0]

        # Top cities (top 8)
        c.execute('''SELECT TRIM(l.city) as city, COUNT(*) as cnt
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE AND l.city IS NOT NULL AND l.city != ''
                     GROUP BY TRIM(l.city) ORDER BY cnt DESC LIMIT 8''')
        top_cities = [{'name': row[0], 'count': row[1]} for row in c.fetchall()]

        # Top states (top 8)
        c.execute('''SELECT TRIM(l.state) as state, COUNT(*) as cnt
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE AND l.state IS NOT NULL AND l.state != ''
                     GROUP BY TRIM(l.state) ORDER BY cnt DESC LIMIT 8''')
        top_states = [{'name': row[0], 'count': row[1]} for row in c.fetchall()]

        # Top categories (top 8)
        c.execute('''SELECT TRIM(l.category) as cat, COUNT(*) as cnt
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE AND l.category IS NOT NULL AND l.category != ''
                     GROUP BY TRIM(l.category) ORDER BY cnt DESC LIMIT 8''')
        top_categories = [{'name': row[0], 'count': row[1]} for row in c.fetchall()]

        # Latest leads (10 most recent)
        c.execute('''SELECT l.id, l.company_name, l.email, l.city, l.state,
                            l.category, COALESCE(l.lead_score, 0) as lead_score, l.extracted_at
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE
                     ORDER BY l.extracted_at DESC LIMIT 10''')
        latest_rows = c.fetchall()
        latest_leads = [
            {
                'id': row[0],
                'company_name': row[1] or '',
                'email': row[2] or '',
                'city': row[3] or '',
                'state': row[4] or '',
                'category': row[5] or '',
                'lead_score': row[6],
                'extracted_at': row[7].isoformat() if row[7] else '',
            }
            for row in latest_rows
        ]

        # Score distribution
        c.execute('''SELECT
                       COUNT(*) FILTER (WHERE COALESCE(l.lead_score, 0) >= 70) as high,
                       COUNT(*) FILTER (WHERE COALESCE(l.lead_score, 0) >= 40 AND COALESCE(l.lead_score, 0) < 70) as medium,
                       COUNT(*) FILTER (WHERE COALESCE(l.lead_score, 0) < 40) as low
                     FROM leads l JOIN batches b ON l.batch_id = b.id
                     WHERE b.is_shared = TRUE''')
        score_row = c.fetchone()
        score_distribution = {
            'high': score_row[0] if score_row else 0,
            'medium': score_row[1] if score_row else 0,
            'low': score_row[2] if score_row else 0,
        }

    return jsonify({
        'total_leads': total_leads,
        'avg_score': avg_score,
        'total_cities': total_cities,
        'total_categories': total_categories,
        'leads_this_week': leads_this_week,
        'top_cities': top_cities,
        'top_states': top_states,
        'top_categories': top_categories,
        'latest_leads': latest_leads,
        'score_distribution': score_distribution,
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
    - Search Engines (DuckDuckGo/Bing/Yahoo - 6 fontes)
    - Google Maps Playwright
    - Diretórios BR (GuiaMais, TeleListas, Apontador)
    - Instagram Business (Instaloader)
    - LinkedIn Companies (Playwright)
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
    # Todos os métodos ativos por padrão
    methods = data.get('methods', ['api_enrichment', 'search_engines', 'google_maps', 'directories', 'instagram', 'linkedin'])
    max_pages = min(3, max(1, int(data.get('max_pages', 2))))
    # Semana 7: admin draft mode — batch starts unpublished (is_shared=FALSE)
    is_draft = bool(data.get('is_draft', False))

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

        # Calculate total jobs — mirrors the exact slices used in each method's loop
        total_jobs = 0
        if 'api_enrichment' in methods:
            total_jobs += min(3, len(niches)) * min(1, len(cities_to_search))
        if 'search_engines' in methods:
            total_jobs += min(3, len(niches))
        if 'google_maps' in methods:
            total_jobs += min(2, len(niches)) * min(2, len(cities_to_search))
        if 'directories' in methods:
            total_jobs += min(5, len(niches)) * min(5, len(cities_to_search))
        if 'instagram' in methods:
            total_jobs += min(2, len(niches)) * min(2, len(cities_to_search))
        if 'linkedin' in methods:
            total_jobs += min(2, len(niches)) * min(2, len(cities_to_search))
        if 'local_business_data' in methods:
            total_jobs += min(5, len(niches)) * min(3, len(cities_to_search))
        if 'receita_ws' in methods:
            total_jobs += min(3, len(niches)) * min(3, len(cities_to_search))
        if 'olx_ads' in methods:
            total_jobs += min(3, len(niches)) * min(3, len(cities_to_search))
        if 'whatsapp_dorks' in methods:
            total_jobs += min(3, len(niches)) * min(2, len(cities_to_search))

        is_shared_val = not is_draft  # draft → is_shared=FALSE; normal → TRUE
        c.execute(
            'INSERT INTO batches (user_id, name, status, total_urls, created_at, is_shared) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id',
            (user_id, batch_name, 'pending', total_jobs, datetime.now(), is_shared_val)
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
        # METHOD 2: SEARCH ENGINES (DuckDuckGo / Bing / Yahoo - 6 fontes)
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
                    'city': None,
                    'state': None,
                    'region': region_id,
                    'max_pages': max_pages,
                })

        # ===========================================================
        # METHOD 3: GOOGLE MAPS (Playwright)
        # ===========================================================
        google_maps_jobs = []
        if 'google_maps' in methods:
            for niche in niches[:2]:  # Max 2 para não saturar
                for city_data in cities_to_search[:2]:  # Max 2 cidades
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

        # ===========================================================
        # METHOD 4: DIRETÓRIOS BR (GuiaMais, TeleListas, Apontador)
        # ===========================================================
        directory_jobs = []
        if 'directories' in methods:
            for niche in niches[:5]:  # Até 5 nichos (mais rápido que Playwright)
                for city_data in cities_to_search[:5]:  # Até 5 cidades
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'directories', datetime.now())
                    )
                    search_job_id = c.fetchone()[0]
                    directory_jobs.append({
                        'search_job_id': search_job_id,
                        'niche': niche,
                        'city': city_data['city'],
                        'state': city_data['state'],
                    })

        # ===========================================================
        # METHOD 5: INSTAGRAM BUSINESS (Instaloader)
        # ===========================================================
        instagram_jobs = []
        if 'instagram' in methods:
            for niche in niches[:2]:  # Max 2 por rate limit do Instagram
                for city_data in cities_to_search[:2]:  # Max 2 cidades
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'instagram', datetime.now())
                    )
                    search_job_id = c.fetchone()[0]
                    instagram_jobs.append({
                        'search_job_id': search_job_id,
                        'niche': niche,
                        'city': city_data['city'],
                        'state': city_data['state'],
                    })

        # ===========================================================
        # METHOD 6: LINKEDIN COMPANIES (Playwright)
        # ===========================================================
        linkedin_jobs = []
        if 'linkedin' in methods:
            for niche in niches[:2]:  # Max 2 — LinkedIn tem anti-scraping forte
                for city_data in cities_to_search[:2]:  # Max 2 cidades
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'linkedin', datetime.now())
                    )
                    search_job_id = c.fetchone()[0]
                    linkedin_jobs.append({
                        'search_job_id': search_job_id,
                        'niche': niche,
                        'city': city_data['city'],
                        'state': city_data['state'],
                    })

        # ===========================================================
        # METHOD 7: LOCAL BUSINESS DATA (RapidAPI) — Google Maps via API
        # Free tier: 500 businesses/month → limita niches[:5] x cities[:3]
        # ===========================================================
        local_business_data_jobs = []
        if 'local_business_data' in methods:
            for niche in niches[:5]:
                for city_data in cities_to_search[:3]:
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'local_business_data', datetime.now())
                    )
                    search_job_id = c.fetchone()[0]
                    local_business_data_jobs.append({
                        'search_job_id': search_job_id,
                        'niche': niche,
                        'city': city_data['city'],
                        'state': city_data['state'],
                    })

        # ===========================================================
        # NEW METHODS 8-12
        # ===========================================================
        google_email_harvest_jobs = []
        if 'google_email_harvest' in methods:
            for niche in niches[:3]:
                for city_data in cities_to_search[:3]:
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'google_email_harvest', datetime.now()))
                    google_email_harvest_jobs.append({'search_job_id': c.fetchone()[0], 'niche': niche, 'city': city_data['city'], 'state': city_data['state']})

        website_email_crawler_jobs = []
        if 'website_email_crawler' in methods:
            for niche in niches[:5]:
                for city_data in cities_to_search[:5]:
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'website_email_crawler', datetime.now()))
                    website_email_crawler_jobs.append({'search_job_id': c.fetchone()[0], 'niche': niche, 'city': city_data['city'], 'state': city_data['state']})

        cnpj_open_jobs = []
        if 'cnpj_open' in methods:
            for niche in niches[:3]:
                for city_data in cities_to_search[:3]:
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'cnpj_open', datetime.now()))
                    cnpj_open_jobs.append({'search_job_id': c.fetchone()[0], 'niche': niche, 'city': city_data['city'], 'state': city_data['state']})

        serper_google_jobs = []
        if 'serper_google' in methods:
            for niche in niches[:5]:
                for city_data in cities_to_search[:3]:
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'serper_google', datetime.now()))
                    serper_google_jobs.append({'search_job_id': c.fetchone()[0], 'niche': niche, 'city': city_data['city'], 'state': city_data['state']})

        apify_maps_jobs = []
        if 'apify_maps' in methods:
            for niche in niches[:3]:
                for city_data in cities_to_search[:2]:
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'apify_maps', datetime.now()))
                    apify_maps_jobs.append({'search_job_id': c.fetchone()[0], 'niche': niche, 'city': city_data['city'], 'state': city_data['state']})

        receita_ws_jobs = []
        if 'receita_ws' in methods:
            for niche in niches[:3]:
                for city_data in cities_to_search[:3]:
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'receita_ws', datetime.now()))
                    receita_ws_jobs.append({'search_job_id': c.fetchone()[0], 'niche': niche, 'city': city_data['city'], 'state': city_data['state']})

        olx_ads_jobs = []
        if 'olx_ads' in methods:
            for niche in niches[:3]:
                for city_data in cities_to_search[:3]:
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'olx_ads', datetime.now()))
                    olx_ads_jobs.append({'search_job_id': c.fetchone()[0], 'niche': niche, 'city': city_data['city'], 'state': city_data['state']})

        whatsapp_dorks_jobs = []
        if 'whatsapp_dorks' in methods:
            for niche in niches[:3]:
                for city_data in cities_to_search[:2]:
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'whatsapp_dorks', datetime.now()))
                    whatsapp_dorks_jobs.append({'search_job_id': c.fetchone()[0], 'niche': niche, 'city': city_data['city'], 'state': city_data['state']})

        # Bug 2 fix: mark batch as 'processing' now that all jobs are queued
        c.execute("UPDATE batches SET status='processing' WHERE id=%s", (batch_id,))

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

    # Thread 2: Search Engines (6 fontes: Bing API, Google CSE, DDG API, DDG HTML, Bing HTML, Yahoo HTML)
    if search_engine_jobs:
        thread2 = threading.Thread(
            target=process_search_job,
            args=(batch_id, search_engine_jobs, user_id),
            daemon=True
        )
        thread2.start()

    # Thread 3: Google Maps (Playwright)
    if google_maps_jobs:
        thread3 = threading.Thread(
            target=process_google_maps_massive,
            args=(batch_id, google_maps_jobs, user_id, token),
            daemon=True
        )
        thread3.start()

    # Thread 4: Diretórios BR (GuiaMais, TeleListas, Apontador)
    if directory_jobs:
        thread4 = threading.Thread(
            target=process_directories_massive,
            args=(batch_id, directory_jobs, user_id),
            daemon=True
        )
        thread4.start()

    # Thread 5: Instagram Business (Instaloader)
    if instagram_jobs:
        thread5 = threading.Thread(
            target=process_instagram_massive,
            args=(batch_id, instagram_jobs, user_id),
            daemon=True
        )
        thread5.start()

    # Thread 6: LinkedIn Companies (Playwright)
    if linkedin_jobs:
        thread6 = threading.Thread(
            target=process_linkedin_massive,
            args=(batch_id, linkedin_jobs, user_id),
            daemon=True
        )
        thread6.start()

    # Thread 7: Local Business Data (RapidAPI — Google Maps via API)
    if local_business_data_jobs:
        thread7 = threading.Thread(
            target=process_local_business_data_massive,
            args=(batch_id, local_business_data_jobs, user_id),
            daemon=True
        )
        thread7.start()

    # Thread 8: Google Email Harvest (Playwright dorks)
    if google_email_harvest_jobs:
        threading.Thread(target=process_google_email_harvest_massive,
                         args=(batch_id, google_email_harvest_jobs, user_id), daemon=True).start()

    # Thread 9: Website Email Crawler (DDG + deep crawl)
    if website_email_crawler_jobs:
        threading.Thread(target=process_website_email_crawler_massive,
                         args=(batch_id, website_email_crawler_jobs, user_id), daemon=True).start()

    # Thread 10: OpenCNPJ (CNPJ directories + API enrichment)
    if cnpj_open_jobs:
        threading.Thread(target=process_cnpj_open_massive,
                         args=(batch_id, cnpj_open_jobs, user_id), daemon=True).start()

    # Thread 11: Serper.dev Google API (2500 free/month)
    if serper_google_jobs:
        threading.Thread(target=process_serper_google_massive,
                         args=(batch_id, serper_google_jobs, user_id), daemon=True).start()

    # Thread 12: Apify Google Maps ($5 free/month)
    if apify_maps_jobs:
        threading.Thread(target=process_apify_maps_massive,
                         args=(batch_id, apify_maps_jobs, user_id), daemon=True).start()

    # Thread 13: ReceitaWS CNPJ Search (3 req/min free)
    if receita_ws_jobs:
        threading.Thread(target=process_receita_ws_massive,
                         args=(batch_id, receita_ws_jobs, user_id), daemon=True).start()

    # Thread 14: OLX Service Ads (WhatsApp harvesting)
    if olx_ads_jobs:
        threading.Thread(target=process_olx_ads_massive,
                         args=(batch_id, olx_ads_jobs, user_id), daemon=True).start()

    # Thread 15: WhatsApp Dorks via Serper
    if whatsapp_dorks_jobs:
        threading.Thread(target=process_whatsapp_dorks_massive,
                         args=(batch_id, whatsapp_dorks_jobs, user_id), daemon=True).start()

    # Bug 4 fix: monitor thread marks batch 'completed' when all jobs finish
    monitor_thread = threading.Thread(target=_monitor_batch_completion, args=(batch_id,), daemon=True)
    monitor_thread.start()

    # AUTO-SANITIZE + SYNC: sanitiza leads ao completar, depois sincroniza com CRM
    threading.Thread(target=auto_sanitize_background, args=(batch_id,), daemon=True).start()

    return jsonify({
        'batch_id': batch_id,
        'name': batch_name,
        'total_jobs': total_jobs,
        'methods': {
            'api_enrichment':     len(api_enrichment_jobs),
            'search_engines':     len(search_engine_jobs),
            'google_maps':        len(google_maps_jobs),
            'directories':        len(directory_jobs),
            'instagram':          len(instagram_jobs),
            'linkedin':           len(linkedin_jobs),
            'local_business_data': len(local_business_data_jobs),
            'google_email_harvest': len(google_email_harvest_jobs),
            'website_email_crawler': len(website_email_crawler_jobs),
            'cnpj_open': len(cnpj_open_jobs),
            'serper_google': len(serper_google_jobs),
            'apify_maps': len(apify_maps_jobs),
            'receita_ws': len(receita_ws_jobs),
            'olx_ads': len(olx_ads_jobs),
            'whatsapp_dorks': len(whatsapp_dorks_jobs),
        },
        'status': 'processing',
        'message': f'Busca massiva iniciada com {total_jobs} jobs em {len(methods)} métodos'
    })


@_persist_thread_errors('google_maps')
def process_google_maps_massive(batch_id, jobs_data, user_id, token):
    """
    Process Google Maps jobs for massive search.
    - Retry 3x por job com backoff exponencial
    - Log de erros em scraper_errors.log
    - NUNCA para: sempre itera todos os jobs até o fim
    """
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[GOOGLE_MAPS] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'google_maps', f'batch={batch_id}',
                f'Iniciando scraping massivo Google Maps. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved = 0

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche = job_data['niche']
            city = job_data['city']
            state = job_data['state']
            query = f"{niche} {city} {state}"

            print(f"[GOOGLE_MAPS] Job {job_idx+1}/{len(jobs_data)}: {query}")

            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                result, err = _massive_retry(
                    lambda n=niche, c=city, s=state: scrape_google_maps(n, c, s, max_results=20),
                    provider='google_maps',
                    query=query
                )

                if result is not None:
                    leads_saved = _save_leads_to_batch(c, conn, batch_id, result, 'google_maps', city, state, 'GOOGLE_MAPS')
                    total_saved += leads_saved
                    status = 'completed'
                    err_msg = None
                    print(f"[GOOGLE_MAPS] Job {job_idx+1} OK: {leads_saved} leads salvos")
                    scraper_log('INFO', 'google_maps', query, f'Job concluído: {leads_saved} leads')
                else:
                    leads_saved = 0
                    status = 'failed'
                    err_msg = str(err)[:500] if err else 'Sem resultados após 3 tentativas'
                    print(f"[GOOGLE_MAPS] Job {job_idx+1} FALHOU: {err_msg}")

                try:
                    c.execute('UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                              (status, datetime.now(), leads_saved, err_msg, search_job_id))
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'google_maps', query, f'Erro inesperado no job: {e}', e)
                print(f"[GOOGLE_MAPS] Erro inesperado job {search_job_id}: {e}")
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            # Delay entre jobs para evitar rate limit
            time.sleep(10)

        scraper_log('INFO', 'google_maps', f'batch={batch_id}',
                    f'Thread finalizada. Total salvo: {total_saved} leads.')
        print(f"[GOOGLE_MAPS] Thread finalizada. batch={batch_id}, total={total_saved} leads")

    except Exception as e:
        scraper_log('CRITICAL', 'google_maps', f'batch={batch_id}',
                    f'Erro crítico na thread: {e}', e)
        print(f"[GOOGLE_MAPS] ERRO CRÍTICO: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ============================================================
# MASSIVE SEARCH PROCESSOR — Local Business Data (RapidAPI)
# ============================================================

@_persist_thread_errors('local_business_data')
def process_local_business_data_massive(batch_id, jobs_data, user_id):
    """
    Processa jobs via Local Business Data API (RapidAPI).
    Princípios de resiliência:
      - Retry 3x com backoff via _massive_retry por job
      - NUNCA lança exceção para fora — itera todos os jobs até o fim
      - Se quota excedida, marca restantes como skipped e encerra graciosamente
      - Loga cada falha no scraper_errors.log
    Free tier: 500 businesses/month → usa max_results=3 por query.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[LOCAL_BIZ] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'local_business_data', f'batch={batch_id}',
                f'Iniciando scraping via RapidAPI Local Business Data. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved    = 0
        quota_exceeded = False

        for job_idx, job_data in enumerate(jobs_data):

            search_job_id = job_data['search_job_id']
            niche  = job_data['niche']
            city   = job_data['city']
            state  = job_data['state']
            query  = f"{niche} {city} {state}"

            # Parar graciosamente se quota esgotada (não desperdiçar tentativas)
            if quota_exceeded:
                print(f"[LOCAL_BIZ] Quota excedida — marcando job {search_job_id} como skipped")
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', 'quota_exceeded', datetime.now(), search_job_id))
                except Exception:
                    pass
                continue

            print(f"[LOCAL_BIZ] Job {job_idx+1}/{len(jobs_data)}: {query}")

            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                result, err = _massive_retry(
                    lambda n=niche, ci=city, s=state: search_local_business_data(n, ci, s, max_results=3),
                    provider='local_business_data',
                    query=query
                )

                if result is not None:
                    leads_saved = _save_leads_to_batch(
                        c, conn, batch_id, result, 'local_business_data', city, state, 'LOCAL_BIZ'
                    )
                    total_saved += leads_saved
                    status  = 'completed'
                    err_msg = None
                    print(f"[LOCAL_BIZ] Job {job_idx+1} OK: {leads_saved} leads salvos")
                    scraper_log('INFO', 'local_business_data', query, f'Job concluído: {leads_saved} leads')
                else:
                    leads_saved = 0
                    status  = 'failed'
                    err_str = str(err)[:500] if err else 'Sem resultados após 3 tentativas'
                    err_msg = err_str
                    # Detectar quota excedida ou config ausente para não desperdiçar chamadas restantes
                    if err and ('quota' in str(err).lower() or '429' in str(err) or isinstance(err, ConfigError)):
                        quota_exceeded = True
                        reason = 'Config ausente (API key)' if isinstance(err, ConfigError) else 'Quota RapidAPI excedida'
                        scraper_log('WARNING', 'local_business_data', query,
                                    f'{reason} — parando thread graciosamente')
                    print(f"[LOCAL_BIZ] Job {job_idx+1} FALHOU: {err_msg}")
                    scraper_log('WARNING', 'local_business_data', query, f'Job falhou: {err_msg}')

                try:
                    c.execute(
                        'UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                        (status, datetime.now(), leads_saved, err_msg, search_job_id)
                    )
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'local_business_data', query, f'Erro inesperado no job: {e}', e)
                print(f"[LOCAL_BIZ] Erro inesperado job {search_job_id}: {e}")
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            # Delay menor que Google Maps (API é mais estável)
            time.sleep(5)

        scraper_log('INFO', 'local_business_data', f'batch={batch_id}',
                    f'Thread finalizada. Total salvo: {total_saved} leads.')
        print(f"[LOCAL_BIZ] Thread finalizada. batch={batch_id}, total={total_saved} leads")

    except Exception as e:
        scraper_log('CRITICAL', 'local_business_data', f'batch={batch_id}',
                    f'Erro crítico na thread: {e}', e)
        print(f"[LOCAL_BIZ] ERRO CRÍTICO: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ============================================================
# MASSIVE SEARCH PROCESSORS — Diretórios / Instagram / LinkedIn
# ============================================================

def _massive_retry(fn, provider, query, max_attempts=3):
    """
    Retry helper para os processadores massivos.
    Tenta até max_attempts vezes com backoff exponencial.
    Nunca lança exceção para fora — SEMPRE retorna (resultado_ou_None, erro_ou_None).
    Loga cada falha em scraper_errors.log.
    ConfigError e BlockedError não são retried — falham imediatamente.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = fn()
            return result, None
        except (ConfigError, BlockedError) as exc:
            # Erros de configuração ou bloqueio — retry não vai resolver
            scraper_log('ERROR', provider, query,
                        f'Falha não-retryable (tentativa {attempt}): {exc}', exc)
            return None, exc
        except Exception as exc:
            last_exc = exc
            scraper_log('WARNING', provider, query,
                        f'Tentativa {attempt}/{max_attempts} falhou: {exc}', exc)
            if attempt < max_attempts:
                wait = 5 * attempt  # 5s, 10s, 15s
                print(f"[{provider.upper()}] Aguardando {wait}s antes da tentativa {attempt+1}...")
                time.sleep(wait)
    # Todas tentativas esgotadas
    scraper_log('ERROR', provider, query,
                f'Todas {max_attempts} tentativas falharam. Último erro: {last_exc}', last_exc)
    return None, last_exc


def _save_leads_to_batch(c, conn, batch_id, leads, source, city, state, provider):
    """Salva lista de leads no batch. Retorna quantidade salva. Nunca lança exceção."""
    saved = 0
    now = datetime.now()
    for lead in leads:
        try:
            email = normalize_email(lead.get('email', '')) if lead.get('email') else None
            phone = lead.get('phone') or None
            website = lead.get('website') or None
            address = lead.get('address') or None
            instagram_url = lead.get('instagram') or None
            linkedin_url = lead.get('linkedin') or None
            whatsapp = lead.get('whatsapp') or None

            # Requer pelo menos UM campo de contato real (não aceita leads só com nome)
            if not email and not phone and not instagram_url and not linkedin_url and not whatsapp:
                continue

            # Limpar e validar nome da empresa antes de salvar
            raw_company = lead.get('company_name') or ''
            company = extract_clean_company_name(raw_company, email=email, website=website)
            if is_garbage_name(company):
                company = None
            company = company or f'Lead {source}'

            # Dedup email placeholder quando não há email real
            if email:
                dedup_email = email
            elif instagram_url:
                dedup_email = f"ig_{re.sub(r'[^a-z0-9]', '', instagram_url.lower()[-35:])}@instagram.local"
            elif linkedin_url:
                dedup_email = f"li_{re.sub(r'[^a-z0-9]', '', linkedin_url.lower()[-35:])}@linkedin.local"
            elif phone:
                dedup_email = f"phone_{re.sub(r'[^0-9]', '', phone)[:15]}@{source}.local"
            else:
                dedup_email = f"{source}_{re.sub(r'[^a-z0-9]', '', company.lower()[:30])}_{saved}@{source}.local"

            c.execute(
                '''INSERT INTO leads (batch_id, company_name, email, phone, website, address,
                                      instagram, linkedin, whatsapp, city, state, source, extracted_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (batch_id, email) DO NOTHING''',
                (batch_id, company, dedup_email, phone, website, address,
                 instagram_url, linkedin_url, whatsapp, city, state, source, now)
            )
            # Bug 3 fix: only count rows actually inserted (rowcount=0 means ON CONFLICT skipped)
            if c.rowcount == 1:
                saved += 1
        except Exception as e:
            print(f"[{provider.upper()}] Erro ao salvar lead: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
    return saved


@_persist_thread_errors('directories')
def process_directories_massive(batch_id, jobs_data, user_id):
    """
    Background thread: scrape GuiaMais, TeleListas e Apontador para cada nicho/cidade.
    - Retry 3x por job com backoff exponencial
    - Log de erros em scraper_errors.log
    - NUNCA para: sempre itera todos os jobs até o fim
    """
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[DIRECTORIES] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'directories', f'batch={batch_id}',
                f'Iniciando scraping de diretórios BR. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        session = http_requests.Session()
        total_saved = 0

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche = job_data['niche']
            city = job_data['city']
            state = job_data['state']
            query = f"{niche} {city} {state}"

            print(f"[DIRECTORIES] Job {job_idx+1}/{len(jobs_data)}: {query}")

            # Nunca para — cada job tem seu próprio try/except independente
            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                # Retry automático com backoff
                result, err = _massive_retry(
                    lambda: scrape_all_directories(niche, city, state, session),
                    provider='directories',
                    query=query
                )

                if result is not None:
                    leads, _domains = result
                    leads_saved = _save_leads_to_batch(c, conn, batch_id, leads, 'directories', city, state, 'DIRECTORIES')
                    total_saved += leads_saved
                    status = 'completed'
                    err_msg = None
                    print(f"[DIRECTORIES] Job {job_idx+1} OK: {leads_saved} leads salvos")
                    scraper_log('INFO', 'directories', query, f'Job concluído: {leads_saved} leads')
                else:
                    # Falhou após 3 tentativas — registra e continua
                    leads_saved = 0
                    status = 'failed'
                    err_msg = str(err)[:500] if err else 'Sem resultados após 3 tentativas'
                    print(f"[DIRECTORIES] Job {job_idx+1} FALHOU após 3 tentativas: {err_msg}")

                try:
                    c.execute('UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                              (status, datetime.now(), leads_saved, err_msg, search_job_id))
                except Exception:
                    pass

            except Exception as e:
                # Captura qualquer erro inesperado — não para a thread
                scraper_log('ERROR', 'directories', query, f'Erro inesperado no job: {e}', e)
                print(f"[DIRECTORIES] Erro inesperado job {search_job_id}: {e}")
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            # Delay entre jobs — sempre executado mesmo após erro
            time.sleep(random.uniform(3, 7))

        scraper_log('INFO', 'directories', f'batch={batch_id}',
                    f'Thread finalizada. Total salvo: {total_saved} leads.')
        print(f"[DIRECTORIES] Thread finalizada. batch={batch_id}, total={total_saved} leads")

    except Exception as e:
        # Erro crítico na thread inteira — loga mas não re-raise
        scraper_log('CRITICAL', 'directories', f'batch={batch_id}',
                    f'Erro crítico na thread: {e}', e)
        print(f"[DIRECTORIES] ERRO CRÍTICO: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


@_persist_thread_errors('instagram')
def process_instagram_massive(batch_id, jobs_data, user_id):
    """
    Background thread: scrape Instagram Business profiles para cada nicho/cidade.
    - Retry 3x por job com backoff exponencial
    - Log de erros em scraper_errors.log
    - NUNCA para: sempre itera todos os jobs até o fim
    """
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[INSTAGRAM] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'instagram', f'batch={batch_id}',
                f'Iniciando scraping massivo Instagram. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved = 0

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche = job_data['niche']
            city = job_data['city']
            state = job_data['state']
            query = f"{niche} {city} {state}"

            print(f"[INSTAGRAM] Job {job_idx+1}/{len(jobs_data)}: {query}")

            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                result, err = _massive_retry(
                    lambda: scrape_instagram_business(niche, city, state, max_results=30),
                    provider='instagram',
                    query=query
                )

                if result is not None:
                    leads = result
                    leads_saved = _save_leads_to_batch(c, conn, batch_id, leads, 'instagram', city, state, 'INSTAGRAM')
                    total_saved += leads_saved
                    status = 'completed'
                    err_msg = None
                    print(f"[INSTAGRAM] Job {job_idx+1} OK: {leads_saved} leads salvos")
                    scraper_log('INFO', 'instagram', query, f'Job concluído: {leads_saved} leads')
                else:
                    leads_saved = 0
                    status = 'failed'
                    err_msg = str(err)[:500] if err else 'Sem resultados após 3 tentativas'
                    print(f"[INSTAGRAM] Job {job_idx+1} FALHOU: {err_msg}")

                try:
                    c.execute('UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                              (status, datetime.now(), leads_saved, err_msg, search_job_id))
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'instagram', query, f'Erro inesperado no job: {e}', e)
                print(f"[INSTAGRAM] Erro inesperado job {search_job_id}: {e}")
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            # Delay longo — Instagram tem rate limiting muito agressivo
            time.sleep(random.uniform(30, 60))

        scraper_log('INFO', 'instagram', f'batch={batch_id}',
                    f'Thread finalizada. Total salvo: {total_saved} leads.')
        print(f"[INSTAGRAM] Thread finalizada. batch={batch_id}, total={total_saved} leads")

    except Exception as e:
        scraper_log('CRITICAL', 'instagram', f'batch={batch_id}',
                    f'Erro crítico na thread: {e}', e)
        print(f"[INSTAGRAM] ERRO CRÍTICO: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


@_persist_thread_errors('linkedin')
def process_linkedin_massive(batch_id, jobs_data, user_id):
    """
    Background thread: scrape LinkedIn Companies para cada nicho/cidade.
    - Retry 3x por job com backoff exponencial
    - Log de erros em scraper_errors.log
    - NUNCA para: sempre itera todos os jobs até o fim
    """
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[LINKEDIN] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'linkedin', f'batch={batch_id}',
                f'Iniciando scraping massivo LinkedIn. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved = 0

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche = job_data['niche']
            city = job_data['city']
            state = job_data['state']
            query = f"{niche} {city} {state}"

            print(f"[LINKEDIN] Job {job_idx+1}/{len(jobs_data)}: {query}")

            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                result, err = _massive_retry(
                    lambda: scrape_linkedin_companies(niche, city, state, max_results=20),
                    provider='linkedin',
                    query=query
                )

                if result is not None:
                    leads = result
                    leads_saved = _save_leads_to_batch(c, conn, batch_id, leads, 'linkedin', city, state, 'LINKEDIN')
                    total_saved += leads_saved
                    status = 'completed'
                    err_msg = None
                    print(f"[LINKEDIN] Job {job_idx+1} OK: {leads_saved} leads salvos")
                    scraper_log('INFO', 'linkedin', query, f'Job concluído: {leads_saved} leads')
                else:
                    leads_saved = 0
                    status = 'failed'
                    err_msg = str(err)[:500] if err else 'Sem resultados após 3 tentativas'
                    print(f"[LINKEDIN] Job {job_idx+1} FALHOU: {err_msg}")

                try:
                    c.execute('UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                              (status, datetime.now(), leads_saved, err_msg, search_job_id))
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'linkedin', query, f'Erro inesperado no job: {e}', e)
                print(f"[LINKEDIN] Erro inesperado job {search_job_id}: {e}")
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            # Delay longo — LinkedIn tem detecção de bot muito agressiva
            time.sleep(random.uniform(60, 120))

        scraper_log('INFO', 'linkedin', f'batch={batch_id}',
                    f'Thread finalizada. Total salvo: {total_saved} leads.')
        print(f"[LINKEDIN] Thread finalizada. batch={batch_id}, total={total_saved} leads")

    except Exception as e:
        scraper_log('CRITICAL', 'linkedin', f'batch={batch_id}',
                    f'Erro crítico na thread: {e}', e)
        print(f"[LINKEDIN] ERRO CRÍTICO: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ============================================================
# NEW MASSIVE PROCESSORS — 5 novos métodos
# ============================================================

@_persist_thread_errors('google_email_harvest')
def process_google_email_harvest_massive(batch_id, jobs_data, user_id):
    """Google Email Harvest via Playwright — busca dorks de email no Google."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[GOOGLE_HARVEST] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'google_email_harvest', f'batch={batch_id}',
                f'Iniciando Google Email Harvest. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved = 0

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche, city, state = job_data['niche'], job_data['city'], job_data['state']
            query = f"{niche} {city} {state}"

            print(f"[GOOGLE_HARVEST] Job {job_idx+1}/{len(jobs_data)}: {query}")
            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                result, err = _massive_retry(
                    lambda n=niche, ci=city, s=state: google_email_harvest(n, ci, s, max_results=20),
                    provider='google_email_harvest', query=query
                )

                if result is not None:
                    leads_saved = _save_leads_to_batch(c, conn, batch_id, result, 'google_email_harvest', city, state, 'GOOGLE_HARVEST')
                    total_saved += leads_saved
                    status, err_msg = 'completed', None
                    print(f"[GOOGLE_HARVEST] Job {job_idx+1} OK: {leads_saved} leads")
                    scraper_log('INFO', 'google_email_harvest', query, f'Job concluído: {leads_saved} leads')
                else:
                    status = 'failed'
                    err_msg = str(err)[:500] if err else 'Sem resultados'
                    print(f"[GOOGLE_HARVEST] Job {job_idx+1} FALHOU: {err_msg}")

                try:
                    c.execute('UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                              (status, datetime.now(), leads_saved if result else 0, err_msg, search_job_id))
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'google_email_harvest', query, f'Erro: {e}', e)
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            time.sleep(random.uniform(10, 20))

        scraper_log('INFO', 'google_email_harvest', f'batch={batch_id}',
                    f'Thread finalizada. Total: {total_saved} leads.')
        print(f"[GOOGLE_HARVEST] Finalizado. batch={batch_id}, total={total_saved}")

    except Exception as e:
        scraper_log('CRITICAL', 'google_email_harvest', f'batch={batch_id}', f'Erro crítico: {e}', e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@_persist_thread_errors('website_email_crawler')
def process_website_email_crawler_massive(batch_id, jobs_data, user_id):
    """Website Email Crawler — busca DDG + deep crawl de cada site."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[WEB_CRAWLER] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'website_email_crawler', f'batch={batch_id}',
                f'Iniciando Website Email Crawler. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved = 0

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche, city, state = job_data['niche'], job_data['city'], job_data['state']
            query = f"{niche} {city} {state}"

            print(f"[WEB_CRAWLER] Job {job_idx+1}/{len(jobs_data)}: {query}")
            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                result, err = _massive_retry(
                    lambda n=niche, ci=city, s=state: search_and_crawl_for_emails(n, ci, s, max_sites=15),
                    provider='website_email_crawler', query=query
                )

                if result is not None:
                    leads_saved = _save_leads_to_batch(c, conn, batch_id, result, 'website_email_crawler', city, state, 'WEB_CRAWLER')
                    total_saved += leads_saved
                    status, err_msg = 'completed', None
                    print(f"[WEB_CRAWLER] Job {job_idx+1} OK: {leads_saved} leads")
                    scraper_log('INFO', 'website_email_crawler', query, f'Job concluído: {leads_saved} leads')
                else:
                    status = 'failed'
                    err_msg = str(err)[:500] if err else 'Sem resultados'
                    print(f"[WEB_CRAWLER] Job {job_idx+1} FALHOU: {err_msg}")

                try:
                    c.execute('UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                              (status, datetime.now(), leads_saved if result else 0, err_msg, search_job_id))
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'website_email_crawler', query, f'Erro: {e}', e)
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            time.sleep(random.uniform(5, 10))

        scraper_log('INFO', 'website_email_crawler', f'batch={batch_id}',
                    f'Thread finalizada. Total: {total_saved} leads.')
        print(f"[WEB_CRAWLER] Finalizado. batch={batch_id}, total={total_saved}")

    except Exception as e:
        scraper_log('CRITICAL', 'website_email_crawler', f'batch={batch_id}', f'Erro crítico: {e}', e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@_persist_thread_errors('cnpj_open')
def process_cnpj_open_massive(batch_id, jobs_data, user_id):
    """OpenCNPJ — busca CNPJs em diretórios e enriquece via API gratuita."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[OPENCNPJ] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'cnpj_open', f'batch={batch_id}',
                f'Iniciando OpenCNPJ enrichment. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved = 0

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche, city, state = job_data['niche'], job_data['city'], job_data['state']
            query = f"{niche} {city} {state}"

            print(f"[OPENCNPJ] Job {job_idx+1}/{len(jobs_data)}: {query}")
            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                result, err = _massive_retry(
                    lambda n=niche, ci=city, s=state: search_opencnpj_by_directory(n, ci, s, max_results=15),
                    provider='cnpj_open', query=query
                )

                if result is not None:
                    leads_saved = _save_leads_to_batch(c, conn, batch_id, result, 'cnpj_open', city, state, 'OPENCNPJ')
                    total_saved += leads_saved
                    status, err_msg = 'completed', None
                    print(f"[OPENCNPJ] Job {job_idx+1} OK: {leads_saved} leads")
                    scraper_log('INFO', 'cnpj_open', query, f'Job concluído: {leads_saved} leads')
                else:
                    status = 'failed'
                    err_msg = str(err)[:500] if err else 'Sem resultados'
                    print(f"[OPENCNPJ] Job {job_idx+1} FALHOU: {err_msg}")

                try:
                    c.execute('UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                              (status, datetime.now(), leads_saved if result else 0, err_msg, search_job_id))
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'cnpj_open', query, f'Erro: {e}', e)
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            time.sleep(random.uniform(3, 6))

        scraper_log('INFO', 'cnpj_open', f'batch={batch_id}',
                    f'Thread finalizada. Total: {total_saved} leads.')
        print(f"[OPENCNPJ] Finalizado. batch={batch_id}, total={total_saved}")

    except Exception as e:
        scraper_log('CRITICAL', 'cnpj_open', f'batch={batch_id}', f'Erro crítico: {e}', e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@_persist_thread_errors('serper_google')
def process_serper_google_massive(batch_id, jobs_data, user_id):
    """Serper.dev — Google Search API (2500 buscas grátis/mês)."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[SERPER] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'serper_google', f'batch={batch_id}',
                f'Iniciando Serper Google Search. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved = 0
        quota_exceeded = False

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche, city, state = job_data['niche'], job_data['city'], job_data['state']
            query = f"{niche} {city} {state}"

            if quota_exceeded:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', 'quota_exceeded', datetime.now(), search_job_id))
                except Exception:
                    pass
                continue

            print(f"[SERPER] Job {job_idx+1}/{len(jobs_data)}: {query}")
            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                result, err = _massive_retry(
                    lambda n=niche, ci=city, s=state: serper_email_search(n, ci, s, max_results=15),
                    provider='serper_google', query=query
                )

                if result is not None:
                    leads_saved = _save_leads_to_batch(c, conn, batch_id, result, 'serper_google', city, state, 'SERPER')
                    total_saved += leads_saved
                    status, err_msg = 'completed', None
                    print(f"[SERPER] Job {job_idx+1} OK: {leads_saved} leads")
                    scraper_log('INFO', 'serper_google', query, f'Job concluído: {leads_saved} leads')
                else:
                    status = 'failed'
                    err_msg = str(err)[:500] if err else 'Sem resultados'
                    if err and ('quota' in str(err).lower() or '429' in str(err) or isinstance(err, ConfigError)):
                        quota_exceeded = True
                    print(f"[SERPER] Job {job_idx+1} FALHOU: {err_msg}")

                try:
                    c.execute('UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                              (status, datetime.now(), leads_saved if result else 0, err_msg, search_job_id))
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'serper_google', query, f'Erro: {e}', e)
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            time.sleep(random.uniform(2, 4))

        scraper_log('INFO', 'serper_google', f'batch={batch_id}',
                    f'Thread finalizada. Total: {total_saved} leads.')
        print(f"[SERPER] Finalizado. batch={batch_id}, total={total_saved}")

    except Exception as e:
        scraper_log('CRITICAL', 'serper_google', f'batch={batch_id}', f'Erro crítico: {e}', e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@_persist_thread_errors('apify_maps')
def process_apify_maps_massive(batch_id, jobs_data, user_id):
    """Apify Google Maps Scraper — free tier $5/mês (~1250 businesses)."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[APIFY_MAPS] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'apify_maps', f'batch={batch_id}',
                f'Iniciando Apify Maps. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved = 0
        quota_exceeded = False

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche, city, state = job_data['niche'], job_data['city'], job_data['state']
            query = f"{niche} {city} {state}"

            if quota_exceeded:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', 'quota_exceeded', datetime.now(), search_job_id))
                except Exception:
                    pass
                continue

            print(f"[APIFY_MAPS] Job {job_idx+1}/{len(jobs_data)}: {query}")
            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                result, err = _massive_retry(
                    lambda n=niche, ci=city, s=state: apify_google_maps_search(n, ci, s, max_results=15),
                    provider='apify_maps', query=query
                )

                if result is not None:
                    leads_saved = _save_leads_to_batch(c, conn, batch_id, result, 'apify_maps', city, state, 'APIFY_MAPS')
                    total_saved += leads_saved
                    status, err_msg = 'completed', None
                    print(f"[APIFY_MAPS] Job {job_idx+1} OK: {leads_saved} leads")
                    scraper_log('INFO', 'apify_maps', query, f'Job concluído: {leads_saved} leads')
                else:
                    status = 'failed'
                    err_msg = str(err)[:500] if err else 'Sem resultados'
                    if err and ('402' in str(err) or 'crédito' in str(err).lower() or isinstance(err, ConfigError)):
                        quota_exceeded = True
                    print(f"[APIFY_MAPS] Job {job_idx+1} FALHOU: {err_msg}")

                try:
                    c.execute('UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                              (status, datetime.now(), leads_saved if result else 0, err_msg, search_job_id))
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'apify_maps', query, f'Erro: {e}', e)
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            time.sleep(random.uniform(5, 10))

        scraper_log('INFO', 'apify_maps', f'batch={batch_id}',
                    f'Thread finalizada. Total: {total_saved} leads.')
        print(f"[APIFY_MAPS] Finalizado. batch={batch_id}, total={total_saved}")

    except Exception as e:
        scraper_log('CRITICAL', 'apify_maps', f'batch={batch_id}', f'Erro crítico: {e}', e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@_persist_thread_errors('receita_ws')
def process_receita_ws_massive(batch_id, jobs_data, user_id):
    """ReceitaWS — busca empresas ativas via API Receita Federal + enriquece CNPJ."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[RECEITA_WS] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'receita_ws', f'batch={batch_id}',
                f'Iniciando ReceitaWS search. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved = 0

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche, city, state = job_data['niche'], job_data['city'], job_data['state']
            query = f"{niche} {city} {state}"

            print(f"[RECEITA_WS] Job {job_idx+1}/{len(jobs_data)}: {query}")
            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                result, err = _massive_retry(
                    lambda n=niche, ci=city, s=state: search_receita_ws(n, ci, s, max_results=10),
                    provider='receita_ws', query=query
                )

                if result is not None:
                    leads_saved = _save_leads_to_batch(c, conn, batch_id, result, 'receita_ws', city, state, 'RECEITA_WS')
                    total_saved += leads_saved
                    status, err_msg = 'completed', None
                    print(f"[RECEITA_WS] Job {job_idx+1} OK: {leads_saved} leads")
                    scraper_log('INFO', 'receita_ws', query, f'Job concluído: {leads_saved} leads')
                else:
                    status = 'failed'
                    err_msg = str(err)[:500] if err else 'Sem resultados'
                    print(f"[RECEITA_WS] Job {job_idx+1} FALHOU: {err_msg}")

                try:
                    c.execute('UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                              (status, datetime.now(), leads_saved if result else 0, err_msg, search_job_id))
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'receita_ws', query, f'Erro: {e}', e)
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            # Rate limit: 3 req/min no search endpoint ReceitaWS
            time.sleep(random.uniform(20, 25))

        scraper_log('INFO', 'receita_ws', f'batch={batch_id}',
                    f'Thread finalizada. Total: {total_saved} leads.')
        print(f"[RECEITA_WS] Finalizado. batch={batch_id}, total={total_saved}")

    except Exception as e:
        scraper_log('CRITICAL', 'receita_ws', f'batch={batch_id}', f'Erro crítico: {e}', e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@_persist_thread_errors('olx_ads')
def process_olx_ads_massive(batch_id, jobs_data, user_id):
    """OLX Ads — scrapa anúncios de serviços no OLX para extrair WhatsApp/telefone."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[OLX_ADS] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'olx_ads', f'batch={batch_id}',
                f'Iniciando OLX Ads scraping. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved = 0

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche, city, state = job_data['niche'], job_data['city'], job_data['state']
            query = f"{niche} {city} {state}"

            print(f"[OLX_ADS] Job {job_idx+1}/{len(jobs_data)}: {query}")
            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                result, err = _massive_retry(
                    lambda n=niche, ci=city, s=state: scrape_olx_ads(n, ci, s, max_results=20),
                    provider='olx_ads', query=query
                )

                if result is not None:
                    leads_saved = _save_leads_to_batch(c, conn, batch_id, result, 'olx_ads', city, state, 'OLX_ADS')
                    total_saved += leads_saved
                    status, err_msg = 'completed', None
                    print(f"[OLX_ADS] Job {job_idx+1} OK: {leads_saved} leads")
                    scraper_log('INFO', 'olx_ads', query, f'Job concluído: {leads_saved} leads')
                else:
                    status = 'failed'
                    err_msg = str(err)[:500] if err else 'Sem resultados'
                    print(f"[OLX_ADS] Job {job_idx+1} FALHOU: {err_msg}")

                try:
                    c.execute('UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                              (status, datetime.now(), leads_saved if result else 0, err_msg, search_job_id))
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'olx_ads', query, f'Erro: {e}', e)
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            time.sleep(random.uniform(5, 10))

        scraper_log('INFO', 'olx_ads', f'batch={batch_id}',
                    f'Thread finalizada. Total: {total_saved} leads.')
        print(f"[OLX_ADS] Finalizado. batch={batch_id}, total={total_saved}")

    except Exception as e:
        scraper_log('CRITICAL', 'olx_ads', f'batch={batch_id}', f'Erro crítico: {e}', e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@_persist_thread_errors('whatsapp_dorks')
def process_whatsapp_dorks_massive(batch_id, jobs_data, user_id):
    """WhatsApp Dorks — descobre números WhatsApp via Serper dorks."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[WA_DORKS] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'whatsapp_dorks', f'batch={batch_id}',
                f'Iniciando WhatsApp Dorks. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved = 0
        quota_exceeded = False

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche, city, state = job_data['niche'], job_data['city'], job_data['state']
            query = f"{niche} {city} {state}"

            if quota_exceeded:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', 'quota_exceeded', datetime.now(), search_job_id))
                except Exception:
                    pass
                continue

            print(f"[WA_DORKS] Job {job_idx+1}/{len(jobs_data)}: {query}")
            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                result, err = _massive_retry(
                    lambda n=niche, ci=city, s=state: search_whatsapp_dorks(n, ci, s, max_results=15),
                    provider='whatsapp_dorks', query=query
                )

                if result is not None:
                    leads_saved = _save_leads_to_batch(c, conn, batch_id, result, 'whatsapp_dorks', city, state, 'WA_DORKS')
                    total_saved += leads_saved
                    status, err_msg = 'completed', None
                    print(f"[WA_DORKS] Job {job_idx+1} OK: {leads_saved} leads")
                    scraper_log('INFO', 'whatsapp_dorks', query, f'Job concluído: {leads_saved} leads')
                else:
                    status = 'failed'
                    err_msg = str(err)[:500] if err else 'Sem resultados'
                    if err and ('429' in str(err) or 'quota' in str(err).lower() or isinstance(err, ConfigError)):
                        quota_exceeded = True
                    print(f"[WA_DORKS] Job {job_idx+1} FALHOU: {err_msg}")

                try:
                    c.execute('UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                              (status, datetime.now(), leads_saved if result else 0, err_msg, search_job_id))
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'whatsapp_dorks', query, f'Erro: {e}', e)
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            time.sleep(random.uniform(3, 6))

        scraper_log('INFO', 'whatsapp_dorks', f'batch={batch_id}',
                    f'Thread finalizada. Total: {total_saved} leads.')
        print(f"[WA_DORKS] Finalizado. batch={batch_id}, total={total_saved}")

    except Exception as e:
        scraper_log('CRITICAL', 'whatsapp_dorks', f'batch={batch_id}', f'Erro crítico: {e}', e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


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

    # API keys with fallback: env -> AWS -> cache local -> DB
    apollo_key = resolve_secret_value(
        'APOLLO_API_KEY',
        secret_ids=['extratordedados/prod'],
        env_keys=['APOLLO_API_KEY'],
        db_provider='apollo',
    )
    pdl_key = resolve_secret_value(
        'PDL_API_KEY',
        secret_ids=['extratordedados/prod'],
        env_keys=['PDL_API_KEY'],
        db_provider='pdl',
    )
    findthatlead_key = resolve_secret_value(
        'FINDTHATLEAD_API_KEY',
        secret_ids=['extratordedados/prod'],
        env_keys=['FINDTHATLEAD_API_KEY'],
        db_provider='findthatlead',
    )

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

def _load_crm_credentials():
    """Load CRM credentials with fallback: env -> AWS -> cache local."""
    email = resolve_secret_value(
        'CRM_EMAIL',
        secret_ids=['extratordedados/prod'],
        env_keys=['CRM_EMAIL'],
        default='admin@alexandrequeiroz.com.br',
    )
    password = resolve_secret_value(
        'CRM_PASS',
        secret_ids=['extratordedados/prod'],
        env_keys=['CRM_PASS'],
        default='',
    )
    if password:
        return email, password
    print("[SYNC] CRM credentials unavailable in env, AWS, and local cache")
    return email, password

ALEXANDREQUEIROZ_EMAIL, ALEXANDREQUEIROZ_PASSWORD = _load_crm_credentials()

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

    # Sanitize before sending to CRM
    sanitized, issues, has_contact = sanitize_single_lead(lead_data)
    if not has_contact:
        return False, f"Lead descartado: {'; '.join(issues[:3])}", None
    lead_data = sanitized

    # Extract and validate data
    email = (lead_data.get('email') or '').strip()
    if not email or '@' not in email:
        return False, "Email inválido após sanitização", None

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
            f'{ALEXANDREQUEIROZ_API}/api/v1/leads',
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
            f'{ALEXANDREQUEIROZ_API}/api/v1/leads',
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


@_persist_thread_errors('monitor')
def _monitor_batch_completion(batch_id):
    """
    Bug 4 fix: Background thread that polls search_jobs and marks the batch as
    'completed' once every job reaches a terminal state (completed/failed/quota_exceeded).
    This allows auto_sync_new_leads_background to detect completion and proceed.
    """
    print(f"[MONITOR] Watching batch {batch_id} for completion")
    conn = psycopg2.connect(**DB_CONFIG)
    c = conn.cursor()
    try:
        terminal = ('completed', 'failed', 'quota_exceeded')
        max_wait = 1800  # 30 minutes max
        elapsed = 0
        while elapsed < max_wait:
            time.sleep(15)
            elapsed += 15
            c.execute(
                "SELECT COUNT(*) FROM search_jobs WHERE batch_id=%s AND status NOT IN %s",
                (batch_id, terminal)
            )
            row = c.fetchone()
            if row and row[0] == 0:
                # All jobs done → mark batch completed
                try:
                    c.execute(
                        "UPDATE batches SET status='completed' WHERE id=%s AND status='processing'",
                        (batch_id,)
                    )
                    conn.commit()
                    print(f"[MONITOR] Batch {batch_id} marked as completed")
                except Exception as e:
                    print(f"[MONITOR] Error marking batch completed: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                return
        print(f"[MONITOR] Timeout waiting for batch {batch_id} — marking completed anyway")
        try:
            c.execute(
                "UPDATE batches SET status='completed' WHERE id=%s AND status='processing'",
                (batch_id,)
            )
            conn.commit()
        except Exception as e:
            print(f"[MONITOR] Error on timeout completion: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
    except Exception as e:
        print(f"[MONITOR] Monitor thread error for batch {batch_id}: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def auto_sanitize_background(batch_id):
    """
    Background thread: aguarda o batch completar, sanitiza os leads e em seguida
    dispara o auto_sync_new_leads_background.
    Substitui o antigo sync_thread direto — pipeline: sanitize → sync.
    """
    print(f"[SANITIZE] Starting auto-sanitize for batch {batch_id}")
    time.sleep(5)

    conn = psycopg2.connect(**DB_CONFIG)
    c = conn.cursor()

    try:
        # Aguarda até 15 min pelo batch completar
        max_wait = 900
        elapsed = 0
        while elapsed < max_wait:
            c.execute('SELECT status FROM batches WHERE id = %s', (batch_id,))
            row = c.fetchone()
            if not row:
                print(f"[SANITIZE] Batch {batch_id} not found, aborting")
                return
            status = row[0]
            if status == 'completed':
                break
            elif status == 'failed':
                print(f"[SANITIZE] Batch {batch_id} failed, aborting sanitize")
                return
            time.sleep(10)
            elapsed += 10

        # Busca todos os leads do batch
        c.execute(
            '''SELECT id, company_name, email, phone, website, address,
                      city, state, source, instagram, linkedin, facebook,
                      whatsapp, cnpj, contact_name, notes, crm_status,
                      quality_score, batch_id
               FROM leads
               WHERE batch_id = %s
               ORDER BY id''',
            (batch_id,)
        )
        rows = c.fetchall()
        if not rows:
            print(f"[SANITIZE] No leads found for batch {batch_id}, skipping")
        else:
            cols = ['id', 'company_name', 'email', 'phone', 'website', 'address',
                    'city', 'state', 'source', 'instagram', 'linkedin', 'facebook',
                    'whatsapp', 'cnpj', 'contact_name', 'notes', 'crm_status',
                    'quality_score', 'batch_id']
            leads_raw = [dict(zip(cols, row)) for row in rows]
            total = len(leads_raw)

            ids_to_delete = []
            seen_emails = {}
            sanitized_leads = []

            # Pass 1: sanitizar cada lead
            for lead in leads_raw:
                sanitized, issues, has_contact = sanitize_single_lead(lead)
                if not has_contact:
                    ids_to_delete.append(lead['id'])
                    continue
                sanitized_leads.append(sanitized)

            # Pass 2: dedup por email dentro do batch
            final_leads = []
            for sanitized in sanitized_leads:
                email = (sanitized.get('email') or '').strip().lower()
                if email:
                    if email in seen_emails:
                        existing = seen_emails[email]
                        existing_score = existing.get('quality_score') or 0
                        new_score = sanitized.get('quality_score') or 0
                        if new_score > existing_score:
                            ids_to_delete.append(existing['id'])
                            seen_emails[email] = sanitized
                        else:
                            ids_to_delete.append(sanitized['id'])
                        continue
                    else:
                        seen_emails[email] = sanitized
                final_leads.append(sanitized)

            # Pass 3: atualizar leads válidos
            updated = 0
            for lead in final_leads:
                try:
                    c.execute(
                        '''UPDATE leads SET
                            company_name = %s, email = %s, phone = %s, website = %s,
                            address = %s, city = %s, state = %s, contact_name = %s,
                            quality_score = %s
                           WHERE id = %s''',
                        (
                            lead.get('company_name'), lead.get('email'), lead.get('phone'),
                            lead.get('website'), lead.get('address'), lead.get('city'),
                            lead.get('state'), lead.get('contact_name'),
                            lead.get('quality_score'), lead['id']
                        )
                    )
                    updated += 1
                except Exception as e:
                    print(f"[SANITIZE] Error updating lead {lead['id']}: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass

            # Pass 4: deletar leads inválidos/duplicados
            deleted = 0
            if ids_to_delete:
                unique_ids = list(set(ids_to_delete))
                try:
                    c.execute('DELETE FROM leads WHERE id = ANY(%s)', (unique_ids,))
                    deleted = len(unique_ids)
                except Exception as e:
                    print(f"[SANITIZE] Error deleting leads: {e}")

            conn.commit()
            print(f"[SANITIZE] ✅ Batch {batch_id}: {total} analisados, {updated} atualizados, {deleted} removidos")

    except Exception as e:
        print(f"[SANITIZE] ❌ Error in auto-sanitize for batch {batch_id}: {e}")
    finally:
        try:
            c.close()
            conn.close()
        except Exception:
            pass

    # Dispara sync após sanitização
    auto_sync_new_leads_background(batch_id)


@_persist_thread_errors('sync')
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


@app.route('/api/crm/sync-all', methods=['POST'])
@limiter.limit("2 per hour")
def crm_sync_all():
    """
    Manual endpoint to sync ALL leads (with email) to alexandrequeiroz.com.br CRM.
    Checks for duplicates before creating.
    Runs in background thread to avoid timeout.
    """
    user = verify_token(get_auth_header())
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = psycopg2.connect(**DB_CONFIG)
    c = conn.cursor()

    try:
        # Count total leads with email
        c.execute("SELECT COUNT(*) FROM leads WHERE email IS NOT NULL AND email != ''")
        total = c.fetchone()[0]

        if total == 0:
            return jsonify({'message': 'No leads with email found', 'total': 0}), 200

        # Fetch all leads with email
        c.execute(
            '''SELECT company_name, email, phone, website, city, state, source
               FROM leads
               WHERE email IS NOT NULL AND email != ''
               ORDER BY extracted_at DESC'''
        )
        rows = c.fetchall()

        leads_to_sync = [
            {
                'company_name': row[0],
                'email': row[1],
                'phone': row[2],
                'website': row[3],
                'city': row[4],
                'state': row[5],
                'source': row[6] or 'extrator-dados',
            }
            for row in rows
        ]

    finally:
        c.close()
        conn.close()

    def _run_sync(leads):
        print(f"[SYNC] Manual sync-all started: {len(leads)} leads")
        synced, skipped, errors = sync_leads_batch_to_alexandrequeiroz(leads, max_leads=len(leads))
        print(f"[SYNC] Manual sync-all done: {synced} created, {skipped} skipped, {errors} errors")

    threading.Thread(target=_run_sync, args=(leads_to_sync,), daemon=True).start()

    return jsonify({
        'message': f'Sync started for {len(leads_to_sync)} leads',
        'total_leads': len(leads_to_sync),
        'status': 'running'
    }), 202


@app.route('/api/crm/status', methods=['GET'])
def crm_status():
    """Check CRM connection status."""
    user = verify_token(get_auth_header())
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    token = get_alexandrequeiroz_token()
    if not token:
        return jsonify({'connected': False, 'error': 'Failed to authenticate with CRM'}), 200

    try:
        import requests as _req
        r = _req.get(
            f'{ALEXANDREQUEIROZ_API}/api/v1/leads',
            headers={'Authorization': f'Bearer {token}'},
            params={'pageSize': 1},
            timeout=8
        )
        if r.status_code == 200:
            data = r.json()
            return jsonify({
                'connected': True,
                'total_crm_leads': data.get('totalCount', 0),
                'crm_url': ALEXANDREQUEIROZ_API
            })
        else:
            return jsonify({'connected': False, 'error': f'CRM returned {r.status_code}'})
    except Exception as e:
        return jsonify({'connected': False, 'error': str(e)})


# ============= Daily Automated Pipeline =============

def _build_massive_search_jobs(batch_id, c, niches, cities_to_search, methods, max_pages, user_id):
    """Cria search_job records para todos os combos método+nicho+cidade."""
    api_enrichment_jobs = []
    search_engine_jobs  = []
    google_maps_jobs         = []
    directory_jobs           = []
    instagram_jobs           = []
    linkedin_jobs            = []
    local_business_data_jobs = []
    google_email_harvest_jobs = []
    website_email_crawler_jobs = []
    cnpj_open_jobs           = []
    serper_google_jobs       = []
    apify_maps_jobs          = []

    def _insert_job(engine, niche, city_data, source, mp):
        query = f"{niche} em {city_data['city']}"
        c.execute(
            '''INSERT INTO search_jobs
               (batch_id, user_id, query, engine, niche, city, state,
                region, max_pages, status, enrichment_source, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s) RETURNING id''',
            (batch_id, user_id, query, engine, niche,
             city_data['city'], city_data['state'], city_data['region'],
             mp, source, datetime.now())
        )
        job_id = c.fetchone()[0]
        return {'search_job_id': job_id, 'niche': niche,
                'city': city_data['city'], 'state': city_data['state'], 'query': query}

    if 'api_enrichment' in methods:
        for niche in niches:
            for cd in cities_to_search:
                api_enrichment_jobs.append(_insert_job('api_enrichment', niche, cd, 'hunter+snov', max_pages))

    if 'search_engines' in methods:
        for niche in niches:
            for cd in cities_to_search:
                search_engine_jobs.append(_insert_job('search', niche, cd, 'search_engines', max_pages))

    if 'google_maps' in methods:
        for niche in niches:
            for cd in cities_to_search:
                google_maps_jobs.append(_insert_job('google_maps', niche, cd, 'google_maps', max_pages))

    if 'directories' in methods:
        for niche in niches[:5]:
            for cd in cities_to_search[:5]:
                directory_jobs.append(_insert_job('directories', niche, cd, 'directories', 1))

    if 'instagram' in methods:
        for niche in niches[:2]:
            for cd in cities_to_search[:2]:
                instagram_jobs.append(_insert_job('instagram', niche, cd, 'instagram', 1))

    if 'linkedin' in methods:
        for niche in niches[:2]:
            for cd in cities_to_search[:2]:
                linkedin_jobs.append(_insert_job('linkedin', niche, cd, 'linkedin', 1))

    if 'local_business_data' in methods:
        for niche in niches[:5]:
            for cd in cities_to_search[:3]:
                local_business_data_jobs.append(
                    _insert_job('local_business_data', niche, cd, 'local_business_data', 1)
                )

    if 'google_email_harvest' in methods:
        for niche in niches[:3]:
            for cd in cities_to_search[:3]:
                google_email_harvest_jobs.append(
                    _insert_job('google_email_harvest', niche, cd, 'google_email_harvest', 1)
                )

    if 'website_email_crawler' in methods:
        for niche in niches[:5]:
            for cd in cities_to_search[:5]:
                website_email_crawler_jobs.append(
                    _insert_job('website_email_crawler', niche, cd, 'website_email_crawler', 1)
                )

    if 'cnpj_open' in methods:
        for niche in niches[:3]:
            for cd in cities_to_search[:3]:
                cnpj_open_jobs.append(
                    _insert_job('cnpj_open', niche, cd, 'cnpj_open', 1)
                )

    if 'serper_google' in methods:
        for niche in niches[:5]:
            for cd in cities_to_search[:3]:
                serper_google_jobs.append(
                    _insert_job('serper_google', niche, cd, 'serper_google', 1)
                )

    if 'apify_maps' in methods:
        for niche in niches[:3]:
            for cd in cities_to_search[:2]:
                apify_maps_jobs.append(
                    _insert_job('apify_maps', niche, cd, 'apify_maps', 1)
                )

    return {
        'api_enrichment':       api_enrichment_jobs,
        'search_engines':       search_engine_jobs,
        'google_maps':          google_maps_jobs,
        'directories':          directory_jobs,
        'instagram':            instagram_jobs,
        'linkedin':             linkedin_jobs,
        'local_business_data':  local_business_data_jobs,
        'google_email_harvest': google_email_harvest_jobs,
        'website_email_crawler': website_email_crawler_jobs,
        'cnpj_open':            cnpj_open_jobs,
        'serper_google':        serper_google_jobs,
        'apify_maps':           apify_maps_jobs,
    }


def run_daily_pipeline(daily_job_id, niches, region_id, cities_to_search):
    """
    Pipeline completo diário:
      1. Cria batch e roda busca massiva (6 métodos em paralelo)
      2. Aguarda conclusão (max 8h, poll 60s)
      3. Sanitiza todos os leads do batch
      4. Sync para api.alexandrequeiroz.com.br (sem duplicar)
      5. Atualiza daily_jobs com resultado
    """
    print(f"\n[DAILY] ======= Pipeline iniciado (id={daily_job_id}) =======")
    methods    = ['api_enrichment', 'search_engines', 'google_maps', 'directories', 'instagram', 'linkedin', 'local_business_data', 'google_email_harvest', 'website_email_crawler', 'cnpj_open']
    max_pages  = 2
    user_id    = DAILY_JOB_USER_ID
    batch_name = f'Pipeline Diário - {region_id} - {datetime.now().strftime("%Y-%m-%d")}'

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    c = conn.cursor()

    try:
        # ── 1. Criar batch ────────────────────────────────────────────────
        n_dirs   = min(5, len(niches))
        n_cities = min(5, len(cities_to_search))
        n_ig_li  = min(2, len(niches)) * min(2, len(cities_to_search))
        n_email_harvest = min(3, len(niches)) * min(3, len(cities_to_search))
        n_web_crawler   = min(5, len(niches)) * min(5, len(cities_to_search))
        n_cnpj_open     = min(3, len(niches)) * min(3, len(cities_to_search))
        total_jobs = (len(niches) * len(cities_to_search) * 3 +
                      n_dirs * n_cities +
                      n_ig_li * 2 +
                      n_email_harvest + n_web_crawler + n_cnpj_open)

        c.execute(
            'INSERT INTO batches (user_id, name, status, total_urls, created_at) '
            'VALUES (%s,%s,%s,%s,%s) RETURNING id',
            (user_id, batch_name, 'pending', total_jobs, datetime.now())
        )
        batch_id = c.fetchone()[0]
        c.execute('UPDATE daily_jobs SET batch_id=%s WHERE id=%s', (batch_id, daily_job_id))
        print(f"[DAILY] Batch criado: batch_id={batch_id}, jobs={total_jobs}")

        # ── 2. Criar search_job records e iniciar threads ────────────────
        jobs = _build_massive_search_jobs(batch_id, c, niches, cities_to_search, methods, max_pages, user_id)
        c.execute("UPDATE batches SET status='processing' WHERE id=%s", (batch_id,))

        if jobs['api_enrichment']:
            threading.Thread(target=process_api_search_job,
                             args=(batch_id, jobs['api_enrichment'], user_id), daemon=True).start()
        if jobs['search_engines']:
            threading.Thread(target=process_search_job,
                             args=(batch_id, jobs['search_engines'], user_id), daemon=True).start()
        if jobs['google_maps']:
            threading.Thread(target=process_google_maps_massive,
                             args=(batch_id, jobs['google_maps'], user_id, None), daemon=True).start()
        if jobs['directories']:
            threading.Thread(target=process_directories_massive,
                             args=(batch_id, jobs['directories'], user_id), daemon=True).start()
        if jobs['instagram']:
            threading.Thread(target=process_instagram_massive,
                             args=(batch_id, jobs['instagram'], user_id), daemon=True).start()
        if jobs['linkedin']:
            threading.Thread(target=process_linkedin_massive,
                             args=(batch_id, jobs['linkedin'], user_id), daemon=True).start()
        if jobs['local_business_data']:
            threading.Thread(target=process_local_business_data_massive,
                             args=(batch_id, jobs['local_business_data'], user_id), daemon=True).start()
        if jobs.get('google_email_harvest'):
            threading.Thread(target=process_google_email_harvest_massive,
                             args=(batch_id, jobs['google_email_harvest'], user_id), daemon=True).start()
        if jobs.get('website_email_crawler'):
            threading.Thread(target=process_website_email_crawler_massive,
                             args=(batch_id, jobs['website_email_crawler'], user_id), daemon=True).start()
        if jobs.get('cnpj_open'):
            threading.Thread(target=process_cnpj_open_massive,
                             args=(batch_id, jobs['cnpj_open'], user_id), daemon=True).start()
        if jobs.get('serper_google'):
            threading.Thread(target=process_serper_google_massive,
                             args=(batch_id, jobs['serper_google'], user_id), daemon=True).start()
        if jobs.get('apify_maps'):
            threading.Thread(target=process_apify_maps_massive,
                             args=(batch_id, jobs['apify_maps'], user_id), daemon=True).start()

        print(f"[DAILY] Threads iniciadas para batch {batch_id}")

        # ── 3. Aguardar conclusão (max 8h, poll 60s) ──────────────────────
        max_wait      = 8 * 3600
        poll_interval = 60
        waited        = 0
        while waited < max_wait:
            time.sleep(poll_interval)
            waited += poll_interval
            c.execute('''
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('completed','failed')) AS done,
                    COUNT(*) FILTER (WHERE status IN ('pending','processing')) AS remaining
                FROM search_jobs WHERE batch_id = %s
            ''', (batch_id,))
            done, remaining = c.fetchone()
            print(f"[DAILY] Batch {batch_id}: done={done}, remaining={remaining} (waited {waited}s)")
            if remaining == 0:
                break

        c.execute(
            'UPDATE batches SET status=%s, updated_at=NOW() WHERE id=%s',
            ('completed', batch_id)
        )

        # ── 4. Contar leads ───────────────────────────────────────────────
        c.execute('SELECT COUNT(*) FROM leads WHERE batch_id=%s', (batch_id,))
        leads_found = c.fetchone()[0]
        c.execute('UPDATE daily_jobs SET leads_found=%s WHERE id=%s', (leads_found, daily_job_id))
        print(f"[DAILY] Leads encontrados: {leads_found}")

        # ── 5. Sanitizar leads do batch ───────────────────────────────────
        print(f"[DAILY] Sanitizando leads do batch {batch_id}...")
        c.execute('''
            SELECT id, company_name, email, phone, website, city, state,
                   category, source, instagram, facebook, linkedin, twitter,
                   whatsapp, cnpj, address, contact_name, quality_score, extra_data
            FROM leads WHERE batch_id = %s
        ''', (batch_id,))
        _cols = ['id','company_name','email','phone','website','city','state',
                 'category','source','instagram','facebook','linkedin','twitter',
                 'whatsapp','cnpj','address','contact_name','quality_score','extra_data']
        leads_rows = c.fetchall()

        ids_to_delete = []
        seen_emails   = {}
        sanitized_count = 0

        for row in leads_rows:
            lead    = dict(zip(_cols, row))
            lead_id = lead['id']
            sanitized, _, has_contact = sanitize_single_lead(lead)

            if not has_contact:
                ids_to_delete.append(lead_id)
                continue

            norm_email = (sanitized.get('email') or '').lower().strip()
            if norm_email and norm_email in seen_emails:
                ids_to_delete.append(lead_id)
                continue
            if norm_email:
                seen_emails[norm_email] = lead_id

            new_score, _, _ = calculate_email_quality_score(sanitized.get('email') or '')
            try:
                c.execute('''
                    UPDATE leads
                    SET email=%s, phone=%s, website=%s, company_name=%s,
                        quality_score=%s, updated_at=NOW()
                    WHERE id=%s
                ''', (sanitized.get('email'), sanitized.get('phone'),
                      sanitized.get('website'), sanitized.get('company_name'),
                      new_score, lead_id))
                sanitized_count += 1
            except Exception as upd_err:
                print(f"[DAILY] Erro ao atualizar lead {lead_id}: {upd_err}")

        if ids_to_delete:
            c.execute('DELETE FROM leads WHERE id = ANY(%s)', (ids_to_delete,))
            print(f"[DAILY] Removidos {len(ids_to_delete)} leads inválidos/duplicados")

        c.execute('UPDATE daily_jobs SET leads_sanitized=%s WHERE id=%s', (sanitized_count, daily_job_id))
        print(f"[DAILY] Sanitização: {sanitized_count} atualizados, {len(ids_to_delete)} removidos")

        # ── 6. Sync para CRM ──────────────────────────────────────────────
        c.execute('''
            SELECT id, company_name, email, phone, website, city, state, source
            FROM leads
            WHERE batch_id=%s AND email IS NOT NULL AND email != ''
              AND email NOT LIKE '%%@directory.local'
              AND email NOT LIKE '%%@instagram.local'
              AND email NOT LIKE '%%@linkedin.local'
        ''', (batch_id,))
        _sync_cols = ['id','company_name','email','phone','website','city','state','source']
        leads_to_sync = [dict(zip(_sync_cols, r)) for r in c.fetchall()]

        print(f"[DAILY] Sincronizando {len(leads_to_sync)} leads com CRM...")
        synced, skipped, errors = sync_leads_batch_to_alexandrequeiroz(leads_to_sync, max_leads=len(leads_to_sync))
        c.execute('UPDATE daily_jobs SET leads_synced=%s, leads_skipped=%s WHERE id=%s',
                  (synced, skipped, daily_job_id))
        print(f"[DAILY] CRM sync: {synced} criados, {skipped} já existiam, {errors} erros")

        # ── 7. Marcar como concluído ──────────────────────────────────────
        c.execute(
            "UPDATE daily_jobs SET status='completed', finished_at=NOW() WHERE id=%s",
            (daily_job_id,)
        )
        print(f"[DAILY] ======= Pipeline CONCLUÍDO (id={daily_job_id}) =======\n")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[DAILY] ERRO CRÍTICO: {e}\n{tb}")
        try:
            c.execute(
                "UPDATE daily_jobs SET status='failed', finished_at=NOW(), error_message=%s WHERE id=%s",
                (str(e)[:500], daily_job_id)
            )
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ============= Daily CRM Sync (09:00 AM) =============

def _run_crm_sync_batch(sync_job_id):
    """
    Background thread: synchronize all leads with email to alexandrequeiroz.com.br CRM.
    Uses batch import endpoint for efficiency.
    """
    print(f"[CRM_SYNC] Job {sync_job_id} started")
    conn = psycopg2.connect(**DB_CONFIG)
    c = conn.cursor()

    try:
        # Fetch all leads with email from shared base
        c.execute(
            '''SELECT id, company_name, email, phone, website, city, state, contact_name, tags, notes, whatsapp
               FROM leads l
               JOIN batches b ON l.batch_id = b.id
               WHERE l.email IS NOT NULL AND l.email != '' AND b.is_shared = TRUE
               ORDER BY l.extracted_at DESC LIMIT 5000'''
        )
        rows = c.fetchall()
        leads_total = len(rows)
        print(f"[CRM_SYNC] Found {leads_total} leads to sync")

        if leads_total == 0:
            c.execute(
                "UPDATE crm_sync_logs SET status='completed', finished_at=NOW(), leads_total=0 WHERE id=%s",
                (sync_job_id,)
            )
            conn.commit()
            return

        # Deduplicate by email
        seen_emails = {}
        unique_leads = []
        for row in rows:
            email = (row[2] or '').strip().lower()
            if email and email not in seen_emails:
                seen_emails[email] = True
                unique_leads.append({
                    'id': row[0],
                    'company_name': row[1],
                    'email': row[2],
                    'phone': row[3],
                    'website': row[4],
                    'city': row[5],
                    'state': row[6],
                    'contact_name': row[7],
                    'tags': row[8],
                    'notes': row[9],
                    'whatsapp': row[10]
                })

        # Format for CRM import API
        customers = []
        for lead in unique_leads:
            contact_name = lead.get('contact_name') or lead.get('company_name') or 'Lead'
            email = (lead.get('email') or '').strip()
            phone = lead.get('phone') or None
            whatsapp = lead.get('whatsapp') or None
            company_name = lead.get('company_name') or 'N/A'
            tags = lead.get('tags') or ''
            notes = lead.get('notes') or ''

            combined_notes = f"{notes}{',' if notes and tags else ''}{tags}"

            customer = {
                'name': contact_name[:100],
                'email': email,
                'phone': phone,
                'whatsApp': whatsapp,
                'companyName': company_name[:100],
                'notes': combined_notes[:500] if combined_notes else '',
                'tags': tags
            }
            customers.append(customer)

        # Get CRM token
        token = get_alexandrequeiroz_token()
        if not token:
            raise Exception("Failed to obtain CRM authentication token")

        # Prepare payload
        payload = {
            'customers': customers,
            'source': 'ExtractorImport'
        }

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        # Send to CRM API
        crm_endpoint = f'{ALEXANDREQUEIROZ_API}/api/v1/customers/import'
        print(f"[CRM_SYNC] Sending {len(customers)} customers to {crm_endpoint}")

        response = http_requests.post(
            crm_endpoint,
            headers=headers,
            json=payload,
            timeout=60
        )

        if response.status_code in [200, 201, 202]:
            result = response.json()
            leads_synced = result.get('created', len(customers))
            leads_skipped = result.get('skipped', 0)
            leads_failed = result.get('failed', 0)

            print(f"[CRM_SYNC] ✅ Success: {leads_synced} created, {leads_skipped} skipped, {leads_failed} failed")

            c.execute(
                '''UPDATE crm_sync_logs
                   SET status='completed', finished_at=NOW(), leads_total=%s,
                       leads_synced=%s, leads_skipped=%s, leads_failed=%s
                   WHERE id=%s''',
                (len(unique_leads), leads_synced, leads_skipped, leads_failed, sync_job_id)
            )
            conn.commit()
        else:
            error_msg = response.text[:200] if response.text else f'HTTP {response.status_code}'
            print(f"[CRM_SYNC] ❌ API error: {error_msg}")

            c.execute(
                '''UPDATE crm_sync_logs
                   SET status='failed', finished_at=NOW(), leads_total=%s,
                       error_message=%s
                   WHERE id=%s''',
                (len(unique_leads), error_msg, sync_job_id)
            )
            conn.commit()

    except Exception as e:
        error_str = str(e)[:500]
        print(f"[CRM_SYNC] ❌ Exception: {error_str}")

        try:
            c.execute(
                '''UPDATE crm_sync_logs
                   SET status='failed', finished_at=NOW(), error_message=%s
                   WHERE id=%s''',
                (error_str, sync_job_id)
            )
            conn.commit()
        except Exception:
            pass

    finally:
        try:
            conn.close()
        except Exception:
            pass


def trigger_daily_crm_sync(trigger='scheduled'):
    """
    Trigger daily CRM sync (09:00). Guard + insert + thread pattern.
    trigger: 'scheduled' (automatic) or 'manual' (user-initiated)
    """
    conn = psycopg2.connect(**DB_CONFIG)
    c = conn.cursor()

    try:
        # Guard: avoid double-fire (check last 5 minutes)
        c.execute(
            "SELECT id FROM crm_sync_logs WHERE started_at > NOW() - INTERVAL '5 minutes' AND status='running'"
        )
        if c.fetchone():
            print("[CRM_SYNC] Already running, skipping")
            return

        # Insert record
        c.execute(
            "INSERT INTO crm_sync_logs (trigger, status) VALUES (%s, 'running') RETURNING id",
            (trigger,)
        )
        sync_job_id = c.fetchone()[0]
        conn.commit()

    except Exception as e:
        print(f"[CRM_SYNC] Failed to start: {e}")
        return

    finally:
        try:
            c.close()
            conn.close()
        except Exception:
            pass

    # Spawn daemon thread
    threading.Thread(target=_run_crm_sync_batch, args=(sync_job_id,), daemon=True).start()
    print(f"[CRM_SYNC] Daily sync initiated (job {sync_job_id}, trigger={trigger})")


def trigger_daily_pipeline(niches=None, region_id=None):
    """Cria registro daily_job e dispara run_daily_pipeline em background."""
    niches    = niches    or DAILY_JOB_NICHES
    region_id = region_id or DAILY_JOB_REGION

    if region_id not in SEARCH_REGIONS:
        print(f"[DAILY] Região desconhecida: {region_id}")
        return None

    region_data      = SEARCH_REGIONS[region_id]
    cities_to_search = [
        {'city': city, 'state': region_data['state'], 'region': region_id}
        for city in region_data['cities']
    ]

    try:
        with get_db() as conn:
            cur = conn.cursor()
            # Guard: evita double-fire quando Gunicorn usa múltiplos workers
            cur.execute(
                "SELECT id FROM daily_jobs WHERE started_at > NOW() - INTERVAL '5 minutes'"
            )
            if cur.fetchone():
                print("[DAILY] Job já iniciado por outro worker nos últimos 5 min — abortando.")
                return None
            cur.execute(
                "INSERT INTO daily_jobs (status, niches_used, region_used, started_at) "
                "VALUES ('running', %s, %s, NOW()) RETURNING id",
                (niches, region_id)
            )
            daily_job_id = cur.fetchone()[0]

        print(f"[DAILY] Pipeline disparado: id={daily_job_id}, região={region_id}, nichos={len(niches)}")
        threading.Thread(
            target=run_daily_pipeline,
            args=(daily_job_id, niches, region_id, cities_to_search),
            daemon=True
        ).start()
        return daily_job_id
    except Exception as e:
        print(f"[DAILY] Falha ao disparar: {e}")
        return None


@app.route('/api/admin/daily-job/status', methods=['GET'])
@limiter.limit("30/minute")
def daily_job_status():
    """Retorna histórico dos últimos 10 jobs diários."""
    user = verify_token(get_auth_header())
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT is_admin FROM users WHERE id=%s', (user,))
        row = cur.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403

        cur.execute('''
            SELECT id, started_at, finished_at, status, batch_id,
                   niches_used, region_used, leads_found, leads_sanitized,
                   leads_synced, leads_skipped, error_message
            FROM daily_jobs ORDER BY started_at DESC LIMIT 10
        ''')
        jobs = []
        for r in cur.fetchall():
            jobs.append({
                'id':              r[0],
                'started_at':      r[1].isoformat() if r[1] else None,
                'finished_at':     r[2].isoformat() if r[2] else None,
                'status':          r[3],
                'batch_id':        r[4],
                'niches':          r[5],
                'region':          r[6],
                'leads_found':     r[7],
                'leads_sanitized': r[8],
                'leads_synced':    r[9],
                'leads_skipped':   r[10],
                'error':           r[11],
            })

    return jsonify({
        'jobs': jobs,
        'next_scheduled': f'{DAILY_JOB_HOUR:02d}:00 (America/Sao_Paulo)',
        'default_region': DAILY_JOB_REGION,
        'default_niches': DAILY_JOB_NICHES,
    })


@app.route('/api/niches/custom', methods=['GET'])
@limiter.limit("60/minute")
def get_custom_niches():
    """Return all custom niches saved by users. Auth required."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT id, name, created_at FROM custom_niches ORDER BY name ASC')
        rows = c.fetchall()
        niches = [{'id': r[0], 'name': r[1], 'created_at': r[2].isoformat() if r[2] else None} for r in rows]

    return jsonify({'niches': niches}), 200


@app.route('/api/niches/custom', methods=['POST'])
@limiter.limit("30/minute")
def add_custom_niche():
    """Save a new custom niche. Auth required."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name é obrigatório'}), 400

    with get_db() as conn:
        c = conn.cursor()
        try:
            c.execute(
                'INSERT INTO custom_niches (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id',
                (name,)
            )
            row = c.fetchone()
            conn.commit()
            niche_id = row[0] if row else None
        except Exception as e:
            conn.rollback()
            return jsonify({'error': str(e)}), 500

    return jsonify({'id': niche_id, 'name': name}), 200 if niche_id is None else 201


@app.route('/api/niches/custom/<path:name>', methods=['DELETE'])
@limiter.limit("30/minute")
def delete_custom_niche(name):
    """Delete a custom niche by name. Auth required."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM custom_niches WHERE LOWER(name) = LOWER(%s)', (name,))
        conn.commit()

    return jsonify({'deleted': name}), 200


@app.route('/api/admin/logs', methods=['GET'])
@limiter.limit("60/minute")
def admin_logs():
    """Return paginated system_logs entries. Admin only."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        row = c.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Forbidden'}), 403

        level   = request.args.get('level', '')
        provider = request.args.get('provider', '')
        search  = request.args.get('search', '')
        error_type = request.args.get('error_type', '')
        date_from = request.args.get('date_from', '')
        date_to   = request.args.get('date_to', '')
        group_by  = request.args.get('group_by', '')  # provider, query, error_type
        page    = max(1, int(request.args.get('page', 1)))
        per_page = min(200, max(10, int(request.args.get('per_page', 50))))
        offset  = (page - 1) * per_page

        conditions = []
        params: list = []

        if level:
            conditions.append('level = %s')
            params.append(level.upper())
        if provider:
            conditions.append('provider ILIKE %s')
            params.append(f'%{provider}%')
        if search:
            conditions.append('(message ILIKE %s OR query ILIKE %s OR exception ILIKE %s)')
            params += [f'%{search}%', f'%{search}%', f'%{search}%']
        if error_type:
            conditions.append('error_type = %s')
            params.append(error_type)
        if date_from:
            conditions.append('created_at >= %s')
            params.append(date_from)
        if date_to:
            conditions.append('created_at <= %s')
            params.append(date_to)

        where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''

        c.execute(f'SELECT COUNT(*) FROM system_logs {where}', params)
        total = c.fetchone()[0]

        c.execute(
            f'''SELECT id, created_at, level, provider, query, message, exception, fix_prompt, error_type, extra_data
                FROM system_logs {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s''',
            params + [per_page, offset]
        )
        rows = c.fetchall()

        import json as _json
        logs = []
        for r in rows:
            extra = None
            if r[9]:
                try:
                    extra = r[9] if isinstance(r[9], dict) else _json.loads(r[9])
                except Exception:
                    extra = None
            logs.append({
                'id':         r[0],
                'created_at': r[1].isoformat() if r[1] else None,
                'level':      r[2],
                'provider':   r[3],
                'query':      r[4],
                'message':    r[5],
                'exception':  r[6],
                'fix_prompt': r[7],
                'error_type': r[8],
                'extra_data': extra,
            })

        # Level counts for summary bar
        c.execute(
            '''SELECT level, COUNT(*) FROM system_logs GROUP BY level ORDER BY level'''
        )
        level_counts = {row[0]: row[1] for row in c.fetchall()}

        # Error type counts
        c.execute(
            '''SELECT error_type, COUNT(*) FROM system_logs WHERE error_type IS NOT NULL GROUP BY error_type ORDER BY COUNT(*) DESC'''
        )
        error_type_counts = {row[0]: row[1] for row in c.fetchall()}

        # Provider counts
        c.execute(
            '''SELECT provider, COUNT(*) FROM system_logs WHERE provider IS NOT NULL GROUP BY provider ORDER BY COUNT(*) DESC'''
        )
        provider_counts = {row[0]: row[1] for row in c.fetchall()}

    return jsonify({
        'logs':               logs,
        'total':              total,
        'page':               page,
        'per_page':           per_page,
        'total_pages':        (total + per_page - 1) // per_page,
        'level_counts':       level_counts,
        'error_type_counts':  error_type_counts,
        'provider_counts':    provider_counts,
    })


@app.route('/api/admin/logs', methods=['DELETE'])
@limiter.limit("5/hour")
def admin_logs_delete_all():
    """Delete ALL system_logs entries. Admin only."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        row = c.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Forbidden'}), 403

        c.execute('SELECT COUNT(*) FROM system_logs')
        total = c.fetchone()[0]
        c.execute('TRUNCATE TABLE system_logs')
        conn.commit()

    return jsonify({'message': f'{total} logs excluidos', 'deleted': total})


@app.route('/api/admin/daily-job/run', methods=['POST'])
@limiter.limit("2/hour")
def daily_job_run():
    """Dispara o pipeline diário manualmente."""
    user = verify_token(get_auth_header())
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT is_admin FROM users WHERE id=%s', (user,))
        row = cur.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403

    data      = request.get_json() or {}
    niches    = data.get('niches')    or DAILY_JOB_NICHES
    region_id = data.get('region')    or DAILY_JOB_REGION

    daily_job_id = trigger_daily_pipeline(niches=niches, region_id=region_id)
    if not daily_job_id:
        return jsonify({'error': 'Falha ao iniciar pipeline'}), 500

    return jsonify({
        'message':      'Pipeline diário iniciado',
        'daily_job_id': daily_job_id,
        'niches_count': len(niches),
        'region':       region_id,
        'status':       'running',
    }), 202


@app.route('/api/crm/refine', methods=['POST'])
@limiter.limit("2/hour")
def crm_refine():
    """
    Sanitiza todos os leads com email e sincroniza com o CRM,
    eliminando inválidos e duplicados. Roda em background.
    """
    user = verify_token(get_auth_header())
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT is_admin FROM users WHERE id=%s', (user,))
        row = cur.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403

    def _run_refine():
        print("[CRM_REFINE] Iniciando refinamento de leads...")
        rconn = psycopg2.connect(**DB_CONFIG)
        rconn.autocommit = True
        rc = rconn.cursor()
        try:
            rc.execute('''
                SELECT id, company_name, email, phone, website, city, state,
                       category, source, instagram, facebook, linkedin, twitter,
                       whatsapp, cnpj, address, contact_name, quality_score, extra_data
                FROM leads
                WHERE email IS NOT NULL AND email != ''
                  AND email NOT LIKE '%%@directory.local'
                  AND email NOT LIKE '%%@instagram.local'
                  AND email NOT LIKE '%%@linkedin.local'
                ORDER BY quality_score DESC NULLS LAST
            ''')
            _cols = ['id','company_name','email','phone','website','city','state',
                     'category','source','instagram','facebook','linkedin','twitter',
                     'whatsapp','cnpj','address','contact_name','quality_score','extra_data']
            rows         = rc.fetchall()
            total        = len(rows)
            san_count    = 0
            invalid_count = 0
            seen_emails  = {}
            to_sync      = []

            for row in rows:
                lead    = dict(zip(_cols, row))
                lead_id = lead['id']
                sanitized, _, has_contact = sanitize_single_lead(lead)

                if not has_contact:
                    invalid_count += 1
                    continue

                norm_email = (sanitized.get('email') or '').lower().strip()
                if norm_email in seen_emails:
                    invalid_count += 1
                    continue
                seen_emails[norm_email] = lead_id

                new_score, _, _ = calculate_email_quality_score(sanitized.get('email') or '')
                try:
                    rc.execute('''
                        UPDATE leads
                        SET email=%s, phone=%s, website=%s, company_name=%s,
                            quality_score=%s, updated_at=NOW()
                        WHERE id=%s
                    ''', (sanitized.get('email'), sanitized.get('phone'),
                          sanitized.get('website'), sanitized.get('company_name'),
                          new_score, lead_id))
                    san_count += 1
                except Exception as e:
                    print(f"[CRM_REFINE] Erro update lead {lead_id}: {e}")
                to_sync.append(sanitized)

            synced = skipped = 0
            if to_sync:
                synced, skipped, _ = sync_leads_batch_to_alexandrequeiroz(to_sync, max_leads=len(to_sync))

            print(f"[CRM_REFINE] Concluído: total={total}, sanitizados={san_count}, "
                  f"inválidos={invalid_count}, sincronizados={synced}, já existiam={skipped}")
        except Exception as e:
            print(f"[CRM_REFINE] ERRO: {e}")
        finally:
            rconn.close()

    threading.Thread(target=_run_refine, daemon=True).start()
    return jsonify({'message': 'Refinamento CRM iniciado em background', 'status': 'running'}), 202


# ============= CRM Sync Status & Manual Trigger =============

@app.route('/api/crm/sync-status', methods=['GET'])
@limiter.limit("30/minute")
def crm_sync_status():
    """Get CRM sync history (last 10 executions)"""
    user = verify_token(get_auth_header())
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''
                SELECT id, started_at, finished_at, status, leads_total, leads_synced,
                       leads_skipped, leads_failed, error_message, trigger
                FROM crm_sync_logs
                ORDER BY started_at DESC
                LIMIT 10
            ''')
            rows = c.fetchall()

        syncs = []
        for row in rows:
            syncs.append({
                'id': row[0],
                'started_at': row[1].isoformat() if row[1] else None,
                'finished_at': row[2].isoformat() if row[2] else None,
                'status': row[3],
                'leads_total': row[4],
                'leads_synced': row[5],
                'leads_skipped': row[6],
                'leads_failed': row[7],
                'error_message': row[8],
                'trigger': row[9]
            })

        return jsonify({
            'syncs': syncs,
            'total': len(syncs),
            'next_sync': f'{DAILY_CRM_SYNC_HOUR:02d}:00 (America/Sao_Paulo)'
        }), 200

    except Exception as e:
        print(f'[ERROR] /api/crm/sync-status: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/crm/auto-token', methods=['GET'])
@limiter.limit("10/minute")
def crm_auto_token():
    """
    Get CRM URL and JWT token automatically.
    Token is obtained via get_alexandrequeiroz_token() with cache 6h.
    Used by frontend modal to auto-fill "Enviar para CRM" form.
    """
    user = verify_token(get_auth_header())
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        token = get_alexandrequeiroz_token()
        if not token:
            return jsonify({'error': 'Não foi possível autenticar no CRM'}), 503

        return jsonify({
            'crm_url': ALEXANDREQUEIROZ_API,
            'token': token,
        }), 200

    except Exception as e:
        print(f'[ERROR] /api/crm/auto-token: {e}')
        return jsonify({'error': f'Erro ao obter token: {str(e)[:100]}'}), 500


@app.route('/api/crm/sync-now', methods=['POST'])
@limiter.limit("2/hour")
def crm_sync_now():
    """Manually trigger CRM sync (admin only)"""
    user = verify_token(get_auth_header())
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT is_admin FROM users WHERE id=%s', (user,))
        row = cur.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403

    try:
        trigger_daily_crm_sync(trigger='manual')
        return jsonify({
            'message': 'CRM sync triggered manually',
            'status': 'running',
            'trigger': 'manual'
        }), 202

    except Exception as e:
        print(f'[ERROR] /api/crm/sync-now: {e}')
        return jsonify({'error': str(e)}), 500


# ============= SaaS: Usage Tracking & Plan Management =============

def _get_current_month_year():
    """Return current month in 'YYYY-MM' format"""
    return datetime.now().strftime('%Y-%m')

def _reset_monthly_usage(user_id):
    """Reset usage tracking for current month if entry doesn't exist"""
    month_year = _get_current_month_year()
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'SELECT id FROM usage_tracking WHERE user_id = %s AND month_year = %s',
            (user_id, month_year)
        )
        if not c.fetchone():
            c.execute(
                'INSERT INTO usage_tracking (user_id, month_year, leads_viewed, leads_exported, reset_at) VALUES (%s, %s, 0, 0, %s)',
                (user_id, month_year, datetime.now())
            )

def _get_user_plan(user_id):
    """Get user's current plan (free/pro/enterprise)"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT plan FROM users WHERE id = %s', (user_id,))
        result = c.fetchone()
        return result[0] if result else 'free'

def _get_plan_limits(plan_name):
    """Get limits for a given plan"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'SELECT leads_per_month, exports_per_month, price_monthly, features FROM plan_limits WHERE plan_name = %s',
            (plan_name,)
        )
        result = c.fetchone()
        if result:
            return {
                'leads_per_month': result[0],
                'exports_per_month': result[1],
                'price_monthly': float(result[2]) if result[2] else 0,
                'features': result[3] if result[3] else {}
            }
        return None

def _get_usage_stats(user_id):
    """Get current month usage stats for a user"""
    month_year = _get_current_month_year()
    _reset_monthly_usage(user_id)

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'SELECT leads_viewed, leads_exported FROM usage_tracking WHERE user_id = %s AND month_year = %s',
            (user_id, month_year)
        )
        result = c.fetchone()
        return {
            'leads_viewed': result[0] if result else 0,
            'leads_exported': result[1] if result else 0,
            'month_year': month_year
        }

def _increment_usage(user_id, field='leads_viewed', amount=1):
    """Increment usage counter (leads_viewed or leads_exported)"""
    month_year = _get_current_month_year()
    _reset_monthly_usage(user_id)

    with get_db() as conn:
        c = conn.cursor()
        if field == 'leads_viewed':
            c.execute(
                'UPDATE usage_tracking SET leads_viewed = leads_viewed + %s WHERE user_id = %s AND month_year = %s',
                (amount, user_id, month_year)
            )
        elif field == 'leads_exported':
            c.execute(
                'UPDATE usage_tracking SET leads_exported = leads_exported + %s WHERE user_id = %s AND month_year = %s',
                (amount, user_id, month_year)
            )

@app.route('/api/client/usage', methods=['GET'])
@limiter.limit("30/minute")
def client_usage():
    """Get client's plan and current usage stats"""
    try:
        token = get_auth_header()
        user_id = verify_token(token)
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401

        plan = _get_user_plan(user_id)
        limits = _get_plan_limits(plan)
        usage = _get_usage_stats(user_id)

        return jsonify({
            'plan': plan,
            'limits': limits,
            'usage': usage,
            'usage_percent': {
                'leads': (usage['leads_viewed'] / limits['leads_per_month'] * 100) if limits['leads_per_month'] > 0 else 0,
                'exports': (usage['leads_exported'] / limits['exports_per_month'] * 100) if limits['exports_per_month'] > 0 else 0
            }
        }), 200
    except Exception as e:
        print(f'[ERROR] /api/client/usage: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users', methods=['GET'])
@limiter.limit("30/minute")
def admin_users():
    """Get all users and their plans (admin only)"""
    try:
        token = get_auth_header()
        user_id = verify_token(token)
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401

        # Check if user is admin
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT is_admin FROM users WHERE id = %s', (user_id,))
            result = c.fetchone()
            if not result or not result[0]:
                return jsonify({'error': 'Forbidden: Admin access required'}), 403

            # Get all users with their plans
            c.execute('SELECT id, username, plan, created_at, is_admin FROM users ORDER BY created_at DESC')
            users = []
            for row in c.fetchall():
                usage = _get_usage_stats(row[0])
                limits = _get_plan_limits(row[2])
                users.append({
                    'id': row[0],
                    'username': row[1],
                    'plan': row[2],
                    'created_at': row[3].isoformat() if row[3] else None,
                    'is_admin': bool(row[4]),
                    'usage': usage,
                    'limits': limits
                })

            return jsonify({'users': users, 'total': len(users)}), 200
    except Exception as e:
        print(f'[ERROR] /api/admin/users: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/summary', methods=['GET'])
@limiter.limit("30/minute")
def admin_summary():
    """Quick summary stats for the admin home page."""
    try:
        token = get_auth_header()
        admin_id = verify_token(token)
        if not admin_id:
            return jsonify({'error': 'Unauthorized'}), 401

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT is_admin FROM users WHERE id = %s', (admin_id,))
            result = c.fetchone()
            if not result or not result[0]:
                return jsonify({'error': 'Forbidden: Admin access required'}), 403

            c.execute('SELECT COUNT(*) FROM users')
            total_users = c.fetchone()[0]

            c.execute('SELECT COUNT(*) FROM users WHERE is_admin = TRUE')
            total_admins = c.fetchone()[0]

            c.execute('SELECT plan, COUNT(*) FROM users GROUP BY plan')
            users_by_plan = {row[0]: row[1] for row in c.fetchall()}

            c.execute('''SELECT COUNT(*) FROM leads l
                         JOIN batches b ON l.batch_id = b.id
                         WHERE b.is_shared = TRUE''')
            total_leads = c.fetchone()[0]

            # Leads added this week
            week_ago = datetime.now() - timedelta(days=7)
            c.execute('''SELECT COUNT(*) FROM leads l
                         JOIN batches b ON l.batch_id = b.id
                         WHERE b.is_shared = TRUE AND l.extracted_at >= %s''', (week_ago,))
            leads_this_week = c.fetchone()[0]

        return jsonify({
            'total_users': total_users,
            'total_admins': total_admins,
            'total_customers': total_users - total_admins,
            'users_by_plan': users_by_plan,
            'total_leads': total_leads,
            'leads_this_week': leads_this_week,
        }), 200
    except Exception as e:
        print(f'[ERROR] /api/admin/summary: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/batches', methods=['GET'])
@limiter.limit("30/minute")
def admin_list_batches():
    """List all batches (admin only) — for the admin base-management view."""
    try:
        token = get_auth_header()
        admin_id = verify_token(token)
        if not admin_id:
            return jsonify({'error': 'Unauthorized'}), 401
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT is_admin FROM users WHERE id = %s', (admin_id,))
            result = c.fetchone()
            if not result or not result[0]:
                return jsonify({'error': 'Forbidden: Admin access required'}), 403

            c.execute('''
                SELECT b.id, b.name, b.status, b.total_urls, b.processed_urls,
                       b.total_leads, b.created_at, b.finished_at, b.is_shared,
                       COUNT(l.id) as lead_count
                FROM batches b
                LEFT JOIN leads l ON l.batch_id = b.id
                GROUP BY b.id, b.name, b.status, b.total_urls, b.processed_urls,
                         b.total_leads, b.created_at, b.finished_at, b.is_shared
                ORDER BY b.created_at DESC
                LIMIT 50
            ''')
            batches = []
            for row in c.fetchall():
                batches.append({
                    'id': row[0],
                    'name': row[1],
                    'status': row[2],
                    'total_urls': row[3],
                    'processed_urls': row[4],
                    'total_leads': row[5],
                    'created_at': row[6].isoformat() if row[6] else None,
                    'finished_at': row[7].isoformat() if row[7] else None,
                    'is_shared': bool(row[8]) if row[8] is not None else True,
                    'lead_count': row[9],
                })
            return jsonify({'batches': batches}), 200
    except Exception as e:
        print(f'[ERROR] /api/admin/batches: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/batches/<int:batch_id>/publish', methods=['PUT'])
@limiter.limit("30/minute")
def admin_publish_batch(batch_id):
    """Publish a batch to the shared base (admin only)."""
    try:
        token = get_auth_header()
        admin_id = verify_token(token)
        if not admin_id:
            return jsonify({'error': 'Unauthorized'}), 401
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT is_admin FROM users WHERE id = %s', (admin_id,))
            result = c.fetchone()
            if not result or not result[0]:
                return jsonify({'error': 'Forbidden: Admin access required'}), 403
            c.execute('UPDATE batches SET is_shared = TRUE WHERE id = %s', (batch_id,))
            if c.rowcount == 0:
                return jsonify({'error': 'Batch not found'}), 404
            return jsonify({'success': True, 'batch_id': batch_id, 'is_shared': True}), 200
    except Exception as e:
        print(f'[ERROR] /api/admin/batches/{batch_id}/publish: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/batches/<int:batch_id>/unpublish', methods=['PUT'])
@limiter.limit("30/minute")
def admin_unpublish_batch(batch_id):
    """Remove a batch from the shared base (admin only)."""
    try:
        token = get_auth_header()
        admin_id = verify_token(token)
        if not admin_id:
            return jsonify({'error': 'Unauthorized'}), 401
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT is_admin FROM users WHERE id = %s', (admin_id,))
            result = c.fetchone()
            if not result or not result[0]:
                return jsonify({'error': 'Forbidden: Admin access required'}), 403
            c.execute('UPDATE batches SET is_shared = FALSE WHERE id = %s', (batch_id,))
            if c.rowcount == 0:
                return jsonify({'error': 'Batch not found'}), 404
            return jsonify({'success': True, 'batch_id': batch_id, 'is_shared': False}), 200
    except Exception as e:
        print(f'[ERROR] /api/admin/batches/{batch_id}/unpublish: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users/<int:user_id>/plan', methods=['PUT'])
@limiter.limit("30/minute")
def admin_update_user_plan(user_id):
    """Update a user's plan (admin only)"""
    try:
        token = get_auth_header()
        admin_id = verify_token(token)
        if not admin_id:
            return jsonify({'error': 'Unauthorized'}), 401

        # Check if requester is admin
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT is_admin FROM users WHERE id = %s', (admin_id,))
            result = c.fetchone()
            if not result or not result[0]:
                return jsonify({'error': 'Forbidden: Admin access required'}), 403

            # Validate new plan exists
            data = request.get_json() or {}
            new_plan = data.get('plan', 'free').lower()

            c.execute('SELECT plan_name FROM plan_limits WHERE plan_name = %s', (new_plan,))
            if not c.fetchone():
                return jsonify({'error': f'Invalid plan: {new_plan}'}), 400

            # Update user's plan
            c.execute('UPDATE users SET plan = %s WHERE id = %s', (new_plan, user_id))

            return jsonify({'message': f'User {user_id} plan updated to {new_plan}', 'new_plan': new_plan}), 200
    except Exception as e:
        print(f'[ERROR] /api/admin/users/{user_id}/plan: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/plans', methods=['GET'])
@limiter.limit("30/minute")
def admin_plans():
    """Get all available plans (admin only)"""
    try:
        token = get_auth_header()
        user_id = verify_token(token)
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401

        # Check if user is admin
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT is_admin FROM users WHERE id = %s', (user_id,))
            result = c.fetchone()
            if not result or not result[0]:
                return jsonify({'error': 'Forbidden: Admin access required'}), 403

            # Get all plans
            c.execute('SELECT plan_name, leads_per_month, exports_per_month, price_monthly, features FROM plan_limits ORDER BY price_monthly ASC')
            plans = []
            for row in c.fetchall():
                plans.append({
                    'name': row[0],
                    'leads_per_month': row[1],
                    'exports_per_month': row[2],
                    'price_monthly': float(row[3]) if row[3] else 0,
                    'features': row[4] if row[4] else {}
                })

            return jsonify({'plans': plans}), 200
    except Exception as e:
        print(f'[ERROR] /api/admin/plans: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/plans-stats', methods=['GET'])
def admin_plans_stats():
    """Get plans with user counts (admin only)"""
    try:
        token = get_auth_header()
        admin_id = verify_token(token)
        if not admin_id:
            return jsonify({'error': 'Unauthorized'}), 401

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT is_admin FROM users WHERE id = %s', (admin_id,))
            result = c.fetchone()
            if not result or not result[0]:
                return jsonify({'error': 'Forbidden: Admin access required'}), 403

            c.execute('''
                SELECT
                    pl.plan_name,
                    pl.leads_per_month,
                    pl.exports_per_month,
                    pl.price_monthly,
                    pl.features,
                    COUNT(u.id) AS user_count
                FROM plan_limits pl
                LEFT JOIN users u ON u.plan = pl.plan_name
                GROUP BY pl.plan_name, pl.leads_per_month, pl.exports_per_month, pl.price_monthly, pl.features
                ORDER BY pl.price_monthly ASC
            ''')
            plans = []
            for row in c.fetchall():
                plans.append({
                    'name': row[0],
                    'leads_per_month': row[1],
                    'exports_per_month': row[2],
                    'price_monthly': float(row[3]) if row[3] else 0,
                    'features': row[4] if row[4] else {},
                    'user_count': row[5]
                })

            return jsonify({'plans': plans}), 200
    except Exception as e:
        print(f'[ERROR] /api/admin/plans-stats: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/plans/<plan_name>', methods=['PUT'])
def admin_update_plan(plan_name):
    """Update plan limits (admin only)"""
    try:
        token = get_auth_header()
        admin_id = verify_token(token)
        if not admin_id:
            return jsonify({'error': 'Unauthorized'}), 401

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT is_admin FROM users WHERE id = %s', (admin_id,))
            result = c.fetchone()
            if not result or not result[0]:
                return jsonify({'error': 'Forbidden: Admin access required'}), 403

            # Validate plan name
            valid_plans = ['free', 'pro', 'enterprise']
            if plan_name not in valid_plans:
                return jsonify({'error': 'Invalid plan name'}), 400

            data = request.json or {}
            allowed_fields = ['leads_per_month', 'exports_per_month', 'price_monthly']
            updates = {k: v for k, v in data.items() if k in allowed_fields}

            if not updates:
                return jsonify({'error': 'No valid fields to update'}), 400

            set_clause = ', '.join([f'{k} = %s' for k in updates.keys()])
            values = list(updates.values()) + [plan_name]
            c.execute(f'UPDATE plan_limits SET {set_clause} WHERE plan_name = %s', values)
            conn.commit()

            # Return updated plan
            c.execute('SELECT plan_name, leads_per_month, exports_per_month, price_monthly, features FROM plan_limits WHERE plan_name = %s', (plan_name,))
            row = c.fetchone()
            if not row:
                return jsonify({'error': 'Plan not found'}), 404

            return jsonify({
                'plan': {
                    'name': row[0],
                    'leads_per_month': row[1],
                    'exports_per_month': row[2],
                    'price_monthly': float(row[3]) if row[3] else 0,
                    'features': row[4] if row[4] else {}
                }
            }), 200
    except Exception as e:
        print(f'[ERROR] /api/admin/plans/{plan_name}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users/<int:target_id>/reset-usage', methods=['POST'])
@limiter.limit("30/minute")
def admin_reset_user_usage(target_id):
    """Reset current month usage for a user (admin only)"""
    try:
        token = get_auth_header()
        admin_id = verify_token(token)
        if not admin_id:
            return jsonify({'error': 'Unauthorized'}), 401

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT is_admin FROM users WHERE id = %s', (admin_id,))
            result = c.fetchone()
            if not result or not result[0]:
                return jsonify({'error': 'Forbidden: Admin access required'}), 403

            month_year = _get_current_month_year()
            c.execute(
                '''INSERT INTO usage_tracking (user_id, month_year, leads_viewed, leads_exported, reset_at)
                   VALUES (%s, %s, 0, 0, %s)
                   ON CONFLICT (user_id, month_year)
                   DO UPDATE SET leads_viewed = 0, leads_exported = 0, reset_at = %s''',
                (target_id, month_year, datetime.now(), datetime.now())
            )
            return jsonify({'message': f'Usage reset for user {target_id}', 'month_year': month_year}), 200
    except Exception as e:
        print(f'[ERROR] /api/admin/users/{target_id}/reset-usage: {e}')
        return jsonify({'error': str(e)}), 500


# ============= Scheduler Setup =============
try:
    if _APSCHEDULER_AVAILABLE:
        _tz = pytz.timezone('America/Sao_Paulo')
        _scheduler = BackgroundScheduler(
            timezone=_tz,
            job_defaults={'misfire_grace_time': 3600, 'coalesce': True}
        )
        _scheduler.add_job(
            trigger_daily_pipeline,
            CronTrigger(hour=DAILY_JOB_HOUR, minute=0, timezone=_tz),
            id='daily_pipeline',
            replace_existing=True
        )
        _scheduler.add_job(
            trigger_daily_crm_sync,
            CronTrigger(hour=DAILY_CRM_SYNC_HOUR, minute=0, timezone=_tz),
            id='daily_crm_sync',
            replace_existing=True
        )
        _scheduler.start()
        print(f"[SCHEDULER] Pipeline diário agendado: {DAILY_JOB_HOUR:02d}:00 America/Sao_Paulo")
        print(f"[SCHEDULER] CRM sync diário agendado: {DAILY_CRM_SYNC_HOUR:02d}:00 America/Sao_Paulo")
    else:
        print("[SCHEDULER] APScheduler indisponível — instale: pip install APScheduler pytz")
except Exception as _sched_err:
    print(f"[SCHEDULER] Erro ao iniciar: {_sched_err}")
