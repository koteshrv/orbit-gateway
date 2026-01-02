import httpx
import asyncio
from typing import Dict, Any


async def call_openai(api_key: str, model: str, prompt: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 512}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(url, json=payload, headers=headers)
        r.raise_for_status()
        j = r.json()
        return j["choices"][0]["message"]["content"]


async def call_azure_openai(api_key: str, endpoint: str, deployment: str, model: str, prompt: str) -> str:
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2023-10-01"
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    payload = {"messages": [{"role": "user", "content": prompt}], "max_tokens": 512}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(url, json=payload, headers=headers)
        r.raise_for_status()
        j = r.json()
        return j["choices"][0]["message"]["content"]


async def call_ollama(model: str, prompt: str, host: str = "http://localhost:11434") -> str:
    url = f"{host}/v1/complete"
    payload = {"model": model, "prompt": prompt, "max_tokens": 512}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(url, json=payload)
        r.raise_for_status()
        j = r.json()
        return j.get("completion") or j.get("text") or ""


async def call_provider(provider: str, model: str, prompt: str, tenant: str, policy: Dict[str, Any]) -> str:
    # provider-specific credentials live in policy under provider_credentials
    creds = policy.get("provider_credentials", {})
    if provider == "openai":
        key = creds.get("openai", {}).get("api_key")
        if not key:
            return f"[mock] {prompt}"
        return await call_openai(key, model, prompt)
    if provider == "azure":
        azure = creds.get("azure_openai", {})
        key = azure.get("api_key")
        endpoint = azure.get("endpoint")
        deployment = azure.get("deployment")
        if not (key and endpoint and deployment):
            return f"[mock] {prompt}"
        return await call_azure_openai(key, endpoint, deployment, model, prompt)
    if provider == "ollama":
        host = creds.get("ollama", {}).get("host", "http://localhost:11434")
        return await call_ollama(model=model, prompt=prompt, host=host)

    # fallback for demo
    await asyncio.sleep(0.01)
    return f"[echo] {prompt}"

