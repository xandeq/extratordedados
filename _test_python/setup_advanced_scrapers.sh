#!/bin/bash
# Setup Playwright e Instaloader no VPS

cd /opt/extrator-api

echo "=== Ativando venv ==="
source venv/bin/activate

echo "=== Instalando dependências Python no venv ==="
pip install --upgrade playwright instaloader

echo ""
echo "=== Instalando browsers do Playwright ==="
python -m playwright install chromium

echo ""
echo "=== Instalando dependências do sistema para Chromium ==="
python -m playwright install-deps chromium

echo ""
echo "=== Verificando instalação ==="
python -c "import playwright; print(f'Playwright: {playwright.__version__}')"
python -c "import instaloader; print(f'Instaloader: {instaloader.__version__}')"

echo ""
echo "=== Reiniciando serviço ==="
systemctl restart extrator-api
sleep 3
systemctl status extrator-api --no-pager

echo ""
echo "=== CONCLUÍDO! ==="
