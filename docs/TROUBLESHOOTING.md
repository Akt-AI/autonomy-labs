# Troubleshooting

## “Token data is not available.” (Codex CLI)

Common causes:
- The container wasn’t restarted after setting Secrets.
- The auth file wasn’t written to `~/.codex/.auth.json`.

In the terminal, check:
- `ls -la ~/.codex`
- `cat ~/.codex/.auth.json`

If you use env-based token auth, set one of:
- `CODEX_ID_TOKEN` or `ID_TOKEN`
- `CODEX_ACCESS_TOKEN` or `ACCESS_TOKEN`
- `CODEX_REFRESH_TOKEN` or `REFRESH_TOKEN`
- optional `CODEX_ACCOUNT_ID` or `ACCOUNT_ID`

Notes:
- You do not need to provide `last_refresh` as a Secret; it is written automatically.

## Gemini / Claude CLI authentication

This repo prefers env-based auth for provider CLIs (keep tokens out of git and UI):
- Gemini: `GEMINI_API_KEY`
- Claude: `ANTHROPIC_API_KEY`

## RAG endpoints return 403 (“Indexing is disabled”)

Set `ENABLE_INDEXING=1` in your environment and restart the container.

## Website indexing fails (“Host is not allowed”)

Website indexing blocks private/localhost targets to reduce SSRF risk.
Use a public `http(s)` URL and keep indexing within the same origin.

## GitHub indexing fails for private repos

Set `GITHUB_TOKEN` (or `GITHUB_PAT`) as an environment variable / HF Secret, then retry.

## Terminal shows vertical/1-column text

This usually means the terminal “fit” ran while the terminal view was hidden or at size 0.

Mitigations:
- Switch to the Terminal view after the page fully loads.
- Resize the browser window once to trigger a refit.

## MCP “Test” fails even though the server is up

The Settings → MCP “Test” button runs from your browser, so it is subject to CORS and network access from the client.

Also note:
- `mcp.json` import only accepts `http://` / `https://` URLs.
- If MCP tool calls are blocked, check Settings → MCP → Tool Policy (server-enforced allow/deny list).

## API errors are shown as JSON

The backend returns a consistent error payload like:
`{"detail":"...","error":{"code":"...","message":"...","status":...,"details":...}}`.

## PTY allocation failed

If the backend prints `PTY allocation failed`, the runtime likely lacks `/dev/pts` or has exhausted PTYs.

HF Spaces generally supports PTYs, but custom runtimes may not.

## Rooms returns 403 (“Rooms are disabled”)

Set `ENABLE_ROOMS=1` in your environment and restart the container.

Admins can also toggle feature overrides from Settings → Admin.

## P2P isn’t connecting in Rooms

The Rooms view uses WebRTC DataChannels (optional, behind “Prefer P2P”). Some networks block UDP/WebRTC.
If P2P fails, keep “Prefer P2P” off and it will use server WebSockets for messaging.

## Password reset emails aren’t arriving

Supabase email delivery depends on your project auth settings and SMTP configuration.
Check Supabase → Authentication → Settings (and SMTP) and verify your site URL/redirect URLs include `/login`.

## Password recovery link opens but “Update password” fails

Some Supabase recovery links include `access_token`/`refresh_token` in the URL hash. This app consumes those tokens and sets a session before calling `updateUser()`.

If it still fails:
- Verify the link points to your deployed `/login` URL.
- Verify Supabase Auth → URL Configuration includes your `/login` redirect URL.

## Vault is disabled

Set `ENABLE_VAULT=1` and restart the container (admins can also toggle the Vault feature override).
