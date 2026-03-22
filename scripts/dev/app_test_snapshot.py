"""
Teste minimo Flask/WSGI para SmarterASP.NET
Se Flask nao estiver disponivel, tenta CGI puro.
"""
try:
    from flask import Flask
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "<h1>Flask rodando na SmarterASP!</h1><p>Backend Python OK.</p>"

    if __name__ == "__main__":
        app.run()
except ImportError:
    # fallback CGI
    print("Content-Type: text/html\n")
    print("<h1>Python CGI rodando (sem Flask)</h1>")
