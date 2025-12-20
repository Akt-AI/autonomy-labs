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

## RAG endpoints return 403 (“Indexing is disabled”)

Set `ENABLE_INDEXING=1` in your environment and restart the container.

## Terminal shows vertical/1-column text

This usually means the terminal “fit” ran while the terminal view was hidden or at size 0.

Mitigations:
- Switch to the Terminal view after the page fully loads.
- Resize the browser window once to trigger a refit.

## MCP “Test” fails even though the server is up

The Settings → MCP “Test” button runs from your browser, so it is subject to CORS and network access from the client.

Also note:
- `mcp.json` import only accepts `http://` / `https://` URLs.

## PTY allocation failed

If the backend prints `PTY allocation failed`, the runtime likely lacks `/dev/pts` or has exhausted PTYs.

HF Spaces generally supports PTYs, but custom runtimes may not.
