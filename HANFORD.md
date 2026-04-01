# Hanford — Technical Specification v0.1
> Life administration agent. Monitors your bills, detects anomalies, calls companies on your behalf, reports back.
> Self-hosted TUI. Travels with you via WhatsApp or Telegram. Open source. Bring your own API keys.

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [Repository Structure](#3-repository-structure)
4. [Data Models](#4-data-models)
5. [Core Modules](#5-core-modules)
6. [Channel System](#6-channel-system)
7. [Agent Workflows](#7-agent-workflows)
8. [TUI Design](#8-tui-design)
9. [External Integrations](#9-external-integrations)
10. [Configuration & Setup](#10-configuration--setup)
11. [v0.1 Scope & Explicit Exclusions](#11-v01-scope--explicit-exclusions)
12. [v0.2 Roadmap Hooks](#12-v02-roadmap-hooks)

---

## 1. Project Overview

### What Hanford Is
Hanford is an open-source, self-hosted AI agent that monitors your bills and digital correspondence, detects anomalies, surfaces proposed actions, and — upon approval — executes those actions autonomously. In v0.1, the primary action is placing an outbound AI phone call to dispute or negotiate with a service provider.

Hanford travels with you. By default it lives in your terminal as a TUI. At any time you can say "switch to text mode" and it migrates to WhatsApp or Telegram, where it continues to notify you, ask for approvals, and accept new instructions — then switches back when you return to your device.

### Design Philosophy
- **The agent travels with you.** Hanford is not tied to a terminal. It follows you into whichever channel you're in.
- **Act-and-report, not ask-and-wait.** Hanford works in the background. It surfaces decisions, not tasks.
- **Confirm before irreversible actions.** Any call, form submission, or correspondence requires explicit approval — regardless of which channel you're in.
- **Directable.** You can give Hanford new instructions at any time in natural language. It understands the difference between approving an action, switching channels, and giving a new directive.
- **Bring your own keys.** All API keys are user-supplied and stored locally. Hanford never phones home.
- **Composable by community.** Provider profiles and negotiation scripts are YAML/Markdown files the community can extend via pull requests.

### v0.1 Capability Set
- Gmail monitoring for bills and statements
- Anomaly detection (current bill vs. baseline)
- Notification + approval gate via active channel (TUI or messaging)
- Outbound AI voice call via Vapi.ai
- Call transcript + outcome logging
- SQLite-backed estate map (providers, baselines, history)
- Channel switching: TUI ↔ WhatsApp or Telegram
- Natural language directives: "watch for X", "remind me about Y", "add Z as a provider"

### Supported Domains in v0.1
- Telecom (internet, cable, mobile)
- Utilities (electricity, gas, water)
- Insurance (auto, home, health — billing disputes only)
- Healthcare (billing errors, EOB discrepancies)

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                        CHANNEL MANAGER                               │
│         Owns the active channel. Routes all I/O through it.          │
│         Handles channel switching. One active channel at a time.     │
└────────────┬─────────────────────────────────────┬───────────────────┘
             │                                     │
    ┌────────▼────────┐                   ┌────────▼────────────────┐
    │   TUI CHANNEL   │                   │   MESSAGING CHANNEL     │
    │   (Textual)     │                   │   WhatsApp / Telegram   │
    │                 │                   │   (user configures one) │
    │ Notifications   │                   │                         │
    │ Action Cards    │                   │ Inbound message handler │
    │ History         │                   │ Outbound notifications  │
    │ Settings        │                   │ Approval via reply      │
    └────────┬────────┘                   └────────┬────────────────┘
             │                                     │
             └──────────────────┬──────────────────┘
                                │
             ┌──────────────────▼──────────────────┐
             │            ORCHESTRATOR              │
             │   Core async event loop (asyncio)    │
             │   Routes events → agents             │
             │   Manages approval queue             │
             │   Owns intent router                 │
             └───────┬──────────────────┬───────────┘
                     │                  │
          ┌──────────▼──────┐  ┌────────▼──────────────┐
          │  MONITOR MODULE │  │    AGENT MODULE        │
          │                 │  │                        │
          │ Gmail watcher   │  │ Call Agent (v0.1)      │
          │ Bill parser     │  │ (v0.2) Web Agent       │
          │ Anomaly detect  │  │ (v0.2) Email Agent     │
          │ Estate updater  │  │                        │
          └──────────┬──────┘  └────────┬───────────────┘
                     │                  │
          ┌──────────▼──────────────────▼───────────────┐
          │                DATA LAYER                    │
          │            SQLite via SQLAlchemy             │
          │  providers | bills | interactions |          │
          │  pending_actions | channel_state |           │
          │  user_directives                             │
          └─────────────────────────────────────────────┘
                     │                  │
          ┌──────────▼──────┐  ┌────────▼──────────────┐
          │  EXTERNAL APIs  │  │   KNOWLEDGE BASE       │
          │                 │  │                        │
          │ Gmail API       │  │ Provider profiles      │
          │ Vapi.ai         │  │ Negotiation scripts    │
          │ OpenAI          │  │ IVR navigation maps    │
          │ Twilio/Telegram │  │                        │
          └─────────────────┘  └────────────────────────┘
```

### Key Architectural Decisions
- **Channel abstraction is the core primitive.** The orchestrator communicates exclusively through `ChannelManager`, never directly with TUI or messaging code. Adding a new channel is self-contained.
- **One active channel at a time.** Switching channels is atomic. The previous channel goes quiet; the new one becomes the sole I/O surface.
- **Intent router sits between all user messages and the orchestrator.** Every inbound message — whether from TUI input bar or a WhatsApp reply — passes through the intent router before anything acts on it.
- **Async throughout.** `asyncio` is the backbone. Monitor loop, TUI, messaging webhook server, and agent calls coexist without blocking.
- **SQLite is the single source of truth.** Channel state, active directives, and all agent history persist across restarts.

---

## 3. Repository Structure

```
hanford/
├── README.md
├── CONTRIBUTING.md
├── pyproject.toml
├── .env.example
│
├── hanford/
│   ├── __init__.py
│   ├── main.py                      # Entry point: starts TUI + orchestrator
│   ├── config.py                    # Loads .env + user config
│   ├── database.py                  # SQLAlchemy setup, session factory
│   │
│   ├── models/                      # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── provider.py
│   │   ├── bill.py
│   │   ├── interaction.py
│   │   ├── pending_action.py
│   │   ├── channel_state.py         # Persists active channel across restarts
│   │   └── user_directive.py        # Stores active user instructions
│   │
│   ├── monitor/                     # Background monitoring
│   │   ├── __init__.py
│   │   ├── base_watcher.py          # Abstract base for all watchers
│   │   ├── gmail_watcher.py
│   │   ├── bill_parser.py
│   │   └── anomaly_detector.py
│   │
│   ├── agents/                      # Action agents
│   │   ├── __init__.py
│   │   ├── base_agent.py            # Abstract base: all agents inherit this
│   │   └── call_agent.py
│   │
│   ├── channels/                    # Channel system
│   │   ├── __init__.py
│   │   ├── base_channel.py          # Abstract BaseChannel
│   │   ├── channel_manager.py       # Owns active channel, handles switching
│   │   ├── tui_channel.py           # Bridges Textual app ↔ BaseChannel interface
│   │   ├── telegram_channel.py      # Telegram bot via python-telegram-bot
│   │   └── whatsapp_channel.py      # WhatsApp via Twilio
│   │
│   ├── intent/
│   │   ├── __init__.py
│   │   └── router.py                # Classifies inbound messages, routes to handler
│   │
│   ├── orchestrator.py
│   │
│   ├── tui/                         # Textual TUI (UI only — logic lives in orchestrator)
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── screens/
│   │   │   ├── dashboard.py
│   │   │   ├── action_card.py
│   │   │   └── settings.py
│   │   └── widgets/
│   │       ├── notification_list.py
│   │       ├── history_table.py
│   │       ├── input_bar.py         # Natural language input (always visible)
│   │       └── status_bar.py
│   │
│   └── knowledge/
│       ├── providers/
│       │   ├── att.yaml
│       │   ├── comcast.yaml
│       │   ├── verizon.yaml
│       │   ├── spectrum.yaml
│       │   └── _template.yaml
│       └── scripts/
│           ├── telecom_dispute.md
│           ├── utility_dispute.md
│           └── insurance_billing.md
│
└── tests/
    ├── test_bill_parser.py
    ├── test_anomaly_detector.py
    ├── test_call_agent.py
    ├── test_intent_router.py
    └── test_channel_manager.py
```

---

## 4. Data Models

### 4.1 Provider
```python
class Provider(Base):
    __tablename__ = "providers"

    id: int (primary key)
    name: str
    slug: str                        # matches knowledge/providers/*.yaml
    category: str                    # "telecom" | "utility" | "insurance" | "healthcare"
    phone_number: str
    account_identifier: str          # nullable
    email_sender_pattern: str        # regex
    baseline_amount: float
    baseline_updated_at: datetime
    created_at: datetime
    is_active: bool
```

### 4.2 Bill
```python
class Bill(Base):
    __tablename__ = "bills"

    id: int (primary key)
    provider_id: int (FK → providers.id)
    amount: float
    due_date: date
    billing_period_start: date       # nullable
    billing_period_end: date         # nullable
    gmail_message_id: str            # deduplication
    raw_email_snippet: str
    parsed_at: datetime
    anomaly_score: float             # 0.0–1.0
    anomaly_reason: str
```

### 4.3 Interaction
```python
class Interaction(Base):
    __tablename__ = "interactions"

    id: int (primary key)
    provider_id: int (FK → providers.id)
    bill_id: int (FK → bills.id, nullable)
    type: str                        # "call" | "email" | "web"
    status: str                      # "pending" | "in_progress" | "completed" | "failed"
    initiated_at: datetime
    completed_at: datetime           # nullable
    outcome: str                     # "success" | "failure" | "escalation_needed" | "no_answer"
    outcome_summary: str
    transcript: str                  # nullable
    amount_saved: float              # nullable
    vapi_call_id: str
```

### 4.4 PendingAction
```python
class PendingAction(Base):
    __tablename__ = "pending_actions"

    id: int (primary key)
    provider_id: int (FK → providers.id)
    bill_id: int (FK → bills.id)
    action_type: str                 # "call" | "email" | "web"
    proposed_action_summary: str     # Shown to user
    context_json: str                # All data the agent needs to execute
    status: str                      # "awaiting_approval" | "approved" | "rejected" | "executed"
    created_at: datetime
    resolved_at: datetime            # nullable
```

### 4.5 ChannelState *(new)*
```python
class ChannelState(Base):
    __tablename__ = "channel_state"
    # Single-row table. Always upsert row id=1.

    id: int (primary key, always 1)
    active_channel: str              # "tui" | "telegram" | "whatsapp"
    switched_at: datetime
    switched_by: str                 # "user_command" | "startup"
```

**Purpose:** Hanford persists which channel is active across restarts. If you switch to Telegram and restart Hanford, it comes back in Telegram mode — not TUI mode — so it continues talking to you where you are.

### 4.6 UserDirective *(new)*
```python
class UserDirective(Base):
    __tablename__ = "user_directives"

    id: int (primary key)
    raw_instruction: str             # Original user message
    parsed_intent: str               # LLM-parsed summary of what to watch/do
    directive_type: str              # "watch_email" | "watch_provider" | "reminder" | "add_provider"
    parameters_json: str             # Structured params extracted from instruction
    status: str                      # "active" | "completed" | "cancelled"
    created_at: datetime
    completed_at: datetime           # nullable
    channel_created_from: str        # "tui" | "telegram" | "whatsapp"
```

**Examples of stored directives:**
```json
// "Keep an eye out for a confirmation from United Airlines"
{
  "directive_type": "watch_email",
  "parameters": {
    "sender_pattern": "united|united airlines",
    "subject_keywords": ["confirmation", "booking", "itinerary"],
    "notify_on_match": true
  }
}

// "Add Spectrum to my providers"
{
  "directive_type": "add_provider",
  "parameters": {
    "provider_slug": "spectrum"
  }
}
```

---

## 5. Core Modules

### 5.1 Gmail Watcher (`monitor/gmail_watcher.py`)

Polls Gmail API every `GMAIL_POLL_INTERVAL` seconds. Uses Gmail history API after first sync. On each new email:
1. Checks against known provider patterns (fast path)
2. Checks against active `UserDirective` watch patterns (new in v0.1)
3. If either matches, passes to BillParser or fires a watch notification respectively

```python
class GmailWatcher(BaseWatcher):
    async def start(self, on_bill_email: Callable, on_directive_match: Callable):
        """
        Two callbacks:
        - on_bill_email: triggers bill parse → anomaly → approval flow
        - on_directive_match: triggers immediate notification to user
          e.g. "Got it — United Airlines confirmation just landed in your inbox."
        """
        ...

    async def _check_directive_matches(self, message: EmailMessage) -> list[UserDirective]:
        """
        Loads all active watch_email directives from DB.
        Checks sender and subject against each directive's parameters.
        Returns matching directives (may be multiple).
        No LLM call — pure pattern matching.
        """
        ...
```

### 5.2 Bill Parser (`monitor/bill_parser.py`)
*(unchanged from v1 spec)*

LLM-based structured extraction of amount, due date, billing period from email body. Uses `gpt-4o-mini`. Returns `None` if amount cannot be extracted.

### 5.3 Anomaly Detector (`monitor/anomaly_detector.py`)
*(unchanged from v1 spec)*

Rolling 3-bill average baseline. Configurable threshold (default 15%). Returns anomaly score and human-readable reason string.

### 5.4 Call Agent (`agents/call_agent.py`)
*(unchanged from v1 spec)*

Builds Vapi payload from provider YAML + negotiation script. Dispatches call. Polls for outcome. Parses transcript. Updates Interaction record.

### 5.5 Intent Router (`intent/router.py`) *(new)*

**Responsibility:** Every message a user sends — whether typed in the TUI input bar or sent via WhatsApp/Telegram — passes through the intent router. It classifies the message and returns a structured intent that the orchestrator acts on.

```python
INTENT_CLASSIFICATION_PROMPT = """
Classify the following user message into exactly one intent.

Intents:
- APPROVE: user is approving a pending action (e.g. "yes", "do it", "go ahead", "y")
- REJECT: user is rejecting a pending action (e.g. "no", "cancel", "don't", "n")
- SWITCH_TO_MESSAGING: user wants to switch to WhatsApp or Telegram
  (e.g. "switch to text mode", "message me on telegram", "go to whatsapp")
- SWITCH_TO_TUI: user wants to switch back to terminal
  (e.g. "switch back to device", "back to terminal", "tui mode")
- NEW_DIRECTIVE: user is giving a new standing instruction
  (e.g. "watch for...", "keep an eye on...", "add X as a provider",
   "remind me when...", "track my...")
- STATUS_REQUEST: user asking for a summary of what's happening
  (e.g. "what are you doing?", "any updates?", "status")
- UNKNOWN: cannot classify

Message: "{message}"

Return JSON: {{"intent": "<INTENT>", "confidence": 0.0-1.0, "extracted": "<key info if any>"}}
"""

class IntentRouter:
    async def route(self, message: str, pending_actions: list[PendingAction]) -> IntentResult:
        """
        Fast-path heuristics first (no LLM):
        - Single "y" or "yes" → APPROVE (if pending actions exist)
        - Single "n" or "no" → REJECT (if pending actions exist)
        - Exact phrase match on switch commands → SWITCH_*

        LLM classification for everything else.
        Returns IntentResult with intent type + any extracted params.
        """
        ...
```

**IntentResult routing:**

| Intent | Orchestrator Action |
|--------|-------------------|
| `APPROVE` | `approve_action(most_recent_pending_id)` |
| `REJECT` | `reject_action(most_recent_pending_id)` |
| `SWITCH_TO_MESSAGING` | `channel_manager.switch_to(telegram or whatsapp)` |
| `SWITCH_TO_TUI` | `channel_manager.switch_to(tui)` |
| `NEW_DIRECTIVE` | Parse directive → store `UserDirective` → confirm to user |
| `STATUS_REQUEST` | Generate and send status summary |
| `UNKNOWN` | Reply: "I didn't quite understand that. You can say yes/no to approve actions, or give me a new instruction." |

---

## 6. Channel System

This is the core abstraction that makes Hanford portable.

### 6.1 BaseChannel (`channels/base_channel.py`)

```python
from abc import ABC, abstractmethod

class BaseChannel(ABC):
    """
    All channels implement this interface.
    The orchestrator only ever calls these methods — never channel-specific code.
    """

    @abstractmethod
    async def start(self):
        """Begin listening for inbound messages and/or render UI."""
        ...

    @abstractmethod
    async def stop(self):
        """Gracefully stop. Called before switching to another channel."""
        ...

    @abstractmethod
    async def send_notification(self, message: str):
        """
        Send a plain informational message to the user.
        e.g. "✓ AT&T call complete. Saved $24/mo."
        """
        ...

    @abstractmethod
    async def request_approval(self, action: PendingAction) -> None:
        """
        Surface an action card to the user.
        Does NOT wait for response — approval comes back via on_user_message callback.
        Formats the action card appropriately for the channel.
        """
        ...

    @abstractmethod
    async def send_status(self, status_summary: str):
        """Respond to a STATUS_REQUEST intent."""
        ...

    def set_message_callback(self, callback: Callable[[str], Awaitable[None]]):
        """
        Orchestrator registers this callback on startup.
        Channel calls it whenever the user sends a message.
        All messages route through IntentRouter before any action is taken.
        """
        self._on_message = callback
```

### 6.2 ChannelManager (`channels/channel_manager.py`)

```python
class ChannelManager:
    """
    Owns the active channel. All orchestrator I/O goes through this class.
    Handles channel switching atomically.
    Persists active channel to DB so restarts resume in the correct channel.
    """

    def __init__(self, tui: TUIChannel, telegram: TelegramChannel | None, whatsapp: WhatsAppChannel | None):
        self._channels = {"tui": tui, "telegram": telegram, "whatsapp": whatsapp}
        self._active: BaseChannel = tui

    async def restore_from_db(self):
        """
        On startup, checks ChannelState table.
        If last active channel was telegram/whatsapp and credentials are configured,
        starts in that channel instead of TUI.
        """
        ...

    async def switch_to(self, channel_name: str):
        """
        1. Validate target channel is configured (API keys exist)
        2. Call self._active.stop()
        3. Update ChannelState in DB
        4. Set self._active = target channel
        5. Call self._active.start()
        6. Send confirmation: "Switched to [channel]. I'll reach you here from now on."
        """
        ...

    # Delegate all I/O to the active channel:
    async def send_notification(self, message: str):
        await self._active.send_notification(message)

    async def request_approval(self, action: PendingAction):
        await self._active.request_approval(action)

    async def send_status(self, summary: str):
        await self._active.send_status(summary)
```

### 6.3 TUI Channel (`channels/tui_channel.py`)

Thin bridge between the Textual app and the `BaseChannel` interface.

- `send_notification()` → posts to the notification list widget
- `request_approval()` → triggers the action card modal
- `stop()` → hides TUI, prints "Hanford is now running in [channel] mode. This terminal is inactive." and keeps the process alive (does NOT exit)
- `start()` → re-activates TUI, restores dashboard

**Important:** When TUI is not the active channel, the terminal process stays running silently. The user can still `ctrl+c` to quit Hanford entirely, but the TUI going inactive does not kill the process.

### 6.4 Telegram Channel (`channels/telegram_channel.py`)

```python
class TelegramChannel(BaseChannel):
    """
    Uses python-telegram-bot (async version).
    Runs a polling loop or webhook server — configurable via TELEGRAM_USE_WEBHOOK.
    Default: polling (simpler for self-hosted).
    """

    async def start(self):
        """Starts telegram bot polling. Registers message handler → self._on_message."""
        ...

    async def send_notification(self, message: str):
        """Sends message to TELEGRAM_CHAT_ID. Supports Markdown."""
        ...

    async def request_approval(self, action: PendingAction):
        """
        Sends a formatted message with inline keyboard buttons:
        
        ⚡ AT&T Bill — $89.00
        37% above your usual $65. Due March 18.
        
        Proposed: Call AT&T and negotiate back to ~$65/mo.
        
        [✓ Approve]  [✗ Dismiss]
        
        Button callbacks route back through IntentRouter as APPROVE/REJECT.
        """
        ...

    async def stop(self):
        """Stops polling loop."""
        ...
```

**Setup requirements:**
- User creates a Telegram bot via @BotFather, gets `TELEGRAM_BOT_TOKEN`
- User gets their `TELEGRAM_CHAT_ID` (Hanford prints it on first `/start` message)
- Both stored in `.env`

### 6.5 WhatsApp Channel (`channels/whatsapp_channel.py`)

```python
class WhatsAppChannel(BaseChannel):
    """
    Uses Twilio WhatsApp API (Twilio Sandbox for dev, production number for prod).
    Requires a lightweight HTTP server to receive inbound webhooks.
    Uses aiohttp to run a small webhook server alongside the main event loop.
    """

    async def start(self):
        """
        Starts aiohttp webhook server on WHATSAPP_WEBHOOK_PORT (default: 8080).
        User must expose this port (ngrok for dev, reverse proxy for prod).
        """
        ...

    async def send_notification(self, message: str):
        """Twilio REST API: POST to /Messages. To: whatsapp:+{USER_PHONE}"""
        ...

    async def request_approval(self, action: PendingAction):
        """
        Sends formatted message. No interactive buttons (WhatsApp API limitation
        without Business API approval). Uses numbered options instead:
        
        ⚡ AT&T Bill — $89.00
        37% above your usual $65. Due March 18.
        
        Proposed: Call AT&T and negotiate back to ~$65/mo.
        
        Reply *1* to approve or *2* to dismiss.
        
        IntentRouter handles "1" → APPROVE, "2" → REJECT.
        """
        ...
```

**Note on WhatsApp vs Telegram:** Telegram is significantly simpler to set up (no webhook server needed, no sandbox, no phone number provisioning, better button support). README should recommend Telegram for most users and document WhatsApp as the alternative for users who prefer it.

---

## 7. Agent Workflows

### 7.1 End-to-End: Bill Detected → Call Dispatched → Report

```
Gmail ──► GmailWatcher.on_bill_email()
              │
              ▼
         BillParser.parse()
              │
              ├─── Parse failed → log, discard
              │
              ▼
         AnomalyDetector.analyze()
              │
              ├─── score < threshold → update baseline, no notification
              │
              ▼ score >= threshold
         PendingAction created (status: awaiting_approval)
              │
              ▼
         ChannelManager.request_approval(action)
         [Renders in TUI modal OR Telegram message OR WhatsApp message]
              │
              ├─── User replies "no" / "2" / taps Dismiss
              │         PendingAction.status = rejected
              │
              ▼ User replies "yes" / "1" / taps Approve / types "go ahead"
         IntentRouter classifies → APPROVE
              │
              ▼
         PendingAction.status = approved
              │
              ▼
         CallAgent.dispatch_call()
              │
              ▼
         ChannelManager.send_notification("Calling AT&T... I'll update you when done.")
              │
              ▼
         [Vapi handles call: IVR navigation, hold, negotiation — up to 40 min]
              │
              ▼
         CallAgent.poll_for_outcome()
              │
              ▼
         _parse_outcome(transcript)
              │
              ▼
         Interaction saved to DB
              │
              ▼
         ChannelManager.send_notification(
           "✓ AT&T call complete. New rate: $65/mo. Saved $24. [View transcript]"
         )
```

### 7.2 Channel Switch Flow

```
User (in TUI input bar): "switch to telegram"
              │
              ▼
         IntentRouter → SWITCH_TO_MESSAGING (channel: telegram)
              │
              ▼
         ChannelManager.switch_to("telegram")
              │
              ├─── Validate TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID configured
              │    If not: send_notification("Telegram isn't set up yet. Add your
              │    TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env first.")
              │    → abort switch
              │
              ▼ configured
         TUIChannel.stop()
         [Terminal shows: "Hanford is running in Telegram mode. This terminal is inactive.
          Send 'switch back to device' from Telegram to return."]
              │
              ▼
         ChannelState updated in DB (active_channel = "telegram")
              │
              ▼
         TelegramChannel.start()
              │
              ▼
         Telegram message sent: "I'm here. You can approve actions, give me new
         instructions, or ask for a status update. I'll reach you here from now on."
```

### 7.3 User Directive Flow

```
User (via any channel): "keep an eye out for a confirmation from United Airlines"
              │
              ▼
         IntentRouter → NEW_DIRECTIVE
         extracted: "watch for email from United Airlines containing confirmation"
              │
              ▼
         Orchestrator._handle_new_directive(message, extracted)
              │
              ▼
         LLM parses into UserDirective:
         {
           "directive_type": "watch_email",
           "parameters": {
             "sender_pattern": "united|unitedairlines",
             "subject_keywords": ["confirmation", "booking", "itinerary", "eticket"],
             "notify_message": "United Airlines confirmation just landed in your inbox."
           }
         }
              │
              ▼
         UserDirective saved to DB (status: active)
              │
              ▼
         ChannelManager.send_notification(
           "Got it — I'll watch for a United Airlines confirmation and let you know
            the moment it arrives."
         )
              │
              ▼ [later, when Gmail sees matching email]
         GmailWatcher._check_directive_matches() → match found
              │
              ▼
         ChannelManager.send_notification(
           "📬 United Airlines confirmation just landed in your inbox."
         )
         UserDirective.status = completed
```

### 7.4 Status Request Flow

```
User (via any channel): "what are you doing?"
              │
              ▼
         IntentRouter → STATUS_REQUEST
              │
              ▼
         Orchestrator._generate_status()
              │
         Queries DB for:
         - Active pending actions
         - In-progress interactions
         - Active user directives
         - Last 3 completed interactions
              │
              ▼
         LLM formats into plain English summary:
         "Currently monitoring Gmail. 1 pending action: AT&T bill awaiting your
          approval. Watching for a United Airlines confirmation. Last action:
          Comcast negotiation on Mar 8 — saved $21/mo."
              │
              ▼
         ChannelManager.send_status(summary)
```

---

## 8. TUI Design

**Framework:** [Textual](https://textual.textualize.io/)

### 8.1 Dashboard

```
┌─ HANFORD ─────────────────────────── [s]ettings [r]efresh [q]uit ─┐
│                                                                    │
│  PENDING (1)                                                       │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ ⚡ AT&T Bill — $89.00                                         │ │
│  │   37% above your usual $65. Due March 18.                    │ │
│  │   [Y] Call AT&T    [N] Dismiss                               │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                    │
│  RECENT ACTIVITY                                                   │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ ✓ Comcast   Mar 8    Negotiated to $79/mo. Saved $21.       │ │
│  │ ✓ AT&T      Feb 22   Credit applied: $15.                   │ │
│  │ ✗ Verizon   Feb 15   No discount available.                 │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                    │
│  WATCHING (1)                                                      │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ 📬 United Airlines confirmation                              │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                    │
│ > _____________________________________________________________ │  │
│                                                                    │
│  Monitoring: Gmail ●  Channel: TUI  │ Last checked: 2 min ago    │
└────────────────────────────────────────────────────────────────────┘
```

The `> ___` input bar is always visible at the bottom of the dashboard. This is the primary natural language interface. Any message typed here routes through the IntentRouter.

### 8.2 Action Card Modal
```
┌─ ACTION REQUIRED ──────────────────────────────────────────────────┐
│                                                                     │
│  AT&T bill detected                                                │
│                                                                     │
│  Current bill:    $89.00                                           │
│  Your usual:      ~$65.00                                          │
│  Difference:      +$24.00 (37% increase)                           │
│  Due date:        March 18, 2026                                   │
│                                                                     │
│  Proposed action:                                                   │
│  Call AT&T customer service and negotiate your bill back down.     │
│  Will target $65/mo or a one-time credit.                          │
│  Estimated call time: 20–40 minutes.                               │
│                                                                     │
│  ┌──────────────┐   ┌───────────────┐   ┌──────────────────────┐  │
│  │ [Y] Approve  │   │  [N] Dismiss  │   │  [V] View bill email │  │
│  └──────────────┘   └───────────────┘   └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.3 Settings Screen
```
┌─ SETTINGS ──────────────────────────────────────────── [esc] back ─┐
│                                                                     │
│  API KEYS                                                           │
│  OpenAI API Key:         sk-••••••••••••••  [edit]                 │
│  Vapi API Key:           vapi-••••••••••••  [edit]                 │
│  Vapi Phone Number ID:   ••••••••••••••••   [edit]                 │
│                                                                     │
│  CONNECTED ACCOUNTS                                                 │
│  Gmail:                  user@gmail.com ●   [disconnect]           │
│                                                                     │
│  MESSAGING CHANNELS                                                 │
│  Telegram Bot Token:     ••••••••••••••••   [edit]                 │
│  Telegram Chat ID:       ••••••••••••••••   [edit]                 │
│  WhatsApp / Twilio SID:  ──────────────     [configure]            │
│  WhatsApp Phone:         ──────────────     [configure]            │
│                                                                     │
│  Active Channel:         TUI                [switch]               │
│                                                                     │
│  MONITORING                                                         │
│  Poll interval:          5 minutes          [edit]                 │
│  Anomaly threshold:      15%                [edit]                 │
│                                                                     │
│  YOUR INFO (used in calls)                                          │
│  Name:                   [                ] [edit]                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.4 Key Bindings
| Key | Action |
|-----|--------|
| `y` | Approve pending action |
| `n` | Dismiss pending action |
| `v` | View transcript / bill for selected item |
| `s` | Open settings |
| `r` | Force Gmail sync now |
| `/` | Focus input bar |
| `esc` | Blur input bar / close modal |
| `q` | Quit Hanford entirely |

---

## 9. External Integrations

### 9.1 Gmail API
- **Library:** `google-auth-oauthlib`, `google-api-python-client`
- **Scope:** `gmail.readonly` only
- **Auth:** OAuth2 desktop flow on first run. Token stored in `~/.hanford/gmail_token.json`
- **Setup:** User creates Google Cloud project, enables Gmail API, downloads `credentials.json` to `~/.hanford/`

### 9.2 Vapi.ai
- **Key endpoints:** `POST /call`, `GET /call/{id}`
- **Phone number:** User provisions via Vapi dashboard (~$2/mo)
- **Cost transparency:** README must document ~$0.05–0.10/min call cost clearly

### 9.3 OpenAI
- **Library:** `openai` Python SDK
- **Models:** `gpt-4o-mini` for bill parsing, outcome parsing, intent classification, directive parsing
- **Config:** `OPENAI_API_KEY` + optional `OPENAI_BASE_URL` for alternative providers

### 9.4 Telegram
- **Library:** `python-telegram-bot>=20.0` (async version)
- **Mode:** Long polling (default). Webhook optional via `TELEGRAM_USE_WEBHOOK=true`
- **Setup:** @BotFather → bot token. Chat ID auto-detected on first `/start`

### 9.5 WhatsApp (Twilio)
- **Library:** `twilio`
- **Inbound:** aiohttp webhook server on configurable port
- **Dev setup:** ngrok to expose local port
- **Prod setup:** Reverse proxy (nginx/caddy)
- **Recommendation:** Document Telegram as the easier path; WhatsApp for users who prefer it

---

## 10. Configuration & Setup

### 10.1 `.env.example`
```env
# LLM
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# Vapi
VAPI_API_KEY=...
VAPI_PHONE_NUMBER_ID=...

# User identity (used in calls)
USER_NAME=John Smith

# Telegram (optional — configure to enable text mode)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_USE_WEBHOOK=false

# WhatsApp / Twilio (optional — alternative to Telegram)
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
USER_WHATSAPP_NUMBER=+1XXXXXXXXXX
WHATSAPP_WEBHOOK_PORT=8080

# Monitoring
GMAIL_POLL_INTERVAL_SECONDS=300
ANOMALY_THRESHOLD=0.15
MAX_CONCURRENT_CALLS=1

# Paths
DATABASE_PATH=~/.hanford/hanford.db
```

### 10.2 Installation
```bash
git clone https://github.com/[user]/hanford
cd hanford
pip install -e .
cp .env.example .env
# Fill in OPENAI_API_KEY, VAPI_*, USER_NAME at minimum
# Optionally add TELEGRAM_* to enable text mode
hanford
# First run: browser opens for Gmail OAuth
# TUI launches. You're live.
```

### 10.3 Enabling Text Mode
```bash
# 1. Create a Telegram bot via @BotFather, copy the token
# 2. Add to .env:
TELEGRAM_BOT_TOKEN=your_token_here
# 3. Start Hanford, send /start to your bot in Telegram
# 4. Hanford prints your Chat ID in the TUI — copy it to .env:
TELEGRAM_CHAT_ID=your_chat_id
# 5. In TUI input bar, type: "switch to telegram"
# Terminal goes quiet. Hanford messages you on Telegram.
```

### 10.4 `pyproject.toml` Dependencies
```toml
[project]
name = "hanford"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "textual>=0.47.0",
    "sqlalchemy>=2.0",
    "aiosqlite>=0.19",
    "openai>=1.0",
    "google-auth-oauthlib>=1.0",
    "google-api-python-client>=2.0",
    "python-telegram-bot>=20.0",
    "twilio>=8.0",
    "aiohttp>=3.9",
    "requests>=2.31",
    "pydantic>=2.0",
    "python-dotenv>=1.0",
    "beautifulsoup4>=4.12",
    "rich>=13.0",
    "pyyaml>=6.0",
    "apscheduler>=3.10",
]

[project.scripts]
hanford = "hanford.main:run"
```

---

## 11. v0.1 Scope & Explicit Exclusions

### In Scope
- [x] Gmail monitoring (OAuth, polling, deduplication)
- [x] Directive-based email watching ("watch for X")
- [x] Bill parsing via LLM
- [x] Anomaly detection with configurable threshold
- [x] SQLite estate map (all 6 models)
- [x] Textual TUI with dashboard, action card, settings, history, input bar
- [x] Intent router (approve, reject, switch channel, new directive, status)
- [x] Channel abstraction (BaseChannel, ChannelManager)
- [x] TUI channel
- [x] Telegram channel (polling mode)
- [x] WhatsApp channel (Twilio)
- [x] Channel switching via natural language
- [x] Channel state persistence across restarts
- [x] Outbound AI calls via Vapi.ai
- [x] Call outcome parsing from transcript
- [x] Provider knowledge YAMLs (AT&T, Comcast, Verizon, Spectrum, one utility)
- [x] Negotiation scripts (telecom, utility)
- [x] README with setup, cost transparency, contributing guide
- [x] `_template.yaml` for community provider contributions

### Explicitly Out of Scope (v0.1)
- ❌ Web automation / browser control
- ❌ Outbound email composition
- ❌ Appointment / flight rescheduling
- ❌ IMAP (non-Gmail) support
- ❌ Hosted / cloud version
- ❌ Multi-user support
- ❌ Vapi webhooks (polling only)
- ❌ Insurance / healthcare negotiation scripts (stubs only)
- ❌ Telegram webhook mode
- ❌ Historical bill backfill beyond 90 days

---

## 12. v0.2 Roadmap Hooks

Build the following with extension in mind, even if not implemented:

**Web Agent:** `agents/base_agent.py` defines the interface. Orchestrator dispatches to agent type based on provider YAML `preferred_contact_method`. Adding `web_agent.py` using `browser-use` requires no orchestrator changes.

**IMAP:** `monitor/base_watcher.py` is the interface. `GmailWatcher` is one implementation. `IMAPWatcher` drops in. Config selects which watcher.

**Hosted Version:** SQLAlchemy with SQLite today → swap connection string for PostgreSQL. No SQLite-specific features. `ChannelState` and `UserDirective` tables are already designed for multi-session use.

**Appointment/Flight Rescheduling:** New directive type `"reschedule"` in `UserDirective`. New agent `agents/schedule_agent.py`. No changes to intent router or channel system.

**Community Knowledge Base:** Provider YAMLs and script `.md` files are the primary contribution surface. Keep them simple, heavily commented. `_template.yaml` ships in v0.1 with full inline documentation.

---

*Hanford v0.1 Technical Specification*
*The agent that travels with you.*
