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
FRONTEND_DIR = os.path.join(ROOT, 'project', 'frontend')
OUT_DIR      = os.path.join(FRONTEND_DIR, 'out')
APP_PY       = os.path.join(ROOT, 'project', 'backend', 'app.py')
REQ_TXT      = os.path.join(ROOT, 'project', 'backend', 'requirements.txt')

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

def _load_aws_secrets():
    """Tenta AWS SM via CLI (subprocess) com timeout de 10s para nao travar no Windows."""
    try:
        import subprocess, json as _json
        result = subprocess.run(
            ['python', '-m', 'awscli', 'secretsmanager', 'get-secret-value',
             '--secret-id', 'extratordedados/prod',
             '--query', 'SecretString', '--output', 'text'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return _json.loads(result.stdout.strip())
    except Exception as e:
        print(f"   [AWS SM] indisponivel ({type(e).__name__}) -- usando fallback")
    return {}

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
        'FTP_PASS': pick('FTP_PASS', 'Alexandre10#'),
        'FTP_ROOT': pick('FTP_ROOT', '/extratordedados.com.br'),
    }
    if not creds['VPS_PASS']:
        print("\nERRO: VPS_PASS não encontrado.")
        print("Adicione ao arquivo .deploy.env:")
        print("  VPS_PASS=sua_senha_aqui")
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
    with ssh.open_sftp() as sftp:
        sftp.put(APP_PY,  '/opt/extrator-api/app.py')
        print("   app.py enviado")
        sftp.put(REQ_TXT, '/opt/extrator-api/requirements.txt')
        print("   requirements.txt enviado")

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

    ftp = ftplib.FTP(creds['FTP_HOST'])
    ftp.login(creds['FTP_USER'], creds['FTP_PASS'])
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
                    # Garante permissao 755 (rwxr-xr-x) para o Apache ler o diretorio
                    try:
                        ftp.voidcmd(f'SITE CHMOD 755 {cur}')
                    except Exception:
                        pass
                except ftplib.error_perm:
                    pass

    def upload_dir(local, remote):
        ensure_dir(remote)
        for item in os.listdir(local):
            lp = os.path.join(local, item)
            rp = remote + '/' + item
            if os.path.isdir(lp):
                upload_dir(lp, rp)
            else:
                try:
                    with open(lp, 'rb') as f:
                        ftp.storbinary(f'STOR {rp}', f)
                    # Garante permissao 644 (rw-r--r--) para o Apache ler o arquivo
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

def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else 'all'
    if mode not in ('all', 'backend', 'frontend'):
        print("Uso: python deploy.py [all|backend|frontend]")
        sys.exit(1)

    print("\n[DEPLOY] DEPLOY PIPELINE - extratordedados.com.br")
    print(f"   Modo: {mode}\n")
    t0 = time.time()

    creds = get_credentials()
    ok_backend = ok_frontend = True

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
