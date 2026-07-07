# Memory Vault — Boot Instructions

Read this file first, at the start of every session that touches this repo. It tells you what
to load and in what order so context carries forward instead of being re-derived from scratch.

## Boot sequence

1. **Read `VAULT-INDEX.md`** — the map of everything else in the vault: what exists, where it
   lives, and when it was last touched.
2. **Read `MEMORY.md`** — the running log of durable facts, decisions, and standing
   preferences. This is the source of truth for "what have we already decided" — don't
   re-litigate something logged here without a stated reason to revisit it.
3. **Check for open threads** — look for the most recent entries in `MEMORY.md` and any
   project notes (see `templates/project-note.md`) with unresolved next steps. Surface these
   to the user early in the session rather than waiting to be asked.
4. **Load `../marketing-skills/SKILL.md`** if the session's task is marketing work (writing
   copy, planning a funnel, reviewing performance) — see that file's routing table for which
   specific playbook to read.

## During the session

- Treat `MEMORY.md` as append-only for durable facts (decisions made, positioning locked in,
  results of tests run). Don't delete history; if something is superseded, add a new entry
  that says so and let the reader see the change over time.
- Use `templates/daily-note.md` for session-scoped work logs, `templates/project-note.md` for
  anything that spans multiple sessions, `templates/job.md` for a discrete task with a clear
  done-state, and `templates/priorities.md` for the current ranked list of what matters most
  right now.

## Before ending a session

Write back anything a future session would need:

- New durable decisions → append to `MEMORY.md`.
- New or updated in-flight work → update the relevant project note.
- Anything that changed the priority ranking → update `templates/priorities.md`'s live copy
  (not the template itself).

If nothing changed, say so explicitly rather than leaving it ambiguous whether the vault is
up to date.

## If the vault is missing or looks broken

See `BUILD-VAULT.md` for how to initialize a fresh vault or repair one that's missing
expected files.
