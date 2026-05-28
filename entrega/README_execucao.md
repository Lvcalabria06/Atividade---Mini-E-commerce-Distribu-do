# Mini E-commerce Distribuído — Instruções de Execução

## Pré-requisitos

- Python 3.10+ (para execução local) **ou** Docker + Docker Compose (recomendado)
- `curl` ou Postman para testes

---

## Opção 1 — Docker Compose (recomendado)

```bash
# Na raiz da pasta entrega/
docker compose up --build
```

Todos os serviços sobem automaticamente:

| Serviço              | URL                        |
|----------------------|----------------------------|
| API Gateway          | http://localhost:5000       |
| Usuários             | http://localhost:5001       |
| Produtos (primário)  | http://localhost:5002       |
| Produtos (réplica)   | http://localhost:5012       |
| Pedidos              | http://localhost:5003       |
| Dashboard            | http://localhost:5000/dashboard |

Para parar:
```bash
docker compose down
```

---

## Opção 2 — Execução Local (sem Docker)

Abra **5 terminais** separados e execute em cada um:

### Terminal 1 — Serviço de Usuários
```bash
cd users
pip install -r requirements.txt
uvicorn main:app --port 5001
```

### Terminal 2 — Serviço de Produtos (primário)
```bash
cd products
pip install -r requirements.txt
PORT=5002 IS_PRIMARY=true REPLICA_URL=http://localhost:5012 uvicorn main:app --port 5002
```

> Windows PowerShell:
> ```powershell
> $env:PORT="5002"; $env:IS_PRIMARY="true"; $env:REPLICA_URL="http://localhost:5012"; uvicorn main:app --port 5002
> ```

### Terminal 3 — Serviço de Produtos (réplica)
```bash
cd products
PORT=5012 IS_PRIMARY=false uvicorn main:app --port 5012
```

> Windows PowerShell:
> ```powershell
> $env:PORT="5012"; $env:IS_PRIMARY="false"; uvicorn main:app --port 5012
> ```

### Terminal 4 — Serviço de Pedidos
```bash
cd orders
pip install -r requirements.txt
uvicorn main:app --port 5003
```

### Terminal 5 — API Gateway
```bash
cd gateway
pip install -r requirements.txt
uvicorn main:app --port 5000
```

---

## Testando o Sistema

### 1. Registrar usuário admin
```bash
curl -X POST http://localhost:5000/users/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Admin","email":"admin@loja.com","password":"senha123","role":"admin"}'
```

### 2. Registrar usuário comum
```bash
curl -X POST http://localhost:5000/users/register \
  -H "Content-Type: application/json" \
  -d '{"name":"João","email":"joao@email.com","password":"senha456","role":"user"}'
```

### 3. Login (salve o token retornado)
```bash
curl -X POST http://localhost:5000/users/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@loja.com","password":"senha123"}'
```

### 4. Criar produto (requer token de admin)
```bash
curl -X POST http://localhost:5000/products \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN_ADMIN>" \
  -d '{"name":"Notebook","description":"15 polegadas","price":2999.99,"stock":10}'
```

### 5. Listar produtos (sem token)
```bash
curl http://localhost:5000/products
```

### 6. Criar pedido (requer token do usuário)
```bash
curl -X POST http://localhost:5000/orders \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN_USER>" \
  -d '{"userId":"<USER_ID>","productId":"<PRODUCT_ID>","quantity":1}'
```

### 7. Listar pedidos do usuário
```bash
curl http://localhost:5000/orders/<USER_ID> \
  -H "Authorization: Bearer <TOKEN_USER>"
```

### 8. Verificar status dos serviços (heartbeat)
```bash
curl http://localhost:5000/health
```

### 9. Dashboard visual
Abra no navegador: http://localhost:5000/dashboard

---

## Testando Tolerância a Falhas

1. Inicie todos os serviços.
2. Derrube o serviço de Pedidos (feche o Terminal 4 ou `Ctrl+C`).
3. Aguarde ~10 segundos (2 ciclos de heartbeat).
4. Tente acessar `/orders` — receberá `503 Service Unavailable`.
5. Tente acessar `/products` e `/users` — continuarão funcionando normalmente.
6. Reinicie o serviço de Pedidos e aguarde a recuperação ser registrada no log do Gateway.

---

## Variáveis de Ambiente

| Variável              | Padrão                   | Descrição                          |
|-----------------------|--------------------------|------------------------------------|
| `JWT_SECRET`          | `supersecret_jwt_key_2024` | Chave de assinatura JWT           |
| `PORT`                | varia por serviço        | Porta de escuta do serviço         |
| `IS_PRIMARY`          | `true`                   | Define se é réplica primária       |
| `REPLICA_URL`         | `""`                     | URL da réplica (apenas no primário)|
| `USERS_URL`           | `http://localhost:5001`  | URL interna do serviço de usuários |
| `PRODUCTS_URL`        | `http://localhost:5002`  | URL interna do serviço de produtos |
| `HEARTBEAT_INTERVAL`  | `5`                      | Intervalo do heartbeat (segundos)  |
