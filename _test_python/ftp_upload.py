"""Upload test files to SmarterASP via FTP"""
import ftplib
import os
import sys

FTP_HOST = "win1151.site4now.net"
FTP_USER = "partiurock-003"
FTP_PASS = "Alexandre10#"
FTP_PATH = "/api-extratordedados"

FILES = ["index.html", "test.py", "app.py", "web.config"]

def main():
    print(f"Conectando a {FTP_HOST}...")
    try:
        ftp = ftplib.FTP(FTP_HOST, timeout=30)
        resp = ftp.login(FTP_USER, FTP_PASS)
        print(f"Login: {resp}")

        # List root directory
        print("\n--- Conteudo raiz do FTP ---")
        ftp.retrlines("LIST")

        # Try to navigate to the folder
        try:
            ftp.cwd(FTP_PATH)
            print(f"\nNavegou para {FTP_PATH}")
        except ftplib.error_perm:
            print(f"\nPasta {FTP_PATH} nao existe, tentando criar...")
            ftp.mkd(FTP_PATH)
            ftp.cwd(FTP_PATH)
            print(f"Criada e navegou para {FTP_PATH}")

        print("\n--- Conteudo da pasta ---")
        ftp.retrlines("LIST")

        # Upload files
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for filename in FILES:
            filepath = os.path.join(script_dir, filename)
            if os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    ftp.storbinary(f"STOR {filename}", f)
                print(f"Uploaded: {filename}")
            else:
                print(f"SKIP (not found): {filename}")

        print("\n--- Conteudo apos upload ---")
        ftp.retrlines("LIST")

        ftp.quit()
        print("\nUpload concluido com sucesso!")
        print(f"\nTeste acessando: http://api-extratordedados.site4now.net/")
        print(f"Ou: http://api-extratordedados.site4now.net/index.html")
        print(f"Ou: http://api-extratordedados.site4now.net/test.py")

    except ftplib.all_errors as e:
        print(f"ERRO FTP: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
