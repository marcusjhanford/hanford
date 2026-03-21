"""Tests for the channel manager module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hanford.channels.base_channel import BaseChannel
from hanford.channels.channel_manager import ChannelManager
from hanford.models.pending_action import PendingAction


class MockChannel(BaseChannel):
    """Test double for BaseChannel."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name
        self.started = False
        self.stopped = False
        self.notifications: list[str] = []
        self.approvals: list[PendingAction] = []
        self.statuses: list[str] = []

    @property
    def channel_name(self) -> str:
        return self._name

    async def start(self) -> None:
        self.started = True
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True
        self.started = False

    async def send_notification(self, message: str) -> None:
        self.notifications.append(message)

    async def request_approval(self, action: PendingAction) -> None:
        self.approvals.append(action)

    async def send_status(self, status_summary: str) -> None:
        self.statuses.append(status_summary)


class TestChannelManager:
    """Tests for ChannelManager."""

    @pytest.fixture
    def tui(self):
        return MockChannel("tui")

    @pytest.fixture
    def telegram(self):
        return MockChannel("telegram")

    @pytest.fixture
    def whatsapp(self):
        return MockChannel("whatsapp")

    @pytest.fixture
    def manager(self, tui, telegram, whatsapp):
        return ChannelManager(tui=tui, telegram=telegram, whatsapp=whatsapp)

    # --- Basic properties ---

    def test_active_channel_defaults_to_tui(self, manager, tui):
        assert manager.active_channel is tui
        assert manager.active_channel_name == "tui"

    # --- Delegation ---

    @pytest.mark.asyncio
    async def test_send_notification_delegates(self, manager, tui):
        await manager.send_notification("test message")
        assert "test message" in tui.notifications

    @pytest.mark.asyncio
    async def test_request_approval_delegates(self, manager, tui):
        action = MagicMock(spec=PendingAction)
        await manager.request_approval(action)
        assert action in tui.approvals

    @pytest.mark.asyncio
    async def test_send_status_delegates(self, manager, tui):
        await manager.send_status("all good")
        assert "all good" in tui.statuses

    # --- Switching ---

    @pytest.mark.asyncio
    async def test_switch_to_telegram(self, manager, tui, telegram):
        """Test switching from TUI to Telegram."""
        with patch.object(manager, "_persist_channel_state", new_callable=AsyncMock):
            success = await manager.switch_to("telegram")

        assert success is True
        assert tui.stopped is True
        assert telegram.started is True
        assert manager.active_channel is telegram
        assert "Switched to telegram" in telegram.notifications[0]

    @pytest.mark.asyncio
    async def test_switch_to_whatsapp(self, manager, tui, whatsapp):
        """Test switching from TUI to WhatsApp."""
        with patch.object(manager, "_persist_channel_state", new_callable=AsyncMock):
            success = await manager.switch_to("whatsapp")

        assert success is True
        assert manager.active_channel is whatsapp

    @pytest.mark.asyncio
    async def test_switch_back_to_tui(self, manager, tui, telegram):
        """Test switching to Telegram then back to TUI."""
        with patch.object(manager, "_persist_channel_state", new_callable=AsyncMock):
            await manager.switch_to("telegram")
            success = await manager.switch_to("tui")

        assert success is True
        assert manager.active_channel is tui
        assert tui.started is True

    @pytest.mark.asyncio
    async def test_switch_to_unconfigured_channel(self, tui):
        """Test switching to a channel that isn't configured."""
        manager = ChannelManager(tui=tui, telegram=None, whatsapp=None)
        success = await manager.switch_to("telegram")

        assert success is False
        assert "not configured" in tui.notifications[0].lower()

    @pytest.mark.asyncio
    async def test_switch_to_same_channel(self, manager, tui):
        """Test switching to the already active channel."""
        success = await manager.switch_to("tui")

        assert success is False
        assert "Already on" in tui.notifications[0]

    # --- Message callback ---

    def test_set_message_callback(self, manager, tui, telegram, whatsapp):
        """Test that message callback is registered on all channels."""
        callback = AsyncMock()
        manager.set_message_callback(callback)

        assert tui._on_message is callback
        assert telegram._on_message is callback
        assert whatsapp._on_message is callback

    # --- Start/Stop ---

    @pytest.mark.asyncio
    async def test_start_active(self, manager, tui):
        await manager.start_active()
        assert tui.started is True

    @pytest.mark.asyncio
    async def test_stop_active(self, manager, tui):
        await manager.start_active()
        await manager.stop_active()
        assert tui.stopped is True

    # --- I/O routing after switch ---

    @pytest.mark.asyncio
    async def test_notification_routes_to_new_channel_after_switch(
        self, manager, tui, telegram
    ):
        """After switching, notifications go to the new channel."""
        with patch.object(manager, "_persist_channel_state", new_callable=AsyncMock):
            await manager.switch_to("telegram")

        # Clear the switch confirmation message
        telegram.notifications.clear()

        await manager.send_notification("test after switch")
        assert "test after switch" in telegram.notifications
        assert "test after switch" not in tui.notifications
