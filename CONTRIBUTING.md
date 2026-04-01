# Contributing to Hanford

Hanford is open source and community-extensible. The primary contribution surfaces are provider profiles and negotiation scripts, but code contributions are welcome too.

## Provider YAMLs (easiest way to contribute)

Provider profiles live in `hanford/knowledge/providers/`. Each YAML file describes a service provider: phone number, IVR navigation, email patterns, and negotiation tips.

### How to add a provider

1. Copy `hanford/knowledge/providers/_template.yaml` to a new file named after the provider's slug (e.g., `tmobile.yaml`, `pg_and_e.yaml`).
2. Fill in every field. See the inline comments in `_template.yaml` for guidance on each field.
3. Test locally by running Hanford and typing `add [provider name] as a provider` in the input bar.
4. Submit a pull request.

### What makes a good provider profile

- **Accurate phone number.** Call it yourself to verify it reaches billing/customer service.
- **IVR navigation tested.** Document the actual phone menu steps. The AI uses these as a guide.
- **Specific negotiation tips.** Include the name of the retention department, competitor leverage points, known discount programs.
- **Correct email pattern.** Check what domain(s) the provider sends bills from.

## Negotiation Scripts

Negotiation scripts live in `hanford/knowledge/scripts/` as Markdown files. They define the strategy the AI phone agent follows during calls.

### How to add or improve a script

1. Look at existing scripts (`telecom_dispute.md`, `utility_dispute.md`) for the expected format.
2. A good script includes: opening strategy, tiered negotiation tactics, key behavioral rules, and a table of common objections with responses.
3. Keep it factual and actionable. The AI reads this as instructions.
4. Submit a pull request.

## Code Contributions

### Setup

```bash
git clone https://github.com/[user]/hanford
cd hanford
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest
```

### Code Style

- Python 3.11+ with type hints throughout
- `async`/`await` for all I/O operations
- Docstrings on all public classes and methods
- No blocking calls on the main asyncio event loop (use `run_in_executor` for sync APIs)

### Architecture Rules

These are non-negotiable:

1. **The orchestrator NEVER references channel implementations directly.** All I/O goes through `ChannelManager`. Adding a new channel must not require any orchestrator changes.
2. **Every user message routes through `IntentRouter`** before any action is taken. No exceptions.
3. **`ChannelState` persists to SQLite.** Restarts resume in the correct channel.
4. **The TUI process stays alive** when switching to a messaging channel. It goes quiet, it does not exit.
5. **SQLite is the single source of truth.** No in-memory-only state that would be lost on restart.

### Pull Request Process

1. Fork the repository and create a feature branch.
2. Write tests for new functionality.
3. Ensure `pytest` passes.
4. Write a clear PR description explaining what and why.
5. One approval required to merge.

## Reporting Issues

Open an issue on GitHub with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
