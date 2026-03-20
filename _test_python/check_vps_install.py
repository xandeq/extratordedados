"""Verifica instalação no VPS"""
import paramiko
import sys
from _secrets import vps_host, vps_user, vps_pass

sys.stdout.reconfigure(encoding='utf-8')

VPS_HOST = vps_host()
VPS_USER = vps_user()
VPS_PASSWORD = vps_pass()

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASSWORD)

print("=" * 80)
print("VERIFICANDO INSTALACAO NO VPS")
print("=" * 80)

# Verificar Playwright
stdin, stdout, stderr = ssh.exec_command("python3 -c 'import playwright; print(playwright.__version__)'")
pw_version = stdout.read().decode().strip()
if pw_version:
    print(f"[OK] Playwright instalado: v{pw_version}")
else:
    print("[ERRO] Playwright NAO encontrado")

# Verificar Instaloader
stdin, stdout, stderr = ssh.exec_command("python3 -c 'import instaloader; print(instaloader.__version__)'")
il_version = stdout.read().decode().strip()
if il_version:
    print(f"[OK] Instaloader instalado: v{il_version}")
else:
    print("[ERRO] Instaloader NAO encontrado")

# Verificar browsers do Playwright
stdin, stdout, stderr = ssh.exec_command("playwright --version")
pw_cli = stdout.read().decode().strip()
if pw_cli:
    print(f"[OK] Playwright CLI: {pw_cli}")

# Tentar instalar Playwright e browsers
print("\n" + "=" * 80)
print("INSTALANDO PLAYWRIGHT E BROWSERS...")
print("=" * 80)

stdin, stdout, stderr = ssh.exec_command("cd /opt/extrator-api && pip3 install --upgrade playwright instaloader", timeout=120)
install_out = stdout.read().decode()
print(install_out[-500:] if len(install_out) > 500 else install_out)

# Instalar browsers
print("\nInstalando browsers Chromium...")
stdin, stdout, stderr = ssh.exec_command("playwright install chromium", timeout=300)
browser_out = stdout.read().decode()
browser_err = stderr.read().decode()
if browser_out:
    print(browser_out[-500:] if len(browser_out) > 500 else browser_out)
if browser_err and 'Successfully' not in browser_err:
    print(f"STDERR: {browser_err[-500:]}")

# Reiniciar serviço
print("\nReiniciando servico...")
stdin, stdout, stderr = ssh.exec_command("systemctl restart extrator-api")
print("Aguardando 3s...")
import time
time.sleep(3)

# Health check
stdin, stdout, stderr = ssh.exec_command("curl -s http://localhost:5000/api/health")
health = stdout.read().decode()
print(f"\n[HEALTH] {health}")

print("\n" + "=" * 80)
print("INSTALACAO CONCLUIDA!")
print("=" * 80)

ssh.close()
