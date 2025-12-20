# Security Notes

This app includes features that can become remote-code-execution (RCE) if exposed publicly:
- Web terminal (`/ws/terminal`)
- Agent/Codex execution (`/api/codex*`)
- MCP tool calls (`/api/mcp*`)
- Rooms WebSocket (`/ws/rooms`) if misconfigured (cross-user data exposure)
- Vault storage (`/api/vault`) if the UI is compromised (XSS can exfiltrate decrypted secrets)

## Current protections
- The dashboard UI requires a Supabase session.
- The backend also enforces Supabase authentication for terminal/Codex/MCP endpoints (server-side).

## Deployment guidance
- Do not run this app publicly without authentication.
- Use Hugging Face Spaces Secrets (or env vars) for all credentials.
- Consider disabling dangerous capabilities unless you explicitly need them:
  - `ENABLE_TERMINAL`
  - `ENABLE_CODEX`
  - `ENABLE_MCP`
  - `ENABLE_INDEXING`
  - `ENABLE_ROOMS`
  - `ENABLE_VAULT`

## Notes
- Browser clients cannot set `Authorization` headers for WebSockets, so the terminal WebSocket uses a Supabase access token passed via a query param. Treat app access tokens as sensitive.
- Rooms WebSocket uses the same token-in-query transport. Treat access tokens as sensitive and avoid logging them.
- If you add RAG indexing, crawling, or repository ingestion, apply the same auth + rate limiting + allowlisting patterns.
