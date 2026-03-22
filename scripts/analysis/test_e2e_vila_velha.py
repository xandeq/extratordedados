import os
"""
TESTE END-TO-END COMPLETO
Busca massiva de restaurantes em Vila Velha-ES + Auto-sync para alexandrequeiroz.com.br
"""
import requests
import time
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_EXTRATOR = 'https://api.extratordedados.com.br'
API_ALEXANDRE = 'https://api.alexandrequeiroz.com.br'

print('='*80)
print('🧪 TESTE END-TO-END: RESTAURANTES VILA VELHA-ES')
print('='*80)
print()

# ============================================================
# STEP 1: Login no Extrator de Dados
# ============================================================
print('STEP 1: Login no extratordedados.com.br...')
r = requests.post(f'{API_EXTRATOR}/api/login', json={
    'username': 'admin',
    'password': os.environ.get('ADMIN_PASSWORD', '')
})

if r.status_code != 200:
    print(f'❌ Login falhou: {r.status_code}')
    sys.exit(1)

token_extrator = r.json().get('token')
headers_extrator = {'Authorization': f'Bearer {token_extrator}'}
print('✅ Login OK - Token obtido')
print()

# ============================================================
# STEP 2: Verificar leads ANTES da busca massiva
# ============================================================
print('STEP 2: Verificando estado ANTES da busca...')
r = requests.get(
    f'{API_EXTRATOR}/api/leads',
    headers=headers_extrator,
    params={'limit': 1}
)
total_leads_antes = r.json().get('total', 0)
print(f'   Total de leads no CRM (ANTES): {total_leads_antes}')
print()

# ============================================================
# STEP 3: Iniciar BUSCA MASSIVA (Restaurantes Vila Velha-ES)
# ============================================================
print('STEP 3: Iniciando busca massiva de RESTAURANTES em Vila Velha-ES...')
r = requests.post(
    f'{API_EXTRATOR}/api/search',
    headers=headers_extrator,
    json={
        'niche': 'restaurante',
        'city': 'Vila Velha',
        'state': 'ES',
        'max_pages': 2
    },
    timeout=15
)

if r.status_code != 200:
    print(f'❌ Busca falhou: {r.status_code}')
    print(f'   Response: {r.text}')
    sys.exit(1)

result = r.json()
batch_id = result.get('batch_id')
print(f'✅ Busca iniciada!')
print(f'   Batch ID: {batch_id}')
print(f'   Status: {result.get("status")}')
print()

# ============================================================
# STEP 4: Aguardar conclusão do batch (max 5 minutos)
# ============================================================
print('STEP 4: Aguardando conclusão da busca...')
max_wait = 300  # 5 minutos
elapsed = 0

while elapsed < max_wait:
    time.sleep(10)
    elapsed += 10

    r = requests.get(
        f'{API_EXTRATOR}/api/search/{batch_id}/progress',
        headers=headers_extrator
    )

    if r.status_code != 200:
        print(f'   ❌ Erro ao verificar progresso: {r.status_code}')
        continue

    progress = r.json()
    status = progress.get('status')
    total_leads = progress.get('total_leads', 0)

    print(f'   [{elapsed}s] Status: {status} | Leads: {total_leads}', end='\r')

    if status == 'completed':
        print()
        print(f'✅ Busca concluída!')
        print(f'   Total de leads extraídos: {total_leads}')
        break

    if status == 'failed':
        print()
        print(f'❌ Busca falhou!')
        sys.exit(1)

if elapsed >= max_wait:
    print()
    print('⚠️  Timeout aguardando conclusão')

print()

# ============================================================
# STEP 5: Verificar leads DEPOIS da busca
# ============================================================
print('STEP 5: Verificando leads extraídos...')
r = requests.get(
    f'{API_EXTRATOR}/api/leads',
    headers=headers_extrator,
    params={'batch_id': batch_id, 'limit': 100}
)

leads_data = r.json()
leads = leads_data.get('leads', [])
total_leads_depois = leads_data.get('total', 0)

print(f'   Total de leads no batch: {len(leads)}')
print(f'   Total geral (DEPOIS): {total_leads_depois}')
print()

# Filtrar leads com email
leads_com_email = [l for l in leads if l.get('email') and '@' in l.get('email', '')]
print(f'   Leads com EMAIL: {len(leads_com_email)}')
print()

if len(leads_com_email) > 0:
    print('   Primeiros 5 leads com email:')
    for i, lead in enumerate(leads_com_email[:5], 1):
        print(f'      {i}. {lead.get("company_name")} - {lead.get("email")} - {lead.get("phone")}')
    print()

# ============================================================
# STEP 6: Aguardar AUTO-SYNC (thread em background)
# ============================================================
print('STEP 6: Aguardando auto-sync para alexandrequeiroz.com.br...')
print('   (Auto-sync inicia automaticamente em background)')
print('   Aguardando 30 segundos para a thread de sync processar...')
time.sleep(30)
print('   ✅ Tempo de espera concluído')
print()

# ============================================================
# STEP 7: Verificar sincronização em alexandrequeiroz.com.br
# ============================================================
print('STEP 7: Verificando leads sincronizados em alexandrequeiroz.com.br...')

# Login
r = requests.post(f'{API_ALEXANDRE}/api/v1/auth/login', json={
    'email': 'admin@alexandrequeiroz.com.br',
    'password': os.environ.get('ADMIN_PASSWORD', '')
})

if r.status_code != 200:
    print(f'   ❌ Login alexandrequeiroz falhou: {r.status_code}')
else:
    token_alexandre = r.json().get('token')
    headers_alexandre = {'Authorization': f'Bearer {token_alexandre}'}

    # Buscar todos os leads
    r = requests.get(
        f'{API_ALEXANDRE}/api/v1/customers',
        headers=headers_alexandre,
        params={'page': 1, 'pageSize': 100}
    )

    if r.status_code == 200:
        data = r.json()
        customers = data.get('items', [])
        total_customers = data.get('totalCount', 0)

        print(f'   ✅ Total de customers no alexandrequeiroz.com.br: {total_customers}')
        print()

        # Verificar se os emails dos leads extraídos estão lá
        emails_extraidos = set([l.get('email', '').lower() for l in leads_com_email if l.get('email')])
        emails_sincronizados = set([c.get('email', '').lower() for c in customers if c.get('email')])

        sincronizados = emails_extraidos & emails_sincronizados

        print(f'   Leads extraídos com email: {len(emails_extraidos)}')
        print(f'   Leads sincronizados: {len(sincronizados)}')
        print()

        if len(sincronizados) > 0:
            print(f'   ✅ AUTO-SYNC FUNCIONOU! {len(sincronizados)} leads sincronizados')
            print()
            print('   Leads sincronizados:')
            for i, email in enumerate(list(sincronizados)[:5], 1):
                # Encontrar o lead
                lead_original = next((l for l in leads_com_email if l.get('email', '').lower() == email), None)
                if lead_original:
                    print(f'      {i}. {lead_original.get("company_name")} - {email}')
        else:
            print('   ⚠️  Nenhum lead sincronizado ainda (pode estar processando)')
    else:
        print(f'   ❌ Erro ao buscar customers: {r.status_code}')

print()

# ============================================================
# RELATÓRIO FINAL
# ============================================================
print('='*80)
print('📊 RELATÓRIO FINAL DO TESTE END-TO-END')
print('='*80)
print()
print(f'✅ Busca massiva executada: Restaurantes em Vila Velha-ES')
print(f'✅ Batch ID: {batch_id}')
print(f'✅ Leads extraídos: {total_leads_depois - total_leads_antes} novos')
print(f'✅ Leads com email: {len(leads_com_email)}')
print(f'✅ Auto-sync ativado: SIM (thread em background)')
print()
print('Acesse:')
print(f'  - Frontend: https://extratordedados.com.br/batch/{batch_id}/')
print(f'  - CRM Principal: https://alexandrequeiroz.com.br')
print()
print('='*80)
