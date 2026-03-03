import ftplib
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

FTP_HOST = 'ftp.extratordedados.com.br'
FTP_USER = 'alexa084'
FTP_PASS = 'Alexandre10#'

LOCAL_DIR = r'C:\Users\acq20\Desktop\Trabalho\Alexandre Queiroz Marketing Digital\DIAX\extrator-de-dados\project\frontend\out'
REMOTE_DIR = '/public_html'

def ftp_mkdirs(ftp, path):
    """Create directory tree on FTP server"""
    dirs = path.strip('/').split('/')
    current = ''
    for d in dirs:
        current += '/' + d
        try:
            ftp.mkd(current)
        except ftplib.error_perm:
            pass  # Directory already exists

def upload_directory(ftp, local_path, remote_path):
    """Recursively upload a directory"""
    items = os.listdir(local_path)

    for item in items:
        local_item = os.path.join(local_path, item)
        remote_item = remote_path + '/' + item

        if os.path.isdir(local_item):
            # Create remote directory
            try:
                ftp.mkd(remote_item)
            except ftplib.error_perm:
                pass
            upload_directory(ftp, local_item, remote_item)
        else:
            # Upload file
            try:
                with open(local_item, 'rb') as f:
                    ftp.storbinary(f'STOR {remote_item}', f)
                size = os.path.getsize(local_item)
                print(f'  OK: {remote_item} ({size} bytes)')
            except Exception as e:
                print(f'  FAIL: {remote_item} - {e}')

print(f"Connecting to {FTP_HOST}...")
ftp = ftplib.FTP(FTP_HOST)
ftp.login(FTP_USER, FTP_PASS)
ftp.encoding = 'utf-8'
print(f"Connected! PWD: {ftp.pwd()}")

# Navigate to public_html
try:
    ftp.cwd(REMOTE_DIR)
    print(f"Changed to {REMOTE_DIR}")
except:
    print(f"Could not change to {REMOTE_DIR}")
    sys.exit(1)

# Clean old files first (optional - be careful)
# Just upload and overwrite
print(f"\nUploading from {LOCAL_DIR}...")
print(f"To remote: {REMOTE_DIR}\n")

upload_directory(ftp, LOCAL_DIR, REMOTE_DIR)

# Verify upload
print("\n=== Files in public_html ===")
ftp.cwd(REMOTE_DIR)
files = ftp.nlst()
for f in files:
    print(f"  {f}")

ftp.quit()
print("\n=== UPLOAD COMPLETE ===")
