"""ChannelState model — single-row table persisting active channel across restarts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from hanford.database import Base


class ChannelState(Base):
    __tablename__ = "channel_state"

    # Single-row table. Always upsert row id=1.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    active_channel: Mapped[str] = mapped_column(
        String(32), nullable=False, default="tui"
    )  # tui | telegram | whatsapp
    switched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    switched_by: Mapped[str] = mapped_column(
        String(64), nullable=False, default="startup"
    )  # user_command | startup

    def __repr__(self) -> str:
        return f"<ChannelState active={self.active_channel}>"
