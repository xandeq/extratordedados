"""Deploy frontend build to HostGator via FTP"""
import ftplib
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

FTP_HOST = 'ftp.extratordedados.com.br'
FTP_USER = 'alexa084'
FTP_PASS = 'Alexandre10#'
REMOTE_ROOT = '/extratordedados.com.br'

LOCAL_OUT = os.path.join(os.path.dirname(__file__), '..', 'project', 'frontend', 'out')
LOCAL_OUT = os.path.abspath(LOCAL_OUT)

print(f"Local build dir: {LOCAL_OUT}")
print(f"Remote root: {REMOTE_ROOT}")
print()

ftp = ftplib.FTP(FTP_HOST)
ftp.login(FTP_USER, FTP_PASS)
ftp.encoding = 'utf-8'
print(f"Connected to {FTP_HOST}")
print(f"Current dir: {ftp.pwd()}")
print()

uploaded = 0
errors = 0

def ensure_remote_dir(remote_path):
    """Create remote directory if it doesn't exist"""
    dirs = remote_path.strip('/').split('/')
    current = ''
    for d in dirs:
        current += '/' + d
        try:
            ftp.cwd(current)
        except ftplib.error_perm:
            try:
                ftp.mkd(current)
            except ftplib.error_perm:
                pass

def upload_dir(local_dir, remote_dir):
    """Recursively upload directory"""
    global uploaded, errors

    ensure_remote_dir(remote_dir)

    for item in os.listdir(local_dir):
        local_path = os.path.join(local_dir, item)
        remote_path = remote_dir + '/' + item

        if os.path.isdir(local_path):
            upload_dir(local_path, remote_path)
        else:
            try:
                with open(local_path, 'rb') as f:
                    ftp.storbinary(f'STOR {remote_path}', f)
                uploaded += 1
                # Only print non-chunk files to reduce noise
                if '/_next/static/chunks/' not in remote_path:
                    print(f"  OK: {remote_path}")
            except Exception as e:
                errors += 1
                print(f"  FAIL: {remote_path} - {e}")

print("Uploading files...")
print()

# Upload all files from out/ to remote root
upload_dir(LOCAL_OUT, REMOTE_ROOT)

print()
print("=" * 50)
print(f"Upload complete: {uploaded} files uploaded, {errors} errors")
print("=" * 50)

if errors == 0:
    print("\nFrontend deployed successfully!")
    print("URL: https://extratordedados.com.br")
else:
    print(f"\n{errors} file(s) failed to upload")

ftp.quit()
