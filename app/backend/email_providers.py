"""
Email provider helpers — pure functions, no DB dependency.
Extracted from app.py for progressive modularization.

Providers: Brevo · Mailjet · SendPulse · Resend
"""
import os
import base64
import re
import time
import urllib.parse
import requests

# ── Constants ─────────────────────────────────────────────────────────────────

# Provider daily quotas (free-tier defaults)
EMAIL_PROVIDERS = [
    {'name': 'brevo',     'daily_limit': 300},
    {'name': 'mailjet',   'daily_limit': 200},
    {'name': 'sendpulse', 'daily_limit': 500},   # 15k/month free (~500/day)
    {'name': 'resend',    'daily_limit': 100},
]

# 1×1 transparent GIF (open-tracking pixel)
TRACKING_PIXEL = base64.b64decode(
    'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
)

_HREF_RE = re.compile(r'href="([^"]+)"')

# ── Credential getters ────────────────────────────────────────────────────────

def get_brevo_credentials() -> dict | None:
    api_key = os.environ.get('BREVO_API_KEY', '')
    if not api_key:
        return None
    return {
        'BREVO_API_KEY':    api_key,
        'BREVO_FROM_EMAIL': os.environ.get('BREVO_FROM_EMAIL', 'noreply@extratordedados.com.br'),
        'BREVO_FROM_NAME':  os.environ.get('BREVO_FROM_NAME', 'Extrator DIAX'),
    }


def get_mailjet_credentials() -> dict | None:
    api_key = os.environ.get('MAILJET_API_KEY', '')
    api_secret = os.environ.get('MAILJET_API_SECRET', '')
    if not api_key or not api_secret:
        return None
    return {
        'MAILJET_API_KEY':    api_key,
        'MAILJET_API_SECRET': api_secret,
        'MAILJET_FROM_EMAIL': os.environ.get('MAILJET_FROM_EMAIL', 'noreply@extratordedados.com.br'),
        'MAILJET_FROM_NAME':  os.environ.get('MAILJET_FROM_NAME', 'Extrator DIAX'),
    }


def get_resend_credentials() -> dict | None:
    api_key = os.environ.get('RESEND_API_KEY', '')
    if not api_key:
        return None
    return {
        'RESEND_API_KEY':    api_key,
        'RESEND_FROM_EMAIL': os.environ.get('RESEND_FROM_EMAIL', 'noreply@extratordedados.com.br'),
    }


# ── Base URL ───────────────────────────────────────────────────────────────────

def get_base_url() -> str:
    return os.environ.get('API_BASE_URL', 'https://api.extratordedados.com.br')


# ── Tracking injection ────────────────────────────────────────────────────────

def inject_tracking(html_body: str, send_token: str, base_url: str) -> str:
    """Rewrite <a href> links for click tracking; inject open-pixel before </body>."""
    pixel_url = f"{base_url}/api/track/o/{send_token}.png"
    pixel_tag = f'<img src="{pixel_url}" width="1" height="1" alt="" style="display:none"/>'

    def replace_link(m: re.Match) -> str:
        original_url = m.group(1)
        if 'track/o/' in original_url or 'track/c/' in original_url:
            return m.group(0)
        encoded = urllib.parse.quote(original_url, safe='')
        tracked = f'{base_url}/api/track/c/{send_token}?url={encoded}'
        return f'href="{tracked}"'

    tracked_html = _HREF_RE.sub(replace_link, html_body)
    if '</body>' in tracked_html.lower():
        tracked_html = tracked_html.replace('</body>', f'{pixel_tag}</body>')
    else:
        tracked_html += pixel_tag
    return tracked_html


# ── Provider send functions ───────────────────────────────────────────────────

def send_via_brevo(to_email: str, to_name: str, subject: str, html_body: str, text_body: str = '') -> bool:
    try:
        creds = get_brevo_credentials()
        if not creds:
            return False
        payload = {
            'sender': {'name': creds['BREVO_FROM_NAME'], 'email': creds['BREVO_FROM_EMAIL']},
            'to': [{'email': to_email, 'name': to_name or to_email}],
            'subject': subject,
            'htmlContent': html_body,
        }
        if text_body:
            payload['textContent'] = text_body
        for attempt in range(2):
            resp = requests.post(
                'https://api.brevo.com/v3/smtp/email',
                headers={'api-key': creds['BREVO_API_KEY'], 'Content-Type': 'application/json'},
                json=payload,
                timeout=15,
            )
            if resp.status_code in (200, 201):
                return True
            if resp.status_code == 429 and attempt == 0:
                time.sleep(1)
                continue
            break
        return False
    except Exception as e:
        print(f'[EMAIL/brevo] error: {e}')
        return False


def send_via_mailjet(to_email: str, to_name: str, subject: str, html_body: str, text_body: str = '') -> bool:
    try:
        creds = get_mailjet_credentials()
        if not creds:
            return False
        payload = {
            'Messages': [{
                'From': {'Email': creds['MAILJET_FROM_EMAIL'], 'Name': creds['MAILJET_FROM_NAME']},
                'To': [{'Email': to_email, 'Name': to_name or to_email}],
                'Subject': subject,
                'HTMLPart': html_body,
                'TextPart': text_body or '',
            }]
        }
        for attempt in range(2):
            resp = requests.post(
                'https://api.mailjet.com/v3.1/send',
                auth=(creds['MAILJET_API_KEY'], creds['MAILJET_API_SECRET']),
                json=payload,
                timeout=15,
            )
            if resp.status_code == 200:
                return True
            if resp.status_code == 429 and attempt == 0:
                time.sleep(1)
                continue
            break
        return False
    except Exception as e:
        print(f'[EMAIL/mailjet] error: {e}')
        return False


def send_via_sendpulse(to_email: str, to_name: str, subject: str, html_body: str, text_body: str = '') -> bool:
    """SendPulse SMTP API — free plan 15k/month."""
    try:
        client_id = os.environ.get('SENDPULSE_CLIENT_ID', '')
        client_secret = os.environ.get('SENDPULSE_CLIENT_SECRET', '')
        if not client_id or not client_secret:
            return False
        from_email = os.environ.get('SENDPULSE_FROM_EMAIL', 'noreply@extratordedados.com.br')
        from_name = os.environ.get('SENDPULSE_FROM_NAME', 'Extrator DIAX')
        token_resp = requests.post('https://api.sendpulse.com/oauth/access_token', json={
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret,
        }, timeout=10)
        if token_resp.status_code != 200:
            return False
        token = token_resp.json().get('access_token', '')
        if not token:
            return False
        payload = {
            'email': {
                'html': html_body,
                'text': text_body or '',
                'subject': subject,
                'from': {'name': from_name, 'email': from_email},
                'to': [{'name': to_name or to_email, 'email': to_email}],
            }
        }
        for attempt in range(2):
            resp = requests.post(
                'https://api.sendpulse.com/smtp/emails',
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                json=payload,
                timeout=15,
            )
            if resp.status_code in (200, 201):
                return True
            if resp.status_code == 429 and attempt == 0:
                time.sleep(1)
                continue
            break
        return False
    except Exception as e:
        print(f'[EMAIL/sendpulse] error: {e}')
        return False


def send_via_resend(to_email: str, to_name: str, subject: str, html_body: str, text_body: str = '') -> bool:
    try:
        creds = get_resend_credentials()
        if not creds:
            return False
        payload = {
            'from': creds['RESEND_FROM_EMAIL'],
            'to': [to_email],
            'subject': subject,
            'html': html_body,
        }
        if text_body:
            payload['text'] = text_body
        for attempt in range(2):
            resp = requests.post(
                'https://api.resend.com/emails',
                headers={'Authorization': f'Bearer {creds["RESEND_API_KEY"]}', 'Content-Type': 'application/json'},
                json=payload,
                timeout=15,
            )
            if resp.status_code in (200, 201):
                return True
            if resp.status_code == 429 and attempt == 0:
                time.sleep(1)
                continue
            break
        return False
    except Exception as e:
        print(f'[EMAIL/resend] error: {e}')
        return False


# ── Provider dispatch map ──────────────────────────────────────────────────────

PROVIDER_SEND_FN: dict = {
    'brevo':     send_via_brevo,
    'mailjet':   send_via_mailjet,
    'sendpulse': send_via_sendpulse,
    'resend':    send_via_resend,
}
