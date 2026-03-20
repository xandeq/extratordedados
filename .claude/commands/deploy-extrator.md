# Deploy Pipeline — extratordedados.com.br

Skill específica deste projeto (extrator-de-dados). Faz deploy do backend para a VPS (185.173.110.180) e do frontend para o HostGator via FTP.

Execute o pipeline de deploy do projeto. Interprete os argumentos do usuário:

- Sem argumento ou "tudo" / "completo" / "all" → modo `all` (backend + frontend)
- "backend" → modo `backend`
- "frontend" → modo `frontend`

## Passos a executar

1. Identifique o modo (all / backend / frontend) com base na mensagem do usuário.

2. Execute o script unificado de deploy:
```bash
python deploy.py [modo]
```
O script está na raiz do projeto: `deploy.py`

3. Acompanhe a saída e reporte o resultado ao usuário:
   - Se backend: mostre se o serviço ficou `active` e o resultado do health check
   - Se frontend: mostre quantos arquivos foram enviados e se houve erros
   - Sempre mostre as URLs finais:
     - API: https://api.extratordedados.com.br/api/health
     - Site: https://extratordedados.com.br

4. Em caso de erro, diagnostique e informe o usuário.

## Notas
- O script lê credenciais de `.deploy.env` (gitignored) automaticamente
- Build do frontend é feito automaticamente antes do FTP
- `.htaccess` é recriado automaticamente após o build
