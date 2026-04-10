# fast_api

API central para webhooks e mensagens, preparada para EasyPanel e dedicada ao `garcom_digital`.

## Variaveis de ambiente

- `PORT` (opcional, padrao `8000`)
- `WEB_CONCURRENCY` (opcional, padrao `4`)
- `WEB_TIMEOUT` (opcional, padrao `120`)
- `REDIS_URL` (recomendado para producao, ex: `redis://:SENHA@redis:6379/0`)
- `WEBHOOK_EVENTS_MAXLEN` (opcional, padrao `1000`)
- `FORWARD_WEBHOOK_TIMEOUT_SECONDS` (opcional, padrao `10`)
- `WEBHOOK_TOKEN_GARCOM_DIGITAL` (obrigatoria)
- `FORWARD_WEBHOOK_URL_GARCOM_DIGITAL` (opcional): URL do garcom_digital para encaminhamento
- `FORWARD_GATEWAY_TOKEN_GARCOM_DIGITAL` (obrigatoria quando houver encaminhamento): token enviado em `X-Gateway-Token`

Exemplo:

- `WEBHOOK_TOKEN_GARCOM_DIGITAL=...`
- `FORWARD_WEBHOOK_URL_GARCOM_DIGITAL=https://SEU_GARCOM/api/v1/webhook?token=...`
- `FORWARD_GATEWAY_TOKEN_GARCOM_DIGITAL=...`

## Endpoints

- `GET /` status basico do servico
- `GET /health` health check + status do Redis
- `POST /webhooks/garcom_digital?token=...` webhook dedicado ao garcom
- `POST /webhook?token=...` alias simples para o mesmo fluxo

Mensagens (CRUD completo):

- `POST /messages`
- `GET /messages`
- `GET /messages/{message_id}`
- `PUT /messages/{message_id}`
- `PATCH /messages/{message_id}`
- `DELETE /messages/{message_id}`

## Observacoes

- Para escalar em muitos workers, use `REDIS_URL` (estado compartilhado).
- Sem Redis, apenas webhook funciona; endpoints de mensagens retornam `503`.
- Se `FORWARD_WEBHOOK_URL_GARCOM_DIGITAL` estiver definido, o payload recebido e encaminhado ao destino.
- O encaminhamento exige `FORWARD_GATEWAY_TOKEN_GARCOM_DIGITAL`; o valor e enviado no header `X-Gateway-Token`.
