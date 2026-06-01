"""Products API router — list/get/update branded SKUs per project."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.product import Product
from app.schemas.product import ProductRead, ProductUpdate

router = APIRouter(tags=["products"])


@router.get("/projects/{project_id}/products", response_model=List[ProductRead])
async def list_products(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Product).where(Product.project_id == project_id).order_by(Product.canonical_name)
    result = await db.execute(stmt)
    return [ProductRead.model_validate(p) for p in result.scalars().all()]


@router.get("/products/{product_id}", response_model=ProductRead)
async def get_product(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductRead.model_validate(product)


@router.put("/products/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: uuid.UUID,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(product, key, value)

    await db.flush()
    await db.refresh(product)
    return ProductRead.model_validate(product)
