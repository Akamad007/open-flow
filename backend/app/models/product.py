"""Product ORM model — one branded SKU per ad project (cap=1 in v1)."""

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    physical_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_marks: Mapped[str | None] = mapped_column(Text, nullable=True)
    color_palette: Mapped[str | None] = mapped_column(Text, nullable=True)
    hero_angle: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_uploaded_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reference_image_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    project = relationship("Project", back_populates="products")

    def __repr__(self) -> str:
        return f"<Product {self.id} name={self.canonical_name!r}>"
