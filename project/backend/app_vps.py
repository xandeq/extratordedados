"""
Extrator de Dados - Backend Flask API
Roda na VPS Hostinger via Gunicorn
"""
import os
import json
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests as http_requests
from bs4 import BeautifulSoup
import re

app = Flask(__name__)
CORS(app, origins=["https://extratordedados.com.br", "http://extratordedados.com.br", "http://localhost:3000"])

# Config
DB_PATH = "/opt/extrator-api/extrator.db"
ADMIN_PASSWORD_HASH = hashlib.sha256("1982Xandeq1982#".encode()).hexdigest()

# ============= Database =============

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        password_hash TEXT,
        is_admin INTEGER DEFAULT 0,
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
        status TEXT DEFAULT 'pending',
        results_count INTEGER DEFAULT 0,
        created_at TEXT,
        started_at TEXT,
        finished_at TEXT,
        error_message TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY,
        job_id INTEGER,
        email TEXT,
        source_url TEXT,
        name TEXT,
        context TEXT,
        extracted_at TEXT,
        FOREIGN KEY(job_id) REFERENCES jobs(id)
    )''')

    # Create admin user
    c.execute('SELECT id FROM users WHERE username = ?', ('admin',))
    if not c.fetchone():
        c.execute(
            'INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)',
            ('admin', ADMIN_PASSWORD_HASH, datetime.now().isoformat())
        )

    conn.commit()
    conn.close()

# ============= Auth Helpers =============

def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_session(user_id):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=7)).isoformat()
    conn = get_db()
    conn.execute(
        'INSERT INTO sessions (user_id, token, created_at, expires_at) VALUES (?, ?, ?, ?)',
        (user_id, token, datetime.now().isoformat(), expires)
    )
    conn.commit()
    conn.close()
    return token

def get_user_from_token():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[7:]
    conn = get_db()
    row = conn.execute(
        'SELECT user_id FROM sessions WHERE token = ? AND expires_at > ?',
        (token, datetime.now().isoformat())
    ).fetchone()
    conn.close()
    return row['user_id'] if row else None

# ============= Scraping Engine =============

def scrape_emails(url, depth=1):
    """Extract emails from URL and optionally follow links"""
    all_emails = {}
    visited = set()

    def _scrape(target_url, current_depth):
        if target_url in visited or current_depth > depth:
            return
        visited.add(target_url)

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            resp = http_requests.get(target_url, timeout=15, headers=headers, verify=True)
            resp.encoding = resp.apparent_encoding or 'utf-8'
            soup = BeautifulSoup(resp.text, 'html.parser')

            # Regex for emails
            email_pattern = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'

            # From page text
            text = soup.get_text(separator=' ')
            for email in re.findall(email_pattern, text):
                email_lower = email.lower().strip('.')
                if email_lower not in all_emails and not _is_junk_email(email_lower):
                    all_emails[email_lower] = {
                        'email': email_lower,
                        'source_url': target_url
                    }

            # From mailto links
            for a_tag in soup.find_all('a', href=True):
                href = a_tag.get('href', '')
                if 'mailto:' in href:
                    email = href.replace('mailto:', '').split('?')[0].strip().lower()
                    if email and '@' in email and email not in all_emails:
                        name = a_tag.get_text(strip=True)
                        all_emails[email] = {
                            'email': email,
                            'source_url': target_url,
                            'name': name if name != email else ''
                        }

            # Follow internal links (depth > 1)
            if current_depth < depth:
                from urllib.parse import urljoin, urlparse
                base_domain = urlparse(target_url).netloc
                for a_tag in soup.find_all('a', href=True):
                    link = urljoin(target_url, a_tag['href'])
                    if urlparse(link).netloc == base_domain and link not in visited:
                        _scrape(link, current_depth + 1)

        except Exception:
            pass

    _scrape(url, 1)
    return list(all_emails.values())

def _is_junk_email(email):
    """Filter out common junk/fake emails"""
    junk = ['example.com', 'test.com', 'email.com', 'domain.com',
            'sentry.io', 'wixpress.com', 'webpack.js']
    return any(j in email for j in junk) or email.endswith('.png') or email.endswith('.jpg')

# ============= API Routes =============

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'service': 'extrator-api',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '')
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': 'Username e password obrigatorios'}), 400

    conn = get_db()
    user = conn.execute('SELECT id, password_hash, is_admin FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()

    if not user or hash_pw(password) != user['password_hash']:
        return jsonify({'error': 'Credenciais invalidas'}), 401

    token = create_session(user['id'])
    return jsonify({
        'token': token,
        'user_id': user['id'],
        'is_admin': bool(user['is_admin'])
    })

@app.route('/api/scrape', methods=['POST'])
def start_scrape():
    user_id = get_user_from_token()
    if not user_id:
        return jsonify({'error': 'Nao autorizado'}), 401

    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    depth = min(int(data.get('depth', 1)), 3)  # Max depth 3

    if not url:
        return jsonify({'error': 'URL obrigatoria'}), 400

    if not url.startswith('http'):
        url = 'https://' + url

    # Create job
    conn = get_db()
    c = conn.cursor()
    c.execute(
        'INSERT INTO jobs (user_id, url, status, created_at, started_at) VALUES (?, ?, ?, ?, ?)',
        (user_id, url, 'running', datetime.now().isoformat(), datetime.now().isoformat())
    )
    conn.commit()
    job_id = c.lastrowid

    # Scrape
    try:
        emails = scrape_emails(url, depth)

        for em in emails:
            c.execute(
                'INSERT INTO emails (job_id, email, source_url, name, extracted_at) VALUES (?, ?, ?, ?, ?)',
                (job_id, em['email'], em.get('source_url', url), em.get('name', ''), datetime.now().isoformat())
            )

        c.execute(
            'UPDATE jobs SET status = ?, results_count = ?, finished_at = ? WHERE id = ?',
            ('completed', len(emails), datetime.now().isoformat(), job_id)
        )
        conn.commit()
        conn.close()

        return jsonify({
            'job_id': job_id,
            'status': 'completed',
            'results_count': len(emails),
            'emails': emails
        })

    except Exception as e:
        c.execute(
            'UPDATE jobs SET status = ?, error_message = ?, finished_at = ? WHERE id = ?',
            ('failed', str(e), datetime.now().isoformat(), job_id)
        )
        conn.commit()
        conn.close()
        return jsonify({'error': str(e), 'job_id': job_id}), 500

@app.route('/api/results', methods=['GET'])
def list_jobs():
    user_id = get_user_from_token()
    if not user_id:
        return jsonify({'error': 'Nao autorizado'}), 401

    conn = get_db()
    jobs = conn.execute(
        'SELECT id, url, status, results_count, created_at, finished_at FROM jobs WHERE user_id = ? ORDER BY created_at DESC',
        (user_id,)
    ).fetchall()
    conn.close()

    return jsonify({
        'jobs': [dict(j) for j in jobs]
    })

@app.route('/api/results/<int:job_id>', methods=['GET'])
def get_job(job_id):
    user_id = get_user_from_token()
    if not user_id:
        return jsonify({'error': 'Nao autorizado'}), 401

    conn = get_db()
    job = conn.execute('SELECT * FROM jobs WHERE id = ? AND user_id = ?', (job_id, user_id)).fetchone()

    if not job:
        conn.close()
        return jsonify({'error': 'Job nao encontrado'}), 404

    emails = conn.execute(
        'SELECT email, source_url, name, extracted_at FROM emails WHERE job_id = ?', (job_id,)
    ).fetchall()
    conn.close()

    return jsonify({
        'job_id': job['id'],
        'url': job['url'],
        'status': job['status'],
        'results_count': job['results_count'],
        'created_at': job['created_at'],
        'finished_at': job['finished_at'],
        'emails': [dict(e) for e in emails]
    })

@app.route('/api/results/<int:job_id>', methods=['DELETE'])
def delete_job(job_id):
    user_id = get_user_from_token()
    if not user_id:
        return jsonify({'error': 'Nao autorizado'}), 401

    conn = get_db()
    conn.execute('DELETE FROM emails WHERE job_id = ?', (job_id,))
    conn.execute('DELETE FROM jobs WHERE id = ? AND user_id = ?', (job_id, user_id))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Job removido'})

# ============= Init =============

init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
