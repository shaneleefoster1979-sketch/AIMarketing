# Building or Repairing a Vault

Use this file when `memory-vault/` is missing entirely, missing expected files, or looks
inconsistent with `VAULT-INDEX.md`. This is a one-time (or occasional-repair) procedure, not
part of normal session boot — see `CLAUDE.md` for that.

## Initializing a fresh vault

1. Create the core files if they don't exist:
   - `CLAUDE.md` — boot instructions (copy the structure from this repo's version; it doesn't
     need project-specific content, just the sequence).
   - `VAULT-INDEX.md` — start with just the core-files table; leave "Active projects" empty.
   - `MEMORY.md` — start with a single "Vault initialized" entry (see the format at the top of
     that file) recording the date and why the vault was created.
2. Create `templates/` with the four templates (`daily-note.md`, `project-note.md`, `job.md`,
   `priorities.md`) — copy them rather than writing from scratch, so the format stays
   consistent across vaults.
3. Do not pre-create project notes or priorities speculatively — those get created the first
   time there's real content for them, using the templates.

## Repairing a vault that's missing files

1. Diff what exists against the file list in this document and in `VAULT-INDEX.md`.
2. Recreate missing core files using the initialization steps above.
3. If `VAULT-INDEX.md` references files that no longer exist, either restore them (if the
   content is recoverable, e.g. from git history) or remove the stale reference — don't leave
   the index pointing at nothing.
4. If `MEMORY.md` exists but conflicts with itself (two entries that contradict without one
   marked superseded), do not silently pick one — surface the conflict to the user and add a
   new entry once it's resolved.

## Repairing a vault that looks inconsistent

Signs of drift to watch for:

- `VAULT-INDEX.md`'s "Active projects" table lists a project whose notes file doesn't exist,
  or vice versa.
- `MEMORY.md` entries reference decisions that a project note contradicts without a
  superseding entry.
- Templates in `templates/` have been edited directly (they should stay generic; real content
  belongs in copies, not the templates themselves).

Fix drift by updating the index/log to match reality, not by silently deleting the
inconsistent side — a note in `MEMORY.md` describing the repair keeps the history honest.

## Principles for any vault, not just this one

- The vault should be readable by a new session with zero prior context — if a file assumes
  unstated background, that background belongs in `MEMORY.md`.
- Prefer several small, clearly-scoped files over one large file that mixes concerns.
- The vault records decisions and state, not conversation transcripts — summarize, don't
  paste raw dialogue.
