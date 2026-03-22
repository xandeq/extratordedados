# Lead Quality, Email Validation & Enrichment — Research Report

**Domain:** B2B Lead Quality for Brazilian Companies
**Researched:** 2026-03-22
**Overall confidence:** HIGH (email/phone topics) | MEDIUM (enrichment APIs) | LOW (some free-tier limits — verify before relying on them)

---

## 1. Free Email Validation Methods in Python (No Paid API)

### Recommended: Multi-Layer Approach

Use all three layers in sequence. Each layer catches different failure modes.

#### Layer 1 — Syntax + Normalization
**Library:** `email-validator` (PyPI: `email-validator`)

- Best-maintained library for format validation (Python 3.8+)
- Handles international domains, unicode local parts, display names
- Returns normalized email (lowercased domain, unicode normalization)
- Does NOT do MX probing by default — add DNS check explicitly

```python
pip install email-validator
```

```python
from email_validator import validate_email, EmailNotValidError

def validate_syntax(email: str) -> tuple[bool, str]:
    try:
        info = validate_email(email, check_deliverability=False)
        return True, info.normalized  # normalized form
    except EmailNotValidError as e:
        return False, str(e)
```

#### Layer 2 — MX Record Check (DNS)
**Library:** `dnspython` (PyPI: `dnspython`)

MX record check is the sweet spot: free, fast (~100ms), catches dead domains (domain no longer exists, no mail server configured). Does NOT confirm the mailbox exists — only that the domain can receive mail.

```python
pip install dnspython
```

```python
import dns.resolver

def check_mx(domain: str) -> bool:
    """Returns True if domain has at least one valid MX record."""
    try:
        answers = dns.resolver.resolve(domain, 'MX', lifetime=5.0)
        return len(answers) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer,
            dns.resolver.NoNameservers, dns.exception.Timeout):
        return False

# Fallback: if no MX, check for A/AAAA record (some domains accept mail via A)
def check_mx_with_fallback(domain: str) -> bool:
    try:
        dns.resolver.resolve(domain, 'MX', lifetime=5.0)
        return True
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        try:
            dns.resolver.resolve(domain, 'A', lifetime=5.0)
            return True
        except Exception:
            return False
    except Exception:
        return False
```

**Cache MX results.** For a batch of 1000 emails from 50 companies, the same domain appears repeatedly. Use `functools.lru_cache` or a dict cache keyed by domain with a TTL of 24h. This reduces DNS queries by 80%+.

```python
from functools import lru_cache

@lru_cache(maxsize=1024)
def check_mx_cached(domain: str) -> bool:
    return check_mx_with_fallback(domain)
```

#### Layer 3 — SMTP Probe (Use With Caution)

**Library:** `py3-validate-email` or `verify-email` or raw `smtplib`

SMTP probing opens a connection to the mail server and checks if the RCPT TO: command is accepted. This can confirm mailbox existence — but:

- Many modern servers (Gmail, Outlook, Yahoo) give a false positive for ALL addresses (catch-all) to prevent harvesting
- Some ISPs block port 25 outbound (VPS Hostinger likely blocks 25)
- Graylisting can cause timeouts
- Aggressive probing triggers SMTP blocking/blacklisting of your VPS IP

**Verdict:** Only use SMTP probing in a controlled, low-volume context (e.g., when a user manually clicks "verify" on a single lead). Do NOT run it in batch.

```python
import smtplib
import socket

def smtp_probe(email: str, timeout: int = 10) -> str:
    """
    Returns: 'valid', 'invalid', 'catch_all', 'error'
    NOTE: unreliable for major providers, may cause IP blacklisting at scale.
    """
    domain = email.split('@')[1]
    try:
        records = dns.resolver.resolve(domain, 'MX', lifetime=5.0)
        mx_host = str(sorted(records, key=lambda r: r.preference)[0].exchange)

        with smtplib.SMTP(timeout=timeout) as smtp:
            smtp.connect(mx_host, 25)
            smtp.helo('validator.yourdomain.com')
            smtp.mail('noreply@yourdomain.com')
            code, _ = smtp.rcpt(email)
            if code == 250:
                return 'valid'
            elif code == 550:
                return 'invalid'
            else:
                return 'error'
    except Exception:
        return 'error'
```

#### Complete Free Validation Pipeline

```python
def validate_email_free(email: str) -> dict:
    """
    Returns a dict with validation result and quality signal.
    Cost: free. Latency: ~100-300ms (DNS).
    """
    result = {
        'email': email,
        'syntax_ok': False,
        'normalized': None,
        'mx_ok': False,
        'is_disposable': False,
        'is_free_provider': False,
        'score': 0,
        'reason': None
    }

    # Layer 1: syntax
    ok, normalized = validate_syntax(email)
    if not ok:
        result['reason'] = 'invalid_syntax'
        return result
    result['syntax_ok'] = True
    result['normalized'] = normalized

    domain = normalized.split('@')[1].lower()

    # Layer 2: disposable check (instant, no network)
    from disposable_email_domains import blocklist
    if domain in blocklist:
        result['is_disposable'] = True
        result['reason'] = 'disposable_domain'
        return result

    # Layer 3: free provider flag (informational, not a disqualifier for B2B)
    FREE_PROVIDERS = {'gmail.com', 'hotmail.com', 'yahoo.com', 'outlook.com',
                      'live.com', 'icloud.com', 'uol.com.br', 'bol.com.br',
                      'ig.com.br', 'terra.com.br', 'globo.com', 'r7.com'}
    if domain in FREE_PROVIDERS:
        result['is_free_provider'] = True

    # Layer 4: MX record (cached)
    result['mx_ok'] = check_mx_cached(domain)
    if not result['mx_ok']:
        result['reason'] = 'no_mx_record'
        return result

    # Score: corporate email is better for B2B
    score = 60
    if not result['is_free_provider']:
        score += 30
    result['score'] = score
    result['reason'] = 'ok'
    return result
```

**Packages to install:**
```
email-validator>=2.1.0
dnspython>=2.6.0
disposable-email-domains>=0.0.100
```

---

## 2. Free/Cheap Email Validation APIs

### Comparison Table

| API | Free Tier | Price After Free | SMTP Check | Disposable Detection | Notes |
|-----|-----------|-----------------|------------|---------------------|-------|
| **ZeroBounce** | 100/month (recurring) | ~$0.008/validation | Yes | Yes | Best recurring free tier; 99.6% accuracy claim |
| **Abstract API** | 100/month (recurring) | Paid plans | Yes | Yes | Rate: 1 req/sec on free |
| **Mailboxlayer** | 250/month | ~$0.003/req | Yes | Yes | via APILayer; SMTP optional param |
| **DeBounce** | 100 credits signup + 10/day unregistered | $0.003/validation | Yes | Yes | 5 concurrent calls max |
| **NeverBounce** | 1,000 one-time signup | ~$0.008/credit | Yes | Yes | One-time only, not recurring |
| **Hunter.io** (verifier only) | 25/month | 50 credits/$9 | Yes | No | Combined with email finder |

### Recommendation for This Project

**Strategy:** ZeroBounce free (100/month) as a "manual verify" feature for the user, not for batch auto-validation. Reserve paid API calls for high-value leads only.

**Python integration — ZeroBounce:**
```python
import requests
import boto3
import json

def get_zerobounce_key() -> str:
    client = boto3.client('secretsmanager', region_name='us-east-1')
    secret = client.get_secret_value(SecretId='tools/zerobounce')
    return json.loads(secret['SecretString'])['ZEROBOUNCE_API_KEY']

def validate_zerobounce(email: str) -> dict:
    api_key = get_zerobounce_key()
    url = "https://api.zerobounce.net/v2/validate"
    params = {"api_key": api_key, "email": email, "ip_address": ""}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    # status values: "valid", "invalid", "catch-all", "unknown", "spamtrap", "abuse", "do_not_mail"
    return {
        'email': email,
        'status': data.get('status'),
        'sub_status': data.get('sub_status'),
        'is_valid': data.get('status') == 'valid',
        'is_disposable': data.get('sub_status') == 'disposable',
        'did_you_mean': data.get('did_you_mean'),  # typo correction
    }
```

**Python integration — Mailboxlayer (via APILayer):**
```python
def validate_mailboxlayer(email: str) -> dict:
    # Store key at tools/mailboxlayer in AWS SM
    api_key = get_secret('tools/mailboxlayer', 'MAILBOXLAYER_API_KEY')
    url = "https://apilayer.net/api/check"
    params = {"access_key": api_key, "email": email, "smtp": 1, "format": 1}
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    return {
        'email': email,
        'format_valid': data.get('format_valid'),
        'mx_found': data.get('mx_found'),
        'smtp_check': data.get('smtp_check'),
        'is_disposable': data.get('disposable'),
        'score': data.get('score'),
    }
```

---

## 3. Detecting Disposable/Temporary Emails in Python

### Primary: Blocklist-Based (Recommended)

**Package:** `disposable-email-domains` (PyPI)

```
pip install disposable-email-domains
```

```python
from disposable_email_domains import blocklist

def is_disposable(email: str) -> bool:
    domain = email.split('@')[-1].strip().lower()
    return domain in blocklist

# blocklist is a Python set — O(1) lookup, ~100k+ domains
# Updated with each package release; pin to a recent version
```

The underlying GitHub repo (`disposable-email-domains/disposable-email-domains`) is community-maintained and updated continuously. The Python package mirrors it. As of 2025, covers 100,000+ domains.

**Limitation:** Doesn't catch brand-new disposable services that haven't been added yet. Combine with free-provider detection and SMTP API for better coverage.

### Secondary: Live-Check Approach

Some disposable services (mailnator, guerrilla mail, tempmail) have their own APIs. But the blocklist covers 99% of them, so a live check adds complexity without much gain.

### Known Disposable Domains Commonly Seen in BR Market

```python
# Supplement the package with common BR-specific throwaway patterns
BR_DISPOSABLE_PATTERNS = [
    'mailinator.com', 'guerrillamail.com', 'tempmail.com',
    'sharklasers.com', 'guerrillamailblock.com', 'grr.la',
    'yopmail.com', 'trashmail.com', 'dispostable.com',
    '10minutemail.com', 'throwam.com', 'fakeinbox.com',
]
```

### Handling Business Freemail (Not Disposable, But Weak)

For B2B leads, a `@gmail.com` or `@hotmail.com` is not disposable but signals the lead didn't provide a corporate email. Flag these separately:

```python
FREEMAIL_DOMAINS_BR = {
    'gmail.com', 'googlemail.com',
    'hotmail.com', 'hotmail.com.br', 'outlook.com', 'live.com',
    'yahoo.com', 'yahoo.com.br',
    'uol.com.br', 'bol.com.br', 'ig.com.br',
    'terra.com.br', 'globo.com', 'r7.com', 'oi.com.br',
}

def email_type(email: str) -> str:
    """Returns: 'corporate', 'freemail', 'disposable'"""
    domain = email.split('@')[-1].lower()
    if is_disposable(email):
        return 'disposable'
    if domain in FREEMAIL_DOMAINS_BR:
        return 'freemail'
    return 'corporate'
```

---

## 4. Brazilian Phone Number Normalization

### Rules (HIGH confidence — Anatel official)

| Type | Format | Digits | Starts With |
|------|--------|--------|-------------|
| Mobile | `(DDD) 9XXXX-XXXX` | 9 digits after DDD | `9` |
| Landline | `(DDD) XXXX-XXXX` | 8 digits after DDD | `2`, `3`, `4`, `5` |
| Toll-free | `0800 XXX XXXX` | — | `0800` |
| Emergency | `190`, `192`, `193`, `197`, `198`, `199` | — | — |

**Key rule:** As of 2017, ALL mobile numbers in Brazil are 9 digits (starting with `9`). Some old 8-digit mobile numbers from before 2012 may still exist in old databases — treat them as potentially stale.

**Country code:** +55. Strip the `0` from DDD when dialing internationally.

**WhatsApp format:** `55DD9XXXXXXXX@c.us` (13 digits for mobile) or `55DDXXXXXXXX@c.us` (12 digits for landline). Both accepted.

### Complete DDD Validation Set

```python
VALID_DDD = {
    # SP
    11, 12, 13, 14, 15, 16, 17, 18, 19,
    # RJ, ES
    21, 22, 24, 27, 28,
    # MG
    31, 32, 33, 34, 35, 37, 38,
    # PR, SC
    41, 42, 43, 44, 45, 46, 47, 48, 49,
    # RS
    51, 53, 54, 55,
    # DF, GO, TO, MT, MS, RO, AC
    61, 62, 63, 64, 65, 66, 67, 68, 69,
    # BA, SE
    71, 73, 74, 75, 77, 79,
    # PE, AL, PB, RN
    81, 82, 83, 84, 85, 86, 87, 88, 89,
    # AM, RR, AP, PA, MA, PI, CE
    91, 92, 93, 94, 95, 96, 97, 98, 99,
}
```

### Recommended Library: `phonenumbers`

Google's libphonenumber ported to Python. Handles all edge cases including Brazilian 9-digit migration.

```
pip install phonenumbers
```

```python
import phonenumbers
from phonenumbers import PhoneNumberFormat, NumberParseException

def normalize_br_phone(raw: str) -> dict:
    """
    Normalizes a Brazilian phone number string.
    Returns dict with normalized forms and metadata.
    """
    result = {
        'raw': raw,
        'e164': None,          # +5511999998888
        'national': None,       # (11) 9 9999-8888
        'ddd': None,
        'number': None,
        'type': None,           # 'mobile', 'landline', 'toll_free', 'unknown'
        'is_whatsapp_likely': False,
        'valid': False,
        'normalized': None      # cleaned string for storage
    }

    if not raw:
        return result

    # Strip formatting — keep only digits
    digits_only = ''.join(filter(str.isdigit, raw))

    # Handle common prefixes
    if digits_only.startswith('55') and len(digits_only) >= 12:
        parse_str = '+' + digits_only
    elif digits_only.startswith('0'):
        digits_only = digits_only[1:]  # strip leading 0
        parse_str = '+55' + digits_only
    else:
        parse_str = '+55' + digits_only

    try:
        parsed = phonenumbers.parse(parse_str, 'BR')
    except NumberParseException:
        result['reason'] = 'parse_error'
        return result

    if not phonenumbers.is_valid_number(parsed):
        result['reason'] = 'invalid_number'
        return result

    result['valid'] = True
    result['e164'] = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    result['national'] = phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL)

    national_digits = ''.join(filter(str.isdigit, result['national']))
    result['ddd'] = int(national_digits[:2]) if len(national_digits) >= 2 else None
    result['number'] = national_digits[2:]

    # Type detection
    num_type = phonenumbers.number_type(parsed)
    from phonenumbers import PhoneNumberType
    if num_type == PhoneNumberType.MOBILE:
        result['type'] = 'mobile'
        result['is_whatsapp_likely'] = True
    elif num_type in (PhoneNumberType.FIXED_LINE, PhoneNumberType.FIXED_LINE_OR_MOBILE):
        result['type'] = 'landline'
    elif num_type == PhoneNumberType.TOLL_FREE:
        result['type'] = 'toll_free'
    else:
        result['type'] = 'unknown'

    # Normalized storage format: E.164 without +
    result['normalized'] = result['e164'].lstrip('+')  # 5511999998888

    return result
```

### WhatsApp ID Generation

```python
def to_whatsapp_id(phone_e164: str) -> str:
    """Converts E.164 to WhatsApp ID format."""
    digits = phone_e164.lstrip('+')  # remove +
    return f"{digits}@c.us"

# For mobile:  5511999998888@c.us
# For landline: 551132223333@c.us
```

### Batch Normalization with Stats

```python
def normalize_phones_batch(leads: list[dict]) -> dict:
    stats = {'total': 0, 'valid': 0, 'mobile': 0, 'landline': 0, 'invalid': 0}
    for lead in leads:
        raw = lead.get('phone') or ''
        result = normalize_br_phone(raw)
        stats['total'] += 1
        if result['valid']:
            lead['phone_normalized'] = result['normalized']
            lead['phone_type'] = result['type']
            lead['phone_ddd'] = result['ddd']
            lead['whatsapp'] = to_whatsapp_id(result['e164']) if result['is_whatsapp_likely'] else None
            stats['valid'] += 1
            if result['type'] == 'mobile':
                stats['mobile'] += 1
            else:
                stats['landline'] += 1
        else:
            lead['phone_normalized'] = None
            stats['invalid'] += 1
    return stats
```

---

## 5. Lead Freshness / Staleness Tracking

### The Problem

Leads decay over time. A business email or phone from 12 months ago has a higher bounce/disconnect rate than one captured last week. B2B data decays at ~30% per year (industry estimate).

### Recommended Approach: Freshness Score + Decay

#### Database Schema Addition

```sql
-- Add to leads table
ALTER TABLE leads ADD COLUMN IF NOT EXISTS captured_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_contacted_at TIMESTAMPTZ;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS freshness_score INT DEFAULT 100;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS staleness_days INT;
```

#### Freshness Score Formula

```python
from datetime import datetime, timezone

def compute_freshness_score(lead: dict) -> int:
    """
    Returns 0-100. 100 = captured today. Decays over time.

    Decay curve:
    - 0-30 days:   100 → 90  (very fresh)
    - 31-60 days:  90 → 75
    - 61-90 days:  75 → 60
    - 91-180 days: 60 → 40
    - 181-365 days: 40 → 20
    - 365+ days:   20 → 5 (never 0, lead might still be valid)
    """
    now = datetime.now(timezone.utc)

    # Use last_verified_at if available (verification resets freshness)
    ref_date = lead.get('last_verified_at') or lead.get('captured_at')
    if not ref_date:
        return 50  # unknown age → neutral

    if isinstance(ref_date, str):
        ref_date = datetime.fromisoformat(ref_date.replace('Z', '+00:00'))

    days = (now - ref_date).days

    if days <= 30:
        score = 100 - (days * 0.33)      # 100 → 90
    elif days <= 60:
        score = 90 - ((days - 30) * 0.5) # 90 → 75
    elif days <= 90:
        score = 75 - ((days - 60) * 0.5) # 75 → 60
    elif days <= 180:
        score = 60 - ((days - 90) * 0.22) # 60 → 40
    elif days <= 365:
        score = 40 - ((days - 180) * 0.108) # 40 → 20
    else:
        score = max(5, 20 - ((days - 365) / 365 * 15))  # floor at 5

    return max(5, int(score))
```

#### Staleness Flags

```python
STALE_THRESHOLDS = {
    'fresh': 60,        # 0-60 days
    'aging': 180,       # 61-180 days
    'stale': 365,       # 181-365 days
    'very_stale': None  # 365+ days
}

def get_staleness_label(days: int) -> str:
    if days <= 60:
        return 'fresh'
    elif days <= 180:
        return 'aging'
    elif days <= 365:
        return 'stale'
    else:
        return 'very_stale'
```

#### Automated Re-validation Trigger

Run a nightly job that flags leads for re-validation based on staleness:

```python
# SQL: get leads that need re-validation
REVALIDATE_SQL = """
    SELECT id, email, phone
    FROM leads
    WHERE (last_verified_at IS NULL AND captured_at < NOW() - INTERVAL '90 days')
       OR last_verified_at < NOW() - INTERVAL '180 days'
    ORDER BY captured_at ASC
    LIMIT 100
"""
```

#### Verification Event — Reset Freshness

Any of these events should reset `last_verified_at`:
- Email bounce confirmed (set `email_valid = FALSE`)
- Successful email delivery (no bounce)
- Phone call completed (human answered)
- Lead responds to any outreach
- User manually verifies in UI

---

## 6. Lead Quality Score — Trusted Dimensions

### Recommended Scoring Model

A quality score between 0-100, composed of weighted sub-scores. Built specifically for Brazilian B2B leads.

#### Dimension Weights

| Dimension | Weight | Rationale |
|-----------|--------|-----------|
| Email validity | 30% | Most critical channel for outreach |
| Phone completeness | 20% | Second most valuable for BR market (WhatsApp) |
| Data completeness | 20% | More fields = more context for sales |
| Freshness/recency | 15% | Time decay per Section 5 |
| CNPJ enrichment | 10% | Validated company = less likely fake |
| Source quality | 5% | Direct capture > scraped > imported |

#### Implementation

```python
def compute_lead_quality_score(lead: dict) -> dict:
    """
    Returns score 0-100 and breakdown dict.
    Store result in leads.quality_score and leads.quality_breakdown (JSONB).
    """
    breakdown = {}

    # --- EMAIL (30 pts) ---
    email = lead.get('email', '')
    if not email:
        breakdown['email'] = 0
    else:
        email_pts = 0
        # Syntax check
        from email_validator import validate_email, EmailNotValidError
        try:
            validate_email(email, check_deliverability=False)
            email_pts += 10  # valid syntax
        except EmailNotValidError:
            breakdown['email'] = 0
            pass

        if email_pts > 0:
            domain = email.split('@')[-1].lower()
            # MX check (cached)
            if check_mx_cached(domain):
                email_pts += 10
            # Corporate email bonus
            et = email_type(email)
            if et == 'corporate':
                email_pts += 10
            elif et == 'freemail':
                email_pts += 5
            else:  # disposable
                email_pts = 0

        breakdown['email'] = email_pts  # 0, 10, 20, or 30

    # --- PHONE (20 pts) ---
    phone = lead.get('phone', '')
    if not phone:
        breakdown['phone'] = 0
    else:
        phone_result = normalize_br_phone(phone)
        if not phone_result['valid']:
            breakdown['phone'] = 0
        elif phone_result['type'] == 'mobile':
            breakdown['phone'] = 20  # mobile = WhatsApp capable
        elif phone_result['type'] == 'landline':
            breakdown['phone'] = 12
        else:
            breakdown['phone'] = 5

    # --- DATA COMPLETENESS (20 pts) ---
    completeness_fields = {
        'company_name': 4,
        'email': 3,
        'phone': 3,
        'website': 2,
        'city': 2,
        'state': 2,
        'cnpj': 2,
        'category': 1,
        'address': 1,
    }
    completeness_pts = sum(
        pts for field, pts in completeness_fields.items()
        if lead.get(field)
    )
    breakdown['completeness'] = min(20, completeness_pts)

    # --- FRESHNESS (15 pts) ---
    freshness_score = compute_freshness_score(lead)  # 0-100
    breakdown['freshness'] = int(freshness_score * 0.15)  # scale to 15

    # --- CNPJ ENRICHMENT (10 pts) ---
    if lead.get('cnpj_enriched'):
        breakdown['cnpj'] = 10
    elif lead.get('cnpj'):
        breakdown['cnpj'] = 5  # has CNPJ but not enriched
    else:
        breakdown['cnpj'] = 0

    # --- SOURCE QUALITY (5 pts) ---
    source_scores = {
        'direct': 5,        # user manually entered
        'google_maps': 4,   # rich source
        'directories': 3,   # structured source
        'search_engines': 2, # scraped from web
        'imported': 1,      # unknown provenance
    }
    source = lead.get('source', '')
    breakdown['source'] = source_scores.get(source, 2)

    total = sum(breakdown.values())

    return {
        'score': min(100, max(0, total)),
        'breakdown': breakdown,
        'grade': _score_to_grade(total),
    }

def _score_to_grade(score: int) -> str:
    if score >= 80: return 'A'
    elif score >= 60: return 'B'
    elif score >= 40: return 'C'
    elif score >= 20: return 'D'
    else: return 'F'
```

#### Grade Interpretation for Clients

| Grade | Score | Meaning | Recommended Action |
|-------|-------|---------|-------------------|
| A | 80-100 | High confidence lead | Direct outreach |
| B | 60-79 | Good lead, minor gaps | Outreach + light enrichment |
| C | 40-59 | Incomplete data | Enrich before contacting |
| D | 20-39 | Low confidence | Verify before using |
| F | 0-19 | Likely invalid | Archive or re-scrape |

---

## 7. Free Enrichment APIs for Brazilian Companies

### Primary: BrasilAPI (FREE, no auth)

**URL:** `https://brasilapi.com.br/api/cnpj/v1/{cnpj}`
**Rate limit:** Not officially documented; community use suggests ~3 req/sec is safe.
**Fields returned:** razao_social, nome_fantasia, data_abertura, cnae_fiscal (primary CNAE), cnae_fiscal_descricao, natureza_juridica, descricao_natureza_juridica, porte (ME/EPP/MEDIO/GRANDE), email, telefone, logradouro, municipio, uf, situacao_cadastral, qsa (partners list)

```python
import requests, time

def enrich_cnpj_brasilapi(cnpj: str) -> dict | None:
    """Already implemented in your app.py. This is the reference."""
    cnpj_clean = ''.join(filter(str.isdigit, cnpj))
    if len(cnpj_clean) != 14:
        return None
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_clean}"
    try:
        resp = requests.get(url, timeout=10,
                           headers={'User-Agent': 'extrator-dados/1.0'})
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None
```

**Key fields to extract and store:**
```python
def extract_enrichment_fields(data: dict) -> dict:
    return {
        'razao_social': data.get('razao_social'),
        'nome_fantasia': data.get('nome_fantasia'),
        'porte': data.get('porte'),                   # ME, EPP, DEMAIS
        'cnae_code': data.get('cnae_fiscal'),
        'cnae_desc': data.get('cnae_fiscal_descricao'),
        'natureza': data.get('descricao_natureza_juridica'),
        'data_abertura': data.get('data_inicio_atividade'),
        'situacao': data.get('descricao_situacao_cadastral'),
        'telefone': data.get('telefone'),
        'email_receita': data.get('email'),            # Receita Federal email (often outdated)
        'municipio': data.get('municipio'),
        'uf': data.get('uf'),
        'cep': data.get('cep'),
        'socios_count': len(data.get('qsa', [])),
    }
```

### Secondary: ReceitaWS (FREE, limited)

**URL:** `https://www.receitaws.com.br/v1/cnpj/{cnpj}`
**Rate limit:** 3 requests/minute (free). Premium removes limit.
**Fields:** Similar to BrasilAPI. Good as fallback.

```python
def enrich_cnpj_receitaws(cnpj: str) -> dict | None:
    cnpj_clean = ''.join(filter(str.isdigit, cnpj))
    url = f"https://www.receitaws.com.br/v1/cnpj/{cnpj_clean}"
    try:
        resp = requests.get(url, timeout=15,
                           headers={'User-Agent': 'extrator-dados/1.0'})
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') != 'ERROR':
                return data
        return None
    except Exception:
        return None
    finally:
        time.sleep(20)  # mandatory: 3 req/min = 1 per 20s
```

### Tertiary: CNPJ.ws (FREE, 3 req/min)

**URL:** `https://publica.cnpj.ws/cnpj/{cnpj}`
**Rate limit:** 3 queries/minute per IP, no auth required.
**Fields:** Complete company registration data including branches, partners, Simples Nacional, state registrations, SUFRAMA.

```python
def enrich_cnpj_ws(cnpj: str) -> dict | None:
    cnpj_clean = ''.join(filter(str.isdigit, cnpj))
    url = f"https://publica.cnpj.ws/cnpj/{cnpj_clean}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None
```

### Cascading Enrichment (Recommended Pattern)

```python
def enrich_with_fallback(cnpj: str) -> dict | None:
    """Try BrasilAPI → ReceitaWS → CNPJ.ws in order."""
    result = enrich_cnpj_brasilapi(cnpj)
    if result:
        return result

    time.sleep(1)
    result = enrich_cnpj_receitaws(cnpj)
    if result:
        return result

    time.sleep(1)
    return enrich_cnpj_ws(cnpj)
```

### What BrasilAPI/ReceitaWS Does NOT Provide

| Data Point | Available? | Alternative |
|------------|-----------|-------------|
| Employee count | No (only porte: ME/EPP) | LinkedIn scraping |
| Revenue estimate | No | None free |
| Social media profiles | No | Manual / Google |
| Technology stack | No | BuiltWith API (paid) |
| Recent news | No | Google News API |
| Credit score | No | Serasa/Boa Vista (paid) |

**Note:** `porte` (company size class) from Receita Federal maps roughly to:
- `ME` = Microempresa (≤R$360k/year revenue)
- `EPP` = Empresa de Pequeno Porte (R$360k–R$4.8M/year)
- `DEMAIS` = Larger companies

This is useful as a free proxy for company size in the absence of employee counts.

---

## Summary Recommendations

### Immediate Wins (Low Effort, High Value)

1. **Replace regex email check with `email-validator` + DNS MX** — catches ~30% more invalid emails at zero cost. Add `disposable-email-domains` check in the same pass.

2. **Normalize phones with `phonenumbers`** — standardize to E.164, auto-detect mobile vs landline, auto-generate WhatsApp IDs. One `pip install phonenumbers` and the existing sanitize endpoint gains phone type detection.

3. **Add `freshness_score` column** — computed from `captured_at`. No external API needed. Display in leads table so users understand lead age.

4. **Enrich `porte` field from BrasilAPI** — already calling BrasilAPI for CNPJ data. Add `porte`, `cnae_fiscal_descricao`, `data_inicio_atividade` to the data extracted. Zero additional cost.

### Medium Effort

5. **Rework quality_score formula** — replace current basic scoring with the 6-dimension model above. Store breakdown as JSONB column. Surface grade (A/B/C/D/F) in the leads UI.

6. **Add `email_type` column** (`corporate`/`freemail`/`disposable`) — computed locally, no API. Huge value for B2B filtering: clients can filter to corporate-only leads.

7. **ZeroBounce integration (100 free/month)** — add a "Verify Email" button on individual lead view that burns a ZeroBounce credit. Store result in lead record (`email_verified_at`, `email_status`).

### Deferred (Paid Tier Features)

8. **Bulk email validation** — only economical at paid API prices. Position as a premium feature. ZeroBounce at $0.008/email = $8 per 1,000 leads.

9. **SMTP probing at scale** — not viable on Hostinger VPS (port 25 likely blocked, IP reputation risk). Skip.

---

## Packages to Add to requirements.txt

```
# Email validation (free, no API)
email-validator>=2.1.0
dnspython>=2.6.0
disposable-email-domains>=0.0.100

# Phone normalization (free, no API)
phonenumbers>=8.13.0
```

---

## Confidence Assessment

| Topic | Confidence | Basis |
|-------|------------|-------|
| Email-validator library | HIGH | PyPI official, well-maintained |
| dnspython MX check | HIGH | Standard library, well-documented |
| disposable-email-domains package | HIGH | Actively maintained GitHub repo |
| phonenumbers library | HIGH | Google libphonenumber port, official |
| BrasilAPI CNPJ fields | HIGH | Official open API, verified fields |
| ReceitaWS rate limits (3 req/min) | MEDIUM | Community-documented, verify |
| CNPJ.ws rate limits (3 req/min) | MEDIUM | Docs say 3/min, verify current |
| ZeroBounce free (100/month) | MEDIUM | Website states this, may change |
| Mailboxlayer free (250/month) | LOW | One source; verify at signup |
| DeBounce free (100 credits) | MEDIUM | Multiple sources confirm |
| Lead decay rate (30%/year) | MEDIUM | Industry estimate, varies by sector |
| B2B freshness thresholds (60/180/365 days) | MEDIUM | Standard CRM practice |

---

## Sources

- [email-validator — PyPI](https://pypi.org/project/email-validator/)
- [dns-smtp-email-validator — PyPI](https://pypi.org/project/dns-smtp-email-validator/)
- [py3-validate-email — PyPI](https://pypi.org/project/py3-validate-email/1.0.4/)
- [disposable-email-domains — GitHub](https://github.com/disposable-email-domains/disposable-email-domains)
- [disposable-email-domains — PyPI](https://pypi.org/project/disposable-email-domains/)
- [phonenumbers — PyPI](https://pypi.org/project/phonenumbers/)
- [Telephone numbers in Brazil — Wikipedia](https://en.wikipedia.org/wiki/Telephone_numbers_in_Brazil)
- [Brazil Phone Number Format Guide 2025 — VitelGlobal](https://www.vitelglobal.com/blog/brazil-phone-number-format/)
- [ZeroBounce Email Validation API](https://www.zerobounce.net/docs/email-validation-api-quickstart/v2-validate-emails)
- [Abstract API Email Verification — Free Tier](https://www.abstractapi.com/api/email-verification-validation-api)
- [Mailboxlayer API](https://mailboxlayer.com/)
- [DeBounce API](https://debounce.com/solutions/api/)
- [BrasilAPI CNPJ Documentation](https://brasilapi.com.br/docs#tag/CNPJ)
- [ReceitaWS API](https://receitaws.com.br/api)
- [CNPJá API — Free Public Endpoint](https://cnpja.com/en/api/open)
- [CNPJ.ws — Public API Documentation](https://docs.cnpj.ws/en/api-reference/api-publica)
- [B2B Lead Scoring Best Practices 2025 — Martal](https://martal.ca/b2b-lead-scoring-lb/)
- [Data Freshness Best Practices — Elementary Data](https://www.elementary-data.com/post/data-freshness-best-practices-and-key-metrics-to-measure-success)
- [12 Best Free Email Validation Tools 2025 — TrueList](https://truelist.co/blog/free-email-validation)
- [How to Normalize Phone Numbers for WhatsApp — Wassenger](https://wassenger.com/blog/en/how-to-normalize-international-phone-numbers-for-whatsapp)
