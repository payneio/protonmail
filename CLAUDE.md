# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## Overview

protonmail is a CLI tool for accessing and managing ProtonMail emails via Bridge.
All commands work with local cached .eml files for fast, offline access.

## Commands

```bash
uv sync                            # Install dependencies
uv run protonmail --version        # Show version
uv run protonmail sync             # Sync emails from Bridge
uv run protonmail list             # List cached emails
uv run protonmail read <file>      # Read a specific email
uv run protonmail search <query>   # Search by subject/sender
uv run pytest tests/ -v            # Run tests
uv run ruff check .                # Lint
uv run ruff format .               # Format
```

## Architecture

- `src/protonmail/main.py` — CLI entry point, all email operations
- `src/protonmail/__init__.py` — Package version (`__version__`)
- `tests/` — pytest tests

## Configuration

Environment variables (set by castle or manually):
- `PROTONMAIL_USERNAME` — ProtonMail Bridge username
- `PROTONMAIL_API_KEY` — ProtonMail Bridge API key
- `PROTONMAIL_DATA_DIR` — Where to store synced .eml files (default: /data/messages/email/protonmail)

## Dependencies

stdlib-only — no third-party packages required.
