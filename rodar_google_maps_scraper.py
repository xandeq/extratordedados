import requests,json,sys,io,time
if sys.platform=='win32':sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')

API="https://api.extratordedados.com.br"
r=requests.post(f"{API}/api/login",json={"username":"admin","password":"1982Xandeq1982#"})
token=r.json().get('token')
h={"Authorization":f"Bearer {token}"}

queries=["clinica medica Vitoria ES","dentista Vila Velha ES","advocacia Serra ES","contabilidade Cariacica ES","consultoria Vitoria ES"]

print("Google Maps Playwright - Rate limit: 5/hour")
print(f"Queries: {len(queries)}\n")

jobs=[]
for q in queries:
    r=requests.post(f"{API}/api/scrape/google-maps",headers=h,json={"query":q,"maxPlaces":10})
    if r.status_code==200:
        j=r.json()
        jobs.append({'q':q,'job_id':j.get('job_id')})
        print(f"✅ {q}: job {j.get('job_id')}")
    else:
        print(f"❌ {q}: {r.status_code}")
    time.sleep(2)

print(f"\n{len(jobs)} jobs criados. Aguardando...")
time.sleep(60)

for job in jobs:
    r=requests.get(f"{API}/api/results/{job['job_id']}",headers=h)
    if r.status_code==200:
        d=r.json()
        print(f"{job['q']}: {d.get('results_count',0)} leads")
