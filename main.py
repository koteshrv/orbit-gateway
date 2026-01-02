
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx
import os
import yaml

from gateway.policy import PolicyStore
from gateway.auth import get_tenant_from_token
from gateway.middleware import RateLimiter, QuotaManager, redact_text, audit_log
from gateway.providers import call_provider
from gateway.store import create_redis
from gateway.tokenizer import estimate_tokens


POLICY_FILE = "policies/example_policy.yaml"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context to initialize and teardown shared resources.

    Replaces the older `@app.on_event("startup")` decorator which may be
    deprecated in newer FastAPI/Starlette versions in favor of a lifespan
    context manager.
    """
    app.state.policies = PolicyStore.load(POLICY_FILE)
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    app.state.redis = create_redis(redis_url)
    app.state.rate_limiter = RateLimiter(app.state.redis)
    app.state.quota_mgr = QuotaManager(app.state.redis)
    yield
    # optional cleanup
    try:
        await app.state.redis.close()
    except Exception:
        pass


app = FastAPI(title="AI Gateway (Policy-driven)", lifespan=lifespan)


class GenerateRequest(BaseModel):
    model: str
    provider: str = "openai"
    prompt: str


@app.post("/v1/generate")
async def generate(req: GenerateRequest, request: Request):
    auth = request.headers.get("authorization")
    if not auth:
        raise HTTPException(401, "missing authorization")
    tenant = get_tenant_from_token(auth, app.state.policies)
    if not tenant:
        raise HTTPException(403, "invalid token")

    policy = app.state.policies.for_tenant(tenant)

    allowed, retry_after = await app.state.rate_limiter.allow(tenant, policy.get("rate_limit", {}))
    if not allowed:
        raise HTTPException(status_code=429, detail=f"rate limit exceeded, retry after {retry_after}s")
    # estimate tokens using tokenizer helper (tiktoken when available)
    estimated_tokens = estimate_tokens(req.prompt, model=req.model)
    if not await app.state.quota_mgr.consume(tenant, estimated_tokens, policy.get("quota", {})):
        raise HTTPException(status_code=402, detail="quota exceeded")

    redacted_prompt = redact_text(req.prompt, policy.get("pii_patterns", []))

    resp = await call_provider(provider=req.provider, model=req.model, prompt=redacted_prompt, tenant=tenant, policy=policy)

    redacted_response = redact_text(resp, policy.get("pii_patterns", []))

    audit_log(tenant, req.provider, req.model, redacted_prompt, redacted_response)

    return {"tenant": tenant, "provider": req.provider, "model": req.model, "response": redacted_response}


class ProxyRequest(BaseModel):
    method: str
    url: str
    headers: dict = None
    body: str = None


@app.post("/v1/proxy")
async def proxy(req: ProxyRequest, request: Request):
    """Simple HTTP proxy endpoint that applies the same tenant rate limit
    controls. This demonstrates how the gateway can act as a regular API
    gateway in front of arbitrary services.
    """
    auth = request.headers.get("authorization")
    if not auth:
        raise HTTPException(401, "missing authorization")
    tenant = get_tenant_from_token(auth, app.state.policies)
    if not tenant:
        raise HTTPException(403, "invalid token")

    policy = app.state.policies.for_tenant(tenant)

    allowed, retry_after = await app.state.rate_limiter.allow(tenant, policy.get("rate_limit", {}))
    if not allowed:
        raise HTTPException(status_code=429, detail=f"rate limit exceeded, retry after {retry_after}s")

    # forward request
    async with httpx.AsyncClient(timeout=30) as c:
        headers = req.headers or {}
        r = await c.request(req.method.upper(), req.url, headers=headers, content=req.body)

    # audit the proxied request (do NOT log auth headers)
    audit_log(tenant, "proxy", req.url, f"{req.method} {req.url}", r.text[:1000])
    return {"status_code": r.status_code, "headers": dict(r.headers), "body": r.text}


@app.api_route("/v1/route/{route_name}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.api_route("/v1/route/{route_name}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def route_forward(route_name: str, path: str = "", request: Request = None):
    """Generic gateway route for tenant-scoped named routes.

    Behavior:
    - Resolve tenant from Authorization header
    - Look up `route_name` in tenant policy
    - Apply rate_limit (route-level or tenant-level)
    - If the route is `ai: true`, expects JSON body with `prompt` and
      will call the configured provider and return the redacted response.
    - Otherwise, proxies the incoming request to `upstream` preserving
      method, path, querystring, headers and body.
    """
    auth = request.headers.get("authorization")
    if not auth:
        raise HTTPException(401, "missing authorization")
    tenant = get_tenant_from_token(auth, app.state.policies)
    if not tenant:
        raise HTTPException(403, "invalid token")

    policy = app.state.policies.for_tenant(tenant)
    route_cfg = app.state.policies.route_for_tenant(tenant, route_name)
    if not route_cfg:
        raise HTTPException(404, "route not found")

    # method allow check
    method = request.method.upper()
    allow_methods = route_cfg.get("allow_methods") or ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    if method not in allow_methods:
        raise HTTPException(405, "method not allowed for this route")

    # rate limiting (route-level overrides tenant-level)
    rl_cfg = route_cfg.get("rate_limit", policy.get("rate_limit", {}))
    allowed, retry_after = await app.state.rate_limiter.allow(tenant, rl_cfg)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"rate limit exceeded, retry after {retry_after}s")

    # AI-enabled route
    if route_cfg.get("ai"):
        body = await request.json()
        prompt = body.get("prompt")
        if not prompt:
            raise HTTPException(400, "ai routes expect JSON body with 'prompt' field")

        # apply PII redaction if requested by route
        if route_cfg.get("redact"):
            prompt = redact_text(prompt, policy.get("pii_patterns", []))

        # token estimation and quota (use tokenizer for accuracy)
        estimated_tokens = estimate_tokens(prompt, model=route_cfg.get("model"))
        if not await app.state.quota_mgr.consume(tenant, estimated_tokens, route_cfg.get("quota", policy.get("quota", {}))):
            raise HTTPException(status_code=402, detail="quota exceeded")

        provider = route_cfg.get("provider") or policy.get("default_provider", "ollama")
        model = route_cfg.get("model")
        resp = await call_provider(provider=provider, model=model, prompt=prompt, tenant=tenant, policy=policy)
        redacted_resp = redact_text(resp, policy.get("pii_patterns", []))
        audit_log(tenant, provider, model, prompt, redacted_resp)
        return JSONResponse({"tenant": tenant, "route": route_name, "response": redacted_resp})

    # Proxy behavior: forward to upstream + path
    upstream = route_cfg.get("upstream")
    if not upstream:
        raise HTTPException(500, "route misconfigured: missing upstream")

    # build url
    qs = request.url.query
    upstream_url = upstream.rstrip("/") + "/" + path.lstrip("/")
    if qs:
        upstream_url = upstream_url + "?" + qs

    # forward headers (strip hop-by-hop and auth)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "authorization", "content-length")}
    body = await request.body()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.request(method, upstream_url, headers=headers, content=body)

    audit_log(tenant, "proxy", upstream_url, f"{method} {upstream_url}", r.text[:1000])
    return JSONResponse(status_code=r.status_code, content={"headers": dict(r.headers), "body": r.text})


@app.post("/admin/reload_policies")
async def reload_policies():
    """Admin endpoint to reload policies from disk (development convenience)."""
    app.state.policies = PolicyStore.load(POLICY_FILE)
    return {"status": "ok"}


@app.post("/admin/policies")
async def update_policies(request: Request):
    """Update/persist policies via REST.

    Accepts either JSON or raw YAML in the request body. If the received
    payload parses correctly, the server will overwrite `POLICY_FILE` and
    reload policies in-memory. This endpoint is primarily a development
    convenience — protect it in production.
    """
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")

    # try JSON first, then YAML
    parsed = None
    try:
        parsed = request.json if False else None
    except Exception:
        parsed = None

    try:
        # attempt YAML parse which also accepts JSON
        parsed = yaml.safe_load(body)
    except Exception as exc:
        raise HTTPException(400, f"unable to parse body as YAML/JSON: {exc}")

    if not isinstance(parsed, dict):
        raise HTTPException(400, "policy payload must be a mapping/object at top-level")

    # persist to disk
    try:
        with open(POLICY_FILE, "w") as f:
            yaml.safe_dump(parsed, f)
    except Exception as exc:
        raise HTTPException(500, f"failed to write policy file: {exc}")

    # reload into memory
    app.state.policies = PolicyStore.load(POLICY_FILE)
    return {"status": "ok"}
