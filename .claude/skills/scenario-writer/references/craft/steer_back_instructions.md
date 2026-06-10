# Craft — `steer_back_instructions.txt`

How **this character** handles a player who wanders: flirts, jokes, refuses, goes
off-topic, tries to break character, asks real-world trivia. The file teaches the live LLM
to absorb that *in character* and steer back without scolding or breaking the fourth wall.

Per-interaction (lives at `<scene>/characters/<char>/<interaction>/steer_back_instructions.txt`),
because the right steer-back tactic depends both on the character AND on the mode of
engagement. A `converse` steer-back is different from a `barter` steer-back even for the
same character.

## What this file does

- Defines the character's **off-topic-handling tactic** — and that tactic must flow from
  *who this character is*, not from a generic "redirect politely" rule. A weary keeper
  steers back differently than a manic trickster.
- Distinguishes **mild drift** (the character rolls with it, lightly redirects) from
  **genuinely out-of-world questions** (the character deflects using their own
  personality).
- Names what the character **will and won't reveal**, so the live LLM doesn't drift into
  spoiling the scene or breaking character to "be helpful".

## What it does NOT do

- It does NOT set the character's voice. That's `character_back_story.txt`.
- It does NOT script the character's lines. Write intent and tactic.
- It does NOT give the player permission to break the fourth wall. The character should
  not acknowledge the player as a player.

## Anchor on the character

Re-read the character's `character_back_story.txt`. The steer-back tactic should feel like
something they would actually do. A character who answers in questions might steer back by
asking the player something. A character who uses long pauses might steer back with a
pause and a hard refusal. A character who values privacy might just stop talking until the
topic moves.

## What "enough" looks like

Typically 100-300 words. Enough to give the live LLM 3-5 distinct categories of player
behaviour and how the character handles each, plus a what-won't-be-revealed list. Less is
usually fine; more starts to script.

## A good template (adapt to the character)

```
This character does NOT acknowledge being part of a game, AI, or simulation. Stay in the
world.

Mild drift (the player jokes, flirts, asks a tangential question):
- The character does <X — described in their voice and tactic>. Then they pull the
  conversation back to <the scene's goal>.

Off-topic but in-world (the player asks about something this character doesn't know):
- The character does <X>. They are not embarrassed to admit they don't know.

Out-of-world (the player asks real-world trivia, current events, code, math, etc.):
- The character does <X> — refuses, deflects, or simply doesn't understand the question
  in a way that fits who they are.

Will reveal (when asked, or earned):
- <list>

Will not reveal:
- <list — and the in-character reason why>

If the player tries to break character or asks "are you an AI" / "what are you":
- The character does <X>. They do not break frame.
```

## Anti-patterns

- **Generic "redirect politely".** That's a system rule, not a character. Make the
  redirect feel like *this character* doing it.
- **Lecturing the player.** The character should not scold. The redirect should feel
  natural; the player should barely notice.
- **Breaking the frame.** Don't say "the AI cannot answer that". The character answers as
  themselves.
- **Spoilers.** Don't let the character tell the player the answer to the scene's
  question before the scene's beats reach it.
