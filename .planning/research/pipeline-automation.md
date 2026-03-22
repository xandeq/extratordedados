# Research: Pipeline Automation, Notification Systems & Configurable Scheduling

**Project:** Extrator de Dados — DIAX
**Domain:** Automated lead pipeline (Flask monolith + PostgreSQL + APScheduler)
**Researched:** 2026-03-22
**Overall confidence:** HIGH (stack is stable, well-documented, patterns verified against official docs)

---

## Executive Summary

The platform already has the right foundation: APScheduler `BackgroundScheduler` with cron triggers, a `daily_jobs` tracking table, a `custom_niches` table, and advisory-lock based double-fire protection for Gunicorn 2 workers. The gaps are (1) pipeline parameters come from Python module-level constants (`DAILY_JOB_NICHES`, `DAILY_JOB_REGION`, `DAILY_JOB_HOUR`), not from the DB; (2) there is no post-pipeline notification; (3) there is no health/observability dashboard surfacing next-run time and last-run outcome.

All six research questions have clear, low-risk answers that do not require new infrastructure. The full solution fits inside the existing monolith without Redis, Celery, or any new service.

---

## Research Question 1: Configurable Scheduler Jobs in Flask/APScheduler

### Current State

```python
# app.py lines 842-851 — hardcoded at import time
DAILY_JOB_NICHES = ['restaurante', 'academia', 'clinica medica', ...]
DAILY_JOB_REGION  = 'grande_vitoria_es'
DAILY_JOB_HOUR    = 3
```

`trigger_daily_pipeline()` already falls back to these constants:

```python
niches    = niches    or DAILY_JOB_NICHES
region_id = region_id or DAILY_JOB_REGION
```

The function signature already accepts runtime overrides — the wiring is incomplete.

### Pattern: DB-Driven Configuration (Recommended)

**Do NOT use APScheduler SQLAlchemyJobStore for parameter storage.** That store serializes the entire Job object (pickle) and is designed for job *identity persistence across restarts*, not for human-editable configuration. It requires SQLAlchemy as an additional dependency on top of the existing psycopg2 pool and has a known schema incompatibility when upgrading APScheduler versions.

**Use instead: a `pipeline_config` table + modify-job-args at startup.**

#### Schema

```sql
CREATE TABLE IF NOT EXISTS pipeline_config (
    key   VARCHAR(100) PRIMARY KEY,
    value TEXT         NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Seed with defaults
INSERT INTO pipeline_config (key, value) VALUES
  ('daily_niches',  '["restaurante","academia","clinica medica","dentista","advocacia","contabilidade","imobiliaria","salao de beleza","farmacia","supermercado"]'),
  ('daily_region',  '"grande_vitoria_es"'),
  ('daily_hour',    '3'),
  ('daily_minute',  '0'),
  ('notify_email',  '"xandeq@gmail.com"'),
  ('notify_whatsapp', 'null')
ON CONFLICT (key) DO NOTHING;
```

Values are stored as JSON strings so lists serialize cleanly without custom parsing.

#### Reading config at job trigger time

```python
import json

def get_pipeline_config():
    """Read current config from DB. Falls back to module constants on error."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM pipeline_config")
            rows = {k: json.loads(v) for k, v in cur.fetchall()}
        return {
            'niches':   rows.get('daily_niches',   DAILY_JOB_NICHES),
            'region':   rows.get('daily_region',   DAILY_JOB_REGION),
            'hour':     int(rows.get('daily_hour', DAILY_JOB_HOUR)),
            'minute':   int(rows.get('daily_minute', 0)),
            'notify_email':     rows.get('notify_email'),
            'notify_whatsapp':  rows.get('notify_whatsapp'),
        }
    except Exception as e:
        print(f"[CONFIG] Erro ao ler pipeline_config: {e} — usando defaults")
        return {'niches': DAILY_JOB_NICHES, 'region': DAILY_JOB_REGION,
                'hour': DAILY_JOB_HOUR, 'minute': 0,
                'notify_email': None, 'notify_whatsapp': None}
```

#### Wiring into trigger_daily_pipeline

```python
def trigger_daily_pipeline(niches=None, region_id=None):
    cfg = get_pipeline_config()
    niches    = niches    or cfg['niches']
    region_id = region_id or cfg['region']
    # ... rest of existing code unchanged
```

Because `trigger_daily_pipeline` reads config every time it fires, **the scheduler does not need to be restarted** when niches/region change. The APScheduler cron trigger only controls *when* the function is called; what it does is determined at call time.

#### Rescheduling the hour at runtime (admin endpoint)

```python
from apscheduler.triggers.cron import CronTrigger

@app.route('/api/admin/pipeline-config', methods=['PUT'])
@require_admin
def update_pipeline_config():
    data = request.json
    updates = {}

    if 'niches' in data:
        updates['daily_niches'] = json.dumps(data['niches'])
    if 'region' in data:
        updates['daily_region'] = json.dumps(data['region'])
    if 'hour' in data:
        updates['daily_hour'] = json.dumps(int(data['hour']))
        updates['daily_minute'] = json.dumps(int(data.get('minute', 0)))

    with get_db() as conn:
        cur = conn.cursor()
        for k, v in updates.items():
            cur.execute(
                "INSERT INTO pipeline_config (key, value, updated_at) VALUES (%s, %s, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
                (k, v)
            )

    # If hour/minute changed, reschedule the APScheduler job immediately
    if 'hour' in data and _scheduler and _scheduler.running:
        cfg = get_pipeline_config()
        _tz = pytz.timezone('America/Sao_Paulo')
        _scheduler.reschedule_job(
            'daily_pipeline',
            trigger=CronTrigger(hour=cfg['hour'], minute=cfg['minute'], timezone=_tz)
        )
        print(f"[CONFIG] Pipeline reagendado: {cfg['hour']:02d}:{cfg['minute']:02d}")

    return jsonify({'success': True})
```

`_scheduler.reschedule_job()` is part of APScheduler 3.x public API (MEDIUM confidence — verified against official docs). It modifies the trigger *in memory* immediately. Since APScheduler is in-process with Gunicorn's `--preload` model (see Section 3), only one scheduler instance exists and the call takes effect immediately.

### Confidence: HIGH
The `pipeline_config` table pattern is a standard "application settings in DB" pattern. APScheduler `reschedule_job` is documented in v3.x official docs. No new libraries needed.

---

## Research Question 2: WhatsApp Notifications from Python

### Options Evaluated

| Option | Cost | Official API | Risk | Verdict |
|--------|------|--------------|------|---------|
| Meta WhatsApp Cloud API (direct) | ~$0.007/util msg in BR | Yes | Low | **Recommended for production** |
| Twilio for WhatsApp | Meta fees + $0.005/msg overhead | Yes (wrapper) | Low | Avoid — pays more for same thing |
| Evolution API (self-hosted Baileys) | Free infra | No | High: ToS ban, breaking changes | Avoid |
| WPPConnect / whatsapp-web.js | Free infra | No | High: ToS ban | Avoid |
| WASenderAPI (paid unofficial wrapper) | $6+/month | No | Medium | Avoid |

### Recommended: Meta WhatsApp Cloud API

For *internal pipeline reports* (1 notification per day, to the owner's own number), cost is negligible at ~$0.007 per utility template message in Brazil (2025 pricing). The setup allows up to 5 verified numbers for free in the developer sandbox — sufficient for this use case until the product scales.

#### Setup requirements

1. Meta Developer App with WhatsApp product enabled (permanent token with `whatsapp_business_messaging` permission)
2. One approved utility template (e.g., `pipeline_report`) in Meta Business Manager
3. Verified business phone number (own number works in sandbox for initial 5 numbers)

Templates must be pre-approved. For internal reports, a simple utility template works:

```
Pipeline {{1}} concluído. {{2}} leads coletados, {{3}} sanitizados, {{4}} sincronizados. Status: {{5}}.
```

#### Python implementation (no external library needed)

```python
import requests
import json

def send_whatsapp_report(to_phone: str, report: dict, wa_token: str, phone_number_id: str):
    """
    Send pipeline summary via WhatsApp Cloud API utility template.
    to_phone: E.164 format, e.g. '5527999999999'
    report:   dict with keys leads_found, leads_sanitized, leads_synced, status, region
    """
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {wa_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": "pipeline_report",   # pre-approved template name
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": report.get('region', 'N/A')},
                    {"type": "text", "text": str(report.get('leads_found', 0))},
                    {"type": "text", "text": str(report.get('leads_sanitized', 0))},
                    {"type": "text", "text": str(report.get('leads_synced', 0))},
                    {"type": "text", "text": report.get('status', 'completed')},
                ]
            }]
        }
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"[NOTIFY] WhatsApp enviado para {to_phone}")
        return True
    except Exception as e:
        print(f"[NOTIFY] Erro WhatsApp: {e}")
        return False
```

Store `wa_token` and `phone_number_id` in AWS Secrets Manager under `tools/whatsapp-cloud` (to create). The `to_phone` is stored in `pipeline_config` table (key: `notify_whatsapp`).

#### Pricing reality for this project (2025)

- 1 template message/day to Brazil = $0.007 × 30 = **$0.21/month**
- This is a utility template (pipeline status notification), which is $0.0068/message in BR
- If using the 24-hour service window (owner messages the bot first), it becomes free
- Verdict: negligible cost, officially supported, no ban risk

### Alternative: Brevo Email (already available)

For the immediate term, Brevo is already configured in AWS Secrets Manager (`tools/brevo`) and requires zero new approval process. It is the path of least resistance for notifications.

```python
import json, subprocess, requests

def _get_brevo_key():
    """Fetch from AWS SM with local cache."""
    secret = subprocess.check_output([
        'python', '-m', 'awscli', 'secretsmanager', 'get-secret-value',
        '--secret-id', 'tools/brevo', '--query', 'SecretString', '--output', 'text'
    ], timeout=10)
    return json.loads(secret)['BREVO_API_KEY']

def send_pipeline_email_report(report: dict, to_email: str):
    """Send HTML pipeline summary via Brevo transactional API."""
    api_key = _get_brevo_key()

    html = f"""
    <h2>Pipeline Diario — {report.get('region', 'N/A')}</h2>
    <table border="1" cellpadding="8">
      <tr><td>Data</td><td>{report.get('date', 'N/A')}</td></tr>
      <tr><td>Leads coletados</td><td>{report.get('leads_found', 0)}</td></tr>
      <tr><td>Leads sanitizados</td><td>{report.get('leads_sanitized', 0)}</td></tr>
      <tr><td>Leads sincronizados</td><td>{report.get('leads_synced', 0)}</td></tr>
      <tr><td>Duracao</td><td>{report.get('duration_min', '?')} min</td></tr>
      <tr><td>Status</td><td>{report.get('status', 'N/A')}</td></tr>
    </table>
    <p>Nichos: {', '.join(report.get('niches', []))}</p>
    """

    payload = {
        "sender": {"name": "Extrator DIAX", "email": "noreply@extratordedados.com.br"},
        "to": [{"email": to_email}],
        "subject": f"[Pipeline] {report.get('date')} — {report.get('leads_found', 0)} leads",
        "htmlContent": html
    }

    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=15
        )
        resp.raise_for_status()
        print(f"[NOTIFY] Email enviado para {to_email}")
        return True
    except Exception as e:
        print(f"[NOTIFY] Erro email: {e}")
        return False
```

### Recommendation: Start with Brevo email (zero setup), add WhatsApp Cloud API in a second pass once template approval is complete.

### Confidence: HIGH for Brevo (already in secrets), MEDIUM for WhatsApp Cloud API (pricing data from official Meta docs, setup process verified from developer docs)

---

## Research Question 3: Pipeline Health Monitoring

### Current state

`GET /api/admin/daily-job/status` returns the last 10 runs from `daily_jobs`. The table has `status`, `started_at`, `finished_at`, `leads_found`, `leads_sanitized`, `leads_synced`, `error_message`. This is solid data — the dashboard just needs to surface it better.

### Dead Man's Switch Pattern (External)

**healthchecks.io** is the standard tool for this. Free tier: 20 checks. Open-source (self-hostable). Works by expecting a ping at a known interval; if the ping does not arrive within `grace_time`, it sends an alert via email/Slack/webhook.

Implementation: at the end of `run_daily_pipeline` (step 7, after marking completed), add:

```python
def _ping_healthcheck(check_url: str, success: bool = True):
    """Dead man's switch: ping healthchecks.io after pipeline completes."""
    if not check_url:
        return
    try:
        suffix = '' if success else '/fail'
        requests.get(check_url + suffix, timeout=5)
        print(f"[HEALTHCHECK] Pinged {check_url}{suffix}")
    except Exception as e:
        print(f"[HEALTHCHECK] Ping failed: {e}")  # non-fatal
```

The check URL (e.g., `https://hc-ping.com/your-uuid`) is stored in `pipeline_config` as `healthcheck_url`. If the pipeline crashes before step 7, the ping is never sent and healthchecks.io fires an alert after `grace_time` (recommended: 10 hours for a 02:00 job expected to finish by 10:00).

### Internal Health Endpoint (for admin UI)

Extend `GET /api/admin/pipeline/health` to return:

```python
@app.route('/api/admin/pipeline/health', methods=['GET'])
@require_admin
def pipeline_health():
    with get_db() as conn:
        cur = conn.cursor()

        # Last run summary
        cur.execute("""
            SELECT id, status, started_at, finished_at, leads_found,
                   leads_sanitized, leads_synced, error_message, region_used,
                   EXTRACT(EPOCH FROM (finished_at - started_at))/60 AS duration_min
            FROM daily_jobs
            ORDER BY started_at DESC LIMIT 1
        """)
        row = cur.fetchone()

        # Success rate last 30 days
        cur.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'completed') AS successful,
                AVG(leads_found) AS avg_leads,
                MAX(leads_found) AS max_leads
            FROM daily_jobs
            WHERE started_at > NOW() - INTERVAL '30 days'
        """)
        stats = cur.fetchone()

    cfg = get_pipeline_config()
    next_run = f"{cfg['hour']:02d}:{cfg['minute']:02d} America/Sao_Paulo"

    last = None
    if row:
        cols = ['id','status','started_at','finished_at','leads_found',
                'leads_sanitized','leads_synced','error_message','region_used','duration_min']
        last = dict(zip(cols, row))
        if last['started_at']:
            last['started_at'] = last['started_at'].isoformat()
        if last['finished_at']:
            last['finished_at'] = last['finished_at'].isoformat()

    return jsonify({
        'last_run': last,
        'next_scheduled': next_run,
        'stats_30d': {
            'total': stats[0] if stats else 0,
            'successful': stats[1] if stats else 0,
            'avg_leads': round(float(stats[2]), 1) if stats and stats[2] else 0,
            'max_leads': stats[3] if stats else 0,
        },
        'scheduler_running': bool(_scheduler and _scheduler.running),
        'config': {
            'niches': cfg['niches'],
            'region': cfg['region'],
            'hour': cfg['hour'],
        }
    })
```

### Gunicorn + APScheduler: The Double-Fire Problem

**Current solution is correct.** The code uses `pg_try_advisory_xact_lock(20260322)` which is a PostgreSQL advisory lock — atomic and released on transaction end. This is better than the 5-minute window guard alone (also present as secondary defense).

**Important:** The scheduler fires in both workers but only one wins the advisory lock. The loser returns `None` immediately, which is the right behavior.

For additional safety, add `--preload` to Gunicorn command. With `--preload`, the module runs once before forking, so the scheduler is created once and the workers share the file descriptor reference. However, because each worker forks its own memory space, `BackgroundScheduler` still gets duplicated — `--preload` helps with module-level singletons but does not help with thread-based schedulers. The advisory lock remains the correct guard.

**Do not switch to SQLAlchemyJobStore** just to solve this — it adds complexity and the advisory lock already handles it correctly.

### Confidence: HIGH

---

## Research Question 4: Niche/Region Configuration via Admin UI

### What already exists

- `custom_niches` table and `GET/POST/DELETE /api/niches/custom` endpoints — operational
- `SEARCH_REGIONS` dict in code — not DB-backed
- `trigger_daily_pipeline` already accepts `niches` and `region_id` overrides

### What is missing

1. `pipeline_config` table (described in Q1) — stores active niches/region for daily job
2. Admin endpoints to read and write `pipeline_config`
3. Frontend panel to edit and preview config before it takes effect

### Region configuration

Regions are trickier because `SEARCH_REGIONS` contains nested city lists with state info. Options:

**Option A (recommended): Hybrid — keep `SEARCH_REGIONS` as the catalog, store the active region key in `pipeline_config`.**

Admin picks from the existing `SEARCH_REGIONS` catalog. No DB schema change for cities. Adding new regions still requires a code change (but this is rare — 4 regions serve 95% of BR cities).

**Option B: Full DB-backed regions table.** Adds `pipeline_regions` table with `region_id, name, state, cities JSONB`. More flexible but more surface area.

Recommendation: Option A now, Option B when the first client in a new region requests it.

### Niche pool management

The existing `custom_niches` table stores available niches. The `pipeline_config.daily_niches` key stores the *active subset* for the daily job. The admin UI should:

1. Show `custom_niches` as the available pool
2. Allow drag-and-drop selection of which go into `pipeline_config.daily_niches`
3. Save via `PUT /api/admin/pipeline-config`

The custom_niches CRUD endpoints already exist — only the config linkage and admin UI page are new.

### Confidence: HIGH

---

## Research Question 5: Async Pipeline Reporting

### When to generate the report

The `run_daily_pipeline` function already tracks all the metrics needed:
- `leads_found`, `leads_sanitized`, `leads_synced` (written to `daily_jobs`)
- `started_at`, `finished_at` (computed duration available)
- `region_used`, `niches_used` (stored in `daily_jobs`)
- `error_message` (on failure)

The report should be generated at step 7 (after marking `completed`) within `run_daily_pipeline`. This is already a daemon thread, so no additional async mechanism is needed.

### Report generation pattern

```python
def _generate_and_send_pipeline_report(daily_job_id: int, report_data: dict):
    """
    Called at the end of run_daily_pipeline.
    report_data: {leads_found, leads_sanitized, leads_synced, status,
                  region, niches, date, duration_min, error_message}
    """
    cfg = get_pipeline_config()

    notify_email    = cfg.get('notify_email')
    notify_whatsapp = cfg.get('notify_whatsapp')

    if not notify_email and not notify_whatsapp:
        print("[REPORT] Sem destinatarios configurados — pulando notificacao")
        return

    if notify_email:
        send_pipeline_email_report(report_data, notify_email)

    if notify_whatsapp:
        wa_cfg = _get_whatsapp_config()  # fetch from AWS SM
        if wa_cfg:
            send_whatsapp_report(notify_whatsapp, report_data,
                                 wa_cfg['token'], wa_cfg['phone_number_id'])

    # Ping healthchecks.io dead man switch
    healthcheck_url = cfg.get('healthcheck_url')
    success = report_data.get('status') == 'completed'
    _ping_healthcheck(healthcheck_url, success)
```

### Error-resilience

Wrap the entire report dispatch in `try/except` so a notification failure (API down, invalid email) **never crashes `run_daily_pipeline`**. This is consistent with the existing pattern in the codebase.

### Report content structure

```python
# Build this dict before calling _generate_and_send_pipeline_report
report_data = {
    'date':             datetime.now().strftime('%Y-%m-%d'),
    'region':           region_id,
    'niches':           niches,
    'leads_found':      leads_found,
    'leads_sanitized':  sanitized_count,
    'leads_synced':     synced,
    'leads_skipped':    skipped,
    'status':           'completed',   # or 'failed'
    'error_message':    None,
    'duration_min':     round((datetime.now() - pipeline_start).seconds / 60, 1),
    'batch_id':         batch_id,
}
```

### Confidence: HIGH

---

## Research Question 6: APScheduler Alternatives

### Should we replace APScheduler 3.x?

**No.** Here is the assessment:

| Option | Verdict | Reason |
|--------|---------|--------|
| APScheduler 3.x (current) | Keep | Already working, advisory lock guard handles Gunicorn, no new dependencies |
| APScheduler 4.x | Do not upgrade | Pre-release, breaking API changes, requires async rewrite. 4.0 is explicitly marked "do not use in production" in official docs |
| Celery + Redis | Overkill | Requires Redis (not installed on VPS), Celery Beat daemon, 2 new processes, complex setup. Zero benefit for 1 job/day + 1 job/week use case |
| RQ + Redis | Overkill | Same Redis requirement. Better than Celery but still unnecessary |
| Arq | Overkill | Async-first, would require rewriting the entire sync scraping stack |
| Python `schedule` library | Downgrade | Simpler but no persistence, no misfire handling, no cron syntax |
| Cron (system cron) | Alternative path | Would remove the double-fire problem entirely. Calls `POST /api/admin/daily-job/run` via curl. Eliminates APScheduler but requires SSH access to VPS cron for config changes |

### System cron as alternative (worth noting)

For the specific use case of "1 pipeline at 02:00 + 1 CRM sync at 09:00", system cron via `crontab` on the VPS is actually simpler and more reliable than in-process APScheduler. It avoids the Gunicorn double-fire problem entirely. The tradeoff is that changing the schedule requires SSH or an admin endpoint that writes to crontab (complex).

**Decision: Keep APScheduler 3.x for now.** The double-fire problem is already solved. The configurable-hour requirement (Q1) is handled by `reschedule_job`. Only revisit if APScheduler starts causing problems.

### Confidence: HIGH

---

## Implementation Order (Recommended)

### Phase 1 — DB-Driven Config (no notifications yet)

1. Add `pipeline_config` table in `init_db()` with defaults
2. Implement `get_pipeline_config()` helper
3. Wire `trigger_daily_pipeline` to read from DB instead of module constants
4. Add `GET /api/admin/pipeline-config` and `PUT /api/admin/pipeline-config` endpoints
5. Add `GET /api/admin/pipeline/health` endpoint (expanded)
6. Frontend: Admin panel page with niche selector, region picker, schedule time, health status

**Risk: LOW.** No new infra, no new libraries, backward compatible (falls back to constants on error).

### Phase 2 — Email Notifications (Brevo)

1. Implement `send_pipeline_email_report()` using Brevo API (already in secrets)
2. Add `notify_email` field to `pipeline_config`
3. Call report function at end of `run_daily_pipeline`
4. Admin UI: notification settings section

**Risk: LOW.** Brevo API key and credentials already available.

### Phase 3 — WhatsApp Notifications (Meta Cloud API)

1. Create Meta Developer App + WhatsApp product
2. Create and get approval for `pipeline_report` utility template (3-5 days)
3. Store `WA_TOKEN` and `WA_PHONE_NUMBER_ID` in AWS SM as `tools/whatsapp-cloud`
4. Implement `send_whatsapp_report()` using direct `requests` call
5. Add `notify_whatsapp` field to `pipeline_config`

**Risk: MEDIUM.** Template approval takes time. Number verification adds a step. Start with email first.

### Phase 4 — Dead Man's Switch

1. Create check on healthchecks.io free tier (20 checks max)
2. Set period = 24h, grace = 10h
3. Store URL in `pipeline_config` as `healthcheck_url`
4. Add `_ping_healthcheck()` call at end of `run_daily_pipeline`

**Risk: LOW.** External service, fire-and-forget ping.

---

## Pitfalls to Avoid

### Pitfall 1: APScheduler 4.x upgrade

APScheduler 4.x is a full rewrite (async-first). The `BackgroundScheduler` class is gone; `Worker`/`AsyncWorker` are gone; data store schema changed. Upgrading would require rewriting scheduler initialization, job registration, and potentially the whole async model. **Stay on 3.x until 4.x reaches stable.**

### Pitfall 2: SQLAlchemyJobStore for parameter storage

The APScheduler job store is for *job persistence across restarts* (serialized trigger state), not for human-editable configuration. Storing nichos as job args in the job store makes them invisible to the admin UI and coupled to APScheduler's internal serialization. Use `pipeline_config` table instead.

### Pitfall 3: WhatsApp unofficial APIs (Baileys/Evolution)

Evolution API, WPPConnect, and whatsapp-web.js all operate on the undocumented WhatsApp Web protocol. Meta actively breaks this protocol (historically 2-4 times per year), causing downtime until the community patches Baileys. Phone number banning is a real risk. For a production system that runs 1 notification/day, the Meta Cloud API cost ($0.007/message) is trivially cheap versus the maintenance cost of unofficial solutions.

### Pitfall 4: Running notification code in the pipeline main thread

`run_daily_pipeline` runs in a daemon thread already. Network calls to Brevo or WhatsApp inside it are fine (blocking is OK since it's already async from Flask's perspective). But wrap every notification call in `try/except` — a network timeout must never abort the DB updates at the end of the pipeline.

### Pitfall 5: Gunicorn --preload + BackgroundScheduler

`--preload` does not prevent duplicate scheduler instantiation. The fork model means each worker gets its own copy of the scheduler object. The existing advisory lock (`pg_try_advisory_xact_lock`) is the correct and sufficient guard. Do not remove it thinking `--preload` solves the problem.

### Pitfall 6: Template approval timeline for WhatsApp

Meta's template review takes 2-5 business days on average, occasionally up to 2 weeks. Plan accordingly: submit the template as soon as the Cloud API app is set up, not when you start coding the integration.

---

## Key Libraries (All Currently Available or No Install Needed)

| Library | Already Installed | Purpose |
|---------|------------------|---------|
| `apscheduler` | Yes | Cron-based scheduling |
| `requests` | Yes | HTTP calls to Brevo, WhatsApp API, healthchecks.io |
| `psycopg2` | Yes | pipeline_config table reads |
| `pytz` | Yes | Timezone-aware reschedule |
| `boto3` | Yes | AWS SM for WhatsApp credentials |
| `brevo-python` (optional) | No | Full Brevo SDK — unnecessary, plain `requests` is sufficient |

**No new pip install required for Phase 1 or 2.** WhatsApp (Phase 3) also requires no new library — the Cloud API is plain REST.

---

## Sources

- APScheduler 3.x user guide: https://apscheduler.readthedocs.io/en/3.x/userguide.html
- APScheduler SQLAlchemy job store: https://apscheduler.readthedocs.io/en/3.x/modules/jobstores/sqlalchemy.html
- APScheduler 4.x migration warning (pre-release, not production): https://apscheduler.readthedocs.io/en/master/migration.html
- Brevo transactional email API: https://developers.brevo.com/docs/send-a-transactional-email
- WhatsApp Cloud API docs: https://developers.facebook.com/docs/whatsapp/cloud-api/
- WhatsApp pricing 2025 (BR utility template ~$0.007): https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- WhatsApp pricing July 2025 per-message model: https://www.ycloud.com/blog/whatsapp-api-pricing-update
- healthchecks.io free tier (20 checks): https://healthchecks.io/about/
- healthchecks.io Python integration: https://healthchecks.io/docs/python/
- Gunicorn + APScheduler duplicate job issue: https://sepgh.medium.com/common-mistakes-with-using-apscheduler-in-your-python-and-django-applications-100b289b812c
- Flask-APScheduler tips (Gunicorn): https://viniciuschiele.github.io/flask-apscheduler/rst/tips.html
- WhatsApp Cloud API + Flask tutorial: https://dev.to/koladev/building-a-web-service-whatsapp-cloud-api-flask-sending-template-messages-part-1-249g
