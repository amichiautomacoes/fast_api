# fast_api

Servico independente de webhook hub para multiplos projetos.

Objetivo:

- Receber webhooks (`POST` + JSON).
- Validar autenticacao por token por projeto.
- Encaminhar payload para destinos configurados por projeto/fonte.
- Manter compatibilidade com rotas legadas (`/rd/entrada`, `/webhook/chatwoot`).

## Endpoints

- `GET /` status basico
- `GET /health` health + status Redis
- `GET /ready` readiness (sempre `200`)
- `POST /v1/webhooks/{project}/{source}` endpoint generico recomendado
- `POST /rd/entrada` alias compativel para RD Station
- `POST /webhook/chatwoot` alias compativel para Chatwoot

## Variaveis de ambiente

Infra:

- `PORT` (opcional, padrao `8000`)
- `WEB_CONCURRENCY` (opcional, padrao `4`)
- `WEB_TIMEOUT` (opcional, padrao `120`)
- `REDIS_URL` (opcional, recomendado para producao)
- `WEBHOOK_EVENTS_MAXLEN` (opcional, padrao `1000`)

Seguranca:

- `WEBHOOK_REQUIRE_TOKEN` (opcional, padrao `true`)
- `WEBHOOK_GLOBAL_TOKEN` (opcional, fallback para qualquer projeto sem token dedicado)
- `WEBHOOK_PROJECT_TOKENS_JSON` (recomendado)
- `WEBHOOK_PROJECT_TOKENS` (formato alternativo CSV: `projeto:token,projeto2:token2`)

Roteamento de encaminhamento:

- `FORWARD_WEBHOOK_TIMEOUT_SECONDS` (opcional, padrao `10`)
- `FORWARD_ROUTES_JSON` (recomendado)
- `FORWARD_WEBHOOK_URL_GARCOM_DIGITAL` (compatibilidade legado)

Compatibilidade de aliases:

- `DEFAULT_PROJECT` (para `/rd/entrada`, padrao `default`)
- `CHATWOOT_DEFAULT_PROJECT` (para `/webhook/chatwoot`, padrao `garcom_digital`)

## Exemplo de configuracao

```env
WEBHOOK_REQUIRE_TOKEN=true
WEBHOOK_PROJECT_TOKENS_JSON={"novauniao":"tok_nova","garcom_digital":"tok_garcom"}
FORWARD_ROUTES_JSON={
  "novauniao:rd_station":"https://seu-pipeline-novauniao/webhook/rd",
  "garcom_digital:chatwoot":"https://seu-garcom/webhook/chatwoot",
  "default:default":"https://seu-destino-padrao/webhook"
}
REDIS_URL=redis://:SENHA@redis:6379/0
```

## Como chamar

Rota generica:

```bash
curl -X POST "https://api.seudominio.com/v1/webhooks/novauniao/rd_station" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer tok_nova" \
  -d '{"lead":{"email":"teste@dominio.com"}}'
```

Alias RD:

```bash
curl -X POST "https://api.seudominio.com/rd/entrada" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: tok_nova" \
  -d '{"event_type":"conversion","lead":{"email":"teste@dominio.com"}}'
```

## Deploy (Easypanel)

1. Criar app apontando para este repositorio.
2. Build usando `Dockerfile` da raiz.
3. Definir variaveis de ambiente.
4. Publicar dominio com HTTPS.
5. Validar `GET /health` e depois testar `POST /v1/webhooks/{project}/{source}`.

