# Receita Federal CNPJ Import — Operator Runbook

This document describes how to import the Receita Federal open CNPJ dataset into the `cnpj_rf`
PostgreSQL table on the VPS. The dataset contains 60M+ companies and is updated monthly.

---

## 1. Prerequisites

### Disk Space
The Estabelecimentos data (~10 shards) unpacks to roughly 25-30GB. Ensure the VPS has at least
**30GB free** before starting. The script checks this automatically and aborts if insufficient.

```bash
df -h /
```

### Python Packages (on VPS)
```bash
pip install requests psycopg2-binary boto3
```

### Database
The `cnpj_rf` table is created automatically by `init_db()` when the Flask app starts.
Verify it exists before running the import:

```sql
-- Run in psql or via python
SELECT COUNT(*) FROM cnpj_rf;
-- Should return (0,) for a fresh table
```

---

## 2. Upload Script to VPS

From your local machine (inside the project root):

```bash
scp scripts/import/import_receita_federal.py root@185.173.110.180:/tmp/
```

Or copy the content manually if SCP is not available.

---

## 3. Dry-Run Validation

Before running the full import, always do a dry-run to validate column indexes against
the actual CSV structure (Receita Federal changes column order between releases).

```bash
ssh root@185.173.110.180
python /tmp/import_receita_federal.py --dry-run
```

**Expected output:**
```
[main] RF Import started at 2026-02-01T12:00:00Z
[main] Mode: DRY-RUN (no DB write)
[main] Free disk: 45.2GB
[main] Using mirror: https://arquivos.receitafederal.gov.br/cnpj/dados_abertos_cnpj/2026-02/
[main] Found 10 Estabelecimentos shard(s)
[dry-run] Downloading first shard for validation: Estabelecimentos0.zip
[import] Processing K3241.720_Estabelecimentos0.csv from Estabelecimentos0.zip
  CNPJ=00000000000191 | razao=BANCO DO BRASIL SA | fantasia=BB | sit=2 | uf=DF | email=...
  ...5 sample rows...
[main] Total rows processed: 1,000
[main] DRY-RUN: no data was written to the database.
```

If the column mapping is wrong (fields appear in wrong positions), update the column indices
in `_import_estabelecimentos()` before the full run. The comment block at the top of that
function documents the expected column order.

---

## 4. Full Run (with nohup)

The full import takes 30-90 minutes depending on VPS I/O speed.
Use `nohup` to keep it running if your SSH session disconnects.

```bash
ssh root@185.173.110.180
nohup python /tmp/import_receita_federal.py > /tmp/rf_import.log 2>&1 &
echo "PID: $!"
```

Monitor progress:
```bash
tail -f /tmp/rf_import.log
```

Check if still running:
```bash
ps aux | grep import_receita_federal
```

---

## 5. Verification SQL

After the import completes, verify the data looks correct:

```sql
-- Connect to the database
docker exec -it extrator-postgres psql -U extrator -d extrator

-- Row count by state (top 10)
SELECT COUNT(*), uf FROM cnpj_rf GROUP BY uf ORDER BY COUNT(*) DESC LIMIT 10;

-- Expected output (approximate):
--  count   | uf
-- ---------+----
--  3500000 | SP
--  2100000 | MG
--  1800000 | RJ
--  1200000 | RS
--  ...

-- Sample active records
SELECT cnpj, razao_social, uf, email FROM cnpj_rf WHERE uf = 'ES' LIMIT 5;

-- Total count
SELECT COUNT(*) FROM cnpj_rf;
-- Expected: 40-60M rows (only active companies if ONLY_ACTIVE=True)
```

---

## 6. Monthly Update Procedure

The Receita Federal releases a new dataset monthly (usually around the 5th-10th of each month).

To update:

1. Upload the latest version of the script (column indexes may change):
   ```bash
   scp scripts/import/import_receita_federal.py root@185.173.110.180:/tmp/
   ```

2. Run dry-run to validate:
   ```bash
   python /tmp/import_receita_federal.py --dry-run
   ```

3. Run full import with nohup — uses `ON CONFLICT (cnpj) DO NOTHING` so safe to re-run:
   ```bash
   nohup python /tmp/import_receita_federal.py > /tmp/rf_import_$(date +%Y%m).log 2>&1 &
   ```

4. Verify row count increased (or stayed the same for same-month re-run).

---

## 7. Minha Receita (Optional — Level 2 Fallback)

Minha Receita is an open-source tool by @cuducos that serves the Receita Federal data via a local
REST API on port 3000. When deployed, it provides HTTP-based CNPJ lookups with all 47 RF fields.

> **Level placement**: `enrich_cnpj_with_fallback()` already calls `http://localhost:3000/{cnpj}`
> as Level 2 — no code change needed. It silently skips if the container is not running.

### 7.1 Prerequisites Check

```bash
# Check available disk — Minha Receita downloads the same RF dataset (~15-25 GB)
df -h /

# Ensure Docker is installed
docker --version
```

> **Warning — Double Download**: If `cnpj_rf` table is already populated from Step 4 above,
> deploying Minha Receita will require downloading the same RF dataset again (~15-25 GB).
> This doubles disk usage. If disk space is tight (< 30 GB free after the import), skip this
> section — Level 1 (SQL lookup in `cnpj_rf`) already provides < 10ms enrichment without overhead.

### 7.2 Create docker-compose.yml on VPS

SSH into the VPS and create the following file at `/opt/minha-receita/docker-compose.yml`:

```bash
ssh root@185.173.110.180
mkdir -p /opt/minha-receita
cat > /opt/minha-receita/docker-compose.yml << 'EOF'
version: "3.8"
services:
  minhareceita:
    image: cuducos/minha-receita:latest
    ports:
      - "127.0.0.1:3000:8080"
    environment:
      - DATABASE_URL=postgres://extrator:${DB_PASS}@localhost:5432/extrator
    restart: unless-stopped
EOF
```

Replace `${DB_PASS}` with the actual database password from AWS SM:

```bash
# Fetch DB_PASS from AWS SM
python3 -c "
import boto3, json
sm = boto3.client('secretsmanager', region_name='us-east-1')
s = sm.get_secret_value(SecretId='extratordedados/prod')['SecretString']
print(json.loads(s)['DB_PASS'])
"
# Then replace in the docker-compose.yml
```

### 7.3 Initial Data Load

Minha Receita must download and import the RF data into its internal format. This can take
30-90 minutes depending on disk I/O:

```bash
cd /opt/minha-receita
docker-compose run minhareceita update
```

This command downloads the current RF dataset and imports it into the PostgreSQL database
configured via `DATABASE_URL`.

### 7.4 Start the Service

```bash
cd /opt/minha-receita
docker-compose up -d
```

Check the container is running:

```bash
docker-compose ps
docker-compose logs --tail=20
```

### 7.5 Verification

Test the API with a known CNPJ (Banco do Brasil):

```bash
curl -s http://localhost:3000/33.000.167/0001-01 | python3 -m json.tool
```

Expected output: JSON object with 47 fields including `razao_social`, `email`, `uf`, `municipio`, etc.

```json
{
  "cnpj": "33000167000101",
  "razao_social": "BANCO DO BRASIL SA",
  "nome_fantasia": "BB",
  "situacao_cadastral": "ATIVA",
  ...
}
```

### 7.6 Flask Integration

No code change needed. `enrich_cnpj_with_fallback()` already calls Minha Receita as Level 2
of the fallback chain. After the container is running, enrichment will automatically use it:

```
Level 1: SQL lookup in cnpj_rf table (< 10ms)
Level 2: Minha Receita local API (http://localhost:3000/{cnpj}) ← active after this deploy
Level 3: BrasilAPI (public, rate-limited)
Level 4: ReceitaWS (public, limited)
Level 5: OpenCNPJ (public, limited)
```

### 7.7 Note on Double Download

If disk space is tight after the `cnpj_rf` import (Level 1), deploying Minha Receita is
**not required**. Level 1 provides equivalent or faster lookups (direct SQL with index).
Minha Receita is only beneficial if you need the full HTTP API interface externally.

---

## 8. Troubleshooting

### Encoding Errors
The script opens CSVs with `encoding='latin-1', errors='replace'`. If you see garbled characters
in company names, this is expected — the RF data uses ISO-8859-1 (Latin-1).

### Disk Full During Import
If the VPS runs out of disk mid-import:
1. The script deletes each ZIP after successful parse to recover space.
2. If the script crashes mid-shard, the ZIP may remain at `/tmp/rf_import/`.
3. Clean up: `rm -rf /tmp/rf_import/` and restart.
4. The `ON CONFLICT DO NOTHING` clause makes re-runs safe — already imported records are skipped.

### SSH Timeout Recovery
If your SSH session disconnects during the import:
1. The `nohup` process continues running in background.
2. SSH back in and check: `tail -f /tmp/rf_import.log`
3. If the process died: check log for last error, then restart from scratch (idempotent).

### Import Stuck (No Progress)
If `tail -f` shows no output for >10 minutes:
1. Check if process is still alive: `ps aux | grep import`
2. Check disk space: `df -h /`
3. Check DB connection: `docker exec -it extrator-postgres pg_isready`

### Column Index Mismatch
If dry-run shows wrong data in fields (e.g., CNPJ has letters, email field contains a number):
1. Download the latest metadata PDF from the RF mirror
2. Compare column positions against the mapping in `_import_estabelecimentos()`
3. Update the row[] indices in the script before full run

### Rate Limiting / 403 from RF Mirror
The RF mirror occasionally rate-limits downloads. If `_download_file()` returns 403:
1. Wait 15-30 minutes and retry
2. Alternative mirror: `https://dadosabertos.rfb.gov.br/CNPJ/` (official, may be slower)
3. Update `RF_MIRROR_BASE` at the top of the script

---

## Notes

- **ONLY_ACTIVE = True** (default): Only imports situacao_cadastral=02 (ativa). Change to False
  to import all ~60M records including inactive companies (requires ~3x more disk space).
- The script is **idempotent**: `ON CONFLICT (cnpj) DO NOTHING` makes re-runs safe.
- Column mapping was validated against the 2026-02 dataset. Verify on each new release.
- The `cnpj_rf` table has no `source` column — all data is from Receita Federal by definition.
