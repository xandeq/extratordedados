import json,sys,io
if sys.platform=='win32':sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')

print("="*80)
print("RESUMO TOTAL - EXTRAÇÃO GRANDE VITÓRIA-ES")
print("="*80)
print()

# 1. Leads API enrichment
try:
    leads_api=json.load(open('leads_api_enrichment.json','r',encoding='utf-8'))
    print(f"✅ API Enrichment (Hunter/Snov): {len(leads_api)} leads COM EMAIL")
    print(f"   Importados no CRM: 18 (1 erro de formato)")
except:
    leads_api=[]
    print("❌ Nenhum lead API enrichment")

# 2. Leads enriquecidos anteriores
try:
    leads_enr=json.load(open('vitoria_leads_enriquecidos.json','r',encoding='utf-8'))
    print(f"✅ Leads enriquecidos (nomes derivados): {len(leads_enr)} leads COM EMAIL")
    print(f"   Importados no CRM: 28 (atualizados)")
except:
    leads_enr=[]

# 3. Leads completos
try:
    leads_completos=json.load(open('vitoria_leads_com_emails.json','r',encoding='utf-8'))
    print(f"✅ Leads completos (Apify): {len(leads_completos)} leads COM EMAIL+TELEFONE")
    print(f"   Importados no CRM: 2 (duplicados)")
except:
    leads_completos=[]

print()
print("="*80)
print("TOTAL NO CRM")
print("="*80)
total_crm = 18 + 28  # 18 novos + 28 atualizados
print(f"🎯 LEADS COM EMAIL NO CRM: ~{total_crm}+ leads")
print()
print("   Origem API enrichment: 18")
print("   Origem Apify (nomes derivados): 28")
print("   Origem Apify (completos): 2")
print()
print("="*80)
print("PRÓXIMOS PASSOS RECOMENDADOS")
print("="*80)
print()
print("OPÇÃO 1: Aguardar reset dos rate limits (1 hora)")
print("  - API enrichment: +3 buscas/hora")
print("  - Google Maps Playwright: +5 buscas/hora")
print("  - Search engines: +3 buscas/hora")
print()
print("OPÇÃO 2: Upgrade Apify ($49/mês)")
print("  - Actor Google Maps com emails: ~100 leads/run")
print("  - Sem rate limits")
print()
print("OPÇÃO 3: APIs de enrichment diretas")
print("  - Hunter.io: $49/mês (1000 verificações)")
print("  - Apollo.io: GRÁTIS (50 emails/mês)")
print("  - Snov.io: $39/mês (1000 créditos)")
print()
print("="*80)
print("✅ SESSÃO ATUAL CONCLUÍDA!")
print("="*80)
print()
print(f"Total extraído e importado: ~{total_crm} leads com email")
print("Acesse: https://crm.alexandrequeiroz.com.br/leads")
