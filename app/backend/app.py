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
import functools
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
            except Exception as _db_err:
                # DB write failed — emit to stderr so Gunicorn captures it
                import sys as _sys
                print(
                    f'[DB_LOG_WRITER_ERROR] failed to persist log: {_db_err!r} '
                    f'| level={level} provider={provider} msg={str(message)[:200]}',
                    file=_sys.stderr, flush=True
                )
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
    for secret_id in ('extratordedados/prod', 'tools/rapidapi', 'tools/serper', 'tools/apify', 'tools/zerobounce'):
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
            # Fallback: write directly to file logger so the error is never lost
            import logging as _logging
            _fb = _logging.getLogger('extrator')
            _fb.error('[QUEUE_FULL_FALLBACK] provider=%s query=%s msg=%s exc=%s',
                      provider, query, str(msg)[:200], exc_text[:200] if exc_text else '')


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
        # Fallback: write directly to rotating file log — never discard an ERROR
        import logging as _logging
        _fb = _logging.getLogger('extrator')
        _lvl = getattr(_logging, level.upper(), _logging.ERROR)
        _fb.log(_lvl, '[QUEUE_FULL_FALLBACK][%s] provider=%s query=%s msg=%s',
                error_type or 'unknown', provider, query, str(message)[:400])


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

import logging
import logging.handlers

# ============= Logging Setup =============
# Structured logging with levels — replaces print() for critical paths.
# Existing print() calls are still captured by Gunicorn stdout.
_log_formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)s %(name)s — %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('extrator')
logger.setLevel(logging.DEBUG)

# Console handler (Gunicorn captures stderr)
_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(_log_formatter)
logger.addHandler(_console_handler)

# Rotating file handler (errors only, 5MB × 3)
try:
    _file_handler = logging.handlers.RotatingFileHandler(
        'app_errors.log', maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8'
    )
    _file_handler.setLevel(logging.WARNING)
    _file_handler.setFormatter(_log_formatter)
    logger.addHandler(_file_handler)
except Exception:
    pass  # Non-fatal if log directory is not writable

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json
import hashlib
import secrets
try:
    import bcrypt as _bcrypt
    _BCRYPT_AVAILABLE = True
except ImportError:
    _BCRYPT_AVAILABLE = False
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

# Phase 2 — Lead Quality: email-validator, disposable-email-domains, phonenumbers
try:
    from email_validator import validate_email as _ev_validate, EmailNotValidError
    _EMAIL_VALIDATOR_AVAILABLE = True
except ImportError:
    _EMAIL_VALIDATOR_AVAILABLE = False
    _ev_validate = None
    EmailNotValidError = Exception

try:
    from disposable_email_domains import blocklist as _DISPOSABLE_BLOCKLIST
    _DISPOSABLE_BLOCKLIST_AVAILABLE = True
except ImportError:
    _DISPOSABLE_BLOCKLIST_AVAILABLE = False
    _DISPOSABLE_BLOCKLIST = set()

try:
    import phonenumbers
    from phonenumbers import PhoneNumberFormat, NumberParseException, PhoneNumberType
    _PHONENUMBERS_AVAILABLE = True
except ImportError:
    _PHONENUMBERS_AVAILABLE = False
    phonenumbers = None
    PhoneNumberFormat = None
    NumberParseException = Exception
    PhoneNumberType = None

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

try:
    import stripe as _stripe_sdk
    _STRIPE_AVAILABLE = True
except ImportError:
    _stripe_sdk = None
    _STRIPE_AVAILABLE = False

CORS(app, resources={r"/api/*": {"origins": [
    "https://extratordedados.com.br",
    "https://www.extratordedados.com.br",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]}})

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

from db_utils import DB_CONFIG, get_pool, get_db  # noqa: E402 — after Flask/limiter setup

def _validate_startup():
    """Validate required environment variables at startup. Logs warnings for missing values."""
    warnings = []
    if not os.environ.get('DB_PASSWORD'):
        warnings.append('DB_PASSWORD is not set — DB connections will use empty password')
    if not os.environ.get('ADMIN_PASSWORD'):
        warnings.append('ADMIN_PASSWORD is not set — admin account will have no password')
    if not os.environ.get('SECRET_KEY') and not os.environ.get('FLASK_SECRET_KEY'):
        warnings.append('SECRET_KEY/FLASK_SECRET_KEY not set — using insecure default')
    for w in warnings:
        logger.warning('[STARTUP] %s', w)
    if warnings:
        logger.warning('[STARTUP] %d configuration warning(s) — review environment variables', len(warnings))
    else:
        logger.info('[STARTUP] Environment validation passed')

_validate_startup()

ADMIN_USERNAME = "admin"
def _make_admin_hash():
    pw = os.environ.get('ADMIN_PASSWORD', '')
    if not pw:
        return ''
    if _BCRYPT_AVAILABLE:
        return _bcrypt.hashpw(pw.encode(), _bcrypt.gensalt()).decode()
    return hashlib.sha256(pw.encode()).hexdigest()
ADMIN_PASSWORD_HASH = _make_admin_hash()

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


def get_pipeline_config():
    """Read current pipeline config from DB. Falls back to module constants on any error.
    NOTE: This function is READ-ONLY. It does NOT update last_used_at.
    Call _mark_niches_used(names) / _mark_cities_used(names) separately after pipeline is triggered.
    Phase 9 addition: also reads next N cities from regions table (round-robin by last_used_at).
    This function is READ-ONLY — it does not advance the rotation (that is trigger_daily_pipeline's job).
    """
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM pipeline_config")
            rows = {k: json.loads(v) for k, v in cur.fetchall()}
            # Phase 8: read niches from catalog table (round-robin)
            n = int(rows.get('daily_niches_per_run', 20))
            cur.execute(
                "SELECT name FROM niches WHERE active = TRUE "
                "ORDER BY last_used_at ASC NULLS FIRST, priority ASC, id ASC "
                "LIMIT %s",
                (n,)
            )
            niche_rows = cur.fetchall()
            niches = [r[0] for r in niche_rows] if niche_rows else DAILY_JOB_NICHES
            # Phase 9: read next N cities from regions table (round-robin)
            n_cities = int(rows.get('daily_cities_per_run', 7))
            cur.execute(
                "SELECT city, state FROM regions WHERE active = TRUE "
                "ORDER BY last_used_at ASC NULLS FIRST, priority ASC, id ASC "
                "LIMIT %s",
                (n_cities,)
            )
            city_rows = cur.fetchall()
            cities = [{'city': r[0], 'state': r[1]} for r in city_rows] if city_rows else None
        return {
            'niches':               niches,
            'region':               rows.get('daily_region',    DAILY_JOB_REGION),
            'hour':                 int(rows.get('daily_hour',  DAILY_JOB_HOUR)),
            'minute':               int(rows.get('daily_minute', 0)),
            'notify_email':         rows.get('notify_email'),
            'healthcheck_url':      rows.get('healthcheck_url'),
            'daily_niches_per_run': n,
            'cities':               cities,
            'daily_cities_per_run': n_cities,
        }
    except Exception as e:
        print(f"[CONFIG] Erro ao ler pipeline_config: {e} — usando defaults")
        return {
            'niches':               DAILY_JOB_NICHES,
            'region':               DAILY_JOB_REGION,
            'hour':                 DAILY_JOB_HOUR,
            'minute':               0,
            'notify_email':         None,
            'healthcheck_url':      None,
            'daily_niches_per_run': 20,
            'cities':               None,
            'daily_cities_per_run': 7,
        }


def _mark_niches_used(names):
    """Update last_used_at for the given niche names. Called once per pipeline trigger.
    Safe to call with empty list (no-op). Errors are logged, not raised.
    """
    if not names:
        return
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE niches SET last_used_at = NOW() WHERE name = ANY(%s)",
                (names,)
            )
            conn.commit()
        print(f"[NICHES] Marked {len(names)} niches used: {names[:5]}{'...' if len(names) > 5 else ''}")
    except Exception as e:
        print(f"[NICHES] _mark_niches_used error (non-fatal): {e}")


def _mark_cities_used(city_names):
    """Update last_used_at for the given ASCII city names in the regions table.
    Called once per trigger_daily_pipeline() call, after city list is selected.
    Safe to call with empty list (no-op). Errors are logged, not raised.
    Uses the 'city' column (ASCII form), not 'name' (accented display form).
    """
    if not city_names:
        return
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE regions SET last_used_at = NOW() WHERE city = ANY(%s) AND state = 'ES'",
                (city_names,)
            )
            conn.commit()
        print(f"[REGIONS] Marked {len(city_names)} cities used: {city_names[:5]}{'...' if len(city_names) > 5 else ''}")
    except Exception as e:
        print(f"[REGIONS] _mark_cities_used error (non-fatal): {e}")


SKIP_DOMAINS = {
    # Redes sociais
    'facebook.com', 'instagram.com', 'twitter.com', 'x.com', 'linkedin.com',
    'youtube.com', 'tiktok.com', 'pinterest.com', 'reddit.com', 'threads.net',
    # Marketplaces e classificados
    'mercadolivre.com.br', 'olx.com.br', 'amazon.com.br', 'magazineluiza.com.br',
    'americanas.com.br', 'shopee.com.br', 'submarino.com.br', 'buscape.com.br',
    # Governo e enciclopédias
    'gov.br', 'wikipedia.org', 'wikimedia.org', 'wikidata.org',
    # Avaliações e diretórios genéricos
    'tripadvisor.com', 'tripadvisor.com.br', 'reclameaqui.com.br',
    'yelp.com', 'glassdoor.com', 'foursquare.com', 'zomato.com',
    # Motores de busca
    'google.com', 'google.com.br', 'bing.com', 'duckduckgo.com', 'yahoo.com',
    # Portais brasileiros (conteúdo editorial, não empresas)
    'uol.com.br', 'globo.com', 'terra.com.br', 'r7.com', 'ig.com.br',
    'msn.com', 'abril.com.br', 'veja.com.br', 'exame.com', 'valor.com.br',
    # Portais de notícias nacionais
    'g1.globo.com', 'ge.globo.com', 'gshow.globo.com', 'oglobo.globo.com',
    'folha.uol.com.br', 'estadao.com', 'estadao.com.br',
    'correiobraziliense.com.br', 'gazetaonline.com.br', 'agazeta.com.br',
    'tribunaonline.com.br', 'aquinoticias.com', 'seculodiario.com.br',
    # Sites de tecnologia e tech media (internacionais)
    'digitaltrends.com', 'techcrunch.com', 'theverge.com', 'engadget.com',
    'wired.com', 'gizmodo.com', 'cnet.com', 'zdnet.com', 'lifehacker.com',
    'tomsguide.com', 'pcmag.com', 'techradar.com', 'makeuseof.com',
    # Empresas internacionais que não são leads BR
    'thermofisher.com', 'mabtech.com', 'sigma-aldrich.com', 'merck.com',
    'cheyenne.org', 'clubic.com', 'businessinsider.com', 'markets.businessinsider.com',
    # Portais de finanças/mercado (não são empresas-alvo)
    'infomoney.com.br', 'investing.com', 'tradingview.com',
    'morningstar.com', 'bloomberg.com', 'reuters.com',
    # Agregadores educacionais
    'ifes.edu.br', 'uff.br', 'usp.br', 'unicamp.br', 'ufrj.br',
}

# Domínios de email irrelevantes para leads BR (empresas/sites não-alvo)
# Vai além do SKIP_DOMAINS — aplicado na validação de email
IRRELEVANT_EMAIL_DOMAINS = {
    'estadao.com', 'estadao.com.br', 'folha.com', 'globo.com',
    'digitaltrends.com', 'techcrunch.com', 'theverge.com', 'wired.com',
    'thermofisher.com', 'mabtech.com', 'cheyenne.org', 'clubic.com',
    'businessinsider.com', 'morningstar.com', 'bloomberg.com', 'reuters.com',
    'ifes.edu.br', 'instagram.local', 'linkedin.local', 'facebook.local',
    'noticiasdealava.eus', 'legacyschool.com.br',
    'generalblue.com', 'almanac.com', 'yankeepub.com', 'nber.org', 'nitrd.gov', 'stanford.edu', 'harvard.edu', 'mit.edu', 'lpl.com', 'trabajo.org',
}

# DDDs válidos no Brasil (ANATEL)
DDD_VALIDOS_BR = {
    '11', '12', '13', '14', '15', '16', '17', '18', '19',  # SP
    '21', '22', '24',                                        # RJ
    '27', '28',                                              # ES
    '31', '32', '33', '34', '35', '37', '38',               # MG
    '41', '42', '43', '44', '45', '46',                     # PR
    '47', '48', '49',                                        # SC
    '51', '53', '54', '55',                                  # RS
    '61',                                                    # DF
    '62', '64',                                              # GO
    '63',                                                    # TO
    '65', '66',                                              # MT
    '67',                                                    # MS
    '68',                                                    # AC
    '69',                                                    # RO
    '71', '73', '74', '75', '77',                           # BA
    '79',                                                    # SE
    '81', '87',                                              # PE
    '82',                                                    # AL
    '83',                                                    # PB
    '84',                                                    # RN
    '85', '88',                                              # CE
    '86', '89',                                              # PI
    '91', '93', '94',                                        # PA
    '92', '97',                                              # AM
    '95',                                                    # RR
    '96',                                                    # AP
    '98', '99',                                              # MA
}

# Sufixos/padrões que indicam empresa estrangeira
FOREIGN_COMPANY_PATTERNS = [
    r'\bInc\.?\b', r'\bLLC\b', r'\bLtd\.?\b', r'\bCO\s+LTD\b',
    r'\bGmbH\b', r'\bS\.A\.S\.?\b', r'\bCorp\.?\b', r'\bPLC\b',
    r'\bAG\b', r'\bNV\b', r'\bBV\b', r'\bSRL\b',
]
_FOREIGN_COMPANY_RE = re.compile('|'.join(FOREIGN_COMPANY_PATTERNS), re.IGNORECASE)

# Prefixos de busca que contaminam o campo city
_CITY_GARBAGE_RE = re.compile(
    r'^(?:escritório|escritorio|advogado|advocacia|clínica|clinica|dentista'
    r'|restaurante|padaria|hotel|pousada|escola|academia|farmácia|farmacia'
    r'|supermercado|mecânica|mecanica|salão|salao|pet\s*shop|imobiliária|imobiliaria'
    r'|contabilidade|psicólogo|psicologo|médico|medico|veterinário|veterinario'
    r'|[a-záéíóúàãõâêîôûç\s]+)\s+(?:em|in|de|do|da|no|na)\s+',
    re.IGNORECASE
)

# Máximo de leads com o mesmo domínio de email por batch
MAX_LEADS_PER_EMAIL_DOMAIN = 5

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

# SRC-04: Five query templates per niche+city for search engine coverage
SEARCH_QUERY_TEMPLATES = [
    "{niche} {city} contato",
    "{niche} {city} email",
    "{niche} {city} whatsapp",
    'site:*.com.br "{niche}" "{city}"',
    '"{niche}" "{city}" OR "{vizinha}"',
]

ES_NEIGHBORING_CITIES = {
    'Vitoria': 'Vila Velha',
    'Vila Velha': 'Vitoria',
    'Serra': 'Cariacica',
    'Cariacica': 'Serra',
    'Viana': 'Cariacica',
    'Guarapari': 'Anchieta',
    'Linhares': 'Colatina',
    'Colatina': 'Linhares',
    'Cachoeiro de Itapemirim': 'Marataizes',
}

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


# ── QUAL-02: Foreign TLD blocklist ────────────────────────────────────────────
_FOREIGN_TLD_BLOCKLIST = {
    '.com.ar', '.com.mx', '.com.co', '.co.uk', '.com.de',
    '.com.fr', '.com.it', '.com.jp', '.com.cn',
    '.es', '.pt', '.pl', '.ru', '.de', '.fr', '.it',
    '.nl', '.se', '.no', '.dk', '.fi', '.cz', '.hu', '.ro',
}

def _is_foreign_tld(domain: str) -> bool:
    """Returns True if domain ends with a foreign (non-BR, non-generic) TLD.
    Checks multi-part TLDs (e.g. .com.ar) before single TLDs to avoid false matches.
    Never blocks .com.br, .br, .io, .co, .net, .org, .app, .dev, .tech, .digital.
    QUAL-02 per Phase 7.
    """
    d = domain.lower().strip()
    # Multi-part TLDs must be checked first (e.g. .com.ar before .ar)
    for tld in sorted(_FOREIGN_TLD_BLOCKLIST, key=len, reverse=True):
        if d.endswith(tld):
            return True
    return False

# ── QUAL-03: Email slogan detector ───────────────────────────────────────────
_SLOGAN_VERBS = {
    'venha', 'fale', 'entre', 'contate', 'acesse',
    'clique', 'seja', 'descubra', 'aproveite', 'conheca', 'conhea',
}
_SAFE_EMAIL_PREFIXES = {
    'contato', 'atendimento', 'comercial', 'financeiro', 'suporte',
    'info', 'sac', 'vendas', 'marketing', 'rh', 'administrativo',
    'recepcao', 'secretaria', 'faleconosco', 'ouvidoria',
}

def _is_slogan_email(email: str) -> bool:
    """Conservative slogan email detector. Returns True ONLY for obvious slogans.
    Never rejects known generic prefixes (D-12). Threshold: conservative (D-10).
    QUAL-03 per Phase 7.
    """
    if '@' not in email:
        return False
    local = email.split('@')[0].lower().strip()
    # D-12: Always accept known generic/safe prefixes
    if local in _SAFE_EMAIL_PREFIXES:
        return False
    # D-11: Reject single action verb as the ENTIRE local part
    if local in _SLOGAN_VERBS:
        return True
    # D-10: Reject if 4+ words separated by hyphens/underscores AND contains action verb
    parts = re.split(r'[-_]', local)
    if len(parts) >= 4:
        for part in parts:
            if part in _SLOGAN_VERBS:
                return True
    return False

# ============= Phase 2: Lead Quality Functions =============

def validate_email_free(email: str) -> dict:
    """
    3-layer free email validation.
    Layer 1: RFC-compliant syntax (email-validator, check_deliverability=False — no DNS per-call).
    Layer 2: Disposable domain blocklist (instant, no network).
    Layer 3: MX record check — reuses existing _MX_CACHE + has_valid_mx().
    Returns: {valid: bool, normalized: str|None, reason: str|None, is_disposable: bool, is_free_provider: bool}
    """
    result = {'valid': False, 'normalized': None, 'reason': None,
              'is_disposable': False, 'is_free_provider': False}

    if not email:
        result['reason'] = 'empty_email'
        return result

    # Layer 1: RFC-compliant syntax (email-validator, no DNS)
    if _ev_validate is not None:
        try:
            info = _ev_validate(email, check_deliverability=False)
            result['normalized'] = info.normalized
        except EmailNotValidError as e:
            result['reason'] = f'invalid_syntax:{e}'
            return result
    else:
        # Fallback: basic regex check if email-validator not installed
        import re as _re_local
        if not _re_local.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email.strip()):
            result['reason'] = 'invalid_syntax:email-validator not installed'
            return result
        result['normalized'] = email.strip().lower()

    domain = result['normalized'].split('@')[1].lower()

    # Layer 2: Disposable blocklist (instant, no network)
    if domain in _DISPOSABLE_BLOCKLIST:
        result['is_disposable'] = True
        result['reason'] = 'disposable_domain'
        return result

    # Free provider flag (informational — not a disqualifier for B2B)
    _FREE_PROVIDERS = {'gmail.com', 'hotmail.com', 'yahoo.com', 'outlook.com', 'live.com',
                       'icloud.com', 'uol.com.br', 'bol.com.br', 'ig.com.br', 'terra.com.br',
                       'globo.com', 'r7.com', 'hotmail.com.br'}
    if domain in _FREE_PROVIDERS:
        result['is_free_provider'] = True

    # Layer 3: MX record — reuse existing _MX_CACHE + has_valid_mx()
    mx_ok = has_valid_mx(domain)
    if mx_ok is False:
        result['reason'] = f'no_mx_record:{domain}'
        return result
    # mx_ok is None means timeout/unknown — allow through

    result['valid'] = True
    return result


def normalize_phone_br(raw: str) -> dict:
    """
    Normalizes a Brazilian phone number using Google libphonenumber.
    Returns: {valid: bool, e164: str|None, national: str|None, type: str|None, whatsapp_id: str|None}
    Per Pitfall 5: FIXED_LINE_OR_MOBILE with 8-digit national number treated as landline.
    """
    result = {'valid': False, 'e164': None, 'national': None,
              'type': None, 'whatsapp_id': None}
    if not raw:
        return result

    if not _PHONENUMBERS_AVAILABLE or phonenumbers is None:
        # Fallback: use existing validate_phone_br
        norm, is_valid = validate_phone_br(raw)
        if is_valid:
            result['valid'] = True
            result['national'] = norm
            result['type'] = 'unknown'
        return result

    digits = ''.join(c for c in raw if c.isdigit())
    if digits.startswith('55') and len(digits) >= 12:
        parse_str = '+' + digits
    elif digits.startswith('0'):
        parse_str = '+55' + digits[1:]
    else:
        parse_str = '+55' + digits

    try:
        parsed = phonenumbers.parse(parse_str, 'BR')
    except NumberParseException:
        return result

    if not phonenumbers.is_valid_number(parsed):
        return result

    result['valid'] = True
    result['e164'] = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    result['national'] = phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL)

    num_type = phonenumbers.number_type(parsed)
    # Get national number string for Pitfall 5 check
    national_digits = str(parsed.national_number)

    if num_type == PhoneNumberType.MOBILE:
        result['type'] = 'mobile'
        digits_e164 = result['e164'].lstrip('+')
        result['whatsapp_id'] = f"{digits_e164}@c.us"
    elif num_type == PhoneNumberType.FIXED_LINE_OR_MOBILE:
        # Pitfall 5: 8-digit national number = legacy format, treat as landline
        if len(national_digits) == 8:
            result['type'] = 'landline'
        else:
            result['type'] = 'mobile'
            digits_e164 = result['e164'].lstrip('+')
            result['whatsapp_id'] = f"{digits_e164}@c.us"
    elif num_type == PhoneNumberType.FIXED_LINE:
        result['type'] = 'landline'
    elif num_type == PhoneNumberType.TOLL_FREE:
        result['type'] = 'toll_free'
    else:
        result['type'] = 'unknown'

    return result


def compute_lead_quality_score(lead: dict) -> dict:
    """
    6-dimension quality score → A/B/C/D/F grade + numeric 0-100 + freshness.
    Dimensions: email(30) + phone(20) + completeness(20) + freshness(15) + cnpj(10) + source(5)
    Returns: {score: int, grade: str, tier: str, freshness: int, breakdown: dict}
    """
    from datetime import datetime as _dt, timezone as _tz

    # --- EMAIL (30 pts) ---
    email = lead.get('email') or ''
    if not email:
        email_pts = 0
    else:
        ev = validate_email_free(email)
        if not ev['valid']:
            email_pts = 0
        elif ev['is_free_provider']:
            email_pts = 15
        else:
            email_pts = 30  # corporate + valid

    # --- PHONE (20 pts) ---
    phone = lead.get('phone') or ''
    if not phone:
        phone_pts = 0
    else:
        pn = normalize_phone_br(phone)
        if not pn['valid']:
            phone_pts = 0
        elif pn['type'] == 'mobile':
            phone_pts = 20
        elif pn['type'] == 'landline':
            phone_pts = 12
        else:
            phone_pts = 5

    # --- COMPLETENESS (20 pts) ---
    fields = {'company_name': 4, 'email': 3, 'phone': 3, 'website': 2,
              'city': 2, 'state': 2, 'cnpj': 2, 'category': 1, 'address': 1}
    completeness_pts = min(20, sum(pts for f, pts in fields.items() if lead.get(f)))

    # --- FRESHNESS (15 pts) ---
    ref = lead.get('last_verified_at') or lead.get('captured_at') or lead.get('extracted_at')
    if ref:
        if isinstance(ref, str):
            try:
                ref = _dt.fromisoformat(ref.replace('Z', '+00:00'))
            except Exception:
                ref = None
        if ref is not None:
            if getattr(ref, 'tzinfo', None) is None:
                ref = ref.replace(tzinfo=_tz.utc)
            days = (_dt.now(_tz.utc) - ref).days
            if days <= 60:     freshness = 100
            elif days <= 180:  freshness = 70
            elif days <= 365:  freshness = 40
            else:               freshness = 10
        else:
            freshness = 50
    else:
        freshness = 50  # unknown age
    freshness_pts = int(freshness * 0.15)

    # --- CNPJ ENRICHMENT (10 pts) ---
    cnpj_pts = 10 if lead.get('cnpj_enriched') else (5 if lead.get('cnpj') else 0)

    # --- SOURCE QUALITY (5 pts) ---
    source_map = {'google_maps': 5, 'directories': 4, 'search_engines': 3,
                  'api_enrichment': 4, 'imported': 2, 'website_crawl': 3}
    source_pts = source_map.get(lead.get('source', ''), 2)

    total = email_pts + phone_pts + completeness_pts + freshness_pts + cnpj_pts + source_pts
    total = max(0, min(100, total))

    if total >= 80:   grade = 'A'
    elif total >= 60: grade = 'B'
    elif total >= 40: grade = 'C'
    elif total >= 20: grade = 'D'
    else:             grade = 'F'

    # Map to legacy tier (backward compat)
    tier = 'premium' if grade in ('A', 'B') else ('medio' if grade == 'C' else 'basico')

    return {
        'score': total, 'grade': grade, 'tier': tier, 'freshness': freshness,
        'breakdown': {
            'email': email_pts, 'phone': phone_pts, 'completeness': completeness_pts,
            'freshness': freshness_pts, 'cnpj': cnpj_pts, 'source': source_pts,
        }
    }


def save_lead_to_db(conn, lead_data: dict) -> bool:
    """
    Single canonical function for inserting a lead into the leads table.
    Computes quality_grade + freshness_score before INSERT.
    Handles UniqueViolation (global email index) silently — returns False on duplicate.
    All extraction pipelines (batch scrape, search engines, google maps, directories,
    apify, instagram, linkedin, local_business_data) MUST call this function.
    Returns True if the lead was inserted, False if skipped (duplicate or error).
    """
    # ── Phase 7 quality guards ────────────────────────────────────────────────
    _email = (lead_data.get('email') or '').strip().lower()
    if _email and '@' in _email:
        _domain = _email.split('@')[-1]
        # QUAL-02: Reject foreign TLD emails
        if _is_foreign_tld(_domain):
            print(f"[QUAL-02] Rejecting foreign TLD: {_domain}")
            return False
        # QUAL-03: Reject slogan emails
        if _is_slogan_email(_email):
            print(f"[QUAL-03] Rejecting slogan email: {_email}")
            return False

    # QUAL-05: Normalize/null whatsapp field — invalid => None (lead still saved)
    _wa = (lead_data.get('whatsapp') or '').strip()
    if _wa:
        try:
            _wa_result = normalize_phone_br(_wa)
            if _wa_result.get('valid') and _wa_result.get('type') == 'mobile':
                lead_data['whatsapp'] = _wa_result.get('e164') or _wa_result.get('national') or _wa
            else:
                print(f"[QUAL-05] Nulling invalid whatsapp: {_wa}")
                lead_data['whatsapp'] = None
        except Exception as _wa_err:
            print(f"[QUAL-05] WhatsApp validation error (non-fatal): {_wa_err}")
            lead_data['whatsapp'] = None
    # ── End Phase 7 guards ────────────────────────────────────────────────────

    qs = compute_lead_quality_score(lead_data)

    # Merge scoring into lead_data for INSERT
    lead_data['quality_grade'] = qs['grade']
    lead_data['quality_score'] = qs['tier']
    lead_data['lead_score'] = qs['score']
    lead_data['freshness_score'] = qs['freshness']

    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO leads (
                batch_id, company_name, email, phone, website, source_url,
                city, state, category, source, instagram, facebook, linkedin,
                twitter, youtube, whatsapp, cnpj, address, crm_status, tags,
                notes, contact_name, quality_score, extra_data, cnpj_trade_name,
                cnpj_status, cnpj_cnae, cnpj_abertura, cnpj_porte, cnpj_qsa,
                cnpj_enriched, mx_valid, email_type, lead_score,
                quality_grade, freshness_score,
                email_pattern, team_members, pdf_emails_found
            ) VALUES (
                %(batch_id)s, %(company_name)s, %(email)s, %(phone)s, %(website)s,
                %(source_url)s, %(city)s, %(state)s, %(category)s, %(source)s,
                %(instagram)s, %(facebook)s, %(linkedin)s, %(twitter)s, %(youtube)s,
                %(whatsapp)s, %(cnpj)s, %(address)s, %(crm_status)s, %(tags)s,
                %(notes)s, %(contact_name)s, %(quality_score)s, %(extra_data)s,
                %(cnpj_trade_name)s, %(cnpj_status)s, %(cnpj_cnae)s, %(cnpj_abertura)s,
                %(cnpj_porte)s, %(cnpj_qsa)s, %(cnpj_enriched)s, %(mx_valid)s,
                %(email_type)s, %(lead_score)s,
                %(quality_grade)s, %(freshness_score)s,
                %(email_pattern)s, %(team_members)s, %(pdf_emails_found)s
            )
        """, {
            'batch_id': lead_data.get('batch_id'),
            'company_name': lead_data.get('company_name'),
            'email': lead_data.get('email'),
            'phone': lead_data.get('phone'),
            'website': lead_data.get('website'),
            'source_url': lead_data.get('source_url'),
            'city': lead_data.get('city'),
            'state': lead_data.get('state'),
            'category': lead_data.get('category'),
            'source': lead_data.get('source'),
            'instagram': lead_data.get('instagram'),
            'facebook': lead_data.get('facebook'),
            'linkedin': lead_data.get('linkedin'),
            'twitter': lead_data.get('twitter'),
            'youtube': lead_data.get('youtube'),
            'whatsapp': lead_data.get('whatsapp'),
            'cnpj': lead_data.get('cnpj'),
            'address': lead_data.get('address'),
            'crm_status': lead_data.get('crm_status', 'novo'),
            'tags': lead_data.get('tags', ''),
            'notes': lead_data.get('notes'),
            'contact_name': lead_data.get('contact_name'),
            'quality_score': qs['tier'],
            'extra_data': lead_data.get('extra_data'),
            'cnpj_trade_name': lead_data.get('cnpj_trade_name'),
            'cnpj_status': lead_data.get('cnpj_status'),
            'cnpj_cnae': lead_data.get('cnpj_cnae'),
            'cnpj_abertura': lead_data.get('cnpj_abertura'),
            'cnpj_porte': lead_data.get('cnpj_porte'),
            'cnpj_qsa': lead_data.get('cnpj_qsa'),
            'cnpj_enriched': lead_data.get('cnpj_enriched', False),
            'mx_valid': lead_data.get('mx_valid'),
            'email_type': lead_data.get('email_type'),
            'lead_score': qs['score'],
            'quality_grade': qs['grade'],
            'freshness_score': qs['freshness'],
            'email_pattern': lead_data.get('email_pattern'),
            'team_members': lead_data.get('team_members'),
            'pdf_emails_found': lead_data.get('pdf_emails_found', False),
        })
        conn.commit()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        err_str = str(e).lower()
        if 'unique' in err_str or 'duplicate' in err_str:
            return False  # duplicate — silent skip
        print(f"[save_lead_to_db] error: {e}")
        return False
    finally:
        c.close()


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


_RF_SITUACAO_MAP = {2: 'ativa', 3: 'suspensa', 4: 'inapta', 8: 'baixada'}


def enrich_from_rf_local(cnpj_raw):
    """
    Direct SQL lookup against cnpj_rf table (Receita Federal local data).
    Returns normalized enrichment dict or {} on miss/error.
    Target latency: <10ms. Never raises — all exceptions caught and logged.
    """
    cnpj = re.sub(r'\D', '', cnpj_raw or '')
    if len(cnpj) != 14:
        return {}
    try:
        import threading
        result_holder = [{}]
        exc_holder = [None]

        def _query():
            try:
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute(
                        '''SELECT razao_social, nome_fantasia, situacao,
                                  cnae_principal, logradouro, numero, complemento,
                                  bairro, cep, municipio_cod, uf, ddd1, telefone1,
                                  ddd2, telefone2, email, data_abertura, porte,
                                  matriz_filial
                           FROM cnpj_rf WHERE cnpj = %s''',
                        (cnpj,)
                    )
                    row = c.fetchone()
                    if row:
                        (razao_social, nome_fantasia, situacao,
                         cnae_principal, logradouro, numero, complemento,
                         bairro, cep, municipio_cod, uf, ddd1, telefone1,
                         ddd2, telefone2, email_rf, data_abertura, porte,
                         matriz_filial) = row
                        phone = None
                        if ddd1 and telefone1:
                            phone = str(ddd1) + str(telefone1)
                        address_parts = filter(None, [logradouro, numero, complemento, bairro])
                        result_holder[0] = {
                            'razao_social': razao_social,
                            'nome_fantasia': nome_fantasia,
                            'phone': phone,
                            'city': None,  # municipio_cod requires a lookup table
                            'state': uf,
                            'cep': cep,
                            'address': ' '.join(address_parts).strip() or None,
                            'cnae_code': cnae_principal,
                            'situacao': _RF_SITUACAO_MAP.get(situacao, str(situacao) if situacao else None),
                            'porte': str(porte) if porte else None,
                            'email_rf': email_rf,
                            'source': 'rf_local',
                        }
            except Exception as e:
                exc_holder[0] = e

        t = threading.Thread(target=_query, daemon=True)
        t.start()
        t.join(timeout=3)
        if t.is_alive():
            print(f"[rf_local] CNPJ {cnpj}: timeout after 3s")
            return {}
        if exc_holder[0]:
            print(f"[rf_local] CNPJ {cnpj}: {type(exc_holder[0]).__name__}: {exc_holder[0]}")
            return {}
        if result_holder[0]:
            print(f"[rf_local] CNPJ {cnpj}: {result_holder[0].get('razao_social')} | {result_holder[0].get('situacao')}")
        return result_holder[0]
    except Exception as e:
        print(f"[rf_local] CNPJ {cnpj}: unexpected error: {type(e).__name__}: {e}")
        return {}


def enrich_cnpj_with_fallback(cnpj_raw):
    """
    5-level CNPJ enrichment fallback chain.
    Returns on first success. Logs which level succeeded.
    Level 1: rf_local (SQL, no network, 3s timeout)
    Level 2: Minha Receita localhost:3000 (optional — skips silently if not running)
    Level 3: BrasilAPI (existing function, 8s timeout)
    Level 4: receitaws.com.br (3 req/min free, 8s timeout)
    Level 5: publica.cnpj.ws (8s timeout)
    """
    cnpj = re.sub(r'\D', '', cnpj_raw or '')
    if len(cnpj) != 14:
        return {}

    cnpj_fmt = f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"

    # Level 1: rf_local
    try:
        result = enrich_from_rf_local(cnpj)
        if result:
            print(f"[cnpj_fallback] hit level 1: rf_local")
            return result
    except Exception as e:
        print(f"[cnpj_fallback] level 1 error: {e}")

    # Level 2: Minha Receita localhost (optional — silently skip if not running)
    try:
        r = http_requests.get(
            f"http://localhost:3000/{cnpj_fmt}",
            timeout=3,
            headers={'Accept': 'application/json'}
        )
        if r.status_code == 200:
            d = r.json()
            if d.get('cnpj'):
                phone1 = re.sub(r'[^0-9]', '', d.get('telefone') or '')
                address_parts = filter(None, [
                    d.get('logradouro'), d.get('numero'),
                    d.get('complemento'), d.get('bairro')
                ])
                result = {
                    'razao_social': d.get('razao_social'),
                    'nome_fantasia': d.get('nome_fantasia'),
                    'phone': phone1 or None,
                    'city': d.get('municipio'),
                    'state': d.get('uf'),
                    'cep': d.get('cep'),
                    'address': ' '.join(address_parts).strip() or None,
                    'cnae_code': d.get('cnae_fiscal'),
                    'situacao': d.get('descricao_situacao_cadastral'),
                    'porte': d.get('porte'),
                    'email_rf': (d.get('email') or '').lower().strip() or None,
                    'source': 'minha_receita',
                }
                print(f"[cnpj_fallback] hit level 2: minha_receita")
                return result
    except Exception:
        pass  # Minha Receita not running is expected — silent skip

    # Level 3: BrasilAPI (existing function)
    try:
        result = enrich_cnpj_brasilapi(cnpj)
        if result:
            result['source'] = 'brasilapi'
            print(f"[cnpj_fallback] hit level 3: brasilapi")
            return result
    except Exception as e:
        print(f"[cnpj_fallback] level 3 error: {e}")

    # Level 4: receitaws.com.br (3 req/min free)
    try:
        r = http_requests.get(
            f"https://receitaws.com.br/v1/cnpj/{cnpj}",
            timeout=8,
            headers={'User-Agent': random.choice(USER_AGENTS), 'Accept': 'application/json'}
        )
        if r.status_code == 200:
            d = r.json()
            if d.get('status') != 'ERROR':
                phone1 = re.sub(r'[^0-9]', '', d.get('telefone') or '')
                address_parts = filter(None, [
                    d.get('logradouro'), d.get('numero'),
                    d.get('complemento'), d.get('bairro')
                ])
                result = {
                    'razao_social': d.get('nome'),
                    'nome_fantasia': d.get('fantasia'),
                    'phone': phone1 or None,
                    'city': d.get('municipio'),
                    'state': d.get('uf'),
                    'cep': re.sub(r'[^0-9]', '', d.get('cep') or ''),
                    'address': ' '.join(address_parts).strip() or None,
                    'cnae_code': d.get('cnae_fiscal'),
                    'situacao': d.get('situacao'),
                    'porte': d.get('porte'),
                    'email_rf': (d.get('email') or '').lower().strip() or None,
                    'source': 'receitaws',
                }
                print(f"[cnpj_fallback] hit level 4: receitaws")
                return result
    except Exception as e:
        print(f"[cnpj_fallback] level 4 error: {e}")

    # Level 5: publica.cnpj.ws
    try:
        r = http_requests.get(
            f"https://publica.cnpj.ws/cnpj/{cnpj}",
            timeout=8,
            headers={'User-Agent': random.choice(USER_AGENTS), 'Accept': 'application/json'}
        )
        if r.status_code == 200:
            d = r.json()
            estabelecimento = d.get('estabelecimento') or {}
            telefones = estabelecimento.get('telefones') or []
            phone1 = None
            if telefones:
                t0 = telefones[0]
                ddd = re.sub(r'[^0-9]', '', t0.get('ddd') or '')
                num = re.sub(r'[^0-9]', '', t0.get('numero') or '')
                phone1 = ddd + num if ddd and num else None
            endereco = estabelecimento.get('logradouro') or ''
            numero = estabelecimento.get('numero') or ''
            complemento = estabelecimento.get('complemento') or ''
            bairro = estabelecimento.get('bairro') or ''
            address_parts = filter(None, [endereco, numero, complemento, bairro])
            atividade = estabelecimento.get('atividade_principal') or {}
            result = {
                'razao_social': d.get('razao_social'),
                'nome_fantasia': estabelecimento.get('nome_fantasia'),
                'phone': phone1,
                'city': (estabelecimento.get('cidade') or {}).get('nome'),
                'state': (estabelecimento.get('estado') or {}).get('sigla'),
                'cep': re.sub(r'[^0-9]', '', estabelecimento.get('cep') or ''),
                'address': ' '.join(address_parts).strip() or None,
                'cnae_code': atividade.get('subclasse'),
                'situacao': (estabelecimento.get('situacao_cadastral') or '').lower() or None,
                'porte': d.get('porte'),
                'email_rf': (estabelecimento.get('email') or '').lower().strip() or None,
                'source': 'cnpj_ws',
            }
            print(f"[cnpj_fallback] hit level 5: cnpj_ws")
            return result
    except Exception as e:
        print(f"[cnpj_fallback] level 5 error: {e}")

    print(f"[cnpj_fallback] all 5 levels exhausted for CNPJ {cnpj}")
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

        # Add email column if not exists (migration for existing DBs)
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(320) UNIQUE")

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

        # Phase 2 — Lead Quality columns
        new_columns += [
            ('captured_at', 'TIMESTAMPTZ DEFAULT NOW()'),
            ('last_verified_at', 'TIMESTAMPTZ'),
            ('freshness_score', 'INTEGER DEFAULT 100'),
            ('quality_grade', 'CHAR(1)'),
        ]

        for col_name, col_type in new_columns:
            try:
                c.execute(f'ALTER TABLE leads ADD COLUMN IF NOT EXISTS {col_name} {col_type}')
            except Exception as _e:
                print(f"[init_db] ADD COLUMN {col_name}: {_e}")
                conn.rollback()

        # Phase 2: Backfill captured_at from extracted_at for pre-migration rows
        try:
            c.execute("UPDATE leads SET captured_at = extracted_at WHERE captured_at IS NULL")
        except Exception as e:
            print(f"[init_db] backfill captured_at: {e}")
            conn.rollback()

        # Phase 2: Dedup cross-batch — keep row with highest lead_score per real email
        # DRY-RUN first: log count before deleting
        try:
            c.execute("""
                SELECT COUNT(*) FROM (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY email
                                   ORDER BY COALESCE(lead_score, 0) DESC, id ASC
                               ) AS rn
                        FROM leads
                        WHERE email IS NOT NULL AND email != ''
                          AND email NOT LIKE '%@directory.local'
                          AND email NOT LIKE '%@instagram.local'
                          AND email NOT LIKE '%@linkedin.local'
                    ) ranked WHERE rn > 1
                ) dup
            """)
            dup_count = c.fetchone()[0]
            if dup_count > 0:
                print(f"[init_db] Phase 2 dedup: removing {dup_count} duplicate email rows")
                c.execute("""
                    DELETE FROM leads WHERE id IN (
                        SELECT id FROM (
                            SELECT id,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY email
                                       ORDER BY COALESCE(lead_score, 0) DESC, id ASC
                                   ) AS rn
                            FROM leads
                            WHERE email IS NOT NULL AND email != ''
                              AND email NOT LIKE '%@directory.local'
                              AND email NOT LIKE '%@instagram.local'
                              AND email NOT LIKE '%@linkedin.local'
                        ) ranked WHERE rn > 1
                    )
                """)
                print(f"[init_db] Phase 2 dedup: {c.rowcount} duplicate rows removed")
            else:
                print("[init_db] Phase 2 dedup: no duplicates found")
        except Exception as e:
            print(f"[init_db] Phase 2 dedup error: {e}")
            conn.rollback()

        # Phase 2: Drop old per-batch UNIQUE constraint, add global partial unique index
        try:
            c.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_batch_id_email_key")
        except Exception as e:
            print(f"[init_db] drop old constraint: {e}")
            conn.rollback()

        try:
            c.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_email_global
                  ON leads(email)
                  WHERE email IS NOT NULL
                    AND email != ''
                    AND email NOT LIKE '%@directory.local'
                    AND email NOT LIKE '%@instagram.local'
                    AND email NOT LIKE '%@linkedin.local'
            """)
        except Exception as e:
            print(f"[init_db] create global email index: {e}")
            conn.rollback()

        # Phase 3: cnpj_rf table — Receita Federal local lookup
        try:
            c.execute('''
                CREATE TABLE IF NOT EXISTS cnpj_rf (
                    cnpj            CHAR(14) PRIMARY KEY,
                    razao_social    TEXT,
                    nome_fantasia   TEXT,
                    situacao        SMALLINT,
                    cnae_principal  VARCHAR(7),
                    logradouro      TEXT,
                    numero          VARCHAR(10),
                    complemento     TEXT,
                    bairro          TEXT,
                    cep             VARCHAR(8),
                    municipio_cod   INTEGER,
                    uf              CHAR(2),
                    ddd1            VARCHAR(3),
                    telefone1       VARCHAR(9),
                    ddd2            VARCHAR(3),
                    telefone2       VARCHAR(9),
                    email           TEXT,
                    data_abertura   DATE,
                    porte           SMALLINT,
                    matriz_filial   SMALLINT
                )
            ''')
            # Partial indexes on active companies only (situacao=2 means ativa)
            c.execute('''
                CREATE INDEX IF NOT EXISTS idx_cnpj_rf_uf_municipio
                  ON cnpj_rf (uf, municipio_cod) WHERE situacao = 2
            ''')
            c.execute('''
                CREATE INDEX IF NOT EXISTS idx_cnpj_rf_cnae
                  ON cnpj_rf (cnae_principal) WHERE situacao = 2
            ''')
            print("[init_db] Phase 3: cnpj_rf table ready")
        except Exception as e:
            print(f"[init_db] Phase 3 cnpj_rf: {e}")
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

        # Pipeline config table — configurable niches, region, schedule
        c.execute('''CREATE TABLE IF NOT EXISTS pipeline_config (
            key        VARCHAR(100) PRIMARY KEY,
            value      TEXT         NOT NULL,
            updated_at TIMESTAMP    DEFAULT NOW()
        )''')
        c.execute('''
            INSERT INTO pipeline_config (key, value) VALUES
              ('daily_niches',         %s),
              ('daily_region',         %s),
              ('daily_hour',           %s),
              ('daily_minute',         '0'),
              ('notify_email',         'null'),
              ('healthcheck_url',      'null'),
              ('daily_niches_per_run', '10'),
              ('daily_cities_per_run', '7')
            ON CONFLICT (key) DO NOTHING
        ''', (
            json.dumps(DAILY_JOB_NICHES),
            json.dumps(DAILY_JOB_REGION),
            json.dumps(DAILY_JOB_HOUR),
        ))

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
        c.execute("ALTER TABLE system_logs ADD COLUMN IF NOT EXISTS fix_prompt TEXT")

        # error_type + extra_data columns on system_logs (v2 logs)
        c.execute("ALTER TABLE system_logs ADD COLUMN IF NOT EXISTS error_type VARCHAR(50)")
        c.execute("ALTER TABLE system_logs ADD COLUMN IF NOT EXISTS extra_data JSONB")
        c.execute('CREATE INDEX IF NOT EXISTS idx_system_logs_error_type ON system_logs(error_type)')

        # Custom niches table (user-saved niches for massive search)
        c.execute('''CREATE TABLE IF NOT EXISTS custom_niches (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(name)
        )''')

        # Phase 8: Niche catalog table
        c.execute('''CREATE TABLE IF NOT EXISTS niches (
            id           SERIAL PRIMARY KEY,
            name         VARCHAR(255) NOT NULL,
            category     VARCHAR(100) NOT NULL DEFAULT 'Outros',
            keywords     TEXT[]       DEFAULT '{}',
            active       BOOLEAN      DEFAULT TRUE,
            priority     INTEGER      DEFAULT 100,
            last_used_at TIMESTAMP,
            created_at   TIMESTAMP    DEFAULT NOW(),
            UNIQUE(name)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_niches_active ON niches(active)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_niches_last_used ON niches(last_used_at ASC NULLS FIRST)')

        # Phase 9: Regional expansion — ES cities table
        c.execute('''CREATE TABLE IF NOT EXISTS regions (
            id           SERIAL PRIMARY KEY,
            name         VARCHAR(255) NOT NULL,   -- Display name with accents, e.g. "Vitória"
            city         VARCHAR(255) NOT NULL,   -- ASCII form used in search queries, e.g. "Vitoria"
            state        VARCHAR(2)   NOT NULL DEFAULT 'ES',
            ibge_code    VARCHAR(10),             -- 7-digit IBGE code, e.g. "3205309"
            priority     INTEGER      DEFAULT 100,
            active       BOOLEAN      DEFAULT TRUE,
            last_used_at TIMESTAMP,
            created_at   TIMESTAMP    DEFAULT NOW(),
            UNIQUE(city, state)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_regions_active ON regions(active)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_regions_last_used ON regions(last_used_at ASC NULLS FIRST)')
        # Performance index for leads-per-city JOIN in GET /api/admin/regions
        c.execute('CREATE INDEX IF NOT EXISTS idx_leads_city_state ON leads(city, state)')

        # Migrate existing custom_niches rows (category = 'Outros', priority = 100)
        c.execute('''
            INSERT INTO niches (name, category, created_at)
            SELECT name, 'Outros', created_at FROM custom_niches
            ON CONFLICT (name) DO NOTHING
        ''')

        # Seed comprehensive niche catalog — 60+ niches, idempotent (ON CONFLICT DO NOTHING)
        # 10 categories × 6-10 niches = ~6-day rotation when daily_niches_per_run = 10
        _niche_catalog = [
            # Saúde (prioridade alta)
            ('clinica medica',          'Saude',        10),
            ('dentista',                'Saude',        10),
            ('clinica odontologica',    'Saude',        10),
            ('clinica veterinaria',     'Saude',        10),
            ('farmacia',                'Saude',        10),
            ('fisioterapia',            'Saude',        10),
            ('psicologo',               'Saude',        10),
            ('nutricao',                'Saude',        10),
            ('oftalmologia',            'Saude',        15),
            ('dermatologia',            'Saude',        15),
            ('ortopedia',               'Saude',        15),
            # Beleza
            ('salao de beleza',         'Beleza',       20),
            ('barbearia',               'Beleza',       20),
            ('estetica',                'Beleza',       20),
            ('manicure pedicure',       'Beleza',       20),
            ('spa',                     'Beleza',       25),
            ('studio de beleza',        'Beleza',       25),
            ('micropigmentacao',        'Beleza',       30),
            # Alimentação
            ('restaurante',             'Alimentacao',  30),
            ('pizzaria',                'Alimentacao',  30),
            ('hamburgueria',            'Alimentacao',  30),
            ('padaria',                 'Alimentacao',  30),
            ('sorveteria',              'Alimentacao',  35),
            ('cafeteria',               'Alimentacao',  35),
            ('lanchonete',              'Alimentacao',  35),
            ('churrascaria',            'Alimentacao',  35),
            ('sushi',                   'Alimentacao',  40),
            ('doceria',                 'Alimentacao',  40),
            # Automotivo
            ('mecanica',                'Automotivo',   40),
            ('auto pecas',              'Automotivo',   40),
            ('lava rapido',             'Automotivo',   45),
            ('funilaria',               'Automotivo',   45),
            ('vidros automotivos',      'Automotivo',   45),
            ('som automotivo',          'Automotivo',   50),
            # Serviços Gerais
            ('eletricista',             'Servicos',     50),
            ('encanador',               'Servicos',     50),
            ('ar condicionado',         'Servicos',     50),
            ('informatica',             'Servicos',     50),
            ('conserto celular',        'Servicos',     55),
            ('chaveiro',                'Servicos',     55),
            ('seguranca eletronica',    'Servicos',     55),
            ('dedetizacao',             'Servicos',     55),
            # Educação
            ('escola',                  'Educacao',     60),
            ('creche',                  'Educacao',     60),
            ('curso de ingles',         'Educacao',     60),
            ('auto escola',             'Educacao',     60),
            ('academia de musica',      'Educacao',     65),
            ('reforco escolar',         'Educacao',     65),
            # Imóveis e Construção
            ('imobiliaria',             'Imoveis',      70),
            ('construtora',             'Imoveis',      70),
            ('arquitetura',             'Imoveis',      70),
            ('reforma',                 'Imoveis',      75),
            ('marcenaria',              'Imoveis',      75),
            ('material de construcao',  'Imoveis',      75),
            # Pet
            ('pet shop',                'Pet',          80),
            ('banho e tosa',            'Pet',          80),
            # Fitness e Bem-Estar
            ('academia',                'Fitness',      85),
            ('crossfit',                'Fitness',      85),
            ('pilates',                 'Fitness',      85),
            ('yoga',                    'Fitness',      90),
            ('natacao',                 'Fitness',      90),
            # Jurídico e Financeiro
            ('advocacia',               'Juridico',     90),
            ('contabilidade',           'Juridico',     90),
            ('consultoria financeira',  'Juridico',     95),
            ('corretora de seguros',    'Juridico',     95),
            # Moda e Varejo
            ('loja de roupas',          'Varejo',      100),
            ('calcados',                'Varejo',      100),
            ('joalheria',               'Varejo',      100),
            ('otica',                   'Varejo',      100),
            ('perfumaria',              'Varejo',      100),
            # Hospedagem e Turismo
            ('hotel',                   'Turismo',     100),
            ('pousada',                 'Turismo',     100),
            ('agencia de viagens',      'Turismo',     100),
        ]
        c.executemany(
            "INSERT INTO niches (name, category, priority) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING",
            _niche_catalog
        )
        print(f"[INIT] Niche catalog seeded: {len(_niche_catalog)} entries (idempotent)")

        # enrichment_source column on search_jobs
        c.execute("ALTER TABLE search_jobs ADD COLUMN IF NOT EXISTS enrichment_source VARCHAR(30) DEFAULT 'scraping'")

        # SaaS Foundation: plan column on users
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS plan VARCHAR(20) DEFAULT 'free'")

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
        c.execute("ALTER TABLE batches ADD COLUMN IF NOT EXISTS is_shared BOOLEAN DEFAULT TRUE")
        # Backfill: ensure all existing batches are marked as shared
        c.execute("UPDATE batches SET is_shared = TRUE WHERE is_shared IS NULL")
        c.execute('CREATE INDEX IF NOT EXISTS idx_batches_is_shared ON batches(is_shared)')

        # Phase 4: Role column on users
        try:
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'client'")
        except Exception as _e:
            print(f"[init_db] ADD COLUMN role: {_e}")
            conn.rollback()

        # Phase 4: credits_per_month on plan_limits
        try:
            c.execute("ALTER TABLE plan_limits ADD COLUMN IF NOT EXISTS credits_per_month INTEGER DEFAULT 0")
        except Exception as _e:
            print(f"[init_db] ADD COLUMN credits_per_month: {_e}")
            conn.rollback()

        # Phase 4: Backfill role='admin' for existing admin users
        c.execute("UPDATE users SET role = 'admin' WHERE is_admin = TRUE AND role = 'client'")

        # Phase 4: Seed credits_per_month per plan (idempotent)
        c.execute("UPDATE plan_limits SET credits_per_month = 10 WHERE plan_name = 'free' AND credits_per_month = 0")
        c.execute("UPDATE plan_limits SET credits_per_month = 200 WHERE plan_name = 'pro' AND credits_per_month = 0")
        c.execute("UPDATE plan_limits SET credits_per_month = 999999 WHERE plan_name = 'enterprise' AND credits_per_month = 0")

        # Phase 4: credit_ledger table
        c.execute('''CREATE TABLE IF NOT EXISTS credit_ledger (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount INTEGER NOT NULL,
            operation VARCHAR(30) NOT NULL,
            ref_id INTEGER,
            balance_after INTEGER NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_credit_ledger_user ON credit_ledger(user_id, id DESC)')

        # Phase 4: user_lead_reveals table
        c.execute('''CREATE TABLE IF NOT EXISTS user_lead_reveals (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            revealed_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (user_id, lead_id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_user_lead_reveals_user ON user_lead_reveals(user_id)')

    # Phase 5: niche_requests and niche_request_votes tables
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS niche_requests (
                    id SERIAL PRIMARY KEY,
                    requester_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    niche VARCHAR(200) NOT NULL,
                    city VARCHAR(100),
                    state VARCHAR(2),
                    notes TEXT,
                    votes INTEGER NOT NULL DEFAULT 1,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    admin_notes TEXT,
                    leads_added INTEGER,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_niche_requests_status
                ON niche_requests(status, votes DESC)
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_niche_requests_user
                ON niche_requests(requester_user_id)
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS niche_request_votes (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    niche_request_id INTEGER NOT NULL REFERENCES niche_requests(id) ON DELETE CASCADE,
                    voted_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (user_id, niche_request_id)
                )
            """)
        print('[init_db] niche_requests and niche_request_votes tables ready')
    except Exception as e:
        print(f'[init_db] niche_requests tables warning: {e}')

    # Phase 6: saved_searches table — client portal notification subscriptions
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS saved_searches (
                    id               SERIAL PRIMARY KEY,
                    user_id          INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    name             VARCHAR(100) NOT NULL,
                    filters          JSONB NOT NULL DEFAULT '{}',
                    notify_enabled   BOOLEAN DEFAULT TRUE,
                    notify_email     VARCHAR(255),
                    last_notified_at TIMESTAMPTZ,
                    created_at       TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_id, name)
                )
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_saved_searches_user
                ON saved_searches(user_id)
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_saved_searches_notify
                ON saved_searches(notify_enabled, last_notified_at)
            """)
            conn.commit()
        print('[DB] saved_searches table ready')
    except Exception as e:
        print(f'[DB] saved_searches: {e}')

    # Phase 7: Email Campaigns / Marketing Automation tables
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS email_campaigns (
                    id              SERIAL PRIMARY KEY,
                    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    name            VARCHAR(255) NOT NULL,
                    status          VARCHAR(30) DEFAULT 'draft',
                    target_filter   JSONB DEFAULT '{}',
                    created_at      TIMESTAMPTZ DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS email_steps (
                    id              SERIAL PRIMARY KEY,
                    campaign_id     INTEGER REFERENCES email_campaigns(id) ON DELETE CASCADE,
                    step_num        INTEGER NOT NULL DEFAULT 1,
                    subject         VARCHAR(500) NOT NULL,
                    body_html       TEXT NOT NULL,
                    delay_days      INTEGER DEFAULT 0,
                    condition       VARCHAR(50) DEFAULT 'always',
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS email_sends (
                    id              SERIAL PRIMARY KEY,
                    campaign_id     INTEGER REFERENCES email_campaigns(id) ON DELETE CASCADE,
                    step_id         INTEGER REFERENCES email_steps(id) ON DELETE SET NULL,
                    lead_id         INTEGER REFERENCES leads(id) ON DELETE SET NULL,
                    email           VARCHAR(255) NOT NULL,
                    token           VARCHAR(64) UNIQUE NOT NULL,
                    provider        VARCHAR(30),
                    status          VARCHAR(20) DEFAULT 'pending',
                    sent_at         TIMESTAMPTZ,
                    opened_at       TIMESTAMPTZ,
                    clicked_at      TIMESTAMPTZ,
                    unsubscribed_at TIMESTAMPTZ,
                    error_msg       TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS email_events (
                    id              SERIAL PRIMARY KEY,
                    send_id         INTEGER REFERENCES email_sends(id) ON DELETE CASCADE,
                    event_type      VARCHAR(30) NOT NULL,
                    occurred_at     TIMESTAMPTZ DEFAULT NOW(),
                    metadata        JSONB DEFAULT '{}'
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS email_provider_usage (
                    id              SERIAL PRIMARY KEY,
                    provider        VARCHAR(30) NOT NULL,
                    usage_date      DATE NOT NULL DEFAULT CURRENT_DATE,
                    sends_count     INTEGER DEFAULT 0,
                    UNIQUE(provider, usage_date)
                )
            """)
            # Indexes
            c.execute("CREATE INDEX IF NOT EXISTS idx_email_sends_campaign ON email_sends(campaign_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_email_sends_token ON email_sends(token)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_email_sends_lead ON email_sends(lead_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_email_events_send ON email_events(send_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_email_steps_campaign ON email_steps(campaign_id, step_num)")
            # Migrations — add columns that may not exist in older deployments
            c.execute("ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS bounced_at TIMESTAMPTZ")
            c.execute("ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS bounce_type VARCHAR(20)")
            c.execute("ALTER TABLE email_campaigns ADD COLUMN IF NOT EXISTS from_name VARCHAR(200)")
            conn.commit()
        print('[DB] email_campaigns tables ready')
    except Exception as e:
        print(f'[DB] email_campaigns: {e}')

    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS image_gen_log (
                    id          SERIAL PRIMARY KEY,
                    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    prompt      TEXT NOT NULL,
                    model_key   VARCHAR(60),
                    model_id    VARCHAR(120),
                    url         TEXT,
                    cost_usd    NUMERIC(10,4),
                    elapsed_s   NUMERIC(6,2),
                    aspect_ratio VARCHAR(10),
                    operation   VARCHAR(20) DEFAULT 'generate',
                    error_msg   TEXT,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_image_gen_log_user ON image_gen_log(user_id, created_at DESC)")
            # Migrations for older image_gen_log schemas
            for col, defn in [
                ('url', 'TEXT'),
                ('model_id', 'VARCHAR(120)'),
                ('cost_usd', 'NUMERIC(10,4)'),
                ('elapsed_s', 'NUMERIC(6,2)'),
                ('aspect_ratio', 'VARCHAR(10)'),
                ('operation', "VARCHAR(20) DEFAULT 'generate'"),
                ('error_msg', 'TEXT'),
            ]:
                try:
                    c.execute(f"ALTER TABLE image_gen_log ADD COLUMN IF NOT EXISTS {col} {defn}")
                except Exception:
                    pass
            conn.commit()
        print('[DB] image_gen_log ready')
    except Exception as e:
        print(f'[DB] image_gen_log: {e}')

    with get_db() as conn:
        c = conn.cursor()

        # Insert admin user if not exists
        ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'xandeq@gmail.com')
        c.execute('SELECT id FROM users WHERE username = %s', (ADMIN_USERNAME,))
        existing_admin = c.fetchone()
        if not existing_admin:
            c.execute(
                'INSERT INTO users (username, email, password_hash, is_admin, created_at) VALUES (%s, %s, %s, %s, %s)',
                (ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD_HASH, True, datetime.now())
            )
        else:
            # Always sync admin email to ADMIN_EMAIL (idempotent migration)
            c.execute(
                'UPDATE users SET email = %s WHERE username = %s',
                (ADMIN_EMAIL, ADMIN_USERNAME)
            )

# ============= Auth =============

def hash_password(password):
    """Hash password using bcrypt (preferred) or SHA-256 fallback."""
    if _BCRYPT_AVAILABLE:
        return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()
    return hashlib.sha256(password.encode()).hexdigest()

def _check_password(password, stored_hash):
    """Verify password against stored hash. Supports bcrypt and legacy SHA-256.
    If legacy SHA-256 match is found, returns (True, new_bcrypt_hash) to trigger migration.
    Returns (valid: bool, new_hash: str|None)."""
    if stored_hash.startswith('$2b$') or stored_hash.startswith('$2a$'):
        if _BCRYPT_AVAILABLE:
            valid = _bcrypt.checkpw(password.encode(), stored_hash.encode())
        else:
            valid = False
        return valid, None
    # Legacy SHA-256 path — migrate to bcrypt on success
    sha_hash = hashlib.sha256(password.encode()).hexdigest()
    if sha_hash == stored_hash:
        new_hash = hash_password(password) if _BCRYPT_AVAILABLE else stored_hash
        return True, new_hash
    return False, None

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

# ============= Phase 4: RBAC + Credit Helpers =============

ROLE_HIERARCHY = {'admin': 3, 'operator': 2, 'client': 1}

def require_role(minimum_role):
    """Decorator: ensures authenticated user has at minimum the given role.
    Also accepts is_admin=True as equivalent to role='admin' for backward compat.
    Usage: @require_role('admin') or @require_role('client')
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            token = get_auth_header()
            user_id = verify_token(token)
            if not user_id:
                return jsonify({'error': 'Unauthorized'}), 401
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute('SELECT role, is_admin FROM users WHERE id = %s', (user_id,))
                row = cur.fetchone()
                user_role = row[0] if row else 'client'
                user_is_admin = row[1] if row else False
            # Backward compat: is_admin=True always grants admin-level access
            if user_is_admin:
                user_role = 'admin'
            if ROLE_HIERARCHY.get(user_role, 0) < ROLE_HIERARCHY.get(minimum_role, 999):
                return jsonify({'error': 'forbidden', 'required_role': minimum_role}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def deduct_credit(conn, user_id, operation, ref_id=None):
    """Atomically deduct 1 credit using SELECT FOR UPDATE.
    Must be called inside an open transaction (with conn: block).
    Returns (success: bool, new_balance: int).
    On success: inserts deduction row in credit_ledger.
    On failure (balance < 1): returns (False, current_balance) — caller returns 402.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT id, balance_after FROM credit_ledger
        WHERE user_id = %s ORDER BY id DESC LIMIT 1
        FOR UPDATE
    """, (user_id,))
    row = cur.fetchone()
    balance = row[1] if row else 0

    if balance < 1:
        return False, balance

    new_balance = balance - 1
    cur.execute("""
        INSERT INTO credit_ledger (user_id, amount, operation, ref_id, balance_after)
        VALUES (%s, -1, %s, %s, %s)
    """, (user_id, operation, ref_id, new_balance))
    return True, new_balance


def grant_monthly_credits():
    """APScheduler job: runs at 00:05 on the 1st of every month (America/Sao_Paulo).
    Grants each active user their plan's credits_per_month credit allocation.
    Double-fire guard: checks credit_ledger for a monthly_grant event in last 5 minutes.
    """
    print('[SCHEDULER] grant_monthly_credits: iniciando concessão mensal de créditos...')
    # Double-fire guard (2 Gunicorn workers may both fire)
    try:
        guard_conn = psycopg2.connect(**DB_CONFIG)
        guard_cur = guard_conn.cursor()
        guard_cur.execute("""
            SELECT COUNT(*) FROM credit_ledger
            WHERE operation = 'monthly_grant'
              AND created_at > NOW() - INTERVAL '5 minutes'
        """)
        recent = guard_cur.fetchone()[0]
        guard_conn.close()
        if recent > 0:
            print('[SCHEDULER] grant_monthly_credits: double-fire detectado, abortando.')
            return
    except Exception as _e:
        print(f'[SCHEDULER] grant_monthly_credits: erro no guard: {_e}')
        return

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        # Fetch all users with their plan's credit allocation
        cur.execute("""
            SELECT u.id, COALESCE(pl.credits_per_month, 0)
            FROM users u
            LEFT JOIN plan_limits pl ON u.plan = pl.plan_name
            WHERE COALESCE(pl.credits_per_month, 0) > 0
        """)
        rows = cur.fetchall()
        granted = 0
        for uid, credits_to_grant in rows:
            try:
                # Get current balance
                cur.execute(
                    'SELECT balance_after FROM credit_ledger WHERE user_id = %s ORDER BY id DESC LIMIT 1',
                    (uid,)
                )
                bal_row = cur.fetchone()
                current_balance = bal_row[0] if bal_row else 0
                new_balance = current_balance + credits_to_grant
                cur.execute("""
                    INSERT INTO credit_ledger (user_id, amount, operation, ref_id, balance_after)
                    VALUES (%s, %s, 'monthly_grant', NULL, %s)
                """, (uid, credits_to_grant, new_balance))
                granted += 1
            except Exception as _ue:
                print(f'[SCHEDULER] grant_monthly_credits: erro para user {uid}: {_ue}')
                try:
                    conn.rollback()
                except Exception:
                    pass
        conn.commit()
        conn.close()
        print(f'[SCHEDULER] grant_monthly_credits: {granted} usuários receberam créditos.')
    except Exception as e:
        print(f'[SCHEDULER] grant_monthly_credits: erro geral: {e}')


def mask_email(email):
    """Mask email for client portal. Example: john@gmail.com -> jo***@gmail.com
    Returns None if email is None or empty.
    """
    if not email:
        return None
    if '@' not in email:
        return email[:2] + '***'
    local, domain = email.split('@', 1)
    shown = local[:2] if len(local) >= 2 else local[0]
    return f"{shown}***@{domain}"


def mask_phone(phone):
    """Mask phone for client portal. Example: 27987655678 -> 279****5678
    Returns None if phone is None or fewer than 6 chars.
    Pattern: first 3 chars + '****' + last 4 chars.
    """
    if not phone or len(phone) < 6:
        return None
    return phone[:3] + '****' + phone[-4:]


def portal_lead_to_dict(row, revealed=False):
    """Serialize a lead row for the client portal response.
    row columns (positional): id, company_name, city, state, category,
                               email, phone, whatsapp, website, cnpj,
                               lead_score, quality_grade, source, captured_at
    NEVER exposes: crm_status, notes, batch_id, tags (internal operator fields).
    Returns masked values by default; unmasked if revealed=True.
    """
    lead_id, company_name, city, state, category = row[0], row[1], row[2], row[3], row[4]
    email, phone, whatsapp, website, cnpj = row[5], row[6], row[7], row[8], row[9]
    lead_score, quality_grade, source, captured_at = row[10], row[11], row[12], row[13]

    return {
        'id': lead_id,
        'company_name': company_name,
        'city': city,
        'state': state,
        'category': category,
        'email': email if revealed else mask_email(email),
        'phone': phone if revealed else mask_phone(phone),
        'whatsapp': whatsapp if revealed else mask_phone(whatsapp),
        'website': website,  # not gated — not sensitive per spec
        'cnpj': cnpj if revealed else (cnpj[:4] + '****' if cnpj else None),
        'lead_score': lead_score,
        'quality_grade': quality_grade,
        'source': source,
        'captured_at': captured_at.isoformat() if captured_at else None,
        'has_email': email is not None and email != '',
        'has_phone': phone is not None and phone != '',
        'has_whatsapp': whatsapp is not None and whatsapp != '',
        'has_website': website is not None and website != '',
        'has_cnpj': cnpj is not None and cnpj != '',
        'revealed': revealed,
    }


def _generate_csv_bytes(leads_dicts):
    """Generate CSV bytes from list of lead dicts (output of portal_lead_to_dict).
    Returns bytes object (utf-8-sig with BOM for Excel compatibility).
    None values are replaced with empty string.
    """
    import csv
    import io
    if not leads_dicts:
        return b''
    fieldnames = [
        'id', 'company_name', 'city', 'state', 'category',
        'email', 'phone', 'whatsapp', 'website', 'cnpj',
        'lead_score', 'quality_grade', 'source', 'captured_at',
        'has_email', 'has_phone', 'has_whatsapp', 'has_website', 'has_cnpj'
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    for lead in leads_dicts:
        row = {k: (v if v is not None else '') for k, v in lead.items()}
        writer.writerow(row)
    return output.getvalue().encode('utf-8-sig')


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


def validate_phone_br(phone):
    """
    Valida e normaliza telefone brasileiro.
    Retorna (phone_normalizado, is_valid).
    Rejeita DDDs inválidos, números muito curtos/longos e prefixos internacionais.
    """
    if not phone:
        return None, False
    p = str(phone).strip()
    # Remove caracteres não numéricos exceto +
    digits = re.sub(r'[^\d]', '', p)
    # Remove +55 ou 55 no início
    if digits.startswith('55') and len(digits) > 11:
        digits = digits[2:]
    # Prefixo internacional (00xx) — rejeitar
    if digits.startswith('00'):
        return None, False
    # Comprimento inválido
    if len(digits) < 8 or len(digits) > 11:
        return None, False
    # Extrai DDD (apenas se tem 10 ou 11 dígitos)
    if len(digits) >= 10:
        ddd = digits[:2]
        if ddd not in DDD_VALIDOS_BR:
            return None, False
    # Número só com dígitos iguais (11111111) — inválido
    if len(set(digits)) == 1:
        return None, False
    return p, True


def clean_city_name(city):
    """
    Remove prefixos de busca que contaminam o campo city.
    Ex: 'Escritório de Contabilidade em Vila Velha' → 'Vila Velha'
        'Advogado em São Paulo' → 'São Paulo'
    """
    if not city:
        return city
    city = city.strip()
    # Aplica regex de limpeza
    cleaned = _CITY_GARBAGE_RE.sub('', city).strip()
    # Se o resultado ficou muito curto ou vazio, mantém o original
    if len(cleaned) < 3:
        return city
    # Remove " - ES", " - SP" etc. no final
    cleaned = re.sub(r'\s*[-–]\s*[A-Z]{2}$', '', cleaned).strip()
    return cleaned


def is_foreign_company(company_name):
    """
    Detecta se a empresa é estrangeira por sufixos legais (Inc, LLC, Ltd, GmbH etc.).
    Retorna True se parecer empresa estrangeira.
    """
    if not company_name:
        return False
    return bool(_FOREIGN_COMPANY_RE.search(company_name))


def is_irrelevant_email_domain(email):
    """
    Verifica se o domínio do email é de um site irrelevante para leads BR
    (portais de notícias, tech media, empresas internacionais).
    """
    if not email or '@' not in email:
        return False
    domain = email.split('@')[-1].lower().strip()
    parts = domain.split('.')
    tld = parts[-1] if parts else ''
    if tld in ('edu', 'gov', 'mil') and not domain.endswith('.br'):
        return True
    tld = domain.split(".")[-1]
    if tld in ("edu", "gov", "mil") and not domain.endswith(".br"):
        return True
    return domain in IRRELEVANT_EMAIL_DOMAINS


def calculate_lead_score_numeric(lead_data):
    """
    Calcula score numérico 0-100 para o lead.
    Delegated to compute_lead_quality_score() for consistent 6-dimension scoring.
    Kept for backward compatibility — all callers continue to work unchanged.
    Retorna int 0-100.
    """
    return compute_lead_quality_score(lead_data).get('score', 0)


def calculate_quality_score(lead_data):
    """
    Calcula tier de qualidade do lead: basico, medio, premium.
    Delegated to compute_lead_quality_score() for consistent scoring.
    Kept for backward compatibility.
    """
    return compute_lead_quality_score(lead_data).get('tier', 'basico')


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
            # SRC-04: use pre-built query from orchestrator if provided
            query_override = job_data.get('query_override')
            if query_override:
                query = query_override
            else:
                # Fallback: original single-query build (backward compatibility)
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
                                inserted = save_lead_to_db(conn, {
                                    'batch_id': batch_id,
                                    'company_name': crawl_data['company_name'],
                                    'email': email,
                                    'phone': first_phone,
                                    'website': crawl_data['website'],
                                    'source_url': result_url,
                                    'source': 'search_engine',
                                    'instagram': crawl_data.get('instagram'),
                                    'facebook': crawl_data.get('facebook'),
                                    'linkedin': crawl_data.get('linkedin'),
                                    'twitter': crawl_data.get('twitter'),
                                    'youtube': crawl_data.get('youtube'),
                                    'whatsapp': crawl_data.get('whatsapp'),
                                    'cnpj': crawl_data.get('cnpj'),
                                    'address': crawl_data.get('address'),
                                    'city': crawl_data.get('city'),
                                    'state': crawl_data.get('state'),
                                    'category': niche,
                                })
                                if inserted:
                                    job_leads += 1
                                    print(f"[search] Lead inserido: {email}")

                        log_search(c, search_job_id, 'crawl_complete', url=result_url,
                                  message=f'{len(crawl_data["emails"])} emails, {len(crawl_data["phones"])} phones',
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
                        inserted = save_lead_to_db(conn, {
                            'batch_id': batch_id,
                            'company_name': company,
                            'email': dedup_email,
                            'phone': phone,
                            'website': website,
                            'source_url': website or '',
                            'source': f'diretorio_{dl.get("source", "br")}',
                            'address': dl.get('address'),
                            'city': city,
                            'state': state,
                            'category': niche,
                        })
                        if inserted:
                            dir_saved += 1
                            job_leads += 1

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

                            inserted = save_lead_to_db(conn, {
                                'batch_id': batch_id,
                                'company_name': company,
                                'email': email,
                                'phone': phone or None,
                                'website': f'https://{domain}',
                                'source_url': result_url,
                                'source': job_source,
                                'city': city,
                                'state': state,
                                'category': niche,
                                'contact_name': contact_name or None,
                                'extra_data': json.dumps({'position': api_lead.get('position', ''),
                                                          'confidence': api_lead.get('confidence', 0),
                                                          'source_api': source}),
                            })
                            if inserted:
                                saved_count += 1
                                job_leads += 1

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
                                        inserted = save_lead_to_db(conn, {
                                            'batch_id': batch_id,
                                            'company_name': crawl_data['company_name'],
                                            'email': email,
                                            'phone': first_phone,
                                            'website': crawl_data['website'],
                                            'source_url': result_url,
                                            'source': 'search_engine',
                                            'instagram': crawl_data.get('instagram'),
                                            'facebook': crawl_data.get('facebook'),
                                            'linkedin': crawl_data.get('linkedin'),
                                            'twitter': crawl_data.get('twitter'),
                                            'youtube': crawl_data.get('youtube'),
                                            'whatsapp': crawl_data.get('whatsapp'),
                                            'cnpj': crawl_data.get('cnpj'),
                                            'address': crawl_data.get('address'),
                                            'city': crawl_data.get('city'),
                                            'state': crawl_data.get('state'),
                                            'category': niche,
                                        })
                                        if inserted:
                                            job_leads += 1

                                log_search(c, search_job_id, 'scrape_done', url=result_url,
                                          message=f'Scraping de {domain}: {len(emails_found)} emails, empresa="{crawl_data.get("company_name", "?")}" ({crawl_duration}ms)',
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
                    save_lead_to_db(conn, {
                        'batch_id': batch_id,
                        'company_name': result['company_name'],
                        'email': email,
                        'phone': first_phone,
                        'website': result['website'],
                        'source_url': url,
                        'source': 'website_crawl',
                        'instagram': result.get('instagram'),
                        'facebook': result.get('facebook'),
                        'linkedin': result.get('linkedin'),
                        'twitter': result.get('twitter'),
                        'youtube': result.get('youtube'),
                        'whatsapp': result.get('whatsapp'),
                        'cnpj': result.get('cnpj'),
                        'address': result.get('address'),
                        'city': result.get('city'),
                        'state': result.get('state'),
                        'email_pattern': email_pattern_val,
                        'team_members': team_members_val,
                        'pdf_emails_found': pdf_emails_found,
                    })

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
@limiter.limit("20/minute")
def login():
    """Login endpoint — accepts email or username"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    # Accept 'email', 'username', or generic 'login' field
    login_field = data.get('email') or data.get('username') or data.get('login')
    password = data.get('password')

    if not login_field or not password:
        return jsonify({'error': 'Email/username and password required'}), 400

    with get_db() as conn:
        c = conn.cursor()
        # Try by email first, then by username (case-insensitive)
        c.execute(
            'SELECT id, password_hash, is_admin FROM users WHERE LOWER(email) = LOWER(%s) OR LOWER(username) = LOWER(%s)',
            (login_field, login_field)
        )
        user = c.fetchone()

    if not user:
        return jsonify({'error': 'Email ou senha incorretos'}), 401

    valid, new_hash = _check_password(password, user[1])
    if not valid:
        return jsonify({'error': 'Email ou senha incorretos'}), 401

    # Migrate legacy SHA-256 hash to bcrypt transparently
    if new_hash:
        try:
            with get_db() as _mconn:
                _mc = _mconn.cursor()
                _mc.execute('UPDATE users SET password_hash = %s WHERE id = %s', (new_hash, user[0]))
        except Exception:
            pass  # Migration failure is non-fatal

    token = create_session(user[0])
    return jsonify({'token': token, 'user_id': user[0], 'is_admin': user[2]})

@app.route('/api/logout', methods=['POST'])
@limiter.limit("20/minute")
def logout():
    """Revoke current session token server-side."""
    token = get_auth_header()
    if not token:
        return jsonify({'error': 'No token provided'}), 400
    with get_db() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM sessions WHERE token = %s', (token,))
    return jsonify({'message': 'Logged out successfully'})

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
            c.execute('SELECT id, username, is_admin, plan, role FROM users WHERE id = %s', (user_id,))
            row = c.fetchone()
            if not row:
                return jsonify({'error': 'User not found'}), 404
            return jsonify({
                'id': row[0],
                'username': row[1],
                'is_admin': row[2],
                'plan': row[3],
                'role': row[4] if row[4] else ('admin' if row[2] else 'client')
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
                    save_lead_to_db(conn, {
                        'batch_id': batch_id,
                        'company_name': lead.get('company_name'),
                        'email': lead.get('email'),
                        'phone': lead.get('phone'),
                        'website': lead.get('website'),
                        'address': lead.get('address'),
                        'city': city,
                        'state': state,
                        'source': 'google_maps',
                        'source_url': lead.get('website') or f"maps:{lead.get('company_name')}",
                    })

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
                    save_lead_to_db(conn, {
                        'batch_id': batch_id,
                        'company_name': lead.get('company_name'),
                        'email': lead.get('email'),
                        'phone': lead.get('phone'),
                        'website': lead.get('website'),
                        'instagram': lead.get('instagram'),
                        'city': city,
                        'state': state,
                        'source': 'instagram',
                        'source_url': lead.get('instagram'),
                    })

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
                    save_lead_to_db(conn, {
                        'batch_id': batch_id,
                        'company_name': lead.get('company_name'),
                        'linkedin': lead.get('linkedin'),
                        'address': lead.get('address'),
                        'city': city,
                        'state': state,
                        'source': 'linkedin',
                        'source_url': lead.get('linkedin'),
                    })

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
                                b.name as batch_name, l.batch_id, COALESCE(l.lead_score, 0) as lead_score,
                                l.source, l.quality_score, l.quality_grade
                         FROM leads l JOIN batches b ON l.batch_id = b.id
                         WHERE b.is_shared = TRUE'''

def _mask_dedup_email(email):
    """Return None for internal dedup placeholder emails (.local domains) — keep real emails."""
    if email and email.endswith('.local'):
        return None
    return email


def lead_row_to_dict(row):
    """Convert a lead row tuple to dict."""
    return {
        'id': row[0], 'company_name': row[1], 'email': _mask_dedup_email(row[2]), 'phone': row[3],
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
        'source': row[26] or '', 'quality_score': row[27] or 'basico',
        'quality_grade': row[28],  # Phase 2: quality grade (A/B/C/D/F), null until scoring runs
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
    quality = request.args.get('quality', '').strip()  # A | B | C | D | F (or legacy: premium | medio | basico)
    source_filter = request.args.get('source', '').strip()
    min_score = request.args.get('min_score', '').strip()
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

    # Filtro por grade de qualidade (A/B/C/D/F) ou tier legado (premium/medio/basico)
    if quality in ('A', 'B', 'C', 'D', 'F'):
        query += ' AND l.quality_grade = %s'
        params.append(quality)
    elif quality in ('premium', 'medio', 'basico'):
        query += ' AND l.quality_score = %s'
        params.append(quality)

    # Filtro por fonte de captura
    if source_filter:
        query += ' AND l.source = %s'
        params.append(source_filter)

    # Filtro por score mínimo numérico
    if min_score and min_score.isdigit():
        query += ' AND COALESCE(l.lead_score, 0) >= %s'
        params.append(int(min_score))

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
    is_admin = _is_admin_user(user_id)

    # Admins bypass usage limits entirely
    if is_admin:
        usage = {'leads_viewed': 0, 'leads_exported': 0}
        leads_limit = 999999
    else:
        usage = _get_usage_stats(user_id)
        leads_limit = limits['leads_per_month'] if limits else 100

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
            'leads_limit': leads_limit,
            'usage_percent': (usage['leads_viewed'] / leads_limit * 100) if leads_limit > 0 else 0
        }
    }

    # Increment view counter (skipped for admins via _increment_usage)
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
    if data.get('confirm') != 'DELETAR':
        return jsonify({'error': 'confirm: "DELETAR" é obrigatório para confirmar a exclusão irreversível'}), 400

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

    # 1b. Detectar empresa estrangeira pelo nome (Inc, LLC, Ltd, GmbH...)
    if is_foreign_company(lead.get('company_name') or ''):
        issues.append(f'foreign_company:{lead.get("company_name","")[:50]}')
        lead['crm_status'] = 'descartado'
        # Marca mas não apaga — deixa auto_sanitize_background decidir

    # 1c. Corrigir encoding de outros campos de texto
    for field in ('address', 'city', 'state', 'contact_name', 'notes'):
        val = lead.get(field)
        if val and isinstance(val, str):
            fixed = fix_text_encoding(val)
            if fixed != val:
                issues.append(f'encoding_corrected:{field}')
                lead[field] = fixed

    # 1d. Limpar cidade: extrair nome real de strings como "Escritório de X em Vitória"
    city = lead.get('city') or ''
    if city:
        cleaned_city = clean_city_name(city)
        if cleaned_city != city:
            issues.append(f'city_cleaned:{city[:40]}→{cleaned_city}')
            lead['city'] = cleaned_city

    # 1e. Smart title case em city e state
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
        # 2a. Domínio irrelevante (jornais, tech media, empresas internacionais)
        if is_irrelevant_email_domain(email):
            issues.append(f'irrelevant_domain:{email}')
            lead['email'] = None
        # 2b. Extensão de domínio ruim (scraping artifact)
        elif has_bad_domain_extension(email):
            issues.append(f'bad_domain_extension:{email}')
            lead['email'] = None
        # 2c. Domínio de spam/temporário
        elif is_spam_domain(email):
            issues.append(f'spam_domain:{email}')
            lead['email'] = None
        else:
            # 2d. Validação de qualidade via score
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

    # 3. Validar e normalizar telefone
    phone = lead.get('phone') or ''
    if phone:
        cleaned_phone, phone_valid = validate_phone_br(phone)
        if not phone_valid:
            issues.append(f'phone_invalid:{phone[:20]}')
            lead['phone'] = None
        else:
            lead['phone'] = cleaned_phone

    # 4. Recalcular quality_score (tier) e lead_score (numérico 0-100)
    lead['quality_score'] = calculate_quality_score(lead)
    lead['lead_score'] = calculate_lead_score_numeric(lead)

    # Lead é válido se tem pelo menos email ou telefone ou rede social
    has_contact = bool(lead.get('email') or lead.get('phone') or
                       lead.get('instagram') or lead.get('linkedin') or
                       lead.get('whatsapp'))

    # Empresa estrangeira sem contato BR = descartar
    if 'foreign_company' in ' '.join(issues) and not has_contact:
        return lead, issues, False

    return lead, issues, has_contact


# ── Phase 2 Lead Quality Endpoints (Wave 2 stubs — auth gates active) ────────

@app.route('/api/leads/validate-email-free', methods=['POST'])
def validate_email_free_endpoint():
    """Validate email using free methods (format + MX + disposable check)."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json() or {}
    email = (data.get('email') or '').strip()
    if not email:
        return jsonify({'error': 'email is required'}), 400
    result = validate_email_free(email)
    return jsonify(result), 200


@app.route('/api/leads/normalize-phone', methods=['POST'])
def normalize_phone_endpoint():
    """Normalize Brazilian phone number to E.164 format."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json() or {}
    phone = (data.get('phone') or '').strip()
    if not phone:
        return jsonify({'error': 'phone is required'}), 400
    result = normalize_phone_br(phone)
    return jsonify(result), 200


@app.route('/api/leads/validate-batch', methods=['POST'])
@limiter.limit("5 per hour")
def validate_batch_endpoint():
    """
    Run quality scoring over all leads in a batch (or all leads for admin).
    Recomputes quality_grade, quality_score, lead_score, freshness_score for each lead.
    Returns: {updated: int, errors: int, batch_id: int|null}
    """
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    batch_id = data.get('batch_id')

    try:
        # First check admin status if no batch_id
        if not batch_id:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
                row = c.fetchone()
                if not row or not row[0]:
                    return jsonify({'error': 'batch_id required for non-admin users'}), 400

        with get_db() as conn:
            c = conn.cursor()
            if batch_id:
                c.execute("SELECT id FROM leads WHERE batch_id = %s", (batch_id,))
            else:
                c.execute("SELECT id FROM leads")
            lead_ids = [r[0] for r in c.fetchall()]

        updated = 0
        errors = 0

        for lead_id in lead_ids:
            try:
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute("""
                        SELECT company_name, email, phone, website, city, state,
                               cnpj, category, address, source, cnpj_enriched,
                               captured_at, extracted_at, last_verified_at
                        FROM leads WHERE id = %s
                    """, (lead_id,))
                    row = c.fetchone()
                    if not row:
                        continue
                    lead_data = {
                        'company_name': row[0], 'email': row[1], 'phone': row[2],
                        'website': row[3], 'city': row[4], 'state': row[5],
                        'cnpj': row[6], 'category': row[7], 'address': row[8],
                        'source': row[9], 'cnpj_enriched': row[10],
                        'captured_at': row[11], 'extracted_at': row[12],
                        'last_verified_at': row[13],
                    }
                    qs = compute_lead_quality_score(lead_data)
                    c.execute("""
                        UPDATE leads
                        SET quality_grade = %s,
                            quality_score = %s,
                            lead_score = %s,
                            freshness_score = %s,
                            last_verified_at = NOW()
                        WHERE id = %s
                    """, (qs['grade'], qs['tier'], qs['score'], qs['freshness'], lead_id))
                updated += 1
            except Exception as e:
                errors += 1
                print(f"[validate-batch] lead {lead_id} error: {e}")

        return jsonify({
            'updated': updated,
            'errors': errors,
            'batch_id': batch_id,
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def validate_zerobounce(email: str) -> dict:
    """
    Validate a single email via ZeroBounce API v2.
    Requires tools/zerobounce secret in AWS SM (ZEROBOUNCE_API_KEY).
    Returns: {is_valid: bool, status: str|None, sub_status: str|None, did_you_mean: str|None, error: str|None}
    """
    api_key = resolve_secret_value(
        'ZEROBOUNCE_API_KEY',
        secret_ids=['tools/zerobounce'],
        env_keys=['ZEROBOUNCE_API_KEY'],
    )
    if not api_key or api_key == 'PLACEHOLDER_REPLACE_WITH_ACTUAL_KEY':
        return {'is_valid': False, 'status': None, 'sub_status': None,
                'did_you_mean': None, 'error': 'zerobounce_key_missing'}
    try:
        resp = requests.get(
            'https://api.zerobounce.net/v2/validate',
            params={'api_key': api_key, 'email': email, 'ip_address': ''},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            'is_valid': data.get('status') == 'valid',
            'status': data.get('status'),
            'sub_status': data.get('sub_status'),
            'did_you_mean': data.get('did_you_mean'),
            'error': None,
        }
    except Exception as e:
        return {'is_valid': False, 'status': None, 'sub_status': None,
                'did_you_mean': None, 'error': str(e)}


@app.route('/api/leads/<int:lead_id>/verify-email', methods=['POST'])
@limiter.limit("20 per hour")
def verify_lead_email(lead_id: int):
    """Verify a single lead email via ZeroBounce API. Updates last_verified_at and mx_valid."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT email FROM leads WHERE id = %s", (lead_id,))
        row = c.fetchone()
        if not row:
            return jsonify({'error': 'Lead not found'}), 404
        email = row[0]
        if not email:
            return jsonify({'error': 'Lead has no email address'}), 400

        zb = validate_zerobounce(email)
        if zb.get('error') == 'zerobounce_key_missing':
            return jsonify({'error': 'ZeroBounce API key not configured'}), 503

        is_valid = zb['is_valid']
        c.execute("""
            UPDATE leads
            SET last_verified_at = NOW(),
                mx_valid = %s
            WHERE id = %s
        """, (is_valid, lead_id))
        conn.commit()

        return jsonify({
            'lead_id': lead_id,
            'email': email,
            'is_valid': is_valid,
            'status': zb['status'],
            'sub_status': zb['sub_status'],
            'did_you_mean': zb['did_you_mean'],
        }), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        c.close()
        conn.close()


@app.route('/api/leads/<int:lead_id>/enrich-linkedin', methods=['POST'])
@limiter.limit("30 per hour")
def enrich_lead_linkedin(lead_id: int):
    """Enrich a lead's email via Prospeo Social URL API using their LinkedIn URL."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()

        c.execute("SELECT email, linkedin FROM leads WHERE id = %s", (lead_id,))
        row = c.fetchone()
        if not row:
            return jsonify({'error': 'Lead not found'}), 404

        current_email, linkedin_url = row[0], row[1]

        if not linkedin_url:
            return jsonify({'error': 'Lead sem LinkedIn URL'}), 400

        # Ensure Prospeo key is available before calling
        api_key = _get_prospeo_key()
        if not api_key:
            return jsonify({'error': 'Prospeo não configurado — adicione chave em tools/prospeo no AWS SM'}), 503

        try:
            enriched = enrich_linkedin_prospeo(linkedin_url)
        except ConfigError:
            return jsonify({'error': 'Créditos Prospeo esgotados este mês'}), 429

        if not enriched.get('email'):
            return jsonify({'enriched': False, 'message': 'Email não encontrado'}), 200

        email_value = enriched['email']
        email_type = enriched.get('email_type', '')
        email_status = enriched.get('email_status', '')

        # Only update if email is currently empty
        if not current_email:
            c.execute(
                "UPDATE leads SET email = %s, last_verified_at = NOW() WHERE id = %s",
                (email_value, lead_id)
            )

        return jsonify({
            'enriched': True,
            'email': email_value,
            'email_type': email_type,
            'email_status': email_status,
        }), 200


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
    if lead_ids and len(lead_ids) > 1000:
        return jsonify({'error': 'Máximo de 1000 leads por sanitização'}), 400

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

                # Phase 2: compute quality_grade using 6-dimension scorer
                qs = compute_lead_quality_score(lead)

                # Phase 2: normalize phone via normalize_phone_br for whatsapp field
                phone_val = lead.get('phone') or ''
                if phone_val:
                    pn_result = normalize_phone_br(phone_val)
                    if pn_result['valid']:
                        if pn_result['whatsapp_id'] and not lead.get('whatsapp'):
                            c.execute("UPDATE leads SET whatsapp = %s WHERE id = %s",
                                      (pn_result['whatsapp_id'], lead['id']))

                # Phase 2: validate email MX and mark mx_valid
                if new_email:
                    ev_result = validate_email_free(new_email)
                    if not ev_result['valid'] and (ev_result.get('reason') or '').startswith('no_mx_record'):
                        c.execute("UPDATE leads SET mx_valid = FALSE WHERE id = %s", (lead['id'],))

                c.execute(
                    '''UPDATE leads SET
                         email = %s,
                         company_name = %s,
                         address = %s,
                         city = %s,
                         quality_score = %s,
                         quality_grade = %s,
                         lead_score = %s,
                         freshness_score = %s,
                         last_verified_at = NOW(),
                         notes = %s,
                         updated_at = %s
                       WHERE id = %s''',
                    (new_email, new_company, new_address, new_city,
                     qs['tier'], qs['grade'], qs['score'], qs['freshness'],
                     new_notes, datetime.now(), lead['id'])
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


# ============= Segment Leads =============
# Classifies leads into segments based on tags, category keywords in company_name,
# CNPJ activity, and source. Updates leads.tags in-place.
# POST /api/leads/segment  { lead_ids?: [...], filters?: {...} }

_SEGMENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ('saude',       ['clínica', 'clinica', 'médico', 'medico', 'odonto', 'dentist', 'farmácia', 'farmacia', 'hospital', 'saúde', 'saude', 'nutrição', 'nutricao', 'fisio']),
    ('beleza',      ['salão', 'salao', 'estética', 'estetica', 'barbearia', 'cabeleire', 'manicure', 'spa', 'beleza', 'depilação']),
    ('educacao',    ['escola', 'colégio', 'colegio', 'curso', 'faculdade', 'universi', 'educação', 'educacao', 'ensino', 'treinamento']),
    ('alimentacao', ['restaurante', 'lanchonete', 'padaria', 'buffet', 'delivery', 'alimento', 'food', 'marmita', 'snack']),
    ('construcao',  ['construção', 'construcao', 'construtora', 'engenharia', 'reforma', 'arquiteto', 'imobiliária', 'imobiliaria', 'imóvel', 'imovel']),
    ('tecnologia',  ['tech', 'software', 'sistemas', 'ti ', 'tecnologia', 'digital', 'consultoria ti', 'desenvolvimento', 'startup']),
    ('varejo',      ['loja', 'comércio', 'comercio', 'varejo', 'boutique', 'mercado', 'supermercado', 'atacado']),
    ('servicos',    ['assessoria', 'consultoria', 'contabilidade', 'contábil', 'advocacia', 'advocado', 'advogado', 'juridico', 'jurídico', 'seguro', 'financeiro']),
    ('industria',   ['indústria', 'industria', 'fabricação', 'fabricacao', 'manufatura', 'fábrica', 'fabrica', 'distribuidora', 'atacadista']),
    ('logistica',   ['logística', 'logistica', 'transporte', 'frete', 'entrega', 'armazém', 'armazem', 'estoque']),
]


def _classify_segment(company_name: str, existing_tags: str) -> list[str]:
    """Return list of segment tags for a lead based on company_name."""
    cn_lower = (company_name or '').lower()
    assigned: list[str] = []
    for seg, keywords in _SEGMENT_KEYWORDS:
        if any(kw in cn_lower for kw in keywords):
            assigned.append(seg)
    return assigned


@app.route('/api/leads/segment', methods=['POST'])
@limiter.limit("5/minute")
def segment_leads():
    """
    Auto-classify leads into segments (tags) based on company_name keywords.
    Updates leads.tags in the database for selected or all user leads.
    Returns: { success, segmented, unchanged, breakdown: {seg: count} }
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    lead_ids = data.get('lead_ids', [])
    overwrite = bool(data.get('overwrite', False))  # if True, replace existing tags; else append

    with get_db() as conn:
        c = conn.cursor()

        if lead_ids:
            valid_ids = [int(x) for x in lead_ids if isinstance(x, (int, str)) and str(x).isdigit()]
            if not valid_ids:
                return jsonify({'success': False, 'error': 'No valid lead_ids provided'}), 400
            placeholders = ','.join(['%s'] * len(valid_ids))
            c.execute(
                f'''SELECT l.id, l.company_name, l.tags
                    FROM leads l
                    JOIN batches b ON b.id = l.batch_id
                    WHERE l.id IN ({placeholders}) AND b.user_id = %s''',
                valid_ids + [user_id]
            )
        else:
            c.execute(
                '''SELECT l.id, l.company_name, l.tags
                   FROM leads l
                   JOIN batches b ON b.id = l.batch_id
                   WHERE b.user_id = %s
                   ORDER BY l.id''',
                (user_id,)
            )

        rows = c.fetchall()

        if not rows:
            return jsonify({'success': False, 'error': 'No leads found'}), 404

        segmented = 0
        unchanged = 0
        breakdown: dict[str, int] = {}
        updates: list[tuple[str, int]] = []

        for lead_id, company_name, existing_tags in rows:
            new_segs = _classify_segment(company_name, existing_tags)
            if not new_segs:
                unchanged += 1
                continue

            # Merge or overwrite tags
            current = set(t.strip() for t in (existing_tags or '').split(',') if t.strip())
            if overwrite:
                merged = set(new_segs)
            else:
                merged = current | set(new_segs)

            new_tags_str = ','.join(sorted(merged))
            if new_tags_str == ','.join(sorted(current)):
                unchanged += 1
                continue

            updates.append((new_tags_str, lead_id))
            segmented += 1
            for seg in new_segs:
                breakdown[seg] = breakdown.get(seg, 0) + 1

        if updates:
            from psycopg2.extras import execute_batch
            execute_batch(
                c,
                'UPDATE leads SET tags = %s WHERE id = %s',
                updates,
                page_size=200
            )
            conn.commit()

    persist_system_log(
        'INFO', 'segment_leads', 'segment_leads',
        f'Segmented {segmented} leads for user {user_id}. Unchanged: {unchanged}',
        user_id=user_id, breakdown=breakdown
    )

    return jsonify({
        'success': True,
        'segmented': segmented,
        'unchanged': unchanged,
        'breakdown': breakdown,
        'message': f'{segmented} leads segmentados automaticamente'
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
            enrichment = enrich_cnpj_with_fallback(cnpj)
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

    # Count leads first to decide sync vs async
    try:
        with get_db() as _conn:
            _cur = _conn.cursor()
            _cur.execute('SELECT COUNT(*) FROM leads WHERE batch_id = %s', (batch_id,))
            lead_count = _cur.fetchone()[0]
    except Exception as e:
        return jsonify({'error': f'Falha ao contar leads: {e}'}), 500

    ASYNC_THRESHOLD = 1000

    if lead_count > ASYNC_THRESHOLD:
        # Large batch — run in background, return immediately
        def _run_dedup_bg(b_id=batch_id, thr=threshold):
            bg_conn = psycopg2.connect(**DB_CONFIG)
            try:
                dupes = fuzzy_deduplicate_leads(b_id, bg_conn, threshold=thr)
                print(f'[fuzzy-dedup] batch {b_id}: {dupes} duplicatas marcadas (async, {lead_count} leads)')
            except Exception as _e:
                print(f'[fuzzy-dedup] batch {b_id}: erro async — {_e}')
            finally:
                bg_conn.close()

        threading.Thread(target=_run_dedup_bg, daemon=True).start()
        return jsonify({
            'status': 'queued',
            'message': f'Deduplicação iniciada em background ({lead_count} leads). Resultado disponível nos logs.',
            'batch_id': batch_id,
            'lead_count': lead_count,
        })

    # Small batch — run synchronously
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        dupes = fuzzy_deduplicate_leads(batch_id, conn, threshold=threshold)
        return jsonify({'duplicates_marked': dupes, 'batch_id': batch_id, 'lead_count': lead_count})
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


# ---- METHOD 5: Outscraper Google Maps API ----
_outscraper_key_cache = None
_outscraper_key_failed = False

# ---- METHOD 6 (Phase 10): Foursquare Places API ----
_foursquare_key_cache = None
_foursquare_key_failed = False


def _get_foursquare_key():
    """Fetch Foursquare API key from env or AWS SM extratordedados/prod."""
    global _foursquare_key_cache, _foursquare_key_failed
    if _foursquare_key_cache:
        return _foursquare_key_cache
    if _foursquare_key_failed:
        return None
    _foursquare_key_cache = resolve_secret_value(
        'FOURSQUARE_API_KEY',
        secret_ids=['extratordedados/prod'],
        env_keys=['FOURSQUARE_API_KEY'],
        db_provider='foursquare',
    )
    if _foursquare_key_cache:
        return _foursquare_key_cache
    _foursquare_key_failed = True
    return None


def _get_outscraper_key():
    """Fetch Outscraper API key — resolve_secret_value with module-level cache (same as _get_serper_key)."""
    global _outscraper_key_cache, _outscraper_key_failed
    if _outscraper_key_cache:
        return _outscraper_key_cache
    if _outscraper_key_failed:
        return None
    _outscraper_key_cache = resolve_secret_value(
        'OUTSCRAPER_API_KEY',
        secret_ids=['tools/outscraper', 'extratordedados/prod'],
        env_keys=['OUTSCRAPER_API_KEY'],
        db_provider='outscraper',
    )
    if _outscraper_key_cache:
        return _outscraper_key_cache
    _outscraper_key_failed = True
    return None


# ---- METHOD 6: Prospeo Social URL API (LinkedIn → email) ----
_prospeo_key_cache = None
_prospeo_key_failed = False


def _get_prospeo_key():
    """Fetch Prospeo API key — resolve_secret_value with module-level cache (same as _get_serper_key)."""
    global _prospeo_key_cache, _prospeo_key_failed
    if _prospeo_key_cache:
        return _prospeo_key_cache
    if _prospeo_key_failed:
        return None
    _prospeo_key_cache = resolve_secret_value(
        'PROSPEO_API_KEY',
        secret_ids=['tools/prospeo', 'extratordedados/prod'],
        env_keys=['PROSPEO_API_KEY'],
        db_provider='prospeo',
    )
    if _prospeo_key_cache:
        return _prospeo_key_cache
    _prospeo_key_failed = True
    return None


def enrich_linkedin_prospeo(linkedin_url):
    """
    Enrich a LinkedIn profile URL to find email via Prospeo Social URL API.
    Returns {"email": ..., "email_type": ..., "email_status": ...} on success.
    Returns {} if email not found.
    Raises ConfigError on quota exhaustion (402) or missing key.
    Never raises on other errors.
    """
    api_key = _get_prospeo_key()
    if not api_key:
        raise ConfigError("[PROSPEO] API key não configurada — cadastre em prospeo.io e salve em AWS SM tools/prospeo")

    # Validate URL format
    if not (linkedin_url.startswith('https://www.linkedin.com/in/')
            or linkedin_url.startswith('https://linkedin.com/in/')):
        return {}

    try:
        resp = http_requests.post(
            'https://api.prospeo.io/social-url-enrichment',
            headers={'X-KEY': api_key, 'Content-Type': 'application/json'},
            json={'url': linkedin_url},
            timeout=10,
        )

        # Quota / billing errors
        if resp.status_code == 402 or 'credits' in resp.text.lower() or 'quota' in resp.text.lower():
            raise ConfigError("[PROSPEO] Créditos esgotados")

        if resp.status_code != 200:
            print(f"[prospeo] HTTP {resp.status_code} for {linkedin_url}")
            return {}

        data = resp.json()
        email_obj = data.get('response', {}).get('email') or data.get('email') or {}
        if isinstance(email_obj, dict):
            email_value = email_obj.get('value') or email_obj.get('email')
            email_type = email_obj.get('type', '')
            email_status = email_obj.get('verification', {}).get('status', '') if isinstance(email_obj.get('verification'), dict) else ''
        else:
            # Flat response structure
            email_value = data.get('email')
            email_type = data.get('type', '')
            email_status = data.get('status', '')

        if not email_value:
            print(f"[prospeo] {linkedin_url} → not found")
            return {}

        print(f"[prospeo] {linkedin_url} → {email_value}")
        return {
            'email': email_value,
            'email_type': email_type,
            'email_status': email_status,
        }

    except ConfigError:
        raise
    except Exception as e:
        print(f"[prospeo] Error enriching {linkedin_url}: {e}")
        return {}


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
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    contacts = data.get('contacts', [])
    if not isinstance(contacts, list):
        return jsonify({'error': '"contacts" deve ser uma lista'}), 400
    if len(contacts) == 0:
        return jsonify({'error': 'Nenhum contato para importar'}), 400
    if len(contacts) > 5000:
        return jsonify({'error': '"contacts" máximo de 5000 por importação'}), 400

    batch_name = str(data.get('batch_name') or '').strip()[:255]
    if not batch_name:
        batch_name = f'Importacao Texto - {datetime.now().strftime("%d/%m/%Y %H:%M")}'

    with get_db() as conn:
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

                inserted = save_lead_to_db(conn, {
                    'batch_id': batch_id,
                    'email': email or None,
                    'phone': phone or None,
                    'company_name': company or None,
                    'website': website or None,
                    'whatsapp': whatsapp or None,
                    'contact_name': contact_name or None,
                    'source_url': website or None,
                    'crm_status': 'novo',
                    'source': 'imported',
                })
                if inserted:
                    imported += 1
                else:
                    skipped += 1

            # Update batch count
            cur.execute("UPDATE batches SET total_urls = %s, total_leads = %s WHERE id = %s", (imported, imported, batch_id))
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
        for l in [x for x in leads if x.get('email')]:
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

    # Deduplicate by email + validate quality (reject malformed/low-score emails)
    seen_emails = {}
    unique_leads = []
    skipped_invalid = 0
    for lead in leads:
        raw_email = (lead.get('email') or '').strip()
        if not raw_email:
            skipped_invalid += 1
            continue
        # Run through normalize_email() — rejects disposable, aggregator, low-score, malformed
        clean_email = normalize_email(raw_email)
        if not clean_email:
            skipped_invalid += 1
            logger.warning('[send_to_crm] Rejecting lead id=%s — invalid/low-quality email: %s',
                           lead.get('id', '?'), raw_email)
            continue
        if clean_email in seen_emails:
            skipped_invalid += 1
            continue
        seen_emails[clean_email] = True
        lead['email'] = clean_email  # use normalised version
        unique_leads.append(lead)

    if not unique_leads:
        _log_send_to_crm_failure(
            user_id=user_id,
            filters=filters,
            lead_ids=lead_ids,
            crm_api_url=crm_api_url,
            error_message='No leads with valid emails found after quality filtering',
            status_code=404,
            stage='prepare_payload',
            total_leads=len(leads),
            source='backend',
        )
        return jsonify({
            'success': False,
            'error': f'Nenhum lead com email válido encontrado. {skipped_invalid} lead(s) rejeitados por email inválido ou baixa qualidade.',
            'sent_count': 0,
            'failed_count': 0,
            'skipped_invalid': skipped_invalid,
        }), 404

    # Format leads for CRM API — sanitize names before sending
    _GARBAGE_NAME_RE = re.compile(
        r'^(lead|n/?a|empresa|company|test|teste|client|cliente|desconhecido|sem nome|unknown|null|none|—|-)$',
        re.I
    )

    def _clean_crm_name(raw: str, fallback: str = '') -> str:
        """Strip encoding artifacts, collapse whitespace, title-case, reject garbage."""
        if not raw:
            return fallback
        name = raw.strip()
        # Fix common mojibake
        try:
            name = name.encode('latin-1').decode('utf-8')
        except Exception:
            pass
        # Collapse whitespace
        name = re.sub(r'\s+', ' ', name).strip()
        # Reject single-char or obvious garbage
        if len(name) < 2 or _GARBAGE_NAME_RE.match(name):
            return fallback
        return name[:100]

    customers = []
    for lead in unique_leads:
        raw_contact = (lead.get('contact_name') or '').strip()
        raw_company = (lead.get('company_name') or '').strip()
        contact_name = _clean_crm_name(raw_contact) or _clean_crm_name(raw_company) or 'Lead'
        company_name = _clean_crm_name(raw_company) or 'N/A'
        email = (lead.get('email') or '').strip()
        phone = lead.get('phone') or None
        whatsapp = lead.get('whatsapp') or None
        tags = lead.get('tags') or ''
        notes = lead.get('notes') or ''

        # Combine notes with tags for the CRM notes field
        combined_notes = f"{notes}{',' if notes and tags else ''}{tags}"

        customer = {
            'name': contact_name,
            'email': email,
            'phone': phone,
            'whatsApp': whatsapp,
            'companyName': company_name,
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
            try:
                result = response.json()
            except Exception:
                # CRM returned 2xx but body is not valid JSON — treat as full success
                result = {}
            sent_count = result.get('created', len(customers))
            failed_count = result.get('failed', 0)
            return jsonify({
                'success': True,
                'sent_count': sent_count,
                'failed_count': failed_count,
                'total_leads': len(unique_leads),
                'skipped_invalid': skipped_invalid,
                'message': f'Successfully sent {sent_count} leads to CRM'
                           + (f' ({skipped_invalid} skipped — invalid email)' if skipped_invalid else '')
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

    # --- Input validation ---
    niches = data.get('niches', [])
    if not isinstance(niches, list):
        return jsonify({'error': '"niches" deve ser uma lista'}), 400
    if len(niches) == 0:
        return jsonify({'error': 'Pelo menos um nicho é obrigatório'}), 400
    if len(niches) > 20:
        return jsonify({'error': '"niches" máximo de 20 nichos por busca'}), 400
    niches = [str(n).strip()[:200] for n in niches if str(n).strip()]
    if not niches:
        return jsonify({'error': 'Nichos inválidos após sanitização'}), 400

    try:
        max_pages = min(3, max(1, int(data.get('max_pages', 2))))
    except (TypeError, ValueError):
        return jsonify({'error': '"max_pages" deve ser um número inteiro entre 1 e 3'}), 400

    methods = data.get('methods')
    if methods is not None and not isinstance(methods, list):
        return jsonify({'error': '"methods" deve ser uma lista'}), 400
    if methods is None:
        methods = ['api_enrichment', 'search_engines', 'google_maps', 'directories', 'instagram', 'linkedin', 'serper_google', 'local_business_data', 'outscraper_maps', 'apple_maps', 'foursquare']

    # Parameters
    region_id = (data.get('region') or '').strip()
    city = (data.get('city') or '').strip()
    state = (data.get('state') or '').strip()
    # Semana 7: admin draft mode — batch starts unpublished (is_shared=FALSE)
    is_draft = bool(data.get('is_draft', False))
    # --- End validation ---

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
            # SRC-04: 5 templates × niches[:2] × cities[:1]
            total_jobs += min(2, len(niches)) * min(1, len(cities_to_search) or 1) * len(SEARCH_QUERY_TEMPLATES)
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
        if 'outscraper_maps' in methods:
            total_jobs += min(2, len(niches)) * min(2, len(cities_to_search))
        if 'apple_maps' in methods:
            total_jobs += min(2, len(niches)) * min(2, len(cities_to_search))
        if 'foursquare' in methods:
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
            # SRC-04: 5 templates per niche+city. Use niches[:2] x cities[:1] = 10 jobs max.
            se_niches = niches[:2]
            se_cities = cities_to_search[:1] if cities_to_search else [{'city': None, 'state': None, 'region': region_id}]
            for niche in se_niches:
                for city_data in se_cities:
                    city_val  = city_data.get('city')
                    state_val = city_data.get('state')
                    vizinha   = ES_NEIGHBORING_CITIES.get(city_val or '', city_val or '')
                    for tmpl in SEARCH_QUERY_TEMPLATES:
                        query_str = tmpl.format(
                            niche=niche,
                            city=city_val or '',
                            vizinha=vizinha,
                        ).strip()
                        c.execute(
                            '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                            (batch_id, user_id, niche, city_val, state_val,
                             city_data.get('region', region_id), max_pages, 'pending', 'duckduckgo', datetime.now())
                        )
                        search_engine_jobs.append({
                            'search_job_id': c.fetchone()[0],
                            'niche': niche,
                            'city': city_val,
                            'state': state_val,
                            'region': city_data.get('region', region_id),
                            'max_pages': max_pages,
                            'query_override': query_str,
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

        outscraper_jobs = []
        if 'outscraper_maps' in methods:
            # Free tier 500 records/month + limit=100 per job → cap at 4 jobs total (niches[:2] x cities[:2])
            for niche in niches[:2]:
                for city_data in cities_to_search[:2]:
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'outscraper_maps', datetime.now()))
                    outscraper_jobs.append({'search_job_id': c.fetchone()[0], 'niche': niche, 'city': city_data['city'], 'state': city_data['state']})

        apple_maps_jobs = []
        if 'apple_maps' in methods:
            for niche in niches[:2]:
                for city_data in cities_to_search[:2]:
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data.get('region', 'manual'), 1, 'pending', 'apple_maps', datetime.now()))
                    apple_maps_jobs.append({'search_job_id': c.fetchone()[0], 'niche': niche, 'city': city_data['city'], 'state': city_data['state']})

        foursquare_jobs = []
        if 'foursquare' in methods:
            _fsq_key = _get_foursquare_key()
            if not _fsq_key:
                scraper_log('WARNING', 'foursquare', f'batch={batch_id}', 'API key ausente — pulando foursquare')
            else:
                for niche in niches[:3]:
                    for city_data in cities_to_search[:2]:
                        c.execute(
                            '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                            (batch_id, user_id, niche, city_data['city'], city_data['state'],
                             city_data.get('region', 'manual'), 1, 'pending', 'foursquare', datetime.now()))
                        foursquare_jobs.append({
                            'search_job_id': c.fetchone()[0],
                            'niche': niche,
                            'city': city_data['city'],
                            'state': city_data['state'],
                        })

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

    # Thread 16: Outscraper Google Maps API (500 records/month free)
    if outscraper_jobs:
        threading.Thread(
            target=process_outscraper_massive,
            args=(batch_id, outscraper_jobs, user_id),
            daemon=True
        ).start()

    # Thread 17: Apple Maps (Playwright)
    if apple_maps_jobs:
        threading.Thread(
            target=process_apple_maps_massive,
            args=(batch_id, apple_maps_jobs, user_id),
            daemon=True
        ).start()

    # Thread 18: Foursquare Places API
    if foursquare_jobs:
        threading.Thread(
            target=process_foursquare_massive,
            args=(batch_id, foursquare_jobs, user_id),
            daemon=True
        ).start()

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
            'outscraper_maps': len(outscraper_jobs),
            'apple_maps': len(apple_maps_jobs),
            'foursquare': len(foursquare_jobs),
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


@_persist_thread_errors('outscraper')
def process_outscraper_massive(batch_id, jobs_data, user_id):
    """
    Processa jobs via Outscraper Google Maps API.
    Princípios de resiliência:
      - Retry 3x com backoff via _massive_retry por job
      - NUNCA lança exceção para fora — itera todos os jobs até o fim
      - Se quota excedida, marca restantes como skipped e encerra graciosamente
      - Loga cada falha no scraper_errors.log
    Free tier: 500 records/month.
    """
    from outscraper import ApiClient as OutscraperClient

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[OUTSCRAPER] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'outscraper', f'batch={batch_id}',
                f'Iniciando Outscraper Maps. {len(jobs_data)} jobs.')

    try:
        c = conn.cursor()
        total_saved    = 0
        quota_exceeded = False

        # Fetch API key once before the loop
        key = _get_outscraper_key()
        if not key:
            scraper_log('WARNING', 'outscraper', f'batch={batch_id}',
                        'API key não disponível — pulando todos os jobs')
            print('[OUTSCRAPER] API key ausente — marcando todos os jobs como quota_exceeded')
            for job_data in jobs_data:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', 'quota_exceeded', datetime.now(), job_data['search_job_id']))
                except Exception:
                    pass
            return

        client = OutscraperClient(api_key=key)

        for job_idx, job_data in enumerate(jobs_data):

            search_job_id = job_data['search_job_id']
            niche  = job_data['niche']
            city   = job_data['city']
            state  = job_data['state']
            query  = f"{niche} {city} {state}"

            # Parar graciosamente se quota esgotada
            if quota_exceeded:
                print(f"[OUTSCRAPER] Quota excedida — marcando job {search_job_id} como skipped")
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', 'quota_exceeded', datetime.now(), search_job_id))
                except Exception:
                    pass
                continue

            print(f"[OUTSCRAPER] Job {job_idx+1}/{len(jobs_data)}: {query}")

            try:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('running', datetime.now(), search_job_id))
                except Exception:
                    pass

                # SRC-03: limit 20→100 (5× more results per query, free tier 500/month)
                result, err = _massive_retry(
                    lambda q=query: client.google_maps_search(
                        [q], limit=100, language="pt", region="BR",
                        fields=["name", "phone", "email", "full_address", "site", "category"]
                    ),
                    provider='outscraper',
                    query=query
                )

                if result is not None:
                    # Outscraper returns list-of-lists: result[0] is the businesses for query[0]
                    raw_businesses = result[0] if (isinstance(result, list) and result) else []
                    leads = []
                    for biz in raw_businesses:
                        if not isinstance(biz, dict):
                            continue
                        leads.append({
                            'company_name': biz.get('name', ''),
                            'email':        biz.get('email', ''),
                            'phone':        biz.get('phone', ''),
                            'website':      biz.get('site', ''),
                            'address':      biz.get('full_address', ''),
                            'category':     niche,
                            'city':         city,
                            'state':        state,
                            'source':       'outscraper_maps',
                        })
                    leads_saved = _save_leads_to_batch(
                        c, conn, batch_id, leads, 'outscraper_maps', city, state, 'OUTSCRAPER'
                    )
                    total_saved += leads_saved
                    status  = 'completed'
                    err_msg = None
                    print(f"[OUTSCRAPER] Job {job_idx+1} OK: {leads_saved} leads salvos")
                    scraper_log('INFO', 'outscraper', query, f'Job concluído: {leads_saved} leads')
                else:
                    leads_saved = 0
                    status  = 'failed'
                    err_str = str(err)[:500] if err else 'Sem resultados após 3 tentativas'
                    err_msg = err_str
                    # Detectar quota excedida para não desperdiçar chamadas restantes
                    if err and ('429' in str(err).lower() or 'quota' in str(err).lower() or 'limit' in str(err).lower() or isinstance(err, ConfigError)):
                        quota_exceeded = True
                        reason = 'Config ausente (API key)' if isinstance(err, ConfigError) else 'Quota Outscraper excedida'
                        scraper_log('WARNING', 'outscraper', query,
                                    f'{reason} — parando thread graciosamente')
                    print(f"[OUTSCRAPER] Job {job_idx+1} FALHOU: {err_msg}")
                    scraper_log('WARNING', 'outscraper', query, f'Job falhou: {err_msg}')

                try:
                    c.execute(
                        'UPDATE search_jobs SET status=%s, finished_at=%s, total_leads=%s, error_message=%s WHERE id=%s',
                        (status, datetime.now(), leads_saved, err_msg, search_job_id)
                    )
                except Exception:
                    pass

            except Exception as e:
                scraper_log('ERROR', 'outscraper', query, f'Erro inesperado no job: {e}', e)
                print(f"[OUTSCRAPER] Erro inesperado job {search_job_id}: {e}")
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(e)[:500], datetime.now(), search_job_id))
                except Exception:
                    pass

            time.sleep(random.uniform(5, 10))

        scraper_log('INFO', 'outscraper', f'batch={batch_id}',
                    f'Thread finalizada. Total salvo: {total_saved} leads.')
        print(f"[OUTSCRAPER] Thread finalizada. batch={batch_id}, total={total_saved} leads")

    except Exception as e:
        scraper_log('CRITICAL', 'outscraper', f'batch={batch_id}',
                    f'Erro crítico na thread: {e}', e)
        print(f"[OUTSCRAPER] ERRO CRÍTICO: {e}")
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


@_persist_thread_errors('apple_maps')
def process_apple_maps_massive(batch_id, jobs_data, user_id):
    """
    Thread 17: Apple Maps via Playwright.
    - Retry 3x com backoff via _massive_retry
    - NUNCA para: itera todos os jobs até o fim
    - Free: sem cota de API (scraping web público)
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[APPLE_MAPS] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'apple_maps', f'batch={batch_id}',
                f'Iniciando Apple Maps. {len(jobs_data)} jobs.')
    try:
        c = conn.cursor()
        total_saved = 0
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            for job_idx, job_data in enumerate(jobs_data):
                search_job_id = job_data['search_job_id']
                niche = job_data['niche']
                city  = job_data['city']
                state = job_data['state']
                try:
                    c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                              ('processing', datetime.now(), search_job_id))
                    url = (f"https://maps.apple.com/?q={niche.replace(' ', '+')}+"
                           f"{city.replace(' ', '+')}%2C+{state}"
                           f"&near={city.replace(' ', '+')}")
                    page.goto(url, wait_until='networkidle', timeout=30000)
                    try:
                        page.wait_for_selector('.place-list-item', timeout=15000)
                    except PWTimeoutError:
                        snippet = page.content()[:500]
                        scraper_log('WARNING', 'apple_maps', f'batch={batch_id}',
                                    f'Selector timeout job {search_job_id}. DOM: {snippet}')
                        c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                                  ('paused', 'selector_timeout', datetime.now(), search_job_id))
                        time.sleep(random.uniform(10, 20))
                        continue

                    items = page.query_selector_all('.place-list-item')[:20]
                    leads = []
                    for item in items:
                        try:
                            name_el = item.query_selector('.place-name') or item.query_selector('h1')
                            name = name_el.inner_text().strip() if name_el else ''
                            phone_el = item.query_selector('a[href^="tel:"]')
                            phone = phone_el.get_attribute('href')[4:] if phone_el else ''
                            addr_el = item.query_selector('.place-subtitle')
                            address = addr_el.inner_text().strip() if addr_el else ''
                            if name:
                                leads.append({
                                    'company_name': name,
                                    'phone': phone,
                                    'address': address,
                                    'category': niche,
                                    'city': city,
                                    'state': state,
                                    'source': 'apple_maps',
                                })
                        except Exception:
                            pass

                    leads_saved = _save_leads_to_batch(c, conn, batch_id, leads,
                                                       'apple_maps', city, state, 'APPLE_MAPS')
                    total_saved += leads_saved
                    c.execute('UPDATE search_jobs SET status=%s, total_results=%s, total_leads=%s, finished_at=%s WHERE id=%s',
                              ('completed', len(items), leads_saved, datetime.now(), search_job_id))
                    print(f"[APPLE_MAPS] job {search_job_id} → {leads_saved} leads")
                except Exception as e:
                    scraper_log('ERROR', 'apple_maps', f'job={search_job_id}', str(e), e)
                    try:
                        c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                                  ('failed', str(e)[:200], datetime.now(), search_job_id))
                    except Exception:
                        pass
                time.sleep(random.uniform(10, 20))
            context.close()
            browser.close()
    except Exception as e:
        scraper_log('CRITICAL', 'apple_maps', f'batch={batch_id}', str(e), e)
    finally:
        conn.close()
    print(f"[APPLE_MAPS] Concluído. batch={batch_id}, total_saved={total_saved}")


def search_foursquare_places(niche, city, state, api_key, limit=50):
    """
    Call Foursquare Places API v3 search.
    Returns (list_of_lead_dicts, None) on success,
            (None, 'quota_exceeded') on HTTP 429,
            (None, error_str) on other errors.
    Free tier: 10,000 calls/month, 50 QPS.
    """
    import requests as http_requests_local
    url = "https://api.foursquare.com/v3/places/search"
    headers = {
        "Authorization": api_key,
        "Accept": "application/json"
    }
    params = {
        "query": niche,
        "near": f"{city}, {state}, Brazil",
        "limit": limit,
        "fields": "name,tel,website,location,categories"
    }
    try:
        resp = http_requests_local.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code == 429:
            return None, 'quota_exceeded'
        resp.raise_for_status()
        results = resp.json().get("results", [])
        leads = []
        for r in results:
            loc = r.get("location", {})
            leads.append({
                'company_name': r.get('name', ''),
                'phone': r.get('tel', ''),
                'website': r.get('website', ''),
                'address': loc.get('formatted_address', ''),
                'city': city,
                'state': state,
                'category': niche,
                'source': 'foursquare',
            })
        return leads, None
    except Exception as e:
        return None, str(e)


@_persist_thread_errors('foursquare')
def process_foursquare_massive(batch_id, jobs_data, user_id):
    """
    Thread 18: Foursquare Places API v3.
    - Retry 3x com backoff via _massive_retry
    - NUNCA para: itera todos os jobs até o fim
    - Free tier: 10,000 calls/month
    """
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"\n[FOURSQUARE] Iniciando. batch={batch_id}, jobs={len(jobs_data)}")
    scraper_log('INFO', 'foursquare', f'batch={batch_id}',
                f'Iniciando Foursquare Places. {len(jobs_data)} jobs.')
    try:
        c = conn.cursor()
        total_saved    = 0
        quota_exceeded = False

        key = _get_foursquare_key()
        if not key:
            scraper_log('WARNING', 'foursquare', f'batch={batch_id}',
                        'API key não disponível — pulando todos os jobs')
            print('[FOURSQUARE] API key ausente — marcando todos os jobs como quota_exceeded')
            for job_data in jobs_data:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', 'quota_exceeded', datetime.now(), job_data['search_job_id']))
                except Exception:
                    pass
            return

        for job_idx, job_data in enumerate(jobs_data):
            search_job_id = job_data['search_job_id']
            niche = job_data['niche']
            city  = job_data['city']
            state = job_data['state']

            if quota_exceeded:
                print(f"[FOURSQUARE] Quota excedida — marcando job {search_job_id} como skipped")
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', 'quota_exceeded', datetime.now(), search_job_id))
                except Exception:
                    pass
                continue

            try:
                c.execute('UPDATE search_jobs SET status=%s, started_at=%s WHERE id=%s',
                          ('processing', datetime.now(), search_job_id))
            except Exception:
                pass

            result, err = _massive_retry(
                lambda n=niche, ci=city, st=state: search_foursquare_places(n, ci, st, key),
                provider='foursquare',
                query=f"{niche} {city}"
            )

            if err == 'quota_exceeded':
                quota_exceeded = True
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', 'quota_exceeded', datetime.now(), search_job_id))
                except Exception:
                    pass
                continue

            if result is None:
                try:
                    c.execute('UPDATE search_jobs SET status=%s, error_message=%s, finished_at=%s WHERE id=%s',
                              ('failed', str(err)[:200], datetime.now(), search_job_id))
                except Exception:
                    pass
                time.sleep(random.uniform(3, 7))
                continue

            leads_saved = _save_leads_to_batch(c, conn, batch_id, result,
                                               'foursquare', city, state, 'FOURSQUARE')
            total_saved += leads_saved
            try:
                c.execute('UPDATE search_jobs SET status=%s, total_results=%s, total_leads=%s, finished_at=%s WHERE id=%s',
                          ('completed', len(result), leads_saved, datetime.now(), search_job_id))
            except Exception:
                pass
            print(f"[FOURSQUARE] job {search_job_id} → {leads_saved} leads")
            time.sleep(random.uniform(3, 7))

    except Exception as e:
        scraper_log('CRITICAL', 'foursquare', f'batch={batch_id}', str(e), e)
    finally:
        conn.close()
    print(f"[FOURSQUARE] Concluído. batch={batch_id}, total_saved={total_saved}")


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

            inserted = save_lead_to_db(conn, {
                'batch_id': batch_id,
                'company_name': company,
                'email': dedup_email,
                'phone': phone,
                'website': website,
                'address': address,
                'instagram': instagram_url,
                'linkedin': linkedin_url,
                'whatsapp': whatsapp,
                'city': city,
                'state': state,
                'source': source,
            })
            if inserted:
                saved += 1
        except Exception as e:
            print(f"[{provider.upper()}] Erro ao salvar lead: {e}")
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
        prospeo_credits_used = 0  # Per-run cap: max 75 to match Prospeo free tier

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

                    # Prospeo enrichment — only for leads with linkedin URL but no email
                    # Guard: max 75 credits per run (Prospeo free tier limit)
                    for lead in leads:
                        if not lead.get('email') and lead.get('linkedin') and prospeo_credits_used < 75:
                            try:
                                enriched = enrich_linkedin_prospeo(lead['linkedin'])
                                if enriched.get('email'):
                                    try:
                                        c.execute(
                                            "UPDATE leads SET email=%s, last_verified_at=NOW() WHERE batch_id=%s AND linkedin=%s AND email IS NULL",
                                            (enriched['email'], batch_id, lead['linkedin'])
                                        )
                                        prospeo_credits_used += 1
                                    except Exception:
                                        pass
                            except ConfigError:
                                print("[prospeo] Quota esgotada — parando enrichment para este job")
                                prospeo_credits_used = 75  # stop further calls

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
    if email.endswith('.local'):
        return False, "Email interno (dedup placeholder) — não enviado ao CRM", None

    # QUAL-04: Check local cache before hitting CRM API
    _email_normalized = email.strip().lower()
    if _email_normalized:
        try:
            _cache_conn = psycopg2.connect(**DB_CONFIG)
            _cache_c = _cache_conn.cursor()
            _cache_c.execute(
                "SELECT id FROM crm_sent_leads WHERE LOWER(email) = LOWER(%s)",
                (_email_normalized,)
            )
            _cached = _cache_c.fetchone()
            _cache_c.close()
            _cache_conn.close()
            if _cached:
                print(f"[QUAL-04] Cache hit — skipping CRM sync for: {_email_normalized}")
                return True, "Lead already in CRM cache (skipped)", None
        except Exception as _cache_err:
            print(f"[QUAL-04] Cache read error (non-fatal, continuing): {_cache_err}")
            # Fall through to API check

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
            # QUAL-04: Record in local cache after successful CRM sync
            try:
                _write_conn = psycopg2.connect(**DB_CONFIG)
                _write_c = _write_conn.cursor()
                _write_c.execute(
                    """INSERT INTO crm_sent_leads (email, phone, whatsapp, crm_id)
                       VALUES (LOWER(%s), %s, %s, %s)
                       ON CONFLICT (LOWER(email)) DO NOTHING""",
                    (
                        _email_normalized,
                        (lead_data.get('phone') or '')[:50] or None,
                        (lead_data.get('whatsapp') or '')[:50] or None,
                        str(customer_id) if customer_id else None,
                    )
                )
                _write_conn.commit()
                _write_c.close()
                _write_conn.close()
            except Exception as _write_err:
                print(f"[QUAL-04] Cache write error (non-fatal): {_write_err}")
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
                # All jobs done → count real leads and mark batch completed
                try:
                    c.execute("SELECT COUNT(*) FROM leads WHERE batch_id=%s", (batch_id,))
                    real_count = c.fetchone()[0]
                    c.execute(
                        "UPDATE batches SET status='completed', total_leads=%s WHERE id=%s AND status='processing'",
                        (real_count, batch_id)
                    )
                    conn.commit()
                    print(f"[MONITOR] Batch {batch_id} marked as completed — {real_count} leads")
                except Exception as e:
                    print(f"[MONITOR] Error marking batch completed: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                return
        print(f"[MONITOR] Timeout waiting for batch {batch_id} — marking completed anyway")
        try:
            c.execute("SELECT COUNT(*) FROM leads WHERE batch_id=%s", (batch_id,))
            real_count = c.fetchone()[0]
            c.execute(
                "UPDATE batches SET status='completed', total_leads=%s WHERE id=%s AND status='processing'",
                (real_count, batch_id)
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
            domain_counts = {}  # domínio → lista de (lead_id, lead_score)
            sanitized_leads = []

            # Pass 1: sanitizar cada lead
            for lead in leads_raw:
                sanitized, issues, has_contact = sanitize_single_lead(lead)
                if not has_contact:
                    ids_to_delete.append(lead['id'])
                    continue
                sanitized_leads.append(sanitized)

            # Pass 2: dedup por email exato dentro do batch
            after_email_dedup = []
            for sanitized in sanitized_leads:
                email = (sanitized.get('email') or '').strip().lower()
                if email:
                    if email in seen_emails:
                        existing = seen_emails[email]
                        existing_score = existing.get('lead_score') or 0
                        new_score = sanitized.get('lead_score') or 0
                        if new_score > existing_score:
                            ids_to_delete.append(existing['id'])
                            seen_emails[email] = sanitized
                        else:
                            ids_to_delete.append(sanitized['id'])
                        continue
                    else:
                        seen_emails[email] = sanitized
                after_email_dedup.append(sanitized)

            # Pass 3: limite por domínio de email (máx MAX_LEADS_PER_EMAIL_DOMAIN por batch)
            final_leads = []
            for sanitized in after_email_dedup:
                email = (sanitized.get('email') or '').strip().lower()
                domain = email.split('@')[-1] if '@' in email else '__no_email__'
                lead_score = sanitized.get('lead_score') or 0

                if domain not in domain_counts:
                    domain_counts[domain] = []
                domain_counts[domain].append((sanitized['id'], lead_score, sanitized))

            for domain, entries in domain_counts.items():
                if domain == '__no_email__' or len(entries) <= MAX_LEADS_PER_EMAIL_DOMAIN:
                    final_leads.extend(e[2] for e in entries)
                else:
                    # Ordenar por score desc, manter os melhores
                    entries.sort(key=lambda x: x[1], reverse=True)
                    kept = entries[:MAX_LEADS_PER_EMAIL_DOMAIN]
                    dropped = entries[MAX_LEADS_PER_EMAIL_DOMAIN:]
                    final_leads.extend(e[2] for e in kept)
                    ids_to_delete.extend(e[0] for e in dropped)
                    print(f"[SANITIZE] Domain limit: {domain} → kept {len(kept)}, dropped {len(dropped)}")

            # Pass 4: atualizar leads válidos (com lead_score numérico)
            updated = 0
            for lead in final_leads:
                try:
                    c.execute(
                        '''UPDATE leads SET
                            company_name = %s, email = %s, phone = %s, website = %s,
                            address = %s, city = %s, state = %s, contact_name = %s,
                            quality_score = %s, lead_score = %s
                           WHERE id = %s''',
                        (
                            lead.get('company_name'), lead.get('email'), lead.get('phone'),
                            lead.get('website'), lead.get('address'), lead.get('city'),
                            lead.get('state'), lead.get('contact_name'),
                            lead.get('quality_score'), lead.get('lead_score', 0),
                            lead['id']
                        )
                    )
                    updated += 1
                except Exception as e:
                    print(f"[SANITIZE] Error updating lead {lead['id']}: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass

            # Pass 5: deletar leads inválidos/duplicados/excedentes
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

        # QUAL-06: Only sync leads with valid email (grade != F) OR valid whatsapp
        c.execute(
            '''SELECT company_name, email, phone, website, city, state, source
               FROM leads
               WHERE batch_id = %s AND (
                   (email IS NOT NULL AND email != \'\' AND quality_grade != \'F\') -- QUAL-06
                   OR
                   (whatsapp IS NOT NULL AND whatsapp != \'\')
               )
               ORDER BY extracted_at DESC''',
            (batch_id,)
        )
        rows = c.fetchall()

        if not rows:
            print(f"[SYNC] No CRM-eligible leads found for batch {batch_id} (QUAL-06 gate)")
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
        # QUAL-06: Consistent gate — same as auto_sync and batch sync
        c.execute("""SELECT COUNT(*) FROM leads WHERE (
            (email IS NOT NULL AND email != '' AND quality_grade != 'F') -- QUAL-06
            OR (whatsapp IS NOT NULL AND whatsapp != '')
        )""")
        total = c.fetchone()[0]

        if total == 0:
            return jsonify({'message': 'No CRM-eligible leads found (QUAL-06 gate)', 'total': 0}), 200

        # QUAL-06: Only sync leads with valid email (grade != F) OR valid whatsapp
        c.execute(
            '''SELECT company_name, email, phone, website, city, state, source
               FROM leads
               WHERE (
                   (email IS NOT NULL AND email != \'\' AND quality_grade != \'F\') -- QUAL-06
                   OR (whatsapp IS NOT NULL AND whatsapp != \'\')
               )
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


# ============= Pipeline Notification Helpers =============

# Credential getters — delegated to email_providers module
from email_providers import (
    get_brevo_credentials as _get_brevo_credentials,
    get_mailjet_credentials as _get_mailjet_credentials,
    get_resend_credentials as _get_resend_credentials,
)


def send_pipeline_email_report(report: dict, to_email: str) -> bool:
    """
    Send HTML pipeline summary via Brevo transactional email API.
    Returns True on success, False on any error. Never raises.
    """
    try:
        creds = _get_brevo_credentials()
        if not creds:
            print("[NOTIFY] Brevo credentials unavailable — skipping email")
            return False

        api_key    = creds['BREVO_API_KEY']
        from_email = creds.get('BREVO_FROM_EMAIL', 'noreply@extratordedados.com.br')
        from_name  = creds.get('BREVO_FROM_NAME', 'Extrator DIAX')

        status_color = '#22c55e' if report.get('status') == 'completed' else '#ef4444'
        niches_str   = ', '.join(report.get('niches', [])) or 'N/A'
        html = f"""
        <div style="font-family:sans-serif;max-width:600px;margin:auto">
          <h2 style="color:{status_color}">Pipeline Diario - {report.get('date','N/A')}</h2>
          <table border="0" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%">
            <tr style="background:#f3f4f6"><td><b>Regiao</b></td><td>{report.get('region','N/A')}</td></tr>
            <tr><td><b>Status</b></td><td style="color:{status_color}">{report.get('status','N/A').upper()}</td></tr>
            <tr style="background:#f3f4f6"><td><b>Leads coletados</b></td><td>{report.get('leads_found',0)}</td></tr>
            <tr><td><b>Leads sanitizados</b></td><td>{report.get('leads_sanitized',0)}</td></tr>
            <tr style="background:#f3f4f6"><td><b>Leads sincronizados</b></td><td>{report.get('leads_synced',0)}</td></tr>
            <tr><td><b>Duracao</b></td><td>{report.get('duration_min','?')} min</td></tr>
            {('<tr style="background:#fef2f2"><td><b>Erro</b></td><td style="color:#dc2626">' + str(report.get('error_message','')) + '</td></tr>') if report.get('error_message') else ''}
          </table>
          <p style="color:#6b7280;font-size:12px">Nichos: {niches_str}</p>
        </div>
        """

        subject = f"[Pipeline] {report.get('date')} - {report.get('leads_found',0)} leads - {report.get('status','N/A').upper()}"
        payload = {
            "sender":      {"name": from_name, "email": from_email},
            "to":          [{"email": to_email}],
            "subject":     subject,
            "htmlContent": html,
        }

        resp = http_requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        print(f"[NOTIFY] Email Brevo enviado para {to_email} (status {resp.status_code})")
        return True

    except Exception as e:
        print(f"[NOTIFY] Erro ao enviar email Brevo: {e}")
        return False


def send_notification_email(to_email: str, search_name: str, new_count: int) -> bool:
    """
    Send a Brevo transactional email notifying a client of new leads
    matching their saved search. Returns True on success, False on any error.
    Never raises.
    """
    try:
        creds = _get_brevo_credentials()
        if not creds:
            print('[NOTIFY] send_notification_email: Brevo creds not available')
            return False
        api_key    = creds.get('BREVO_API_KEY', '')
        from_email = creds.get('BREVO_FROM_EMAIL', 'noreply@extratordedados.com.br')
        from_name  = creds.get('BREVO_FROM_NAME', 'Extrator DIAX')
        subject    = f"[DIAX] {new_count} novos leads em '{search_name}'"
        html = f"""
        <div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px">
          <h2 style="color:#2563eb">Novos leads disponíveis</h2>
          <p>Sua busca salva <strong>'{search_name}'</strong> encontrou
             <strong>{new_count} novos leads</strong> desde a última notificação.</p>
          <p style="margin-top:24px">
            <a href="https://extratordedados.com.br/portal"
               style="background:#2563eb;color:#fff;padding:10px 20px;
                      border-radius:6px;text-decoration:none;font-weight:bold">
              Ver leads no portal
            </a>
          </p>
          <hr style="margin-top:32px;border:none;border-top:1px solid #e5e7eb"/>
          <p style="font-size:12px;color:#6b7280">
            Extrator de Dados DIAX — para parar notificações acesse
            <a href="https://extratordedados.com.br/saved-searches">/saved-searches</a>
          </p>
        </div>
        """
        resp = http_requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json={
                "sender": {"name": from_name, "email": from_email},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html,
            },
            timeout=15,
        )
        resp.raise_for_status()
        print(f'[NOTIFY] Email enviado para {to_email}: {new_count} leads em "{search_name}"')
        return True
    except Exception as e:
        print(f'[NOTIFY] send_notification_email erro: {e}')
        return False


def _ping_healthcheck(check_url: str, success: bool = True) -> None:
    """
    Dead man's switch: ping healthchecks.io after pipeline completes.
    Appends '/fail' suffix when success=False. Never raises.
    """
    if not check_url:
        return
    try:
        suffix = '' if success else '/fail'
        http_requests.get(check_url + suffix, timeout=5)
        print(f"[HEALTHCHECK] Pinged: {check_url}{suffix}")
    except Exception as e:
        print(f"[HEALTHCHECK] Ping failed (non-fatal): {e}")


def _generate_and_send_pipeline_report(daily_job_id: int, report_data: dict) -> None:
    """
    Called at the end of run_daily_pipeline.
    Sends email via Brevo and pings healthchecks.io.
    Wrapped in try/except - must NEVER abort the pipeline.
    """
    try:
        cfg = get_pipeline_config()

        notify_email    = cfg.get('notify_email')
        healthcheck_url = cfg.get('healthcheck_url')

        if notify_email:
            send_pipeline_email_report(report_data, notify_email)
        else:
            print("[REPORT] notify_email nao configurado - email nao enviado")

        success = report_data.get('status') == 'completed'
        _ping_healthcheck(healthcheck_url, success)

    except Exception as e:
        print(f"[REPORT] Erro no envio do relatorio (non-fatal): {e}")


def run_daily_pipeline(daily_job_id, niches, region_id, cities_to_search):
    """
    Pipeline completo diário:
      1. Cria batch e roda busca massiva (6 métodos em paralelo)
      2. Aguarda conclusão (max 8h, poll 60s)
      3. Sanitiza todos os leads do batch
      4. Sync para api.alexandrequeiroz.com.br (sem duplicar)
      5. Atualiza daily_jobs com resultado
    """
    pipeline_start = datetime.now()   # MUST be first — before any other line
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

        # ── 5.5. Remover leads de baixa qualidade (score < 40, grade D/F) ─
        try:
            c.execute(
                "DELETE FROM leads WHERE batch_id=%s AND (quality_score IS NULL OR quality_score < 40)",
                (batch_id,)
            )
            low_quality_removed = c.rowcount
            print(f"[DAILY] Qualidade: {low_quality_removed} leads grade D/F removidos (score<40)")
        except Exception as _qe:
            print(f"[DAILY] Erro ao remover leads baixa qualidade (non-fatal): {_qe}")

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

        # ── 8. Enviar relatório e ping healthcheck ────────────────────────
        try:
            _generate_and_send_pipeline_report(daily_job_id, {
                'date':             datetime.now().strftime('%Y-%m-%d'),
                'region':           region_id,
                'niches':           niches,
                'leads_found':      leads_found,
                'leads_sanitized':  sanitized_count,
                'leads_synced':     synced,
                'status':           'completed',
                'error_message':    None,
                'duration_min':     round((datetime.now() - pipeline_start).total_seconds() / 60, 1),
                'batch_id':         batch_id,
            })
        except Exception as _rep_err:
            print(f"[DAILY] Erro no relatório (non-fatal): {_rep_err}")

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
        try:
            _generate_and_send_pipeline_report(daily_job_id, {
                'date':            datetime.now().strftime('%Y-%m-%d'),
                'region':          region_id,
                'niches':          niches,
                'leads_found':     locals().get('leads_found', 0),
                'leads_sanitized': locals().get('sanitized_count', 0),
                'leads_synced':    locals().get('synced', 0),
                'status':          'failed',
                'error_message':   str(e)[:200],
                'duration_min':    round((datetime.now() - pipeline_start).total_seconds() / 60, 1) if 'pipeline_start' in locals() else 0,
                'batch_id':        locals().get('batch_id'),
            })
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
        # QUAL-06: Gate — only leads with valid email OR valid whatsapp sent to CRM
        c.execute(
            '''SELECT id, company_name, email, phone, website, city, state, contact_name, tags, notes, whatsapp
               FROM leads l
               JOIN batches b ON l.batch_id = b.id
               WHERE b.is_shared = TRUE AND (
                   (l.email IS NOT NULL AND l.email != \'\' AND l.quality_grade != \'F\') -- QUAL-06
                   OR
                   (l.whatsapp IS NOT NULL AND l.whatsapp != \'\')
               )
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
    cfg       = get_pipeline_config()
    niches    = niches    or cfg['niches']
    region_id = region_id or cfg['region']
    # Phase 8: mark selected niches as used (advances round-robin for next run)
    _mark_niches_used(niches)

    # Phase 9: prefer DB-driven cities (round-robin from regions table)
    db_cities = cfg.get('cities')
    if db_cities:
        cities_to_search = [
            {'city': c['city'], 'state': c['state'], 'region': 'es_round_robin'}
            for c in db_cities
        ]
        _mark_cities_used([c['city'] for c in db_cities])
        region_label = f"es_round_robin_{len(db_cities)}cidades"
    elif region_id in SEARCH_REGIONS:
        # Legacy fallback — SEARCH_REGIONS dict preserved for non-ES regions and cold start
        region_data = SEARCH_REGIONS[region_id]
        cities_to_search = [
            {'city': c, 'state': region_data['state'], 'region': region_id}
            for c in region_data['cities']
        ]
        region_label = region_id
        print(f"[DAILY] regions table vazia — usando fallback {region_id} ({len(cities_to_search)} cidades)")
    else:
        print(f"[DAILY] Região desconhecida e regions table vazia: {region_id}")
        return None

    try:
        with get_db() as conn:
            cur = conn.cursor()
            # Advisory lock (transaction-scoped) — atomic, prevents race condition
            # between 2 Gunicorn workers checking daily_jobs simultaneously.
            # pg_try_advisory_xact_lock returns FALSE if another session holds the lock;
            # released automatically on commit/rollback (end of this with-block).
            cur.execute("SELECT pg_try_advisory_xact_lock(20260322)")
            if not cur.fetchone()[0]:
                print("[DAILY] Lock não obtido — outro worker já está iniciando — abortando.")
                return None
            # Secondary guard: prevent re-fire if job already started in last 5 min
            cur.execute(
                "SELECT id FROM daily_jobs WHERE started_at > NOW() - INTERVAL '5 minutes'"
            )
            if cur.fetchone():
                print("[DAILY] Job já iniciado por outro worker nos últimos 5 min — abortando.")
                return None
            cur.execute(
                "INSERT INTO daily_jobs (status, niches_used, region_used, started_at) "
                "VALUES ('running', %s, %s, NOW()) RETURNING id",
                (niches, region_label)
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


@app.route('/api/admin/pipeline-config', methods=['GET'])
@limiter.limit("60/minute")
def admin_get_pipeline_config():
    """Return current pipeline configuration. Admin only."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403
    cfg = get_pipeline_config()
    return jsonify(cfg), 200


@app.route('/api/admin/pipeline-config', methods=['PUT'])
@limiter.limit("30/minute")
def admin_update_pipeline_config():
    """Update pipeline configuration. Admin only. Reschedules job if hour/minute changes."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403

    data = request.get_json() or {}
    updates = {}
    if 'niches' in data:
        updates['daily_niches']    = json.dumps(data['niches'])
    if 'region' in data:
        updates['daily_region']    = json.dumps(data['region'])
    if 'hour' in data:
        updates['daily_hour']      = json.dumps(int(data['hour']))
    if 'minute' in data:
        updates['daily_minute']    = json.dumps(int(data.get('minute', 0)))
    if 'notify_email' in data:
        updates['notify_email']    = json.dumps(data['notify_email'])
    if 'healthcheck_url' in data:
        updates['healthcheck_url'] = json.dumps(data['healthcheck_url'])

    if updates:
        with get_db() as conn:
            cur = conn.cursor()
            for k, v in updates.items():
                cur.execute(
                    "INSERT INTO pipeline_config (key, value, updated_at) VALUES (%s, %s, NOW()) "
                    "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
                    (k, v)
                )

    # Reschedule APScheduler job if time changed
    if ('hour' in data or 'minute' in data) and _APSCHEDULER_AVAILABLE:
        try:
            cfg = get_pipeline_config()
            _tz = pytz.timezone('America/Sao_Paulo')
            _scheduler.reschedule_job(
                'daily_pipeline',
                trigger=CronTrigger(hour=cfg['hour'], minute=cfg['minute'], timezone=_tz)
            )
            print(f"[CONFIG] Pipeline reagendado: {cfg['hour']:02d}:{cfg['minute']:02d}")
        except Exception as e:
            print(f"[CONFIG] Erro ao reagendar: {e}")

    return jsonify({'success': True}), 200


@app.route('/api/admin/pipeline/health', methods=['GET'])
@limiter.limit("60/minute")
def admin_pipeline_health():
    """Return pipeline health summary: last run, 30d stats, next scheduled time. Admin only."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403

        # Last run
        cur.execute('''
            SELECT id, status, started_at, finished_at, leads_found,
                   leads_sanitized, leads_synced, error_message, region_used,
                   CASE WHEN finished_at IS NOT NULL AND started_at IS NOT NULL
                        THEN ROUND(EXTRACT(EPOCH FROM (finished_at - started_at))/60, 1)
                        ELSE NULL END AS duration_min
            FROM daily_jobs
            ORDER BY started_at DESC LIMIT 1
        ''')
        row = cur.fetchone()

        last_run = None
        if row:
            cols = ['id', 'status', 'started_at', 'finished_at', 'leads_found',
                    'leads_sanitized', 'leads_synced', 'error_message', 'region_used', 'duration_min']
            last_run = dict(zip(cols, row))
            if last_run['started_at']:
                last_run['started_at'] = last_run['started_at'].isoformat()
            if last_run['finished_at']:
                last_run['finished_at'] = last_run['finished_at'].isoformat()
            if last_run['duration_min'] is not None:
                last_run['duration_min'] = float(last_run['duration_min'])

        # 30-day stats
        cur.execute('''
            SELECT
                COUNT(*)                                               AS total,
                COUNT(*) FILTER (WHERE status = 'completed')          AS successful,
                COALESCE(ROUND(AVG(leads_found)::numeric, 1), 0)      AS avg_leads,
                COALESCE(MAX(leads_found), 0)                         AS max_leads
            FROM daily_jobs
            WHERE started_at > NOW() - INTERVAL '30 days'
        ''')
        stats = cur.fetchone()

    cfg = get_pipeline_config()
    next_scheduled = f"{cfg['hour']:02d}:{cfg['minute']:02d} America/Sao_Paulo"

    return jsonify({
        'last_run':        last_run,
        'next_scheduled':  next_scheduled,
        'stats_30d': {
            'total':      int(stats[0]) if stats else 0,
            'successful': int(stats[1]) if stats else 0,
            'avg_leads':  float(stats[2]) if stats else 0.0,
            'max_leads':  int(stats[3]) if stats else 0,
        },
        'scheduler_running': bool(_APSCHEDULER_AVAILABLE and _scheduler and _scheduler.running),
        'config': {
            'niches': cfg['niches'],
            'region': cfg['region'],
            'hour':   cfg['hour'],
        }
    }), 200


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


@app.route('/api/admin/niches', methods=['GET'])
@limiter.limit("60/minute")
def admin_get_niches():
    """Return all niches grouped by category. Admin only."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        row = c.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403
        c.execute('''
            SELECT id, name, category, active, priority, last_used_at, created_at
            FROM niches
            ORDER BY category, priority ASC, name ASC
        ''')
        rows = c.fetchall()
    from collections import defaultdict
    grouped = defaultdict(list)
    for r in rows:
        grouped[r[2]].append({
            'id': r[0], 'name': r[1], 'category': r[2],
            'active': r[3], 'priority': r[4],
            'last_used_at': r[5].isoformat() if r[5] else None,
            'created_at': r[6].isoformat() if r[6] else None,
        })
    return jsonify({'niches': dict(grouped), 'total': len(rows)}), 200


@app.route('/api/admin/niches/bulk', methods=['PUT'])
@limiter.limit("30/minute")
def admin_bulk_toggle_niches():
    """Activate or deactivate multiple niches by ID list. Admin only."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        row = c.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403
        data = request.get_json() or {}
        ids = data.get('ids', [])
        active = data.get('active', True)
        if not ids or not isinstance(ids, list):
            return jsonify({'error': 'ids deve ser lista não vazia'}), 400
        try:
            c.execute('UPDATE niches SET active = %s WHERE id = ANY(%s)', (bool(active), ids))
            conn.commit()
        except Exception as e:
            conn.rollback()
            return jsonify({'error': str(e)}), 500
    return jsonify({'updated': len(ids), 'active': bool(active)}), 200


@app.route('/api/admin/niches/<int:niche_id>', methods=['PUT'])
@limiter.limit("120/minute")
def admin_update_niche(niche_id):
    """Toggle active or update priority for a single niche. Admin only."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        row = c.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403
        data = request.get_json() or {}
        updates = []
        params = []
        if 'active' in data:
            updates.append('active = %s')
            params.append(bool(data['active']))
        if 'priority' in data:
            updates.append('priority = %s')
            params.append(int(data['priority']))
        if not updates:
            return jsonify({'error': 'Nenhum campo para atualizar'}), 400
        params.append(niche_id)
        try:
            c.execute(f'UPDATE niches SET {", ".join(updates)} WHERE id = %s RETURNING id, name, active, priority', params)
            updated = c.fetchone()
            conn.commit()
        except Exception as e:
            conn.rollback()
            return jsonify({'error': str(e)}), 500
    if not updated:
        return jsonify({'error': 'Nicho não encontrado'}), 404
    return jsonify({'id': updated[0], 'name': updated[1], 'active': updated[2], 'priority': updated[3]}), 200


@app.route('/api/niches', methods=['GET'])
@limiter.limit("120/minute")
def get_niches_catalog():
    """Return niches grouped by category. Auth required. ?active=true filters to active only."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    active_only = request.args.get('active', '').lower() == 'true'
    with get_db() as conn:
        c = conn.cursor()
        if active_only:
            c.execute('SELECT id, name, category, priority FROM niches WHERE active = TRUE ORDER BY category, priority ASC, name ASC')
        else:
            c.execute('SELECT id, name, category, priority, active FROM niches ORDER BY category, priority ASC, name ASC')
        rows = c.fetchall()
    from collections import defaultdict
    grouped = defaultdict(list)
    for r in rows:
        entry = {'id': r[0], 'name': r[1], 'priority': r[3]}
        if not active_only:
            entry['active'] = r[4]
        grouped[r[2]].append(entry)
    return jsonify({'niches': dict(grouped)}), 200


@app.route('/api/admin/regions', methods=['GET'])
@limiter.limit("60/minute")
def admin_get_regions():
    """Return all regions with last execution time and leads captured. Admin only."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        row = c.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403
        c.execute('''
            SELECT
                r.id,
                r.name,
                r.city,
                r.state,
                r.ibge_code,
                r.priority,
                r.active,
                r.last_used_at,
                COUNT(l.id) FILTER (WHERE l.extracted_at > NOW() - INTERVAL '30 days') AS leads_last_30d,
                COUNT(l.id) AS leads_total
            FROM regions r
            LEFT JOIN leads l ON l.city = r.city AND l.state = r.state
            GROUP BY r.id
            ORDER BY r.priority ASC, r.name ASC
        ''')
        rows = c.fetchall()
    result = []
    for r in rows:
        result.append({
            'id':            r[0],
            'name':          r[1],
            'city':          r[2],
            'state':         r[3],
            'ibge_code':     r[4],
            'priority':      r[5],
            'active':        r[6],
            'last_used_at':  r[7].isoformat() if r[7] else None,
            'leads_last_30d': r[8] or 0,
            'leads_total':   r[9] or 0,
        })
    return jsonify({'regions': result, 'total': len(result)}), 200


@app.route('/api/admin/regions/bulk', methods=['PUT'])
@limiter.limit("30/minute")
def admin_bulk_update_regions():
    """Activate or deactivate multiple regions by ID list. Admin only."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        row = c.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403
        data = request.get_json() or {}
        ids = data.get('ids', [])
        active = data.get('active', True)
        if not ids or not isinstance(ids, list):
            return jsonify({'error': 'ids deve ser lista não vazia'}), 400
        try:
            c.execute('UPDATE regions SET active = %s WHERE id = ANY(%s)', (bool(active), ids))
            conn.commit()
        except Exception as e:
            conn.rollback()
            return jsonify({'error': str(e)}), 500
    return jsonify({'updated': len(ids), 'active': bool(active)}), 200


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
    niches    = data.get('niches')    or get_pipeline_config()['niches']
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

def _is_admin_user(user_id):
    """Check if user is admin (helper for usage tracking bypass)"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT is_admin FROM users WHERE id = %s', (user_id,))
            row = c.fetchone()
            return bool(row and row[0])
    except Exception:
        return False

def _increment_usage(user_id, field='leads_viewed', amount=1):
    """Increment usage counter (leads_viewed or leads_exported). Skipped for admins."""
    if _is_admin_user(user_id):
        return  # admins have unlimited usage
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

@app.route('/api/leads/reveal/<int:lead_id>', methods=['POST'])
@limiter.limit("60/hour")
def reveal_lead(lead_id):
    """Reveal full contact details for a lead. Costs 1 credit.
    Re-revealing the same lead is free (idempotent — checks user_lead_reveals).
    Admin users bypass credit check entirely.
    Returns: {lead_id, email, phone, whatsapp, credits_remaining, already_revealed}
    HTTP 402 if insufficient credits.
    HTTP 409 is NOT used — re-reveal returns 200 (already_revealed=True, no charge).
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    # Admin bypass: admins always get full data, no credit deducted
    is_admin = _is_admin_user(user_id)

    try:
        with get_db() as conn:
            c = conn.cursor()

            # Verify lead exists
            c.execute('SELECT email, phone, whatsapp FROM leads WHERE id = %s', (lead_id,))
            lead_row = c.fetchone()
            if not lead_row:
                return jsonify({'error': 'lead_not_found'}), 404

            if is_admin:
                # Admins bypass credit system entirely
                return jsonify({
                    'lead_id': lead_id,
                    'email': lead_row[0],
                    'phone': lead_row[1],
                    'whatsapp': lead_row[2],
                    'credits_remaining': None,
                    'already_revealed': True
                }), 200

            # Check if already revealed (no double-charge)
            c.execute(
                'SELECT 1 FROM user_lead_reveals WHERE user_id = %s AND lead_id = %s',
                (user_id, lead_id)
            )
            already_revealed = c.fetchone() is not None

            if not already_revealed:
                # Atomically deduct 1 credit (SELECT FOR UPDATE inside transaction)
                success, new_balance = deduct_credit(conn, user_id, 'reveal', lead_id)
                if not success:
                    return jsonify({
                        'error': 'insufficient_credits',
                        'balance': new_balance,
                        'required': 1
                    }), 402
                # Record reveal — ON CONFLICT DO NOTHING prevents duplicate if race occurs
                c.execute(
                    'INSERT INTO user_lead_reveals (user_id, lead_id) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                    (user_id, lead_id)
                )
            else:
                # Fetch current balance without deducting
                c.execute(
                    'SELECT balance_after FROM credit_ledger WHERE user_id = %s ORDER BY id DESC LIMIT 1',
                    (user_id,)
                )
                bal_row = c.fetchone()
                new_balance = bal_row[0] if bal_row else 0

            return jsonify({
                'lead_id': lead_id,
                'email': lead_row[0],
                'phone': lead_row[1],
                'whatsapp': lead_row[2],
                'credits_remaining': new_balance,
                'already_revealed': already_revealed
            }), 200

    except Exception as e:
        print(f'[ERROR] /api/leads/reveal/{lead_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/client/credits', methods=['GET'])
@limiter.limit("30/minute")
def client_credits():
    """Get client's credit balance and last 20 credit events.
    Returns: {balance: int, history: [{amount, operation, ref_id, balance_after, created_at}]}
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        with get_db() as conn:
            c = conn.cursor()

            # Current balance from last ledger event
            c.execute(
                'SELECT balance_after FROM credit_ledger WHERE user_id = %s ORDER BY id DESC LIMIT 1',
                (user_id,)
            )
            row = c.fetchone()
            balance = row[0] if row else 0

            # Last 20 events
            c.execute("""
                SELECT amount, operation, ref_id, balance_after, created_at
                FROM credit_ledger
                WHERE user_id = %s
                ORDER BY id DESC LIMIT 20
            """, (user_id,))
            history = [
                {
                    'amount': r[0],
                    'operation': r[1],
                    'ref_id': r[2],
                    'balance_after': r[3],
                    'created_at': r[4].isoformat() if r[4] else None
                }
                for r in c.fetchall()
            ]

        return jsonify({'balance': balance, 'history': history}), 200

    except Exception as e:
        print(f'[ERROR] /api/client/credits: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/client/leads/export', methods=['GET'])
@limiter.limit("10/hour")
def client_export_leads():
    """Export filtered leads as CSV or JSON. Debits credits equal to leads exported.
    Admin users bypass credit check (unlimited export).
    Query params: format (csv|json), category, city, state, quality_grade,
                  has_email, has_phone, has_whatsapp, has_website, has_cnpj.
    Returns: file download (text/csv or application/json).
    HTTP 401 if not authenticated, 402 if insufficient credits, 404 if no leads match.
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    fmt = request.args.get('format', 'csv').lower()
    if fmt not in ('csv', 'json'):
        return jsonify({'error': 'format must be csv or json'}), 400

    # Build filter params (same as GET /api/leads/search)
    category = request.args.get('category', '').strip()
    city = request.args.get('city', '').strip()
    state_param = request.args.get('state', '').strip()
    quality_grade = request.args.get('quality_grade', '').strip().upper()
    has_email = request.args.get('has_email', '').lower() in ('true', '1')
    has_phone = request.args.get('has_phone', '').lower() in ('true', '1')
    has_whatsapp = request.args.get('has_whatsapp', '').lower() in ('true', '1')
    has_website = request.args.get('has_website', '').lower() in ('true', '1')
    has_cnpj = request.args.get('has_cnpj', '').lower() in ('true', '1')

    # Build WHERE clause — same logic as client_search_leads
    conditions = ['b.is_shared = TRUE']
    params = []
    if category:
        conditions.append('l.category ILIKE %s')
        params.append(f'%{category}%')
    if city:
        conditions.append('l.city ILIKE %s')
        params.append(f'%{city}%')
    if state_param:
        conditions.append('l.state ILIKE %s')
        params.append(f'%{state_param}%')
    if quality_grade:
        grade_order = {'A': 5, 'B': 4, 'C': 3, 'D': 2, 'F': 1}
        min_grade = grade_order.get(quality_grade, 0)
        matching_grades = [g for g, v in grade_order.items() if v >= min_grade]
        if matching_grades:
            conditions.append('l.quality_grade = ANY(%s)')
            params.append(matching_grades)
    if has_email:
        conditions.append("l.email IS NOT NULL AND l.email != ''")
    if has_phone:
        conditions.append("l.phone IS NOT NULL AND l.phone != ''")
    if has_whatsapp:
        conditions.append("l.whatsapp IS NOT NULL AND l.whatsapp != ''")
    if has_website:
        conditions.append("l.website IS NOT NULL AND l.website != ''")
    if has_cnpj:
        conditions.append("l.cnpj IS NOT NULL AND l.cnpj != ''")

    where_clause = ' AND '.join(conditions)
    base_query = f"""
        SELECT l.id, l.company_name, l.city, l.state, l.category,
               l.email, l.phone, l.whatsapp, l.website, l.cnpj,
               l.lead_score, l.quality_grade, l.source, l.captured_at
        FROM leads l
        JOIN batches b ON l.batch_id = b.id
        WHERE {where_clause}
    """

    is_admin = _is_admin_user(user_id)

    try:
        with get_db() as conn:
            c = conn.cursor()

            # 1. Count matching leads
            c.execute(f'SELECT COUNT(*) FROM ({base_query}) _sub', params)
            total_count = c.fetchone()[0]
            if total_count == 0:
                return jsonify({'error': 'no_leads_match', 'count': 0}), 404

            # 2. Determine export cap from credit balance
            if is_admin:
                export_count = total_count
                balance = None
            else:
                # Get current balance (SELECT FOR UPDATE to prevent concurrent exports)
                c.execute(
                    'SELECT id, balance_after FROM credit_ledger WHERE user_id = %s ORDER BY id DESC LIMIT 1 FOR UPDATE',
                    (user_id,)
                )
                row = c.fetchone()
                balance = row[1] if row else 0
                if balance <= 0:
                    return jsonify({'error': 'insufficient_credits', 'balance': 0}), 402
                # Cap at balance
                export_count = min(total_count, balance)

            # 3. Fetch the actual rows (ordered by lead_score desc, capped)
            paged_query = base_query + ' ORDER BY l.lead_score DESC NULLS LAST LIMIT %s'
            c.execute(paged_query, params + [export_count])
            rows = c.fetchall()
            actual_count = len(rows)

            if actual_count == 0:
                return jsonify({'error': 'no_leads_match', 'count': 0}), 404

            # 4. Build lead dicts (all revealed=True for export)
            leads_dicts = [portal_lead_to_dict(r, revealed=True) for r in rows]
            lead_ids = [r[0] for r in rows]

            # 5. Atomically debit credits + mark reveals in same transaction
            if not is_admin and actual_count > 0:
                new_balance = balance - actual_count
                c.execute("""
                    INSERT INTO credit_ledger (user_id, amount, operation, ref_id, balance_after)
                    VALUES (%s, %s, 'export', NULL, %s)
                """, (user_id, -actual_count, new_balance))
                # Mark all exported leads as revealed (idempotent)
                c.executemany(
                    'INSERT INTO user_lead_reveals (user_id, lead_id) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                    [(user_id, lid) for lid in lead_ids]
                )
            # get_db() context manager auto-commits on __exit__

        # 6. Generate and return file (outside transaction — file gen after credits committed)
        if fmt == 'json':
            import json as json_lib
            from flask import Response as FlaskResponse
            json_bytes = json_lib.dumps(leads_dicts, default=str, ensure_ascii=False).encode('utf-8')
            return FlaskResponse(
                json_bytes,
                mimetype='application/json',
                headers={
                    'Content-Disposition': f'attachment; filename="leads_{datetime.now().strftime("%Y%m%d")}.json"'
                }
            )
        else:
            from flask import Response as FlaskResponse
            csv_bytes = _generate_csv_bytes(leads_dicts)
            return FlaskResponse(
                csv_bytes,
                mimetype='text/csv; charset=utf-8-sig',
                headers={
                    'Content-Disposition': f'attachment; filename="leads_{datetime.now().strftime("%Y%m%d")}.csv"'
                }
            )

    except Exception as e:
        print(f'[ERROR] /api/client/leads/export: {e}')
        return jsonify({'error': str(e)}), 500


# ─── Niche Request Queue (Phase 5, Plan 02) ───────────────────────────────────

@app.route('/api/client/niche-requests', methods=['POST'])
@limiter.limit("5/hour")
def client_create_niche_request():
    """Submit or vote on a niche request. Deduplicates by niche+city+state."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    niche = (data.get('niche') or '').strip()
    city = (data.get('city') or '').strip() or None
    state_val = (data.get('state') or '').strip().upper() or None
    notes = (data.get('notes') or '').strip() or None

    if not niche:
        return jsonify({'error': 'niche is required'}), 400
    if len(niche) > 200:
        return jsonify({'error': 'niche must be <= 200 chars'}), 400

    with get_db() as conn:
        c = conn.cursor()
        # Dedup check with FOR UPDATE to prevent race condition
        c.execute("""
            SELECT id, votes FROM niche_requests
            WHERE niche ILIKE %s
              AND (city ILIKE %s OR (%s IS NULL AND city IS NULL))
              AND (state ILIKE %s OR (%s IS NULL AND state IS NULL))
              AND status IN ('pending', 'approved')
            ORDER BY created_at DESC LIMIT 1
            FOR UPDATE
        """, (niche, city, city, state_val, state_val))
        existing = c.fetchone()

        if existing:
            req_id = existing[0]
            current_votes = existing[1]
            # Check if this user already voted
            c.execute(
                'SELECT 1 FROM niche_request_votes WHERE user_id = %s AND niche_request_id = %s',
                (user_id, req_id)
            )
            if c.fetchone():
                return jsonify({'error': 'already_voted', 'niche_request_id': req_id}), 409
            # Increment votes
            c.execute(
                'UPDATE niche_requests SET votes = votes + 1, updated_at = NOW() WHERE id = %s',
                (req_id,)
            )
            c.execute(
                'INSERT INTO niche_request_votes (user_id, niche_request_id) VALUES (%s, %s)',
                (user_id, req_id)
            )
            return jsonify({
                'action': 'voted',
                'niche_request_id': req_id,
                'votes': current_votes + 1
            }), 200
        else:
            # Create new request
            c.execute("""
                INSERT INTO niche_requests (requester_user_id, niche, city, state, notes, votes)
                VALUES (%s, %s, %s, %s, %s, 1)
                RETURNING id
            """, (user_id, niche, city, state_val, notes))
            req_id = c.fetchone()[0]
            c.execute(
                'INSERT INTO niche_request_votes (user_id, niche_request_id) VALUES (%s, %s)',
                (user_id, req_id)
            )
            return jsonify({
                'action': 'created',
                'niche_request_id': req_id,
                'votes': 1
            }), 201


@app.route('/api/client/niche-requests', methods=['GET'])
@limiter.limit("30/minute")
def client_list_niche_requests():
    """List pending/approved/processing/done niche requests for the vote list."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT nr.id, nr.niche, nr.city, nr.state, nr.votes, nr.status,
                   nr.created_at, nr.leads_added,
                   u.username as requester_username,
                   CASE WHEN nrv.user_id IS NOT NULL THEN TRUE ELSE FALSE END as user_voted
            FROM niche_requests nr
            JOIN users u ON u.id = nr.requester_user_id
            LEFT JOIN niche_request_votes nrv
                   ON nrv.niche_request_id = nr.id AND nrv.user_id = %s
            WHERE nr.status IN ('pending', 'approved', 'processing', 'done')
            ORDER BY
                CASE WHEN nr.status = 'pending' THEN 0
                     WHEN nr.status = 'approved' THEN 1
                     WHEN nr.status = 'processing' THEN 2
                     ELSE 3 END,
                nr.votes DESC,
                nr.created_at DESC
        """, (user_id,))
        rows = c.fetchall()

    requests_list = []
    for r in rows:
        requests_list.append({
            'id': r[0],
            'niche': r[1],
            'city': r[2],
            'state': r[3],
            'votes': r[4],
            'status': r[5],
            'created_at': r[6].isoformat() if r[6] else None,
            'leads_added': r[7],
            'requester_username': r[8],
            'user_voted': r[9],
        })

    return jsonify({'requests': requests_list, 'total': len(requests_list)}), 200


@app.route('/api/admin/niche-requests', methods=['GET'])
@limiter.limit("30/minute")
@require_role('admin')
def admin_list_niche_requests():
    """Admin: list all niche requests sorted by votes desc."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT nr.id, nr.niche, nr.city, nr.state, nr.votes, nr.status,
                   nr.admin_notes, nr.leads_added,
                   nr.created_at, nr.updated_at, nr.completed_at,
                   u.username as requester_username
            FROM niche_requests nr
            JOIN users u ON u.id = nr.requester_user_id
            ORDER BY nr.votes DESC, nr.created_at DESC
        """)
        rows = c.fetchall()

    requests_list = []
    for r in rows:
        requests_list.append({
            'id': r[0],
            'niche': r[1],
            'city': r[2],
            'state': r[3],
            'votes': r[4],
            'status': r[5],
            'admin_notes': r[6],
            'leads_added': r[7],
            'created_at': r[8].isoformat() if r[8] else None,
            'updated_at': r[9].isoformat() if r[9] else None,
            'completed_at': r[10].isoformat() if r[10] else None,
            'requester_username': r[11],
        })

    pending_count = sum(1 for r in requests_list if r['status'] == 'pending')
    return jsonify({'requests': requests_list, 'total': len(requests_list), 'pending_count': pending_count}), 200


# ── Saved Searches (Phase 6) ─────────────────────────────────────────────────

@app.route('/api/client/saved-searches', methods=['POST'])
@limiter.limit("60/minute")
def create_saved_search():
    """Create or upsert a saved search for the authenticated user."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    filters = data.get('filters') or {}
    notify_enabled = bool(data.get('notify_enabled', True))
    notify_email = (data.get('notify_email') or '').strip() or None

    if not name:
        return jsonify({'error': 'name is required'}), 400
    if not isinstance(filters, dict):
        return jsonify({'error': 'filters must be an object'}), 400

    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO saved_searches (user_id, name, filters, notify_enabled, notify_email)
                VALUES (%s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (user_id, name) DO UPDATE SET
                    filters = EXCLUDED.filters,
                    notify_enabled = EXCLUDED.notify_enabled,
                    notify_email = COALESCE(EXCLUDED.notify_email, saved_searches.notify_email)
                RETURNING id, name, filters, notify_enabled, notify_email, last_notified_at, created_at
            """, (user_id, name, json.dumps(filters), notify_enabled, notify_email))
            row = cur.fetchone()
            conn.commit()
            return jsonify({
                'id': row[0], 'name': row[1], 'filters': row[2],
                'notify_enabled': row[3], 'notify_email': row[4],
                'last_notified_at': row[5].isoformat() if row[5] else None,
                'created_at': row[6].isoformat() if row[6] else None,
            }), 201
    except Exception as e:
        print(f'[API] create_saved_search erro: {e}')
        return jsonify({'error': 'internal error'}), 500


@app.route('/api/client/saved-searches', methods=['GET'])
@limiter.limit("60/minute")
def list_saved_searches():
    """List all saved searches for the authenticated user."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, filters, notify_enabled, notify_email,
                       last_notified_at, created_at
                FROM saved_searches
                WHERE user_id = %s
                ORDER BY created_at DESC
            """, (user_id,))
            rows = cur.fetchall()
            result = []
            for row in rows:
                result.append({
                    'id': row[0], 'name': row[1], 'filters': row[2],
                    'notify_enabled': row[3], 'notify_email': row[4],
                    'last_notified_at': row[5].isoformat() if row[5] else None,
                    'created_at': row[6].isoformat() if row[6] else None,
                })
            return jsonify({'saved_searches': result}), 200
    except Exception as e:
        print(f'[API] list_saved_searches erro: {e}')
        return jsonify({'error': 'internal error'}), 500


@app.route('/api/client/saved-searches/<int:ss_id>', methods=['DELETE'])
@limiter.limit("60/minute")
def delete_saved_search(ss_id):
    """Delete a saved search (owner check enforced)."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM saved_searches WHERE id = %s AND user_id = %s RETURNING id",
                (ss_id, user_id)
            )
            deleted = cur.fetchone()
            conn.commit()
            if not deleted:
                return jsonify({'error': 'Not found or not yours'}), 404
            return jsonify({'deleted': ss_id}), 200
    except Exception as e:
        print(f'[API] delete_saved_search erro: {e}')
        return jsonify({'error': 'internal error'}), 500


@app.route('/api/client/saved-searches/<int:ss_id>', methods=['PATCH'])
@limiter.limit("60/minute")
def update_saved_search(ss_id):
    """Update a saved search (toggle notify_enabled, update email or name). Owner check enforced."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    updates = []
    params = []

    if 'notify_enabled' in data:
        updates.append("notify_enabled = %s")
        params.append(bool(data['notify_enabled']))
    if 'notify_email' in data:
        updates.append("notify_email = %s")
        params.append((data['notify_email'] or '').strip() or None)
    if 'name' in data:
        new_name = (data['name'] or '').strip()
        if new_name:
            updates.append("name = %s")
            params.append(new_name)

    if not updates:
        return jsonify({'error': 'nothing to update'}), 400

    params.extend([ss_id, user_id])
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE saved_searches SET {', '.join(updates)} "
                f"WHERE id = %s AND user_id = %s "
                f"RETURNING id, name, filters, notify_enabled, notify_email, last_notified_at, created_at",
                params
            )
            row = cur.fetchone()
            conn.commit()
            if not row:
                return jsonify({'error': 'Not found or not yours'}), 404
            return jsonify({
                'id': row[0], 'name': row[1], 'filters': row[2],
                'notify_enabled': row[3], 'notify_email': row[4],
                'last_notified_at': row[5].isoformat() if row[5] else None,
                'created_at': row[6].isoformat() if row[6] else None,
            }), 200
    except Exception as e:
        print(f'[API] update_saved_search erro: {e}')
        return jsonify({'error': 'internal error'}), 500


@app.route('/api/admin/niche-requests/<int:req_id>/approve', methods=['POST'])
@limiter.limit("10/hour")
@require_role('admin')
def admin_approve_niche_request(req_id):
    """Admin: approve a niche request and trigger background extraction."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT niche, city, state FROM niche_requests WHERE id = %s AND status = 'pending'",
            (req_id,)
        )
        row = c.fetchone()
        if not row:
            return jsonify({'error': 'not_found_or_not_pending'}), 404
        niche, city, state_val = row[0], row[1], row[2]
        c.execute(
            "UPDATE niche_requests SET status = 'processing', updated_at = NOW() WHERE id = %s",
            (req_id,)
        )

    # Trigger extraction in background thread (daemon — same pattern as daily pipeline)
    def _trigger_niche_extraction(req_id=req_id, niche=niche, city=city, state_val=state_val):
        try:
            print(f'[niche_request] Starting extraction for req_id={req_id} niche={niche} city={city} state={state_val}')

            # 1. Create a shared batch for the niche extraction results
            batch_name = f'Niche Request #{req_id} — {niche}'
            if city:
                batch_name += f' em {city}'
            max_pages = 2

            with get_db() as conn:
                c = conn.cursor()
                c.execute(
                    'INSERT INTO batches (user_id, name, status, total_urls, created_at, is_shared) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id',
                    (1, batch_name, 'pending', 3, datetime.now(), True)
                )
                batch_id = c.fetchone()[0]

                # 2. Create search_jobs for search_engines method (DuckDuckGo + Bing)
                #    Use 3 engine variants for better coverage
                jobs_data = []
                for engine in ['duckduckgo', 'bing', 'yahoo']:
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, 1, niche, city or '', state_val or '', 'manual',
                         max_pages, 'pending', engine, datetime.now())
                    )
                    search_job_id = c.fetchone()[0]
                    jobs_data.append({
                        'search_job_id': search_job_id,
                        'niche': niche,
                        'city': city or '',
                        'state': state_val or '',
                        'max_pages': max_pages,
                    })

            # 3. Count leads before running extraction
            leads_before = 0
            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT COUNT(*) FROM leads WHERE batch_id = %s', (batch_id,))
                leads_before = c.fetchone()[0]

            # 4. Run the search engines processor (blocking — runs in this daemon thread)
            #    process_search_job runs DuckDuckGo + Bing — no Playwright, safe for daemon thread
            process_search_job(batch_id, jobs_data, 1)

            # 5. Count leads added and update niche request as done
            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT COUNT(*) FROM leads WHERE batch_id = %s', (batch_id,))
                leads_after = c.fetchone()[0]
                leads_added = leads_after - leads_before

                c.execute(
                    "UPDATE batches SET status = 'completed' WHERE id = %s",
                    (batch_id,)
                )
                c.execute(
                    "UPDATE niche_requests SET status = 'done', leads_added = %s, updated_at = NOW(), completed_at = NOW() WHERE id = %s",
                    (leads_added, req_id)
                )
            print(f'[niche_request] Extraction complete req_id={req_id} leads_added={leads_added} batch_id={batch_id}')

        except Exception as e:
            print(f'[niche_request] Error processing req_id={req_id}: {e}')
            try:
                with get_db() as conn:
                    conn.cursor().execute(
                        "UPDATE niche_requests SET status = 'pending', updated_at = NOW() WHERE id = %s AND status = 'processing'",
                        (req_id,)
                    )
            except Exception:
                pass

    threading.Thread(target=_trigger_niche_extraction, daemon=True).start()

    return jsonify({'status': 'processing', 'niche_request_id': req_id, 'niche': niche, 'city': city}), 200


@app.route('/api/admin/niche-requests/<int:req_id>/reject', methods=['POST'])
@limiter.limit("10/hour")
@require_role('admin')
def admin_reject_niche_request(req_id):
    """Admin: reject a pending niche request."""
    data = request.get_json(silent=True) or {}
    admin_notes = (data.get('admin_notes') or '').strip() or None

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM niche_requests WHERE id = %s AND status = 'pending'",
            (req_id,)
        )
        if not c.fetchone():
            return jsonify({'error': 'not_found_or_not_pending'}), 404
        c.execute(
            "UPDATE niche_requests SET status = 'rejected', admin_notes = %s, updated_at = NOW() WHERE id = %s",
            (admin_notes, req_id)
        )

    return jsonify({'status': 'rejected', 'niche_request_id': req_id}), 200


# ─── End Niche Request Queue ──────────────────────────────────────────────────


def _build_portal_filter_query(filters: dict):
    """
    Build the SQL WHERE clause for client portal lead searches.
    Used by client_search_leads() and trigger_saved_search_notifications().

    Returns: (conditions: list[str], params: list)
    The caller is responsible for joining conditions with AND and prepending
    the mandatory base condition 'b.is_shared = TRUE'.
    """
    conditions = ["b.is_shared = TRUE"]
    params = []

    category = filters.get('category', '').strip()
    if category:
        conditions.append("l.category ILIKE %s")
        params.append(f"%{category}%")

    city = filters.get('city', '').strip()
    if city:
        conditions.append("l.city ILIKE %s")
        params.append(f"%{city}%")

    state = filters.get('state', '').strip()
    if state:
        conditions.append("l.state ILIKE %s")
        params.append(f"%{state}%")

    q = filters.get('q', '').strip()
    if q:
        conditions.append("l.company_name ILIKE %s")
        params.append(f"%{q}%")

    quality_grade = filters.get('quality_grade', '').strip()
    if quality_grade:
        grade_order = {'A': 1, 'B': 2, 'C': 3, 'D': 4, 'F': 5}
        if quality_grade.upper() in grade_order:
            target_rank = grade_order[quality_grade.upper()]
            eligible = [g for g, r in grade_order.items() if r <= target_rank]
            if eligible:
                conditions.append("l.quality_grade = ANY(%s)")
                params.append(eligible)

    if filters.get('has_email'):
        conditions.append("l.email IS NOT NULL AND l.email != ''")
    if filters.get('has_phone'):
        conditions.append("l.phone IS NOT NULL AND l.phone != ''")
    if filters.get('has_whatsapp'):
        conditions.append("l.whatsapp IS NOT NULL AND l.whatsapp != ''")
    if filters.get('has_website'):
        conditions.append("l.website IS NOT NULL AND l.website != ''")
    if filters.get('has_cnpj'):
        conditions.append("l.cnpj IS NOT NULL AND l.cnpj != ''")

    return conditions, params


@app.route('/api/leads/search', methods=['GET'])
@limiter.limit("100/hour")
def client_search_leads():
    """Client-facing lead search. Returns masked contact data by default.
    Checks user_lead_reveals and returns unmasked data for already-revealed leads.
    Supported filters: category, city, state, quality_grade, has_email, has_phone,
                       has_whatsapp, has_website, has_cnpj, q, page, per_page (max 50).
    Never returns: crm_status, notes, batch_id, tags (internal fields).
    Rate limit: 100/hour.
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = min(50, max(10, int(request.args.get('per_page', 20))))
    except (ValueError, TypeError):
        per_page = 20

    # Build WHERE clause using shared helper
    conditions, params = _build_portal_filter_query({
        'category': request.args.get('category', ''),
        'city': request.args.get('city', ''),
        'state': request.args.get('state', ''),
        'q': request.args.get('q', ''),
        'quality_grade': request.args.get('quality_grade', ''),
        'has_email': request.args.get('has_email') in ('true', '1', 'yes'),
        'has_phone': request.args.get('has_phone') in ('true', '1', 'yes'),
        'has_whatsapp': request.args.get('has_whatsapp') in ('true', '1', 'yes'),
        'has_website': request.args.get('has_website') in ('true', '1', 'yes'),
        'has_cnpj': request.args.get('has_cnpj') in ('true', '1', 'yes'),
    })
    where_clause = " AND ".join(conditions)

    # Base query — only shared batches
    base_query = f"""
        SELECT l.id, l.company_name, l.city, l.state, l.category,
               l.email, l.phone, l.whatsapp, l.website, l.cnpj,
               l.lead_score, l.quality_grade, l.source, l.captured_at
        FROM leads l JOIN batches b ON l.batch_id = b.id
        WHERE {where_clause}
    """

    try:
        with get_db() as conn:
            c = conn.cursor()

            # Count total matching leads
            c.execute(f'SELECT COUNT(*) FROM ({base_query}) _sub', params)
            total = c.fetchone()[0]

            # Fetch paginated results
            paged_query = base_query + ' ORDER BY l.lead_score DESC NULLS LAST LIMIT %s OFFSET %s'
            c.execute(paged_query, params + [per_page, (page - 1) * per_page])
            rows = c.fetchall()

            # Determine which leads this user has already revealed
            lead_ids = [row[0] for row in rows]
            revealed_set = set()
            if lead_ids:
                c.execute(
                    'SELECT lead_id FROM user_lead_reveals WHERE user_id = %s AND lead_id = ANY(%s)',
                    (user_id, lead_ids)
                )
                revealed_set = {r[0] for r in c.fetchall()}

        leads = [
            portal_lead_to_dict(row, revealed=(row[0] in revealed_set))
            for row in rows
        ]

        return jsonify({
            'leads': leads,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page if per_page > 0 else 1
        }), 200

    except Exception as e:
        print(f'[ERROR] /api/leads/search: {e}')
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


# ============= Admin Quality Endpoints =============

@app.route('/api/admin/rescore-all', methods=['POST'])
def admin_rescore_all():
    """
    Recalcula lead_score (0-100) e quality_score para TODOS os leads.
    Roda em background. Retorna imediatamente com contagem estimada.
    """
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as _chk:
        _cur = _chk.cursor()
        _cur.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        _row = _cur.fetchone()
        if not _row or not _row[0]:
            return jsonify({'error': 'Admin only'}), 403

    def _rescore_background():
        conn = psycopg2.connect(**DB_CONFIG)
        c = conn.cursor()
        try:
            c.execute('''SELECT id, company_name, email, phone, website, instagram, facebook,
                                linkedin, whatsapp, cnpj, quality_score
                         FROM leads ORDER BY id''')
            rows = c.fetchall()
            cols = ['id', 'company_name', 'email', 'phone', 'website', 'instagram', 'facebook',
                    'linkedin', 'whatsapp', 'cnpj', 'quality_score']
            total = len(rows)
            updated = 0
            for row in rows:
                lead = dict(zip(cols, row))
                new_score = calculate_lead_score_numeric(lead)
                new_tier = calculate_quality_score(lead)
                try:
                    c.execute('UPDATE leads SET lead_score = %s, quality_score = %s WHERE id = %s',
                              (new_score, new_tier, lead['id']))
                    updated += 1
                except Exception as e:
                    print(f'[RESCORE] Error lead {lead["id"]}: {e}')
                    try: conn.rollback()
                    except: pass
            conn.commit()
            print(f'[RESCORE] ✅ {updated}/{total} leads rescored')
        except Exception as e:
            print(f'[RESCORE] ❌ {e}')
        finally:
            c.close()
            conn.close()

    # Conta leads para informar
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM leads')
        total = c.fetchone()[0]

    threading.Thread(target=_rescore_background, daemon=True).start()
    return jsonify({'message': f'Rescore iniciado em background para {total} leads', 'total': total})


@app.route('/api/admin/global-dedup', methods=['POST'])
def admin_global_dedup():
    """
    Deduplicação global cross-batch:
    1. Email exato: mantém lead com maior lead_score, remove os outros.
    2. Fuzzy por nome+cidade (threshold 88): marca como duplicado.
    Roda em background.
    """
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as _chk:
        _cur = _chk.cursor()
        _cur.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        _row = _cur.fetchone()
        if not _row or not _row[0]:
            return jsonify({'error': 'Admin only'}), 403

    def _global_dedup_background():
        conn = psycopg2.connect(**DB_CONFIG)
        c = conn.cursor()
        try:
            # --- Pass 1: dedup por email exato ---
            c.execute('''SELECT id, email, COALESCE(lead_score, 0) as score
                         FROM leads
                         WHERE email IS NOT NULL AND email != ''
                           AND email NOT LIKE '%@%.local'
                         ORDER BY COALESCE(lead_score, 0) DESC, id ASC''')
            rows = c.fetchall()
            seen_emails = {}
            ids_to_delete = []
            for lid, email, score in rows:
                email_clean = email.strip().lower()
                if email_clean in seen_emails:
                    ids_to_delete.append(lid)  # já tem um com score maior
                else:
                    seen_emails[email_clean] = lid

            deleted_exact = 0
            if ids_to_delete:
                c.execute('DELETE FROM leads WHERE id = ANY(%s)', (ids_to_delete,))
                deleted_exact = len(ids_to_delete)
                conn.commit()
            print(f'[GLOBAL-DEDUP] Email exato: {deleted_exact} deletados')

            # --- Pass 2: fuzzy dedup por nome+cidade ---
            if not _RAPIDFUZZ_AVAILABLE:
                print('[GLOBAL-DEDUP] rapidfuzz indisponível, pulando fuzzy pass')
                return

            from rapidfuzz import fuzz
            c.execute('''SELECT id, LOWER(TRIM(COALESCE(company_name, ''))),
                                LOWER(TRIM(COALESCE(city, '')))
                         FROM leads
                         WHERE company_name IS NOT NULL AND company_name != ''
                           AND crm_status != 'duplicado'
                         ORDER BY COALESCE(lead_score, 0) DESC''')
            rows = c.fetchall()
            seen_names = []  # list of (id, name_city_key)
            fuzzy_dups = []
            for lid, name, city in rows:
                if not name or len(name) < 4:
                    continue
                key = f"{name}|{city}"
                is_dup = False
                for sid, skey in seen_names:
                    sname = skey.split('|')[0]
                    scity = skey.split('|')[1]
                    # Só compara mesma cidade
                    if city and scity and city != scity:
                        continue
                    similarity = fuzz.token_sort_ratio(name, sname)
                    if similarity >= 88:
                        fuzzy_dups.append(lid)
                        is_dup = True
                        break
                if not is_dup:
                    seen_names.append((lid, key))

            marked_fuzzy = 0
            if fuzzy_dups:
                c.execute('''UPDATE leads SET crm_status = 'duplicado',
                                tags = CASE WHEN tags IS NULL OR tags = '' THEN 'duplicado_fuzzy'
                                            WHEN tags NOT LIKE '%%duplicado_fuzzy%%' THEN tags || ',duplicado_fuzzy'
                                            ELSE tags END
                             WHERE id = ANY(%s)''', (fuzzy_dups,))
                marked_fuzzy = len(fuzzy_dups)
                conn.commit()

            print(f'[GLOBAL-DEDUP] ✅ Email: {deleted_exact} deletados | Fuzzy: {marked_fuzzy} marcados')
        except Exception as e:
            print(f'[GLOBAL-DEDUP] ❌ {e}')
            import traceback; traceback.print_exc()
        finally:
            c.close()
            conn.close()

    threading.Thread(target=_global_dedup_background, daemon=True).start()
    return jsonify({'message': 'Deduplicação global iniciada em background'})


@app.route('/api/admin/bulk-cnpj-enrich', methods=['POST'])
def admin_bulk_cnpj_enrich():
    """
    Enriquecimento CNPJ em massa via BrasilAPI para leads com website .com.br sem CNPJ.
    Roda em background com throttle (2s entre requisições).
    """
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as _chk:
        _cur = _chk.cursor()
        _cur.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        _row = _cur.fetchone()
        if not _row or not _row[0]:
            return jsonify({'error': 'Admin only'}), 403

    def _bulk_cnpj_background():
        conn = psycopg2.connect(**DB_CONFIG)
        c = conn.cursor()
        try:
            c.execute('''SELECT id, website, company_name
                         FROM leads
                         WHERE (cnpj IS NULL OR cnpj = '')
                           AND website IS NOT NULL AND website != ''
                           AND (website ILIKE '%.com.br%' OR website ILIKE '%.med.br%'
                                OR website ILIKE '%.adv.br%' OR website ILIKE '%.eng.br%')
                         ORDER BY id
                         LIMIT 300''')
            rows = c.fetchall()
            enriched = 0
            for lid, website, name in rows:
                try:
                    # Extrai domínio do website
                    domain = re.sub(r'https?://', '', website or '').split('/')[0].strip()
                    if not domain:
                        continue
                    # Tenta buscar CNPJ via BrasilAPI por razão social
                    # Usa endpoint de busca por nome
                    search_url = f'https://brasilapi.com.br/api/cnpj/v1/search?query={requests.utils.quote(domain)}'
                    try:
                        resp = http_requests.get(search_url, timeout=8,
                                                  headers={'User-Agent': random.choice(USER_AGENTS)})
                        if resp.status_code == 200:
                            results = resp.json()
                            if isinstance(results, list) and results:
                                cnpj_found = results[0].get('cnpj', '')
                                if cnpj_found:
                                    c.execute('UPDATE leads SET cnpj = %s WHERE id = %s',
                                              (cnpj_found, lid))
                                    enriched += 1
                    except Exception:
                        pass
                    time.sleep(2)  # throttle BrasilAPI
                except Exception as e:
                    print(f'[BULK-CNPJ] Error lead {lid}: {e}')
            conn.commit()
            print(f'[BULK-CNPJ] ✅ {enriched}/{len(rows)} leads enriquecidos com CNPJ')
        except Exception as e:
            print(f'[BULK-CNPJ] ❌ {e}')
        finally:
            c.close()
            conn.close()

    with get_db() as conn:
        c = conn.cursor()
        c.execute('''SELECT COUNT(*) FROM leads
                     WHERE (cnpj IS NULL OR cnpj = '') AND website IS NOT NULL
                       AND (website ILIKE '%.com.br%' OR website ILIKE '%.med.br%')''')
        candidates = c.fetchone()[0]

    threading.Thread(target=_bulk_cnpj_background, daemon=True).start()
    return jsonify({'message': f'Enriquecimento CNPJ iniciado para ~{candidates} leads', 'candidates': candidates})


@app.route('/api/admin/auto-categorize-all', methods=['POST'])
def admin_auto_categorize_all():
    """
    Auto-categoriza leads sem categoria usando auto_tag_lead().
    Também preenche campos source 'desconhecido' de leads antigos.
    """
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as _chk:
        _cur = _chk.cursor()
        _cur.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        _row = _cur.fetchone()
        if not _row or not _row[0]:
            return jsonify({'error': 'Admin only'}), 403

    with get_db() as conn:
        c = conn.cursor()
        # Categorizar leads sem categoria
        c.execute('''SELECT id, company_name, email, city
                     FROM leads
                     WHERE (category IS NULL OR category = '')
                     ORDER BY id''')
        rows = c.fetchall()
        categorized = 0
        for lid, name, email, city in rows:
            tags = auto_tag_lead(name or '', email=email, city=city)
            if tags:
                category = tags[0]  # usa primeiro tag como categoria
                tag_str = ','.join(tags)
                c.execute('''UPDATE leads SET category = %s,
                                tags = CASE WHEN tags IS NULL OR tags = '' THEN %s
                                            ELSE tags END
                             WHERE id = %s''',
                          (category, tag_str, lid))
                categorized += 1

        # Normalizar source NULL → 'search_engine' para leads antigos sem source
        c.execute('''UPDATE leads SET source = 'search_engine'
                     WHERE (source IS NULL OR source = '')''')
        source_fixed = c.rowcount

        conn.commit()

    return jsonify({
        'categorized': categorized,
        'source_normalized': source_fixed,
        'message': f'{categorized} leads categorizados, {source_fixed} sources normalizados'
    })


@app.route('/api/admin/source-stats')
def api_admin_source_stats():
    """
    Retorna contagem de leads por source dos últimos 30 dias.
    Usado para o bar chart de fontes no painel admin.
    """
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as _chk:
        _cur = _chk.cursor()
        _cur.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        _row = _cur.fetchone()
        if not _row or not _row[0]:
            return jsonify({'error': 'Admin only'}), 403

    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT source, COUNT(*) AS total
            FROM leads
            WHERE captured_at >= NOW() - INTERVAL '30 days'
              AND source IS NOT NULL
            GROUP BY source
            ORDER BY total DESC
        ''')
        rows = c.fetchall()
    return jsonify([{'source': r[0], 'count': r[1]} for r in rows])


@app.route('/api/admin/quality-stats', methods=['GET'])
def get_quality_stats():
    """QUAL-06/Phase 7: Returns quality filter metrics for admin dashboard.
    Counts leads by quality_grade, whatsapp presence, and CRM eligibility.
    """
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as _chk:
        _cur = _chk.cursor()
        _cur.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        _row = _cur.fetchone()
        if not _row or not _row[0]:
            return jsonify({'error': 'Admin only'}), 403

    try:
        with get_db() as conn:
            c = conn.cursor()

            # Total leads in DB
            c.execute("SELECT COUNT(*) FROM leads")
            total_leads = c.fetchone()[0]

            # Leads by quality grade
            c.execute("""
                SELECT quality_grade, COUNT(*) as count
                FROM leads
                WHERE quality_grade IS NOT NULL
                GROUP BY quality_grade
                ORDER BY quality_grade
            """)
            grade_counts = {row[0]: row[1] for row in c.fetchall()}

            # Leads with valid email (grade != F and email not null)
            c.execute("""
                SELECT COUNT(*) FROM leads
                WHERE email IS NOT NULL AND email != ''
                  AND quality_grade IS NOT NULL AND quality_grade != 'F'
            """)
            leads_with_valid_email = c.fetchone()[0]

            # Leads with valid whatsapp (non-null, non-empty after QUAL-05 normalization)
            c.execute("""
                SELECT COUNT(*) FROM leads
                WHERE whatsapp IS NOT NULL AND whatsapp != ''
            """)
            leads_with_valid_whatsapp = c.fetchone()[0]

            # Leads eligible for CRM (valid email OR valid whatsapp) -- QUAL-06
            c.execute("""
                SELECT COUNT(*) FROM leads
                WHERE (email IS NOT NULL AND email != '' AND quality_grade != 'F')
                   OR (whatsapp IS NOT NULL AND whatsapp != '')
            """)
            leads_eligible_for_crm = c.fetchone()[0]

            # Leads NOT eligible for CRM (no valid email AND no valid whatsapp)
            leads_blocked_from_crm = total_leads - leads_eligible_for_crm

            # Leads already sent to CRM (from cache table)
            try:
                c.execute("SELECT COUNT(*) FROM crm_sent_leads")
                leads_sent_to_crm = c.fetchone()[0]
            except Exception:
                leads_sent_to_crm = None  # Table may not exist in all environments

            # Leads added in last 24h
            c.execute("""
                SELECT COUNT(*) FROM leads
                WHERE extracted_at >= NOW() - INTERVAL '24 hours'
            """)
            leads_last_24h = c.fetchone()[0]

        return jsonify({
            'total_leads': total_leads,
            'grade_distribution': grade_counts,
            'leads_with_valid_email': leads_with_valid_email,
            'leads_with_valid_whatsapp': leads_with_valid_whatsapp,
            'leads_eligible_for_crm': leads_eligible_for_crm,
            'leads_blocked_from_crm': leads_blocked_from_crm,
            'leads_sent_to_crm': leads_sent_to_crm,
            'leads_last_24h': leads_last_24h,
            'crm_gate_rule': 'valid_email (grade!=F) OR valid_whatsapp',
        }), 200

    except Exception as e:
        print(f"[quality-stats] Error: {e}")
        return jsonify({'error': str(e)}), 500


def trigger_saved_search_notifications():
    """
    APScheduler job: runs daily at 08:00 America/Sao_Paulo.
    For each saved search with notify_enabled=TRUE and a notify_email:
      1. Count new leads (since last_notified_at) matching the saved filters.
      2. If count > 0 and last_notified_at is older than 23 hours (or NULL):
         send email and update last_notified_at.
    Uses raw psycopg2.connect — NOT get_db() — consistent with all other scheduler jobs.
    """
    print('[SCHEDULER] trigger_saved_search_notifications: iniciando...')
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        # Double-fire guard: if any row was notified in the last 10 minutes, another worker ran.
        cur.execute("""
            SELECT COUNT(*) FROM saved_searches
            WHERE last_notified_at > NOW() - INTERVAL '10 minutes'
        """)
        if cur.fetchone()[0] > 0:
            print('[SCHEDULER] saved_search_notifications: double-fire detectado, abortando.')
            cur.close()
            conn.close()
            return

        # Fetch all active notification subscriptions
        cur.execute("""
            SELECT id, user_id, name, filters, notify_enabled, notify_email, last_notified_at
            FROM saved_searches
            WHERE notify_enabled = TRUE
              AND notify_email IS NOT NULL
              AND notify_email != ''
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        print(f'[SCHEDULER] saved_search_notifications: {len(rows)} subscriptions ativas')
        notified = 0

        for ss_id, user_id, name, filters, notify_enabled, notify_email, last_notified_at in rows:
            try:
                # Skip if notified within the last 23 hours (1 email/day guard)
                if last_notified_at:
                    import pytz as _pytz
                    if last_notified_at.tzinfo is None:
                        last_notified_at = last_notified_at.replace(tzinfo=_pytz.UTC)
                    from datetime import datetime as _dt
                    now_utc = _dt.now(_pytz.UTC)
                    elapsed_hours = (now_utc - last_notified_at).total_seconds() / 3600
                    if elapsed_hours < 23:
                        continue

                # Count new leads matching this filter since last_notified_at
                since = last_notified_at
                filters_dict = filters if isinstance(filters, dict) else {}
                conditions, params = _build_portal_filter_query(filters_dict)
                if since:
                    conditions.append("l.captured_at > %s")
                    params.append(since)

                where_sql = " AND ".join(conditions)
                count_sql = f"""
                    SELECT COUNT(*) FROM leads l
                    JOIN batches b ON l.batch_id = b.id
                    WHERE {where_sql}
                """
                count_conn = psycopg2.connect(**DB_CONFIG)
                count_cur = count_conn.cursor()
                count_cur.execute(count_sql, params)
                new_count = count_cur.fetchone()[0]
                count_cur.close()
                count_conn.close()

                if new_count > 0:
                    sent = send_notification_email(notify_email, name, new_count)
                    if sent:
                        upd_conn = psycopg2.connect(**DB_CONFIG)
                        upd_cur = upd_conn.cursor()
                        upd_cur.execute(
                            "UPDATE saved_searches SET last_notified_at = NOW() WHERE id = %s",
                            (ss_id,)
                        )
                        upd_conn.commit()
                        upd_cur.close()
                        upd_conn.close()
                        notified += 1
                        print(f'[SCHEDULER] Notificado {notify_email}: {new_count} leads em "{name}"')
            except Exception as row_err:
                print(f'[SCHEDULER] saved_search_notifications: erro para id={ss_id}: {row_err}')

        print(f'[SCHEDULER] saved_search_notifications: {notified} notificações enviadas.')
    except Exception as e:
        print(f'[SCHEDULER] saved_search_notifications: erro geral: {e}')


# ============= Stripe Checkout =============
# Requires env vars: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRO_PRICE_ID
# Falls back gracefully when keys are not configured.

def _get_stripe_config():
    """Read Stripe keys from environment. Returns dict with keys or None values."""
    return {
        'secret_key':     os.environ.get('STRIPE_SECRET_KEY'),
        'webhook_secret': os.environ.get('STRIPE_WEBHOOK_SECRET'),
        'pro_price_id':   os.environ.get('STRIPE_PRO_PRICE_ID'),
        'publishable_key': os.environ.get('STRIPE_PUBLISHABLE_KEY'),
    }


@app.route('/api/stripe/config', methods=['GET'])
@limiter.limit("30/minute")
def stripe_config():
    """Return publishable key and whether Stripe is configured. Safe to expose."""
    cfg = _get_stripe_config()
    return jsonify({
        'enabled': bool(cfg['secret_key'] and _STRIPE_AVAILABLE),
        'publishable_key': cfg['publishable_key'] or '',
    }), 200


@app.route('/api/stripe/create-checkout-session', methods=['POST'])
@limiter.limit("10/minute")
def stripe_create_checkout():
    """Create a Stripe Checkout session for plan upgrade.
    Body: {plan: 'pro'}
    Returns: {url: 'https://checkout.stripe.com/...'} or {error: ...}
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    if not _STRIPE_AVAILABLE:
        return jsonify({'error': 'Stripe SDK not installed. pip install stripe'}), 503

    cfg = _get_stripe_config()
    if not cfg['secret_key']:
        return jsonify({'error': 'Stripe not configured. Add STRIPE_SECRET_KEY to .deploy.env'}), 503

    body = request.get_json(silent=True) or {}
    plan = body.get('plan', 'pro')

    if plan != 'pro':
        return jsonify({'error': 'Only pro plan is available for checkout'}), 400

    price_id = cfg.get('pro_price_id')
    if not price_id:
        return jsonify({'error': 'STRIPE_PRO_PRICE_ID not set in .deploy.env'}), 503

    try:
        _stripe_sdk.api_key = cfg['secret_key']

        # Get user email for pre-fill
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT username FROM users WHERE id=%s', (user_id,))
            row = c.fetchone()
            username = row[0] if row else None

        session = _stripe_sdk.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription',
            success_url='https://extratordedados.com.br/plans?success=1',
            cancel_url='https://extratordedados.com.br/plans?canceled=1',
            metadata={'user_id': str(user_id), 'plan': plan},
            customer_email=username if username and '@' in username else None,
        )
        return jsonify({'url': session.url}), 200
    except Exception as e:
        print(f'[STRIPE] create-checkout-session error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/stripe/webhook', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhook events.
    Must be configured in Stripe dashboard: checkout.session.completed,
    customer.subscription.deleted, invoice.payment_failed
    Set endpoint: https://api.extratordedados.com.br/api/stripe/webhook
    """
    cfg = _get_stripe_config()
    if not _STRIPE_AVAILABLE or not cfg['secret_key']:
        return jsonify({'error': 'Stripe not configured'}), 503

    _stripe_sdk.api_key = cfg['secret_key']
    payload   = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')
    webhook_secret = cfg['webhook_secret']

    try:
        if webhook_secret:
            event = _stripe_sdk.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            event = _stripe_sdk.Event.construct_from(json.loads(payload), cfg['secret_key'])
    except Exception as e:
        print(f'[STRIPE] Webhook signature error: {e}')
        return jsonify({'error': str(e)}), 400

    etype = event['type']
    print(f'[STRIPE] Event: {etype}')

    try:
        if etype == 'checkout.session.completed':
            session   = event['data']['object']
            user_id   = int(session['metadata'].get('user_id', 0))
            plan_name = session['metadata'].get('plan', 'pro')
            if user_id:
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute("UPDATE users SET plan=%s WHERE id=%s", (plan_name, user_id))
                    conn.commit()
                print(f'[STRIPE] User {user_id} upgraded to {plan_name}')

        elif etype in ('customer.subscription.deleted', 'customer.subscription.paused'):
            session = event['data']['object']
            # Look up user by stripe customer ID (stored in extra_data or separate column if added later)
            # For now, log and skip — full customer mapping can be added when needed
            print(f'[STRIPE] Subscription {etype} — manual review may be required')

        elif etype == 'invoice.payment_failed':
            print(f'[STRIPE] Payment failed — invoice: {event["data"]["object"].get("id")}')

    except Exception as proc_err:
        print(f'[STRIPE] Event processing error (non-fatal): {proc_err}')

    return jsonify({'received': True}), 200


# ============= Email Campaigns Module =============
# Pure provider helpers live in email_providers.py (no DB dependency).
# DB-accessing orchestration stays here pending shared db_utils extraction.

import uuid as _uuid
import threading as _email_threading
from email_providers import (
    EMAIL_PROVIDERS as _EMAIL_PROVIDERS,
    TRACKING_PIXEL as _TRACKING_PIXEL,
    PROVIDER_SEND_FN as _PROVIDER_SEND_FN,
    inject_tracking as _inject_tracking,
    get_base_url as _get_base_url,
    send_via_brevo as _send_via_brevo,
    send_via_mailjet as _send_via_mailjet,
    send_via_sendpulse as _send_via_sendpulse,
    send_via_resend as _send_via_resend,
)

_EMAIL_AUTO_LOCK = _email_threading.Lock()


def _get_provider_usage(provider: str) -> int:
    """Return how many emails were sent today by this provider."""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT sends_count FROM email_provider_usage WHERE provider=%s AND usage_date=CURRENT_DATE",
                (provider,)
            )
            row = c.fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


def _increment_provider_usage(provider: str):
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO email_provider_usage (provider, usage_date, sends_count)
                VALUES (%s, CURRENT_DATE, 1)
                ON CONFLICT (provider, usage_date)
                DO UPDATE SET sends_count = email_provider_usage.sends_count + 1
            """, (provider,))
            conn.commit()
    except Exception as e:
        print(f'[EMAIL] _increment_provider_usage error: {e}')


def _pick_provider() -> str | None:
    """Return name of a provider that still has quota today, or None."""
    for p in _EMAIL_PROVIDERS:
        used = _get_provider_usage(p['name'])
        if used < p['daily_limit']:
            return p['name']
    return None


# _send_via_* functions and _PROVIDER_SEND_FN imported from email_providers above


def send_campaign_email(to_email: str, to_name: str, subject: str, html_body: str,
                        text_body: str = '', from_name: str = None) -> tuple[bool, str]:
    """Send email via whichever provider has quota. Returns (success, provider_used)."""
    provider = _pick_provider()
    if not provider:
        return False, 'quota_exceeded'
    fn = _PROVIDER_SEND_FN.get(provider)
    if fn and fn(to_email, to_name, subject, html_body, text_body, from_name=from_name):
        _increment_provider_usage(provider)
        return True, provider
    # Try next providers
    for p in _EMAIL_PROVIDERS:
        if p['name'] == provider:
            continue
        used = _get_provider_usage(p['name'])
        if used < p['daily_limit']:
            fn2 = _PROVIDER_SEND_FN.get(p['name'])
            if fn2 and fn2(to_email, to_name, subject, html_body, text_body, from_name=from_name):
                _increment_provider_usage(p['name'])
                return True, p['name']
    return False, 'all_failed'


# _inject_tracking and _get_base_url imported from email_providers above

# ---- Tracking endpoints ----

@app.route('/api/track/o/<token>.png', methods=['GET'])
def track_open(token):
    """Open tracking pixel."""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id, opened_at FROM email_sends WHERE token=%s", (token,))
            row = c.fetchone()
            if row:
                send_id, opened_at = row
                if not opened_at:
                    c.execute("UPDATE email_sends SET opened_at=NOW(), status='opened' WHERE token=%s", (token,))
                    c.execute("INSERT INTO email_events (send_id, event_type) VALUES (%s, 'open')", (send_id,))
                    conn.commit()
    except Exception as e:
        print(f'[TRACK/open] {e}')
    from flask import Response
    return Response(_TRACKING_PIXEL, mimetype='image/gif',
                    headers={'Cache-Control': 'no-cache, no-store, must-revalidate'})


@app.route('/api/track/c/<token>', methods=['GET'])
def track_click(token):
    """Click tracking redirect."""
    import urllib.parse
    from flask import redirect
    raw_url = request.args.get('url', '')
    original_url = urllib.parse.unquote(raw_url)
    # Prevent open redirect: only allow http/https URLs
    if not original_url.startswith(('http://', 'https://')):
        original_url = 'https://extratordedados.com.br'
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id, clicked_at FROM email_sends WHERE token=%s", (token,))
            row = c.fetchone()
            if row:
                send_id, clicked_at = row
                if not clicked_at:
                    c.execute("UPDATE email_sends SET clicked_at=NOW(), status='clicked' WHERE token=%s", (token,))
                c.execute("INSERT INTO email_events (send_id, event_type, metadata) VALUES (%s, 'click', %s)",
                          (send_id, json.dumps({'url': original_url})))
                conn.commit()
    except Exception as e:
        print(f'[TRACK/click] {e}')
    return redirect(original_url, code=302)


@app.route('/api/track/unsubscribe/<token>', methods=['GET'])
def track_unsubscribe(token):
    """Unsubscribe link handler."""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM email_sends WHERE token=%s", (token,))
            row = c.fetchone()
            if row:
                send_id = row[0]
                c.execute("UPDATE email_sends SET unsubscribed_at=NOW(), status='unsubscribed' WHERE token=%s", (token,))
                c.execute("INSERT INTO email_events (send_id, event_type) VALUES (%s, 'unsubscribe')", (send_id,))
                conn.commit()
    except Exception as e:
        print(f'[TRACK/unsubscribe] {e}')
    from flask import make_response
    html = '<html><body style="font-family:sans-serif;text-align:center;padding:60px"><h2>Descadastrado com sucesso</h2><p>Você não receberá mais emails desta campanha.</p></body></html>'
    return make_response(html, 200)


# ---- Campaign CRUD endpoints ----

@app.route('/api/campaigns', methods=['POST'])
def create_campaign():
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    steps = data.get('steps', [])
    target_filter = data.get('target_filter', {})
    from_name = (data.get('from_name') or '').strip() or None
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO email_campaigns (user_id, name, status, target_filter, from_name) VALUES (%s,%s,'draft',%s,%s) RETURNING id",
                (user_id, name, json.dumps(target_filter), from_name)
            )
            campaign_id = c.fetchone()[0]
            for i, step in enumerate(steps, start=1):
                c.execute("""
                    INSERT INTO email_steps (campaign_id, step_num, subject, body_html, delay_days, condition)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (
                    campaign_id, i,
                    step.get('subject', ''),
                    step.get('body_html', ''),
                    step.get('delay_days', 0),
                    step.get('condition', 'always'),
                ))
            conn.commit()
        return jsonify({'id': campaign_id, 'name': name}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns', methods=['GET'])
def list_campaigns():
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT ec.id, ec.name, ec.status, ec.created_at,
                    COUNT(DISTINCT es.id) AS total_sends,
                    COUNT(DISTINCT CASE WHEN es.opened_at IS NOT NULL THEN es.id END) AS opens,
                    COUNT(DISTINCT CASE WHEN es.clicked_at IS NOT NULL THEN es.id END) AS clicks,
                    COUNT(DISTINCT CASE WHEN es.unsubscribed_at IS NOT NULL THEN es.id END) AS unsubs,
                    (SELECT COUNT(*) FROM email_steps WHERE campaign_id=ec.id) AS steps_count
                FROM email_campaigns ec
                LEFT JOIN email_sends es ON es.campaign_id = ec.id AND es.status != 'pending'
                WHERE ec.user_id = %s
                GROUP BY ec.id
                ORDER BY ec.created_at DESC
            """, (user_id,))
            rows = c.fetchall()
            campaigns = []
            for r in rows:
                total = r[4] or 0
                opens = r[5] or 0
                clicks = r[6] or 0
                campaigns.append({
                    'id': r[0], 'name': r[1], 'status': r[2],
                    'created_at': r[3].isoformat() if r[3] else None,
                    'total_sends': total,
                    'open_rate': round(opens / total * 100, 1) if total else 0,
                    'click_rate': round(clicks / total * 100, 1) if total else 0,
                    'unsubs': r[7] or 0,
                    'steps_count': r[8] or 0,
                })
        return jsonify(campaigns)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/<int:campaign_id>', methods=['GET'])
def get_campaign(campaign_id):
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id, name, status, target_filter, created_at, from_name FROM email_campaigns WHERE id=%s AND user_id=%s",
                      (campaign_id, user_id))
            row = c.fetchone()
            if not row:
                return jsonify({'error': 'not found'}), 404
            c.execute("SELECT id, step_num, subject, body_html, delay_days, condition FROM email_steps WHERE campaign_id=%s ORDER BY step_num",
                      (campaign_id,))
            steps = [{'id': s[0], 'step_num': s[1], 'subject': s[2], 'body_html': s[3],
                      'delay_days': s[4], 'condition': s[5]} for s in c.fetchall()]
            campaign = {
                'id': row[0], 'name': row[1], 'status': row[2],
                'target_filter': row[3] or {},
                'created_at': row[4].isoformat() if row[4] else None,
                'from_name': row[5],
                'steps': steps,
            }
        return jsonify(campaign)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/<int:campaign_id>', methods=['DELETE'])
def delete_campaign(campaign_id):
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM email_campaigns WHERE id=%s AND user_id=%s", (campaign_id, user_id))
            conn.commit()
        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/<int:campaign_id>', methods=['PUT'])
def update_campaign(campaign_id):
    """Update campaign name and steps (only allowed when status=draft)."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id, status FROM email_campaigns WHERE id=%s AND user_id=%s",
                      (campaign_id, user_id))
            row = c.fetchone()
            if not row:
                return jsonify({'error': 'not found'}), 404
            if row[1] not in ('draft',):
                return jsonify({'error': 'can only edit draft campaigns'}), 409
            if 'name' in data:
                name = (data['name'] or '').strip()
                if name:
                    c.execute("UPDATE email_campaigns SET name=%s, updated_at=NOW() WHERE id=%s",
                              (name, campaign_id))
            if 'steps' in data:
                c.execute("DELETE FROM email_steps WHERE campaign_id=%s", (campaign_id,))
                for i, step in enumerate(data['steps'], start=1):
                    c.execute("""
                        INSERT INTO email_steps (campaign_id, step_num, subject, body_html, delay_days, condition)
                        VALUES (%s,%s,%s,%s,%s,%s)
                    """, (campaign_id, i, step.get('subject', ''), step.get('body_html', ''),
                          step.get('delay_days', 0), step.get('condition', 'always')))
            if 'target_filter' in data:
                c.execute("UPDATE email_campaigns SET target_filter=%s, updated_at=NOW() WHERE id=%s",
                          (json.dumps(data['target_filter']), campaign_id))
            if 'from_name' in data:
                from_name = (data['from_name'] or '').strip() or None
                c.execute("UPDATE email_campaigns SET from_name=%s, updated_at=NOW() WHERE id=%s",
                          (from_name, campaign_id))
            conn.commit()
        return jsonify({'updated': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _run_campaign_send_background(campaign_id: int, step_id: int, subject: str, body_html: str,
                                   leads: list, already_sent: set, unsubscribed: set,
                                   from_name: str = None):
    """Background daemon thread: send campaign step 1 to eligible leads."""
    import psycopg2 as _psy2
    import time as _bg_time
    conn = _psy2.connect(**DB_CONFIG)
    c = conn.cursor()
    base_url = _get_base_url()
    sent_count = 0
    failed_count = 0
    skipped_count = 0
    t0_bg = _bg_time.time()
    print(f'[CAMPAIGN-SEND] campaign={campaign_id} starting: {len(leads)} leads queued')
    try:
        for lead_id, email, company_name in leads:
            if not email or email.lower() in already_sent:
                skipped_count += 1
                continue
            email_lower = email.lower()
            if email_lower in unsubscribed:
                skipped_count += 1
                continue
            validation = validate_email_free(email)
            if not validation.get('valid') or validation.get('is_disposable'):
                skipped_count += 1
                continue
            token = str(_uuid.uuid4()).replace('-', '')
            tracked_html = _inject_tracking(body_html, token, base_url)
            unsub_url = f"{base_url}/api/track/unsubscribe/{token}"
            tracked_html += (
                f'<p style="font-size:11px;color:#999;text-align:center;margin-top:30px">'
                f'Para descadastrar: <a href="{unsub_url}">clique aqui</a></p>'
            )
            success, provider = send_campaign_email(email, company_name or '', subject, tracked_html, from_name=from_name)
            status = 'sent' if success else 'failed'
            try:
                c.execute("""
                    INSERT INTO email_sends (campaign_id, step_id, lead_id, email, token, provider, status, sent_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (token) DO NOTHING
                """, (campaign_id, step_id, lead_id, email, token, provider if success else None, status))
                conn.commit()
            except Exception:
                try: conn.rollback()
                except: pass
            if success:
                sent_count += 1
                already_sent.add(email_lower)
                print(f'[CAMPAIGN-SEND] campaign={campaign_id} sent email={email} provider={provider}')
                import time as _time_mod; _time_mod.sleep(0.5)
            else:
                failed_count += 1
                print(f'[CAMPAIGN-SEND] campaign={campaign_id} failed email={email} provider={provider}')
        elapsed = round(_bg_time.time() - t0_bg, 1)
        c.execute("UPDATE email_campaigns SET status='active', updated_at=NOW() WHERE id=%s", (campaign_id,))
        conn.commit()
        print(f'[CAMPAIGN-SEND] campaign={campaign_id} COMPLETE: sent={sent_count} failed={failed_count} skipped={skipped_count} elapsed={elapsed}s')
        # Log quota usage after batch
        for _p in _EMAIL_PROVIDERS:
            _used = _get_provider_usage(_p['name'])
            print(f'[EMAIL-QUOTA] {_p["name"]}: used={_used}/{_p["daily_limit"]} remaining={max(0, _p["daily_limit"] - _used)}')
    except Exception as e:
        print(f'[CAMPAIGN-SEND] campaign={campaign_id} error: {e}')
        try:
            c.execute("UPDATE email_campaigns SET status='draft', updated_at=NOW() WHERE id=%s", (campaign_id,))
            conn.commit()
        except: pass
    finally:
        try: c.close()
        except: pass
        try: conn.close()
        except: pass


@app.route('/api/campaigns/<int:campaign_id>/send', methods=['POST'])
@limiter.limit("5/hour")
def send_campaign(campaign_id):
    """Queue campaign step-1 send in background thread. Returns 202 immediately."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id, name, status, target_filter, from_name FROM email_campaigns WHERE id=%s AND user_id=%s",
                      (campaign_id, user_id))
            camp = c.fetchone()
            if not camp:
                return jsonify({'error': 'not found'}), 404
            if camp[2] == 'sending':
                return jsonify({'error': 'already sending'}), 409
            camp_from_name = camp[4]

            c.execute("SELECT id, subject, body_html FROM email_steps WHERE campaign_id=%s AND step_num=1", (campaign_id,))
            step = c.fetchone()
            if not step:
                return jsonify({'error': 'no step 1 defined'}), 400
            step_id, subject, body_html = step

            tf = camp[3] or {}
            quality_filter = tf.get('quality_grade')
            limit = min(int(tf.get('limit', 500)), 2000)

            query = "SELECT id, email, company_name FROM leads WHERE email IS NOT NULL AND email != '' AND quality_grade != 'F'"
            params = []
            if quality_filter:
                query += " AND quality_grade=%s"
                params.append(quality_filter)
            query += f" LIMIT {limit}"
            c.execute(query, params)
            leads = c.fetchall()

            c.execute("SELECT DISTINCT email FROM email_sends WHERE campaign_id=%s", (campaign_id,))
            already_sent = {r[0].lower() for r in c.fetchall()}

            c.execute("SELECT DISTINCT email FROM email_sends WHERE unsubscribed_at IS NOT NULL")
            unsubscribed = {r[0].lower() for r in c.fetchall()}

            c.execute("UPDATE email_campaigns SET status='sending', updated_at=NOW() WHERE id=%s", (campaign_id,))
            conn.commit()

        import threading as _thr
        t = _thr.Thread(
            target=_run_campaign_send_background,
            args=(campaign_id, step_id, subject, body_html, leads, already_sent, unsubscribed),
            kwargs={'from_name': camp_from_name},
            daemon=True,
        )
        t.start()
        return jsonify({
            'status': 'queued',
            'campaign_id': campaign_id,
            'leads_to_process': len(leads),
            'message': f'Envio iniciado para até {len(leads)} leads. Acompanhe o status da campanha.',
        }), 202
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/<int:campaign_id>/stats', methods=['GET'])
def campaign_stats(campaign_id):
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM email_campaigns WHERE id=%s AND user_id=%s", (campaign_id, user_id))
            if not c.fetchone():
                return jsonify({'error': 'not found'}), 404

            c.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status='sent') AS sent,
                    COUNT(*) FILTER (WHERE status='opened') AS opened,
                    COUNT(*) FILTER (WHERE status='clicked') AS clicked,
                    COUNT(*) FILTER (WHERE status='failed') AS failed,
                    COUNT(*) FILTER (WHERE status='unsubscribed') AS unsubscribed,
                    COUNT(*) AS total
                FROM email_sends WHERE campaign_id=%s
            """, (campaign_id,))
            r = c.fetchone()
            total = r[5] or 0
            sent = (r[0] or 0) + (r[1] or 0) + (r[2] or 0)
            opens = r[1] or 0
            clicks = r[2] or 0

            # Timeline (last 14 days)
            c.execute("""
                SELECT DATE(occurred_at) AS day, event_type, COUNT(*) AS cnt
                FROM email_events ee
                JOIN email_sends es ON es.id=ee.send_id
                WHERE es.campaign_id=%s AND occurred_at >= NOW()-INTERVAL '14 days'
                GROUP BY day, event_type ORDER BY day
            """, (campaign_id,))
            timeline = [{'date': str(r[0]), 'event': r[1], 'count': r[2]} for r in c.fetchall()]

            return jsonify({
                'total': total,
                'sent': sent,
                'open_rate': round(opens / sent * 100, 1) if sent else 0,
                'click_rate': round(clicks / sent * 100, 1) if sent else 0,
                'failed': r[3] or 0,
                'unsubscribed': r[4] or 0,
                'timeline': timeline,
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns/provider-status', methods=['GET'])
def campaigns_provider_status():
    """Return daily quota usage per provider."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    result = []
    for p in _EMAIL_PROVIDERS:
        used = _get_provider_usage(p['name'])
        result.append({
            'provider': p['name'],
            'used': used,
            'limit': p['daily_limit'],
            'remaining': max(0, p['daily_limit'] - used),
        })
    return jsonify(result)


@app.route('/api/campaigns/<int:campaign_id>/log', methods=['GET'])
def campaign_log(campaign_id):
    """Paginated send log for a campaign — real-time progress feed."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(100, int(request.args.get('per_page', 50)))
    offset = (page - 1) * per_page
    status_filter = request.args.get('status')
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM email_campaigns WHERE id=%s AND user_id=%s", (campaign_id, user_id))
            if not c.fetchone():
                return jsonify({'error': 'not found'}), 404

            where = "es.campaign_id=%s"
            params = [campaign_id]
            if status_filter:
                where += " AND es.status=%s"
                params.append(status_filter)

            c.execute(f"SELECT COUNT(*) FROM email_sends es WHERE {where}", params)
            total = c.fetchone()[0]

            c.execute(f"""
                SELECT es.id, es.email, es.provider, es.status, es.step_id,
                       es.sent_at, es.opened_at, es.clicked_at, es.bounced_at, es.error_msg,
                       est.step_num, est.subject
                FROM email_sends es
                LEFT JOIN email_steps est ON est.id = es.step_id
                WHERE {where}
                ORDER BY es.sent_at DESC NULLS LAST, es.id DESC
                LIMIT %s OFFSET %s
            """, params + [per_page, offset])
            items = []
            for row in c.fetchall():
                items.append({
                    'id': row[0],
                    'email': row[1],
                    'provider': row[2],
                    'status': row[3],
                    'step_id': row[4],
                    'sent_at': row[5].isoformat() if row[5] else None,
                    'opened_at': row[6].isoformat() if row[6] else None,
                    'clicked_at': row[7].isoformat() if row[7] else None,
                    'bounced_at': row[8].isoformat() if row[8] else None,
                    'error_msg': row[9],
                    'step_num': row[10],
                    'subject': row[11],
                })
            return jsonify({
                'total': total,
                'page': page,
                'per_page': per_page,
                'pages': max(1, (total + per_page - 1) // per_page),
                'items': items,
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/webhooks/bounces/brevo', methods=['POST'])
def webhook_bounce_brevo():
    """Receive Brevo webhook events (hard_bounce, soft_bounce, blocked, spam)."""
    data = request.get_json(silent=True) or {}
    event = data.get('event', '')
    if event not in ('hard_bounce', 'soft_bounce', 'blocked', 'spam'):
        return jsonify({'ok': True, 'skipped': True})
    email = (data.get('email') or '').lower()
    bounce_type = 'hard' if event in ('hard_bounce', 'spam') else 'soft'
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE email_sends
                SET status='bounced', bounced_at=NOW(), bounce_type=%s
                WHERE email=%s AND bounced_at IS NULL
                RETURNING id
            """, (bounce_type, email))
            updated = c.rowcount
            if updated:
                conn.commit()
                print(f'[BOUNCE-BREVO] {event} email={email} type={bounce_type} rows={updated}')
            else:
                conn.rollback()
        return jsonify({'ok': True, 'updated': updated})
    except Exception as e:
        print(f'[BOUNCE-BREVO] error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/webhooks/bounces/resend', methods=['POST'])
def webhook_bounce_resend():
    """Receive Resend webhook events (email.bounced, email.complained)."""
    data = request.get_json(silent=True) or {}
    event_type = data.get('type', '')
    if event_type not in ('email.bounced', 'email.complained'):
        return jsonify({'ok': True, 'skipped': True})
    email_data = data.get('data', {})
    to_field = email_data.get('to', '')
    email = (to_field[0] if isinstance(to_field, list) else to_field or '').lower()
    if not email:
        return jsonify({'ok': False, 'error': 'no email in payload'}), 400
    bounce_type = 'hard' if event_type == 'email.bounced' else 'soft'
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE email_sends
                SET status='bounced', bounced_at=NOW(), bounce_type=%s
                WHERE email=%s AND bounced_at IS NULL
                RETURNING id
            """, (bounce_type, email))
            updated = c.rowcount
            if updated:
                conn.commit()
                print(f'[BOUNCE-RESEND] {event_type} email={email} type={bounce_type} rows={updated}')
            else:
                conn.rollback()
        return jsonify({'ok': True, 'updated': updated})
    except Exception as e:
        print(f'[BOUNCE-RESEND] error: {e}')
        return jsonify({'error': str(e)}), 500


# ---- Automation Engine ----

def run_email_automation():
    """
    Called by scheduler every 2 hours.
    For each active campaign with multiple steps, check email_sends
    and trigger next steps based on conditions (if_opened, if_not_opened, if_clicked).
    """
    import datetime as _dt
    import psycopg2 as _psy2_auto
    # Within-worker guard
    if not _EMAIL_AUTO_LOCK.acquire(blocking=False):
        print('[EMAIL-AUTO] Skipping — already running in this worker')
        return
    # Cross-worker guard via DB session advisory lock (key 20260518)
    _guard_conn = None
    try:
        _guard_conn = _psy2_auto.connect(**DB_CONFIG)
        _guard_cur = _guard_conn.cursor()
        _guard_cur.execute("SELECT pg_try_advisory_lock(20260518)")
        if not _guard_cur.fetchone()[0]:
            print('[EMAIL-AUTO] Skipping — another worker holds the advisory lock')
            return
    except Exception as _ge:
        print(f'[EMAIL-AUTO] guard error: {_ge}')
    try:
        with get_db() as conn:
            c = conn.cursor()
            # Find campaigns with >1 step that are active
            c.execute("""
                SELECT DISTINCT ec.id, ec.user_id, ec.from_name
                FROM email_campaigns ec
                JOIN email_steps es ON es.campaign_id=ec.id AND es.step_num > 1
                WHERE ec.status = 'active'
            """)
            campaigns = c.fetchall()

            base_url = _get_base_url()

            for campaign_id, user_id, camp_from_name in campaigns:
                # Load all steps (step_num >= 2)
                c.execute("""
                    SELECT id, step_num, subject, body_html, delay_days, condition
                    FROM email_steps WHERE campaign_id=%s AND step_num > 1 ORDER BY step_num
                """, (campaign_id,))
                steps = c.fetchall()

                for step_id, step_num, subject, body_html, delay_days, condition in steps:
                    # For each send at step_num-1, check if this step should fire
                    c.execute("""
                        SELECT es.id, es.lead_id, es.email, es.opened_at, es.clicked_at, es.sent_at
                        FROM email_sends es
                        JOIN email_steps prev_step ON prev_step.campaign_id=%s AND prev_step.step_num=%s
                        WHERE es.campaign_id=%s AND es.step_id=prev_step.id
                          AND es.status NOT IN ('pending','unsubscribed')
                    """, (campaign_id, step_num - 1, campaign_id))
                    prev_sends = c.fetchall()

                    for ps_id, lead_id, email, opened_at, clicked_at, sent_at in prev_sends:
                        if not sent_at:
                            continue
                        # Check if already sent this step to this email
                        c.execute("""
                            SELECT id FROM email_sends
                            WHERE campaign_id=%s AND step_id=%s AND email=%s
                        """, (campaign_id, step_id, email))
                        if c.fetchone():
                            continue  # already sent

                        # Check delay
                        now = _dt.datetime.now(_dt.timezone.utc)
                        delta = (now - sent_at.replace(tzinfo=_dt.timezone.utc)).days if sent_at.tzinfo is None else (now - sent_at).days
                        if delta < delay_days:
                            continue

                        # Check condition
                        should_send = False
                        if condition == 'always':
                            should_send = True
                        elif condition == 'if_opened':
                            should_send = opened_at is not None
                        elif condition == 'if_not_opened':
                            should_send = opened_at is None
                        elif condition == 'if_clicked':
                            should_send = clicked_at is not None

                        if not should_send:
                            continue

                        # Send!
                        token = str(_uuid.uuid4()).replace('-', '')
                        tracked_html = _inject_tracking(body_html, token, base_url)
                        unsub_url = f"{base_url}/api/track/unsubscribe/{token}"
                        tracked_html += f'<p style="font-size:11px;color:#999;text-align:center;margin-top:30px">Para descadastrar: <a href="{unsub_url}">clique aqui</a></p>'
                        success, provider = send_campaign_email(email, '', subject, tracked_html, from_name=camp_from_name)
                        status = 'sent' if success else 'failed'
                        c.execute("""
                            INSERT INTO email_sends (campaign_id, step_id, lead_id, email, token, provider, status, sent_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
                            ON CONFLICT (token) DO NOTHING
                        """, (campaign_id, step_id, lead_id, email, token, provider if success else None, status))
                        print(f'[EMAIL-AUTO] campaign={campaign_id} step={step_num} email={email} result={status} provider={provider}')
                    conn.commit()
        print('[EMAIL-AUTO] Automation run complete')
    except Exception as e:
        print(f'[EMAIL-AUTO] Error: {e}')
    finally:
        if _guard_conn:
            try: _guard_conn.close()
            except: pass
        _EMAIL_AUTO_LOCK.release()


# ============= Image Generation Module =============
try:
    from image_gen import (
        get_models as _img_get_models,
        generate_image as _img_generate,
        edit_image as _img_edit,
        enhance_prompt as _img_enhance_prompt,
    )
    _IMAGE_GEN_AVAILABLE = True
except ImportError as _img_err:
    _IMAGE_GEN_AVAILABLE = False
    print(f"[IMAGE-GEN] Module unavailable: {_img_err}")


@app.route('/api/images/models', methods=['GET'])
@require_role('client')
def api_image_models():
    if not _IMAGE_GEN_AVAILABLE:
        return jsonify({'error': 'image_gen module not installed'}), 503
    return jsonify({'models': _img_get_models()})


@app.route('/api/images/generate', methods=['POST'])
@require_role('client')
@limiter.limit("10/hour")
def api_image_generate():
    if not _IMAGE_GEN_AVAILABLE:
        return jsonify({'error': 'image_gen module not installed'}), 503
    data = request.get_json(force=True) or {}
    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return jsonify({'error': 'prompt is required'}), 400
    model_key = data.get('model', 'nano-banana-2')
    enhance = bool(data.get('enhance', False))
    aspect_ratio = data.get('aspect_ratio', '1:1')
    user_id = verify_token(get_auth_header())
    try:
        result = _img_generate(prompt, model_key=model_key, enhance=enhance, aspect_ratio=aspect_ratio)
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO image_gen_log (user_id, prompt, model_key, model_id, url, cost_usd, elapsed_s, aspect_ratio, operation, error_msg)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'generate',%s)
                """, (user_id, prompt, result.get('model_key'), result.get('model_id'),
                      result.get('url'), result.get('cost_usd'), result.get('elapsed_s'),
                      aspect_ratio, result.get('error')))
        except Exception:
            pass
        if result.get('error') and not result.get('url'):
            return jsonify(result), 502
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/images/edit', methods=['POST'])
@require_role('client')
@limiter.limit("10/hour")
def api_image_edit():
    if not _IMAGE_GEN_AVAILABLE:
        return jsonify({'error': 'image_gen module not installed'}), 503
    data = request.get_json(force=True) or {}
    image_url = (data.get('image_url') or '').strip()
    prompt = (data.get('prompt') or '').strip()
    if not image_url or not prompt:
        return jsonify({'error': 'image_url and prompt are required'}), 400
    model_key = data.get('model', 'nano-banana-2')
    user_id = verify_token(get_auth_header())
    try:
        result = _img_edit(image_url, prompt, model_key=model_key)
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO image_gen_log (user_id, prompt, model_key, model_id, url, cost_usd, elapsed_s, operation, error_msg)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'edit',%s)
                """, (user_id, prompt, result.get('model_key'), result.get('model_id'),
                      result.get('url'), result.get('cost_usd'), result.get('elapsed_s'),
                      result.get('error')))
        except Exception:
            pass
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/images/enhance-prompt', methods=['POST'])
@require_role('client')
def api_image_enhance_prompt():
    if not _IMAGE_GEN_AVAILABLE:
        return jsonify({'error': 'image_gen module not installed'}), 503
    data = request.get_json(force=True) or {}
    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return jsonify({'error': 'prompt is required'}), 400
    result = _img_enhance_prompt(prompt)
    return jsonify(result)


@app.route('/api/images/history', methods=['GET'])
@require_role('client')
def api_image_history():
    """Paginated history of generated/edited images for the authenticated user."""
    user_id = verify_token(get_auth_header())
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(100, int(request.args.get('per_page', 20)))
    offset = (page - 1) * per_page
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM image_gen_log WHERE user_id=%s", (user_id,))
            total = c.fetchone()[0]
            c.execute("""
                SELECT id, prompt, model_key, url, cost_usd, elapsed_s, aspect_ratio, operation, error_msg, created_at
                FROM image_gen_log WHERE user_id=%s
                ORDER BY created_at DESC LIMIT %s OFFSET %s
            """, (user_id, per_page, offset))
            items = []
            for row in c.fetchall():
                items.append({
                    'id': row[0],
                    'prompt': row[1],
                    'model_key': row[2],
                    'url': row[3],
                    'cost_usd': float(row[4]) if row[4] else None,
                    'elapsed_s': float(row[5]) if row[5] else None,
                    'aspect_ratio': row[6],
                    'operation': row[7],
                    'error_msg': row[8],
                    'created_at': row[9].isoformat() if row[9] else None,
                })
        return jsonify({'total': total, 'page': page, 'per_page': per_page,
                        'pages': max(1, (total + per_page - 1) // per_page), 'items': items})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/images/health', methods=['GET'])
@require_role('client')
def api_image_health():
    """Check connectivity of each image provider (FAL.AI, OpenRouter, Groq). Fast ping, no generation."""
    import requests as _req
    results = {}

    # FAL.AI — probe key with a GET (returns 405 if key valid, 401 if invalid)
    try:
        from image_gen import _get_fal_key
        fal_key = _get_fal_key()
        if not fal_key:
            results['fal'] = {'status': 'misconfigured', 'error': 'FAL_KEY not set'}
        else:
            r = _req.get('https://fal.run/fal-ai/flux/schnell',
                         headers={'Authorization': f'Key {fal_key}'}, timeout=6)
            if r.status_code == 401:
                results['fal'] = {'status': 'invalid_key', 'http': 401}
            elif r.status_code == 402:
                results['fal'] = {'status': 'no_credits', 'http': 402}
            else:
                results['fal'] = {'status': 'ok', 'http': r.status_code}
    except Exception as e:
        results['fal'] = {'status': 'error', 'error': str(e)}

    # OpenRouter — list models (fast, no credits used)
    try:
        from image_gen import _get_openrouter_key
        or_key = _get_openrouter_key()
        if not or_key:
            results['openrouter'] = {'status': 'misconfigured', 'error': 'OPENROUTER_API_KEY not set'}
        else:
            r = _req.get('https://openrouter.ai/api/v1/models',
                         headers={'Authorization': f'Bearer {or_key}'}, timeout=8)
            if r.status_code == 401:
                results['openrouter'] = {'status': 'invalid_key', 'http': 401}
            else:
                n = len(r.json().get('data', []))
                results['openrouter'] = {'status': 'ok', 'http': r.status_code, 'models_available': n}
    except Exception as e:
        results['openrouter'] = {'status': 'error', 'error': str(e)}

    # Groq — list models
    try:
        from image_gen import _get_groq_key
        groq_key = _get_groq_key()
        if not groq_key:
            results['groq'] = {'status': 'misconfigured', 'error': 'GROQ_API_KEY not set'}
        else:
            r = _req.get('https://api.groq.com/openai/v1/models',
                         headers={'Authorization': f'Bearer {groq_key}'}, timeout=8)
            if r.status_code == 401:
                results['groq'] = {'status': 'invalid_key', 'http': 401}
            else:
                results['groq'] = {'status': 'ok', 'http': r.status_code}
    except Exception as e:
        results['groq'] = {'status': 'error', 'error': str(e)}

    overall = 'ok' if all(v.get('status') == 'ok' for v in results.values()) else 'degraded'
    return jsonify({'overall': overall, 'providers': results})


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

        def trigger_weekly_quality_maintenance():
            """Domingo 03:30 — rescore + global dedup + sanitize de todos os leads."""
            print('[SCHEDULER] Iniciando manutenção semanal de qualidade...')
            # Guard: evita double-fire com 2 workers
            conn = psycopg2.connect(**DB_CONFIG)
            c = conn.cursor()
            try:
                # Rescore
                c.execute('SELECT id, company_name, email, phone, website, instagram, facebook, linkedin, whatsapp, cnpj FROM leads ORDER BY id')
                rows = c.fetchall()
                cols = ['id','company_name','email','phone','website','instagram','facebook','linkedin','whatsapp','cnpj']
                updated = 0
                for row in rows:
                    lead = dict(zip(cols, row))
                    new_score = calculate_lead_score_numeric(lead)
                    new_tier = calculate_quality_score(lead)
                    try:
                        c.execute('UPDATE leads SET lead_score = %s, quality_score = %s WHERE id = %s',
                                  (new_score, new_tier, lead['id']))
                        updated += 1
                    except Exception:
                        try: conn.rollback()
                        except: pass
                conn.commit()
                print(f'[WEEKLY-QUALITY] Rescore: {updated} leads atualizados')

                # Global dedup por email
                c.execute('''SELECT id, email, COALESCE(lead_score, 0)
                             FROM leads
                             WHERE email IS NOT NULL AND email != ''
                               AND email NOT LIKE '%%@%%.local'
                             ORDER BY COALESCE(lead_score, 0) DESC, id ASC''')
                email_rows = c.fetchall()
                seen_e = {}
                del_ids = []
                for lid, email, score in email_rows:
                    ec = (email or '').strip().lower()
                    if ec in seen_e:
                        del_ids.append(lid)
                    else:
                        seen_e[ec] = lid
                if del_ids:
                    c.execute('DELETE FROM leads WHERE id = ANY(%s)', (del_ids,))
                    conn.commit()
                print(f'[WEEKLY-QUALITY] Global dedup: {len(del_ids)} removidos')

                # Auto-categorize sem categoria
                c.execute('SELECT id, company_name, email, city FROM leads WHERE (category IS NULL OR category = \'\')')
                cat_rows = c.fetchall()
                categorized = 0
                for lid, name, email, city in cat_rows:
                    tags = auto_tag_lead(name or '', email=email, city=city)
                    if tags:
                        c.execute('UPDATE leads SET category = %s WHERE id = %s', (tags[0], lid))
                        categorized += 1
                conn.commit()
                print(f'[WEEKLY-QUALITY] Auto-categorize: {categorized} leads categorizados')
                print('[SCHEDULER] ✅ Manutenção semanal concluída')
            except Exception as e:
                print(f'[SCHEDULER] ❌ Erro na manutenção semanal: {e}')
            finally:
                c.close()
                conn.close()

        _scheduler.add_job(
            trigger_weekly_quality_maintenance,
            CronTrigger(day_of_week='sun', hour=3, minute=30, timezone=_tz),
            id='weekly_quality_maintenance',
            replace_existing=True
        )

        _scheduler.add_job(
            grant_monthly_credits,
            CronTrigger(day=1, hour=0, minute=5, timezone=_tz),
            id='monthly_credit_grant',
            replace_existing=True
        )

        _scheduler.add_job(
            trigger_saved_search_notifications,
            CronTrigger(hour=8, minute=0, timezone=_tz),
            id='saved_search_notifications',
            replace_existing=True
        )
        print('[SCHEDULER] saved_search_notifications job registrado (08:00 BRT)')

        _scheduler.add_job(
            run_email_automation,
            CronTrigger(hour='*/2', timezone=_tz),
            id='email_automation',
            replace_existing=True
        )
        print('[SCHEDULER] email_automation job registrado (a cada 2h)')

        _scheduler.start()
        print(f"[SCHEDULER] Pipeline diário agendado: {DAILY_JOB_HOUR:02d}:00 America/Sao_Paulo")
        print(f"[SCHEDULER] CRM sync diário agendado: {DAILY_CRM_SYNC_HOUR:02d}:00 America/Sao_Paulo")
        print(f"[SCHEDULER] Manutenção semanal agendada: Domingo 03:30 America/Sao_Paulo")
        print("[SCHEDULER] Concessão mensal de créditos agendada: dia 1 às 00:05 America/Sao_Paulo")
    else:
        print("[SCHEDULER] APScheduler indisponível — instale: pip install APScheduler pytz")
except Exception as _sched_err:
    print(f"[SCHEDULER] Erro ao iniciar: {_sched_err}")
