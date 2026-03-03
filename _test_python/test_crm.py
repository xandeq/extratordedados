"""Test CRM endpoints on VPS"""
import paramiko
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('185.173.110.180', username='root', password='1982X@ndeq1982#', timeout=15)

# Upload test script
sftp = ssh.open_sftp()
test_code = '''
import urllib.request, json

# Login
data = json.dumps({"username": "admin", "password": "1982Xandeq1982#"}).encode()
req = urllib.request.Request("http://localhost:8000/api/login", data=data, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print("Login OK")
token = result["token"]

# Test GET /api/leads
req2 = urllib.request.Request("http://localhost:8000/api/leads", headers={"Authorization": "Bearer " + token})
resp2 = urllib.request.urlopen(req2)
leads_data = json.loads(resp2.read())
print("Total leads:", leads_data.get("total", 0))
print("Status counts:", json.dumps(leads_data.get("status_counts", {})))
print("All tags:", leads_data.get("all_tags", [])[:5])
if leads_data.get("leads"):
    l = leads_data["leads"][0]
    print("First lead:", l.get("company_name"), "|", l.get("email"), "|", l.get("crm_status"))
else:
    print("No leads found")
'''

with sftp.open('/tmp/test_crm.py', 'w') as f:
    f.write(test_code)
sftp.close()

stdin, stdout, stderr = ssh.exec_command('/opt/extrator-api/venv/bin/python3 /tmp/test_crm.py', timeout=20)
out = stdout.read().decode('utf-8', errors='replace').strip()
err = stderr.read().decode('utf-8', errors='replace').strip()
if out:
    print(out)
if err:
    print('ERROR:', err)

ssh.close()
