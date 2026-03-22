---
phase: 01-pipeline-100-automatico
plan: 02
type: execute
wave: 2
depends_on:
  - "01-PLAN"
files_modified:
  - app/backend/app.py
  - tests/test_pipeline_health.py
autonomous: true
requirements:
  - health-endpoint
  - brevo-email-report
  - healthchecks-ping
  - pipeline-reads-db

must_haves:
  truths:
    - "GET /api/admin/pipeline/health returns last_run, next_scheduled, stats_30d, scheduler_running, config in one response"
    - "After run_daily_pipeline completes (step 7), an HTML email is sent to the notify_email address via Brevo API"
    - "If notify_email is null/empty in pipeline_config, no email is sent and the pipeline does not error"
    - "If healthcheck_url is configured in pipeline_config, requests.get(url) is called after pipeline completes successfully; requests.get(url+'/fail') if pipeline failed"
    - "If healthcheck_url is null/empty, no ping is attempted and the pipeline does not error"
    - "All notification code is wrapped in try/except — a Brevo API timeout or invalid healthcheck URL NEVER aborts run_daily_pipeline"
  artifacts:
    - path: "app/backend/app.py"
      provides: "GET /api/admin/pipeline/health, _generate_and_send_pipeline_report(), send_pipeline_email_report(), _ping_healthcheck(), _get_brevo_credentials()"
      contains: "pipeline/health"
    - path: "tests/test_pipeline_health.py"
      provides: "Live-API smoke tests for health endpoint structure"
      exports: ["test_health_unauthenticated", "test_health_response_keys"]
  key_links:
    - from: "run_daily_pipeline() step 7 (UPDATE daily_jobs SET status='completed')"
      to: "_generate_and_send_pipeline_report()"
      via: "called in finally block or after step 7, inside try/except"
      pattern: "_generate_and_send_pipeline_report"
    - from: "_generate_and_send_pipeline_report()"
      to: "Brevo API https://api.brevo.com/v3/smtp/email"
      via: "requests.post with api-key header"
      pattern: "api\\.brevo\\.com"
    - from: "_generate_and_send_pipeline_report()"
      to: "healthchecks.io URL"
      via: "requests.get(healthcheck_url)"
      pattern: "_ping_healthcheck"
---

<objective>
Add the pipeline health endpoint, Brevo email report sent at end of every pipeline run, and healthchecks.io dead-man's-switch ping. All notification code is fire-and-forget (wrapped in try/except) and reads config from pipeline_config table added in Plan 01.

Purpose: Closes the "operador abre o sistema de manhã e vê relatório" goal. Email arrives automatically; health endpoint powers the admin UI card in Plan 03.

Output: Three new functions (_get_brevo_credentials, send_pipeline_email_report, _ping_healthcheck, _generate_and_send_pipeline_report), one new endpoint (GET /api/admin/pipeline/health), run_daily_pipeline() calls report function after step 7.
</objective>

<execution_context>
@C:/Users/acq20/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/acq20/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/research/pipeline-automation.md
@.planning/phases/01-pipeline-100-automatico/01-PLAN-SUMMARY.md

<interfaces>
<!-- Key contracts from Plan 01 output and existing app.py patterns. -->

get_pipeline_config() return shape (added in Plan 01):
```python
{
    'niches':          list[str],
    'region':          str,
    'hour':            int,
    'minute':          int,
    'notify_email':    str | None,   # None if 'null' in DB
    'healthcheck_url': str | None,   # None if 'null' in DB
}
```

run_daily_pipeline() completion block (lines ~13031-13053):
```python
        # ── 7. Marcar como concluído ──────────────────────────────────────
        c.execute(
            "UPDATE daily_jobs SET status='completed', finished_at=NOW() WHERE id=%s",
            (daily_job_id,)
        )
        print(f"[DAILY] ======= Pipeline CONCLUÍDO (id={daily_job_id}) =======\n")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        ...
        c.execute("UPDATE daily_jobs SET status='failed' ...")
    finally:
        conn.close()
```

daily_jobs row columns available at end of run_daily_pipeline:
```
daily_job_id  — int (passed as argument)
region_id     — str (passed as argument)
niches        — list[str] (passed as argument)
leads_found   — int (updated incrementally by pipeline)
sanitized_count — int (tracked in step 3)
synced        — int (tracked in step 6)
skipped       — int (tracked in step 6)
pipeline_start — datetime (MUST be captured as absolute first line of function body)
```

AWS Secrets Manager pattern in app.py:
```python
def _fetch_secret_blob_from_aws(secret_id):
    # returns dict or None; uses _aws_secret_blob_cache for in-process caching
```

Brevo credentials in AWS SM:
```
secret_id: "tools/brevo"
keys: BREVO_API_KEY, BREVO_FROM_EMAIL, BREVO_FROM_NAME, BREVO_REPLY_TO
```

SEARCH_REGIONS dict (existing):
```python
SEARCH_REGIONS = {
    'grande_vitoria_es': {'state': 'ES', 'cities': ['Vitória', 'Vila Velha', ...]},
    ...
}
```

get_db() context manager already imported; requests module imported as `http_requests`:
```python
import requests as http_requests
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add GET /api/admin/pipeline/health endpoint</name>
  <files>app/backend/app.py, tests/test_pipeline_health.py</files>

  <read_first>
    - app/backend/app.py lines 13300-13350 (GET /api/admin/daily-job/status endpoint — insert new endpoint nearby)
    - app/backend/app.py lines 1389-1402 (daily_jobs table columns for query reference)
    - .planning/research/pipeline-automation.md lines 323-385 (exact SQL queries for health endpoint)
    - tests/conftest.py (existing live-API fixtures: api_base, auth_headers)
    - tests/test_health.py (live-API test pattern — match this exactly)
  </read_first>

  <behavior>
    - Endpoint is admin-only (401/403 guards identical to existing admin endpoints)
    - Returns JSON: {last_run: {...}|null, next_scheduled: "03:00 America/Sao_Paulo", stats_30d: {total, successful, avg_leads, max_leads}, scheduler_running: bool, config: {niches, region, hour}}
    - last_run contains: id, status, started_at (ISO), finished_at (ISO)|null, leads_found, leads_sanitized, leads_synced, error_message, region_used, duration_min (float|null)
    - stats_30d.total and stats_30d.successful are integers; avg_leads is float rounded to 1 decimal
    - If no daily_jobs rows exist, last_run is null and all stats_30d values are 0
    - test_health_unauthenticated: GET /api/admin/pipeline/health without token → live API → 401
    - test_health_response_keys: GET with auth_headers → live API → JSON has keys last_run, next_scheduled, stats_30d, scheduler_running
  </behavior>

  <action>
Insert this endpoint after `admin_update_pipeline_config()` in app/backend/app.py:

```python
@app.route('/api/admin/pipeline/health', methods=['GET'])
@limiter.limit("60/minute")
def admin_pipeline_health():
    """Return pipeline health summary: last run, 30d stats, next scheduled time. Admin only."""
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT is_admin FROM users WHERE id=%s', (user_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'Admin only'}), 403

        # Last run
        cur.execute('''
            SELECT id, status, started_at, finished_at, leads_found,
                   leads_sanitized, leads_synced, error_message, region_used,
                   CASE WHEN finished_at IS NOT NULL AND started_at IS NOT NULL
                        THEN ROUND(EXTRACT(EPOCH FROM (finished_at - started_at))/60, 1)
                        ELSE NULL END AS duration_min
            FROM daily_jobs
            ORDER BY started_at DESC LIMIT 1
        ''')
        row = cur.fetchone()

        last_run = None
        if row:
            cols = ['id', 'status', 'started_at', 'finished_at', 'leads_found',
                    'leads_sanitized', 'leads_synced', 'error_message', 'region_used', 'duration_min']
            last_run = dict(zip(cols, row))
            if last_run['started_at']:
                last_run['started_at'] = last_run['started_at'].isoformat()
            if last_run['finished_at']:
                last_run['finished_at'] = last_run['finished_at'].isoformat()
            if last_run['duration_min'] is not None:
                last_run['duration_min'] = float(last_run['duration_min'])

        # 30-day stats
        cur.execute('''
            SELECT
                COUNT(*)                                               AS total,
                COUNT(*) FILTER (WHERE status = 'completed')          AS successful,
                COALESCE(ROUND(AVG(leads_found)::numeric, 1), 0)      AS avg_leads,
                COALESCE(MAX(leads_found), 0)                         AS max_leads
            FROM daily_jobs
            WHERE started_at > NOW() - INTERVAL '30 days'
        ''')
        stats = cur.fetchone()

    cfg = get_pipeline_config()
    next_scheduled = f"{cfg['hour']:02d}:{cfg['minute']:02d} America/Sao_Paulo"

    return jsonify({
        'last_run':        last_run,
        'next_scheduled':  next_scheduled,
        'stats_30d': {
            'total':      int(stats[0]) if stats else 0,
            'successful': int(stats[1]) if stats else 0,
            'avg_leads':  float(stats[2]) if stats else 0.0,
            'max_leads':  int(stats[3]) if stats else 0,
        },
        'scheduler_running': bool(_APSCHEDULER_AVAILABLE and _scheduler and _scheduler.running),
        'config': {
            'niches': cfg['niches'],
            'region': cfg['region'],
            'hour':   cfg['hour'],
        }
    }), 200
```

Create tests/test_pipeline_health.py using the live-API pattern from tests/test_health.py.
The existing conftest.py provides: `api_base` (str URL), `auth_headers` (dict with Bearer token).
Do NOT use Flask test client (`client`, `admin_client`) — those fixtures do not exist.

```python
"""Smoke tests for GET /api/admin/pipeline/health — Phase 1.
Uses live-API fixtures from conftest.py (api_base, auth_headers).
Hits https://api.extratordedados.com.br — requires deploy before running.
"""
import requests


def test_health_unauthenticated_returns_401(api_base):
    """GET /api/admin/pipeline/health without token returns 401."""
    resp = requests.get(f"{api_base}/api/admin/pipeline/health", timeout=10)
    assert resp.status_code == 401


def test_health_response_has_required_keys(api_base, auth_headers):
    """GET /api/admin/pipeline/health with admin token returns expected shape."""
    resp = requests.get(
        f"{api_base}/api/admin/pipeline/health",
        headers=auth_headers,
        timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert 'last_run' in data
    assert 'next_scheduled' in data
    assert 'stats_30d' in data
    assert 'scheduler_running' in data
    stats = data['stats_30d']
    for key in ('total', 'successful', 'avg_leads', 'max_leads'):
        assert key in stats, f"Missing stats_30d key: {key}"
```
  </action>

  <verify>
    <automated>cd "C:/Users/acq20/Desktop/Trabalho/Alexandre Queiroz Marketing Digital/DIAX/extrator-de-dados" && python -c "import ast; ast.parse(open('app/backend/app.py').read()); print('syntax OK')" && python -m pytest tests/test_pipeline_health.py -x -q 2>&1 | head -20</automated>
  </verify>

  <done>Health endpoint live at GET /api/admin/pipeline/health; returns last_run, next_scheduled, stats_30d, scheduler_running, config; live-API smoke tests in tests/test_pipeline_health.py pass.</done>
</task>

<task type="auto">
  <name>Task 2: Add Brevo email report + healthchecks.io ping; hook into run_daily_pipeline()</name>
  <files>app/backend/app.py</files>

  <read_first>
    - app/backend/app.py lines 12846-13053 (entire run_daily_pipeline function — understand variables available at step 7)
    - app/backend/app.py lines 176-210 (_fetch_secret_blob_from_aws — pattern for secrets fetching)
    - .planning/research/pipeline-automation.md lines 241-320 (send_pipeline_email_report and _ping_healthcheck exact code)
    - .planning/research/pipeline-automation.md lines 455-507 (report_data dict structure and _generate_and_send_pipeline_report)
  </read_first>

  <action>
**Step 1: Add helper functions** near the other helper/utility functions in app.py (before run_daily_pipeline, after pipeline_config helpers):

```python
def _get_brevo_credentials():
    """Fetch Brevo credentials from AWS Secrets Manager. Returns dict or None."""
    try:
        blob = _fetch_secret_blob_from_aws('tools/brevo')
        if blob and blob.get('BREVO_API_KEY'):
            return blob
        return None
    except Exception as e:
        print(f"[BREVO] Erro ao buscar credenciais: {e}")
        return None


def send_pipeline_email_report(report: dict, to_email: str) -> bool:
    """
    Send HTML pipeline summary via Brevo transactional email API.
    Returns True on success, False on any error. Never raises.
    """
    try:
        creds = _get_brevo_credentials()
        if not creds:
            print("[NOTIFY] Brevo credentials unavailable — skipping email")
            return False

        api_key    = creds['BREVO_API_KEY']
        from_email = creds.get('BREVO_FROM_EMAIL', 'noreply@extratordedados.com.br')
        from_name  = creds.get('BREVO_FROM_NAME', 'Extrator DIAX')

        status_color = '#22c55e' if report.get('status') == 'completed' else '#ef4444'
        niches_str   = ', '.join(report.get('niches', [])) or 'N/A'
        html = f"""
        <div style="font-family:sans-serif;max-width:600px;margin:auto">
          <h2 style="color:{status_color}">Pipeline Diario — {report.get('date','N/A')}</h2>
          <table border="0" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%">
            <tr style="background:#f3f4f6"><td><b>Regiao</b></td><td>{report.get('region','N/A')}</td></tr>
            <tr><td><b>Status</b></td><td style="color:{status_color}">{report.get('status','N/A').upper()}</td></tr>
            <tr style="background:#f3f4f6"><td><b>Leads coletados</b></td><td>{report.get('leads_found',0)}</td></tr>
            <tr><td><b>Leads sanitizados</b></td><td>{report.get('leads_sanitized',0)}</td></tr>
            <tr style="background:#f3f4f6"><td><b>Leads sincronizados</b></td><td>{report.get('leads_synced',0)}</td></tr>
            <tr><td><b>Duracao</b></td><td>{report.get('duration_min','?')} min</td></tr>
            {('<tr style="background:#fef2f2"><td><b>Erro</b></td><td style="color:#dc2626">' + str(report.get('error_message','')) + '</td></tr>') if report.get('error_message') else ''}
          </table>
          <p style="color:#6b7280;font-size:12px">Nichos: {niches_str}</p>
        </div>
        """

        subject = f"[Pipeline] {report.get('date')} — {report.get('leads_found',0)} leads — {report.get('status','N/A').upper()}"
        payload = {
            "sender":      {"name": from_name, "email": from_email},
            "to":          [{"email": to_email}],
            "subject":     subject,
            "htmlContent": html,
        }

        resp = http_requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        print(f"[NOTIFY] Email Brevo enviado para {to_email} (status {resp.status_code})")
        return True

    except Exception as e:
        print(f"[NOTIFY] Erro ao enviar email Brevo: {e}")
        return False


def _ping_healthcheck(check_url: str, success: bool = True) -> None:
    """
    Dead man's switch: ping healthchecks.io after pipeline completes.
    Appends '/fail' suffix when success=False. Never raises.
    """
    if not check_url:
        return
    try:
        suffix = '' if success else '/fail'
        http_requests.get(check_url + suffix, timeout=5)
        print(f"[HEALTHCHECK] Pinged: {check_url}{suffix}")
    except Exception as e:
        print(f"[HEALTHCHECK] Ping failed (non-fatal): {e}")


def _generate_and_send_pipeline_report(daily_job_id: int, report_data: dict) -> None:
    """
    Called at the end of run_daily_pipeline.
    Sends email via Brevo and pings healthchecks.io.
    Wrapped in try/except — must NEVER abort the pipeline.
    """
    try:
        cfg = get_pipeline_config()

        notify_email    = cfg.get('notify_email')
        healthcheck_url = cfg.get('healthcheck_url')

        if notify_email:
            send_pipeline_email_report(report_data, notify_email)
        else:
            print("[REPORT] notify_email nao configurado — email nao enviado")

        success = report_data.get('status') == 'completed'
        _ping_healthcheck(healthcheck_url, success)

    except Exception as e:
        print(f"[REPORT] Erro no envio do relatorio (non-fatal): {e}")
```

**Step 2: Capture pipeline_start and call report at end of run_daily_pipeline()**

`pipeline_start = datetime.now()` MUST be the **absolute first line** of `run_daily_pipeline()` function body — before any other statement, including print calls. This guarantees it is always bound even if an exception fires at any point in the function.

```python
def run_daily_pipeline(daily_job_id, niches, region_id, user_id):
    pipeline_start = datetime.now()   # MUST be first — before any other line
    # ... rest of function follows
```

After step 7 (`c.execute("UPDATE daily_jobs SET status='completed'...")`) and BEFORE `finally`, add the report call — it must be inside the main `try` block but AFTER the UPDATE, to ensure DB is already committed:

```python
        # ── 8. Enviar relatório e ping healthcheck ────────────────────────
        try:
            _generate_and_send_pipeline_report(daily_job_id, {
                'date':             datetime.now().strftime('%Y-%m-%d'),
                'region':           region_id,
                'niches':           niches,
                'leads_found':      leads_found,
                'leads_sanitized':  sanitized_count,
                'leads_synced':     synced,
                'status':           'completed',
                'error_message':    None,
                'duration_min':     round((datetime.now() - pipeline_start).total_seconds() / 60, 1),
                'batch_id':         batch_id,
            })
        except Exception as _rep_err:
            print(f"[DAILY] Erro no relatório (non-fatal): {_rep_err}")
```

Also add a failure ping in the `except Exception as e:` block of run_daily_pipeline, after the status='failed' UPDATE:
```python
        try:
            _generate_and_send_pipeline_report(daily_job_id, {
                'date':            datetime.now().strftime('%Y-%m-%d'),
                'region':          region_id,
                'niches':          niches,
                'leads_found':     locals().get('leads_found', 0),
                'leads_sanitized': locals().get('sanitized_count', 0),
                'leads_synced':    locals().get('synced', 0),
                'status':          'failed',
                'error_message':   str(e)[:200],
                'duration_min':    round((datetime.now() - pipeline_start).total_seconds() / 60, 1) if 'pipeline_start' in locals() else 0,
                'batch_id':        locals().get('batch_id'),
            })
        except Exception:
            pass
```

Note: Using `if 'pipeline_start' in locals() else 0` in the failure path is a safety guard only. Because `pipeline_start = datetime.now()` is set as the absolute first line of the function, `pipeline_start` will always be bound in practice. The guard is defensive code for any unexpected early-exit scenario.
  </action>

  <verify>
    <automated>cd "C:/Users/acq20/Desktop/Trabalho/Alexandre Queiroz Marketing Digital/DIAX/extrator-de-dados" && python -c "import ast; ast.parse(open('app/backend/app.py').read()); print('syntax OK')"</automated>
  </verify>

  <done>_get_brevo_credentials(), send_pipeline_email_report(), _ping_healthcheck(), and _generate_and_send_pipeline_report() implemented; pipeline_start captured as the absolute first line of run_daily_pipeline(); report called after both success (step 8) and failure paths; all notification code is try/except protected.</done>
</task>

</tasks>

<verification>
After both tasks complete:

```bash
# Syntax
python -c "import ast; ast.parse(open('app/backend/app.py').read()); print('OK')"

# Structural checks
grep -n "def admin_pipeline_health" app/backend/app.py
grep -n "def send_pipeline_email_report" app/backend/app.py
grep -n "def _ping_healthcheck" app/backend/app.py
grep -n "_generate_and_send_pipeline_report" app/backend/app.py
grep -n "pipeline_start = datetime.now()" app/backend/app.py

# Tests
python -m pytest tests/test_pipeline_health.py -v
```
</verification>

<success_criteria>
- GET /api/admin/pipeline/health returns all required fields
- send_pipeline_email_report() uses Brevo API key from AWS SM (via _fetch_secret_blob_from_aws)
- _ping_healthcheck() sends /fail suffix on failure, bare URL on success
- _generate_and_send_pipeline_report() called after both success and failure paths in run_daily_pipeline
- pipeline_start = datetime.now() is the absolute first line of run_daily_pipeline()
- No new library imports required (requests already imported as http_requests)
- All notification functions wrapped in try/except
</success_criteria>

<output>
After completion, create `.planning/phases/01-pipeline-100-automatico/02-PLAN-SUMMARY.md` with:
- What was implemented
- Key function names and line numbers added
- Any deviations from the plan
</output>
