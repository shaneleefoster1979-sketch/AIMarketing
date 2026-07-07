# Memory Log

Append-only. Each entry is a durable fact, decision, or preference that future sessions
should treat as already-settled unless a later entry explicitly revisits it. Newest entries
at the bottom. Don't delete or rewrite old entries — if something changes, add a new entry
that says what changed and why.

Entry format:

```
## YYYY-MM-DD — Short title
Context: why this came up.
Decision/fact: what was decided or learned.
Status: active | superseded by <link/date> | resolved
```

---

## 2026-07-06 — Vault initialized

Context: Setting up the AI Marketing Skills + Memory Vault system for this repository, as a
portable priming pack for marketing work.

Decision/fact: `marketing-skills/` holds the marketing knowledge (principles, funnel model,
voice, and channel playbooks). `memory-vault/` holds session-to-session persistence (this
file, the index, templates). Sessions should read `memory-vault/CLAUDE.md` first.

Status: active
