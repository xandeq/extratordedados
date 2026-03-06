import os
"""
AUTO-SYNC TO ALEXANDREQUEIROZ.COM.BR API
Add this code to app.py after line ~300 (after DB connection pool setup)
"""

# ============= Alexandre Queiroz API Sync =============

ALEXANDREQUEIROZ_API = 'https://api.alexandrequeiroz.com.br'
ALEXANDREQUEIROZ_EMAIL = 'admin@alexandrequeiroz.com.br'
ALEXANDREQUEIROZ_PASSWORD = os.environ.get('CRM_PASS', '')

# Global token cache (expires in 6 hours)
_alexandrequeiroz_token = None
_alexandrequeiroz_token_expires = None

def get_alexandrequeiroz_token():
    """Get or refresh API token for alexandrequeiroz.com.br"""
    global _alexandrequeiroz_token, _alexandrequeiroz_token_expires

    # Check if token is still valid (with 1 minute buffer)
    if _alexandrequeiroz_token and _alexandrequeiroz_token_expires:
        if datetime.now() < (_alexandrequeiroz_token_expires - timedelta(minutes=1)):
            return _alexandrequeiroz_token

    # Login to get new token
    try:
        response = http_requests.post(
            f'{ALEXANDREQUEIROZ_API}/api/v1/auth/login',
            json={
                'email': ALEXANDREQUEIROZ_EMAIL,
                'password': ALEXANDREQUEIROZ_PASSWORD
            },
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            _alexandrequeiroz_token = data.get('token')
            # Token expires in 6 hours
            _alexandrequeiroz_token_expires = datetime.now() + timedelta(hours=6)
            print(f"[SYNC] Obtained new token for alexandrequeiroz.com.br")
            return _alexandrequeiroz_token
        else:
            print(f"[SYNC] Login failed: {response.status_code} - {response.text[:200]}")
            return None
    except Exception as e:
        print(f"[SYNC] Login error: {e}")
        return None


def sync_lead_to_alexandrequeiroz(lead_data):
    """
    Sync a single lead to alexandrequeiroz.com.br API
    Returns: (success: bool, message: str, customer_id: str or None)
    """
    token = get_alexandrequeiroz_token()
    if not token:
        return False, "Failed to obtain API token", None

    # Extract and validate data
    email = (lead_data.get('email') or '').strip()
    if not email or '@' not in email:
        return False, "Invalid email", None

    company_name = lead_data.get('company_name') or lead_data.get('name') or 'Lead sem nome'
    phone = lead_data.get('phone') or None
    website = lead_data.get('website') or None
    city = lead_data.get('city') or None
    state = lead_data.get('state') or None

    # Build payload matching alexandrequeiroz.com.br schema
    payload = {
        'name': company_name,
        'companyName': company_name,
        'email': email,
        'phone': phone,
        'website': website,
    }

    # Optional fields
    if city and state:
        # API may accept address field or separate city/state
        payload['notes'] = f"Origem: Extrator de Dados\nCidade: {city}\nEstado: {state}"

    # Add source information
    source = lead_data.get('source', 'extrator-dados')
    if source:
        if 'notes' in payload:
            payload['notes'] += f"\nFonte: {source}"
        else:
            payload['notes'] = f"Origem: Extrator de Dados\nFonte: {source}"

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    try:
        # First, check if lead already exists (GET with email filter)
        check_response = http_requests.get(
            f'{ALEXANDREQUEIROZ_API}/api/v1/customers',
            headers=headers,
            params={'search': email, 'pageSize': 1},
            timeout=10
        )

        if check_response.status_code == 200:
            data = check_response.json()
            items = data.get('items', [])

            # If lead exists, check if it's the same email
            if items and len(items) > 0:
                existing_lead = items[0]
                existing_email = (existing_lead.get('email') or '').strip().lower()
                if existing_email == email.lower():
                    customer_id = existing_lead.get('id')
                    return True, f"Lead already exists (skipped)", customer_id

        # Lead doesn't exist, create it
        create_response = http_requests.post(
            f'{ALEXANDREQUEIROZ_API}/api/v1/customers',
            headers=headers,
            json=payload,
            timeout=15
        )

        if create_response.status_code in [200, 201]:
            result = create_response.json()
            customer_id = result.get('id')
            print(f"[SYNC] ✅ Created lead: {email} -> ID: {customer_id}")
            return True, "Lead created successfully", customer_id
        elif create_response.status_code == 409:
            # Conflict - lead already exists
            return True, "Lead already exists (409)", None
        else:
            error_msg = create_response.text[:200]
            print(f"[SYNC] ❌ Failed to create lead: {create_response.status_code} - {error_msg}")
            return False, f"API error: {create_response.status_code}", None

    except Exception as e:
        print(f"[SYNC] ❌ Exception syncing lead: {e}")
        return False, f"Exception: {str(e)[:100]}", None


def sync_leads_batch_to_alexandrequeiroz(leads_list, max_leads=100):
    """
    Sync multiple leads to alexandrequeiroz.com.br
    Returns: (total_synced: int, total_skipped: int, total_errors: int)
    """
    synced = 0
    skipped = 0
    errors = 0

    for lead in leads_list[:max_leads]:
        success, message, customer_id = sync_lead_to_alexandrequeiroz(lead)

        if success:
            if "already exists" in message or "skipped" in message:
                skipped += 1
            else:
                synced += 1
        else:
            errors += 1

        # Small delay to avoid rate limiting
        time.sleep(0.2)

    print(f"[SYNC] Batch sync complete: {synced} created, {skipped} skipped, {errors} errors")
    return synced, skipped, errors


def auto_sync_new_leads_background(batch_id):
    """
    Background thread to automatically sync new leads from a batch
    to alexandrequeiroz.com.br API
    """
    print(f"[SYNC] Starting auto-sync for batch {batch_id}")

    # Wait 5 seconds to let the extraction process start
    time.sleep(5)

    # Get dedicated DB connection for this thread
    conn = psycopg2.connect(**DB_CONFIG)
    c = conn.cursor()

    try:
        # Wait up to 10 minutes for batch to complete
        max_wait = 600  # 10 minutes
        elapsed = 0

        while elapsed < max_wait:
            # Check batch status
            c.execute('SELECT status FROM batches WHERE id = %s', (batch_id,))
            row = c.fetchone()

            if not row:
                print(f"[SYNC] Batch {batch_id} not found")
                return

            status = row[0]

            if status == 'completed':
                break
            elif status == 'failed':
                print(f"[SYNC] Batch {batch_id} failed, aborting sync")
                return

            # Wait 10 seconds before checking again
            time.sleep(10)
            elapsed += 10

        # Get all leads from this batch
        c.execute(
            '''SELECT company_name, email, phone, website, city, state, source
               FROM leads
               WHERE batch_id = %s AND email IS NOT NULL AND email != \'\'
               ORDER BY extracted_at DESC''',
            (batch_id,)
        )
        rows = c.fetchall()

        if not rows:
            print(f"[SYNC] No leads with email found for batch {batch_id}")
            return

        leads_to_sync = []
        for row in rows:
            leads_to_sync.append({
                'company_name': row[0],
                'email': row[1],
                'phone': row[2],
                'website': row[3],
                'city': row[4],
                'state': row[5],
                'source': row[6] or 'extrator-dados',
            })

        print(f"[SYNC] Found {len(leads_to_sync)} leads to sync for batch {batch_id}")

        # Sync in batches of 50
        synced, skipped, errors = sync_leads_batch_to_alexandrequeiroz(leads_to_sync, max_leads=200)

        print(f"[SYNC] ✅ Batch {batch_id} sync complete: {synced} created, {skipped} skipped, {errors} errors")

    except Exception as e:
        print(f"[SYNC] ❌ Error in auto-sync for batch {batch_id}: {e}")
    finally:
        c.close()
        conn.close()


# IMPORTANT: Add these lines in the endpoints that create leads:
# - After creating a batch in /api/batch
# - After creating a batch in /api/search
# - After importing leads in /api/leads/import
#
# Example:
# threading.Thread(target=auto_sync_new_leads_background, args=(batch_id,), daemon=True).start()
