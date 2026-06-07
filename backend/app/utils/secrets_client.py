"""
Secrets client — resolves secrets at runtime, newer wins:

  1. in-memory cache (a previous successful lookup),
  2. the OPTIONAL secrets-manager vault (SECRETS_MANAGER_URL + _TOKEN), if configured,
  3. environment variables — so the vault is entirely optional.

Nothing is written to disk. If the vault isn't configured or can't be reached,
secrets are read straight from the environment (e.g. OPENAI_API_KEY).
"""

import logging
import os
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# In-memory cache — lives only in process memory
_cache: dict[str, str] = {}


def _vault_configured() -> bool:
    return bool(settings.secrets_manager_url and settings.secrets_manager_token)


def _from_env(key: str) -> Optional[str]:
    """Fallback: read the secret straight from the environment."""
    value = os.environ.get(key)
    if value:
        _cache[key] = value
        logger.info("Secret '%s' resolved from env var", key)
    return value


def _vault_url(key: str) -> str:
    return f"{settings.secrets_manager_url.rstrip('/')}/api/secrets/{key}/"


async def get_secret(key: str, use_cache: bool = True) -> Optional[str]:
    """Resolve a secret: cache → vault (if configured) → env var."""
    key = key.upper()
    if use_cache and key in _cache:
        return _cache[key]
    if not _vault_configured():
        return _from_env(key)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _vault_url(key),
                headers={"Authorization": f"Token {settings.secrets_manager_token}"},
            )
        if resp.status_code != 404:
            resp.raise_for_status()
            value = resp.json().get("value")
            if value:
                _cache[key] = value
                logger.info("Fetched secret '%s' from vault (in-memory only)", key)
                return value
    except Exception as e:
        logger.warning("Vault lookup of '%s' failed (%s) — falling back to env", key, e)
    return _from_env(key)


def get_secret_sync(key: str, use_cache: bool = True) -> Optional[str]:
    """Synchronous version (startup / config loading). cache → vault → env var."""
    key = key.upper()
    if use_cache and key in _cache:
        return _cache[key]
    if not _vault_configured():
        return _from_env(key)
    try:
        resp = httpx.get(
            _vault_url(key),
            headers={"Authorization": f"Token {settings.secrets_manager_token}"},
            timeout=10.0,
        )
        if resp.status_code != 404:
            resp.raise_for_status()
            value = resp.json().get("value")
            if value:
                _cache[key] = value
                return value
    except Exception as e:
        logger.warning("Vault lookup of '%s' failed (%s) — falling back to env", key, e)
    return _from_env(key)


def clear_cache():
    """Clear the in-memory secrets cache."""
    _cache.clear()
