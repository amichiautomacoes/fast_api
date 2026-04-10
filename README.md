# fast_api

API central para webhooks e mensagens, preparada para EasyPanel e multiplos workers.

## Variaveis de ambiente

- `PORT` (opcional, padrao `8000`)
- `WEB_CONCURRENCY` (opcional, padrao `4`)
- `WEB_TIMEOUT` (opcional, padrao `120`)
- `REDIS_URL` (recomendado para producao, ex: `redis://:SENHA@redis:6379/0`)
- `WEBHOOK_EVENTS_MAXLEN` (opcional, padrao `1000`)
- `FORWARD_WEBHOOK_TIMEOUT_SECONDS` (opcional, padrao `10`)

Tokens por projeto (obrigatorios para rotas `/webhooks/{project}`):

- `WEBHOOK_TOKEN_CHATWOOT=...`
- `WEBHOOK_TOKEN_NOVAUNIAO_MARKETING=...`
- `WEBHOOK_TOKEN_GARCOM_DIGITAL=...`
- Regra geral: `WEBHOOK_TOKEN_<PROJECT_EM_MAIUSCULO_COM_UNDERSCORE>`

Forward por projeto (opcional):

- `FORWARD_WEBHOOK_URL_GARCOM_DIGITAL=https://SEU_GARCOM/api/v1/webhook?token=...`
- Regra geral: `FORWARD_WEBHOOK_URL_<PROJECT_EM_MAIUSCULO_COM_UNDERSCORE>`

## Endpoints

- `GET /` status basico do servico
- `GET /health` health check + status do Redis
- `POST /webhooks/{project}?token=...` recebe webhooks por projeto
- `POST /chatwoot-webhook?token=...` alias legado
- `POST /novauniao-marketing-webhook?token=...` alias legado

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
- Se `FORWARD_WEBHOOK_URL_<PROJECT>` estiver definido, o payload recebido em `/webhooks/{project}` e encaminhado ao destino.
