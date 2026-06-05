"""Optional API-key authentication.

When ``settings.api_key`` is empty (the default) auth is disabled and every
request is allowed — convenient for local / trusted-LAN use. When it is set,
all ``/api`` routes require an ``X-API-Key`` header matching it. Health,
readiness, docs and static assets stay open so liveness probes and the API docs
keep working. See SECURITY.md.
"""

from fastapi import Header, HTTPException, Request, status

from app.config import settings

_OPEN_PREFIXES = (
    "/api/health",
    "/api/readiness",
    "/api/liveness",
    "/storage",
    "/docs",
    "/openapi.json",
    "/redoc",
)


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    if not settings.api_key:
        return  # auth disabled (default)
    path = request.url.path
    if any(path.startswith(p) for p in _OPEN_PREFIXES):
        return
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )
