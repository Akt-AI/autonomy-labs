---
title: Autonomy Labs Sandbox
emoji: 🚀
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# Autonomy Labs Sandbox

A lightweight web UI for chat + autonomous mode + terminal tabs, backed by FastAPI and Supabase Auth/DB.

## Features

- **AI Chat** with markdown + KaTeX math rendering, stop-generation, and provider presets.
- **Autonomous Mode** with resizable split panes (chat + terminal).
- **Terminal** tabs over WebSockets (PTY-backed), Ubuntu-like theme, resizable viewport.
- **Multimodal input**: attach/paste images and take a screenshot (browser screen capture).
- **Saved providers**: store per-user provider configs (API key + base URL + model) in Supabase.
- **Chat history**: persists sessions/messages in Supabase with delete-from-history.

## Quickstart (local)

### 1) Environment

Create a `.env` file (or set env vars):

```bash
SUPABASE_URL=...
SUPABASE_KEY=...          # Supabase anon key used by the frontend
DEFAULT_BASE_URL=https://router.huggingface.co/v1
DEFAULT_API_KEY=...       # optional default for UI (avoid committing secrets)
DEFAULT_MODEL=gpt-3.5-turbo
```

### 2) Supabase SQL

This app expects these tables to exist in Supabase:

- `chat_sessions`
- `chat_messages`
- `provider_configs` (for provider API keys/base URLs)

Run `supabase_provider_configs.sql` in the Supabase SQL editor to create `provider_configs` + RLS policies.

### 3) Run

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 7860
```

Open `http://localhost:7860`.

## Docker

```bash
docker build -t autonomy-labs .
docker run --rm -p 7860:7860 --env-file .env autonomy-labs
```

## Notes

- **Secrets**: don’t hardcode API keys in source. GitHub push protection will block pushes containing tokens.
- **Terminal PTY**: the host/container must have PTY devices (`/dev/pts`) available for interactive terminals.
- **Codex login (Hugging Face Spaces/web terminal)**: Spaces expose a single port, so localhost callback URLs (like `http://localhost:1455/auth/callback?...`) won’t work; use device auth: `codex login --device-auth` (alias: `codex-login`).
- **Git over SSH (web terminal/Docker)**: the container auto-generates `~/.ssh/id_ed25519` on first start and prints the public key; add it to your Git provider, then use `git@github.com:ORG/REPO.git` URLs.
