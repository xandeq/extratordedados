"""Envia e executa script de setup no VPS"""
import paramiko
import sys
import os
import time

sys.stdout.reconfigure(encoding='utf-8')

VPS_HOST = "185.173.110.180"
VPS_USER = "root"
VPS_PASSWORD = "1982X@ndeq1982#"

print("Conectando ao VPS...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASSWORD, timeout=30)

# Enviar script via SFTP
print("Enviando script de setup...")
sftp = ssh.open_sftp()
local_script = os.path.join(os.path.dirname(__file__), 'setup_advanced_scrapers.sh')
remote_script = '/tmp/setup_advanced_scrapers.sh'
sftp.put(local_script, remote_script)
sftp.close()

# Dar permissão de execução e executar
print("Executando setup...")
print("=" * 80)

stdin, stdout, stderr = ssh.exec_command(f"chmod +x {remote_script} && bash {remote_script}", timeout=600)

# Ler output em tempo real
while True:
    line = stdout.readline()
    if not line:
        break
    print(line.rstrip())

# Verificar erros
errors = stderr.read().decode()
if errors and 'Successfully' not in errors:
    print("\nERROS:")
    print(errors)

print("=" * 80)
print("\n[OK] Setup concluido!")

# Health check final
time.sleep(2)
stdin, stdout, stderr = ssh.exec_command("curl -s http://localhost:5000/api/health")
health = stdout.read().decode()
print(f"\n[HEALTH CHECK] {health}")

ssh.close()
