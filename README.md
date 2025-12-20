---
title: Autonomy Labs
emoji: 🚀
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# Autonomy Labs

A lightweight web UI for chat + autonomous mode + terminal tabs, backed by FastAPI and Supabase Auth/DB.

## Features

- **AI Chat** with markdown + KaTeX math rendering, stop-generation, and provider presets.
- **Autonomous Mode** with resizable split panes (chat + terminal).
- **Terminal** tabs over WebSockets (PTY-backed), Ubuntu-like theme, resizable viewport.
- **Rooms (MVP)** with server pubsub + optional P2P DataChannel.
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

## Codex Auto Fix (GitHub Actions)

This repo includes a manual workflow at `.github/workflows/codex-autofix.yml`.

- Add `OPENAI_API_KEY` as a GitHub Actions secret.
- Run the workflow from the Actions tab and optionally customize the `prompt` input.

## Notes

- **Secrets**: don’t hardcode API keys in source. GitHub push protection will block pushes containing tokens.
- **Security**: the web terminal and agent/Codex endpoints are gated by Supabase auth. Keep Supabase configured and avoid exposing execution features publicly without auth.
- **Terminal PTY**: the host/container must have PTY devices (`/dev/pts`) available for interactive terminals.
- **Codex login (Hugging Face Spaces/web terminal)**: Spaces expose a single port, so localhost callback URLs (like `http://localhost:1455/auth/callback?...`) won’t work; use device auth: `codex login --device-auth` (alias: `codex-login`).
- **Codex login persistence (Spaces)**: on startup the container will use `/data/.codex` (if available) for `~/.codex`, so device-auth stays logged in across restarts.
- **Codex tokens (Spaces Secrets)**: if you already have tokens, set `CODEX_ID_TOKEN`, `CODEX_ACCESS_TOKEN`, `CODEX_REFRESH_TOKEN` (and optionally `CODEX_ACCOUNT_ID`) as Spaces Secrets; the container will write `~/.codex/.auth.json` (and `~/.codex/auth.json`) on startup.
- **Gemini CLI**: installed as `gemini` via `npm i -g @google/gemini-cli`. Set one of `GEMINI_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI`, or `GOOGLE_GENAI_USE_GCA` (Spaces Secret recommended).
- **Git over SSH (web terminal/Docker)**: the container auto-generates `~/.ssh/id_ed25519` on first start and prints the public key; add it to your Git provider, then use `git@github.com:ORG/REPO.git` URLs. To provide a key via Secrets instead, set `SSH_PRIVATE_KEY` (and optionally `SSH_PUBLIC_KEY`, `SSH_KNOWN_HOSTS`).
