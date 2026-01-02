from typing import Optional
from gateway.policy import PolicyStore


def get_tenant_from_token(authorization_header: str, policies: PolicyStore) -> Optional[str]:
    """Resolve a tenant id from an Authorization header using the
    `PolicyStore.token_map()`.

    Expected `authorization_header` format: `Bearer <token>`.
    Returns the tenant id string or `None` if the token is unknown.
    """
    # Expect `Bearer <token>`
    if not authorization_header:
        return None
    parts = authorization_header.split()
    if len(parts) != 2:
        return None
    token = parts[1]
    mapping = policies.token_map()
    return mapping.get(token)
