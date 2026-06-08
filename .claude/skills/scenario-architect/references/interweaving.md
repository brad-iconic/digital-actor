# Interweaving

A scenario with two characters who could swap dialogue without anything changing is a
collection, not a world. Interweaving is the work that turns characters and scenes into
something that feels connected. This reference is the toolkit for that work.

## Asymmetric knowledge

The strongest interweaving technique. Give characters **non-overlapping** pieces of the
truth about each other and the world.

- Character A knows what happened in the alley last night; character B does not.
- Character C knows character D's real name; the player and D don't.
- Character E lied to character F about something; F has not yet noticed.

Record asymmetric knowledge in each character's `epistemics` block in the blueprint.
Write it as bullets: "Knows: ..." and "Does not know: ...". The writer enforces this when
drafting `character_back_story.txt` and the steer-back tactics — the live LLM can only
keep secrets it was told are secrets.

## Shared history with diverging takes

Two characters can share an event and remember it differently. Sister and brother both
attended the funeral; she remembers it as a betrayal, he remembers it as a relief. Write
the *event* once in `back_story.txt` (world-level fact) and the *interpretation* in each
character's blueprint block.

This produces conversations where the player can ask both characters about the same
thing and get genuinely different answers — the single highest-impact thing for making a
world feel real.

## Scene-to-scene consequence

A scene with no consequence is a vignette. Scene 2 should be **different because of
something that happened in scene 1**. Concretely:

- The player learned a piece of information that the scene-2 character did not expect them
  to have.
- A character changed their mind, or lost something, or arrived somewhere new.
- A relationship moved — colder, warmer, more guarded.

Capture this in the blueprint's "Continuity notes" section as specific facts the writer
will translate into prose. *"Vivian now knows the player is uninjured but exhausted, and
trusts their reports more"* is usable. *"The story has progressed"* is not.

## Cross-character voice contrast

Voices should not just be different — they should be different along **dimensions you can
hear**. A useful technique is to pick two or three axes and place each character on them:

- *Sentence length:* clipped → flowing.
- *Punctuation signature:* periods → ellipses → exclamations → commas (the breathy one).
- *Disfluency rate:* zero (composed) → frequent (anxious, drunk, dazed).
- *Volume range:* monotone → wide dynamic range.
- *Question/statement ratio:* answers in statements vs. answers in questions.

In a multi-character scenario, make sure no two characters share the same point on more
than one axis. Write the axis values into each voice brief explicitly — it gives the
writer a clear delivery target for each character.

## Triggers as relationships

Triggers are not just openers and closers. They are also where the world reaches into the
character. Examples that interweave:

- `<other_character>_arrived` — fires when a different NPC enters the scene. The
  character reacts to *that specific other character*. Tone depends on the relationship
  in the blueprint.
- `player_mentioned_<topic>` — fires when the player names someone or something this
  character has history with. The character's reaction is grounded in that history.
- `player_drew_weapon` — different characters react differently. A guard escalates;
  a child flinches; a smuggler measures the player's grip.

Each non-greet/goodbye trigger should encode *this character's relationship with the
thing that triggered it*. If two characters' `player_drew_weapon` triggers read the same,
you've lost the interweaving.

## The interweaving smell test

Before declaring the blueprint done, read each character's block aloud and ask:
- Could I swap this character's `wants` and `epistemics` with another's and have the
  scenario still work? If yes, sharpen until no.
- Does at least one character know something the others don't?
- Is there at least one scene whose existence depends on something that happened in a
  prior scene?
- Are voices distinct along at least two of the axes above?

If any answer is "no" in a multi-character or multi-scene scenario, the blueprint is
not done yet.
