# “Password manager” scope (clarification)

This repo currently **does not implement a password manager / secure vault**.

## Why this matters

A real password manager is a high-risk feature. To do it safely you need:
- client-side encryption (or a trusted enclave) and a clear key-derivation strategy
- strict access controls and auditing
- safe handling of backups/exports
- threat modeling for the deployment environment (HF Spaces, browser clients, admin operators)

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

