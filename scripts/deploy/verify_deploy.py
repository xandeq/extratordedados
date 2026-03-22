#!/usr/bin/env python3
import requests
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print('='*80)
print('VERIFICACAO POS-DEPLOY')
print('='*80)
print()

# Test backend health
print('Testando backend...')
try:
    r = requests.get('https://api.extratordedados.com.br/api/health', timeout=10)
    if r.status_code == 200:
        print(f'✅ Backend OK: {r.json()}')
    else:
        print(f'❌ Backend erro: {r.status_code}')
except Exception as e:
    print(f'❌ Backend erro: {e}')

print()

# Test frontend
print('Testando frontend /massive-search...')
try:
    r = requests.get('https://extratordedados.com.br/massive-search', timeout=10)
    if r.status_code == 200:
        print('✅ Frontend /massive-search OK!')
        if 'Busca Massiva' in r.text:
            print('✅ Conteudo correto detectado!')
    elif r.status_code == 404:
        print('❌ Frontend 404 - verificar .htaccess')
    else:
        print(f'❌ Frontend erro: {r.status_code}')
except Exception as e:
    print(f'❌ Frontend erro: {e}')

print()
print('='*80)
print('DEPLOY COMPLETO!')
print('='*80)
print()
print('Frontend: https://extratordedados.com.br/massive-search')
print('Backend: https://api.extratordedados.com.br')
print('GitHub: https://github.com/xandeq/extratordedados')
print()
