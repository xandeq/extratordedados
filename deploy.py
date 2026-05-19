"""
deploy.py -- Pipeline unificado de deploy
  Backend  -> VPS 185.173.110.180 via SSH/SFTP
  Frontend -> HostGator via FTP

Uso:
  python deploy.py           # deploy completo
  python deploy.py backend   # só backend
  python deploy.py frontend  # só frontend

Credenciais (em ordem de prioridade):
  1. AWS Secrets Manager (secret: extratordedados/prod)
  2. Arquivo .deploy.env na raiz do projeto
  3. Variáveis de ambiente
"""

import sys
import os
import json
import time
import subprocess
import ftplib
import paramiko

ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(ROOT, 'app', 'frontend')
OUT_DIR      = os.path.join(FRONTEND_DIR, 'out')
APP_PY       = os.path.join(ROOT, 'app', 'backend', 'app.py')
REQ_TXT      = os.path.join(ROOT, 'app', 'backend', 'requirements.txt')
SECRETS_CACHE_PATH = os.path.join(ROOT, '.secrets.cache.json')

# ?? Credenciais ??????????????????????????????????????????????????????????????

def _load_deploy_env():
    """Lê .deploy.env (key=value, um por linha)."""
    path = os.path.join(ROOT, '.deploy.env')
    data = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    data[k.strip()] = v.strip()
    return data

def _load_secrets_cache():
    try:
        with open(SECRETS_CACHE_PATH, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _save_secret_cache(secret_id, secret_data):
    if not secret_id or not isinstance(secret_data, dict):
        return
    cache = _load_secrets_cache()
    cache[secret_id] = secret_data
    try:
        with open(SECRETS_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _load_aws_secrets():
    """Tenta AWS SM via CLI; se falhar, usa cache local persistido."""
    try:
        import subprocess, json as _json
        result = subprocess.run(
            ['python', '-m', 'awscli', 'secretsmanager', 'get-secret-value',
             '--secret-id', 'extratordedados/prod',
             '--query', 'SecretString', '--output', 'text'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            data = _json.loads(result.stdout.strip())
            if isinstance(data, dict):
                _save_secret_cache('extratordedados/prod', data)
                return data
    except Exception as e:
        print(f"   [AWS SM] indisponivel ({type(e).__name__}) -- usando fallback")
    cached = _load_secrets_cache().get('extratordedados/prod')
    return cached if isinstance(cached, dict) else {}

def get_credentials():
    print("Carregando credenciais...")
    aws  = _load_aws_secrets()
    env  = _load_deploy_env()
    def pick(key, default=''):
        return aws.get(key) or env.get(key) or os.environ.get(key, default)

    creds = {
        'VPS_HOST': pick('VPS_HOST', '185.173.110.180'),
        'VPS_USER': pick('VPS_USER', 'root'),
        'VPS_PASS': pick('VPS_PASS'),
        'DB_PASS':  pick('DB_PASS'),
        'FTP_HOST': pick('FTP_HOST', 'ftp.extratordedados.com.br'),
        'FTP_USER': pick('FTP_USER', 'alexa084'),
        'FTP_PASS': pick('FTP_PASS'),
        'FTP_ROOT': pick('FTP_ROOT', '/'),
    }
    if not creds['VPS_PASS']:
        print("\nERRO: VPS_PASS não encontrado.")
        print("Adicione ao arquivo .deploy.env:")
        print("  VPS_PASS=sua_senha_aqui")
        sys.exit(1)
    if not creds['FTP_PASS']:
        print("\nERRO: FTP_PASS não encontrado.")
        print("Adicione ao AWS SM (extratordedados/prod) ou .deploy.env:")
        print("  FTP_PASS=sua_senha_ftp_aqui")
        sys.exit(1)
    print("   Credenciais OK\n")
    return creds

# ?? Backend ???????????????????????????????????????????????????????????????????

def deploy_backend(creds):
    print("=" * 55)
    print("BACKEND -- SSH -> VPS")
    print("=" * 55)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando a {creds['VPS_HOST']}...")
    _vps_key_path = r'C:\Users\acq20\.ssh\id_ed25519_vps'
    if os.path.exists(_vps_key_path):
        _pkey = paramiko.Ed25519Key.from_private_key_file(_vps_key_path)
        ssh.connect(creds['VPS_HOST'], username=creds['VPS_USER'],
                    pkey=_pkey, timeout=15)
    else:
        ssh.connect(creds['VPS_HOST'], username=creds['VPS_USER'],
                    password=creds['VPS_PASS'], timeout=15)
    print("   Conectado\n")

    def run(cmd, timeout=60):
        _, out, err = ssh.exec_command(cmd, timeout=timeout)
        return (out.read().decode('utf-8', errors='replace').strip(),
                err.read().decode('utf-8', errors='replace').strip())

    # 1. Backup
    print("1. Backup de app.py...")
    run('cp /opt/extrator-api/app.py /opt/extrator-api/app.py.bak')
    print("   OK")

    # 2. Upload
    print("\n2. Upload de arquivos...")
    IMAGE_GEN_PY = os.path.join(ROOT, 'app', 'backend', 'image_gen.py')
    EMAIL_PROVIDERS_PY = os.path.join(ROOT, 'app', 'backend', 'email_providers.py')
    DB_UTILS_PY = os.path.join(ROOT, 'app', 'backend', 'db_utils.py')
    EMAIL_CAMPAIGNS_PY = os.path.join(ROOT, 'app', 'backend', 'email_campaigns.py')
    with ssh.open_sftp() as sftp:
        sftp.put(APP_PY,  '/opt/extrator-api/app.py')
        print("   app.py enviado")
        sftp.put(REQ_TXT, '/opt/extrator-api/requirements.txt')
        print("   requirements.txt enviado")
        if os.path.exists(DB_UTILS_PY):
            sftp.put(DB_UTILS_PY, '/opt/extrator-api/db_utils.py')
            print("   db_utils.py enviado")
        if os.path.exists(IMAGE_GEN_PY):
            sftp.put(IMAGE_GEN_PY, '/opt/extrator-api/image_gen.py')
            print("   image_gen.py enviado")
        if os.path.exists(EMAIL_PROVIDERS_PY):
            sftp.put(EMAIL_PROVIDERS_PY, '/opt/extrator-api/email_providers.py')
            print("   email_providers.py enviado")
        if os.path.exists(EMAIL_CAMPAIGNS_PY):
            sftp.put(EMAIL_CAMPAIGNS_PY, '/opt/extrator-api/email_campaigns.py')
            print("   email_campaigns.py enviado")

    # 3. Dependências
    print("\n3. Instalando dependências...")
    out, err = run('/opt/extrator-api/venv/bin/pip install -r /opt/extrator-api/requirements.txt', timeout=120)
    if 'already satisfied' in out or 'Successfully installed' in out:
        print("   Dependências OK")
    else:
        print(f"   {out[:400]}")

    # 4. Restart
    print("\n4. Reiniciando serviço...")
    run('systemctl restart extrator-api')
    time.sleep(3)
    status, _ = run('systemctl is-active extrator-api')
    print(f"   Status: {status}")

    if status != 'active':
        logs, _ = run('journalctl -u extrator-api -n 30 --no-pager')
        print(f"   Logs:\n{logs}")
        ssh.close()
        return False

    # 5. Health check
    print("\n5. Health check...")
    health, _ = run('curl -s http://127.0.0.1:8000/api/health')
    print(f"   {health}")

    ssh.close()
    return True

# ?? Frontend ??????????????????????????????????????????????????????????????????

HTACCESS = """\
# trailingSlash: true -> diretorios com index.html (Apache serve nativamente)
DirectoryIndex index.html

# Disable server-side caching for HTML files (force fresh serve)
<FilesMatch "\\.html$">
    Header set Cache-Control "no-cache, no-store, must-revalidate"
    Header set Pragma "no-cache"
    Header set Expires "0"
    Header unset ETag
    FileETag None
</FilesMatch>

# Cache static assets aggressively (they have content-hashed names)
<FilesMatch "\\.(js|css|png|jpg|ico|woff2?)$">
    Header set Cache-Control "public, max-age=31536000, immutable"
</FilesMatch>

RewriteEngine On
RewriteBase /

# Rotas dinamicas com ID (batch/123 -> batch/[id]/index.html)
RewriteRule ^batch/[^/]+/?$ /batch/[id]/index.html [L]
RewriteRule ^results/[^/]+/?$ /results/[id]/index.html [L]
"""

def build_frontend():
    print("=" * 55)
    print("FRONTEND -- Build Next.js")
    print("=" * 55)
    result = subprocess.run(
        'npx next build',
        cwd=FRONTEND_DIR,
        capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        print("ERRO no build:")
        print(result.stdout[-2000:])
        print(result.stderr[-1000:])
        return False
    # Estatísticas do build
    for line in result.stdout.splitlines():
        if any(x in line for x in ['Route', 'chunks', 'First Load', 'Page', '?', '?', '?']):
            print(' ', line)
    print("   Build OK\n")
    return True

def write_htaccess():
    path = os.path.join(OUT_DIR, '.htaccess')
    with open(path, 'w', newline='\n') as f:
        f.write(HTACCESS)
    print("   .htaccess criado")

def deploy_frontend(creds):
    print("=" * 55)
    print("FRONTEND -- FTP -> HostGator")
    print("=" * 55)

    if not os.path.isdir(OUT_DIR):
        print("ERRO: diretório out/ não encontrado. Rode o build primeiro.")
        return False

    write_htaccess()

    ftp = ftplib.FTP()
    ftp.connect(creds['FTP_HOST'], 21, timeout=60)
    ftp.login(creds['FTP_USER'], creds['FTP_PASS'])
    ftp.set_pasv(True)
    ftp.encoding = 'utf-8'
    print(f"Conectado ao FTP: {creds['FTP_HOST']}\n")

    uploaded = [0]
    errors   = [0]

    def ensure_dir(path):
        dirs = path.strip('/').split('/')
        cur = ''
        for d in dirs:
            cur += '/' + d
            try:
                ftp.cwd(cur)
            except ftplib.error_perm:
                try:
                    ftp.mkd(cur)
                    try:
                        ftp.voidcmd(f'SITE CHMOD 755 {cur}')
                    except Exception:
                        pass
                    ftp.cwd(cur)
                except ftplib.error_perm:
                    pass

    def upload_dir(local, remote):
        ensure_dir(remote)
        for item in sorted(os.listdir(local)):
            lp = os.path.join(local, item)
            rp = (remote.rstrip('/') + '/' + item) if remote != '/' else '/' + item
            if os.path.isdir(lp):
                upload_dir(lp, rp)
            else:
                try:
                    with open(lp, 'rb') as f:
                        ftp.storbinary(f'STOR {rp}', f)
                    try:
                        ftp.voidcmd(f'SITE CHMOD 644 {rp}')
                    except Exception:
                        pass
                    uploaded[0] += 1
                    if '/_next/static/chunks/' not in rp:
                        print(f"  OK: {rp}")
                except Exception as e:
                    errors[0] += 1
                    print(f"  FAIL: {rp} -- {e}")

    upload_dir(OUT_DIR, creds['FTP_ROOT'])
    ftp.quit()

    print(f"\nFTP: {uploaded[0]} arquivos enviados, {errors[0]} erros")
    return errors[0] == 0

# ?? Main ??????????????????????????????????????????????????????????????????????

def rollback_backend(creds):
    """Restore app.py from .bak created during last deploy."""
    print("=" * 55)
    print("ROLLBACK -- Restaurando backup do backend")
    print("=" * 55)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando a {creds['VPS_HOST']}...")
    _vps_key_path = r'C:\Users\acq20\.ssh\id_ed25519_vps'
    if os.path.exists(_vps_key_path):
        _pkey = paramiko.Ed25519Key.from_private_key_file(_vps_key_path)
        ssh.connect(creds['VPS_HOST'], username=creds['VPS_USER'],
                    pkey=_pkey, timeout=15)
    else:
        ssh.connect(creds['VPS_HOST'], username=creds['VPS_USER'],
                    password=creds['VPS_PASS'], timeout=15)
    print("   Conectado\n")

    def run(cmd, timeout=60):
        _, out, err = ssh.exec_command(cmd, timeout=timeout)
        return (out.read().decode('utf-8', errors='replace').strip(),
                err.read().decode('utf-8', errors='replace').strip())

    # Verify backup exists
    out, _ = run('ls -lh /opt/extrator-api/app.py.bak 2>/dev/null || echo MISSING')
    if 'MISSING' in out:
        print("ERRO: /opt/extrator-api/app.py.bak não encontrado.")
        print("   Faça um deploy primeiro para criar o backup.")
        ssh.close()
        return False
    print(f"1. Backup encontrado: {out}")

    # Restore
    print("\n2. Restaurando app.py.bak -> app.py...")
    run('cp /opt/extrator-api/app.py.bak /opt/extrator-api/app.py')
    print("   OK")

    # Restart
    print("\n3. Reiniciando serviço...")
    run('systemctl restart extrator-api')
    time.sleep(3)
    status, _ = run('systemctl is-active extrator-api')
    print(f"   Status: {status}")

    if status != 'active':
        logs, _ = run('journalctl -u extrator-api -n 20 --no-pager')
        print(f"   Logs:\n{logs}")
        ssh.close()
        return False

    # Health check
    print("\n4. Health check...")
    health, _ = run('curl -s http://127.0.0.1:8000/api/health')
    print(f"   {health}")

    ssh.close()
    return True


def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else 'all'
    if mode not in ('all', 'backend', 'frontend', 'rollback'):
        print("Uso: python deploy.py [all|backend|frontend|rollback]")
        sys.exit(1)

    print("\n[DEPLOY] DEPLOY PIPELINE - extratordedados.com.br")
    print(f"   Modo: {mode}\n")
    t0 = time.time()

    creds = get_credentials()
    ok_backend = ok_frontend = True

    if mode == 'rollback':
        ok = rollback_backend(creds)
        elapsed = time.time() - t0
        print("=" * 55)
        print(f"  Rollback: {'✓ OK' if ok else '✗ FALHOU'}")
        print(f"  Tempo:    {elapsed:.0f}s")
        print("=" * 55)
        print(f"\n  API:  https://api.extratordedados.com.br/api/health\n")
        sys.exit(0 if ok else 1)

    if mode in ('all', 'backend'):
        ok_backend = deploy_backend(creds)
        print()

    if mode in ('all', 'frontend'):
        if build_frontend():
            ok_frontend = deploy_frontend(creds)
        else:
            ok_frontend = False
        print()

    elapsed = time.time() - t0
    print("=" * 55)
    if mode in ('all', 'backend'):
        print(f"  Backend:  {'? OK' if ok_backend  else '? FALHOU'}")
    if mode in ('all', 'frontend'):
        print(f"  Frontend: {'? OK' if ok_frontend else '? FALHOU'}")
    print(f"  Tempo:    {elapsed:.0f}s")
    print("=" * 55)
    print(f"\n  API:  https://api.extratordedados.com.br/api/health")
    print(f"  Site: https://extratordedados.com.br\n")

if __name__ == '__main__':
    main()
