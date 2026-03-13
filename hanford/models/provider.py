"""Provider model — represents a service provider in the user's estate."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hanford.database import Base


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # telecom | utility | insurance | healthcare
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    account_identifier: Mapped[str | None] = mapped_column(String(256), nullable=True)
    email_sender_pattern: Mapped[str] = mapped_column(
        String(512), nullable=False, default=""
    )  # regex
    baseline_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    baseline_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    bills: Mapped[list["Bill"]] = relationship(  # noqa: F821
        "Bill", back_populates="provider", lazy="selectin"
    )
    interactions: Mapped[list["Interaction"]] = relationship(  # noqa: F821
        "Interaction", back_populates="provider", lazy="selectin"
    )
    pending_actions: Mapped[list["PendingAction"]] = relationship(  # noqa: F821
        "PendingAction", back_populates="provider", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Provider {self.slug} ({self.category})>"
