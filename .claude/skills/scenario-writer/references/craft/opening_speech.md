# Craft — `opening_speech.txt`

The character's **pre-authored opening line(s)**, sent straight to TTS without an LLM call.
**Optional** in the new game-driven format — most interactions use a `greet` trigger
instead (the game decides when to fire it). Only write this file if the blueprint
explicitly declares an `opening_speech.txt` for this interaction.

When you do write it, the format is strict because the dialogue parser reads it exactly.

## Format (strict)

Lines begin with `[<display_name>]: ` (the persona's exact `display_name`, square brackets,
colon, space). Emotion/intensity tags appear inline as `[emotion, intensity]` and drive
vocal delivery.

```
[Keeper]: [neutral, low] Stop where you are. [neutral, low] Hands so I can see them.
```

You may script a short exchange that includes the player's silence:

```
[Keeper]: [neutral, low] Stop where you are. [neutral, low] Hands so I can see them.
[Player]: ...
[Keeper]: [surprise, low] A name. [neutral, low] Good. A name's a place to start.
```

## Allowed tag values

- Emotion (lowercase, exactly one): `anger`, `fear`, `joy`, `sadness`, `disgust`,
  `surprise`, `neutral`.
- Intensity (lowercase, exactly one): `low`, `medium`, `high`.

## What this file does

- Establishes voice, situation, and a hook that invites the player to respond — in a way
  that lands without LLM improvisation, because there is none.
- Sets the **first impression**. Tone, register, energy.

## What it does NOT do

- It does NOT replace `character_back_story.txt`'s voice rules. The live LLM uses those
  for everything else; the opening just demonstrates them.
- It is NOT a full scene; it's an opener. One to three character turns total is the norm.

## TTS rules

All `tts-safety.md` rules apply. The big ones:
- No em-dashes, no en-dashes. Use a period or a comma.
- No unicode ellipsis; use `...`.
- Short sentences; fragments are good.
- Numbers spoken as words.

## When `opening_speech.txt` is the right choice vs. a `greet` trigger

Use `opening_speech.txt` when:
- The opener is **fixed** and known at scenario-author time.
- The game does not need to delay the opener until a runtime event.
- You want to script a short two-or-three-line exchange (including `[Player]: ...`) for
  rhythm.

Use a `greet` trigger when:
- The game decides when the character enters / starts speaking.
- The opener depends on `{{info}}` values the game has at runtime (e.g.
  `{{visitor_name}}`).
- You want the live LLM to vary the opener (richer, more replayable).

Most scenarios use `greet`. Use `opening_speech.txt` deliberately.

## Anti-patterns

- **Dashes.** The single most common bug. Grep before declaring done.
- **Display-name case mismatch.** `[keeper]:` will not parse correctly if the persona's
  `display_name` is `Keeper`. Use the exact `display_name`.
- **Invalid emotion or intensity.** Anything outside the allowed sets won't parse.
- **Over-long openers.** This is a hook, not a monologue.

## Pre-flight

- [ ] Every spoken line starts with `[<display_name>]: ` using the persona's exact
      `display_name`.
- [ ] Every `[emotion, intensity]` tag uses allowed values only.
- [ ] No em-dashes, no en-dashes, no unicode ellipsis.
- [ ] If you scripted a `[Player]: ...` beat, it parses as a separate line.
