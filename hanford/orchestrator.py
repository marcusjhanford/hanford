"""Orchestrator — core async event loop. Routes events to agents. Manages approval queue."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from hanford.agents.call_agent import CallAgent
from hanford.channels.channel_manager import ChannelManager
from hanford.config import Config
from hanford.database import get_session
from hanford.intent.router import IntentResult, IntentRouter, IntentType
from hanford.llm import LLMClient, LLMMessage, strip_code_fences
from hanford.models.bill import Bill
from hanford.models.interaction import Interaction
from hanford.models.pending_action import PendingAction
from hanford.models.provider import Provider
from hanford.models.user_directive import UserDirective
from hanford.monitor.anomaly_detector import AnomalyDetector
from hanford.monitor.bill_parser import BillParser
from hanford.monitor.gmail_watcher import GmailWatcher

logger = logging.getLogger(__name__)

DIRECTIVE_PARSE_PROMPT = """Parse this user instruction into a structured directive.

User said: "{instruction}"

Return a JSON object with:
- "directive_type": one of "watch_email", "watch_provider", "reminder", "add_provider"
- "parsed_intent": a concise summary of what the user wants
- "parameters": an object containing structured parameters:
  For watch_email:
    - "sender_pattern": regex pattern for email sender (lowercase)
    - "subject_keywords": list of keywords to match in subject
    - "notify_message": message to show user when matched
  For add_provider:
    - "provider_slug": slug for the provider
    - "provider_name": display name
    - "category": "telecom" | "utility" | "insurance" | "healthcare"
  For watch_provider:
    - "provider_slug": slug to watch
  For reminder:
    - "reminder_text": what to remind about

Return only valid JSON.
"""

STATUS_FORMAT_PROMPT = """Format this data into a concise, plain English status summary.
Keep it to 2-4 sentences. Be conversational.

Data:
- Active pending actions: {pending_count}
- Pending action details: {pending_details}
- In-progress interactions: {in_progress_count}
- Active directives: {directive_count}
- Directive details: {directive_details}
- Recent completed interactions: {recent_details}
- Gmail monitoring: {gmail_status}
- Active channel: {channel}

Return only the plain text summary.
"""


class Orchestrator:
    """
    Core async event loop (asyncio). Routes events to agents.
    Manages approval queue. Owns intent router.

    The orchestrator communicates EXCLUSIVELY through ChannelManager,
    never directly with TUI or messaging code.
    """

    def __init__(
        self,
        config: Config,
        channel_manager: ChannelManager,
    ) -> None:
        self._config = config
        self._channel_manager = channel_manager
        self._intent_router = IntentRouter(config)
        self._bill_parser = BillParser(config)
        self._anomaly_detector = AnomalyDetector(config)
        self._call_agent = CallAgent(config)
        self._gmail_watcher = GmailWatcher(config)
        self._llm = LLMClient(config)
        self._running = False
        self._call_semaphore = asyncio.Semaphore(config.max_concurrent_calls)

    async def start(self) -> None:
        """
        Boot the orchestrator:
        1. Restore channel state from DB
        2. Register message callback
        3. Start Gmail watcher
        4. Start the active channel
        """
        self._running = True

        # Register the message callback on all channels
        self._channel_manager.set_message_callback(self._on_user_message)

        # Restore persisted channel state
        await self._channel_manager.restore_from_db()

        # Start the active channel
        await self._channel_manager.start_active()

        # Start Gmail monitoring
        await self._gmail_watcher.start(
            on_bill_email=self._on_bill_email,
            on_directive_match=self._on_directive_match,
        )

        logger.info(
            "Orchestrator started. Active channel: %s",
            self._channel_manager.active_channel_name,
        )

    async def stop(self) -> None:
        """Gracefully shut down all subsystems."""
        self._running = False
        await self._gmail_watcher.stop()
        await self._channel_manager.stop_active()
        logger.info("Orchestrator stopped.")

    async def force_gmail_sync(self) -> None:
        """Force an immediate Gmail poll (triggered by TUI refresh)."""
        await self._gmail_watcher.force_sync()

    # ------------------------------------------------------------------
    # Message handling — every user message routes through IntentRouter
    # ------------------------------------------------------------------

    async def _on_user_message(self, message: str) -> None:
        """
        Entry point for ALL user messages, regardless of channel.
        Routes through IntentRouter before anything acts on it.
        """
        if not self._running:
            return

        # Get pending actions for context
        pending = await self._get_pending_actions()

        # Route through intent classifier
        intent_result = await self._intent_router.route(message, pending)
        logger.info(
            "Intent: %s (confidence=%.2f) from '%s'",
            intent_result.intent.value,
            intent_result.confidence,
            message[:80],
        )

        # Dispatch based on intent
        handlers = {
            IntentType.APPROVE: self._handle_approve,
            IntentType.REJECT: self._handle_reject,
            IntentType.SWITCH_TO_MESSAGING: self._handle_switch_to_messaging,
            IntentType.SWITCH_TO_TUI: self._handle_switch_to_tui,
            IntentType.NEW_DIRECTIVE: self._handle_new_directive,
            IntentType.STATUS_REQUEST: self._handle_status_request,
            IntentType.UNKNOWN: self._handle_unknown,
        }

        handler = handlers.get(intent_result.intent, self._handle_unknown)
        await handler(intent_result)

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_approve(self, result: IntentResult) -> None:
        """Approve the most recent pending action."""
        pending = await self._get_pending_actions()
        if not pending:
            await self._channel_manager.send_notification(
                "No pending actions to approve."
            )
            return

        action = pending[0]  # Most recent
        session = await get_session()
        try:
            action_obj = await session.get(PendingAction, action.id)
            if action_obj:
                action_obj.status = "approved"
                action_obj.resolved_at = datetime.utcnow()
                await session.commit()

                await self._channel_manager.send_notification(
                    f"Approved. Executing action against "
                    f"{json.loads(action_obj.context_json).get('provider_name', 'provider')}..."
                )

                # Dispatch the agent
                asyncio.create_task(self._execute_approved_action(action_obj))
        finally:
            await session.close()

    async def _handle_reject(self, result: IntentResult) -> None:
        """Reject the most recent pending action."""
        pending = await self._get_pending_actions()
        if not pending:
            await self._channel_manager.send_notification(
                "No pending actions to dismiss."
            )
            return

        action = pending[0]
        session = await get_session()
        try:
            action_obj = await session.get(PendingAction, action.id)
            if action_obj:
                action_obj.status = "rejected"
                action_obj.resolved_at = datetime.utcnow()
                await session.commit()

                await self._channel_manager.send_notification("Action dismissed.")
        finally:
            await session.close()

    async def _handle_switch_to_messaging(self, result: IntentResult) -> None:
        """Switch to a messaging channel (Telegram or WhatsApp)."""
        target = result.channel_target or "telegram"
        await self._channel_manager.switch_to(target)

    async def _handle_switch_to_tui(self, result: IntentResult) -> None:
        """Switch back to the TUI channel."""
        await self._channel_manager.switch_to("tui")

    async def _handle_new_directive(self, result: IntentResult) -> None:
        """Parse and store a new user directive."""
        directive = await self._parse_directive(result.raw_message)
        if not directive:
            await self._channel_manager.send_notification(
                "I understood that as a new instruction, but I couldn't parse the details. "
                "Could you rephrase?"
            )
            return

        # Save to DB
        session = await get_session()
        try:
            user_directive = UserDirective(
                raw_instruction=result.raw_message,
                parsed_intent=directive.get("parsed_intent", ""),
                directive_type=directive.get("directive_type", "watch_email"),
                parameters_json=json.dumps(directive.get("parameters", {})),
                status="active",
                created_at=datetime.utcnow(),
                channel_created_from=self._channel_manager.active_channel_name,
            )
            session.add(user_directive)
            await session.commit()

            # Handle add_provider directive immediately
            if directive.get("directive_type") == "add_provider":
                await self._handle_add_provider(directive.get("parameters", {}))

            # Confirm to user
            parsed_intent = directive.get("parsed_intent", result.raw_message)
            await self._channel_manager.send_notification(f"Got it -- {parsed_intent}")
        except Exception as exc:
            await session.rollback()
            logger.error("Error saving directive: %s", exc)
            await self._channel_manager.send_notification(
                "Something went wrong saving that instruction. Please try again."
            )
        finally:
            await session.close()

    async def _handle_status_request(self, result: IntentResult) -> None:
        """Generate and send a status summary."""
        summary = await self._generate_status()
        await self._channel_manager.send_status(summary)

    async def _handle_unknown(self, result: IntentResult) -> None:
        """Handle unclassifiable messages."""
        await self._channel_manager.send_notification(
            "I didn't quite understand that. You can say yes/no to approve actions, "
            "or give me a new instruction."
        )

    # ------------------------------------------------------------------
    # Bill detection pipeline
    # ------------------------------------------------------------------

    async def _on_bill_email(
        self,
        provider_slug: str,
        message_id: str,
        subject: str,
        body: str,
        snippet: str,
    ) -> None:
        """
        Callback from GmailWatcher when a bill email is detected.
        Pipeline: parse -> anomaly check -> create PendingAction -> notify user.
        """
        session = await get_session()
        try:
            # Check for deduplication
            existing = await session.execute(
                select(Bill).where(Bill.gmail_message_id == message_id)
            )
            if existing.scalar_one_or_none():
                logger.info("Bill already processed: %s", message_id)
                return

            # Look up provider
            provider_result = await session.execute(
                select(Provider).where(Provider.slug == provider_slug)
            )
            provider = provider_result.scalar_one_or_none()
            if not provider:
                logger.warning("Provider not found for slug: %s", provider_slug)
                return

            # Parse the bill
            parsed = await self._bill_parser.parse(body)
            if not parsed:
                logger.info("Could not parse bill from email: %s", subject)
                return

            # Analyze for anomalies
            anomaly = await self._anomaly_detector.analyze(
                session=session,
                provider_id=provider.id,
                current_amount=parsed.amount,
                baseline_amount=provider.baseline_amount,
            )

            # Save the bill
            bill = Bill(
                provider_id=provider.id,
                amount=parsed.amount,
                due_date=parsed.due_date,
                billing_period_start=parsed.billing_period_start,
                billing_period_end=parsed.billing_period_end,
                gmail_message_id=message_id,
                raw_email_snippet=snippet[:2000],
                parsed_at=datetime.utcnow(),
                anomaly_score=anomaly.score,
                anomaly_reason=anomaly.reason,
            )
            session.add(bill)
            await session.flush()

            if anomaly.is_anomalous:
                # Create pending action
                due_str = str(parsed.due_date) if parsed.due_date else "upcoming"
                deviation_pct = round(anomaly.deviation_pct * 100)
                action_summary = f"Call {provider.name} and negotiate back to ~${anomaly.baseline_amount:.0f}/mo."

                context = {
                    "provider_name": provider.name,
                    "provider_slug": provider.slug,
                    "phone_number": provider.phone_number,
                    "current_amount": parsed.amount,
                    "baseline_amount": anomaly.baseline_amount,
                    "due_date": due_str,
                    "deviation_pct": deviation_pct,
                    "user_name": self._config.user_name,
                    "account_identifier": provider.account_identifier or "",
                    "bill_id": bill.id,
                }

                pending = PendingAction(
                    provider_id=provider.id,
                    bill_id=bill.id,
                    action_type="call",
                    proposed_action_summary=action_summary,
                    context_json=json.dumps(context),
                    status="awaiting_approval",
                    created_at=datetime.utcnow(),
                )
                session.add(pending)
                await session.flush()

                await session.commit()

                # Notify user through the active channel
                await self._channel_manager.request_approval(pending)
            else:
                # Update baseline if amount is normal
                if parsed.amount > 0:
                    provider.baseline_amount = anomaly.baseline_amount
                    provider.baseline_updated_at = datetime.utcnow()

                await session.commit()
                logger.info(
                    "Bill from %s ($%.2f) within normal range.",
                    provider.name,
                    parsed.amount,
                )

        except Exception as exc:
            await session.rollback()
            logger.error("Error processing bill email: %s", exc)
        finally:
            await session.close()

    async def _on_directive_match(
        self,
        directive_id: int,
        message_subject: str,
        message_snippet: str,
    ) -> None:
        """Callback from GmailWatcher when an email matches a user directive."""
        session = await get_session()
        try:
            directive = await session.get(UserDirective, directive_id)
            if not directive:
                return

            params = (
                json.loads(directive.parameters_json)
                if directive.parameters_json
                else {}
            )
            notify_message = params.get(
                "notify_message",
                f"Email matching your watch arrived: {message_subject}",
            )

            await self._channel_manager.send_notification(notify_message)

            # Mark directive as completed
            directive.status = "completed"
            directive.completed_at = datetime.utcnow()
            await session.commit()

        except Exception as exc:
            await session.rollback()
            logger.error("Error handling directive match: %s", exc)
        finally:
            await session.close()

    # ------------------------------------------------------------------
    # Agent execution
    # ------------------------------------------------------------------

    async def _execute_approved_action(self, action: PendingAction) -> None:
        """Execute an approved action by dispatching the appropriate agent."""
        context = json.loads(action.context_json) if action.context_json else {}

        session = await get_session()
        try:
            # Create interaction record
            interaction = Interaction(
                provider_id=action.provider_id,
                bill_id=action.bill_id,
                type=action.action_type,
                status="in_progress",
                initiated_at=datetime.utcnow(),
            )
            session.add(interaction)
            await session.commit()

            provider_slug = context.get("provider_slug", "")

            # Notify user that action is starting
            provider_name = context.get("provider_name", "the provider")
            await self._channel_manager.send_notification(
                f"Calling {provider_name}... I'll update you when done."
            )

            # Execute with semaphore to limit concurrent calls
            async with self._call_semaphore:
                agent_result = await self._call_agent.execute(provider_slug, context)

            # Update interaction record
            interaction.status = "completed" if agent_result.success else "failed"
            interaction.completed_at = datetime.utcnow()
            interaction.outcome = agent_result.outcome
            interaction.outcome_summary = agent_result.outcome_summary
            interaction.transcript = agent_result.transcript
            interaction.amount_saved = agent_result.amount_saved
            interaction.vapi_call_id = agent_result.external_id

            # Mark pending action as executed
            action_obj = await session.get(PendingAction, action.id)
            if action_obj:
                action_obj.status = "executed"
                action_obj.resolved_at = datetime.utcnow()

            await session.commit()

            # Report result to user
            if agent_result.success and agent_result.amount_saved:
                await self._channel_manager.send_notification(
                    f"{provider_name} call complete. "
                    f"Saved ${agent_result.amount_saved:.2f}/mo. "
                    f"{agent_result.outcome_summary}"
                )
            elif agent_result.success:
                await self._channel_manager.send_notification(
                    f"{provider_name} call complete. {agent_result.outcome_summary}"
                )
            else:
                await self._channel_manager.send_notification(
                    f"{provider_name} call result: {agent_result.outcome_summary}"
                )

        except Exception as exc:
            logger.error("Error executing action: %s", exc)
            await self._channel_manager.send_notification(
                f"Error executing action: {exc}"
            )
            await session.rollback()
        finally:
            await session.close()

    # ------------------------------------------------------------------
    # Directive parsing
    # ------------------------------------------------------------------

    async def _parse_directive(self, instruction: str) -> dict[str, Any] | None:
        """Use LLM to parse a user instruction into a structured directive."""
        prompt = DIRECTIVE_PARSE_PROMPT.format(instruction=instruction)

        try:
            response = await self._llm.chat_completion(
                messages=[
                    LLMMessage(
                        role="system",
                        content="You are a precise instruction parser. Return only valid JSON.",
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                max_tokens=512,
            )

            raw = strip_code_fences(response.content)
            return json.loads(raw)

        except (json.JSONDecodeError, Exception) as exc:
            logger.error("Directive parse error: %s", exc)
            return None

    async def _handle_add_provider(self, params: dict[str, Any]) -> None:
        """Handle an add_provider directive by creating a new Provider record."""
        slug = params.get("provider_slug", "")
        if not slug:
            return

        session = await get_session()
        try:
            # Check if provider already exists
            existing = await session.execute(
                select(Provider).where(Provider.slug == slug)
            )
            if existing.scalar_one_or_none():
                await self._channel_manager.send_notification(
                    f"{slug} is already in your providers."
                )
                return

            # Try to load from knowledge base
            from pathlib import Path

            import yaml

            yaml_path = (
                Path(__file__).resolve().parent
                / "knowledge"
                / "providers"
                / f"{slug}.yaml"
            )
            profile = {}
            if yaml_path.exists():
                with open(yaml_path) as f:
                    profile = yaml.safe_load(f) or {}

            provider = Provider(
                name=params.get("provider_name", profile.get("name", slug.title())),
                slug=slug,
                category=params.get("category", profile.get("category", "telecom")),
                phone_number=profile.get("phone_number", ""),
                email_sender_pattern=profile.get("email_sender_pattern", ""),
                baseline_amount=0.0,
                is_active=True,
                created_at=datetime.utcnow(),
            )
            session.add(provider)
            await session.commit()

        except Exception as exc:
            await session.rollback()
            logger.error("Error adding provider: %s", exc)
        finally:
            await session.close()

    # ------------------------------------------------------------------
    # Status generation
    # ------------------------------------------------------------------

    async def _generate_status(self) -> str:
        """Generate a plain English status summary using LLM."""
        session = await get_session()
        try:
            # Pending actions
            pending_result = await session.execute(
                select(PendingAction).where(PendingAction.status == "awaiting_approval")
            )
            pending = pending_result.scalars().all()

            # In-progress interactions
            in_progress_result = await session.execute(
                select(Interaction).where(Interaction.status == "in_progress")
            )
            in_progress = in_progress_result.scalars().all()

            # Active directives
            directives_result = await session.execute(
                select(UserDirective).where(UserDirective.status == "active")
            )
            directives = directives_result.scalars().all()

            # Recent completed interactions
            recent_result = await session.execute(
                select(Interaction)
                .where(Interaction.status == "completed")
                .order_by(Interaction.completed_at.desc())
                .limit(3)
            )
            recent = recent_result.scalars().all()

            # Format details
            pending_details = (
                "; ".join(
                    f"{p.action_type} for provider #{p.provider_id}: {p.proposed_action_summary}"
                    for p in pending
                )
                or "None"
            )

            directive_details = (
                "; ".join(f"{d.directive_type}: {d.parsed_intent}" for d in directives)
                or "None"
            )

            recent_details = (
                "; ".join(
                    f"{r.type} ({r.outcome}): {r.outcome_summary}" for r in recent
                )
                or "None"
            )

            prompt = STATUS_FORMAT_PROMPT.format(
                pending_count=len(pending),
                pending_details=pending_details,
                in_progress_count=len(in_progress),
                directive_count=len(directives),
                directive_details=directive_details,
                recent_details=recent_details,
                gmail_status="active" if self._gmail_watcher._running else "inactive",
                channel=self._channel_manager.active_channel_name,
            )

            response = await self._llm.chat_completion(
                messages=[
                    LLMMessage(
                        role="system",
                        content="You are Hanford, a life administration agent. Be concise and conversational.",
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.3,
                max_tokens=256,
            )

            return response.content or "All quiet. Nothing to report."

        except Exception as exc:
            logger.error("Status generation error: %s", exc)
            return "Currently monitoring. Use the dashboard for detailed status."
        finally:
            await session.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_pending_actions(self) -> list[PendingAction]:
        """Fetch all actions awaiting approval, most recent first."""
        session = await get_session()
        try:
            result = await session.execute(
                select(PendingAction)
                .where(PendingAction.status == "awaiting_approval")
                .order_by(PendingAction.created_at.desc())
            )
            return list(result.scalars().all())
        finally:
            await session.close()
