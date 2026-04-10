# fast_api

API central para webhooks e mensagens, preparada para EasyPanel e dedicada ao `garcom_digital`.

## Variaveis de ambiente

- `PORT` (opcional, padrao `8000`)
- `WEB_CONCURRENCY` (opcional, padrao `4`)
- `WEB_TIMEOUT` (opcional, padrao `120`)
- `REDIS_URL` (recomendado para producao, ex: `redis://:SENHA@redis:6379/0`)
- `WEBHOOK_EVENTS_MAXLEN` (opcional, padrao `1000`)
- `FORWARD_WEBHOOK_TIMEOUT_SECONDS` (opcional, padrao `10`)
- `FORWARD_WEBHOOK_URL_GARCOM_DIGITAL` (opcional): URL do garcom_digital para encaminhamento
- `CHATWOOT_BASE_URL` (obrigatoria para outbound)
- `CHATWOOT_ACCOUNT_ID` (obrigatoria para outbound)
- `CHATWOOT_API_ACCESS_TOKEN` (obrigatoria para outbound)

Exemplo:

- `FORWARD_WEBHOOK_URL_GARCOM_DIGITAL=https://SEU_GARCOM/api/v1/webhook`
- `CHATWOOT_BASE_URL=https://SEU_CHATWOOT`
- `CHATWOOT_ACCOUNT_ID=1`
- `CHATWOOT_API_ACCESS_TOKEN=...`

## Endpoints

- `GET /` status basico do servico
- `GET /health` health check + status do Redis
- `POST /webhooks/garcom_digital` webhook dedicado ao garcom
- `POST /webhook` alias simples para o mesmo fluxo
- `POST /bridge/chatwoot/outgoing` envio interno do garcom para Chatwoot via fast_api

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
- O fluxo recomendado fica:
  - `Chatwoot -> fast_api -> garcom_digital` (entrada de mensagem)
  - `garcom_digital -> fast_api -> Chatwoot` (saida de mensagem)
