# fast_api

API central para webhook de entrada e health, preparada para EasyPanel e dedicada ao `garcom_digital`.

Regra simples:

- `Webhook = entrada`, comeco do fluxo.
- `Response API = saida`, faz o `HTTP POST` direto para a API do Chatwoot no Stage07.

## Variaveis de ambiente

- `PORT` (opcional, padrao `8000`)
- `WEB_CONCURRENCY` (opcional, padrao `4`)
- `WEB_TIMEOUT` (opcional, padrao `120`)
- `REDIS_URL` (recomendado para producao, ex: `redis://:SENHA@redis:6379/0`)
- `WEBHOOK_EVENTS_MAXLEN` (opcional, padrao `1000`)
- `FORWARD_WEBHOOK_TIMEOUT_SECONDS` (opcional, padrao `10`)
- `FORWARD_WEBHOOK_URL_GARCOM_DIGITAL` (opcional): URL do garcom_digital para encaminhamento

Exemplo:

- `FORWARD_WEBHOOK_URL_GARCOM_DIGITAL=https://SEU_GARCOM/webhook/chatwoot`

## Endpoints

- `GET /health` health check + status do Redis
- `POST /webhook/chatwoot`

## Observacoes

- Para escalar em muitos workers, use `REDIS_URL` (estado compartilhado).
- Sem Redis, apenas webhook funciona; endpoints de mensagens foram removidos.
- Se `FORWARD_WEBHOOK_URL_GARCOM_DIGITAL` estiver definido, o payload recebido e encaminhado ao destino de entrada do `garcom_digital`.
- O fluxo fica:
  - `Chatwoot -> fast_api -> garcom_digital`
  - `garcom_digital -> Chatwoot API` no Stage07
