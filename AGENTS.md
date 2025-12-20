# Autonomy Labs — Agent Notes

This repo powers a FastAPI web app deployed to Hugging Face Spaces (Docker). It includes:
- a Supabase-backed login + user data
- a chat UI (OpenAI-compatible providers)
- a PTY-backed web terminal over WebSockets
- optional Codex CLI/SDK integration
- optional MCP tooling integration

## Non-negotiables
- **Never commit secrets** (API keys, tokens, cookies, private SSH keys). Use env vars / HF Spaces Secrets.
- **Assume hostile clients**: UI checks are not security. Dangerous endpoints must be protected server-side.
- **Prefer minimal, reversible changes** with clear validation steps.

## Repo map
- `main.py`: FastAPI backend (currently a single large file).
- `static/index.html`: login page (Supabase Auth).
- `static/dashboard.html`: main UI (chat, terminal, agent mode, notes, settings UI).
- `docker-entrypoint.sh`: runtime setup (persistence under `/data`, writes Codex auth files from env if provided).
- `Dockerfile`: image build (Python + Node + CLIs).
- `codex_agent.mjs`: Node wrapper around `@openai/codex-sdk`.
- `.github/workflows/deploy.yml`: deploy to Hugging Face Space.
- `.github/workflows/codex-autofix.yml`: optional GitHub Action to run Codex for autofixes.

## How to run (local)
- Python deps: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port 7860`
- Open: `http://localhost:7860`

## Key environment variables
### Supabase
- `SUPABASE_URL`
- `SUPABASE_KEY` (anon key used by the frontend)

### Chat defaults (UI convenience)
- `DEFAULT_BASE_URL` (e.g. `https://router.huggingface.co/v1`)
- `DEFAULT_API_KEY` (avoid using in production; don’t commit)
- `DEFAULT_MODEL`

### Codex (HF Spaces Secrets recommended)
Supported token env names (either set works):
- `CODEX_ID_TOKEN` or `ID_TOKEN`
- `CODEX_ACCESS_TOKEN` or `ACCESS_TOKEN`
- `CODEX_REFRESH_TOKEN` or `REFRESH_TOKEN`
- optional: `CODEX_ACCOUNT_ID` or `ACCOUNT_ID`

At runtime, the container writes:
- `~/.codex/.auth.json`
- `~/.codex/auth.json`

### Gemini / Claude
Prefer env-based auth (keep tokens out of the UI and git):
- Gemini: typically `GEMINI_API_KEY` (or Google GenAI envs, depending on mode)
- Claude: typically `ANTHROPIC_API_KEY`

If adding “Codex-like” auth files for these CLIs, document **exact paths + formats** and keep them **generated at runtime** from Secrets.

### SSH (optional)
Default behavior: container may generate `~/.ssh/id_ed25519` and persist to `/data/.ssh` (Spaces).
If adding SSH-from-secrets support, prefer:
- `SSH_PRIVATE_KEY` (+ optional `SSH_PUBLIC_KEY`, `SSH_KNOWN_HOSTS`)
and ensure files are `0600`, never logged.

## Security posture (important)
The web terminal and any agent/Codex/MCP execution is effectively remote code execution if exposed.

Before shipping features, ensure:
- server-side auth checks for `/ws/terminal` and all `/api/codex*` + `/api/mcp*` endpoints
- explicit capability flags (e.g. `ENABLE_TERMINAL`, `ENABLE_CODEX`, `ENABLE_MCP`) with safe defaults
- rate limiting / abuse controls if public

## Development hygiene
- Prefer extracting modules from `main.py` rather than growing it further.
- Prefer moving large inline JS/CSS out of `static/dashboard.html` into `static/*.js` + `static/*.css`.
- Keep UI theme tokens consistent between login and dashboard.

## Quick validation
- Python syntax: `python3 -m py_compile main.py`
- Basic endpoint check: `curl -sSf http://localhost:7860/health`

## Deployment notes (HF Spaces)
- Port: `7860`
- Persistence: `/data` is used for `~/.codex`, `~/.ssh`, and a default workspace directory when available.
- Web terminals often require device auth flows; avoid localhost callback assumptions.

