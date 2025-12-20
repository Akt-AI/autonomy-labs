# Tasks Checklist

This file tracks the implementation status of `PLANS.md`. Update this checklist as work progresses.

Legend:
- [x] done
- [ ] pending
- [~] in progress

## P0 — Security + correctness
- [x] Gate dangerous endpoints server-side (`/ws/terminal`, `/api/codex*`, `/api/mcp*`).
- [x] Define WebSocket auth transport (token in query string for `/ws/terminal`).
- [x] Add capability flags (`ENABLE_TERMINAL`, `ENABLE_CODEX`, `ENABLE_MCP`, `ENABLE_INDEXING`) with safe defaults.
- [x] Add `SECURITY.md` with threat model + guidance.

## P1 — Backend refactor + lifecycle
- [x] Refactor backend into modules under `app/` and keep `uvicorn main:app` working.
- [x] Add FastAPI lifespan management for MCP subprocess and device-login cleanup.
- [ ] Unify Codex integration further (decide SDK vs CLI as primary, remove redundant paths if safe).
- [ ] Standardize API error schema across endpoints (single shape for UI).

## P2 — UI/UX, settings, admin, landing
- [x] Landing + route split (`/` landing, `/login`, `/app`) and UI redirects updated.
- [x] Split `static/dashboard.html` into JS/CSS files (`static/dashboard.js`, `static/dashboard.css`).
- [~] Theme tokens shared across login + dashboard (single source of truth via `static/theme.css`).
- [~] Separate Settings vs Admin dashboard (admin section scaffolded; full dedicated pages pending).

## P2 — Provider auth parity (Codex/Gemini/Claude)
- [x] Codex auth file generation from env/secrets (`~/.codex/.auth.json` and `~/.codex/auth.json`).
- [ ] Gemini auth file parity (only if CLI requires; otherwise env-only with docs).
- [ ] Claude auth file parity (only if CLI requires; otherwise env-only with docs).
- [x] Optional SSH key support via Secrets (`SSH_PRIVATE_KEY`, `SSH_PUBLIC_KEY`, `SSH_KNOWN_HOSTS`).

## P2 — Codex workspace directory (UI)
- [x] Add UI setting for Codex working directory.
- [x] Enforce allowlisted root server-side and create directories as needed.

## P2 — Stream Codex events in Agent mode
- [x] Use `/api/codex/cli/stream` for agent execution.
- [x] UI renders streaming events + partial text (agent mode and chat target).
- [ ] Stop/reconnect improvements (resume stream after transient disconnects).

## P2/P3 — MCP registry
- [~] First-class MCP registry storage (per-user persistence via backend).
- [~] Admin-managed MCP templates (server-side persisted).
- [ ] “Test connection”, “list tools”, tool allow/deny UI (SSRF-safe).
- [ ] Import/export `mcp.json` via UI with validation.

## P3 — RAG + indexing (docs/web/GitHub) + “password manager”
- [ ] Clarify “password manager” scope and threat model.
- [x] Document upload indexing connector (MVP: text-only, keyword search).
- [ ] Website crawler indexing (depth/allowlist/robots/rate limits).
- [ ] GitHub repo indexing connector (branch/path filters + token support).
- [ ] Jobs UI (progress/retries/errors/access controls).

## P3 — P2P pubsub chat + account manager
- [ ] Account manager: identities/devices, memberships, permissions, moderation.
- [ ] Transport: WebRTC DataChannel + signaling, with server pubsub fallback.
- [ ] UX: rooms, presence, delivery status, network mode indicators.

## Engineering hygiene
- [x] Add `.env.example`.
- [x] Add `docs/ARCHITECTURE.md`, `docs/SECURITY_DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`.
- [x] Add lint/tests + CI (`ruff`, `pytest`, `.github/workflows/ci.yml`).
