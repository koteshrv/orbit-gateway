# TODO / Roadmap

This file lists prioritized next work items for the `orbit-gateway` (Orbit Gateway) PoC.

Notes:
- For local testing we recommend running Redis as a separate container (see `docker-compose.yml`).
- Authentication and secret management will be added later; current admin endpoints are development-only.

## Priority: High

- [ ] Add integration tests for Redis-backed enforcement
  - Purpose: exercise `gateway.store.rate_allow` and `gateway.store.quota_consume` against a real Redis instance.
  - Approach: use `pytest` with a `docker-compose` test fixture (start Redis service) or GitHub Actions service container.
  - Files to add: `tests/test_store.py`, `pytest.ini`, CI workflow that runs `docker-compose up -d redis && pytest`.

- [ ] Add Docker Compose for local dev
  - Purpose: make it easy to run Redis and the gateway locally for manual testing.
  - File: `docker-compose.yml` (included in repo). Start with `redis` service and extend later.

- [ ] Protect admin endpoints and add operator auth
  - Purpose: secure `/admin/*` endpoints before any non-dev usage.
  - Options: JWT introspection, API-key with RBAC, or OAuth2 client credentials for operators.

## Priority: Medium

- [ ] Use `tiktoken` tokenization for quota accounting (already included in PoC)
  - Confirm behavior against provider billing and adjust padding/estimators.

- [ ] Replace YAML-stored secrets with a secret store
  - Integrate HashiCorp Vault / AWS Secrets Manager / Azure Key Vault.

- [ ] Replace file-based audits with centralized logging
  - Send audit JSON-lines to Kafka/Fluentd/Cloud Logging, ensure encryption and ACLs.

## Priority: Low / Nice-to-have

- [ ] Add automated reconciliation of provider usage vs quotas
- [ ] Add ML-based PII detection and DLP integration
- [ ] Add management UI for policies and tenant onboarding
- [ ] Add multi-tenant observability dashboards (Prometheus/Grafana)

## How to run the quick PoC locally

1. Start Redis locally via docker-compose:

```bash
docker-compose up -d redis
```

2. Install Python deps and run the app:

```bash
python -m pip install -r requirements.txt
export REDIS_URL=redis://localhost:6379/0
uvicorn main:app --reload --port 8080
```

3. Run tests (when added):

```bash
docker-compose up -d redis
pytest
```

If you'd like, I can add the test skeleton and a CI workflow next.
