# Repository Guidelines

## Project Structure & Module Organization

- `main.py`: app entrypoint (loads dotenv, creates FastAPI app).
- `app/`: backend package; feature routers live in `app/routes/` (chat, codex, mcp, terminal, user, admin, rag).
- `static/`: frontend assets (`landing.html`, `index.html`, `dashboard.html` + `dashboard.js`/`dashboard.css`).
- `tests/`: pytest suite (security-gate coverage is especially important).
- `docs/`: architecture and ops notes (start with `docs/ARCHITECTURE.md`).

## Build, Test, and Development Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn main:app --reload --host 0.0.0.0 --port 7860
```

- Lint/format: `ruff check .` and `ruff format .`
- Tests: `pytest -q`
- Docker (Spaces-like): `docker build -t autonomy-labs . && docker run --rm -p 7860:7860 --env-file .env autonomy-labs`

## Coding Style & Naming Conventions

- Python 3.11+, 4-space indentation; prefer explicit types for API payloads and settings.
- Keep modules small: add new routes under `app/routes/<feature>.py` instead of growing large files.
- Ruff is the source of truth (line length is 120); fix lint before pushing.

## Testing Guidelines

- Use `pytest` and keep tests fast and isolated (set env via `monkeypatch`).
- Name tests `tests/test_<topic>.py` and add coverage for:
  - auth enforcement on dangerous endpoints (`/ws/terminal`, `/api/codex*`, `/api/mcp*`)
  - feature flags (e.g., `ENABLE_CODEX=0` should hard-disable routes).

## Commit & Pull Request Guidelines

- Commits use short, imperative subjects (e.g., “Add RAG document indexing MVP”), no required prefixes.
- PRs should include: summary, how you tested (`pytest -q`, `ruff check .`), screenshots for UI changes, and any new env vars documented in `.env.example`.

## Security & Configuration Tips

- Never commit secrets; use environment variables / Hugging Face Spaces Secrets.
- High-risk features are gated by Supabase auth and flags (`ENABLE_TERMINAL`, `ENABLE_CODEX`, `ENABLE_MCP`, `ENABLE_INDEXING`). Keep defaults conservative and document changes in `SECURITY.md`.

## Deployment notes (HF Spaces)
- Port: `7860`
- Persistence: `/data` is used for `~/.codex`, `~/.ssh`, and a default workspace directory when available.
- Web terminals often require device auth flows; avoid localhost callback assumptions.
