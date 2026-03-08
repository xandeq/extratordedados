"""Deploy frontend (out/) to HostGator via FTP using AWS SM credentials."""
import ftplib
import os
import sys
import json
import boto3

sys.stdout.reconfigure(encoding='utf-8')

# Fetch FTP credentials
client = boto3.client('secretsmanager', region_name='us-east-1')
response = client.get_secret_value(SecretId='extratordedados/prod')
secrets = json.loads(response['SecretString'])

LOCAL_OUT = os.path.join(os.path.dirname(__file__), 'project', 'frontend', 'out')

print(f'Connecting to FTP {secrets["FTP_HOST"]}...')
ftp = ftplib.FTP(timeout=60)
ftp.connect(secrets['FTP_HOST'], 21)
ftp.login(secrets['FTP_USER'], secrets['FTP_PASS'])
print('Connected!')

uploaded = 0
skipped = 0
errors = 0


def ftp_makedirs(path):
    """Create remote directory path, one level at a time."""
    parts = path.replace('\\', '/').split('/')
    current = ''
    for part in parts:
        if not part:
            continue
        current += '/' + part
        try:
            ftp.cwd(current)
        except Exception:
            try:
                ftp.mkd(current)
            except Exception:
                pass


def upload_recursive(local_dir, remote_prefix):
    global uploaded, skipped, errors

    for item in sorted(os.listdir(local_dir)):
        local_path = os.path.join(local_dir, item)
        remote_path = remote_prefix + '/' + item if remote_prefix else item

        # Skip [id] dynamic routes (Next.js handles client-side)
        if '[' in item or ']' in item:
            skipped += 1
            continue

        if os.path.isdir(local_path):
            upload_recursive(local_path, remote_path)
        else:
            try:
                # Ensure parent dir exists
                parent_parts = remote_path.replace('\\', '/').split('/')
                if len(parent_parts) > 1:
                    parent = '/'.join(parent_parts[:-1])
                    ftp_makedirs(parent)
                ftp.cwd('/' + '/'.join(parent_parts[:-1]) if len(parent_parts) > 1 else '/')
                with open(local_path, 'rb') as f:
                    ftp.storbinary(f'STOR {item}', f)
                uploaded += 1
                if uploaded % 25 == 0:
                    print(f'  {uploaded} files uploaded...')
            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f'  ERROR: {remote_path}: {e}')


print(f'Uploading {LOCAL_OUT} to FTP root...')
upload_recursive(LOCAL_OUT, '')

ftp.quit()
print(f'\nDone!')
print(f'  Uploaded: {uploaded}')
print(f'  Skipped (dynamic routes): {skipped}')
print(f'  Errors: {errors}')
