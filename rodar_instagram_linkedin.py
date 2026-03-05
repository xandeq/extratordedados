import requests,json,sys,io,time
if sys.platform=='win32':sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')

API="https://api.extratordedados.com.br"
r=requests.post(f"{API}/api/login",json={"username":"admin","password":"1982Xandeq1982#"})
token=r.json().get('token')
h={"Authorization":f"Bearer {token}"}

print("="*60)
print("INSTAGRAM BUSINESS PROFILES - Rate limit: 3/hour")
print("="*60)

# Contas Instagram de negócios da região
insta_profiles=["clinicavitoriaes","odontovv","adv_es","contabilidadeES","consultores_es"]

insta_jobs=[]
for profile in insta_profiles[:3]:  # Máx 3 por rate limit
    r=requests.post(f"{API}/api/scrape/instagram",headers=h,json={"username":profile})
    if r.status_code==200:
        j=r.json()
        print(f"✅ @{profile}: job {j.get('job_id')}")
        insta_jobs.append(j.get('job_id'))
    else:
        print(f"❌ @{profile}: {r.status_code}")
    time.sleep(3)

print(f"\n{len(insta_jobs)} jobs Instagram iniciados\n")

print("="*60)
print("LINKEDIN COMPANIES - Rate limit: 2/hour")
print("="*60)

# Empresas LinkedIn da região
linkedin_companies=["clinica-exemplo-vitoria","advocacia-es"]

linkedin_jobs=[]
for company in linkedin_companies[:2]:  # Máx 2 por rate limit
    r=requests.post(f"{API}/api/scrape/linkedin",headers=h,json={"company":company})
    if r.status_code==200:
        j=r.json()
        print(f"✅ {company}: job {j.get('job_id')}")
        linkedin_jobs.append(j.get('job_id'))
    else:
        print(f"❌ {company}: {r.status_code}")
    time.sleep(3)

print(f"\n{len(linkedin_jobs)} jobs LinkedIn iniciados")
print("\nTotal jobs: Instagram={} LinkedIn={}".format(len(insta_jobs),len(linkedin_jobs)))
