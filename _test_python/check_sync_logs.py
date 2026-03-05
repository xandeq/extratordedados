import paramiko
import sys

def check_logs():
    host = '185.173.110.180'
    user = 'root'
    password = 'REDACTED_PASSWORD'

    print(f"Connecting to {host}...")
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, username=user, password=password, timeout=10)

        print("\n=== SYSTEMCTL STATUS ===")
        stdin, stdout, stderr = ssh.exec_command('systemctl status extrator-api')
        print(stdout.read().decode('utf-8'))

        print("\n=== GUNICORN LOGS (grep SYNC) ===")
        stdin, stdout, stderr = ssh.exec_command('journalctl -u extrator-api -n 200 | grep SYNC')
        logs = stdout.read().decode('utf-8')
        if not logs:
            print("No [SYNC] logs found in the last 200 lines.")
        else:
            print(logs)

        print("\n=== ERROR LOGS ===")
        stdin, stdout, stderr = ssh.exec_command('journalctl -u extrator-api -n 50 | grep -i error')
        print(stdout.read().decode('utf-8'))

        ssh.close()

    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == '__main__':
    check_logs()
