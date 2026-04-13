# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace Rules

`/root/DevAgent` (also accessible as `/home/ubuntu/DevAgent`) is the **root workspace** for a dev agent that manages multiple independent GitHub projects.

- **All cloned project repos go into `projects/`** — e.g. `git clone <url> projects/my-repo`. This folder is gitignored so working repos never leak into the DevAgent meta repo.
- **Each subfolder of `projects/` is a separate GitHub repo** — independent git history, branches, issues, and decisions. Changes in one project never affect others.
- **Tool docs and metadata belong at the DevAgent root only** — never inside a project subfolder. `.md` reference files, workflow guides, and agent configuration stay at `/root/DevAgent/`.
- **Project folders stay clean** — only the project's own code and assets. No agent metadata, memory artifacts, or CLAUDE.md files inside project subfolders.

## Telegram Bot (`telegram/`)

The only application code in this repo is the Telegram bot that bridges chat with the Claude CLI.

**Run locally (requires env vars):**
```bash
pip install -r telegram/requirements.txt
python telegram/bot.py
```

**Build and deploy (Docker):**
```bash
cd telegram
docker-compose build
docker-compose up -d
docker-compose logs -f
```

**Required environment variables** (see `.env` at repo root, never commit):
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `ALLOWED_USER_IDS` — comma-separated Telegram user IDs permitted to use the bot
- `WEBHOOK_URL` — public HTTPS base URL (default: `https://agent.enginchantier.ma`)
- `WEBHOOK_SECRET` — optional token to authenticate Telegram webhook calls

## Architecture

**`telegram/bot.py`** is the entire application (~82 lines). Flow:

1. Telegram sends updates via HTTPS webhook to `POST /webhook` on port 8000
2. `handle_message()` validates `user_id` against `ALLOWED_USER_IDS`, then runs:
   ```python
   subprocess.run(["claude", "-p", text, "--dangerously-skip-permissions"], cwd="/workspace", timeout=300)
   ```
3. stdout/stderr is chunked into ≤4096-char messages and sent back to the user

The bot runs as `devagent` (uid=1000) inside Docker. The host's `/home/ubuntu/DevAgent` is mounted at `/workspace` — this is the directory where Claude CLI executes all commands. The host's `~/.claude` auth and git credentials are bind-mounted so the container reuses existing authentication.

**Traefik** handles TLS termination and routes `agent.enginchantier.ma` → container port 8000. The `web` Docker network must exist before `docker-compose up`.
