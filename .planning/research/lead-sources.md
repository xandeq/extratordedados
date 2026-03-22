# Lead Generation APIs and Free Data Sources — Brazilian Market

**Researched:** 2026-03-22
**Domain:** B2B Lead Extraction / Brazilian Market Data
**Overall Confidence:** MEDIUM-HIGH (most findings verified via multiple sources)

---

## 1. Brazilian CNPJ and Company Registry APIs

These are the highest-priority additions. The Receita Federal publishes full CNPJ data openly — several community and commercial services wrap it into usable APIs. The project already uses BrasilAPI; the services below are either superior or complementary.

### 1.1 CNPJá (cnpja.com) — RECOMMENDED PRIMARY

**URL:** https://cnpja.com/en/api
**Free tier (public, no auth):** 5 requests/minute per IP
**Free tier (with account):** 10 requests/minute + 50 monthly credits for real-time online queries; cache queries are unlimited (no credit cost)
**Key feature:** "CACHE" query strategy returns most recent cached data at zero credit cost — critical for high-volume enrichment
**Fields returned:** CNPJ, razao social, nome fantasia, situacao cadastral, CNAE primário/secundário, address, telefone, email, socios, Simples Nacional, MEI, data abertura, capital social, porte
**Data quality:** Aggregates from Receita Federal + Sintegra + SUFRAMA + Simples Nacional
**Pricing:** Pay-per-credit above free tier; cache queries free
**Relevance:** HIGH — includes `telefone` and `email` fields from cadastro (when registered)
**Action:** Replace or supplement existing BrasilAPI calls with CNPJá cache strategy for speed + cost savings.

### 1.2 ReceitaWS (receitaws.com.br) — CURRENT (already partially used)

**URL:** https://receitaws.com.br/api
**Free tier:** 3 requests/minute (no auth required)
**Endpoint:** `GET https://receitaws.com.br/v1/cnpj/{cnpj}`
**Fields returned:** razao social, fantasia, abertura, situacao, tipo, atividade_principal, atividades_secundarias, natureza_juridica, logradouro, numero, complemento, cep, bairro, municipio, uf, email, telefone, efr, motivo_situacao, situacao_especial, data_situacao_especial, capital_social, qsa (socios)
**Confidence:** HIGH — confirmed 3 req/min limit in dev tutorials
**Note:** This is the most widely used free CNPJ API; rate limit is the main constraint. Good for low-volume enrichment or as fallback.

### 1.3 CNPJ.ws (cnpj.ws) — RECOMMENDED SECONDARY

**URL:** https://www.cnpj.ws / https://docs.cnpj.ws
**Free tier:** Public API, no auth required
**Fields:** Includes establishment data: socios, filiais, endereço, inscrição estadual, Simples Nacional, MEI, CNAEs, and `estabelecimento` object
**Differentiator:** Returns `filiais` (branches) — useful for multi-establishment companies
**Confidence:** MEDIUM (verified existence, full field list requires direct docs check)
**Action:** Test against CNPJá for fields; use as fallback rotation to spread rate limits.

### 1.4 OpenCNPJ (opencnpj.org) — BULK DOWNLOAD

**URL:** https://opencnpj.org
**Free tier:** Completely free, no auth, no rate limits stated
**Model:** Monthly updated full CNPJ database available as a single ZIP download from Receita Federal
**Use case:** Local database enrichment — download once, query locally, no per-query cost
**Update frequency:** Monthly (mirrors Receita Federal public release)
**Confidence:** HIGH
**Action:** Download and index locally for offline enrichment. Eliminates API rate limits entirely for CNPJ lookups. Massive competitive advantage at scale.

### 1.5 Receita Federal Raw Open Data — BULK DOWNLOAD

**URL:** https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-da-pessoa-juridica---cnpj
**Mirror:** https://arquivos.receitafederal.gov.br/cnpj/dados_abertos_cnpj/
**Metadata:** https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf
**Free tier:** Completely free, public domain
**Fields in ESTABELECIMENTOS file:** CNPJ básico, CNPJ ordem, CNPJ dígitos, identificador matriz/filial, nome fantasia, situação cadastral, data situação, motivo situação, cidade exterior, pais, data início atividade, CNAE fiscal principal, CNAEs secundários, logradouro, número, complemento, bairro, CEP, UF, município, **ddd_1, telefone_1, ddd_2, telefone_2, ddd_fax, fax**, **email**, situação especial, data situação especial
**Critical finding:** The raw RF data DOES include `email` and `telefone` fields per establishment (not every company fills them, but many do)
**Confidence:** HIGH — verified from official metadata PDF link
**Action:** This is the most powerful source. A local PostgreSQL import of the full CNPJ dataset gives instant, unlimited, free access to phone numbers and emails for ~60M CNPJs. The GitHub project `aphonsoar/Receita_Federal_do_Brasil_-_Dados_Publicos_CNPJ` provides import tooling.

### 1.6 Minha Receita (minhareceita.org) — SELF-HOSTED OPTION

**GitHub:** https://github.com/cuducos/minha-receita
**Model:** Open source Go server that serves the RF CNPJ data via REST API
**Free tier:** Completely free if self-hosted on VPS
**Fields:** 47+ fields from official Receita Federal data
**Rate limits:** None (self-hosted — limited only by VPS resources)
**Confidence:** HIGH (established open source project)
**Action:** Deploy on existing VPS (185.173.110.180) alongside the Flask app. Gives an internal CNPJ API with no external rate limits. Highly recommended for production scale.

### 1.7 Speedio (speedio.com.br / apiconsultacnpj.com.br)

**URL:** https://www.apiconsultacnpj.com.br
**Free tier:** Limited CNPJ lookup API; 50 leads free trial on main platform
**Model:** Crosses 80+ data points, AI-validated contacts, 80+ segmentation filters
**Differentiator:** Goes beyond RF data — enriches with additional contact validation
**Pricing:** Paid platform; API free tier exists but limits not well-documented
**Confidence:** MEDIUM
**Action:** Evaluate free tier; potentially useful for validated contact enrichment beyond raw CNPJ data.

---

## 2. Government Open Data Portals

### 2.1 Portal de Dados Abertos (dados.gov.br)

**URL:** https://dados.gov.br
**Coverage:** 12,000+ datasets from all government levels
**Business-relevant datasets:**
- CNPJ cadastral data (Receita Federal)
- CVM company registry (public companies)
- INPI trademark/patent data
- IBGE economic census data
**Access:** Free, direct download, no API key required
**Confidence:** HIGH

### 2.2 Portal de Dados Abertos CVM (dados.cvm.gov.br)

**URL:** https://dados.cvm.gov.br
**Coverage:** All companies registered with the CVM (publicly traded + FIIs + fundos)
**Fields:** CNPJ, razao social, situação cadastral, data registro, setor, subsetor
**Use case:** Enrich leads that are publicly traded companies; verify legitimacy; add financial data
**Update frequency:** Daily
**Access:** Free download, CSV/JSON
**Confidence:** HIGH
**Action:** Index CVM dataset locally; use to flag companies as "public" and add regulatory status to enrichment.

### 2.3 DataSebrae (datasebrae.com.br)

**URL:** https://datasebrae.com.br
**Coverage:** Research on Brazilian SMBs — not direct contact data
**Use case:** Market intelligence (which sectors have most SMBs, regional distribution) to improve niche targeting
**Confidence:** MEDIUM

### 2.4 IBGE API

**URL:** https://servicodados.ibge.gov.br/api/docs/
**Coverage:** Geographic data — municípios, estados, CEPs, population
**Use case:** Geographic enrichment — validate city/state, get municipal codes (IBGE codes used in RF data), population context for lead scoring
**Access:** Free, no auth
**Confidence:** HIGH

---

## 3. Email Finder APIs (Domain-to-Email Discovery)

Replacements and alternatives to Hunter.io with better free tiers or pricing.

### 3.1 Prospeo (prospeo.io) — RECOMMENDED

**URL:** https://prospeo.io
**Free tier:** 75 verified email searches/month (no credit card)
**APIs available:** Email Finder API, Domain Search API, Social URL Enrichment API, Mobile Finder API, Email Verifier API
**Pricing:** Paid plans start low
**Key feature:** Social URL enrichment — give it a LinkedIn URL, get the email
**Accuracy:** 16.9% find rate (independent benchmark Sep 2025, Anymail Finder methodology — lower but verified)
**Confidence:** HIGH (multiple sources confirm)
**Action:** Integrate Prospeo Domain Search API as Hunter.io supplement. Social URL enrichment is a unique differentiator for LinkedIn-sourced leads.

### 3.2 Anymail Finder (anymailfinder.com) — HIGHEST ACCURACY

**URL:** https://anymailfinder.com
**Free tier:** 100 credits (7-day expiry on signup)
**Pricing:** €26/month for 400 credits (Starter); only charged for verified results
**Accuracy:** Highest in independent Sep 2025 benchmark of 5,000 contacts
**API:** Full REST API, supports bulk CSV processing
**Confidence:** HIGH
**Action:** Use as premium verification tier when accuracy matters most (e.g., for paid outreach lists).

### 3.3 Findymail (findymail.com)

**URL:** https://findymail.com
**Free tier:** 10 bulk processing credits on free trial
**Pricing:** $49/month for 1,000 emails; $99/month for 5,000 emails
**Differentiator:** Fastest bulk processing (~2 min vs 15-30 min at competitors); only charges for verified results
**Accuracy:** 75.1% find rate in Sep 2025 benchmark (second place)
**Confidence:** HIGH
**Action:** Evaluate for bulk domain-list email discovery where speed matters.

### 3.4 Voila Norbert (voilanorbert.com)

**URL:** https://www.voilanorbert.com
**Free tier:** 50 credits on signup
**Pricing:** $49/month for 1,000 leads; only pays for successful finds
**API:** Full REST API available
**Confidence:** HIGH

### 3.5 Apollo.io (apollo.io) — ENRICHMENT PLATFORM

**URL:** https://www.apollo.io
**Free tier:** 70 credits/month (email lookups cost 1 credit each)
**Database:** 275M+ contacts, 73M companies
**Key feature:** Person + company enrichment from domain or LinkedIn URL
**Brazilian coverage:** MEDIUM (global database, US-heavy)
**Confidence:** HIGH
**Note:** Free tier is too limited for production volume but useful for targeted enrichment.

### 3.6 People Data Labs (PDL) (peopledatalabs.com)

**URL:** https://www.peopledatalabs.com
**Free tier:** 100 person/company lookups/month (free plan)
**API:** Full REST API, person enrichment, company enrichment, search
**Brazilian coverage:** MEDIUM-LOW (global, but Brazilian records exist for larger companies)
**Confidence:** MEDIUM

---

## 4. Email Validation APIs

For validating extracted email lists at scale (10k-50k/month).

### 4.1 MillionVerifier — RECOMMENDED FOR VOLUME

**URL:** https://www.millionverifier.com
**Free credits:** 10,000 one-time free credits (no expiry)
**Paid pricing:** $37 for 10,000 verifications ($0.0037/email) — cheapest in market
**Credits:** Never expire
**Accuracy:** High (not specified vs competitors but widely reviewed positively)
**API:** Available
**Confidence:** HIGH (multiple review sources confirm pricing)
**Action:** Use for bulk validation of extracted leads. At $0.0037/email, validating 50k/month costs ~$185 — very competitive.

### 4.2 ZeroBounce (zerobounce.net)

**URL:** https://www.zerobounce.net
**Free tier:** 100 verifications/month (with business domain email signup)
**Paid pricing:** Pay-as-you-go available
**Accuracy:** 99.6% stated
**Extra features:** Activity Data (email engagement signals), Email Finder, duplicate removal
**Credits:** Never expire
**API:** Full REST API
**Confidence:** HIGH

### 4.3 NeverBounce (neverbounce.com)

**URL:** https://www.neverbounce.com
**Free tier:** 100 credits/month
**Paid:** $16 for 2,000 emails (pay-as-you-go)
**API:** Available
**Accuracy:** 97% stated
**Confidence:** HIGH

### 4.4 AbstractAPI Email Validation

**URL:** https://www.abstractapi.com/api/email-verification-validation-api
**Free tier:** 100 validations/month
**Features:** Syntax check, MX record check, SMTP check, disposable email detection
**Confidence:** MEDIUM

### 4.5 Maileroo (maileroo.com)

**URL:** https://maileroo.com/free-email-verification-api
**Free tier:** 250 verifications/month
**API:** Free email verification API
**Confidence:** MEDIUM

---

## 5. Brazilian-Specific Lead Generation Platforms

### 5.1 CNPJ.biz (cnpj.biz)

**URL:** https://cnpj.biz
**Model:** B2B prospecting SaaS — 60M+ company database, filters by CNAE, city, neighborhood, porte
**Free trial:** Available (lead count not specified)
**Features:** Phone + email in lists, export to Excel/CRM, WhatsApp with AI, integrated CRM
**Use case:** Not an API but a source for acquiring pre-filtered, pre-enriched Brazilian leads
**Confidence:** MEDIUM
**Action:** Evaluate trial for niche/region combinations not reachable via current scraping.

### 5.2 EmpresAqui (empresaqui.com.br)

**URL:** https://www.empresaqui.com.br
**Model:** Updated company lists for B2B prospecting
**Use case:** Similar to CNPJ.biz — pre-built filtered lists
**Confidence:** LOW (limited research; requires direct evaluation)

### 5.3 Econodata (econodata.com.br)

**URL:** https://www.econodata.com.br
**Model:** Brazilian B2B intelligence platform with 20M+ companies
**Filters:** CNAE, porte, localização, faturamento estimado
**Free tier:** Limited trial
**Confidence:** MEDIUM (well-known in Brazilian B2B market)

---

## 6. Google Maps / Local Business Data Alternatives

### 6.1 Outscraper (outscraper.com) — RECOMMENDED

**URL:** https://outscraper.com/google-maps-scraper
**Free tier:** 500 business records/month (resets monthly, no credit card)
**Paid pricing:** $3/1,000 records up to 100k; $1/1,000 records above 100k
**Data extracted:** Business name, email, phone, website, address, rating, reviews, categories
**API:** Full REST API + Python/JS clients
**Coverage:** 100M+ business records, 249 countries
**Confidence:** HIGH
**Action:** Use as API complement to existing Playwright Google Maps scraping. Outscraper handles anti-bot at scale; cheaper than Apify actor for high volume.

### 6.2 Apify (apify.com) — ALREADY USING

**Current actor:** `lukaskrivka~google-maps-with-contact-details`
**Alternative actors for Brazil:**
- `compass/crawler-google-places` — Google Maps Scraper (most popular, 4.8 stars)
- `natural_lease/google-maps-local-leads-scraper` — Local leads with website audit score
- `mea/leadlocator-pro` — Emails + Phone extraction
**Free tier:** $5/month free compute on Starter
**Action:** Test `compass/crawler-google-places` as it's the platform's flagship actor and may return more fields than current actor.

---

## 7. Additional Enrichment Sources

### 7.1 BrasilAPI (brasilapi.com.br) — ALREADY USING FOR CNPJ

**Additional endpoints not yet used:**
- `GET /api/cnpj/v1/{cnpj}` — already integrated
- `GET /api/cep/v2/{cep}` — CEP to full address (useful for address normalization)
- `GET /api/banks/v1` — Bank list (for lead context)
- `GET /api/ibge/municipios/v1/{uf}` — List of municipalities per state
**All free, no auth, no rate limits stated**
**Confidence:** HIGH
**Action:** Integrate CEP endpoint for address normalization during lead enrichment.

### 7.2 SintegraWS (sintegraws.com.br)

**URL:** https://www.sintegraws.com.br/api
**Model:** CNPJ + state tax registration (inscrição estadual) lookup
**Use case:** Verify if company is active state-level (Sintegra data), get state registration number
**Free tier:** Limited; requires registration
**Confidence:** MEDIUM
**Note:** Inscrição estadual data is not in the free CNPJ APIs — unique enrichment field.

### 7.3 Casa dos Dados (dados-abertos-rf-cnpj.casadosdados.com.br)

**URL:** https://dados-abertos-rf-cnpj.casadosdados.com.br
**Model:** Hosted copy of Receita Federal CNPJ open data, searchable via web interface
**Use case:** Manual verification and search interface for RF data
**API:** Unclear if API exists
**Confidence:** LOW

---

## 8. LinkedIn Alternatives and Social Enrichment

### 8.1 Evaboot / Airscale (Sales Navigator Scrapers)

- Evaboot: Optimized for LinkedIn Sales Navigator export + enrichment
- Airscale: Free solution for scraping Sales Navigator
**Use case:** When you have LinkedIn URLs (from Playwright scraping), use these to enrich with verified emails
**Confidence:** MEDIUM

### 8.2 Prospeo Social URL Enrichment

**URL:** https://prospeo.io/api
**Feature:** Input a LinkedIn profile URL → get verified professional email
**Free tier:** Part of 75 monthly credits
**Confidence:** HIGH
**Action:** Integrate for LinkedIn-sourced leads. This is a direct complement to existing LinkedIn Playwright scraping — scrape the URL, then enrich with Prospeo.

---

## 9. Prioritized Integration Roadmap

Listed by impact-to-effort ratio for the extrator-de-dados project:

### Tier 1 — Immediate (Free, High Impact)

| Source | Action | Expected Gain |
|--------|--------|---------------|
| Receita Federal raw data | Download + import CNPJ dataset to local PostgreSQL | Phone + email for ~60M CNPJs, unlimited queries |
| Minha Receita (self-hosted) | Deploy Go server on VPS | Internal API, no rate limits, 47 fields |
| CNPJá cache strategy | Replace BrasilAPI calls where cache is acceptable | Zero credit cost for most queries, better fields |
| BrasilAPI CEP endpoint | Add `/api/cep/v2/{cep}` to enrichment pipeline | Address normalization for all leads |
| CVM open data | Import CVM company dataset | Flag publicly traded companies, add regulatory data |

### Tier 2 — Short-term (Low cost, medium effort)

| Source | Action | Expected Gain |
|--------|--------|---------------|
| Outscraper | Integrate API as fallback for Google Maps | 500 free records/month, reliable anti-bot |
| Prospeo Social URL enrichment | Add after LinkedIn scraping step | Convert LinkedIn profiles to verified emails |
| MillionVerifier | Integrate for bulk email validation | $0.0037/email at scale, clean list quality |
| CNPJ.ws | Add as rate-limit rotation with ReceitaWS/CNPJá | More uptime, higher aggregate throughput |

### Tier 3 — Evaluate (Paid, higher investment)

| Source | Action | Expected Gain |
|--------|--------|---------------|
| Anymail Finder | Test for premium list creation | Highest accuracy email finder |
| Findymail | Test bulk domain processing | Fast bulk email discovery |
| ZeroBounce | Replace or complement current validation | 99.6% accuracy + activity data signals |
| Speedio | Trial 50 leads | Validated B2B contacts with 80+ enrichment points |

---

## 10. Compliance and Legal Notes

- **Receita Federal data:** Explicitly public under Brazilian transparency law (Lei de Acesso à Informação). Free to use for any purpose.
- **CNPJ APIs:** All wrap publicly available government data — legal to use.
- **Email harvesting from websites:** Legally gray in Brazil (LGPD applies). Current practice of extracting emails from public websites is common but requires consent for marketing use.
- **LGPD (Lei Geral de Proteção de Dados):** Applies to personal data (CPF, individual contacts). Company data (CNPJ, business emails, business phones) has fewer restrictions but B2C contact requires opt-in.
- **WhatsApp:** Meta's API requires business opt-in. Scraping WhatsApp numbers for unsolicited contact violates ToS.
- **LinkedIn:** Playwright scraping violates LinkedIn ToS. Current approach carries account ban risk. Prospeo/Evaboot provide a ToS-safer alternative.

---

## 11. Quick Reference — API Summary Table

| API | Free Tier | Auth Required | Best Use | Confidence |
|-----|-----------|---------------|----------|------------|
| CNPJá (cache) | Unlimited cache queries | Optional (account = higher rate limits) | CNPJ enrichment at scale | HIGH |
| ReceitaWS | 3 req/min | None | Simple CNPJ lookup | HIGH |
| CNPJ.ws | Public, rate unclear | None | Branch/filial data | MEDIUM |
| OpenCNPJ | Free, no limits | None | Full DB download | HIGH |
| RF Raw Data | Free download | None | Local bulk enrichment | HIGH |
| Minha Receita | Free (self-hosted) | None | VPS-hosted CNPJ API | HIGH |
| BrasilAPI (CEP) | Free, no limit | None | Address normalization | HIGH |
| CVM dados abertos | Free download | None | Public company data | HIGH |
| Outscraper | 500 records/month | Yes (API key) | Google Maps alternative | HIGH |
| Prospeo | 75 emails/month | Yes | Domain + LinkedIn email | HIGH |
| Anymail Finder | 100 credits (7-day) | Yes | Highest accuracy email finder | HIGH |
| Findymail | 10 bulk credits | Yes | Fast bulk email discovery | HIGH |
| MillionVerifier | 10,000 one-time | Yes | Bulk email validation | HIGH |
| ZeroBounce | 100/month | Yes | Email validation + activity data | HIGH |
| NeverBounce | 100/month | Yes | Email validation | HIGH |
| Apollo.io | 70 credits/month | Yes | Contact enrichment | HIGH |
| PDL | 100 lookups/month | Yes | Person/company enrichment | MEDIUM |
| Speedio | 50 leads trial | Yes | Validated BR B2B contacts | MEDIUM |

---

## Sources

- [CNPJá API Documentation](https://cnpja.com/en/api)
- [CNPJá Pricing](https://cnpja.com/en/pricing)
- [ReceitaWS API](https://receitaws.com.br/api)
- [CNPJ.ws Documentation](https://docs.cnpj.ws/en/api-reference/api-publica/limitacoes)
- [OpenCNPJ Public API](https://opencnpj.org/)
- [Receita Federal Dados Abertos CNPJ](https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-da-pessoa-juridica---cnpj)
- [RF CNPJ Metadata PDF](https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf)
- [Minha Receita GitHub](https://github.com/cuducos/minha-receita)
- [GitHub - Receita Federal CNPJ importer](https://github.com/aphonsoar/Receita_Federal_do_Brasil_-_Dados_Publicos_CNPJ)
- [Dados CVM Portal](https://dados.cvm.gov.br/)
- [Portal de Dados Abertos Brasil](https://dados.gov.br/)
- [Prospeo Email Finder](https://prospeo.io/email-finder)
- [Prospeo Domain Search API](https://prospeo.io/api/domain-search)
- [Anymail Finder Pricing](https://anymailfinder.com/pricing)
- [Findymail vs Prospeo Comparison](https://coldiq.com/blog/prospeo-vs-findymail)
- [Apollo.io Pricing](https://www.apollo.io/pricing)
- [People Data Labs Pricing](https://fullenrich.com/content/people-data-labs-pricing)
- [MillionVerifier vs ZeroBounce](https://sparkle.io/blog/millionverifier-vs-zerobounce/)
- [ZeroBounce Pricing](https://www.zerobounce.net/email-validation-pricing)
- [NeverBounce Pricing](https://www.neverbounce.com/pricing)
- [Outscraper Google Maps Scraper](https://outscraper.com/google-maps-scraper/)
- [Outscraper Pricing](https://outscraper.com/pricing/)
- [Apify Google Maps Scraper](https://apify.com/compass/crawler-google-places)
- [BrazilDataAPI](https://lightbluetitan.github.io/brazildataapi/)
- [Speedio API CNPJ Gratuita](https://www.apiconsultacnpj.com.br/)
- [CNPJ.biz Platform](https://cnpj.biz/)
- [Hunter.io Alternatives 2025](https://www.kaspr.io/blog/hunter-io-alternatives)
- [Best Email Finder Tools 2025 Benchmark](https://anymailfinder.com/blog/best-email-finder-tools-2025)
