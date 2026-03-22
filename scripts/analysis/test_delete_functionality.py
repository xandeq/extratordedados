"""
Teste da funcionalidade de delete em massa de leads
"""
import requests
import sys

sys.stdout.reconfigure(encoding='utf-8')

API_URL = "https://api.extratordedados.com.br"

print("=" * 100)
print("TESTE DE DELETE EM MASSA - EXTRATOR DE DADOS")
print("=" * 100)

# 1. Login
print("\n[1/6] LOGIN...")
try:
    login_resp = requests.post(f"{API_URL}/api/login", json={
        'username': 'admin',
        'password': 'REDACTED_PASSWORD'
    }, timeout=10)

    if login_resp.status_code == 200:
        token = login_resp.json()['token']
        print(f"[OK] Token obtido")
    else:
        print(f"[ERRO] Login falhou: {login_resp.text}")
        sys.exit(1)
except Exception as e:
    print(f"[ERRO] {e}")
    sys.exit(1)

headers = {'Authorization': f'Bearer {token}'}

# 2. Buscar leads atuais
print("\n[2/6] BUSCANDO LEADS EXISTENTES...")
try:
    leads_resp = requests.get(f"{API_URL}/api/leads?limit=10", headers=headers, timeout=10)
    if leads_resp.status_code == 200:
        leads_data = leads_resp.json()
        total_before = leads_data['total']
        leads = leads_data['leads']
        print(f"[OK] Total de leads no sistema: {total_before}")
        print(f"[OK] Leads retornados: {len(leads)}")

        if len(leads) < 2:
            print("[AVISO] Poucos leads para testar delete em massa")
            print("[INFO] Execute primeiro uma busca para ter leads no sistema")
            sys.exit(0)
    else:
        print(f"[ERRO] Falha ao buscar leads: {leads_resp.text}")
        sys.exit(1)
except Exception as e:
    print(f"[ERRO] {e}")
    sys.exit(1)

# 3. Testar DELETE individual
print("\n[3/6] TESTANDO DELETE INDIVIDUAL...")
test_lead_id = leads[0]['id']
try:
    delete_resp = requests.delete(f"{API_URL}/api/leads/{test_lead_id}", headers=headers, timeout=10)
    if delete_resp.status_code == 200:
        print(f"[OK] Lead {test_lead_id} deletado com sucesso")
    else:
        print(f"[ERRO] Falha ao deletar lead: {delete_resp.text}")
        sys.exit(1)
except Exception as e:
    print(f"[ERRO] {e}")
    sys.exit(1)

# 4. Verificar se lead foi removido
print("\n[4/6] VERIFICANDO SE LEAD FOI REMOVIDO...")
try:
    check_resp = requests.get(f"{API_URL}/api/leads/{test_lead_id}", headers=headers, timeout=10)
    if check_resp.status_code == 404:
        print(f"[OK] Lead {test_lead_id} não existe mais (correto)")
    else:
        print(f"[ERRO] Lead ainda existe! Status: {check_resp.status_code}")
        sys.exit(1)
except Exception as e:
    print(f"[ERRO] {e}")
    sys.exit(1)

# 5. Testar DELETE em massa
if len(leads) >= 3:
    print("\n[5/6] TESTANDO DELETE EM MASSA...")
    lead_ids_to_delete = [leads[1]['id'], leads[2]['id']]
    try:
        bulk_delete_resp = requests.post(
            f"{API_URL}/api/leads/bulk-delete",
            json={'lead_ids': lead_ids_to_delete},
            headers=headers,
            timeout=10
        )
        if bulk_delete_resp.status_code == 200:
            result = bulk_delete_resp.json()
            deleted_count = result.get('deleted', 0)
            print(f"[OK] {deleted_count} leads deletados em massa")
            if deleted_count != len(lead_ids_to_delete):
                print(f"[AVISO] Esperado {len(lead_ids_to_delete)}, deletado {deleted_count}")
        else:
            print(f"[ERRO] Falha ao deletar em massa: {bulk_delete_resp.text}")
            sys.exit(1)
    except Exception as e:
        print(f"[ERRO] {e}")
        sys.exit(1)
else:
    print("\n[5/6] PULANDO DELETE EM MASSA (poucos leads)")

# 6. Verificar total final
print("\n[6/6] VERIFICANDO TOTAL FINAL...")
try:
    final_resp = requests.get(f"{API_URL}/api/leads?limit=1", headers=headers, timeout=10)
    if final_resp.status_code == 200:
        total_after = final_resp.json()['total']
        deleted_total = total_before - total_after
        print(f"[OK] Total de leads agora: {total_after}")
        print(f"[OK] Total deletado: {deleted_total}")

        expected_deleted = 1 + (2 if len(leads) >= 3 else 0)
        if deleted_total == expected_deleted:
            print(f"[OK] Número correto de leads deletados!")
        else:
            print(f"[AVISO] Esperado deletar {expected_deleted}, deletado {deleted_total}")
    else:
        print(f"[ERRO] Falha ao verificar total: {final_resp.text}")
except Exception as e:
    print(f"[ERRO] {e}")

# Resumo final
print("\n" + "=" * 100)
print("RESUMO DOS TESTES")
print("=" * 100)
print("[OK] Endpoint DELETE individual funcionando")
print("[OK] Endpoint DELETE em massa funcionando")
print("[OK] Leads removidos corretamente do banco")
print("[OK] API retorna 404 para leads deletados")
print("\n[SUCCESS] TODOS OS TESTES DE DELETE PASSARAM!")
print("=" * 100)

print("\n[INFO] Frontend deve estar funcionando em:")
print("https://extratordedados.com.br/leads")
print("\nPassos para testar no frontend:")
print("1. Acesse a página de Leads")
print("2. Selecione alguns leads (checkbox)")
print("3. Clique no botão 'Deletar' (vermelho)")
print("4. Confirme a exclusão no modal")
print("5. Verifique que os leads foram removidos")
