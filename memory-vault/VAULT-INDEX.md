# Vault Index

Map of everything in `memory-vault/`. Update this file whenever a new note, job, or project
file is added elsewhere in the vault, so future sessions can find it without searching blind.

## Core files

| File               | Purpose                                                        |
|---------------------|------------------------------------------------------------------|
| `CLAUDE.md`          | Boot sequence — read first, every session                        |
| `VAULT-INDEX.md`     | This file — map of the vault                                      |
| `MEMORY.md`          | Append-only log of durable facts, decisions, and preferences      |
| `BUILD-VAULT.md`     | How to initialize or repair a vault from scratch                  |

## Templates

| File                        | Use for                                                  |
|------------------------------|-------------------------------------------------------------|
| `templates/daily-note.md`    | Session-scoped work log (what happened this session)         |
| `templates/project-note.md`  | Anything spanning multiple sessions (a campaign, a build)     |
| `templates/job.md`           | A discrete task with a clear done-state                      |
| `templates/priorities.md`    | Current ranked list of what matters most right now            |

## Active projects

_None yet. When a project note is created (copy `templates/project-note.md`, don't edit it
directly), list it here with a one-line status so it's discoverable without opening every
file._

Example row format once projects exist:

| Project | Status | Last updated | Notes file |
|---------|--------|--------------|------------|
| Q3 email relaunch | In progress | 2026-07-06 | `projects/q3-email-relaunch.md` |

## Maintenance

- Keep this index in sync whenever a file is added or removed elsewhere in the vault — an
  index that lags reality is worse than no index, since it creates false confidence.
- If the vault grows large, consider splitting `MEMORY.md` by topic or date range and linking
  the split files from here rather than letting one file grow unbounded.
