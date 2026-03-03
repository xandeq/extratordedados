import ftplib
import sys

sys.stdout.reconfigure(encoding='utf-8')

FTP_HOST = 'ftp.extratordedados.com.br'
FTP_USER = 'alexa084'
FTP_PASS = 'Alexandre10#'

ftp = ftplib.FTP(FTP_HOST)
ftp.login(FTP_USER, FTP_PASS)
ftp.encoding = 'utf-8'
ftp.cwd('/public_html')

# Upload fixed .htaccess
htaccess_path = r'C:\Users\acq20\Desktop\Trabalho\Alexandre Queiroz Marketing Digital\DIAX\extrator-de-dados\project\frontend\out\.htaccess'
with open(htaccess_path, 'rb') as f:
    ftp.storbinary('STOR .htaccess', f)
print("Uploaded fixed .htaccess")

# Rename index.php to index.php.bak to avoid conflict
try:
    ftp.rename('index.php', 'index.php.bak')
    print("Renamed index.php -> index.php.bak")
except Exception as e:
    print(f"Rename index.php: {e}")

# Verify
print("\nVerifying .htaccess:")
lines = []
ftp.retrlines('RETR .htaccess', lines.append)
for l in lines[:5]:
    print(f"  {l}")

# List root files
print("\nRoot files:")
for f in ['index.html', 'index.php', 'index.php.bak', '.htaccess']:
    try:
        size = ftp.size(f)
        print(f"  {f}: {size} bytes")
    except:
        print(f"  {f}: NOT FOUND")

ftp.quit()
print("\n=== FIX COMPLETE ===")
