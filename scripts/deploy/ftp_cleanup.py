import ftplib
import sys

sys.stdout.reconfigure(encoding='utf-8')

FTP_HOST = 'ftp.extratordedados.com.br'
FTP_USER = 'alexa084'
FTP_PASS = 'Alexandre10#'

ftp = ftplib.FTP(FTP_HOST)
ftp.login(FTP_USER, FTP_PASS)
ftp.encoding = 'utf-8'
ftp.cwd('/extratordedados.com.br')

# Remove old test files
old_files = [
    'test.py', 'final_test.py', 'test_modules.py',
    'fix_and_test.py', 'install_test.py', 'index_old_test.html'
]

print("=== Cleaning old test files ===")
for f in old_files:
    try:
        ftp.delete(f)
        print(f"  Deleted: {f}")
    except:
        print(f"  Skip: {f} (not found)")

# Clean old test directories
for d in ['teste', 'teste2', 'contato']:
    try:
        ftp.cwd(f'/extratordedados.com.br/{d}')
        for f in ftp.nlst():
            if f not in ['.', '..']:
                try:
                    ftp.delete(f)
                except:
                    pass
        ftp.cwd('/extratordedados.com.br')
        ftp.rmd(d)
        print(f"  Deleted dir: {d}/")
    except:
        print(f"  Skip dir: {d}/ (not found or not empty)")

ftp.quit()
print("\n=== CLEANUP DONE ===")
