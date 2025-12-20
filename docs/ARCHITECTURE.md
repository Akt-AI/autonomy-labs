# Architecture

## Overview

`autonomy-labs` is a single-container FastAPI app intended to run on Hugging Face Spaces (Docker). It serves:
- static pages (`static/index.html`, `static/dashboard.html`)
- REST APIs for chat + Codex + MCP
- a WebSocket PTY-backed terminal (`/ws/terminal`)

## Backend layout

- `main.py`: minimal entrypoint (loads dotenv, creates app).
- `app/server.py`: app factory + lifespan lifecycle.
- `app/routes/*`: feature routers:
  - `base.py`: `/`, `/health`, `/config`
  - `chat.py`: `/api/chat`, `/api/proxy/models`
  - `codex.py`: `/api/codex*` and Codex login helpers
  - `mcp.py`: `/api/mcp/*`
  - `terminal.py`: `/ws/terminal`
- `app/auth.py`: Supabase access-token verification (server-side) with small TTL cache.

## Frontend layout

Currently the UI is primarily `static/dashboard.html` with inline JS/CSS and CDN dependencies (Tailwind, xterm, etc).

## Execution safety model

The following capabilities are high-risk and gated:
- web terminal
- Codex execution endpoints
- MCP tool calls

Auth is enforced server-side via Supabase access tokens. Feature flags can disable them entirely.

