# Repository Guidelines

## Project Structure & Module Organization

This Python Discord bot serves the Talent4Cyber group with `/panel`, `/ia`, and `/help` commands. Source lives in `bot/`: `main.py` initializes the client and registers commands, `config.py` validates environment settings, `panel.py` defines resource buttons, `ia.py` handles requests and reply limits, and `lmstudio.py` communicates with LM Studio. Tests live in `tests/`. Design specifications and implementation plans are under `docs/superpowers/`. There is no separate asset directory or build pipeline.

## Build, Test, and Development Commands

Run commands from the repository root. For Linux/WSL:

```bash
python3 -m venv .venv-wsl
.venv-wsl/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv-wsl/bin/python -m bot.main
.venv-wsl/bin/python -m pytest -q
```

These commands create an environment, install runtime and test dependencies, initialize local configuration, launch the bot, and run the test suite. Fill in `.env` before launching. On Windows, follow the PowerShell setup in `README.md`. Load a model and start LM Studio's server before using `/ia`.

## Coding Style & Naming Conventions

Use four-space indentation, `snake_case` for modules and functions, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Follow existing type annotations and small, focused functions. Use asynchronous APIs for Discord interactions and HTTP requests. Keep Discord-facing messages in Spanish and follow existing module-level `register(...)` patterns for commands. No formatter or linter is currently configured.

## Testing Guidelines

Use pytest and pytest-asyncio; `pytest.ini` enables automatic async handling and discovers tests in `tests/`. Name files `test_<module_or_behavior>.py` and functions `test_<expected_behavior>`. Use fake interactions and mocked model responses so tests require no Discord token or running LM Studio. Cover relevant success, failure, permission, cooldown, queue, and reply-chunking behavior. No numerical coverage threshold is configured. Run the full suite before submitting changes; use README's Discord smoke checks for integration changes.

## Commit & Pull Request Guidelines

Recent commits use imperative `feat:` and `fix:` subjects, such as `feat: add panel and help commands`. Keep commits focused. Pull requests should describe the behavior change, reference related issues when applicable, and report test results. Include screenshots or Discord transcripts for visible command changes, with secrets removed.

## Security & Configuration Tips

Keep credentials in `.env`; never commit tokens or log them. Update `.env.example` and `README.md` when configuration changes. Under WSL, set `LMSTUDIO_BASE_URL` to the Windows host address when LM Studio runs on Windows. Preserve private error replies and disabled mentions when changing interaction handling.
