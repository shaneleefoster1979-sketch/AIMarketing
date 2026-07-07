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

## 2026-07-07 — Added affiliate marketing coverage

Context: Confirmed the pack should also support affiliate marketing — promoting third-party
products/brands for commission, including running multiple different brands to the same
audience over time, not just first-party offers.

Decision/fact: Added `marketing-skills/playbooks/affiliate-marketing.md` (offer selection
criteria, disclosure/compliance, multi-brand list sequencing) and extended
`marketing-skills/playbooks/analytics.md` with affiliate-specific metrics (EPC, cookie
duration, vendor-side conversion rate, revenue per subscriber). `SKILL.md`'s routing table and
the README now reference the new playbook.

Status: active

## 2026-07-07 — Push access to GitHub still broken

Context: The GitHub App integration used by this session's `github` MCP tools and the local
git proxy both return `403 Resource not accessible by integration` on writes to this repo,
even though reads work fine. Confirmed the app shows only under GitHub's "Authorized GitHub
Apps" list, not "Installed GitHub Apps" — meaning it has identity authorization but no actual
repo installation/write grant. Disconnecting and reconnecting the GitHub integration in Claude
Code's own settings did not fix it.

Decision/fact: Until this is fixed, the working pattern is: make changes locally in this
session, commit locally, then have the repo owner push/upload the changes manually via
GitHub's web UI (drag-and-drop upload, or creating branches/commits directly on github.com).
The branch `claude/jared-rhod-ai-project-ckmaij` was created this way and is kept in sync with
local work via `git fetch` + `git reset --hard origin/<branch>` once the owner confirms a
manual push landed.

Status: active
