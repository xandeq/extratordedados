"""
Fetch credentials from AWS Secrets Manager (extratordedados/prod).
Falls back to environment variables if AWS SM is unavailable.
"""
import os
import json

_cache = None

def get_secrets():
    global _cache
    if _cache is not None:
        return _cache

    try:
        import boto3
        client = boto3.client('secretsmanager', region_name='us-east-1')
        response = client.get_secret_value(SecretId='extratordedados/prod')
        _cache = json.loads(response['SecretString'])
    except Exception as e:
        print(f"[AWS SM] {e} — using env vars as fallback")
        _cache = {}

    return _cache


def get(key, default=''):
    secrets = get_secrets()
    return secrets.get(key) or os.environ.get(key, default)


# Convenience accessors
def vps_host():
    return get('VPS_HOST', '185.173.110.180')

def vps_user():
    return get('VPS_USER', 'root')

def vps_pass():
    return get('VPS_PASS')

def db_password():
    return get('DB_PASSWORD')

def ftp_host():
    return get('FTP_HOST')

def ftp_user():
    return get('FTP_USER')

def admin_password():
    return get('ADMIN_PASSWORD')

def apify_token():
    return get('APIFY_TOKEN')
