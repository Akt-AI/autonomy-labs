# Roadmap (P0–P3)

This file is the repo-level roadmap for `autonomy-labs`. It’s intentionally opinionated and ordered by risk reduction first, then maintainability, then feature expansion.

## P0 — Security + correctness (blockers)

- Gate **all dangerous endpoints** server-side (not just UI):
  - `/ws/terminal`
  - `/api/codex*`
  - `/api/mcp*`
  - any indexing endpoints (docs/web/GitHub)
- Define a clear auth transport for WebSockets (cookie or token) and verify on the server.
- Add capability flags with safe defaults:
  - `ENABLE_TERMINAL`, `ENABLE_CODEX`, `ENABLE_MCP`, `ENABLE_INDEXING`
- Add `SECURITY.md` with threat model + safe deployment guidance.

## P1 — Backend refactor + lifecycle

- Split `main.py` into routers/services:
  - `app/auth.py`, `app/chat.py`, `app/terminal.py`, `app/codex.py`, `app/mcp.py`, `app/settings.py`, `app/admin.py`, `app/indexing.py`
- Add FastAPI lifespan management:
  - subprocess lifecycle (Codex MCP server)
  - cleanup policies (device-login attempts, job registries)
- Unify Codex integration (prefer CLI-first for device-auth consistency; keep SDK only if needed).
- Standardize API error schema (UI should not parse strings to detect failure modes).

## P2 — UI/UX, settings, admin, landing

- Split `static/dashboard.html` into modules:
  - `static/dashboard.js`, `static/terminal.js`, `static/agent.js`, `static/settings.js`, `static/admin.js`, `static/mcp.js`, `static/rag.js`
  - `static/theme.css`
- Fix UI inconsistencies:
  - theme tokens shared across login + dashboard
  - consistent spacing, typography, button states, error banners
  - terminal sizing/fit reliability (debounce + visible-only fitting)
- Separate Settings vs Admin dashboard:
  - Settings: provider configs, tokens status, terminal layout, workspace directory, MCP registry
  - Admin: user/role management, global toggles, indexing jobs, audit logs
- Create a “blazing” landing page:
  - `/` marketing/intro + CTA
  - keep `/login` and `/app` as dedicated routes (or similar)

## P2 — Provider auth parity (Codex/Gemini/Claude)

- Keep provider auth out of git; source from env/HF Secrets.
- Support “Codex-like” auth file generation when a CLI requires it:
  - Codex: `~/.codex/.auth.json` and `~/.codex/auth.json` from `CODEX_*` (or fallback envs).
  - Gemini/Claude: prefer env (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`); add file-based auth only if required and documented.
- Optional: SSH key support via Secrets:
  - `SSH_PRIVATE_KEY` (+ optional `SSH_PUBLIC_KEY`, `SSH_KNOWN_HOSTS`)

## P2 — Codex workspace directory (UI)

- Add a per-user “workspace directory” setting.
- Enforce an allowlisted root (e.g. `/data/codex/workspace/<user>`), prevent traversal, ensure it exists.

## P2 — Stream Codex events in Agent mode

- Use `/api/codex/cli/stream` for agent execution.
- UI: render streaming events progressively (agent text, tool events, final summary + usage).
- Add stop/reconnect handling.

## P2/P3 — MCP registry

- Add a first-class MCP registry:
  - per-user servers + optional global templates
  - “test connection”, “list tools”, allow/deny tool lists
  - import/export `mcp.json`

## P3 — RAG + indexing (docs/web/GitHub) + “password manager”

- Clarify “password manager” scope:
  - secure vault for secrets (high-risk; encryption + audit required), or
  - indexed notes (lower-risk but still private)
- Implement indexing connectors:
  - document uploads
  - website crawl (depth, allowlist, robots, rate limits)
  - GitHub repo indexing (branch/path filters, token support via Secrets)
- Build a jobs UI: progress, retries, errors, and access controls.

Note: see `docs/PASSWORD_MANAGER_SCOPE.md` for the current (non-vault) stance and recommended path forward.

## P3 — P2P pubsub chat + account manager

- Implement account manager concepts:
  - identities/devices, room/topic membership, permissions, moderation tools
- Transport:
  - WebRTC DataChannel (P2P) + server signaling
  - fallback to server pubsub when P2P fails
- UX:
  - rooms, presence, delivery status, network mode indicators

## Engineering hygiene (ongoing)

- Add `.env.example`, `docs/TROUBLESHOOTING.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY_DEPLOYMENT.md`
- Add lint/tests + CI:
  - Python: `ruff`, `pytest`
  - basic security smoke tests for endpoint gating

## Feature suggestions (By User)

- Support GitHub token auth via HF Secrets (`GITHUB_TOKEN`/`GITHUB_PAT`) and document it in `.env.example`.
