"""UserDirective model — stores active user instructions (watch, remind, add provider)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from hanford.database import Base


class UserDirective(Base):
    __tablename__ = "user_directives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_intent: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # LLM-parsed summary
    directive_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # watch_email | watch_provider | reminder | add_provider
    parameters_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}"
    )  # structured params extracted from instruction
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active"
    )  # active | completed | cancelled
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    channel_created_from: Mapped[str] = mapped_column(
        String(32), nullable=False, default="tui"
    )  # tui | telegram | whatsapp

    def __repr__(self) -> str:
        return f"<UserDirective {self.directive_type} status={self.status}>"
