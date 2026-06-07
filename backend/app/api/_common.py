"""Shared API helpers for consistent error handling across routers."""
from __future__ import annotations

from typing import Type, TypeVar

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")

# Documented on every router so Swagger shows the standard 404 shape.
NOT_FOUND_RESPONSE = {404: {"description": "Resource not found"}}


async def get_or_404(db: AsyncSession, model: Type[T], obj_id, name: str | None = None) -> T:
    """Fetch a row by primary key or raise a standardized 404."""
    obj = await db.get(model, obj_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{name or model.__name__} not found",
        )
    return obj
