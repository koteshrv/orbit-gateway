# Orbit Gateway — Unified API & AI Governance Platform

This repository provides a minimal FastAPI-based central gateway ("Orbit Gateway") that combines traditional API gateway features with AI governance. It demonstrates:

- Tenant isolation via token-to-tenant mapping
- PII redaction using tenant policy regexes
- Redis-backed rate limiting and token-based quota enforcement
- Provider adapters for OpenAI, Azure OpenAI, and Ollama (local LLMs)
- Audit logging to `logs/audit.log`

Quick start

Install deps:

```bash
python -m pip install -r requirements.txt
```

Run:

```bash
export REDIS_URL=redis://localhost:6379/0
uvicorn main:app --reload --host 0.0.0.0 --port 8080
```

Example request (uses token defined in `policies/example_policy.yaml`):

```bash
curl -sS -X POST http://localhost:8080/v1/generate \
  -H "Authorization: Bearer acme-token-123" \
  -H "Content-Type: application/json" \
  -d '{"provider":"ollama","model":"llama2","prompt":"Hello, my email is test@example.com"}'
```

Proxying an arbitrary API (gateway behaviour):

```bash
curl -sS -X POST http://localhost:8080/v1/proxy \
  -H "Authorization: Bearer acme-token-123" \
  -H "Content-Type: application/json" \
  -d '{"method":"GET","url":"https://httpbin.org/get"}'
```

Redis configuration

Set `REDIS_URL` in the environment to point the gateway at a Redis instance. This
is required for distributed rate limiting and quota enforcement when running
multiple replicas.

Named routes (API Gateway features)

You can define named routes in the tenant policy under `routes:`. The gateway
exposes these routes via the path pattern `/v1/route/{route_name}` (and
`/v1/route/{route_name}/{path...}`) and will:

- Enforce per-route or tenant-level rate limits.
- Enforce per-route quotas (requests or tokens for AI routes).
- Proxy regular REST calls to an `upstream` URL.
- Host AI-enabled routes that accept a JSON `prompt` and forward it to the
  configured LLM provider with PII redaction and quota enforcement.

Example `routes` are configured in `policies/example_policy.yaml`:
- `sample_api` forwards requests to `https://httpbin.org`.
- `ai_chat` demonstrates an AI-enabled endpoint using Ollama.

To reload policies without restarting the server (dev only):

```bash
curl -X POST http://localhost:8080/admin/reload_policies
```

Files
- [main.py](main.py) - entrypoint and request path
- [policies/example_policy.yaml](policies/example_policy.yaml) - sample governance policies
- [gateway/policy.py](gateway/policy.py) - YAML policy loader
- [gateway/auth.py](gateway/auth.py) - token-to-tenant mapping
- [gateway/middleware.py](gateway/middleware.py) - redaction, rate limit, quota, audit
- [gateway/providers.py](gateway/providers.py) - provider adapters
