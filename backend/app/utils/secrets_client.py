"""
Secrets Manager client — fetches secrets at runtime from the
secrets-manager Django app. NEVER stores secrets on disk.

The secrets-manager must be running and accessible at SECRETS_MANAGER_URL.
Auth via DRF Token (Authorization: Token <token>).
"""

import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# In-memory cache — populated once at startup, lives only in process memory
_cache: dict[str, str] = {}


async def get_secret(key: str, use_cache: bool = True) -> Optional[str]:
    """
    Fetch a secret by key from the secrets-manager API.

    Args:
        key: Secret key (e.g. OPENAI_API_KEY)
        use_cache: If True, return cached value if available

    Returns:
        Plaintext secret value, or None if not found.
    """
    key = key.upper()

    if use_cache and key in _cache:
        return _cache[key]

    url = f"{settings.secrets_manager_url.rstrip('/')}/api/secrets/{key}/"
    token = settings.secrets_manager_token

    if not token:
        logger.warning("SECRETS_MANAGER_TOKEN not set — cannot fetch secrets")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Token {token}"},
            )

            if resp.status_code == 404:
                logger.warning("Secret '%s' not found in vault", key)
                return None

            resp.raise_for_status()
            data = resp.json()
            value = data.get("value")

            if value:
                _cache[key] = value
                logger.info("Fetched secret '%s' from vault (cached in memory)", key)

            return value

    except httpx.ConnectError:
        logger.error("Cannot connect to secrets-manager at %s", settings.secrets_manager_url)
        return None
    except Exception as e:
        logger.exception("Failed to fetch secret '%s': %s", key, e)
        return None


def get_secret_sync(key: str, use_cache: bool = True) -> Optional[str]:
    """Synchronous version for use during startup / config loading."""
    key = key.upper()

    if use_cache and key in _cache:
        return _cache[key]

    url = f"{settings.secrets_manager_url.rstrip('/')}/api/secrets/{key}/"
    token = settings.secrets_manager_token

    if not token:
        return None

    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Token {token}"},
            timeout=10.0,
        )

        if resp.status_code == 404:
            return None

        resp.raise_for_status()
        data = resp.json()
        value = data.get("value")

        if value:
            _cache[key] = value

        return value

    except Exception as e:
        logger.error("Sync fetch of secret '%s' failed: %s", key, e)
        return None


def clear_cache():
    """Clear the in-memory secrets cache."""
    _cache.clear()
