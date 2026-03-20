import requests, json, sys, io
if sys.platform=='win32': sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')

API="https://api.alexandrequeiroz.com.br"
r=requests.post(f"{API}/api/v1/customers/import",json={"customers":[{"name":l.get('company_name'),"email":l.get('email'),"phone":l.get('phone'),"whatsApp":l.get('phone'),"companyName":l.get('company_name'),"website":l.get('website'),"notes":"","tags":"api-enrichment,grande-vitoria-es"}for l in json.load(open('leads_api_enrichment.json','r',encoding='utf-8'))],"source":11})
print(f"Status:{r.status_code}")
print(json.dumps(r.json(),indent=2,ensure_ascii=False)[:1000])
