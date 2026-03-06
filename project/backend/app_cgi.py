#!/usr/bin/env python3
"""
API CGI simplificada (sem Flask) para HostGator
Funciona direto como CGI script
"""
import sys
import os
import json
import cgi
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import re
import urllib.parse

# Paths
sys.path.insert(0, os.path.expanduser("~") + "/python_libs")
os.environ['SSL_CERT_FILE'] = os.path.expanduser("~") + "/python_libs/certifi/cacert.pem"
os.environ['REQUESTS_CA_BUNDLE'] = os.path.expanduser("~") + "/python_libs/certifi/cacert.pem"

DB_PATH = os.path.expanduser("~") + "/extrator.db"
ADMIN_PASSWORD_HASH = hashlib.sha256(os.environ.get("ADMIN_PASSWORD", "").encode()).hexdigest()

# ============= Database =============

def init_db():
    """Initialize database"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        password_hash TEXT,
        is_admin INTEGER,
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        token TEXT UNIQUE,
        created_at TEXT,
        expires_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        url TEXT,
        status TEXT,
        results_count INTEGER,
        created_at TEXT,
        started_at TEXT,
        finished_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY,
        job_id INTEGER,
        email TEXT,
        source_url TEXT,
        context TEXT,
        extracted_at TEXT,
        FOREIGN KEY(job_id) REFERENCES jobs(id)
    )''')

    c.execute('SELECT * FROM users WHERE username = ?', ('admin',))
    if not c.fetchone():
        c.execute(
            'INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)',
            ('admin', ADMIN_PASSWORD_HASH, 1, datetime.now().isoformat())
        )

    conn.commit()
    conn.close()

# ============= API Logic =============

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_token(token):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'SELECT user_id FROM sessions WHERE token = ? AND expires_at > ?',
        (token, datetime.now().isoformat())
    )
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def create_session(user_id):
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(days=7)).isoformat()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'INSERT INTO sessions (user_id, token, created_at, expires_at) VALUES (?, ?, ?, ?)',
        (user_id, token, datetime.now().isoformat(), expires_at)
    )
    conn.commit()
    conn.close()

    return token

def scrape_emails_from_url(url):
    emails = []
    try:
        response = requests.get(url, timeout=10, verify=False)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')

        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        text = soup.get_text()
        found_emails = set(re.findall(email_pattern, text))

        for email in found_emails:
            if not email.startswith('.'):
                emails.append({'email': email, 'url': url})

    except Exception as e:
        pass

    unique = {e['email']: e for e in emails}
    return list(unique.values())

# ============= HTTP Response =============

def json_response(data, status=200):
    print(f"Status: {status}")
    print("Content-Type: application/json")
    print("Access-Control-Allow-Origin: *")
    print()
    print(json.dumps(data))

def json_error(message, status=400):
    json_response({'error': message}, status)

# ============= Routes =============

def route_health():
    """GET /api/health"""
    json_response({'status': 'ok', 'timestamp': datetime.now().isoformat()})

def route_login(method, params):
    """POST /api/login"""
    if method != 'POST':
        json_error('Method not allowed', 405)
        return

    username = params.get('username', '')
    password = params.get('password', '')

    if not username or not password:
        json_error('Username and password required', 400)
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, password_hash FROM users WHERE username = ?', (username,))
    user = c.fetchone()
    conn.close()

    if not user or hash_password(password) != user[1]:
        json_error('Invalid credentials', 401)
        return

    token = create_session(user[0])
    json_response({'token': token, 'user_id': user[0]})

def route_scrape(method, params, auth):
    """POST /api/scrape"""
    if not auth:
        json_error('Unauthorized', 401)
        return

    if method != 'POST':
        json_error('Method not allowed', 405)
        return

    user_id = verify_token(auth)
    if not user_id:
        json_error('Unauthorized', 401)
        return

    url = params.get('url', '')
    if not url:
        json_error('URL required', 400)
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'INSERT INTO jobs (user_id, url, status, results_count, created_at) VALUES (?, ?, ?, ?, ?)',
        (user_id, url, 'pending', 0, datetime.now().isoformat())
    )
    conn.commit()
    job_id = c.lastrowid

    # Scrape
    emails = scrape_emails_from_url(url)

    c.execute('UPDATE jobs SET status = ?, results_count = ?, started_at = ?, finished_at = ? WHERE id = ?',
              ('completed', len(emails), datetime.now().isoformat(), datetime.now().isoformat(), job_id))

    for email in emails:
        c.execute(
            'INSERT INTO emails (job_id, email, source_url, extracted_at) VALUES (?, ?, ?, ?)',
            (job_id, email['email'], email['url'], datetime.now().isoformat())
        )

    conn.commit()
    conn.close()

    json_response({'job_id': job_id, 'status': 'completed', 'results_count': len(emails)})

def route_results(method, params, auth, job_id=None):
    """GET /api/results or /api/results/{job_id}"""
    if not auth:
        json_error('Unauthorized', 401)
        return

    user_id = verify_token(auth)
    if not user_id:
        json_error('Unauthorized', 401)
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if job_id:
        c.execute('SELECT * FROM jobs WHERE id = ? AND user_id = ?', (job_id, user_id))
        job = c.fetchone()

        if not job:
            conn.close()
            json_error('Job not found', 404)
            return

        c.execute('SELECT email, source_url, extracted_at FROM emails WHERE job_id = ?', (job_id,))
        emails = c.fetchall()
        conn.close()

        json_response({
            'job_id': job[0],
            'url': job[2],
            'status': job[3],
            'results_count': job[4],
            'created_at': job[6],
            'emails': [{'email': e[0], 'source_url': e[1], 'extracted_at': e[2]} for e in emails]
        })
    else:
        c.execute(
            'SELECT id, url, status, results_count, created_at FROM jobs WHERE user_id = ? ORDER BY created_at DESC',
            (user_id,)
        )
        jobs = c.fetchall()
        conn.close()

        json_response({
            'jobs': [{'id': j[0], 'url': j[1], 'status': j[2], 'results_count': j[3], 'created_at': j[4]} for j in jobs]
        })

# ============= Main CGI Handler =============

def main():
    init_db()

    # Parse request
    method = os.environ.get('REQUEST_METHOD', 'GET')
    path = os.environ.get('PATH_INFO', '/')
    query_string = os.environ.get('QUERY_STRING', '')
    content_type = os.environ.get('CONTENT_TYPE', '')
    content_length = int(os.environ.get('CONTENT_LENGTH', 0))

    # Parse body
    params = {}
    auth = None

    if method == 'POST':
        if 'application/json' in content_type:
            try:
                body = sys.stdin.read(content_length)
                params = json.loads(body)
            except:
                params = {}
        else:
            form = cgi.FieldStorage()
            params = {key: form.getvalue(key) for key in form.keys()}
    elif method == 'GET' and query_string:
        params = urllib.parse.parse_qs(query_string)
        params = {k: v[0] if v else '' for k, v in params.items()}

    # Get auth header
    auth_header = os.environ.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Bearer '):
        auth = auth_header[7:]

    # Route
    if path == '/api/health':
        route_health()
    elif path == '/api/login':
        route_login(method, params)
    elif path == '/api/scrape':
        route_scrape(method, params, auth)
    elif path.startswith('/api/results/'):
        job_id = int(path.split('/')[-1])
        route_results(method, params, auth, job_id)
    elif path == '/api/results':
        route_results(method, params, auth)
    else:
        json_error('Not found', 404)

if __name__ == '__main__':
    main()
