"""
Email Campaigns — CRUD, background sending, tracking, webhooks, automation.

Registered into the Flask app via register() to avoid circular imports with app.py.
The register() call must happen AFTER limiter, verify_token, get_auth_header,
and validate_email_free are defined in app.py.
"""

import json
import uuid as _uuid
import threading as _email_threading

from db_utils import DB_CONFIG, get_db
from email_providers import (
    EMAIL_PROVIDERS as _EMAIL_PROVIDERS,
    TRACKING_PIXEL as _TRACKING_PIXEL,
    PROVIDER_SEND_FN as _PROVIDER_SEND_FN,
    inject_tracking as _inject_tracking,
    get_base_url as _get_base_url,
)

_EMAIL_AUTO_LOCK = _email_threading.Lock()

# Injected by register() — filled before any request can arrive
_verify_token = None
_get_auth_header = None
_validate_email_free = None


# ── Provider quota helpers ────────────────────────────────────────────────────

def _get_provider_usage(provider: str) -> int:
    """Return how many emails were sent today by this provider."""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT sends_count FROM email_provider_usage WHERE provider=%s AND usage_date=CURRENT_DATE",
                (provider,)
            )
            row = c.fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


def _increment_provider_usage(provider: str):
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO email_provider_usage (provider, usage_date, sends_count)
                VALUES (%s, CURRENT_DATE, 1)
                ON CONFLICT (provider, usage_date)
                DO UPDATE SET sends_count = email_provider_usage.sends_count + 1
            """, (provider,))
            conn.commit()
    except Exception as e:
        print(f'[EMAIL] _increment_provider_usage error: {e}')


def _pick_provider() -> str | None:
    """Return name of a provider that still has quota today, or None."""
    for p in _EMAIL_PROVIDERS:
        used = _get_provider_usage(p['name'])
        if used < p['daily_limit']:
            return p['name']
    return None


# ── Core send helper ─────────────────────────────────────────────────────────

def send_campaign_email(to_email: str, to_name: str, subject: str, html_body: str,
                        text_body: str = '', from_name: str = None) -> tuple[bool, str]:
    """Send email via whichever provider has quota. Returns (success, provider_used)."""
    provider = _pick_provider()
    if not provider:
        return False, 'quota_exceeded'
    fn = _PROVIDER_SEND_FN.get(provider)
    if fn and fn(to_email, to_name, subject, html_body, text_body, from_name=from_name):
        _increment_provider_usage(provider)
        return True, provider
    # Try remaining providers
    for p in _EMAIL_PROVIDERS:
        if p['name'] == provider:
            continue
        used = _get_provider_usage(p['name'])
        if used < p['daily_limit']:
            fn2 = _PROVIDER_SEND_FN.get(p['name'])
            if fn2 and fn2(to_email, to_name, subject, html_body, text_body, from_name=from_name):
                _increment_provider_usage(p['name'])
                return True, p['name']
    return False, 'all_failed'


# ── Background send thread ────────────────────────────────────────────────────

def _run_campaign_send_background(campaign_id: int, step_id: int, subject: str, body_html: str,
                                   leads: list, already_sent: set, unsubscribed: set,
                                   from_name: str = None):
    """Background daemon thread: send campaign step 1 to eligible leads."""
    import psycopg2 as _psy2
    import time as _bg_time
    conn = _psy2.connect(**DB_CONFIG)
    c = conn.cursor()
    base_url = _get_base_url()
    sent_count = 0
    failed_count = 0
    skipped_count = 0
    t0_bg = _bg_time.time()
    print(f'[CAMPAIGN-SEND] campaign={campaign_id} starting: {len(leads)} leads queued')
    try:
        for lead_id, email, company_name in leads:
            if not email or email.lower() in already_sent:
                skipped_count += 1
                continue
            email_lower = email.lower()
            if email_lower in unsubscribed:
                skipped_count += 1
                continue
            validation = _validate_email_free(email)
            if not validation.get('valid') or validation.get('is_disposable'):
                skipped_count += 1
                continue
            token = str(_uuid.uuid4()).replace('-', '')
            tracked_html = _inject_tracking(body_html, token, base_url)
            unsub_url = f"{base_url}/api/track/unsubscribe/{token}"
            tracked_html += (
                f'<p style="font-size:11px;color:#999;text-align:center;margin-top:30px">'
                f'Para descadastrar: <a href="{unsub_url}">clique aqui</a></p>'
            )
            success, provider = send_campaign_email(email, company_name or '', subject, tracked_html, from_name=from_name)
            status = 'sent' if success else 'failed'
            try:
                c.execute("""
                    INSERT INTO email_sends (campaign_id, step_id, lead_id, email, token, provider, status, sent_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (token) DO NOTHING
                """, (campaign_id, step_id, lead_id, email, token, provider if success else None, status))
                conn.commit()
            except Exception:
                try: conn.rollback()
                except: pass
            if success:
                sent_count += 1
                already_sent.add(email_lower)
                print(f'[CAMPAIGN-SEND] campaign={campaign_id} sent email={email} provider={provider}')
                import time as _time_mod; _time_mod.sleep(0.5)
            else:
                failed_count += 1
                print(f'[CAMPAIGN-SEND] campaign={campaign_id} failed email={email} provider={provider}')
        elapsed = round(_bg_time.time() - t0_bg, 1)
        c.execute("UPDATE email_campaigns SET status='active', updated_at=NOW() WHERE id=%s", (campaign_id,))
        conn.commit()
        print(f'[CAMPAIGN-SEND] campaign={campaign_id} COMPLETE: sent={sent_count} failed={failed_count} skipped={skipped_count} elapsed={elapsed}s')
        for _p in _EMAIL_PROVIDERS:
            _used = _get_provider_usage(_p['name'])
            print(f'[EMAIL-QUOTA] {_p["name"]}: used={_used}/{_p["daily_limit"]} remaining={max(0, _p["daily_limit"] - _used)}')
    except Exception as e:
        print(f'[CAMPAIGN-SEND] campaign={campaign_id} error: {e}')
        try:
            c.execute("UPDATE email_campaigns SET status='draft', updated_at=NOW() WHERE id=%s", (campaign_id,))
            conn.commit()
        except: pass
    finally:
        try: c.close()
        except: pass
        try: conn.close()
        except: pass


# ── Automation engine ─────────────────────────────────────────────────────────

def run_email_automation():
    """
    Called by scheduler every 2 hours.
    For each active campaign with multiple steps, check email_sends
    and trigger next steps based on conditions (if_opened, if_not_opened, if_clicked).
    """
    import datetime as _dt
    import psycopg2 as _psy2_auto
    if not _EMAIL_AUTO_LOCK.acquire(blocking=False):
        print('[EMAIL-AUTO] Skipping — already running in this worker')
        return
    _guard_conn = None
    try:
        _guard_conn = _psy2_auto.connect(**DB_CONFIG)
        _guard_cur = _guard_conn.cursor()
        _guard_cur.execute("SELECT pg_try_advisory_lock(20260518)")
        if not _guard_cur.fetchone()[0]:
            print('[EMAIL-AUTO] Skipping — another worker holds the advisory lock')
            return
    except Exception as _ge:
        print(f'[EMAIL-AUTO] guard error: {_ge}')
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT DISTINCT ec.id, ec.user_id, ec.from_name
                FROM email_campaigns ec
                JOIN email_steps es ON es.campaign_id=ec.id AND es.step_num > 1
                WHERE ec.status = 'active'
            """)
            campaigns = c.fetchall()

            base_url = _get_base_url()

            for campaign_id, user_id, camp_from_name in campaigns:
                c.execute("""
                    SELECT id, step_num, subject, body_html, delay_days, condition
                    FROM email_steps WHERE campaign_id=%s AND step_num > 1 ORDER BY step_num
                """, (campaign_id,))
                steps = c.fetchall()

                for step_id, step_num, subject, body_html, delay_days, condition in steps:
                    c.execute("""
                        SELECT es.id, es.lead_id, es.email, es.opened_at, es.clicked_at, es.sent_at
                        FROM email_sends es
                        JOIN email_steps prev_step ON prev_step.campaign_id=%s AND prev_step.step_num=%s
                        WHERE es.campaign_id=%s AND es.step_id=prev_step.id
                          AND es.status NOT IN ('pending','unsubscribed')
                    """, (campaign_id, step_num - 1, campaign_id))
                    prev_sends = c.fetchall()

                    for ps_id, lead_id, email, opened_at, clicked_at, sent_at in prev_sends:
                        if not sent_at:
                            continue
                        c.execute("""
                            SELECT id FROM email_sends
                            WHERE campaign_id=%s AND step_id=%s AND email=%s
                        """, (campaign_id, step_id, email))
                        if c.fetchone():
                            continue

                        now = _dt.datetime.now(_dt.timezone.utc)
                        delta = (now - sent_at.replace(tzinfo=_dt.timezone.utc)).days if sent_at.tzinfo is None else (now - sent_at).days
                        if delta < delay_days:
                            continue

                        should_send = False
                        if condition == 'always':
                            should_send = True
                        elif condition == 'if_opened':
                            should_send = opened_at is not None
                        elif condition == 'if_not_opened':
                            should_send = opened_at is None
                        elif condition == 'if_clicked':
                            should_send = clicked_at is not None

                        if not should_send:
                            continue

                        token = str(_uuid.uuid4()).replace('-', '')
                        tracked_html = _inject_tracking(body_html, token, base_url)
                        unsub_url = f"{base_url}/api/track/unsubscribe/{token}"
                        tracked_html += f'<p style="font-size:11px;color:#999;text-align:center;margin-top:30px">Para descadastrar: <a href="{unsub_url}">clique aqui</a></p>'
                        success, provider = send_campaign_email(email, '', subject, tracked_html, from_name=camp_from_name)
                        status = 'sent' if success else 'failed'
                        c.execute("""
                            INSERT INTO email_sends (campaign_id, step_id, lead_id, email, token, provider, status, sent_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
                            ON CONFLICT (token) DO NOTHING
                        """, (campaign_id, step_id, lead_id, email, token, provider if success else None, status))
                        print(f'[EMAIL-AUTO] campaign={campaign_id} step={step_num} email={email} result={status} provider={provider}')
                    conn.commit()
        print('[EMAIL-AUTO] Automation run complete')
    except Exception as e:
        print(f'[EMAIL-AUTO] Error: {e}')
    finally:
        if _guard_conn:
            try: _guard_conn.close()
            except: pass
        _EMAIL_AUTO_LOCK.release()


# ── Route registration ────────────────────────────────────────────────────────

def register(app, limiter, verify_token_fn, get_auth_header_fn, validate_email_free_fn):
    """Register all email campaign routes into the Flask app."""
    global _verify_token, _get_auth_header, _validate_email_free
    _verify_token = verify_token_fn
    _get_auth_header = get_auth_header_fn
    _validate_email_free = validate_email_free_fn

    from flask import jsonify, request, Response, redirect, make_response

    # ── Tracking endpoints ────────────────────────────────────────────────────

    @app.route('/api/track/o/<token>.png', methods=['GET'])
    def track_open(token):
        """Open tracking pixel."""
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT id, opened_at FROM email_sends WHERE token=%s", (token,))
                row = c.fetchone()
                if row:
                    send_id, opened_at = row
                    if not opened_at:
                        c.execute("UPDATE email_sends SET opened_at=NOW(), status='opened' WHERE token=%s", (token,))
                        c.execute("INSERT INTO email_events (send_id, event_type) VALUES (%s, 'open')", (send_id,))
                        conn.commit()
        except Exception as e:
            print(f'[TRACK/open] {e}')
        return Response(_TRACKING_PIXEL, mimetype='image/gif',
                        headers={'Cache-Control': 'no-cache, no-store, must-revalidate'})

    @app.route('/api/track/c/<token>', methods=['GET'])
    def track_click(token):
        """Click tracking redirect."""
        import urllib.parse
        raw_url = request.args.get('url', '')
        original_url = urllib.parse.unquote(raw_url)
        if not original_url.startswith(('http://', 'https://')):
            original_url = 'https://extratordedados.com.br'
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT id, clicked_at FROM email_sends WHERE token=%s", (token,))
                row = c.fetchone()
                if row:
                    send_id, clicked_at = row
                    if not clicked_at:
                        c.execute("UPDATE email_sends SET clicked_at=NOW(), status='clicked' WHERE token=%s", (token,))
                    c.execute("INSERT INTO email_events (send_id, event_type, metadata) VALUES (%s, 'click', %s)",
                              (send_id, json.dumps({'url': original_url})))
                    conn.commit()
        except Exception as e:
            print(f'[TRACK/click] {e}')
        return redirect(original_url, code=302)

    @app.route('/api/track/unsubscribe/<token>', methods=['GET'])
    def track_unsubscribe(token):
        """Unsubscribe link handler."""
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT id FROM email_sends WHERE token=%s", (token,))
                row = c.fetchone()
                if row:
                    send_id = row[0]
                    c.execute("UPDATE email_sends SET unsubscribed_at=NOW(), status='unsubscribed' WHERE token=%s", (token,))
                    c.execute("INSERT INTO email_events (send_id, event_type) VALUES (%s, 'unsubscribe')", (send_id,))
                    conn.commit()
        except Exception as e:
            print(f'[TRACK/unsubscribe] {e}')
        html = '<html><body style="font-family:sans-serif;text-align:center;padding:60px"><h2>Descadastrado com sucesso</h2><p>Você não receberá mais emails desta campanha.</p></body></html>'
        return make_response(html, 200)

    # ── Campaign CRUD ─────────────────────────────────────────────────────────

    @app.route('/api/campaigns', methods=['POST'])
    def create_campaign():
        user_id = _verify_token(_get_auth_header())
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'name required'}), 400
        steps = data.get('steps', [])
        target_filter = data.get('target_filter', {})
        from_name = (data.get('from_name') or '').strip() or None
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO email_campaigns (user_id, name, status, target_filter, from_name) VALUES (%s,%s,'draft',%s,%s) RETURNING id",
                    (user_id, name, json.dumps(target_filter), from_name)
                )
                campaign_id = c.fetchone()[0]
                for i, step in enumerate(steps, start=1):
                    c.execute("""
                        INSERT INTO email_steps (campaign_id, step_num, subject, body_html, delay_days, condition)
                        VALUES (%s,%s,%s,%s,%s,%s)
                    """, (
                        campaign_id, i,
                        step.get('subject', ''),
                        step.get('body_html', ''),
                        step.get('delay_days', 0),
                        step.get('condition', 'always'),
                    ))
                conn.commit()
            return jsonify({'id': campaign_id, 'name': name}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/campaigns', methods=['GET'])
    def list_campaigns():
        user_id = _verify_token(_get_auth_header())
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT ec.id, ec.name, ec.status, ec.created_at,
                        COUNT(DISTINCT es.id) AS total_sends,
                        COUNT(DISTINCT CASE WHEN es.opened_at IS NOT NULL THEN es.id END) AS opens,
                        COUNT(DISTINCT CASE WHEN es.clicked_at IS NOT NULL THEN es.id END) AS clicks,
                        COUNT(DISTINCT CASE WHEN es.unsubscribed_at IS NOT NULL THEN es.id END) AS unsubs,
                        (SELECT COUNT(*) FROM email_steps WHERE campaign_id=ec.id) AS steps_count
                    FROM email_campaigns ec
                    LEFT JOIN email_sends es ON es.campaign_id = ec.id AND es.status != 'pending'
                    WHERE ec.user_id = %s
                    GROUP BY ec.id
                    ORDER BY ec.created_at DESC
                """, (user_id,))
                rows = c.fetchall()
                campaigns = []
                for r in rows:
                    total = r[4] or 0
                    opens = r[5] or 0
                    clicks = r[6] or 0
                    campaigns.append({
                        'id': r[0], 'name': r[1], 'status': r[2],
                        'created_at': r[3].isoformat() if r[3] else None,
                        'total_sends': total,
                        'open_rate': round(opens / total * 100, 1) if total else 0,
                        'click_rate': round(clicks / total * 100, 1) if total else 0,
                        'unsubs': r[7] or 0,
                        'steps_count': r[8] or 0,
                    })
            return jsonify(campaigns)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/campaigns/<int:campaign_id>', methods=['GET'])
    def get_campaign(campaign_id):
        user_id = _verify_token(_get_auth_header())
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT id, name, status, target_filter, created_at, from_name FROM email_campaigns WHERE id=%s AND user_id=%s",
                          (campaign_id, user_id))
                row = c.fetchone()
                if not row:
                    return jsonify({'error': 'not found'}), 404
                c.execute("SELECT id, step_num, subject, body_html, delay_days, condition FROM email_steps WHERE campaign_id=%s ORDER BY step_num",
                          (campaign_id,))
                steps = [{'id': s[0], 'step_num': s[1], 'subject': s[2], 'body_html': s[3],
                          'delay_days': s[4], 'condition': s[5]} for s in c.fetchall()]
                campaign = {
                    'id': row[0], 'name': row[1], 'status': row[2],
                    'target_filter': row[3] or {},
                    'created_at': row[4].isoformat() if row[4] else None,
                    'from_name': row[5],
                    'steps': steps,
                }
            return jsonify(campaign)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/campaigns/<int:campaign_id>', methods=['DELETE'])
    def delete_campaign(campaign_id):
        user_id = _verify_token(_get_auth_header())
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM email_campaigns WHERE id=%s AND user_id=%s", (campaign_id, user_id))
                conn.commit()
            return jsonify({'deleted': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/campaigns/<int:campaign_id>', methods=['PUT'])
    def update_campaign(campaign_id):
        """Update campaign name and steps (only allowed when status=draft)."""
        user_id = _verify_token(_get_auth_header())
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json() or {}
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT id, status FROM email_campaigns WHERE id=%s AND user_id=%s",
                          (campaign_id, user_id))
                row = c.fetchone()
                if not row:
                    return jsonify({'error': 'not found'}), 404
                if row[1] not in ('draft',):
                    return jsonify({'error': 'can only edit draft campaigns'}), 409
                if 'name' in data:
                    name = (data['name'] or '').strip()
                    if name:
                        c.execute("UPDATE email_campaigns SET name=%s, updated_at=NOW() WHERE id=%s",
                                  (name, campaign_id))
                if 'steps' in data:
                    c.execute("DELETE FROM email_steps WHERE campaign_id=%s", (campaign_id,))
                    for i, step in enumerate(data['steps'], start=1):
                        c.execute("""
                            INSERT INTO email_steps (campaign_id, step_num, subject, body_html, delay_days, condition)
                            VALUES (%s,%s,%s,%s,%s,%s)
                        """, (campaign_id, i, step.get('subject', ''), step.get('body_html', ''),
                              step.get('delay_days', 0), step.get('condition', 'always')))
                if 'target_filter' in data:
                    c.execute("UPDATE email_campaigns SET target_filter=%s, updated_at=NOW() WHERE id=%s",
                              (json.dumps(data['target_filter']), campaign_id))
                if 'from_name' in data:
                    from_name = (data['from_name'] or '').strip() or None
                    c.execute("UPDATE email_campaigns SET from_name=%s, updated_at=NOW() WHERE id=%s",
                              (from_name, campaign_id))
                conn.commit()
            return jsonify({'updated': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/campaigns/<int:campaign_id>/send', methods=['POST'])
    @limiter.limit("5/hour")
    def send_campaign(campaign_id):
        """Queue campaign step-1 send in background thread. Returns 202 immediately."""
        user_id = _verify_token(_get_auth_header())
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT id, name, status, target_filter, from_name FROM email_campaigns WHERE id=%s AND user_id=%s",
                          (campaign_id, user_id))
                camp = c.fetchone()
                if not camp:
                    return jsonify({'error': 'not found'}), 404
                if camp[2] == 'sending':
                    return jsonify({'error': 'already sending'}), 409
                camp_from_name = camp[4]

                c.execute("SELECT id, subject, body_html FROM email_steps WHERE campaign_id=%s AND step_num=1", (campaign_id,))
                step = c.fetchone()
                if not step:
                    return jsonify({'error': 'no step 1 defined'}), 400
                step_id, subject, body_html = step

                tf = camp[3] or {}
                quality_filter = tf.get('quality_grade')
                limit = min(int(tf.get('limit', 500)), 2000)

                query = "SELECT id, email, company_name FROM leads WHERE email IS NOT NULL AND email != '' AND quality_grade != 'F'"
                params = []
                if quality_filter:
                    query += " AND quality_grade=%s"
                    params.append(quality_filter)
                query += f" LIMIT {limit}"
                c.execute(query, params)
                leads = c.fetchall()

                c.execute("SELECT DISTINCT email FROM email_sends WHERE campaign_id=%s", (campaign_id,))
                already_sent = {r[0].lower() for r in c.fetchall()}

                c.execute("SELECT DISTINCT email FROM email_sends WHERE unsubscribed_at IS NOT NULL")
                unsubscribed = {r[0].lower() for r in c.fetchall()}

                c.execute("UPDATE email_campaigns SET status='sending', updated_at=NOW() WHERE id=%s", (campaign_id,))
                conn.commit()

            import threading as _thr
            t = _thr.Thread(
                target=_run_campaign_send_background,
                args=(campaign_id, step_id, subject, body_html, leads, already_sent, unsubscribed),
                kwargs={'from_name': camp_from_name},
                daemon=True,
            )
            t.start()
            return jsonify({
                'status': 'queued',
                'campaign_id': campaign_id,
                'leads_to_process': len(leads),
                'message': f'Envio iniciado para até {len(leads)} leads. Acompanhe o status da campanha.',
            }), 202
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/campaigns/<int:campaign_id>/stats', methods=['GET'])
    def campaign_stats(campaign_id):
        user_id = _verify_token(_get_auth_header())
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT id FROM email_campaigns WHERE id=%s AND user_id=%s", (campaign_id, user_id))
                if not c.fetchone():
                    return jsonify({'error': 'not found'}), 404

                c.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE status='sent') AS sent,
                        COUNT(*) FILTER (WHERE status='opened') AS opened,
                        COUNT(*) FILTER (WHERE status='clicked') AS clicked,
                        COUNT(*) FILTER (WHERE status='failed') AS failed,
                        COUNT(*) FILTER (WHERE status='unsubscribed') AS unsubscribed,
                        COUNT(*) AS total
                    FROM email_sends WHERE campaign_id=%s
                """, (campaign_id,))
                r = c.fetchone()
                total = r[5] or 0
                sent = (r[0] or 0) + (r[1] or 0) + (r[2] or 0)
                opens = r[1] or 0
                clicks = r[2] or 0

                c.execute("""
                    SELECT DATE(occurred_at) AS day, event_type, COUNT(*) AS cnt
                    FROM email_events ee
                    JOIN email_sends es ON es.id=ee.send_id
                    WHERE es.campaign_id=%s AND occurred_at >= NOW()-INTERVAL '14 days'
                    GROUP BY day, event_type ORDER BY day
                """, (campaign_id,))
                timeline = [{'date': str(r[0]), 'event': r[1], 'count': r[2]} for r in c.fetchall()]

                return jsonify({
                    'total': total,
                    'sent': sent,
                    'open_rate': round(opens / sent * 100, 1) if sent else 0,
                    'click_rate': round(clicks / sent * 100, 1) if sent else 0,
                    'failed': r[3] or 0,
                    'unsubscribed': r[4] or 0,
                    'timeline': timeline,
                })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/campaigns/provider-status', methods=['GET'])
    def campaigns_provider_status():
        """Return daily quota usage per provider."""
        user_id = _verify_token(_get_auth_header())
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        result = []
        for p in _EMAIL_PROVIDERS:
            used = _get_provider_usage(p['name'])
            result.append({
                'provider': p['name'],
                'used': used,
                'limit': p['daily_limit'],
                'remaining': max(0, p['daily_limit'] - used),
            })
        return jsonify(result)

    @app.route('/api/campaigns/<int:campaign_id>/log', methods=['GET'])
    def campaign_log(campaign_id):
        """Paginated send log for a campaign — real-time progress feed."""
        user_id = _verify_token(_get_auth_header())
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(100, int(request.args.get('per_page', 50)))
        offset = (page - 1) * per_page
        status_filter = request.args.get('status')
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT id FROM email_campaigns WHERE id=%s AND user_id=%s", (campaign_id, user_id))
                if not c.fetchone():
                    return jsonify({'error': 'not found'}), 404

                where = "es.campaign_id=%s"
                params = [campaign_id]
                if status_filter:
                    where += " AND es.status=%s"
                    params.append(status_filter)

                c.execute(f"SELECT COUNT(*) FROM email_sends es WHERE {where}", params)
                total = c.fetchone()[0]

                c.execute(f"""
                    SELECT es.id, es.email, es.provider, es.status, es.step_id,
                           es.sent_at, es.opened_at, es.clicked_at, es.bounced_at, es.error_msg,
                           est.step_num, est.subject
                    FROM email_sends es
                    LEFT JOIN email_steps est ON est.id = es.step_id
                    WHERE {where}
                    ORDER BY es.sent_at DESC NULLS LAST, es.id DESC
                    LIMIT %s OFFSET %s
                """, params + [per_page, offset])
                items = []
                for row in c.fetchall():
                    items.append({
                        'id': row[0],
                        'email': row[1],
                        'provider': row[2],
                        'status': row[3],
                        'step_id': row[4],
                        'sent_at': row[5].isoformat() if row[5] else None,
                        'opened_at': row[6].isoformat() if row[6] else None,
                        'clicked_at': row[7].isoformat() if row[7] else None,
                        'bounced_at': row[8].isoformat() if row[8] else None,
                        'error_msg': row[9],
                        'step_num': row[10],
                        'subject': row[11],
                    })
                return jsonify({
                    'total': total,
                    'page': page,
                    'per_page': per_page,
                    'pages': max(1, (total + per_page - 1) // per_page),
                    'items': items,
                })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ── Bounce webhooks ───────────────────────────────────────────────────────

    @app.route('/api/webhooks/bounces/brevo', methods=['POST'])
    def webhook_bounce_brevo():
        """Receive Brevo webhook events (hard_bounce, soft_bounce, blocked, spam)."""
        data = request.get_json(silent=True) or {}
        event = data.get('event', '')
        if event not in ('hard_bounce', 'soft_bounce', 'blocked', 'spam'):
            return jsonify({'ok': True, 'skipped': True})
        email = (data.get('email') or '').lower()
        bounce_type = 'hard' if event in ('hard_bounce', 'spam') else 'soft'
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("""
                    UPDATE email_sends
                    SET status='bounced', bounced_at=NOW(), bounce_type=%s
                    WHERE email=%s AND bounced_at IS NULL
                    RETURNING id
                """, (bounce_type, email))
                updated = c.rowcount
                if updated:
                    conn.commit()
                    print(f'[BOUNCE-BREVO] {event} email={email} type={bounce_type} rows={updated}')
                else:
                    conn.rollback()
            return jsonify({'ok': True, 'updated': updated})
        except Exception as e:
            print(f'[BOUNCE-BREVO] error: {e}')
            return jsonify({'error': str(e)}), 500

    @app.route('/api/webhooks/bounces/resend', methods=['POST'])
    def webhook_bounce_resend():
        """Receive Resend webhook events (email.bounced, email.complained)."""
        data = request.get_json(silent=True) or {}
        event_type = data.get('type', '')
        if event_type not in ('email.bounced', 'email.complained'):
            return jsonify({'ok': True, 'skipped': True})
        email_data = data.get('data', {})
        to_field = email_data.get('to', '')
        email = (to_field[0] if isinstance(to_field, list) else to_field or '').lower()
        if not email:
            return jsonify({'ok': False, 'error': 'no email in payload'}), 400
        bounce_type = 'hard' if event_type == 'email.bounced' else 'soft'
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("""
                    UPDATE email_sends
                    SET status='bounced', bounced_at=NOW(), bounce_type=%s
                    WHERE email=%s AND bounced_at IS NULL
                    RETURNING id
                """, (bounce_type, email))
                updated = c.rowcount
                if updated:
                    conn.commit()
                    print(f'[BOUNCE-RESEND] {event_type} email={email} type={bounce_type} rows={updated}')
                else:
                    conn.rollback()
            return jsonify({'ok': True, 'updated': updated})
        except Exception as e:
            print(f'[BOUNCE-RESEND] error: {e}')
            return jsonify({'error': str(e)}), 500
