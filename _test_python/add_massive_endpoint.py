#!/usr/bin/env python3
"""
Adicionar endpoint de busca massiva ao app.py via SSH
"""

import paramiko
import sys
import io
from _secrets import vps_host, vps_user, vps_pass

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

VPS_HOST = vps_host()
VPS_USER = vps_user()
VPS_PORT = 22
VPS_PASSWORD = vps_pass()

print("="*80)
print("🚀 ADICIONANDO ENDPOINT DE BUSCA MASSIVA")
print("="*80)
print()

try:
    # Read massive search endpoint code
    with open('massive_search_endpoint.py', 'r', encoding='utf-8') as f:
        massive_search_code = f.read()

    # Connect to VPS
    print(f"Conectando em {VPS_HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASSWORD)

    print("✅ Conectado!")
    print()

    # Check if endpoint already exists
    print("🔍 Verificando se endpoint já existe...")
    stdin, stdout, stderr = ssh.exec_command('cd /opt/extrator-api && grep -q "/api/search/massive" app.py && echo "EXISTS" || echo "NOT_EXISTS"')
    check_result = stdout.read().decode().strip()

    if "EXISTS" in check_result:
        print("✅ Endpoint /api/search/massive já existe!")
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

    import time
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

    print()
    print("="*80)
    print("✅ ENDPOINT ADICIONADO COM SUCESSO!")
    print("="*80)

except Exception as e:
    print(f"❌ Erro: {e}")
    sys.exit(1)
