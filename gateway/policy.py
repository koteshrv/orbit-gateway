from pydantic import BaseModel
import yaml
from typing import Dict, Any


class PolicyStore:
    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw

    @classmethod
    def load(cls, path: str):
        with open(path, "r") as f:
            raw = yaml.safe_load(f) or {}
        return cls(raw)

    def for_tenant(self, tenant: str) -> Dict[str, Any]:
        return self.raw.get("tenants", {}).get(tenant, {})

    def route_for_tenant(self, tenant: str, route_name: str) -> Dict[str, Any]:
        """Return route configuration for a named route under a tenant.

        The policy YAML can declare a `routes:` mapping per tenant. Each
        route entry may contain `upstream`, `allow_methods`, `rate_limit`,
        `quota`, and `ai` flags. This helper returns the route dict or an
        empty dict if not found.
        """
        tenant_cfg = self.for_tenant(tenant)
        return (tenant_cfg.get("routes", {}) or {}).get(route_name, {})

    def token_map(self) -> Dict[str, str]:
        # returns token -> tenant mapping
        mapping = {}
        for t, cfg in (self.raw.get("tenants", {})).items():
            for tok in cfg.get("tokens", []):
                mapping[tok] = t
        return mapping
