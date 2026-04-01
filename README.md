# Hanford

Life administration agent. Monitors your bills, detects anomalies, calls companies on your behalf, reports back.

Self-hosted TUI. Travels with you via Telegram or WhatsApp. Open source. Bring your own API keys.

## What Hanford Does

Hanford watches your Gmail for bills, detects when you're being overcharged, and — with your approval — places an AI phone call to negotiate on your behalf. It lives in your terminal as a TUI, but you can switch to Telegram or WhatsApp at any time. It follows you.

### v0.1 Capabilities

- Gmail monitoring for bills and statements
- Anomaly detection (current bill vs. your historical baseline)
- Approval gate before any action is taken
- Outbound AI voice calls via Vapi.ai to negotiate bills
- Call transcript and outcome logging
- SQLite-backed estate map (providers, bills, interaction history)
- Channel switching: TUI <-> Telegram or WhatsApp
- Natural language directives: "watch for X", "add Z as a provider", "status"

### Supported Domains

- Telecom (internet, cable, mobile)
- Utilities (electricity, gas, water)
- Insurance (billing disputes only)
- Healthcare (billing errors, EOB discrepancies)

---

## Setup

### Prerequisites

- Python 3.11+
- An OpenAI API key
- A Vapi.ai account with a provisioned phone number
- Gmail API credentials (Google Cloud project with Gmail API enabled)

### Installation

```bash
git clone https://github.com/[your-user]/hanford
cd hanford
pip install -e .
cp .env.example .env
```

### Configuration

Edit `.env` with your API keys. At minimum you need a Vapi key and one LLM provider:

```env
# Pick one LLM provider:
LLM_PROVIDER=openai   # or "anthropic"

# If using OpenAI:
OPENAI_API_KEY=sk-...

# If using Anthropic (Claude):
ANTHROPIC_API_KEY=sk-ant-...

# Required for phone calls:
VAPI_API_KEY=your-vapi-key
VAPI_PHONE_NUMBER_ID=your-phone-number-id
USER_NAME=Your Full Name
```

Hanford supports both OpenAI and Anthropic (Claude) as the LLM backend. Set `LLM_PROVIDER` to choose which one. Both are used for bill parsing, intent classification, directive parsing, and status generation. The Vapi phone call assistant is separate and always uses OpenAI via Vapi's infrastructure.

### Gmail Setup

1. Create a Google Cloud project at https://console.cloud.google.com
2. Enable the Gmail API
3. Create OAuth 2.0 credentials (Desktop application type)
4. Download the credentials JSON file
5. Save it to `~/.hanford/credentials.json`

On first run, Hanford opens a browser window for OAuth authorization. The token is saved to `~/.hanford/gmail_token.json` for subsequent runs.

### Running

```bash
hanford
```

The TUI launches. You're live. Hanford begins monitoring Gmail in the background.

---

## Cost Transparency

Hanford uses paid external APIs. Here's what each costs:

### Vapi.ai (AI Phone Calls)

- **Phone number:** ~$2/month
- **Call cost:** ~$0.05-0.10 per minute of call time
- **Typical negotiation call:** 20-40 minutes = **$1-4 per call**
- You are billed directly by Vapi. Hanford does not mark up or intermediate.
- Calls are only placed with your explicit approval.

### LLM (OpenAI or Anthropic)

Hanford uses an LLM for bill parsing, intent classification, directive parsing, and status summaries. You choose the provider.

**OpenAI (default):**
- Model: `gpt-4o-mini`
- Cost: ~$0.15 per million input tokens, ~$0.60 per million output tokens
- Monthly cost for typical use: **< $1/month**

**Anthropic (Claude):**
- Model: `claude-sonnet-4-20250514`
- Cost: ~$3 per million input tokens, ~$15 per million output tokens
- Monthly cost for typical use: **< $2/month** (higher per-token cost but very low volume)

### Telegram / WhatsApp

- **Telegram:** Free (bot API has no cost)
- **WhatsApp via Twilio:** Twilio messaging rates apply (~$0.005-0.05 per message depending on region)

### Total Estimated Monthly Cost

For a typical user monitoring 5-10 providers with 1-2 negotiation calls per month:
- Vapi phone number: $2
- Vapi call time: $2-8
- OpenAI: < $1
- **Total: $5-11/month**

All API keys are user-supplied and stored locally. Hanford never phones home.

---

## Enabling Text Mode (Telegram)

Telegram is recommended for most users. It's simpler to set up than WhatsApp.

1. Create a Telegram bot via [@BotFather](https://t.me/botfather). Copy the bot token.
2. Add to your `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_token_here
   ```
3. Start Hanford, then send `/start` to your bot in Telegram.
4. Hanford displays your Chat ID in the TUI. Copy it to `.env`:
   ```
   TELEGRAM_CHAT_ID=your_chat_id
   ```
5. Restart Hanford. In the TUI input bar, type: `switch to telegram`
6. The terminal goes quiet. Hanford messages you on Telegram from now on.
7. To switch back, send `switch back to device` from Telegram.

### WhatsApp (Alternative)

WhatsApp requires a Twilio account and a webhook server. See `.env.example` for the required configuration variables. You'll need to expose a local port via ngrok (dev) or a reverse proxy (prod).

---

## Key Bindings (TUI)

| Key | Action |
|-----|--------|
| `y` | Approve pending action |
| `n` | Dismiss pending action |
| `v` | View transcript / bill |
| `s` | Open settings |
| `r` | Force Gmail sync |
| `/` | Focus input bar |
| `Esc` | Blur input / close modal |
| `q` | Quit Hanford |

---

## Architecture

```
ChannelManager (owns active channel, routes all I/O)
    |
    +-- TUI Channel (Textual)
    +-- Telegram Channel (python-telegram-bot)
    +-- WhatsApp Channel (Twilio + aiohttp)
    |
Orchestrator (async event loop, routes events to agents)
    |
    +-- IntentRouter (classifies every user message)
    +-- Monitor (Gmail watcher, bill parser, anomaly detector)
    +-- Agents (CallAgent via Vapi.ai)
    |
Data Layer (SQLite via SQLAlchemy async)
    |
Knowledge Base (provider YAMLs + negotiation scripts)
```

Key design decisions:
- **Channel abstraction is the core primitive.** The orchestrator never references TUI or Telegram directly.
- **Every user message routes through IntentRouter** before anything acts on it.
- **async throughout.** asyncio is the backbone.
- **SQLite is the single source of truth.** Channel state persists across restarts.

---

## Contributing

### Adding a Provider YAML

This is the easiest way to contribute. Provider YAMLs live in `hanford/knowledge/providers/`.

1. Copy `_template.yaml` to `your_provider.yaml`
2. Fill in all fields (see the inline comments in `_template.yaml` for guidance)
3. Test by adding the provider: type `add [provider name] as a provider` in Hanford
4. Submit a PR

### Adding a Negotiation Script

Negotiation scripts live in `hanford/knowledge/scripts/` as Markdown files. They provide the strategy the AI follows during phone calls.

1. Look at existing scripts (`telecom_dispute.md`, `utility_dispute.md`) as examples
2. Write your script covering: opening strategy, negotiation tactics, key rules, common objections
3. Submit a PR

### Code Contributions

1. Fork the repository
2. Create a feature branch
3. Install dev dependencies: `pip install -e ".[dev]"`
4. Run tests: `pytest`
5. Submit a PR with a clear description of the change

### Guidelines

- All provider profiles and scripts should be factual and community-verifiable
- No secrets or personal data in committed files
- Follow existing code style (async throughout, type hints, docstrings)
- Test coverage for new modules is expected

---

## License

MIT
