#!/usr/bin/env python3
"""
import_receita_federal.py — Standalone script to import Receita Federal CNPJ open data
into the cnpj_rf PostgreSQL table.

Runs on the VPS (not inside Flask). No Flask imports.
Credentials: AWS SM extratordedados/prod (with .deploy.env fallback).

Usage:
    python import_receita_federal.py            # Full import
    python import_receita_federal.py --dry-run  # Parse first 1000 rows, no DB insert
    python import_receita_federal.py --help     # Show this help

Requirements:
    pip install requests psycopg2-binary boto3
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import zipfile
from datetime import datetime
from io import StringIO
from pathlib import Path

import requests
import psycopg2

# ─── Constants ────────────────────────────────────────────────────────────────

RF_MIRROR_BASE = "https://arquivos.receitafederal.gov.br/cnpj/dados_abertos_cnpj/"
BATCH_SIZE = 10_000
ONLY_ACTIVE = True          # Only import situacao_cadastral == '02' (ativa)
MIN_FREE_DISK_GB = 30       # Abort if less than this available
DOWNLOAD_DIR = "/tmp/rf_import"

# ─── Credential Loading ────────────────────────────────────────────────────────

def _load_credentials():
    """Load DB credentials from AWS SM (primary) or .deploy.env (fallback)."""
    # Try AWS SM first
    try:
        import boto3
        client = boto3.client('secretsmanager', region_name='us-east-1')
        resp = client.get_secret_value(SecretId='extratordedados/prod')
        secrets = json.loads(resp['SecretString'])
        return {
            'host': secrets.get('DB_HOST', 'localhost'),
            'port': int(secrets.get('DB_PORT', 5432)),
            'dbname': secrets.get('DB_NAME', 'extrator'),
            'user': secrets.get('DB_USER', 'extrator'),
            'password': secrets.get('DB_PASS', ''),
        }
    except Exception as e:
        print(f"[creds] AWS SM failed: {e} — trying .deploy.env fallback")

    # Fallback: .deploy.env in script directory or parent directories
    for candidate in [
        Path(__file__).parent.parent.parent / '.deploy.env',  # project root
        Path('/app/.deploy.env'),
        Path(os.environ.get('HOME', '/root')) / '.deploy.env',
    ]:
        if candidate.exists():
            env = {}
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
            if env.get('DB_PASS'):
                print(f"[creds] Using .deploy.env from {candidate}")
                return {
                    'host': env.get('DB_HOST', 'localhost'),
                    'port': int(env.get('DB_PORT', 5432)),
                    'dbname': env.get('DB_NAME', 'extrator'),
                    'user': env.get('DB_USER', 'extrator'),
                    'password': env.get('DB_PASS', ''),
                }

    raise RuntimeError(
        "No credentials found. Set AWS SM extratordedados/prod or create .deploy.env"
    )

# ─── Mirror Discovery ──────────────────────────────────────────────────────────

def _discover_latest_month():
    """
    Scrape the RF mirror index page to find the latest available month directory.
    Returns URL like 'https://.../2026-02/' on success, or a hardcoded fallback.
    """
    fallback = RF_MIRROR_BASE + "2026-02/"
    try:
        r = requests.get(RF_MIRROR_BASE, timeout=15,
                         headers={'User-Agent': 'Mozilla/5.0 (compatible; RF-Importer/1.0)'})
        if r.status_code != 200:
            print(f"[discover] Mirror returned {r.status_code} — using fallback {fallback}")
            return fallback
        # Look for links like 2025-12/, 2026-01/, 2026-02/
        months = re.findall(r'href="(\d{4}-\d{2}/)"', r.text)
        if months:
            latest = sorted(months)[-1]
            url = RF_MIRROR_BASE + latest
            print(f"[discover] Latest month: {url}")
            return url
    except Exception as e:
        print(f"[discover] Error: {e} — using fallback {fallback}")
    return fallback


def _discover_shards(base_url, prefix):
    """
    Discover shard files from the month index page.
    prefix: 'Estabelecimentos' or 'Empresas'
    Returns list of (filename, url) tuples.
    """
    try:
        r = requests.get(base_url, timeout=15,
                         headers={'User-Agent': 'Mozilla/5.0 (compatible; RF-Importer/1.0)'})
        if r.status_code == 200:
            # e.g. Estabelecimentos0.zip through Estabelecimentos9.zip
            files = re.findall(rf'href="({re.escape(prefix)}\d+\.zip)"', r.text)
            if files:
                return [(f, base_url + f) for f in sorted(set(files))]
    except Exception as e:
        print(f"[discover] Shard discovery error for {prefix}: {e}")
    # Fallback: assume 0-9 shards
    return [(f"{prefix}{i}.zip", base_url + f"{prefix}{i}.zip") for i in range(10)]

# ─── Download ─────────────────────────────────────────────────────────────────

def _download_file(url, dest_path, desc=""):
    """Download a file with progress reporting. Returns True on success."""
    print(f"[download] {desc or url} → {dest_path}")
    try:
        r = requests.get(url, stream=True, timeout=300,
                         headers={'User-Agent': 'Mozilla/5.0 (compatible; RF-Importer/1.0)'})
        if r.status_code == 404:
            print(f"[download] 404 — skipping {url}")
            return False
        r.raise_for_status()
        total = int(r.headers.get('content-length', 0))
        downloaded = 0
        with open(dest_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0 and downloaded % (50 * 1024 * 1024) < 1024 * 1024:
                    pct = 100 * downloaded // total
                    print(f"[download] {pct}% ({downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB)")
        size_mb = os.path.getsize(dest_path) / 1024 / 1024
        print(f"[download] Done: {size_mb:.1f}MB")
        return True
    except Exception as e:
        print(f"[download] Error: {e}")
        if os.path.exists(dest_path):
            os.remove(dest_path)
        return False

# ─── Empresas (razao_social, data_abertura, porte, matriz_filial) ─────────────

def _load_empresas_index(zip_path, dry_run=False, max_rows=None):
    """
    Load cnpj_basico → (razao_social, data_abertura, porte, matriz_filial) mapping
    from an Empresas ZIP file.
    Column mapping for EMPRESAS CSV:
        row[0]  cnpj_basico (8 digits)
        row[1]  razao_social
        row[2]  natureza_juridica
        row[3]  qualificacao_responsavel
        row[4]  capital_social
        row[5]  porte (1=não informado, 2=micro, 3=pequena, 5=demais)
        row[6]  ente_federativo
    NOTE: data_abertura is in the Estabelecimentos file, not Empresas.
          matriz_filial: '1' = matriz, '2' = filial (from Estabelecimentos row[3])
    """
    index = {}
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            csv_names = [n for n in zf.namelist() if n.upper().endswith('.CSV')]
            if not csv_names:
                print(f"[empresas] No CSV found in {zip_path}")
                return index
            csv_name = csv_names[0]
            print(f"[empresas] Loading index from {csv_name}")
            count = 0
            with zf.open(csv_name) as raw_f:
                import io
                text_f = io.TextIOWrapper(raw_f, encoding='latin-1', errors='replace')
                reader = csv.reader(text_f, delimiter=';')
                for row in reader:
                    if max_rows and count >= max_rows:
                        break
                    if len(row) < 6:
                        continue
                    cnpj_basico = row[0].strip().zfill(8)
                    razao_social = row[1].strip() or None
                    porte_str = row[5].strip()
                    porte = int(porte_str) if porte_str.isdigit() else None
                    index[cnpj_basico] = {
                        'razao_social': razao_social,
                        'porte': porte,
                    }
                    count += 1
            print(f"[empresas] Loaded {count:,} empresa records into index")
    except Exception as e:
        print(f"[empresas] Error loading {zip_path}: {e}")
    return index


# ─── Estabelecimentos Import ───────────────────────────────────────────────────

def _import_estabelecimentos(zip_path, conn, empresas_index, dry_run=False, max_rows=None):
    """
    Parse an Estabelecimentos ZIP and insert into cnpj_rf.
    Column mapping (validate against metadata PDF before first run):
        row[0]  cnpj_basico (8 digits)
        row[1]  cnpj_ordem (4 digits)
        row[2]  cnpj_dv (2 digits)
        row[3]  identificador_matriz_filial (1=matriz, 2=filial)
        row[4]  nome_fantasia
        row[5]  situacao_cadastral (01=nula,02=ativa,03=suspensa,04=inapta,08=baixada)
        row[6]  data_situacao_cadastral
        row[7]  motivo_situacao_cadastral
        row[8]  nome_cidade_exterior
        row[9]  pais
        row[10] data_inicio_atividade
        row[11] cnae_fiscal_principal
        row[12] cnae_fiscal_secundaria
        row[13] tipo_logradouro
        row[14] logradouro
        row[15] numero
        row[16] complemento
        row[17] bairro
        row[18] cep
        row[19] uf (sigla 2 chars)
        row[20] municipio (codigo RF integer)
        row[21] ddd_1
        row[22] telefone_1
        row[23] ddd_2
        row[24] telefone_2
        row[25] ddd_fax
        row[26] fax
        row[27] correio_eletronico (email)
        row[28] situacao_especial
        row[29] data_situacao_especial
    """
    total = 0
    inserted = 0
    skipped = 0

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            csv_names = [n for n in zf.namelist() if n.upper().endswith('.CSV')]
            if not csv_names:
                print(f"[import] No CSV in {zip_path}")
                return total, inserted

            csv_name = csv_names[0]
            print(f"[import] Processing {csv_name} from {os.path.basename(zip_path)}")

            batch = []
            c = conn.cursor() if not dry_run else None
            import io

            with zf.open(csv_name) as raw_f:
                text_f = io.TextIOWrapper(raw_f, encoding='latin-1', errors='replace')
                reader = csv.reader(text_f, delimiter=';')
                for row in reader:
                    if max_rows and total >= max_rows:
                        break
                    if len(row) < 23:
                        skipped += 1
                        continue

                    total += 1

                    # Filter: only active (situacao_cadastral == '02')
                    situacao_raw = row[5].strip()
                    if ONLY_ACTIVE and situacao_raw != '02':
                        skipped += 1
                        continue

                    # Build CNPJ (14 digits)
                    cnpj_basico = row[0].strip().zfill(8)
                    cnpj_ordem = row[1].strip().zfill(4)
                    cnpj_dv = row[2].strip().zfill(2)
                    cnpj = cnpj_basico + cnpj_ordem + cnpj_dv

                    # situacao int
                    situacao_map = {'01': 0, '02': 2, '03': 3, '04': 4, '08': 8}
                    situacao = situacao_map.get(situacao_raw, 0)

                    # Get razao_social + porte from empresas_index
                    emp = empresas_index.get(cnpj_basico, {})
                    razao_social = emp.get('razao_social')
                    porte = emp.get('porte')

                    # Fields from Estabelecimentos
                    nome_fantasia = row[4].strip() or None
                    cnae_principal = row[11].strip() or None
                    logradouro = (row[13].strip() + ' ' + row[14].strip()).strip() or None
                    numero = row[15].strip() or None
                    complemento = row[16].strip() or None
                    bairro = row[17].strip() or None
                    cep = re.sub(r'[^0-9]', '', row[18].strip())[:8] or None
                    uf = row[19].strip()[:2] or None
                    municipio_str = row[20].strip()
                    municipio_cod = int(municipio_str) if municipio_str.isdigit() else None
                    ddd1 = row[21].strip()[:3] or None
                    telefone1 = row[22].strip()[:9] or None
                    ddd2 = row[23].strip()[:3] if len(row) > 23 else None
                    telefone2 = row[24].strip()[:9] if len(row) > 24 else None
                    email = row[27].strip().lower() or None if len(row) > 27 else None
                    data_abertura_str = row[10].strip() if len(row) > 10 else ''
                    data_abertura = None
                    if data_abertura_str and len(data_abertura_str) == 8 and data_abertura_str.isdigit():
                        try:
                            data_abertura = datetime.strptime(data_abertura_str, '%Y%m%d').date()
                        except Exception:
                            pass
                    matriz_filial_str = row[3].strip()
                    matriz_filial = int(matriz_filial_str) if matriz_filial_str.isdigit() else None

                    if dry_run:
                        if total <= 5:
                            print(f"  CNPJ={cnpj} | razao={razao_social} | fantasia={nome_fantasia} "
                                  f"| sit={situacao} | uf={uf} | email={email}")
                        inserted += 1
                        continue

                    batch.append((
                        cnpj, razao_social, nome_fantasia, situacao, cnae_principal,
                        logradouro, numero, complemento, bairro, cep, municipio_cod,
                        uf, ddd1, telefone1, ddd2, telefone2, email, data_abertura,
                        porte, matriz_filial
                    ))

                    if len(batch) >= BATCH_SIZE:
                        c.executemany(
                            '''INSERT INTO cnpj_rf (
                                cnpj, razao_social, nome_fantasia, situacao, cnae_principal,
                                logradouro, numero, complemento, bairro, cep, municipio_cod,
                                uf, ddd1, telefone1, ddd2, telefone2, email, data_abertura,
                                porte, matriz_filial
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (cnpj) DO NOTHING''',
                            batch
                        )
                        conn.commit()
                        inserted += len(batch)
                        batch = []

                    if total % 100_000 == 0:
                        print(f"[import] {total:,} linhas processadas, {inserted:,} inseridas...")

            # Flush remaining batch
            if batch and not dry_run:
                c.executemany(
                    '''INSERT INTO cnpj_rf (
                        cnpj, razao_social, nome_fantasia, situacao, cnae_principal,
                        logradouro, numero, complemento, bairro, cep, municipio_cod,
                        uf, ddd1, telefone1, ddd2, telefone2, email, data_abertura,
                        porte, matriz_filial
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (cnpj) DO NOTHING''',
                    batch
                )
                conn.commit()
                inserted += len(batch)

    except Exception as e:
        print(f"[import] Error processing {zip_path}: {e}")
        if not dry_run:
            try:
                conn.rollback()
            except Exception:
                pass

    print(f"[import] {os.path.basename(zip_path)}: {total:,} total, {inserted:,} inserted, {skipped:,} skipped")
    return total, inserted


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Import Receita Federal CNPJ open data into cnpj_rf table.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Parse first 1000 rows and print sample data without inserting into DB.'
    )
    args = parser.parse_args()

    start_time = time.time()
    print(f"[main] RF Import started at {datetime.utcnow().isoformat()}Z")
    print(f"[main] Mode: {'DRY-RUN (no DB write)' if args.dry_run else 'FULL IMPORT'}")

    # ── Disk check ──
    free_bytes = shutil.disk_usage('/').free if os.name != 'nt' else shutil.disk_usage('C:\\').free
    free_gb = free_bytes / 1024 ** 3
    print(f"[main] Free disk: {free_gb:.1f}GB")
    if not args.dry_run and free_gb < MIN_FREE_DISK_GB:
        print(f"[main] ERROR: Need at least {MIN_FREE_DISK_GB}GB free, only {free_gb:.1f}GB available. Aborting.")
        sys.exit(1)

    # ── Credentials + DB connection ──
    conn = None
    if not args.dry_run:
        creds = _load_credentials()
        print(f"[main] Connecting to DB: {creds['host']}:{creds['port']}/{creds['dbname']}")
        conn = psycopg2.connect(**creds)
        conn.autocommit = False
        print("[main] DB connected.")

    # ── Discover latest month ──
    base_url = _discover_latest_month()
    print(f"[main] Using mirror: {base_url}")

    # ── Create download directory ──
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # ── Download and load Empresas index first ──
    empresas_index = {}
    empresas_shards = _discover_shards(base_url, 'Empresas')
    print(f"[main] Found {len(empresas_shards)} Empresas shard(s)")

    if args.dry_run:
        print("[dry-run] Skipping Empresas download for dry-run")
    else:
        for fname, url in empresas_shards:
            zip_path = os.path.join(DOWNLOAD_DIR, fname)
            if not os.path.exists(zip_path):
                ok = _download_file(url, zip_path, desc=fname)
                if not ok:
                    print(f"[main] Skipping unavailable shard: {fname}")
                    continue
            shard_index = _load_empresas_index(zip_path)
            empresas_index.update(shard_index)
            # Delete ZIP after parse to recover disk space
            os.remove(zip_path)
            print(f"[main] Deleted {zip_path}")

    print(f"[main] Empresas index loaded: {len(empresas_index):,} entries")

    # ── Download and import Estabelecimentos shards ──
    estab_shards = _discover_shards(base_url, 'Estabelecimentos')
    print(f"[main] Found {len(estab_shards)} Estabelecimentos shard(s)")

    total_rows = 0
    total_inserted = 0
    max_rows_dry = 1000 if args.dry_run else None

    for fname, url in estab_shards:
        zip_path = os.path.join(DOWNLOAD_DIR, fname)

        if not args.dry_run:
            if not os.path.exists(zip_path):
                ok = _download_file(url, zip_path, desc=fname)
                if not ok:
                    print(f"[main] Skipping unavailable shard: {fname}")
                    continue
        else:
            # Dry-run: download first shard only
            if total_rows == 0 and not os.path.exists(zip_path):
                print(f"[dry-run] Downloading first shard for validation: {fname}")
                ok = _download_file(url, zip_path, desc=fname)
                if not ok:
                    print("[dry-run] Could not download shard — skipping file validation")
                    print("[dry-run] Dry-run complete (no file available)")
                    break
            elif total_rows > 0:
                break  # Only process first shard in dry-run

        rows, ins = _import_estabelecimentos(
            zip_path, conn, empresas_index,
            dry_run=args.dry_run,
            max_rows=max_rows_dry
        )
        total_rows += rows
        total_inserted += ins

        # Delete ZIP after successful parse
        if not args.dry_run and os.path.exists(zip_path):
            os.remove(zip_path)
            print(f"[main] Deleted {zip_path}")

        if args.dry_run:
            break  # Only first shard in dry-run

    # ── Final report ──
    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"[main] Import complete!")
    print(f"[main] Total rows processed: {total_rows:,}")
    print(f"[main] Total inserted: {total_inserted:,}")
    print(f"[main] Elapsed: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    if args.dry_run:
        print("[main] DRY-RUN: no data was written to the database.")
    print(f"{'='*60}\n")

    if conn:
        conn.close()


if __name__ == '__main__':
    main()
