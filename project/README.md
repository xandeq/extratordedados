# Extrator de Dados - Email Scraper

Sistema completo para extração e gerenciamento de emails com backend Python + Flask e frontend Next.js.

## Estrutura

```
project/
├── backend/           # API Flask (Python)
├── frontend/          # Next.js (JavaScript/TypeScript)
├── shared/            # Arquivos compartilhados
└── scripts/           # Scripts auxiliares
```

## Backend (Python Flask)

**URL:** `https://api.extratordedados.com.br`

### Endpoints

- `GET /api/health` - Health check
- `POST /api/scrape` - Iniciar scraping
- `GET /api/results` - Listar resultados
- `GET /api/results/<id>` - Detalhe de um resultado

### Setup Local

```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # ou venv\Scripts\activate no Windows
pip install -r requirements.txt
python app.py
```

## Frontend (Next.js)

**URL:** `https://extratordedados.com.br`

### Setup Local

```bash
cd frontend
npm install
npm run dev
```

## Deploy

### HostGator

Arquivos Python estão em `/home/alexa084/api.extratordedados.com.br/api/`

FTP: `ftp.alexandrequeiroz.com.br`
User: `alexa084`

### Scraper Automático

Roda via cron job a cada 6 horas para buscar novos emails de públicas.

## Tecnologias

- **Backend:** Python 3.6, Flask 2.0, BeautifulSoup4, Requests
- **Frontend:** Next.js, React, TypeScript
- **Database:** SQLite3
- **Host:** HostGator (cPanel)
