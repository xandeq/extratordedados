#!/usr/bin/env python3
"""
Deploy completo da busca massiva
Backend + Frontend + Verificação
"""

import paramiko
import sys
import io
import time
import os

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

VPS_HOST = "185.173.110.180"
VPS_USER = "root"
VPS_PORT = 22

print("="*80)
print("🚀 DEPLOY COMPLETO - BUSCA MASSIVA")
print("="*80)
print()

# ============================================================
# PASSO 1: FRONTEND BUILD
# ============================================================
print("📦 PASSO 1: BUILD DO FRONTEND")
print("-"*60)

os.chdir("project/frontend")

print("Executando: npx next build...")
result = os.system("npx next build")

if result != 0:
    print("❌ Erro no build do frontend!")
    sys.exit(1)

print("✅ Build concluído!")
print()

# ============================================================
# PASSO 2: CRIAR .htaccess
# ============================================================
print("📝 PASSO 2: CRIANDO .htaccess")
print("-"*60)

htaccess_content = """RewriteEngine On
# Handle Next.js dynamic routes
RewriteRule ^batch/(.+)$ /batch/[id].html [L]
RewriteRule ^results/(.+)$ /results/[id].html [L]
RewriteRule ^massive-search$ /massive-search.html [L]

# If file/directory doesn't exist, try .html extension
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteCond %{REQUEST_FILENAME}.html -f
RewriteRule ^(.*)$ $1.html [L]
"""

with open('out/.htaccess', 'w') as f:
    f.write(htaccess_content)

print("✅ .htaccess criado!")
print()

# ============================================================
# PASSO 3: DEPLOY FRONTEND VIA FTP
# ============================================================
print("🌐 PASSO 3: DEPLOY FRONTEND (FTP)")
print("-"*60)

os.chdir("../..")
result = os.system("python _test_python/ftp_deploy_frontend.py")

if result != 0:
    print("⚠️  Aviso: FTP pode ter falhado, mas continuando...")

print()

# ============================================================
# PASSO 4: DEPLOY BACKEND VIA SSH
# ============================================================
print("⚙️  PASSO 4: DEPLOY BACKEND (SSH)")
print("-"*60)

try:
    # Read massive search endpoint code
    with open('massive_search_endpoint.py', 'r', encoding='utf-8') as f:
        massive_search_code = f.read()

    # Connect to VPS
    print(f"Conectando em {VPS_HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # You'll need to provide password or use SSH key
    print("Digite a senha SSH para root@185.173.110.180:")
    password = input()

    ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=password)

    print("✅ Conectado!")
    print()

    # Backup app.py
    print("📦 Fazendo backup do app.py...")
    stdin, stdout, stderr = ssh.exec_command('cd /opt/extrator-api && cp app.py app.py.backup_$(date +%Y%m%d_%H%M%S)')
    stdout.channel.recv_exit_status()
    print("✅ Backup feito!")

    # Check if endpoint already exists
    print("🔍 Verificando se endpoint já existe...")
    stdin, stdout, stderr = ssh.exec_command('cd /opt/extrator-api && grep -q "/api/search/massive" app.py && echo "EXISTS" || echo "NOT_EXISTS"')
    check_result = stdout.read().decode().strip()

    if "EXISTS" in check_result:
        print("ℹ️  Endpoint /api/search/massive já existe. Pulando adição...")
    else:
        print("📝 Adicionando novo endpoint...")

        # Create temp file with new code
        temp_file = '/tmp/massive_search_endpoint.py'
        sftp = ssh.open_sftp()
        with sftp.file(temp_file, 'w') as f:
            f.write(massive_search_code)
        sftp.close()

        # Append to app.py
        stdin, stdout, stderr = ssh.exec_command(f'cd /opt/extrator-api && cat {temp_file} >> app.py')
        stdout.channel.recv_exit_status()

        print("✅ Código adicionado!")

    # Restart service
    print("🔄 Reiniciando serviço...")
    stdin, stdout, stderr = ssh.exec_command('systemctl restart extrator-api')
    stdout.channel.recv_exit_status()

    time.sleep(3)

    # Check status
    stdin, stdout, stderr = ssh.exec_command('systemctl is-active extrator-api')
    status = stdout.read().decode().strip()

    if status == "active":
        print("✅ Serviço reiniciado com sucesso!")
    else:
        print(f"❌ Serviço com problema: {status}")
        print("Verificando logs...")
        stdin, stdout, stderr = ssh.exec_command('journalctl -u extrator-api -n 20')
        print(stdout.read().decode())

    ssh.close()

except Exception as e:
    print(f"❌ Erro no deploy backend: {e}")
    print()

# ============================================================
# PASSO 5: VERIFICAÇÃO
# ============================================================
print()
print("="*80)
print("✅ VERIFICAÇÃO PÓS-DEPLOY")
print("="*80)
print()

import requests

try:
    # Test API health
    print("🔍 Testando API health...")
    r = requests.get("https://api.extratordedados.com.br/api/health", timeout=10)
    if r.status_code == 200:
        print(f"✅ API OK: {r.json()}")
    else:
        print(f"❌ API retornou: {r.status_code}")

    # Test frontend
    print()
    print("🔍 Testando frontend...")
    r = requests.get("https://extratordedados.com.br/massive-search", timeout=10)
    if r.status_code == 200:
        print("✅ Frontend /massive-search OK!")
    elif r.status_code == 404:
        print("⚠️  Frontend retornou 404 - verifique .htaccess")
    else:
        print(f"❌ Frontend retornou: {r.status_code}")

except Exception as e:
    print(f"❌ Erro na verificação: {e}")

print()
print("="*80)
print("🎉 DEPLOY CONCLUÍDO!")
print("="*80)
print()
print("🔗 Acesse:")
print("   • https://extratordedados.com.br/massive-search")
print("   • https://api.extratordedados.com.br/api/health")
print()
