"""Test SSH connection to VPS"""
import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

VPS_HOST = '185.173.110.180'
VPS_USER = 'root'
VPS_PASS = '1982X@ndeq1982#'

print(f"Testing SSH connection to {VPS_HOST}...")
print(f"User: {VPS_USER}")
print(f"Pass: {'*' * len(VPS_PASS)}\n")

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print("Attempting connection...")
    ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)

    print("SUCCESS! Connected to VPS\n")

    # Test command
    print("Running test command: whoami")
    stdin, stdout, stderr = ssh.exec_command('whoami')
    result = stdout.read().decode().strip()
    print(f"Result: {result}\n")

    # Check if extrator-api service exists
    print("Checking extrator-api service...")
    stdin, stdout, stderr = ssh.exec_command('systemctl is-active extrator-api')
    status = stdout.read().decode().strip()
    print(f"Service status: {status}\n")

    ssh.close()
    print("Connection test passed!")

except paramiko.AuthenticationException:
    print("ERROR: Authentication failed")
    print("\nPossible causes:")
    print("- Password changed")
    print("- User disabled")
    print("- SSH key authentication required")
    print("\nPlease verify credentials manually:")
    print(f"ssh {VPS_USER}@{VPS_HOST}")

except paramiko.SSHException as e:
    print(f"ERROR: SSH error: {e}")

except Exception as e:
    print(f"ERROR: {e}")
