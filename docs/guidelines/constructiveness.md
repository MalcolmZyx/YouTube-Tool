# Labeling guideline: constructive criticism

Version 0.1 (draft). Every comment gets one binary label: **constructive** or **not constructive**.
Rulings below were decided by the project owner; examples are placeholders until real comments are added.

## Definition

A comment is **constructive criticism** if it criticises something about the video, even informally or vaguely, and gives
some reason, cause or pointer for it. The creator could learn from it or act on it.

It does not need to be polite. In informal YouTube comments a blunt comment with a reason still counts.

## Rulings

| Case | Label | Reason |
|---|---|---|
| Criticism with a reason, specific ("music drowns out your voice") | Constructive | Specific and actionable |
| Criticism with a reason, vague ("too long, got bored") | Constructive | Informal and vague, but it names a cause |
| Blunt or rude, with a reason ("your intro is awful and way too long") | Constructive | The reason is what counts, not the tone |
| A specific correction or counter-fact ("that changed to paid in March") | Constructive | Gives evidence the creator can check |
| A suggestion for how to improve the video | Constructive | Gives a solution |
| Specific praise ("the editing in the second half was tight") | Not constructive | Informative, but not criticism |
| General praise ("great video") | Not constructive | |
| Questions ("how did you do the transition?") | Not constructive | Not criticism, and hard to decide reliably |
| Ideas for future videos ("do one on X next") | Not constructive | Helpful, but not criticism of this video |
| Negativity with no reason ("this sucks") | Not constructive | No reason given |
| Spam, self-promotion, jokes, "first" | Not constructive | |
| Emoji-only, timestamp-only, empty | Not constructive (ignored) | Nothing to judge |
| Non-English | Skipped | English only |
| Sarcasm | Not a label concern | Read the comment at face value; sarcasm is handled by other signals later |

## Optional tags (not required for the binary label)

The binary label above is the one that is trained on and reported. Tags are recorded only for comments labeled
constructive, as quick optional toggles. They exist to check coverage while collecting data (are the positives all the
basic kind?) and to break down the model's errors later (does it only catch basic criticism? does it fail on audio
feedback?).

**Depth** (pick one):
- **Basic**: vague, but names a cause ("too long, got bored", "audio is bad").
- **Specific**: points at an exact moment, part or problem ("the music drowns out your voice around 3:20").
- **Advanced**: technical or expert critique, with evidence or a fix ("your compressor settings are clipping the
  vocals; try a lower ratio").

**Aspect** (pick any that apply): audio; video quality; pacing or length; content accuracy; title or thumbnail;
delivery or presentation; other.

The comment-quality characteristics from the constructiveness research (solution, specific points, evidence, personal
experience, dialogue) informed these tags. They are not used directly, because "personal experience" or "dialogue"
alone do not make a comment constructive here: specific praise and questions are ruled out above.

## Open questions (decide while labeling)

- A comment that is partly praise and partly criticism: label it constructive if the criticism part meets the definition.
- Criticism of something outside the video (the platform, another commenter): not constructive.
- Add new rulings here as edge cases come up, with the date, so the guideline and the labels stay consistent.
