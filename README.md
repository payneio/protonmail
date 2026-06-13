# protonmail

CLI tool for syncing and managing ProtonMail emails via ProtonMail Bridge. Downloads emails as `.eml` files for fast, offline access. All read/list/search commands work against the local cache.

## Prerequisites

[ProtonMail Bridge](https://proton.me/mail/bridge) must be running locally with IMAP enabled (default port 1143).

## Usage

```bash
# Sync all emails from Bridge to local .eml files
protonmail sync

# Sync to a custom directory
protonmail sync -o ~/emails

# List recent emails (from local cache)
protonmail list
protonmail list Sent
protonmail list -n 50

# Read a specific email
protonmail read "2024-07-17_01-14-40_from_alice_example_com_to_bob_example_com.eml"

# Search by subject or sender
protonmail search "invoice"
protonmail search "alice" -f Sent

# Send an email (interactive, requires Bridge)
protonmail send
```

## Configuration

Set via environment variables (castle manages these automatically):

| Variable | Description | Default |
|----------|-------------|---------|
| `PROTONMAIL_USERNAME` | Bridge username (required) | - |
| `PROTONMAIL_API_KEY` | Bridge API key (required) | - |
| `PROTONMAIL_DATA_DIR` | Where to store synced .eml files | `/data/messages/email/protonmail` |

In castle, the API key is stored as a secret:

```yaml
env:
  PROTONMAIL_API_KEY: ${secret:PROTONMAIL_API_KEY}
```

## How sync works

1. Connects to Bridge via IMAP on `127.0.0.1:1143`
2. Lists all folders (INBOX, Sent, Drafts, etc.)
3. For each folder, downloads new messages as `.eml` files
4. Skips emails already in the local cache (matched by Message-ID)
5. Filenames follow the pattern: `YYYY-MM-DD_HH-MM-SS_from_SENDER_to_RECIPIENT_SUBJECT.eml`

## Castle integration

Registered as both a **tool** (installed to PATH) and a **job** (syncs every 5 minutes via systemd timer).

## Development

```bash
uv sync                         # Install dependencies
uv run protonmail --version     # Verify
uv run pytest tests/ -v         # Run tests
uv run ruff check .             # Lint
```

No third-party dependencies -- stdlib only.
