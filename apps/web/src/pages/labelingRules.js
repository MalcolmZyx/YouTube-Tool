// The labeling rules shown beside the comment. A compact copy of docs/guidelines/constructiveness.md (version 0.1):
// when a ruling changes there, change it here too.

export const RULES = {
  version: '0.1 (draft)',
  definition:
    'Constructive criticism: the comment criticises something about the video, even informally or vaguely, and gives '
    + 'some reason, cause or pointer for it. The creator could learn from it or act on it. It does not need to be '
    + 'polite: a blunt comment with a reason still counts.',
  rulings: [
    ['Criticism with a reason, specific ("music drowns out your voice")', 'Constructive'],
    ['Criticism with a reason, vague ("too long, got bored")', 'Constructive'],
    ['Blunt or rude, with a reason ("your intro is awful and way too long")', 'Constructive'],
    ['A specific correction or counter-fact ("that changed to paid in March")', 'Constructive'],
    ['A suggestion for how to improve the video', 'Constructive'],
    ['Specific praise ("the editing in the second half was tight")', 'Not constructive'],
    ['General praise ("great video")', 'Not constructive'],
    ['A question ("how did you do the transition?")', 'Not constructive'],
    ['An idea for a future video ("do one on X next")', 'Not constructive'],
    ['Negativity with no reason ("this sucks")', 'Not constructive'],
    ['Spam, self-promotion, jokes, "first"', 'Not constructive'],
    ['Emoji-only, timestamp-only, empty', 'Not constructive'],
    ['Non-English', 'Skip'],
    ['Sarcasm', 'Read it at face value'],
  ],
  tags:
    'Tags are optional and only saved with Constructive. Depth: Basic is vague but names a cause; Specific points at '
    + 'an exact moment or problem; Advanced is technical or expert, with evidence or a fix. Aspect: pick any that apply.',
  open: [
    'Part praise, part criticism: constructive if the criticism part meets the definition.',
    'Criticism of something outside the video (the platform, another commenter): not constructive.',
    'Discard removes a comment from the dataset for good (no text is kept). Skip puts it at the back of the queue.',
  ],
}
