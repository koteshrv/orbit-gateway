import re
import time
import os
import json
from typing import List, Dict, Any, Optional, Tuple

from gateway.store import rate_allow, quota_consume


class RateLimiter:
    """Redis-backed rate limiter wrapper.

    This class delegates to `gateway.store.rate_allow` which performs a
    fixed-window counter in Redis. Instances hold a reference to the
    Redis client provided by the app and expose a small `allow` method
    compatible with the previous in-memory API.
    """

    def __init__(self, redis_client):
        self.redis = redis_client

    async def allow(self, tenant: str, cfg: Dict[str, Any]) -> Tuple[bool, int]:
        """Check whether tenant can make a request under `cfg`.

        Args:
            tenant: tenant id string
            cfg: dict with `requests` and `per_seconds` keys

        Returns:
            (allowed: bool, retry_after_seconds: int)
        """
        reqs = int(cfg.get("requests", 60))
        per = int(cfg.get("per_seconds", 60))
        return await rate_allow(self.redis, tenant, reqs, per)


class QuotaManager:
    """Redis-backed monthly quota manager.

    Uses an atomic Lua script in `gateway.store.quota_consume` to ensure
    multiple replicas don't oversubscribe the tenant's monthly token cap.
    """

    def __init__(self, redis_client):
        self.redis = redis_client

    async def consume(self, tenant: str, tokens: int, cfg: Dict[str, Any]) -> bool:
        """Attempt to consume `tokens` from tenant's monthly cap.

        Args:
            tenant: tenant id
            tokens: estimated tokens to consume
            cfg: dict with `monthly_tokens` cap

        Returns:
            True if consumption succeeded; False if cap would be exceeded.
        """
        cap = int(cfg.get("monthly_tokens", 100000))
        return await quota_consume(self.redis, tenant, tokens, cap)


def redact_text(text: str, patterns: Optional[List[str]]) -> str:
    """Redact occurrences matching regex patterns.

    For each pattern in `patterns` the function replaces matches with
    the literal string `[REDACTED]`. Invalid regexes are treated as
    plain substrings and replaced.
    """
    if not patterns:
        return text
    out = text
    for p in patterns:
        try:
            out = re.sub(p, "[REDACTED]", out, flags=re.IGNORECASE)
        except re.error:
            out = out.replace(p, "[REDACTED]")
    return out


def audit_log(tenant: str, provider: str, model: str, prompt: str, response: str, path: str = "logs/audit.log"):
    """Append a JSON line to the audit log.

    This helper keeps the audit sink simple for the demo; in production
    you'd forward events to a secure logging pipeline or SIEM.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = {"timestamp": int(time.time()), "tenant": tenant, "provider": provider, "model": model, "prompt": prompt, "response": response}
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
