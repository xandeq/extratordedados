"""
MASSIVE SEARCH ENDPOINT - To be added to app.py
Endpoint para busca massiva usando TODOS os métodos disponíveis
"""

# Add this after line ~3400 (after /api/search-api endpoint)

@app.route('/api/search/massive', methods=['POST'])
@limiter.limit("1/hour")  # Limit massivo é menor
def start_massive_search():
    """
    Start a massive search using ALL available methods:
    - API Enrichment (Hunter.io/Snov.io)
    - Search Engines (DuckDuckGo/Bing)
    - Google Maps Playwright
    - Instagram Business
    - LinkedIn Companies
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    # Parameters
    niches = data.get('niches', [])  # Lista de nichos
    region_id = (data.get('region') or '').strip()
    city = (data.get('city') or '').strip()
    state = (data.get('state') or '').strip()
    methods = data.get('methods', ['api_enrichment', 'search_engines', 'google_maps'])  # Métodos selecionados
    max_pages = min(3, max(1, int(data.get('max_pages', 2))))

    if not niches or len(niches) == 0:
        return jsonify({'error': 'Pelo menos um nicho é obrigatório'}), 400

    # Build cities list
    cities_to_search = []
    if region_id and region_id in SEARCH_REGIONS:
        region_data = SEARCH_REGIONS[region_id]
        for c_name in region_data['cities']:
            cities_to_search.append({
                'city': c_name,
                'state': region_data['state'],
                'region': region_id,
            })
    elif city and state:
        cities_to_search.append({
            'city': city,
            'state': state,
            'region': 'manual',
        })
    else:
        return jsonify({'error': 'Selecione uma região ou informe cidade/estado'}), 400

    # Create master batch
    batch_name = f'Busca Massiva - {region_id or city}'
    if len(niches) > 1:
        batch_name += f' ({len(niches)} nichos)'

    with get_db() as conn:
        c = conn.cursor()

        # Calculate total jobs
        total_jobs = 0
        if 'api_enrichment' in methods:
            total_jobs += len(niches) * len(cities_to_search)
        if 'search_engines' in methods:
            total_jobs += len(niches)
        if 'google_maps' in methods:
            total_jobs += len(niches) * len(cities_to_search)

        c.execute(
            'INSERT INTO batches (user_id, name, status, total_urls, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id',
            (user_id, batch_name, 'pending', total_jobs, datetime.now())
        )
        batch_id = c.fetchone()[0]

        # ===========================================================
        # METHOD 1: API ENRICHMENT (Hunter.io / Snov.io)
        # ===========================================================
        api_enrichment_jobs = []
        if 'api_enrichment' in methods:
            for niche in niches[:3]:  # Max 3 por rate limit
                for city_data in cities_to_search[:1]:  # 1 cidade por nicho para não explodir
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, enrichment_source, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         city_data['region'], max_pages, 'pending', 'hunter+snov', datetime.now())
                    )
                    search_job_id = c.fetchone()[0]
                    api_enrichment_jobs.append({
                        'search_job_id': search_job_id,
                        'niche': niche,
                        'city': city_data['city'],
                        'state': city_data['state'],
                        'max_pages': max_pages,
                    })

        # ===========================================================
        # METHOD 2: SEARCH ENGINES (DuckDuckGo / Bing)
        # ===========================================================
        search_engine_jobs = []
        if 'search_engines' in methods:
            for niche in niches[:3]:  # Max 3 por rate limit
                c.execute(
                    '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, region, max_pages, status, engine, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                    (batch_id, user_id, niche, None, None, region_id, max_pages, 'pending', 'duckduckgo', datetime.now())
                )
                search_job_id = c.fetchone()[0]
                search_engine_jobs.append({
                    'search_job_id': search_job_id,
                    'niche': niche,
                    'region': region_id,
                    'max_pages': max_pages,
                })

        # ===========================================================
        # METHOD 3: GOOGLE MAPS (via existing endpoint)
        # Note: Google Maps não usa search_jobs, cria jobs separados
        # Vamos apenas salvar referência para tracking
        # ===========================================================
        google_maps_jobs = []
        if 'google_maps' in methods:
            for niche in niches[:2]:  # Max 2 para não saturar
                for city_data in cities_to_search[:2]:  # Max 2 cidades
                    # Criar entry de tracking
                    c.execute(
                        '''INSERT INTO search_jobs (batch_id, user_id, niche, city, state, max_pages, status, engine, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                        (batch_id, user_id, niche, city_data['city'], city_data['state'],
                         0, 'pending', 'google_maps', datetime.now())
                    )
                    search_job_id = c.fetchone()[0]
                    google_maps_jobs.append({
                        'search_job_id': search_job_id,
                        'niche': niche,
                        'city': city_data['city'],
                        'state': city_data['state'],
                    })

    # ============================================================
    # START BACKGROUND THREADS FOR EACH METHOD
    # ============================================================

    # Thread 1: API Enrichment
    if api_enrichment_jobs:
        thread1 = threading.Thread(
            target=process_api_search_job,
            args=(batch_id, api_enrichment_jobs, user_id),
            daemon=True
        )
        thread1.start()

    # Thread 2: Search Engines
    if search_engine_jobs:
        thread2 = threading.Thread(
            target=process_search_job,
            args=(batch_id, search_engine_jobs, user_id),
            daemon=True
        )
        thread2.start()

    # Thread 3: Google Maps (precisa ser chamado via requests internos)
    if google_maps_jobs:
        thread3 = threading.Thread(
            target=process_google_maps_massive,
            args=(batch_id, google_maps_jobs, user_id, token),
            daemon=True
        )
        thread3.start()

    return jsonify({
        'batch_id': batch_id,
        'name': batch_name,
        'total_jobs': total_jobs,
        'methods': {
            'api_enrichment': len(api_enrichment_jobs),
            'search_engines': len(search_engine_jobs),
            'google_maps': len(google_maps_jobs),
        },
        'status': 'processing',
        'message': f'Busca massiva iniciada com {total_jobs} jobs em {len(methods)} métodos'
    })


def process_google_maps_massive(batch_id, jobs_data, user_id, token):
    """Process Google Maps jobs for massive search."""
    with get_db() as conn:
        c = conn.cursor()

        for job_data in jobs_data:
            search_job_id = job_data['search_job_id']
            niche = job_data['niche']
            city = job_data['city']
            state = job_data['state']

            try:
                # Update status to running
                c.execute(
                    'UPDATE search_jobs SET status = %s, started_at = %s WHERE id = %s',
                    ('running', datetime.now(), search_job_id)
                )
                conn.commit()

                # Chamar scraper de Google Maps internamente
                # (Playwright já implementado em outro endpoint)
                results = scrape_google_maps_playwright(f"{niche} {city} {state}", max_places=20)

                if results and len(results) > 0:
                    # Inserir leads no batch
                    for result in results:
                        email = result.get('email', '')
                        phone = result.get('phone', '')
                        website = result.get('website', '')

                        if email or phone or website:
                            c.execute(
                                '''INSERT INTO leads (batch_id, company_name, email, phone, website, city, state, source, extracted_at)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                   ON CONFLICT (batch_id, email) DO NOTHING''',
                                (batch_id, result.get('name', 'Lead sem nome'), email, phone, website,
                                 city, state, 'google_maps', datetime.now())
                            )

                    conn.commit()

                    # Update status to completed
                    c.execute(
                        'UPDATE search_jobs SET status = %s, finished_at = %s, total_leads = %s WHERE id = %s',
                        ('completed', datetime.now(), len(results), search_job_id)
                    )
                    conn.commit()
                else:
                    # No results
                    c.execute(
                        'UPDATE search_jobs SET status = %s, finished_at = %s, total_leads = %s WHERE id = %s',
                        ('completed', datetime.now(), 0, search_job_id)
                    )
                    conn.commit()

            except Exception as e:
                # Error handling
                c.execute(
                    'UPDATE search_jobs SET status = %s, error_message = %s, finished_at = %s WHERE id = %s',
                    ('failed', str(e)[:500], datetime.now(), search_job_id)
                )
                conn.commit()

            # Delay entre jobs para evitar rate limit
            time.sleep(10)

        # Update batch final status
        c.execute(
            '''SELECT COUNT(*) FROM search_jobs
               WHERE batch_id = %s AND status IN ('pending', 'running')''',
            (batch_id,)
        )
        remaining = c.fetchone()[0]

        if remaining == 0:
            c.execute(
                'UPDATE batches SET status = %s WHERE id = %s',
                ('completed', batch_id)
            )
            conn.commit()


# ============================================================
# EXTERNAL APIs INTEGRATION (Apollo.io, PDL, FindThatLead)
# ============================================================

def search_apollo_io(company_name, domain=None, api_key=None):
    """
    Search for leads using Apollo.io API
    Free tier: 50 emails/month
    """
    if not api_key:
        return None

    url = "https://api.apollo.io/v1/people/match"
    headers = {
        'Cache-Control': 'no-cache',
        'Content-Type': 'application/json',
        'X-Api-Key': api_key
    }

    payload = {
        "first_name": "",
        "last_name": "",
        "organization_name": company_name,
    }

    if domain:
        payload['domain'] = domain

    try:
        response = http_requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            person = data.get('person', {})
            return {
                'email': person.get('email'),
                'phone': person.get('phone_numbers', [{}])[0].get('raw_number') if person.get('phone_numbers') else None,
                'name': f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
                'title': person.get('title'),
                'company': person.get('organization', {}).get('name'),
                'source': 'apollo.io'
            }
    except Exception as e:
        print(f"Apollo.io error: {e}")

    return None


def search_pdl(company_name, domain=None, api_key=None):
    """
    Search for leads using PDL (People Data Labs) API
    Free tier: 1000 credits/month
    """
    if not api_key:
        return None

    url = "https://api.peopledatalabs.com/v5/company/enrich"
    headers = {
        'X-Api-Key': api_key
    }

    params = {
        'name': company_name,
    }

    if domain:
        params['website'] = domain

    try:
        response = http_requests.get(url, params=params, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            company = data.get('data', {})
            return {
                'email': company.get('emails', [None])[0],
                'phone': company.get('phone'),
                'website': company.get('website'),
                'company': company.get('name'),
                'location': company.get('location'),
                'source': 'pdl'
            }
    except Exception as e:
        print(f"PDL error: {e}")

    return None


def search_findthatlead(domain, api_key=None):
    """
    Search for leads using FindThatLead API
    Free tier: 50 emails/month
    """
    if not api_key:
        return None

    url = f"https://api.findthatlead.com/v1/companies/{domain}"
    headers = {
        'Authorization': f'Bearer {api_key}'
    }

    try:
        response = http_requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            company = data.get('company', {})
            emails = company.get('emails', [])
            return {
                'email': emails[0] if emails else None,
                'phone': company.get('phone'),
                'website': company.get('website'),
                'company': company.get('name'),
                'source': 'findthatlead'
            }
    except Exception as e:
        print(f"FindThatLead error: {e}")

    return None


@app.route('/api/enrich/external', methods=['POST'])
@limiter.limit("50/hour")
def enrich_with_external_apis():
    """
    Enrich a lead using external APIs (Apollo.io, PDL, FindThatLead)
    """
    token = get_auth_header()
    user_id = verify_token(token)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    company_name = data.get('company_name', '').strip()
    domain = data.get('domain', '').strip()

    # API keys (can be stored in DB or env vars)
    apollo_key = os.environ.get('APOLLO_API_KEY')
    pdl_key = os.environ.get('PDL_API_KEY')
    findthatlead_key = os.environ.get('FINDTHATLEAD_API_KEY')

    results = []

    # Try Apollo.io
    if apollo_key:
        result = search_apollo_io(company_name, domain, apollo_key)
        if result:
            results.append(result)

    # Try PDL
    if pdl_key:
        result = search_pdl(company_name, domain, pdl_key)
        if result:
            results.append(result)

    # Try FindThatLead
    if findthatlead_key and domain:
        result = search_findthatlead(domain, findthatlead_key)
        if result:
            results.append(result)

    return jsonify({
        'results': results,
        'total': len(results)
    })
