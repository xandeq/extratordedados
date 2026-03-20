"""
Inline test for normalization functions (no Flask import needed)
"""
import re
import sys

# ---- Inline copies of constants ----

CORPORATE_SUFFIXES = [
    ' LTDA', ' S/A', ' SA', ' EIRELI', ' ME', ' EPP', ' MEI',
    ' LIMITADA', ' SERVICOS', ' SERVICE', ' SOLUTIONS', ' CONSULTORIA',
    ' ASSESSORIA', ' EMPREENDIMENTOS', ' PARTICIPACOES',
]

GENERIC_EMAIL_PROVIDERS = {
    'gmail.com', 'googlemail.com', 'outlook.com', 'outlook.com.br',
    'hotmail.com', 'hotmail.com.br', 'yahoo.com', 'yahoo.com.br',
    'live.com', 'msn.com', 'aol.com', 'icloud.com', 'me.com',
    'protonmail.com', 'proton.me', 'zoho.com', 'mail.com', 'gmx.com',
    'uol.com.br', 'bol.com.br', 'terra.com.br', 'ig.com.br',
    'r7.com', 'globo.com', 'globomail.com', 'zipmail.com.br',
    'oi.com.br', 'veloxmail.com.br',
}

EMAIL_LOW_QUALITY_PATTERNS = [
    r'^(webmaster|postmaster|hostmaster|abuse|spam)@',
    r'^(root|admin|administrator|system|daemon)@',
    r'^(info|contact|contato|atendimento|suporte|support|sales|vendas)@',
    r'^(newsletter|news|noticias|updates|marketing)@',
    r'^(financeiro|rh|recursos-humanos|fiscal|comercial|recepcao|portaria)@',
    r'^(contabilidade|vendas|sac|ouvidoria|diretoria|gestao)@',
]

# ---- Inline copies of functions ----

def derive_company_name(email):
    if not email or '@' not in email:
        return ''
    _, domain = email.lower().split('@', 1)
    if not domain or domain in GENERIC_EMAIL_PROVIDERS:
        return ''
    name = domain.split('.')[0]
    name = re.sub(r'\d+$', '', name)
    name = re.sub(r'[._\-]+', ' ', name)
    name = name.upper()
    for suffix in CORPORATE_SUFFIXES:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
            break
    name = re.sub(r'\s+', ' ', name).strip()
    if not name or len(name) < 2:
        return ''
    return ' '.join(w.capitalize() for w in name.split())


def derive_contact_name(email):
    if not email or '@' not in email:
        return ''
    local_part, _ = email.lower().split('@', 1)
    for pattern in EMAIL_LOW_QUALITY_PATTERNS:
        if re.search(pattern, local_part + '@'):
            return ''
    name = re.sub(r'\d+$', '', local_part)
    name = re.sub(r'[._\-]+', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if not name or len(name) < 3:
        return ''
    words = name.split()
    if len(words) == 1 and len(words[0]) < 4:
        return ''
    return ' '.join(w.capitalize() for w in words)


# =====================
# TEST CASES
# =====================

tests = [
    # (email, must_contain_in_company, must_contain_in_contact)
    ('contato@acme.com.br',             'Acme',       ''),
    ('joao.silva@gmail.com',            '',            'Joao Silva'),
    ('fernando.oliveira@outlook.com',   '',            'Fernando Oliveira'),
    ('financeiro@empresa.com.br',       'Empresa',     ''),       # low-quality email -> no contact name
    ('rh@bigcorp.com.br',              'Bigcorp',     ''),
    ('info@techsolutions.com.br',       'Techsolutions',''),
    ('maria.santos@imoveis-vitoria.com.br', 'Imoveis Vitoria', 'Maria Santos'),
    ('publicidade@exame.com.br',        'Exame',       ''),
    ('ana.lima@empresa.com.br',         'Empresa',     'Ana Lima'),
]

print('=' * 60)
print('NORMALIZATION FUNCTION TESTS')
print('=' * 60)

all_passed = True
for email, exp_company, exp_contact in tests:
    got_company = derive_company_name(email)
    got_contact = derive_contact_name(email)

    company_ok = (not exp_company) or (exp_company.lower() in got_company.lower())
    contact_ok = (not exp_contact) or (exp_contact.lower() in got_contact.lower())

    status = '[PASS]' if (company_ok and contact_ok) else '[FAIL]'
    if not (company_ok and contact_ok):
        all_passed = False

    print(f'\n{status}  {email}')
    print(f'   Company : got="{got_company}" (expected contains "{exp_company}")')
    print(f'   Contact : got="{got_contact}" (expected contains "{exp_contact}")')

print('\n' + '=' * 60)
print('ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED')
print('=' * 60)
sys.exit(0 if all_passed else 1)
