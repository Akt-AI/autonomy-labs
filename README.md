# Sandbox Agent Hub

React-based control center for AI chat, terminal, embedded browser, and n8n/MCP agent workflows. Ships as a FastAPI backend with WebSocket terminal support and containerized tooling.

## Features
- AI chat with streaming Markdown/Katex/HLJS rendering, attachments, and screenshot capture via html2canvas.
- @agent n8n trigger panel (API key + base URL + workflow ID) using `X-N8N-API-KEY`.
- Autonomous mode that splits chat, terminal, and browser side-by-side for agent runs with feedback capture.
- Embedded web browser tab with quick URL launcher.
- MCP host admin panel with default servers (n8n-mcp docs/api, filesystem, gemini, claude, codex, canva, github) and localStorage-backed config.
- Web terminal (xterm.js) hooked to `/ws/terminal` for container shells (vim, git, codex, gemini-cli, claude-cli available).

## Running locally
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 7860
```
Open `http://localhost:7860` to access the React UI.

## Container build
Dockerfile installs Python deps plus vim/git/chromium and lightweight shims for codex, gemini-cli, and claude-cli. Build and run:
```bash
docker build -t sandbox-agent .
docker run -p 7860:7860 sandbox-agent
```

## Notes
- Chat endpoint: `POST /api/chat` (OpenAI-compatible streaming).
- Terminal WebSocket: `/ws/terminal`.
- Config endpoint: `/config` returns Supabase keys if provided.
- MCP configs persist in browser localStorage.
