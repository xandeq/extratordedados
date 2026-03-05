"""
Instala Playwright e browsers no VPS via SSH
"""
import paramiko

VPS_HOST = "185.173.110.180"
VPS_USER = "root"
VPS_PASSWORD = "1982X@ndeq1982#"

print("Conectando ao VPS...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASSWORD)

commands = [
    "cd /opt/extrator-api && pip3 install playwright instaloader",
    "playwright install chromium --with-deps",
]

for cmd in commands:
    print(f"\n[EXEC] {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    output = stdout.read().decode()
    error = stderr.read().decode()

    if output:
        print(output)
    if error and "warning" not in error.lower():
        print(f"[ERRO] {error}")

print("\n[OK] Playwright instalado!")
ssh.close()
