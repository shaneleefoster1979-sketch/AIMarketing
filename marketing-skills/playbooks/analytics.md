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
