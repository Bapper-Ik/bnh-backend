# Endpoint integration notes

## CORE-001 — runtime

- `GET /api/v1/health/live`: public process liveness; no inputs or business permission; `200 {"status":"alive"}`.
- `GET /api/v1/health/ready`: public dependency readiness; no inputs or business permission; checks PostgreSQL connectivity, schema availability and restricted runtime privileges. `200 {"status":"ready"}` or `503 {"status":"unavailable"}`. No database credentials or internals in responses.
- Both return `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, and a generated `X-Request-ID`. No mutation, pagination, expected version or idempotency key applies.
- Monitoring should retry unavailable readiness. Liveness/readiness do not establish authentication, business feature completion, or human acceptance.
- No staff-facing UI is required by this foundation feature. OpenAPI is exposed through FastAPI's `/openapi.json` and `/docs`.
