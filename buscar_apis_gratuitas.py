#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Buscar e testar APIs GRATUITAS de email finder
"""

import sys
import io
import requests
import json

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("="*80)
print("🔍 BUSCANDO APIs GRATUITAS DE EMAIL FINDER")
print("="*80)
print()

# ============================================================
# LISTA DE APIs GRATUITAS CONHECIDAS
# ============================================================

apis_gratuitas = [
    {
        "nome": "EmailRep.io",
        "url": "https://emailrep.io/",
        "endpoint": "https://emailrep.io/{email}",
        "free_tier": "Unlimited (sem auth)",
        "features": "Reputação de email, validação"
    },
    {
        "nome": "Hunter.io Free",
        "url": "https://hunter.io",
        "endpoint": "https://api.hunter.io/v2/email-finder",
        "free_tier": "25 searches/month",
        "features": "Email finder + verification"
    },
    {
        "nome": "Snov.io Free",
        "url": "https://snov.io",
        "endpoint": "https://api.snov.io/v1/get-emails-from-url",
        "free_tier": "50 credits/month",
        "features": "Email extractor + finder"
    },
    {
        "nome": "Apollo.io Free",
        "url": "https://apollo.io",
        "endpoint": "https://api.apollo.io/v1/people/match",
        "free_tier": "50 emails/month",
        "features": "Email finder + enrichment"
    },
    {
        "nome": "VoilaNorbert Free",
        "url": "https://www.voilanorbert.com",
        "endpoint": "https://api.voilanorbert.com/2018-01-08/search/name",
        "free_tier": "50 leads/month",
        "features": "Email finder por nome+empresa"
    },
    {
        "nome": "Clearbit Free",
        "url": "https://clearbit.com",
        "endpoint": "https://person.clearbit.com/v2/people/find",
        "free_tier": "Limited (requer API key)",
        "features": "Enrichment + email"
    },
    {
        "nome": "Proxycurl Free",
        "url": "https://nubela.co/proxycurl",
        "endpoint": "https://nubela.co/proxycurl/api/linkedin/company",
        "free_tier": "$0 tier available",
        "features": "LinkedIn data + emails"
    },
    {
        "nome": "PDL (People Data Labs) Free",
        "url": "https://www.peopledatalabs.com",
        "endpoint": "https://api.peopledatalabs.com/v5/person/enrich",
        "free_tier": "1000 credits/month",
        "features": "Email enrichment"
    },
    {
        "nome": "RocketReach Free",
        "url": "https://rocketreach.co",
        "endpoint": "https://api.rocketreach.co/v2/api/search",
        "free_tier": "5 lookups/month",
        "features": "Email + phone finder"
    },
    {
        "nome": "FindThatLead Free",
        "url": "https://findthatlead.com",
        "endpoint": "https://api.findthatlead.com/v1/search",
        "free_tier": "50 emails/month",
        "features": "Email finder"
    }
]

print("📋 LISTA DE APIs GRATUITAS DISPONÍVEIS:")
print()

for i, api in enumerate(apis_gratuitas, 1):
    print(f"{i}. {api['nome']}")
    print(f"   🌐 URL: {api['url']}")
    print(f"   🆓 Free Tier: {api['free_tier']}")
    print(f"   ✨ Features: {api['features']}")
    print()

print("="*80)
print()

# ============================================================
# APIFY ACTORS GRATUITOS
# ============================================================

print("="*80)
print("🎭 APIFY ACTORS GRATUITOS PARA EMAIL EXTRACTION")
print("="*80)
print()

apify_actors = [
    {
        "nome": "Email Extractor",
        "id": "junglee/email-extractor",
        "free": "Yes (free tier)",
        "features": "Extract emails from any webpage"
    },
    {
        "nome": "Google Maps Scraper",
        "id": "nwua9Gu5YrADL7ZDj",
        "free": "Yes (with limits)",
        "features": "Extract business data + emails from Google Maps"
    },
    {
        "nome": "Website Contact Scraper",
        "id": "lukaskrivka/website-contact-scraper",
        "free": "Yes",
        "features": "Extract emails, phones, social media"
    },
    {
        "nome": "Yellow Pages Scraper",
        "id": "dtrungtin/yellow-pages-scraper",
        "free": "Yes",
        "features": "Scrape business listings with contact info"
    },
    {
        "nome": "Bing Search Scraper",
        "id": "apify/bing-search-scraper",
        "free": "Yes",
        "features": "Search results from Bing"
    },
    {
        "nome": "DuckDuckGo Search",
        "id": "apify/duckduckgo-search",
        "free": "Yes",
        "features": "Search results from DuckDuckGo"
    },
    {
        "nome": "Instagram Profile Scraper",
        "id": "apify/instagram-profile-scraper",
        "free": "Yes (limited)",
        "features": "Extract business profiles + bio links"
    },
    {
        "nome": "LinkedIn Companies Scraper",
        "id": "bebity/linkedin-company-info-scraper",
        "free": "Yes",
        "features": "Company data + website"
    }
]

print("📋 LISTA DE APIFY ACTORS:")
print()

for i, actor in enumerate(apify_actors, 1):
    print(f"{i}. {actor['nome']}")
    print(f"   🎭 ID: {actor['id']}")
    print(f"   🆓 Free: {actor['free']}")
    print(f"   ✨ Features: {actor['features']}")
    print()

print("="*80)
print()

# ============================================================
# FERRAMENTAS OPEN SOURCE
# ============================================================

print("="*80)
print("🔓 FERRAMENTAS OPEN SOURCE (100% GRÁTIS)")
print("="*80)
print()

ferramentas_oss = [
    {
        "nome": "theHarvester",
        "url": "https://github.com/laramies/theHarvester",
        "features": "Email harvesting from search engines, PGP key servers"
    },
    {
        "nome": "EmailHarvester",
        "url": "https://github.com/maldevel/EmailHarvester",
        "features": "Search emails from Google, Bing"
    },
    {
        "nome": "h8mail",
        "url": "https://github.com/khast3x/h8mail",
        "features": "Email OSINT + breach checking"
    },
    {
        "nome": "Photon",
        "url": "https://github.com/s0md3v/Photon",
        "features": "Web crawler + email extraction"
    },
    {
        "nome": "ReconDog",
        "url": "https://github.com/s0md3v/ReconDog",
        "features": "Email search + reconnaissance"
    }
]

print("📋 FERRAMENTAS OPEN SOURCE:")
print()

for i, tool in enumerate(ferramentas_oss, 1):
    print(f"{i}. {tool['nome']}")
    print(f"   🔗 GitHub: {tool['url']}")
    print(f"   ✨ Features: {tool['features']}")
    print()

print("="*80)
print()

# ============================================================
# RECOMENDAÇÕES
# ============================================================

print("="*80)
print("💡 RECOMENDAÇÕES")
print("="*80)
print()
print("✅ PRIORIDADE 1 - APIs com Free Tier Generoso:")
print("   1. Apollo.io (50 emails/month)")
print("   2. PDL - People Data Labs (1000 credits/month)")
print("   3. FindThatLead (50 emails/month)")
print()
print("✅ PRIORIDADE 2 - Apify Actors (já temos integração):")
print("   1. Email Extractor (junglee/email-extractor)")
print("   2. Website Contact Scraper (lukaskrivka/website-contact-scraper)")
print()
print("✅ PRIORIDADE 3 - Ferramentas OSS (100% grátis):")
print("   1. theHarvester (muito popular, bem mantido)")
print("   2. Photon (crawler rápido)")
print()
print("="*80)
print()
print("🚀 PRÓXIMOS PASSOS:")
print("   1. Testar Apollo.io e PDL (melhores free tiers)")
print("   2. Executar Apify actors gratuitos")
print("   3. Instalar theHarvester localmente")
print()
