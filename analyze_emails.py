import os
import requests
import json
import re

# Login
resp = requests.post('https://api.extratordedados.com.br/api/login', json={
    'username': 'admin',
    'password': os.environ.get('ADMIN_PASSWORD', '')
})
token = resp.json()['token']

# Buscar TODOS os leads em múltiplas páginas
headers = {'Authorization': f'Bearer {token}'}
all_leads = []
page = 1
while True:
    leads_resp = requests.get(f'https://api.extratordedados.com.br/api/leads?limit=50&page={page}', headers=headers)
    leads_data = leads_resp.json()
    batch_leads = leads_data.get('leads', [])
    if not batch_leads:
        break
    all_leads.extend(batch_leads)
    if len(all_leads) >= leads_data.get('total', 0):
        break
    page += 1

leads_data = {'leads': all_leads, 'total': len(all_leads)}

print('=' * 120)
print(f'TOTAL DE LEADS RETORNADOS: {len(leads_data.get("leads", []))}')
print(f'TOTAL GERAL NO BANCO: {leads_data.get("total", 0)}')
print('=' * 120)
print()

# Analisar emails
validos = []
invalidos = []
problemas = {}

invalid_patterns = {
    'exemplo/teste': r'@(example|test|domain|email|company|yourdomain|yourcompany|site|website)\.',
    'noreply': r'(noreply|no-reply)@',
    'localhost/placeholders': r'@(localhost|sentry|wixpress|placeholder|dummy)',
    'imagens': r'(image|img|photo|foto)@',
    'extensoes arquivo': r'@(svg|png|jpg|gif)\.|\.( jpg|png|svg|gif|webp)$',
    'numeros invalidos': r'^[0-9]+@|@[0-9]+\.',
    'javascript': r'javascript:|mailto:$',
    'plataformas': r'@(wix\.com|hostinger|vercel)',
    'genericos': r'(support|sales|info|contact)@(example|test|domain)',
    'diretorios/agregadores': r'@(doctoralia|zhihu|listamais|forum-pet|hospitales-privados|nesx\.co|quironsalud)\.',
    'emails internacionais': r'\.(es|de|fr|it|uk|cn)$',
    'emails duplicados mesmo dominio': r'@doctoralia\.',  # Múltiplos emails do mesmo agregador
}

for lead in leads_data.get('leads', []):
    email = lead.get('email')
    if not email:
        continue

    email_lower = email.lower()
    is_invalid = False

    # Checar padrões inválidos
    for problema_tipo, pattern in invalid_patterns.items():
        if re.search(pattern, email_lower):
            invalidos.append(lead)
            is_invalid = True
            if problema_tipo not in problemas:
                problemas[problema_tipo] = []
            problemas[problema_tipo].append(email)
            break

    if not is_invalid:
        # Validação básica
        if '@' in email and len(email.split('@')) == 2:
            domain = email.split('@')[1]
            if '.' in domain and len(domain) > 3:
                validos.append(lead)
            else:
                invalidos.append(lead)
                if 'dominio invalido' not in problemas:
                    problemas['dominio invalido'] = []
                problemas['dominio invalido'].append(email)
        else:
            invalidos.append(lead)
            if 'formato invalido' not in problemas:
                problemas['formato invalido'] = []
            problemas['formato invalido'].append(email)

total_leads = len(leads_data.get('leads', []))
if total_leads > 0:
    print(f'[OK] EMAILS VALIDOS: {len(validos)} ({len(validos)*100//total_leads}%)')
    print(f'[!!] EMAILS INVALIDOS: {len(invalidos)} ({len(invalidos)*100//total_leads}%)')
else:
    print('Nenhum lead encontrado')
print()

print('=' * 120)
print('TIPOS DE PROBLEMAS ENCONTRADOS:')
print('=' * 120)
for problema, emails in sorted(problemas.items(), key=lambda x: len(x[1]), reverse=True):
    print(f'{problema:30} : {len(emails):3} emails')
    for email in emails[:3]:
        print(f'    - {email}')
print()

print('=' * 120)
print('EMAILS INVALIDOS (Primeiros 30):')
print('=' * 120)
for i, lead in enumerate(invalidos[:30], 1):
    email = lead['email']
    company = (lead.get('company_name', 'N/A') or 'N/A')[:35]
    source = (lead.get('source_url', 'N/A') or 'N/A')[:70]
    print(f'{i:2}. ID {lead["id"]:4} | {email:45} | {company:35} | {source}')

print()
print('=' * 120)
print('EMAILS VALIDOS (Primeiros 30):')
print('=' * 120)
for i, lead in enumerate(validos[:30], 1):
    email = lead['email']
    company = (lead.get('company_name', 'N/A') or 'N/A')[:35]
    phone = (lead.get('phone', 'N/A') or 'N/A')[:20]
    city = lead.get('city', 'N/A') or 'N/A'
    print(f'{i:2}. {email:45} | {company:35} | {phone:20} | {city}')
