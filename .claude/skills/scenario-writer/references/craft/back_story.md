# Craft — `back_story.txt`

The world / setting / hard constraints, shared across every scene and every character in
this scenario. **It is written prose, not spoken text** — TTS rules from
`tts-safety.md` do not apply to its narrative; clean written English is the goal.

## What this file does

- Establishes place, time period, situation, the physical / social / technological rules.
- Names what the world **does not allow, does not know, or cannot do**. These constraints
  are gold — they keep the live LLM from inventing escape hatches when the player asks
  "can we just call the helicopter?"
- Is read by every character in every scene. Anything truly universal about the world
  belongs here; anything character-specific belongs in `character_back_story.txt`.

## What it does NOT do

- It does NOT describe the character. That's `character_back_story.txt`.
- It does NOT describe what's happening *right now* in the scene. That's
  `scene_description.txt`.
- It does NOT teach the character how to talk. That's the voice work inside
  `character_back_story.txt`.

## Anchor on the blueprint

The architect's blueprint has a "World rules" section with the hard constraints already
named. Lift them. Then *expand* each into a paragraph that gives the live LLM enough texture
to improvise inside the rule, not just the rule itself. A constraint stated without sensory
or social detail is easy to forget; embedded in a paragraph of texture, it sticks.

## What "enough" looks like

Aim for 150-400 words. Less and you've given a logline; more and you've started writing the
character's life instead of the world's. If the world is big (a kingdom, an era), pick the
*intersection of the world and this scenario* — what does the player actually touch? Write
that.

## Anti-patterns

- **Vague atmosphere.** "A dark and mysterious tower." vs. "A watchtower on a stretch of
  coast the village has called 'wreckers' beach' for three generations; the only road in
  washes out in any storm worse than a strong rain."
- **Story summary.** Don't tell the *plot* here — that's `scene_description.txt`. Write the
  *world* the plot happens inside.
- **Hidden character voice.** This file is the world, not the character. If your back_story
  sounds like the character narrating, you've put character work in the wrong file.
- **Soft constraints.** "There probably isn't any help available." vs. "There is no working
  radio in the watchtower, and no road off this stretch of coast until dawn." Hard.

## A good drafting pass

1. Re-read the blueprint's Premise and World rules sections.
2. Write three to six paragraphs of world prose. Open with the place, the time, and the
   situation. Anchor every paragraph in something physical the player or character can
   point at — a door, a horizon, a tool, a weather front.
3. Make every hard constraint named in the blueprint appear in the prose, ideally
   embedded in a sentence that has texture, not as a bullet list.
4. Read it back. Could the character in this scenario plausibly read this and feel it
   describes the world they live in? Could a *different* character do the same? It
   should be character-agnostic.
