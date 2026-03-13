"""Interaction model — records each action taken against a provider."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hanford.database import Base


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("providers.id"), nullable=False
    )
    bill_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("bills.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # call | email | web
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )  # pending | in_progress | completed | failed
    initiated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outcome: Mapped[str] = mapped_column(
        String(64), nullable=False, default=""
    )  # success | failure | escalation_needed | no_answer
    outcome_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_saved: Mapped[float | None] = mapped_column(Float, nullable=True)
    vapi_call_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")

    # Relationships
    provider: Mapped["Provider"] = relationship(  # noqa: F821
        "Provider", back_populates="interactions"
    )

    def __repr__(self) -> str:
        return f"<Interaction {self.type} provider={self.provider_id} status={self.status}>"
