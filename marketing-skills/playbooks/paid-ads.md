# Playbook: Paid Ads

Applies to paid acquisition across Meta, Google, YouTube, TikTok, and similar platforms.
Assumes `core-principles.md` and `playbooks/copywriting.md` are already loaded.

## Before writing any ad copy

Confirm these are already decided — ad copy can't fix a wrong answer to any of them:

- **Audience**: who exactly is this targeting, and why do they have this problem now?
- **Offer**: what's the specific thing being offered at the end of the click (not just "learn
  more")?
- **Objective**: awareness, lead gen, or direct sale? The right ad format and copy differ by
  objective — don't write a cold-awareness hook and a hard-close CTA in the same ad.

## Structure by objective

- **Cold / awareness ads**: pattern interrupt + relatable problem statement. Soft or no direct
  CTA to buy; the job is a stop-scroll and a first impression, not a close.
- **Warm / retargeting ads**: reference the specific thing they engaged with (viewed product,
  read the article, watched % of video). Handle the objection that's most likely stopping
  them specifically.
- **Direct-response / conversion ads**: full hook-problem-solution-proof-CTA structure, same
  as `copywriting.md`, compressed to platform constraints.

## Platform-specific notes

- **Meta/Instagram**: native-feeling creative outperforms polished ads for cold audiences —
  UGC-style and founder-to-camera formats typically beat produced video for cost per result.
  First 3 seconds of video must contain the hook.
- **Google Search**: intent is already present — lead with the specific solution, not a
  problem-agitation hook. Match headline language to actual query language.
- **YouTube**: pre-roll needs the hook before second 5, since skip is available at 5s on
  skippable formats.
- **TikTok**: native, fast-cut, sound-on by default. Overtly "ad-like" production typically
  underperforms native-style content.

## Testing discipline

- Change one variable per test (hook, creative format, audience, or offer) — testing multiple
  variables at once makes results unreadable.
- Give a test enough spend/impressions to reach statistical relevance before killing or
  scaling — killing a test after a few hours on noise is a common wasted-spend mistake.
- Kill criteria and scale criteria should be defined *before* the test launches (e.g. "kill
  below $X CPA after $Y spend; scale budget 20% if above target ROAS for 3 consecutive days").

## Reporting essentials

Track cost per result, but tie it back to actual downstream value (CAC vs. LTV), not just
platform-reported conversions — platform attribution frequently overstates contribution,
especially across multi-touch journeys. See `analytics.md` for full metric definitions.
