"""Bill model — represents a parsed bill detected from email."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hanford.database import Base


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("providers.id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    billing_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    billing_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    gmail_message_id: Mapped[str] = mapped_column(
        String(256), unique=True, nullable=False
    )  # deduplication
    raw_email_snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parsed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    anomaly_reason: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    # Relationships
    provider: Mapped["Provider"] = relationship(  # noqa: F821
        "Provider", back_populates="bills"
    )

    def __repr__(self) -> str:
        return f"<Bill provider={self.provider_id} amount={self.amount}>"
