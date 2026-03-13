"""PendingAction model — queued actions awaiting user approval."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hanford.database import Base


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("providers.id"), nullable=False
    )
    bill_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bills.id"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # call | email | web
    proposed_action_summary: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}"
    )  # all data the agent needs to execute
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="awaiting_approval"
    )  # awaiting_approval | approved | rejected | executed
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    provider: Mapped["Provider"] = relationship(  # noqa: F821
        "Provider", back_populates="pending_actions"
    )

    def __repr__(self) -> str:
        return f"<PendingAction {self.action_type} provider={self.provider_id} status={self.status}>"
