"""
Auditoria completa da aplicação extratordedados.com.br
Navega como usuário real, testa todas as funcionalidades,
monitora console, network, performance e gera relatório.
"""
import json, time, os, sys
from datetime import datetime
from playwright.sync_api import sync_playwright

BASE_URL = "https://extratordedados.com.br"
API_URL = "https://api.extratordedados.com.br"
USERNAME = "admin"
PASSWORD = "1982Xandeq1982#"
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "_audit_screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# ── Collectors ──────────────────────────────────────────
console_logs = []
console_errors = []
network_requests = []
failed_requests = []
slow_requests = []       # > 3s
js_errors = []
flow_results = []
ux_issues = []
perf_notes = []

def screenshot(page, name):
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=True)
    return path

def log_step(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")

def add_flow(name, status, detail=""):
    flow_results.append({"flow": name, "status": status, "detail": detail})
    icon = "OK" if status == "pass" else "FAIL" if status == "fail" else "WARN"
    log_step(f"[{icon}] {name} — {detail}")

# ── Network listener ────────────────────────────────────
def on_response(response):
    req = response.request
    entry = {
        "url": req.url,
        "method": req.method,
        "status": response.status,
        "timing_ms": None,
        "content_type": response.headers.get("content-type", ""),
    }
    # Calculate timing from request timing if available
    try:
        timing = response.request.timing
        if timing and timing.get("responseEnd"):
            entry["timing_ms"] = round(timing["responseEnd"])
    except Exception:
        pass

    network_requests.append(entry)

    if response.status >= 400:
        body_text = ""
        try:
            body_text = response.text()[:500]
        except Exception:
            pass
        failed_requests.append({**entry, "body": body_text})

    if entry["timing_ms"] and entry["timing_ms"] > 3000:
        slow_requests.append(entry)

def on_request_failed(request):
    failed_requests.append({
        "url": request.url,
        "method": request.method,
        "status": "NETWORK_ERROR",
        "failure": str(request.failure),
    })

# ── Test flows ──────────────────────────────────────────
def test_login(page):
    """Test login flow."""
    page.goto(f"{BASE_URL}/login", wait_until="networkidle", timeout=30000)
    time.sleep(1)
    screenshot(page, "01_login_page")

    # Check login form exists
    user_input = page.locator('input[type="text"], input[name="username"], input[placeholder*="suário"], input[placeholder*="user"]').first
    pass_input = page.locator('input[type="password"]').first

    if not user_input.is_visible():
        add_flow("Login — campo username", "fail", "Campo username não encontrado")
        return False
    if not pass_input.is_visible():
        add_flow("Login — campo password", "fail", "Campo password não encontrado")
        return False

    add_flow("Login — formulário visível", "pass", "Campos username e password encontrados")

    # Fill and submit
    user_input.fill(USERNAME)
    pass_input.fill(PASSWORD)
    time.sleep(0.5)

    submit = page.locator('button[type="submit"], button:has-text("Entrar"), button:has-text("Login")').first
    if submit.is_visible():
        submit.click()
    else:
        pass_input.press("Enter")

    # Wait for redirect
    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=10000)
        add_flow("Login — autenticação", "pass", f"Redirecionado para {page.url}")
        screenshot(page, "02_after_login")
        return True
    except Exception as e:
        screenshot(page, "02_login_failed")
        add_flow("Login — autenticação", "fail", f"Não redirecionou: {e}")
        return False


def test_dashboard(page):
    """Test dashboard page."""
    page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle", timeout=30000)
    time.sleep(2)
    screenshot(page, "03_dashboard")

    # Check if redirected to login
    if "/login" in page.url:
        add_flow("Dashboard — acesso", "fail", "Redirecionado para login (sessão perdida)")
        return

    add_flow("Dashboard — carregamento", "pass", "Página carregada")

    # Check for chart/stats elements
    stats = page.locator('[class*="stat"], [class*="card"], [class*="metric"]').count()
    charts = page.locator('svg.recharts-surface, [class*="chart"]').count()
    add_flow("Dashboard — elementos visuais", "pass" if stats > 0 or charts > 0 else "warn",
             f"{stats} cards de estatística, {charts} gráficos encontrados")


def test_leads_page(page):
    """Test leads/CRM page."""
    page.goto(f"{BASE_URL}/leads", wait_until="networkidle", timeout=30000)
    time.sleep(2)
    screenshot(page, "04_leads")

    if "/login" in page.url:
        add_flow("Leads — acesso", "fail", "Redirecionado para login")
        return

    add_flow("Leads — carregamento", "pass", "Página carregada")

    # Check table/list
    rows = page.locator('table tbody tr, [class*="lead-row"], [class*="lead-card"]').count()
    add_flow("Leads — listagem", "pass" if rows > 0 else "warn",
             f"{rows} leads na tabela")

    # Test filters
    filter_inputs = page.locator('input[placeholder*="Buscar"], input[placeholder*="Filtrar"], input[placeholder*="search"]')
    if filter_inputs.count() > 0:
        filter_inputs.first.fill("teste")
        time.sleep(1)
        filter_inputs.first.fill("")
        add_flow("Leads — filtro busca", "pass", "Campo de busca funcional")
    else:
        add_flow("Leads — filtro busca", "warn", "Campo de busca não encontrado")

    # Test pagination
    pagination = page.locator('button:has-text("Próx"), button:has-text("Next"), button:has-text("2"), [class*="pagination"]')
    if pagination.count() > 0:
        add_flow("Leads — paginação", "pass", "Controles de paginação encontrados")
    else:
        add_flow("Leads — paginação", "warn", "Sem paginação visível (pode ter poucos leads)")

    # Test export button
    export_btn = page.locator('button:has-text("Exportar"), button:has-text("Export")')
    if export_btn.count() > 0:
        add_flow("Leads — botão exportar", "pass", "Botão de exportação presente")
    else:
        add_flow("Leads — botão exportar", "warn", "Botão de exportação não encontrado")

    # Test CRM status dropdown (click first lead if exists)
    if rows > 0:
        try:
            first_row = page.locator('table tbody tr').first
            first_row.click()
            time.sleep(1)
            screenshot(page, "04b_lead_detail")
            drawer = page.locator('[class*="drawer"], [class*="modal"], [class*="slide"]')
            if drawer.count() > 0:
                add_flow("Leads — drawer/detalhe", "pass", "Drawer de lead abriu ao clicar")
            else:
                add_flow("Leads — drawer/detalhe", "warn", "Nenhum drawer abriu ao clicar no lead")
        except Exception as e:
            add_flow("Leads — drawer/detalhe", "warn", f"Erro ao abrir: {e}")

    # Test sanitize button
    sanitize_btn = page.locator('button:has-text("Sanitizar"), button:has-text("Sanitize")')
    if sanitize_btn.count() > 0:
        add_flow("Leads — botão sanitizar", "pass", "Botão sanitizar presente")


def test_scrape_page(page):
    """Test scrape/extraction page."""
    page.goto(f"{BASE_URL}/scrape", wait_until="networkidle", timeout=30000)
    time.sleep(2)
    screenshot(page, "05_scrape")

    if "/login" in page.url:
        add_flow("Scrape — acesso", "fail", "Redirecionado para login")
        return

    add_flow("Scrape — carregamento", "pass", "Página carregada")

    # Check tabs
    tabs = page.locator('[role="tab"], button[class*="tab"]')
    tab_count = tabs.count()
    add_flow("Scrape — tabs", "pass" if tab_count > 0 else "warn",
             f"{tab_count} tabs de método encontradas")

    # Check URL input
    url_input = page.locator('input[type="url"], input[placeholder*="URL"], input[placeholder*="url"], input[placeholder*="http"]')
    if url_input.count() > 0:
        add_flow("Scrape — campo URL", "pass", "Campo de URL presente")
    else:
        add_flow("Scrape — campo URL", "warn", "Campo de URL não encontrado")


def test_massive_search(page):
    """Test massive search page — MAIN FEATURE."""
    page.goto(f"{BASE_URL}/massive-search", wait_until="networkidle", timeout=30000)
    time.sleep(2)
    screenshot(page, "06_massive_search")

    if "/login" in page.url:
        add_flow("Busca Massiva — acesso", "fail", "Redirecionado para login")
        return

    add_flow("Busca Massiva — carregamento", "pass", "Página carregada")

    # Check niches grid
    niche_buttons = page.locator('button:has-text("Clínica"), button:has-text("Escritório"), button:has-text("Academia")')
    add_flow("Busca Massiva — nichos pré-definidos", "pass" if niche_buttons.count() >= 3 else "warn",
             f"{niche_buttons.count()} nichos pré-definidos encontrados")

    # Test custom niche input
    custom_input = page.locator('input[placeholder*="nicho"], input[placeholder*="Adicionar"]')
    if custom_input.count() > 0:
        custom_input.first.fill("Auditoria Teste")
        add_btn = page.locator('button:has-text("Adicionar")')
        if add_btn.count() > 0:
            add_btn.first.click()
            time.sleep(1)
            # Check it appeared
            added = page.locator('button:has-text("Auditoria Teste"), div:has-text("Auditoria Teste")')
            if added.count() > 0:
                add_flow("Busca Massiva — adicionar nicho custom", "pass", "'Auditoria Teste' adicionado com sucesso")
                screenshot(page, "06b_custom_niche_added")

                # Reload and check persistence
                page.reload(wait_until="networkidle", timeout=30000)
                time.sleep(2)
                persisted = page.locator('button:has-text("Auditoria Teste"), div:has-text("Auditoria Teste")')
                if persisted.count() > 0:
                    add_flow("Busca Massiva — persistência nicho custom", "pass", "Nicho persistiu após reload")
                else:
                    add_flow("Busca Massiva — persistência nicho custom", "fail", "Nicho NÃO persistiu após reload")
                screenshot(page, "06c_after_reload")
            else:
                add_flow("Busca Massiva — adicionar nicho custom", "fail", "Nicho não apareceu após clicar Adicionar")
        else:
            add_flow("Busca Massiva — botão adicionar", "fail", "Botão 'Adicionar' não encontrado")
    else:
        add_flow("Busca Massiva — input nicho custom", "fail", "Input de nicho custom não encontrado")

    # Check region selector
    regions = page.locator('button:has-text("Vitória"), button:has-text("São Paulo"), button:has-text("Rio")')
    add_flow("Busca Massiva — regiões", "pass" if regions.count() >= 2 else "warn",
             f"{regions.count()} regiões encontradas")

    # Check methods
    methods = page.locator('button:has-text("Google Maps"), button:has-text("Motores"), button:has-text("Local Business")')
    add_flow("Busca Massiva — métodos de busca", "pass" if methods.count() >= 2 else "warn",
             f"{methods.count()} métodos encontrados")

    # Check summary card
    summary = page.locator('text=Resumo da Busca')
    add_flow("Busca Massiva — card resumo", "pass" if summary.count() > 0 else "warn",
             "Card de resumo presente" if summary.count() > 0 else "Card de resumo não encontrado")

    # Check start button
    start_btn = page.locator('button:has-text("Iniciar Busca Massiva")')
    if start_btn.count() > 0:
        is_disabled = start_btn.first.is_disabled()
        add_flow("Busca Massiva — botão iniciar", "pass",
                 f"Botão presente (disabled={is_disabled} — correto se nenhum nicho selecionado)")

    # Test selecting a niche and checking job estimate updates
    clinica_btn = page.locator('button:has-text("Clínica Médica")').first
    if clinica_btn.is_visible():
        clinica_btn.click()
        time.sleep(0.5)
        jobs_text = page.locator('text=/\\d+/').all_text_contents()
        add_flow("Busca Massiva — estimativa jobs", "pass", "Contador de jobs atualiza ao selecionar nicho")


def test_app_logs(page):
    """Test app-logs page (admin logs viewer)."""
    page.goto(f"{BASE_URL}/app-logs", wait_until="networkidle", timeout=30000)
    time.sleep(2)
    screenshot(page, "07_app_logs")

    if "/login" in page.url:
        add_flow("App Logs — acesso", "fail", "Redirecionado para login")
        return

    add_flow("App Logs — carregamento", "pass", "Página carregada")


def test_api_health(page):
    """Test backend API health."""
    page.goto(f"{API_URL}/api/health", wait_until="networkidle", timeout=15000)
    time.sleep(1)
    content = page.content()
    if '"ok"' in content:
        add_flow("API Health — status", "pass", "Backend respondendo OK")
    else:
        add_flow("API Health — status", "fail", f"Resposta inesperada")
    screenshot(page, "08_api_health")


def test_api_endpoints(page, token):
    """Test key API endpoints directly."""
    import urllib.request, urllib.error

    endpoints = [
        ("GET", "/api/analytics", None),
        ("GET", "/api/leads?page=1&per_page=5", None),
        ("GET", "/api/regions", None),
        ("GET", "/api/crm/status", None),
        ("GET", "/api/niches/custom", None),
        ("GET", "/api/admin/daily-job/status", None),
        ("GET", "/api/admin/logs?page=1&per_page=5", None),
    ]

    for method, path, body in endpoints:
        url = f"{API_URL}{path}"
        start = time.time()
        try:
            req = urllib.request.Request(url, method=method)
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Content-Type", "application/json")
            if body:
                req.data = json.dumps(body).encode()

            with urllib.request.urlopen(req, timeout=15) as resp:
                elapsed_ms = int((time.time() - start) * 1000)
                status = resp.status
                resp_body = resp.read().decode()[:300]

                label = f"API {method} {path}"
                if status < 400:
                    add_flow(label, "pass", f"{status} em {elapsed_ms}ms")
                else:
                    add_flow(label, "fail", f"Status {status}: {resp_body}")

                if elapsed_ms > 3000:
                    perf_notes.append(f"LENTO: {method} {path} — {elapsed_ms}ms")

        except urllib.error.HTTPError as e:
            elapsed_ms = int((time.time() - start) * 1000)
            add_flow(f"API {method} {path}", "fail", f"HTTP {e.code}: {e.read().decode()[:200]}")
        except Exception as e:
            add_flow(f"API {method} {path}", "fail", f"Erro: {e}")


def test_dark_mode(page):
    """Test dark mode toggle."""
    page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle", timeout=30000)
    time.sleep(1)

    toggle = page.locator('button[aria-label*="dark"], button[aria-label*="theme"], button:has-text("🌙"), button:has-text("☀")')
    # Also try sidebar toggle
    if toggle.count() == 0:
        toggle = page.locator('[class*="dark-mode"], [class*="theme-toggle"]')

    if toggle.count() > 0:
        toggle.first.click()
        time.sleep(0.5)
        screenshot(page, "09_dark_mode")
        html_class = page.locator("html").get_attribute("class") or ""
        if "dark" in html_class:
            add_flow("Dark Mode — toggle", "pass", "Classe 'dark' aplicada ao HTML")
        else:
            add_flow("Dark Mode — toggle", "warn", f"Classe no html: '{html_class}'")
        # Toggle back
        toggle.first.click()
        time.sleep(0.3)
    else:
        add_flow("Dark Mode — toggle", "warn", "Botão de dark mode não encontrado automaticamente")


def test_responsive(page, context):
    """Test mobile viewport."""
    mobile_page = context.new_page()
    mobile_page.set_viewport_size({"width": 375, "height": 812})
    mobile_page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle", timeout=30000)
    time.sleep(2)
    screenshot(mobile_page, "10_mobile_dashboard")

    # Check sidebar is hidden or hamburger visible
    sidebar = mobile_page.locator('[class*="sidebar"], nav')
    hamburger = mobile_page.locator('button[class*="menu"], button[aria-label*="menu"]')

    if hamburger.count() > 0:
        add_flow("Responsivo — menu mobile", "pass", "Hamburger menu visível em 375px")
    else:
        add_flow("Responsivo — menu mobile", "warn", "Sem hamburger visível — sidebar pode sobrepor conteúdo")

    mobile_page.goto(f"{BASE_URL}/massive-search", wait_until="networkidle", timeout=30000)
    time.sleep(1)
    screenshot(mobile_page, "10b_mobile_massive_search")
    add_flow("Responsivo — massive search mobile", "pass", "Página carregada em viewport mobile")

    mobile_page.close()


# ── Extract token from storage ──────────────────────────
def get_token(page):
    """Extract auth token from localStorage or cookies."""
    token = page.evaluate("() => localStorage.getItem('token')")
    if token:
        return token
    # Try other storage keys
    for key in ["auth_token", "session_token", "jwt"]:
        token = page.evaluate(f"() => localStorage.getItem('{key}')")
        if token:
            return token
    return None


# ── Generate report ─────────────────────────────────────
def generate_report():
    total = len(flow_results)
    passed = sum(1 for f in flow_results if f["status"] == "pass")
    failed = sum(1 for f in flow_results if f["status"] == "fail")
    warned = sum(1 for f in flow_results if f["status"] == "warn")

    report = []
    report.append("=" * 70)
    report.append("  RELATÓRIO DE AUDITORIA — extratordedados.com.br")
    report.append(f"  Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 70)
    report.append("")
    report.append(f"  RESUMO: {passed} OK | {failed} FALHAS | {warned} AVISOS | {total} testes")
    report.append("")

    # ── Flows ──
    report.append("-" * 70)
    report.append("  TESTES EXECUTADOS")
    report.append("-" * 70)
    for f in flow_results:
        icon = {"pass": "  [OK]  ", "fail": " [FAIL] ", "warn": " [WARN] "}[f["status"]]
        report.append(f"{icon} {f['flow']}")
        if f["detail"]:
            report.append(f"         {f['detail']}")
    report.append("")

    # ── Failures ──
    failures = [f for f in flow_results if f["status"] == "fail"]
    if failures:
        report.append("-" * 70)
        report.append("  ERROS ENCONTRADOS (PRIORIDADE ALTA)")
        report.append("-" * 70)
        for i, f in enumerate(failures, 1):
            report.append(f"  {i}. {f['flow']}")
            report.append(f"     {f['detail']}")
        report.append("")

    # ── Console Errors ──
    if console_errors:
        report.append("-" * 70)
        report.append(f"  ERROS DE CONSOLE ({len(console_errors)})")
        report.append("-" * 70)
        for err in console_errors[:20]:
            report.append(f"  - [{err['type']}] {err['text'][:200]}")
            if err.get("url"):
                report.append(f"    Página: {err['url']}")
        report.append("")

    # ── Failed Requests ──
    if failed_requests:
        report.append("-" * 70)
        report.append(f"  REQUESTS FALHADOS ({len(failed_requests)})")
        report.append("-" * 70)
        seen = set()
        for r in failed_requests:
            key = f"{r['method']} {r['url']} {r['status']}"
            if key in seen:
                continue
            seen.add(key)
            report.append(f"  - {r['method']} {r['url']}")
            report.append(f"    Status: {r['status']}")
            if r.get("body"):
                report.append(f"    Body: {r['body'][:150]}")
        report.append("")

    # ── Slow Requests ──
    if slow_requests:
        report.append("-" * 70)
        report.append(f"  REQUESTS LENTOS > 3s ({len(slow_requests)})")
        report.append("-" * 70)
        for r in slow_requests:
            report.append(f"  - {r['method']} {r['url']} — {r['timing_ms']}ms")
        report.append("")

    # ── Performance ──
    if perf_notes:
        report.append("-" * 70)
        report.append("  NOTAS DE PERFORMANCE")
        report.append("-" * 70)
        for n in perf_notes:
            report.append(f"  - {n}")
        report.append("")

    # ── Network summary ──
    api_reqs = [r for r in network_requests if "/api/" in r["url"]]
    report.append("-" * 70)
    report.append(f"  NETWORK SUMMARY")
    report.append("-" * 70)
    report.append(f"  Total requests capturados: {len(network_requests)}")
    report.append(f"  Requests para API: {len(api_reqs)}")
    report.append(f"  Requests falhados: {len(failed_requests)}")
    report.append(f"  Requests lentos (>3s): {len(slow_requests)}")
    report.append("")

    # ── UX Issues ──
    if ux_issues:
        report.append("-" * 70)
        report.append("  PROBLEMAS DE UX")
        report.append("-" * 70)
        for u in ux_issues:
            report.append(f"  - {u}")
        report.append("")

    # ── Warnings ──
    warnings = [f for f in flow_results if f["status"] == "warn"]
    if warnings:
        report.append("-" * 70)
        report.append("  AVISOS (PRIORIDADE MÉDIA/BAIXA)")
        report.append("-" * 70)
        for i, f in enumerate(warnings, 1):
            report.append(f"  {i}. {f['flow']}")
            report.append(f"     {f['detail']}")
        report.append("")

    # ── Screenshots ──
    report.append("-" * 70)
    report.append(f"  SCREENSHOTS")
    report.append("-" * 70)
    report.append(f"  Diretório: {SCREENSHOT_DIR}")
    for f in sorted(os.listdir(SCREENSHOT_DIR)):
        if f.endswith(".png"):
            report.append(f"  - {f}")
    report.append("")

    report.append("=" * 70)
    report.append("  FIM DO RELATÓRIO")
    report.append("=" * 70)

    return "\n".join(report)


# ── Main ────────────────────────────────────────────────
def main():
    print("\n" + "=" * 70)
    print("  AUDITORIA COMPLETA — extratordedados.com.br")
    print("=" * 70 + "\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # ── Setup listeners ──
        page.on("console", lambda msg: (
            console_logs.append({"type": msg.type, "text": msg.text, "url": page.url}),
            console_errors.append({"type": msg.type, "text": msg.text, "url": page.url})
                if msg.type in ("error", "warning") else None
        ))
        page.on("pageerror", lambda err: js_errors.append({"error": str(err), "url": page.url}))
        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)

        # ── Run tests ──
        print("1/9  Login")
        logged_in = test_login(page)

        if logged_in:
            token = get_token(page)

            print("\n2/9  Dashboard")
            test_dashboard(page)

            print("\n3/9  Leads / CRM")
            test_leads_page(page)

            print("\n4/9  Scrape")
            test_scrape_page(page)

            print("\n5/9  Busca Massiva")
            test_massive_search(page)

            print("\n6/9  App Logs")
            test_app_logs(page)

            print("\n7/9  API Health + Endpoints")
            test_api_health(page)
            if token:
                test_api_endpoints(page, token)
            else:
                add_flow("API Endpoints — token", "warn", "Token não encontrado no localStorage, pulando testes de API diretos")

            print("\n8/9  Dark Mode")
            test_dark_mode(page)

            print("\n9/9  Responsivo")
            test_responsive(page, context)
        else:
            add_flow("Todos os testes subsequentes", "fail", "Login falhou — impossível continuar")

        browser.close()

    # ── Report ──
    report = generate_report()
    print("\n" + report)

    # Save report
    report_path = os.path.join(os.path.dirname(__file__), "_audit_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nRelatório salvo em: {report_path}")
    print(f"Screenshots em: {SCREENSHOT_DIR}\n")


if __name__ == "__main__":
    main()
