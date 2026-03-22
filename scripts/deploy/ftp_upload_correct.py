import ftplib
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

FTP_HOST = 'ftp.extratordedados.com.br'
FTP_USER = 'alexa084'
FTP_PASS = 'Alexandre10#'

LOCAL_DIR = r'C:\Users\acq20\Desktop\Trabalho\Alexandre Queiroz Marketing Digital\DIAX\extrator-de-dados\project\frontend\out'
REMOTE_DIR = '/extratordedados.com.br'

def upload_directory(ftp, local_path, remote_path):
    """Recursively upload a directory"""
    items = os.listdir(local_path)

    for item in items:
        local_item = os.path.join(local_path, item)
        remote_item = remote_path + '/' + item

        if os.path.isdir(local_item):
            try:
                ftp.mkd(remote_item)
            except ftplib.error_perm:
                pass
            upload_directory(ftp, local_item, remote_item)
        else:
            try:
                with open(local_item, 'rb') as f:
                    ftp.storbinary(f'STOR {remote_item}', f)
                size = os.path.getsize(local_item)
                print(f'  OK: {remote_item} ({size} bytes)')
            except Exception as e:
                print(f'  FAIL: {remote_item} - {e}')

ftp = ftplib.FTP(FTP_HOST)
ftp.login(FTP_USER, FTP_PASS)
ftp.encoding = 'utf-8'

# First check what's already in the correct directory
print(f"=== Current files in {REMOTE_DIR} ===")
ftp.cwd(REMOTE_DIR)
for f in ftp.nlst():
    if not f.startswith('.'):
        print(f"  {f}")

# Rename old index.html if exists
try:
    ftp.rename('index.html', 'index_old_test.html')
    print("\nRenamed old index.html -> index_old_test.html")
except:
    pass

# Upload frontend
print(f"\nUploading to {REMOTE_DIR}...")
upload_directory(ftp, LOCAL_DIR, REMOTE_DIR)

# Verify key files
print(f"\n=== Verification ===")
ftp.cwd(REMOTE_DIR)
for f in ['index.html', '.htaccess']:
    try:
        size = ftp.size(f)
        print(f"  {f}: {size} bytes OK")
    except:
        print(f"  {f}: NOT FOUND")

for d in ['login', 'dashboard', 'scrape', '_next', 'results']:
    try:
        ftp.cwd(f'{REMOTE_DIR}/{d}')
        print(f"  {d}/: OK")
    except:
        print(f"  {d}/: NOT FOUND")

ftp.quit()
print("\n=== UPLOAD TO CORRECT DIR COMPLETE ===")
