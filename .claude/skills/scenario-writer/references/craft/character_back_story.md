# Craft — `character_back_story.txt`

The deepest file in the scenario, and the only one that does double duty: it both
**establishes who the character is** (interior, history, epistemics, wants) and **teaches
the live LLM how this character sounds** (sentence shape, punctuation signature, tag
discipline, TTS-safety rules).

Structure the file in two parts: **The person** (written prose, not spoken) and **How they
speak** (instructions to the live LLM about delivery). Both parts matter and neither is
optional.

## Part 1 — The person

Pulls from the architect's character block in the blueprint. Your job is to take the
blueprint's compressed facts (role, wants, epistemics, one-paragraph voice brief) and
expand them into prose with enough specificity that the live LLM can improvise in
character across questions you never anticipated.

What to include:

- **History.** Specific events in their past that shaped who they are now. Names, places,
  dates if useful. Not "they had a difficult childhood" — *what happened*.
- **Values.** What they will and won't do. What lines they won't cross. What they value
  about other people. What they despise.
- **Wants.** What they want in this scenario, and (often) what they want underneath that.
  A character whose surface want is "find their sister" and underneath want is "be
  forgiven by her" is a real character.
- **Epistemics.** What they know. What they cannot perceive. What they're guessing about.
  Be **explicit** about the limits. If the architect's blueprint says they're blind to the
  mountain, the back_story must say *what they can hear, smell, feel that they're using to
  build a picture instead*.
- **Tells / soft spots / deflections.** The seams a real person has. A tell that gives them
  away when they lie. A topic that softens them. A topic they pivot away from.
- **How they handle pressure.** Calm characters under stress, panicky characters with a
  rare moment of stillness — written so the live LLM has a model to follow when the player
  pushes.

Length for this part: typically 400-1000 words for a rich character; 200-400 for a simple
one. Specificity is the bar, not length.

## Part 2 — How they speak

Expand the architect's one-paragraph voice brief into **delivery rules the live LLM follows
on every generated line**, made character-specific.

Required sub-rules (taken from `tts-safety.md` — restate them here so the live LLM sees
them in context for this character):

1. **Length.** One to three sentences per turn; fragments are good; do not write
   paragraph English.
2. **No em-dashes or en-dashes.** Use a period or a comma.
3. **Punctuation as direction.** State how *this character* uses each:
   - `.` (neutral end-of-thought)
   - `,` (micro-pause / breath)
   - `?` (inquiry)
   - `!` (urgency)
   - `...` (soft pause / thinking / held beat). State whether this character uses ellipses
     a lot (typical of slow, weather-worn, dazed, or thoughtful characters) or rarely
     (typical of crisp, efficient, manic characters).
4. **Disfluencies.** Which fillers fit this character ("uh", "um", "well...", a repeated
   word, a small repair) and which would feel wrong. Rotate them; same filler twice in a
   row sounds like a tic.
5. **Emotional tags.** Every generated line must begin with `[emotion, intensity]` from the
   allowed set: emotions = `anger`, `fear`, `joy`, `sadness`, `disgust`, `surprise`,
   `neutral`; intensities = `low`, `medium`, `high`. State which combinations are
   characteristic (a stoic character's default may be `[neutral, low]`; a manic one's may
   be `[joy, high]`).
6. **Volume range.** Does this character get louder or quieter under pressure? Note it.
7. **Question/statement ratio.** Does this character answer in statements (most do) or in
   questions (some do)?

End Part 2 with two or three **example lines** in the character's voice, fully tagged,
demonstrating the rules. These are gold: the live LLM uses them as concrete patterns.

## Part 2 example template

```
Keeper speaks low and slow. One or two sentences a turn; fragments are normal. Lots of
commas and ellipses to make space for the weather. Never raises volume; goes quieter when
alarmed. Dry humour only when they've decided you aren't a threat.

- No em-dashes or en-dashes ever. Use a period or a comma.
- Default emotion-intensity is `[neutral, low]`. Surprise lands as `[surprise, low]`, not
  high. Alarm lands as `[fear, low]`, quieter than normal.
- Use `...` often, for held beats, for weighing a thought, for the second of two breaths.
- Disfluencies: a soft repair ("I... I'd ask again"). Almost never "um".
- Answer in statements, not questions. If you ask the player something, end it on a
  comma, not a question mark, unless you actually want them to answer right now.

Examples:
[neutral, low] Stop where you are. [neutral, low] Hands so I can see them.
[surprise, low] A name. [neutral, low] Good. A name's a place to start.
[neutral, low] Wind's turning. [fear, low] You'd best come up the path.
```

## What this file does NOT do

- It does NOT tell the character their *goal in this scene*. That's `scene_description.txt`.
- It does NOT tell the character how to handle off-topic players. That's
  `steer_back_instructions.txt`.
- It does NOT script the opening line. That's the `greet` trigger (or
  `opening_speech.txt`).

## Coherence anchor

After drafting, re-read the architect's voice brief and check: every axis the brief named
must be addressed somewhere in Part 2. If the brief said "almost never raises volume" and
your Part 2 doesn't mention volume, you've drifted. Fix it.
