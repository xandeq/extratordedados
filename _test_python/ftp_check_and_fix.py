import ftplib
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

FTP_HOST = 'ftp.extratordedados.com.br'
FTP_USER = 'alexa084'
FTP_PASS = 'Alexandre10#'

ftp = ftplib.FTP(FTP_HOST)
ftp.login(FTP_USER, FTP_PASS)
ftp.encoding = 'utf-8'
ftp.cwd('/public_html')

# Check what's in key directories
print("=== /public_html/ listing ===")
for f in ['index.html', 'index.php', '.htaccess']:
    try:
        size = ftp.size(f)
        print(f"  {f}: {size} bytes")
    except:
        print(f"  {f}: NOT FOUND")

print("\n=== /public_html/login/ ===")
try:
    ftp.cwd('/public_html/login')
    print(f"  Files: {ftp.nlst()}")
    try:
        size = ftp.size('index.html')
        print(f"  index.html: {size} bytes")
    except:
        print("  index.html: NOT FOUND")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== /public_html/dashboard/ ===")
try:
    ftp.cwd('/public_html/dashboard')
    print(f"  Files: {ftp.nlst()}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== /public_html/results/ ===")
try:
    ftp.cwd('/public_html/results')
    print(f"  Files: {ftp.nlst()}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== /public_html/_next/ ===")
try:
    ftp.cwd('/public_html/_next')
    print(f"  Files: {ftp.nlst()}")
except Exception as e:
    print(f"  Error: {e}")

# Check .htaccess content
print("\n=== Current .htaccess ===")
ftp.cwd('/public_html')
lines = []
ftp.retrlines('RETR .htaccess', lines.append)
for l in lines:
    print(f"  {l}")

ftp.quit()
