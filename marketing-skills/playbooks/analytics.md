# Playbook: Analytics & Reporting

Applies to performance review, reporting, and deciding what to scale, fix, or cut. Assumes
`the-fundamentals.md` is already loaded so metrics can be mapped to the funnel stage they
measure.

## Metrics by funnel stage

| Stage        | Primary metrics                                   |
|---------------|-----------------------------------------------------|
| Awareness      | Reach, impressions, cost per reach (paid), engagement rate |
| Lead Magnet    | Opt-in rate, cost per lead (paid)                     |
| Nurture        | Open rate, click rate, sequence completion rate       |
| Offer          | Page conversion rate, cost per acquisition (CPA)      |
| Close          | Checkout completion rate, cart abandonment rate       |
| Retain/Refer   | Repeat purchase rate, churn/refund rate, referral rate, LTV |

## Affiliate-specific metrics

When you're promoting someone else's product (see `playbooks/affiliate-marketing.md`), the
Offer and Close stages above are only partly visible to you — the vendor's checkout sits
outside your tracking. Use these instead/in addition:

| Metric                     | What it tells you                                                  |
|------------------------------|------------------------------------------------------------------------|
| EPC (earnings per click)     | Revenue generated per click sent to the vendor — the single best number for comparing different offers against each other, since it nets out the vendor's own conversion rate and commission structure into one figure. |
| Cookie duration               | How long after a click you still get credit for a purchase — affects how directly a promotion's results map to a single send/post, especially for considered purchases. |
| Vendor-side conversion rate   | The rate at which your clicks convert on the vendor's page — not directly controllable, but worth tracking per-vendor to catch an offer that's degraded (e.g. a vendor raised price or broke their checkout). |
| Revenue per subscriber/segment | Tracked over time per list segment, not just per promotion — the number that tells you whether a segment is worth continuing to nurture and monetize. |
| Refund/chargeback rate (where visible) | An early warning that an offer is a poor fit for your audience, even if EPC currently looks fine. |

Report EPC next to CPA/CAC exactly the way LTV is reported below — a high EPC with a low cost
to reach the audience is the affiliate equivalent of a healthy LTV:CAC ratio.

## The metric that matters most: LTV vs. CAC

Every acquisition decision ultimately comes down to whether lifetime value exceeds customer
acquisition cost by a healthy enough margin to fund growth and cover overhead. A campaign with
an impressive-looking CPA that doesn't clear this bar isn't actually working, and a campaign
with a scary-looking CPA might be fine if LTV supports it. Always report CAC next to LTV, not
in isolation.

## Reading a funnel report

1. Find the stage with the steepest drop-off relative to typical benchmarks for that stage —
   that's usually the highest-leverage fix, more so than optimizing a stage that's already
   converting well.
2. Distinguish a volume problem (not enough people entering the stage) from a conversion
   problem (enough people, but too few advancing) — the fixes are different and often
   confused.
3. Check for confounds before concluding a change caused a metric shift: seasonality,
   platform algorithm changes, list fatigue, and tracking/attribution changes all mimic real
   performance changes.

## Reporting cadence

- **Daily**: spend and pacing checks on active paid campaigns only — not a full report.
- **Weekly**: funnel-stage conversion rates, top/bottom performing assets, list health.
- **Monthly**: full LTV/CAC review, cohort retention, and a decision on what to scale, pause,
  or kill.

## Reporting format

Lead every report with the decision it implies ("Scale the retargeting ad set 20%; kill the
lookalike ad set"), then show the numbers that justify it. A report that's all numbers and no
recommendation pushes the analysis work back onto the reader.
