# Labeling comments

Code: [`apps/api/labeling/`](../../apps/api/labeling/), [`apps/api/routers/labeling.py`](../../apps/api/routers/labeling.py).
Table: `comment_label`. Page: **Label comments** in the sidebar. The rules the labeler follows are in
`docs/guidelines/constructiveness.md` and, in short form, beside the comment on the page.

The goal is a set of YouTube comments, each marked **constructive criticism** or **not**, to train and test a binary
classifier. The labeler is one person who will do this by hand for a long time, so the page is built around speed and
not losing work.

## Why a queue, one comment at a time

Labeling is repetitive, and the cost is mostly the time between comments. The page shows one comment large, decides on
a single key press (C, N, S, D), and moves on at once while the save happens in the background. It shows the next few
comments too, so the labeler can see what is coming, but only the first one can be decided: seeing a list invites
comparing comments with each other, which makes the labels less consistent.

Nothing is lost on a failure. A save that fails puts its comment back on screen with the error; a held key is ignored
(`e.repeat`) so one long press cannot label twenty comments; a button that was clicked is un-focused so Enter or Space
cannot press it again on the next comment; and shortcuts are ignored while typing in a text box.

## Why random order for the first pass

If the labels will be used to say "about X% of comments are constructive", the comments labeled must be a random draw
from the pool. Labeling the ones that look interesting would overstate the share. So the only queue mode today is
`random`: a random sample of the whole pool, not newest first and not one video after another.

Two details keep it honest and pleasant. Each label records which `queue_mode` served it, so later modes (comments that
look likely to be constructive, comments the model is unsure about) can be added without contaminating the estimate:
the share is computed only from `random` labels. And random order does not mean clusters: a naive draw of eight
comments can give five from one popular video, and the labeler then judges them against each other. The queue is
sampled from a pool four times larger and then ordered so neighbours come from different videos whenever the sample
allows. This is best effort: if only one video has comments left, it is all there is.

Replies are left out (they answer another comment and mean little alone), and so are comments past their expiry.
**Skip** puts a comment at the back: skipped comments are shown again only after every never-seen comment is done.
**Discard** means "I do not want this in the dataset"; the comment never comes back.

## Why tags

The label that is trained on is binary. Depth (basic, specific, advanced) and aspect (audio, video quality, pacing,
content accuracy, title or thumbnail, delivery, other) are optional and only stored for constructive comments, which a
CHECK constraint enforces. They cost one or two extra key presses and answer questions that the binary label hides:
are the positives all the vague kind? Does the model only catch audio complaints? They are a coverage check while
collecting and a breakdown of errors later, not a second target.

## How labeled text is kept, and why

Comments come from the YouTube API and live in MongoDB for 30 days, then a TTL index deletes them (see
[youtube-api.md](youtube-api.md)). A label without its text is useless, so the owner decided that a comment labeled
**constructive** or **not constructive** has its text copied into Postgres (`comment_label.text`) and kept, together
with the video id and title, like count, publish date and stratum at that moment. Keep this in mind: it is a deliberate
exception to "public data is deleted at 30 days", and the reason is that it is the research dataset.

A **discarded** comment keeps only its id and status, so it never reappears and no text is stored. A **skipped** one
keeps its id, status and queue mode. The CHECK `text IS NOT NULL` exactly for the two kept statuses means the database
refuses a row that breaks this.

`comment_label` has no `client_id`: comments are a research corpus, not a client's data, so deleting a client does not
touch it (a test checks this). The migration (`0004`) is reversible and its downgrade drops only this table.

A comment can disappear from MongoDB between "next" and "submit". Then the save answers 404 `{"error": ...}` and writes
nothing, unless the comment already has a stored copy (a relabel works from that copy).

**Undo** reverts the most recent change. Each row keeps its previous state (`previous`, one level), so undoing a
first label deletes the row and undoing a relabel restores the earlier label. Repeating the same decision (a double
click) changes nothing, so it cannot overwrite the state that Undo goes back to.

## Class imbalance and the Wilson interval

Constructive comments are probably a small minority, perhaps one in ten or fewer. Two consequences:

* A model that says "not constructive" every time is right most of the time, so **accuracy is misleading**; the metrics
  that matter are precision and recall for the constructive class. That is why the page reports the share and not a
  score, and why the stats keep the tag breakdowns.
* A small class needs many labels. The progress strip shows the share with a 95% interval so it is visible how
  uncertain it still is.

The interval is the **Wilson score interval**, computed by hand in `labeling/stats.py`. The textbook interval
`p ± 1.96·sqrt(p(1−p)/n)` fails exactly where this project lives: with few labels or a rare class it can go below 0 and
it collapses to zero width when no positive has been seen yet. Wilson stays inside 0 to 1 and widens honestly: 0 of 10
gives about 0% to 28%, not "0% exactly". Worked example, 3 constructive of 10: centre
`(0.3 + 1.96²/20) / (1 + 1.96²/10) = 0.356`, half-width `0.248`, so 11% to 60%. It would take hundreds of labels to
narrow this to a few points.

The figure is only meaningful for `random` labels, and the API and page say so.

## You should be able to explain

1. Why the first queue mode is random, and what would go wrong with a queue of "interesting" comments.
2. Why each label records the queue mode that served it.
3. Why neighbours in the queue should come from different videos, and how the queue arranges that.
4. What skip and discard do differently, and what is stored for each.
5. Why labeled text is kept in Postgres although public YouTube data is deleted after 30 days, and which comments keep text.
6. Why `comment_label` has no `client_id`, and what test shows that deleting a client leaves it alone.
7. What happens when a comment expires between being shown and being labeled.
8. How Undo knows what to restore, and why repeating a decision must not overwrite it.
9. Why accuracy is a poor measure with this class balance, and what to look at instead.
10. Why the Wilson interval and not `p ± 1.96·sqrt(p(1−p)/n)`; what does it give for 0 of 10?
11. Why do keyboard shortcuts ignore held keys and text inputs, and why does a clicked button lose focus?
