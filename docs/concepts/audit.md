# The audit engine

Code: [`apps/api/audit/`](../../apps/api/audit/). Route: `GET /api/clients/{id}/audit`. Page: **Audit** in the sidebar.

An audit is a list of **findings** about a channel. Each finding has a headline, how far to trust it, its evidence, and
its caveats. The numbers are computed deterministically from the stored export; nothing is written by a language model,
so nothing can be invented.

## The principles (these matter more than the individual analyses)

1. **Say how sure you are.** Every finding carries a strength: *solid* (clear difference, enough videos), *suggestive*,
   *weak* (a hint only), *not enough data*, or *fact* (a description, no claim to test).
2. **Refuse rather than guess.** Fewer than 5 videos in a group: no number is reported. Fewer than 10: always "weak",
   whatever the p-value, because p-values from tiny samples are easy to get by luck.
3. **Show the size and the range, not only the p-value.** "Shorts get 2.8x the views (range 1.1 to 5.2)" tells you more
   than "p = 0.013". A range that includes 1 means "could be no difference".
4. **A blank is not a zero.** A video with no impressions (a Short) is left out of a click-rate comparison, not counted
   as a 0% click rate.
5. **Never average rates.** The channel click rate is weighted by impressions; a mean of per-video rates would let a
   video seen 100 times count as much as one seen 400,000 times.
6. **Reproducible.** Resampling uses a fixed seed; the same data gives the same report, byte for byte (a test checks it).

## The findings (first slice)

| Finding | What it computes | Statistics |
|---|---|---|
| Overview | videos, median views, how concentrated views are (share held by the top 10%) | descriptive; flags when the export's Total exceeds the videos' sum |
| Standout videos | views against what a video of **that age** usually has, so old videos do not win by being old | least-squares fit of log views on log age; the index is actual / expected |
| Upload rhythm | uploads per month, last 90 days against the 90 before, longest silence, weekday spread | descriptive |
| Shorts and long-form | do they get different views? | Mann-Whitney U, rank-biserial effect size, bootstrap range for the ratio of medians |
| Click-through opportunities | widely shown videos clicked less than typical | impressions-weighted rate; bottom-quarter threshold |

**Why Mann-Whitney and medians, not a t-test and means?** Views are heavy-tailed: one hit can be 50x the median, so the
mean says little and a t-test assumes bell-shaped data. A rank test compares typical videos and does not care how big
the hit was.

**Why a bootstrap?** To get a range for the *ratio of medians*, which has no simple formula: resample each group with
replacement 2,000 times, take the ratio each time, and read off the middle 95%.

## Limits we state in the product

* **Shorts are guessed from duration** (60 seconds or less): the export has no Shorts flag.
* **The "age" reference date** is the end of the date range, else the export date you gave, else the import day, and the
  page says which. Wrong reference dates shift every age.
* **The standout index assumes lifetime figures.** If the export covers a date range, older videos only show the views in
  that range; the page warns when the period is not confirmed as lifetime.
* **Click rate** depends on where views come from (search against browse); a low rate is a question about the title and
  thumbnail, not a verdict.
* **It finds associations, not causes.** "Shorts get more views" does not say posting more Shorts will help this channel.

## Not built yet (next slices)

Title features (length, questions, numbers) against the age-adjusted index, duration effects, retention, traffic-source
mix (needs a breakdown export), a printable or shareable report, and the comment themes once the classifier exists.
Checking many features at once needs a correction for multiple comparisons, which is why title features are a separate,
careful step.

## A note on the synthetic data

The fake channels plant one known effect: Shorts get 1.6x the views. The test suite checks the audit finds a Shorts
advantage on the channel with enough Shorts, and says "not enough data" on the channel with 2 Shorts. A method is only
trusted once it has recovered an effect we put there.

## You should be able to explain

1. Why does a finding carry a strength label, and what makes one "weak" regardless of its p-value?
2. Why compare medians with a rank test instead of means with a t-test?
3. What does the bootstrap range mean, and what does it mean when it includes 1?
4. Why is the channel click rate weighted by impressions? What goes wrong with a plain average?
5. How does the standout index stop old videos from winning just by being old, and when does it break down?
6. Why are blanks left out of the click-rate comparison instead of counted as 0?
7. Why is the audit computed from the database and not from the table the dashboard shows?
8. What is the difference between "Shorts get more views" and "post more Shorts"?
