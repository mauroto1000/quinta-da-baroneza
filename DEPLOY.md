# Deploy no PythonAnywhere

## 1. Upload do projeto

No PythonAnywhere, abra um console Bash e clone ou faça upload do projeto:

```bash
cd ~
git clone <seu-repositorio> quinta-da-baronesa
# ou use o gerenciador de arquivos do PythonAnywhere para fazer upload do ZIP
```

## 2. Criar virtualenv e instalar dependências

```bash
cd ~/quinta-da-baronesa
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. Criar o arquivo .env

```bash
cp .env.example .env
nano .env
```

Edite a `SECRET_KEY` com uma string aleatória longa (ex: `openssl rand -hex 32`).

## 4. Criar o primeiro administrador

```bash
source venv/bin/activate
python create_admin.py
```

## 5. Configurar o Web App no PythonAnywhere

Na aba **Web** do PythonAnywhere:

1. Clique em **Add a new web app**
2. Escolha **Manual configuration** → **Python 3.12**
3. Configure:
   - **Source code**: `/home/<username>/quinta-da-baronesa`
   - **Working directory**: `/home/<username>/quinta-da-baronesa`
   - **Virtualenv**: `/home/<username>/quinta-da-baronesa/venv`
4. Edite o arquivo WSGI (link na página Web):
   ```python
   import sys, os
   sys.path.insert(0, '/home/<username>/quinta-da-baronesa')
   os.chdir('/home/<username>/quinta-da-baronesa')
   
   from a2wsgi import ASGIMiddleware
   from app.main import app
   application = ASGIMiddleware(app)
   ```
5. Em **Static files**, adicione:
   - URL: `/static/`
   - Path: `/home/<username>/quinta-da-baronesa/static`

## 6. Task agendada (verificação de timeouts)

Na aba **Tasks** do PythonAnywhere (plano pago), adicione uma tarefa a cada minuto:
```
/home/<username>/quinta-da-baronesa/venv/bin/python -c "
import sys; sys.path.insert(0, '/home/<username>/quinta-da-baronesa')
import os; os.chdir('/home/<username>/quinta-da-baronesa')
from app.services.tasks import check_expired_steps
check_expired_steps()
"
```

> **Nota**: No plano gratuito, o mínimo é 1 task/dia. Nesse caso, o APScheduler embutido no app cuidará dos timeouts enquanto o worker estiver ativo.

## 7. Configurações finais no Admin

Após o primeiro login:
1. Acesse **Admin → Configurações**
2. Preencha a **URL base da aplicação** (ex: `https://seunome.pythonanywhere.com`)
3. Configure a **Evolution API** (URL, chave e instância)
4. Crie os jogadores em **Admin → Jogadores**
5. Configure a agenda em **Admin → Gerenciar Agenda**

## Evolution API (WhatsApp)

Para integração com WhatsApp, você precisa de:
- Um servidor rodando a [Evolution API](https://github.com/EvolutionAPI/evolution-api)
- Ou contratar um serviço de hospedagem da Evolution API

Configure os dados no painel Admin → Configurações.
