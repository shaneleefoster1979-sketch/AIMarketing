# AI Marketing — Jared Rhod System

A portable, self-contained marketing operating system for use with Claude. It has two halves
that work together:

- **`marketing-skills/`** — a priming pack that teaches Claude how to think and write like an
  experienced direct-response marketer: the funnel model, core principles, voice, and
  channel-specific playbooks (copywriting, email, paid ads, lead magnets, sales letters,
  content strategy, analytics).
- **`memory-vault/`** — a boot-and-persistence layer so a Claude session (or a sequence of
  sessions) can carry context forward: what's been decided, what's in flight, and what to
  pick up next time, instead of re-deriving everything from scratch every conversation.

## How it fits together

1. On session start, Claude reads `memory-vault/CLAUDE.md`, which points to
   `VAULT-INDEX.md` and `MEMORY.md` to load current state.
2. When a marketing task comes up, Claude loads `marketing-skills/SKILL.md`, which routes to
   `core-principles.md`, `the-fundamentals.md`, and the relevant playbook in
   `marketing-skills/playbooks/`.
3. New decisions, campaigns, and open threads get written back into the vault using the
   templates in `memory-vault/templates/`, so the next session inherits them.

## Layout

```
marketing-skills/
  SKILL.md               entry point — when and how to use this pack
  core-principles.md      the non-negotiables behind every piece of output
  the-fundamentals.md     the funnel: awareness → lead magnet → nurture → offer → close → retain
  about.md                voice, positioning, and the operator persona
  playbooks/
    copywriting.md
    sales-letters.md
    email-marketing.md
    paid-ads.md
    lead-magnets.md
    content-strategy.md
    analytics.md

memory-vault/
  CLAUDE.md               boot sequence — read this first, every session
  VAULT-INDEX.md          map of everything else in the vault
  MEMORY.md               running log of durable facts and decisions
  BUILD-VAULT.md          how to initialize or repair a vault from scratch
  templates/
    daily-note.md
    project-note.md
    job.md
    priorities.md
```

## Getting started

Point a Claude session at this repo and have it read `memory-vault/CLAUDE.md` first. From
there it will know where to find everything else.
