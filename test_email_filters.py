"""
Script de teste para validar os novos filtros de email
"""
import re

# Copia dos filtros do backend
EMAIL_AGGREGATOR_DOMAINS = {
    'doctoralia.com.br', 'doctoralia.es', 'doctoralia.com',
    'zhihu.com', 'stackoverflow.com', 'quora.com',
    'listamais.com.br', 'guiafacil.com', 'encontrasp.com.br',
    'forum-pet.de', 'forum-pet.com',
    'hospitales-privados.es', 'quironsalud.es', 'quironsalud.com',
    'sentry.io', 'wixpress.com', 'wix.com',
    'hostinger.com', 'vercel.com', 'netlify.com',
    'nesx.co', 'weebly.com', 'squarespace.com',
    'sjd.es', 'vithas.es', 'sanitas.es',
}

EMAIL_INVALID_PATTERNS = [
    r'@(example|test|domain|email|company|yourdomain|yourcompany|site|website)\.',
    r'(noreply|no-reply|donotreply)@',
    r'@(localhost|127\.0\.0\.1)',
    r'@(placeholder|dummy|fake|sample)\.',
    r'^(image|img|photo|foto|icon|banner|logo)@',
    r'@(svg|png|jpg|jpeg|gif|webp|ico)\.',
    r'\.(jpg|jpeg|png|svg|gif|webp|ico|pdf|doc|zip)$',
    r'^[0-9]+@',
    r'@[0-9]+\.',
    r'javascript:|mailto:$|void\(0\)',
]

EMAIL_LOW_QUALITY_PATTERNS = [
    r'^(webmaster|postmaster|hostmaster|abuse|spam)@',
    r'^(root|admin|administrator|system|daemon)@',
    r'^(info|contact|contato|atendimento|suporte|support|sales|vendas)@',
    r'^(newsletter|news|noticias|updates|marketing)@',
]

EMAIL_FOREIGN_TLDS = {
    '.es', '.de', '.fr', '.it', '.uk', '.cn', '.jp', '.kr', '.ru', '.pt',
}

INVALID_EMAIL_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp',
    '.css', '.js', '.woff', '.woff2', '.ttf', '.eot',
}

def calculate_email_quality_score(email_str):
    """Calculate quality score for email (0-100)."""
    email_lower = email_str.lower().strip()

    if '@' not in email_lower or '.' not in email_lower.split('@')[-1]:
        return 0, False, 'formato_invalido'

    if len(email_lower) > 320:
        return 0, False, 'email_muito_longo'

    try:
        local_part, domain = email_lower.split('@')
    except ValueError:
        return 0, False, 'formato_invalido'

    # Check 1: Agregadores
    for aggregator_domain in EMAIL_AGGREGATOR_DOMAINS:
        if aggregator_domain in domain:
            return 0, False, f'agregador:{aggregator_domain}'

    # Check 2: Padrões inválidos
    for pattern in EMAIL_INVALID_PATTERNS:
        if re.search(pattern, email_lower):
            return 0, False, f'padrao_invalido:{pattern[:30]}'

    # Check 3: TLDs estrangeiros
    for foreign_tld in EMAIL_FOREIGN_TLDS:
        if email_lower.endswith(foreign_tld):
            return 0, False, f'tld_estrangeiro:{foreign_tld}'

    # Check 4: Extensões de arquivo
    for ext in INVALID_EMAIL_EXTENSIONS:
        if email_lower.endswith(ext):
            return 0, False, f'extensao_arquivo:{ext}'

    # Calcular score
    score = 100

    # Penalização: Emails genéricos
    for pattern in EMAIL_LOW_QUALITY_PATTERNS:
        if re.search(pattern, email_lower):
            score -= 30
            break

    # Penalização: Email gratuito
    free_email_domains = ['gmail.com', 'hotmail.com', 'yahoo.com', 'outlook.com',
                          'bol.com.br', 'ig.com.br', 'uol.com.br', 'terra.com.br']
    if any(free_domain in domain for free_domain in free_email_domains):
        score -= 20

    # Bônus: Nome real
    if '.' in local_part and len(local_part) > 5:
        score += 10

    # Bônus: Domínio corporativo BR
    if domain.endswith('.com.br') or domain.endswith('.med.br'):
        score += 10

    score = max(0, min(100, score))
    return score, True, None

# Emails de teste (dos dados reais extraídos)
test_emails = [
    # INVÁLIDOS - Agregadores
    ('atendimento@listamais.com.br', 'agregador'),
    ('info@forum-pet.de', 'agregador'),
    ('juliana@doctoralia.com.br', 'agregador'),
    ('agency@zhihu.com', 'agregador'),

    # INVÁLIDOS - Internacionais
    ('hstaclotilde@sjd.es', 'internacional'),
    ('cortesj@vithas.es', 'internacional'),
    ('miyel.gomez@doctoralia.es', 'agregador+internacional'),

    # VÁLIDOS - Alta qualidade
    ('leonardo.amaral@bioscan.med.br', 'alto'),
    ('evoluir.recrutamento2016@gmail.com', 'medio'),
    ('contato@centromedicocg.com.br', 'medio'),

    # VÁLIDOS - Baixa qualidade
    ('contato@clinicavitoria.com', 'baixo'),
    ('info@klinik.eus', 'baixo'),
    ('contact@nesx.co', 'baixo (agregador)'),
]

print('=' * 100)
print('TESTE DE FILTROS DE EMAIL')
print('=' * 100)
print()

approved = []
rejected = []

for email, expected_category in test_emails:
    score, is_valid, rejection_reason = calculate_email_quality_score(email)

    if is_valid and score >= 40:
        approved.append((email, score, expected_category))
        status = f'[APROVADO] Score: {score:3}'
        if score >= 70:
            quality = 'PREMIUM'
        elif score >= 50:
            quality = 'MEDIO'
        else:
            quality = 'BASICO'
        print(f'{status} | {quality:7} | {email:50} (esperado: {expected_category})')
    else:
        rejected.append((email, rejection_reason, expected_category))
        print(f'[REJEITADO] {rejection_reason:30} | {email:50} (esperado: {expected_category})')

print()
print('=' * 100)
print(f'RESUMO: {len(approved)} aprovados, {len(rejected)} rejeitados de {len(test_emails)} testados')
print('=' * 100)

# Verificar eficácia
print()
print('VERIFICAÇÃO DE EFICÁCIA:')
print('-' * 100)

errors = []

# Agregadores devem ser rejeitados
for email, reason, expected in rejected:
    if 'agregador' in expected and 'agregador' not in reason and 'tld_estrangeiro' not in reason:
        errors.append(f'ERRO: {email} deveria ser bloqueado como agregador')

# Internacionais devem ser rejeitados
for email, reason, expected in rejected:
    if 'internacional' in expected and 'tld_estrangeiro' not in reason and 'agregador' not in reason:
        errors.append(f'ERRO: {email} deveria ser bloqueado como internacional')

# Emails válidos de alta qualidade devem passar
for email, score, expected in approved:
    if expected == 'alto' and score < 70:
        errors.append(f'ALERTA: {email} esperado alto mas score {score}')

if errors:
    for error in errors:
        print(f'[!!] {error}')
else:
    print('[OK] Todos os filtros funcionando conforme esperado!')

print()
print('ANÁLISE DE IMPACTO:')
print(f'- Taxa de rejeição: {len(rejected)*100//len(test_emails)}%')
print(f'- Emails aprovados: {len(approved)}')
print(f'- Agregadores bloqueados: {sum(1 for e, r, _ in rejected if "agregador" in r)}')
print(f'- Internacionais bloqueados: {sum(1 for e, r, _ in rejected if "tld_estrangeiro" in r)}')
