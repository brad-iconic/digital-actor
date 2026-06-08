# TTS Safety

Every spoken line — pre-authored (`opening_speech.txt`, trigger `prompt.txt` / `narrator.txt` content
that reaches the speech model) and live-generated — runs through a text-to-speech voice. These
rules are not stylistic preferences; they prevent the voice from mangling delivery.

## The rules

- **Never use em-dashes (—) or en-dashes (–) in spoken text.** They break the speech model. Use
  a period or a comma instead, even where a dash would read better on the page. Hyphens (`-`)
  are fine inside hyphenated words.
- **Punctuation is direction.** Be deliberate:
  - `.` — neutral end-of-thought.
  - `,` — micro-pause / breath.
  - `?` — inquiry (do not chain with `!`).
  - `!` — urgency / high energy.
  - `...` — soft trailing pause, thinking, or a held beat. Use the three-character ellipsis,
    not the single unicode `…`.
- **Read multi-digit numbers as whole values.** Write `twelve` not `12` when the character
  speaks it. If a digit string must appear, guide the delivery with punctuation (e.g. an
  ellipsis before a list's final item).
- **Disfluencies are TTS-friendly when they're text.** "um", "uh", "huh", "well...", a short
  word repair ("I... I don't know") all parse cleanly. But rotate them — the same filler
  twice in a row sounds like a tic, not a person.
- **Short sentences.** Spoken English is not paragraph English. Fragments are natural. One to
  three sentences per spoken turn is the live LLM's target; mirror that in any pre-authored
  spoken text.

## Where these rules must be enforced

- Every spoken line in `opening_speech.txt`.
- Every trigger `prompt.txt` whose output is spoken back to the player (which is most of them
  — a trigger prompt instructs the model to *say* something).
- Every `narrator.txt` whose contents are logged into conversation history and may later be
  read aloud as recap.
- The style rules in `character_back_story.txt` (where the writer expands the architect's
  voice brief into delivery rules the live LLM will follow on every generated line).

## Where these rules do NOT apply

- Inside `back_story.txt`, `scene_description.txt`, `steer_back_instructions.txt`, and the
  *narrative* portions of `character_back_story.txt`. Those are read by the LLM as written
  prose context, not spoken aloud — write them in clean written English.
- Inside `narrator.txt` lines that are stage directions (e.g. "The player draws their
  {{weapon}}") rather than dialogue.

## Sanity check before declaring a file done

If the file contains spoken text:
- Grep for em-dashes and en-dashes. None allowed.
- Grep for the unicode ellipsis `…`. Replace with `...`.
- Read it aloud (mentally). If a sentence is longer than ~25 words, break it.
