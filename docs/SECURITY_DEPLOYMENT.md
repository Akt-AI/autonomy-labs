# Security Deployment Guide

## Defaults

If Supabase is not configured (`SUPABASE_URL` + `SUPABASE_KEY` missing), dangerous features are disabled by default.

## Recommended settings (HF Spaces)

Use Spaces Secrets for:
- `SUPABASE_URL`
- `SUPABASE_KEY`
- Codex tokens (if using token-based auth) or use device auth inside terminal
- provider API keys (Gemini/Claude/OpenAI-compatible) as needed

Consider explicitly setting:
- `ENABLE_TERMINAL=0` unless you truly need it
- `ENABLE_CODEX=0` unless you truly need it
- `ENABLE_MCP=0` unless you truly need it
- `ENABLE_ROOMS=0` unless you need multi-user rooms/presence

## WebSocket auth

Browsers cannot set `Authorization` headers on WebSockets, so `/ws/terminal` expects a Supabase access token via `?token=...`.

Treat access tokens as sensitive; do not log them.

Rooms use the same pattern on `/ws/rooms`.

## SSH keys

Preferred: generate a key inside the container and add the public key to your Git provider.

Optional: supply keys via secrets:
- `SSH_PRIVATE_KEY` (required)
- `SSH_PUBLIC_KEY` (optional)
- `SSH_KNOWN_HOSTS` (optional)
