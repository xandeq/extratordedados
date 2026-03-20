#!/usr/bin/env python3
"""
scraping_apify_massive.py - Script de Scraping Massivo com Apify
Alimenta a tabela leads com dados qualificados via Google Maps
Custo: ~$20 USD para scraping de 1000+ leads

Uso:
    python scraping_apify_massive.py --niches "Clínica Médica,Imobiliária" --region "grande_vitoria_es" --max-results 100

Pré-requisitos:
    - Apify API key em AWS Secrets Manager (tools/apify)
    - PostgreSQL rodando
    - psycopg2 instalado
"""

import os
import sys
import json
import time
import argparse
import requests
import psycopg2
from datetime import datetime
from typing import List, Dict, Any
from urllib.parse import urljoin
import subprocess

# ════════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO
# ════════════════════════════════════════════════════════════════════════════════

# Regiões pré-configuradas
REGIONS = {
    'grande_vitoria_es': {
        'cities': ['Vitória', 'Vila Velha', 'Serra', 'Cariacica', 'Viana', 'Guarapari', 'Fundão'],
        'state': 'ES'
    },
    'grande_sp': {
        'cities': ['São Paulo', 'Guarulhos', 'Campinas', 'Santo André', 'São Bernardo do Campo'],
        'state': 'SP'
    },
    'grande_rj': {
        'cities': ['Rio de Janeiro', 'Niterói', 'Duque de Caxias', 'Nova Iguaçu'],
        'state': 'RJ'
    },
    'grande_bh': {
        'cities': ['Belo Horizonte', 'Contagem', 'Betim', 'Sete Lagoas'],
        'state': 'MG'
    }
}


def get_apify_key() -> str:
    """Busca Apify key do AWS Secrets Manager"""
    try:
        result = subprocess.run(
            ['python', '-m', 'awscli', 'secretsmanager', 'get-secret-value',
             '--secret-id', 'tools/apify', '--query', 'SecretString', '--output', 'text'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get('FAL_KEY') or data.get('APIFY_API_KEY')
    except Exception as e:
        print(f'❌ Error fetching Apify key: {e}')

    # Fallback: tentar variável de ambiente
    return os.environ.get('APIFY_API_KEY', '')


def get_db_connection() -> psycopg2.extensions.connection:
    """Cria conexão com PostgreSQL"""
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            port=os.environ.get('DB_PORT', 5432),
            database=os.environ.get('DB_NAME', 'extrator'),
            user=os.environ.get('DB_USER', 'extrator'),
            password=os.environ.get('DB_PASSWORD', ''),
            connect_timeout=10
        )
        return conn
    except Exception as e:
        print(f'❌ Database connection error: {e}')
        raise


# ════════════════════════════════════════════════════════════════════════════════
# ORQUESTRADOR APIFY
# ════════════════════════════════════════════════════════════════════════════════

def run_apify_google_maps(niche: str, city: str, state: str, max_results: int = 50) -> List[Dict]:
    """
    Executa Apify Actor para scraping de Google Maps

    Actor: lukaskrivka~google-maps-with-contact-details
    Retorna: lista de leads com nome, endereço, telefone, website, coordenadas
    """
    apify_key = get_apify_key()
    if not apify_key:
        print('❌ Apify key não configurada')
        return []

    print(f'\n🔍 Scrapando Google Maps: {niche} em {city}, {state}...')

    # Input para o Actor
    actor_input = {
        'searchStringsArray': [f'{niche} em {city}'],
        'includeWebsites': True,
        'includeReviews': False,
        'maxPostsPerSearch': max_results,
        'maxReviewsPerPlace': 0,
        'maxImageCount': 0,
        'startUrls': []  # Deixa vazio para usar searchStrings
    }

    try:
        # 1. Criar run do Actor
        run_response = requests.post(
            'https://api.apify.com/v2/acts/lukaskrivka~google-maps-with-contact-details/runs',
            json={'input': actor_input},
            headers={'Authorization': f'Bearer {apify_key}'},
            timeout=30
        )

        if run_response.status_code != 201:
            print(f'❌ Apify run creation failed: {run_response.text}')
            return []

        run_data = run_response.json()['data']
        run_id = run_data['id']
        dataset_id = run_data.get('defaultDatasetId')

        print(f'✅ Run iniciado: {run_id}')

        # 2. Aguardar conclusão
        max_wait = 300  # 5 minutos
        start_time = time.time()

        while time.time() - start_time < max_wait:
            run_status = requests.get(
                f'https://api.apify.com/v2/acts/lukaskrivka~google-maps-with-contact-details/runs/{run_id}',
                headers={'Authorization': f'Bearer {apify_key}'},
                timeout=10
            )

            status = run_status.json()['data']['status']
            print(f'  Status: {status}')

            if status == 'SUCCEEDED':
                print(f'✅ Run concluído com sucesso')
                break
            elif status == 'FAILED':
                print(f'❌ Run falhou')
                return []

            time.sleep(5)

        # 3. Buscar resultados
        if not dataset_id:
            dataset_id = run_status.json()['data'].get('defaultDatasetId')

        results_response = requests.get(
            f'https://api.apify.com/v2/datasets/{dataset_id}/items',
            headers={'Authorization': f'Bearer {apify_key}'},
            timeout=30
        )

        if results_response.status_code != 200:
            print(f'❌ Failed to fetch results')
            return []

        items = results_response.json()

        # 4. Transformar resultados em leads
        leads = []
        for item in items:
            lead = {
                'company_name': item.get('title', '').strip(),
                'phone': item.get('phoneNumber', '').strip(),
                'website': item.get('website', '').strip(),
                'address': item.get('address', '').strip(),
                'city': city,
                'state': state,
                'niche': niche,
                'latitude': item.get('location', {}).get('lat'),
                'longitude': item.get('location', {}).get('lng'),
                'source': 'apify_google_maps',
                'source_url': item.get('url', ''),
                'data_sources': ['google_maps', 'apify'],
                'extracted_at': datetime.now()
            }

            # Filtra leads vazios
            if lead['company_name'] and (lead['phone'] or lead['website']):
                leads.append(lead)

        print(f'✅ {len(leads)} leads extraídos')
        return leads

    except Exception as e:
        print(f'❌ Apify error: {str(e)}')
        return []


# ════════════════════════════════════════════════════════════════════════════════
# INSERÇÃO NO BANCO
# ════════════════════════════════════════════════════════════════════════════════

def insert_leads_batch(leads: List[Dict], conn: psycopg2.extensions.connection) -> int:
    """
    Insere batch de leads no banco (upsert by email or company_slug)
    Retorna número de leads inseridos/atualizados
    """
    if not leads:
        return 0

    cursor = conn.cursor()
    inserted_count = 0

    for lead in leads:
        try:
            # Busca se já existe
            cursor.execute(
                'SELECT id FROM leads WHERE company_slug = %s OR (email = %s AND email IS NOT NULL)',
                (lead.get('company_slug'), lead.get('email'))
            )

            existing = cursor.fetchone()

            if existing:
                # Update
                cursor.execute(
                    '''UPDATE leads SET
                        company_name = COALESCE(%s, company_name),
                        phone = COALESCE(%s, phone),
                        website = COALESCE(%s, website),
                        address = COALESCE(%s, address),
                        city = COALESCE(%s, city),
                        state = COALESCE(%s, state),
                        niche = COALESCE(%s, niche),
                        latitude = COALESCE(%s, latitude),
                        longitude = COALESCE(%s, longitude),
                        source = %s,
                        source_url = COALESCE(%s, source_url),
                        data_sources = %s,
                        last_verified_at = NOW()
                    WHERE id = %s''',
                    (lead.get('company_name'), lead.get('phone'), lead.get('website'),
                     lead.get('address'), lead.get('city'), lead.get('state'),
                     lead.get('niche'), lead.get('latitude'), lead.get('longitude'),
                     lead.get('source'), lead.get('source_url'),
                     json.dumps(lead.get('data_sources', [])),
                     existing[0])
                )
            else:
                # Insert
                cursor.execute(
                    '''INSERT INTO leads
                    (company_name, phone, website, address, city, state, niche,
                     latitude, longitude, source, source_url, data_sources,
                     extracted_at, company_slug)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                    (lead.get('company_name'), lead.get('phone'), lead.get('website'),
                     lead.get('address'), lead.get('city'), lead.get('state'),
                     lead.get('niche'), lead.get('latitude'), lead.get('longitude'),
                     lead.get('source'), lead.get('source_url'),
                     json.dumps(lead.get('data_sources', [])),
                     lead.get('extracted_at'), lead.get('company_slug'))
                )

            inserted_count += 1

        except psycopg2.IntegrityError as e:
            conn.rollback()
            print(f'  ⚠️  Duplicate or constraint error: {str(e)}')
        except Exception as e:
            conn.rollback()
            print(f'  ❌ Error inserting lead: {str(e)}')

    conn.commit()
    cursor.close()

    return inserted_count


# ════════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Scraping massivo com Apify para alimentar banco de leads'
    )
    parser.add_argument('--niches', type=str, default='Clínica Médica,Imobiliária',
                        help='Nichos separados por vírgula')
    parser.add_argument('--region', type=str, default='grande_vitoria_es',
                        help=f'Região: {", ".join(REGIONS.keys())}')
    parser.add_argument('--max-results', type=int, default=100,
                        help='Máximo de resultados por niche/city')
    parser.add_argument('--skip-enrichment', action='store_true',
                        help='Não rodar enriquecimento (BrasilAPI, Nominatim)')

    args = parser.parse_args()

    niches = [n.strip() for n in args.niches.split(',')]
    region_key = args.region

    if region_key not in REGIONS:
        print(f'❌ Region {region_key} not found. Available: {", ".join(REGIONS.keys())}')
        sys.exit(1)

    region_data = REGIONS[region_key]
    cities = region_data['cities']
    state = region_data['state']

    print(f'''
    ╔═══════════════════════════════════════════════════════════════════╗
    ║         SCRAPING MASSIVO - APIFY GOOGLE MAPS                     ║
    ║         Custo estimado: $20 USD para 1000+ leads                 ║
    ╚═══════════════════════════════════════════════════════════════════╝

    📊 Configuração:
       Nichos: {', '.join(niches)}
       Região: {region_key} ({state})
       Cidades: {', '.join(cities)}
       Max resultados/niche/city: {args.max_results}

    ⚠️  Este script vai:
       1. Fazer requisições ao Apify (custo)
       2. Scrapear Google Maps
       3. Inserir dados no PostgreSQL

    Pressione ENTER para continuar ou CTRL+C para cancelar...
    ''')

    input()

    # Conectar ao banco
    try:
        conn = get_db_connection()
        print('✅ Conectado ao PostgreSQL')
    except Exception as e:
        print(f'❌ Erro ao conectar: {e}')
        sys.exit(1)

    # Estatísticas globais
    total_leads_scraped = 0
    total_leads_inserted = 0
    total_cost_usd = 0

    # Iterar por nicho e cidade
    for niche in niches:
        for city in cities:
            try:
                # Scraping
                leads = run_apify_google_maps(niche, city, state, args.max_results)
                total_leads_scraped += len(leads)

                # Enriquecimento (opcional)
                if not args.skip_enrichment and leads:
                    print(f'  🔧 Enriquecendo {len(leads)} leads...')
                    # Importar função de enriquecimento
                    try:
                        from lead_enrichment import enrich_lead_comprehensive
                        for i, lead in enumerate(leads):
                            leads[i] = enrich_lead_comprehensive(lead)
                            if (i + 1) % 10 == 0:
                                print(f'    {i + 1}/{len(leads)} enriquecidos')
                    except ImportError:
                        print('    ⚠️  lead_enrichment.py não encontrado, pulando enriquecimento')

                # Inserção
                inserted = insert_leads_batch(leads, conn)
                total_leads_inserted += inserted

                print(f'✅ {inserted}/{len(leads)} leads inseridos\n')

                # Custo estimado (Apify: $5-10 por 1000 requests)
                # Aqui usamos ~0.01 USD por lead extraído
                batch_cost = len(leads) * 0.01
                total_cost_usd += batch_cost

                # Rate limiting (Apify: 10 req/min)
                time.sleep(6)

            except KeyboardInterrupt:
                print('\n⚠️  Interrompido pelo usuário')
                break
            except Exception as e:
                print(f'❌ Erro em {niche}/{city}: {str(e)}')
                continue

    # Fechaar conexão
    conn.close()

    print(f'''
    ╔═══════════════════════════════════════════════════════════════════╗
    ║                      RESUMO FINAL                                 ║
    ╚═══════════════════════════════════════════════════════════════════╝

    📊 Resultados:
       Total scrapado: {total_leads_scraped}
       Total inserido: {total_leads_inserted}
       Taxa sucesso: {(total_leads_inserted/total_leads_scraped*100):.1f}% se total_leads_scraped > 0 else '—'

    💰 Custo estimado: ${total_cost_usd:.2f} USD

    ✅ Banco atualizado com sucesso!
    ''')


if __name__ == '__main__':
    main()
