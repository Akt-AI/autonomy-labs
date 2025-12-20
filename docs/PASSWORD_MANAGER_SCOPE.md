# “Password manager” scope (clarification)

This repo now includes an **experimental encrypted vault MVP** (client-side encryption, server-side storage), but it is **not a production-grade password manager**.

## Why this matters

A real password manager is a high-risk feature. To do it safely you need:
- client-side encryption (or a trusted enclave) and a clear key-derivation strategy
- strict access controls and auditing
- safe handling of backups/exports
- threat modeling for the deployment environment (HF Spaces, browser clients, admin operators)

## What we implemented (MVP)

- Feature flag: `ENABLE_VAULT=1`
- UI: Settings → Vault (Encrypted)
- Encryption: browser-only (WebCrypto `PBKDF2` + `AES-GCM`)
- Storage: per-user encrypted blob persisted server-side at rest (the server never receives the password)

Important limitations:
- If your browser is compromised (XSS, malicious extensions), your vault can be compromised.
- There is no key rotation, export, recovery, or audit logging yet.
  Treat this feature as a convenience tool for personal/dev use, not as a hardened credential vault.

## What we can safely support first (recommended)

**Indexed private notes / secrets references** (lower risk than storing raw credentials):
- store *non-sensitive* snippets and references (e.g., “service X uses token Y stored in HF secret Z”)
- use the existing RAG indexing pipeline for retrieval
- keep actual secrets in HF Spaces Secrets or Supabase (never in git)

## If you want a real vault

We should treat it as a separate milestone:
1. Define threat model (who can read, what happens if admin/host is compromised).
2. Choose encryption strategy (client-side keys vs server-managed keys).
3. Add UX for create/unlock/lock, rotate keys, and recovery.
4. Add audit logging, rate limiting, and tests.
