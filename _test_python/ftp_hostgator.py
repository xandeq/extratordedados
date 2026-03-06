"""Test FTP connection to HostGator and upload Python test files"""
import ftplib
import os
import io
from _secrets import ftp_host, ftp_user, get

FTP_HOST = ftp_host()
FTP_USER = ftp_user()
FTP_PASS = get('FTP_PASS', '')

def main():
    print(f"Conectando a {FTP_HOST}...")
    ftp = ftplib.FTP(timeout=30)
    ftp.connect(FTP_HOST, 21)
    resp = ftp.login(FTP_USER, FTP_PASS)
    print(f"Login: {resp}")

    print("\n--- Raiz do FTP ---")
    ftp.retrlines("LIST")

    # Check if cgi-bin exists
    dirs = []
    ftp.retrlines("NLST", dirs.append)
    print(f"\nPastas/arquivos: {dirs}")

    # Check if public_html exists
    target = None
    for d in ["public_html", "www", "htdocs"]:
        try:
            ftp.cwd(d)
            print(f"\nEntrou em /{d}")
            target = d
            break
        except:
            pass

    if target:
        print(f"\n--- Conteudo de /{target} ---")
        ftp.retrlines("LIST")

    # Check for cgi-bin
    try:
        ftp.cwd("cgi-bin")
        print("\n--- cgi-bin existe! ---")
        ftp.retrlines("LIST")
        cgi_path = True
        ftp.cwd("..")
    except:
        print("\ncgi-bin NAO encontrado, criando...")
        try:
            ftp.mkd("cgi-bin")
            ftp.cwd("cgi-bin")
            cgi_path = True
            ftp.cwd("..")
            print("cgi-bin criado!")
        except Exception as e:
            print(f"Erro ao criar cgi-bin: {e}")
            cgi_path = False

    # === Upload test files ===

    # 1) Simple CGI Python script in cgi-bin
    cgi_script = b"""#!/usr/bin/env python3
print("Content-Type: text/html")
print()
print("<h1>Python CGI funciona na HostGator!</h1>")
print("<p>Teste OK via cgi-bin.</p>")

import sys
print(f"<p>Python version: {sys.version}</p>")
import os
print(f"<p>Server: {os.environ.get('SERVER_SOFTWARE', 'N/A')}</p>")
"""

    if cgi_path:
        ftp.cwd("cgi-bin")
        ftp.storbinary("STOR test.py", io.BytesIO(cgi_script))
        # Set executable permission via SITE CHMOD
        try:
            ftp.sendcmd("SITE CHMOD 755 test.py")
            print("Uploaded cgi-bin/test.py (chmod 755)")
        except:
            print("Uploaded cgi-bin/test.py (chmod falhou, pode precisar ajustar)")
        ftp.cwd("..")

    # 2) Python in public_html with .htaccess
    py_script = b"""#!/usr/bin/env python3
print("Content-Type: text/html")
print()
print("<h1>Python roda na HostGator!</h1>")
print("<p>Script executando diretamente em public_html.</p>")

import sys
print(f"<p>Python: {sys.version}</p>")
"""

    ftp.storbinary("STOR test_python.py", io.BytesIO(py_script))
    try:
        ftp.sendcmd("SITE CHMOD 755 test_python.py")
        print("Uploaded test_python.py (chmod 755)")
    except:
        print("Uploaded test_python.py")

    # 3) .htaccess to enable Python CGI
    htaccess_content = b"""AddHandler cgi-script .py
Options +ExecCGI
"""

    # Check if .htaccess already exists, back it up
    existing_files = []
    ftp.retrlines("NLST", existing_files.append)
    if ".htaccess" in existing_files:
        print("\n.htaccess ja existe - vou criar test_python.htaccess separado")
        ftp.storbinary("STOR test_python.htaccess", io.BytesIO(htaccess_content))
        print("Uploaded test_python.htaccess (aplique manualmente se necessario)")
    else:
        ftp.storbinary("STOR .htaccess", io.BytesIO(htaccess_content))
        print("Uploaded .htaccess (habilitando CGI para .py)")

    # 4) Simple HTML test page
    html = b"""<!DOCTYPE html>
<html><head><title>Teste HostGator</title></head>
<body>
<h1>FTP Upload OK - HostGator</h1>
<p><a href="/cgi-bin/test.py">Teste Python via cgi-bin</a></p>
<p><a href="/test_python.py">Teste Python direto</a></p>
</body></html>
"""
    ftp.storbinary("STOR test_python.html", io.BytesIO(html))
    print("Uploaded test_python.html")

    print("\n--- Conteudo final ---")
    ftp.retrlines("LIST")

    ftp.quit()
    print("\n=== Upload concluido! ===")
    print("Teste acessando:")
    print("  http://extratordedados.com.br/test_python.html")
    print("  http://extratordedados.com.br/cgi-bin/test.py")
    print("  http://extratordedados.com.br/test_python.py")

if __name__ == "__main__":
    main()
