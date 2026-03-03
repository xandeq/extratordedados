import ftplib
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')

FTP_HOST = 'ftp.extratordedados.com.br'
FTP_USER = 'alexa084'
FTP_PASS = 'Alexandre10#'

ftp = ftplib.FTP(FTP_HOST)
ftp.login(FTP_USER, FTP_PASS)
ftp.encoding = 'utf-8'

# Check FTP home
print(f"FTP PWD: {ftp.pwd()}")
print(f"FTP root listing:")
for f in ftp.nlst():
    print(f"  {f}")

# Check if public_html is symlink or different
ftp.cwd('/public_html')
print(f"\npublic_html PWD: {ftp.pwd()}")

# Download and show index.html content
print(f"\n=== index.html content ===")
buf = io.BytesIO()
ftp.retrbinary('RETR index.html', buf.write)
content = buf.getvalue().decode('utf-8', errors='replace')
print(content[:500])

# Download and show login/index.html
print(f"\n=== login/index.html content (first 300 chars) ===")
buf = io.BytesIO()
ftp.retrbinary('RETR login/index.html', buf.write)
content = buf.getvalue().decode('utf-8', errors='replace')
print(content[:300])

# Check if there's another index.html elsewhere
print(f"\n=== Check for other index files ===")
try:
    ftp.cwd('/public_html')
    # Look for old test files
    for f in ['test.py', 'install_test.py', 'cgi-bin/test.py']:
        try:
            size = ftp.size(f)
            print(f"  {f}: {size} bytes (OLD TEST FILE)")
        except:
            pass
except Exception as e:
    print(f"  Error: {e}")

# Check if there is a different document root
print("\n=== Check for alternate dirs ===")
ftp.cwd('/')
for d in ftp.nlst():
    print(f"  /{d}")

ftp.quit()
