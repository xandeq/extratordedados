"""
NEW LEAD SOURCES - 10 POWERFUL METHODS
Add these to app.py for MASSIVE lead coverage
"""

# ============================================================
# METHOD 7: YELP API (5,000 calls/day FREE!)
# ============================================================

def search_yelp_api(term, location, api_key=None):
    """
    Search Yelp API for businesses
    FREE: 5,000 calls/day
    Perfect for: restaurants, clinics, services
    """
    if not api_key:
        # Get free API key at: https://www.yelp.com/developers/v3/manage_app
        return []

    import requests

    url = "https://api.yelp.com/v3/businesses/search"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    params = {
        "term": term,
        "location": location,
        "limit": 50,  # Max 50 per request
        "locale": "pt_BR"
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            businesses = data.get('businesses', [])

            leads = []
            for biz in businesses:
                lead = {
                    'name': biz.get('name'),
                    'phone': biz.get('phone', '').replace('+55', ''),
                    'website': biz.get('url'),  # Yelp page URL
                    'address': ', '.join(biz.get('location', {}).get('display_address', [])),
                    'city': biz.get('location', {}).get('city'),
                    'state': biz.get('location', {}).get('state'),
                    'rating': biz.get('rating'),
                    'review_count': biz.get('review_count'),
                    'categories': ', '.join([c.get('title') for c in biz.get('categories', [])]),
                    'source': 'yelp'
                }
                leads.append(lead)

            return leads
    except Exception as e:
        print(f"[YELP] Error: {e}")
        return []


# ============================================================
# METHOD 8: YELLOW PAGES BR (Playwright scraping)
# ============================================================

async def scrape_yellow_pages_br(category, city, state):
    """
    Scrape listeloja.com.br (Brazilian Yellow Pages)
    Returns: company name, phone, address, website
    """
    from playwright.async_api import async_playwright

    url = f"https://www.listeloja.com.br/{state.lower()}/{city.lower()}/{category.lower()}"

    results = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(url, wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(2000)

            # Extract business listings
            listings = await page.query_selector_all('.business-item, .listing-card')

            for listing in listings[:50]:  # Max 50 per page
                try:
                    name = await listing.query_selector('.business-name, .company-name')
                    phone = await listing.query_selector('.phone, .telefone')
                    address = await listing.query_selector('.address, .endereco')
                    website = await listing.query_selector('a.website, .site')

                    result = {
                        'name': await name.text_content() if name else '',
                        'phone': await phone.text_content() if phone else '',
                        'address': await address.text_content() if address else '',
                        'website': await website.get_attribute('href') if website else '',
                        'city': city,
                        'state': state,
                        'source': 'yellow_pages_br'
                    }

                    results.append(result)
                except:
                    continue

            await browser.close()
    except Exception as e:
        print(f"[YELLOW_PAGES] Error: {e}")

    return results


# ============================================================
# METHOD 9: GUIA MAIS (Playwright)
# ============================================================

async def scrape_guia_mais(query, city, state):
    """
    Scrape guiamais.com.br - Brazilian business directory
    """
    from playwright.async_api import async_playwright
    import urllib.parse

    query_encoded = urllib.parse.quote(f"{query} {city} {state}")
    url = f"https://www.guiamais.com.br/busca?q={query_encoded}"

    results = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(3000)

            # Extract listings
            listings = await page.query_selector_all('.card-local, .resultado-busca')

            for listing in listings[:30]:
                try:
                    name_el = await listing.query_selector('.nome, h2, .title')
                    phone_el = await listing.query_selector('.telefone, .phone')
                    address_el = await listing.query_selector('.endereco, .address')

                    name = await name_el.text_content() if name_el else ''
                    phone = await phone_el.text_content() if phone_el else ''
                    address = await address_el.text_content() if address_el else ''

                    results.append({
                        'name': name.strip(),
                        'phone': phone.strip(),
                        'address': address.strip(),
                        'city': city,
                        'state': state,
                        'source': 'guia_mais'
                    })
                except:
                    continue

            await browser.close()
    except Exception as e:
        print(f"[GUIA_MAIS] Error: {e}")

    return results


# ============================================================
# METHOD 10: APONTADOR (Playwright)
# ============================================================

async def scrape_apontador(query, city, state):
    """
    Scrape apontador.com.br - Local business search
    """
    from playwright.async_api import async_playwright
    import urllib.parse

    query_formatted = urllib.parse.quote(f"{query}")
    location = urllib.parse.quote(f"{city}, {state}")
    url = f"https://www.apontador.com.br/local/busca.html?q={query_formatted}&l={location}"

    results = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(2000)

            listings = await page.query_selector_all('.poi-card, .local-item')

            for listing in listings[:40]:
                try:
                    name = await listing.query_selector('.poi-name, .name')
                    phone = await listing.query_selector('.phone, .telefone')
                    address = await listing.query_selector('.address, .endereco')

                    results.append({
                        'name': await name.text_content() if name else '',
                        'phone': await phone.text_content() if phone else '',
                        'address': await address.text_content() if address else '',
                        'city': city,
                        'state': state,
                        'source': 'apontador'
                    })
                except:
                    continue

            await browser.close()
    except Exception as e:
        print(f"[APONTADOR] Error: {e}")

    return results


# ============================================================
# METHOD 11: PÁGINAS AMARELAS (Playwright)
# ============================================================

async def scrape_paginas_amarelas(category, city, state):
    """
    Scrape paginasamarelas.com.br - Classic Brazilian directory
    """
    from playwright.async_api import async_playwright

    url = f"https://www.paginasamarelas.com.br/{category}/{city}-{state}"

    results = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(2000)

            listings = await page.query_selector_all('.listing, .empresa')

            for listing in listings[:50]:
                try:
                    name = await listing.query_selector('.title, .nome')
                    phone = await listing.query_selector('.phone, .telefone')
                    address = await listing.query_selector('.address, .endereco')
                    website = await listing.query_selector('a.website')

                    results.append({
                        'name': await name.text_content() if name else '',
                        'phone': await phone.text_content() if phone else '',
                        'address': await address.text_content() if address else '',
                        'website': await website.get_attribute('href') if website else '',
                        'city': city,
                        'state': state,
                        'source': 'paginas_amarelas'
                    })
                except:
                    continue

            await browser.close()
    except Exception as e:
        print(f"[PAGINAS_AMARELAS] Error: {e}")

    return results


# ============================================================
# METHOD 12: TRIPADVISOR (Playwright)
# ============================================================

async def scrape_tripadvisor(category, city, state):
    """
    Scrape TripAdvisor for restaurants, hotels, attractions
    Best for: hospitality, tourism, food service
    """
    from playwright.async_api import async_playwright
    import urllib.parse

    location_query = urllib.parse.quote(f"{city} {state}")
    url = f"https://www.tripadvisor.com.br/Search?q={location_query}&searchSessionId=&searchNearby=false&geo=&sid="

    results = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(3000)

            listings = await page.query_selector_all('.result-card, .listing')

            for listing in listings[:30]:
                try:
                    name = await listing.query_selector('.result-title, h3')
                    phone = await listing.query_selector('.phone')
                    address = await listing.query_selector('.address')
                    website = await listing.query_selector('a.website')

                    results.append({
                        'name': await name.text_content() if name else '',
                        'phone': await phone.text_content() if phone else '',
                        'address': await address.text_content() if address else '',
                        'website': await website.get_attribute('href') if website else '',
                        'city': city,
                        'state': state,
                        'source': 'tripadvisor'
                    })
                except:
                    continue

            await browser.close()
    except Exception as e:
        print(f"[TRIPADVISOR] Error: {e}")

    return results


# ============================================================
# METHOD 13: RECLAME AQUI (Playwright)
# ============================================================

async def scrape_reclame_aqui(query, city=None):
    """
    Scrape reclameaqui.com.br - Companies with complaints = active businesses
    """
    from playwright.async_api import async_playwright
    import urllib.parse

    query_encoded = urllib.parse.quote(query)
    url = f"https://www.reclameaqui.com.br/busca/?q={query_encoded}"

    results = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(2000)

            companies = await page.query_selector_all('.company-card, .empresa')

            for company in companies[:30]:
                try:
                    name = await company.query_selector('.company-name, h3')
                    rating = await company.query_selector('.rating, .nota')
                    complaints = await company.query_selector('.complaints-count')

                    # Get company detail page for website/phone
                    link = await company.query_selector('a')
                    if link:
                        href = await link.get_attribute('href')

                        results.append({
                            'name': await name.text_content() if name else '',
                            'rating': await rating.text_content() if rating else '',
                            'complaints_count': await complaints.text_content() if complaints else '',
                            'reclame_aqui_url': f"https://www.reclameaqui.com.br{href}" if href else '',
                            'city': city or '',
                            'source': 'reclame_aqui'
                        })
                except:
                    continue

            await browser.close()
    except Exception as e:
        print(f"[RECLAME_AQUI] Error: {e}")

    return results


# ============================================================
# METHOD 14: FACEBOOK PAGES SEARCH (Playwright)
# ============================================================

async def scrape_facebook_business_pages(query, city, state):
    """
    Scrape Facebook business pages search
    NOTE: Requires careful anti-detection measures
    """
    from playwright.async_api import async_playwright
    import urllib.parse

    query_full = urllib.parse.quote(f"{query} {city} {state}")
    url = f"https://www.facebook.com/pages/?q={query_full}&category=businesses"

    results = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()

            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(5000)  # Wait for JS render

            # Extract business info from search results
            # NOTE: Facebook structure changes frequently, selectors may need updates

            await browser.close()
    except Exception as e:
        print(f"[FACEBOOK] Error: {e}")

    return results


# ============================================================
# METHOD 15: GOOGLE MY BUSINESS via Outscraper API
# ============================================================

def search_gmb_outscraper(query, location, api_key=None):
    """
    Search Google My Business using Outscraper API
    FREE: 100 requests/month
    https://outscraper.com/
    """
    import requests

    if not api_key:
        return []

    url = "https://api.outscraper.com/maps/search-v3"
    headers = {
        "X-API-KEY": api_key
    }
    params = {
        "query": f"{query} {location}",
        "limit": 100,
        "language": "pt",
        "region": "BR"
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            results = []

            for item in data.get('data', []):
                results.append({
                    'name': item.get('name'),
                    'phone': item.get('phone'),
                    'website': item.get('site'),
                    'address': item.get('full_address'),
                    'rating': item.get('rating'),
                    'reviews_count': item.get('reviews'),
                    'category': item.get('category'),
                    'source': 'gmb_outscraper'
                })

            return results
    except Exception as e:
        print(f"[OUTSCRAPER] Error: {e}")
        return []


# ============================================================
# METHOD 16: CONSELHO DE CLASSE SCRAPERS
# ============================================================

async def scrape_crm_es(specialty=None):
    """
    Scrape CRM-ES (Conselho Regional de Medicina do ES)
    http://www.crmes.org.br/
    """
    from playwright.async_api import async_playwright

    url = "http://www.crmes.org.br/index.php?option=com_medicos"

    results = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(2000)

            # Extract registered doctors
            doctors = await page.query_selector_all('.medico-item, .profissional')

            for doctor in doctors[:100]:
                try:
                    name = await doctor.query_selector('.name, .nome')
                    crm = await doctor.query_selector('.crm, .registro')
                    specialty_el = await doctor.query_selector('.especialidade, .specialty')
                    phone = await doctor.query_selector('.phone, .telefone')

                    results.append({
                        'name': await name.text_content() if name else '',
                        'crm': await crm.text_content() if crm else '',
                        'specialty': await specialty_el.text_content() if specialty_el else '',
                        'phone': await phone.text_content() if phone else '',
                        'source': 'crm_es'
                    })
                except:
                    continue

            await browser.close()
    except Exception as e:
        print(f"[CRM_ES] Error: {e}")

    return results


# ============================================================
# INTEGRATION INSTRUCTIONS
# ============================================================

"""
To add these to the massive search endpoint:

1. Add methods parameter options in frontend:
   - 'yelp'
   - 'yellow_pages_br'
   - 'guia_mais'
   - 'apontador'
   - 'paginas_amarelas'
   - 'tripadvisor'
   - 'reclame_aqui'
   - 'facebook_pages'
   - 'gmb_outscraper'
   - 'crm_es'

2. Create background threads for each method in /api/search/massive

3. Store API keys in environment variables:
   - YELP_API_KEY
   - OUTSCRAPER_API_KEY

4. Update requirements.txt with playwright

5. Rate limits:
   - Yelp: 5000/day (very generous)
   - Outscraper: 100/month (free tier)
   - Playwright scrapers: 10/hour each (to avoid blocking)
"""
