# Craft — triggers (`prompt.txt` and `narrator.txt`)

A trigger is a tiny prompt that produces an in-character line when the game fires a named
event. `greet` and `goodbye` are the conventional opening and closing beats; other
triggers react to events like `player_drew_weapon`, `player_offered_gold`, `night_falls`.

Each trigger folder contains:
- `prompt.txt` — **required**. The instruction the live LLM uses to generate the reactive
  line. Output IS spoken — TTS rules apply.
- `narrator.txt` — **optional**. A writer-authored line dropped into conversation history
  (NOT model-generated, NOT spoken by the character). Stage-direction style.

Both files support `{{var}}` substitution from the event's `info` payload. Use
`{{double_curly}}` tokens with no internal spaces.

## The right shape for `prompt.txt`

A trigger prompt is a **tight stage direction**, not a script. The model writes the line;
you write the instruction.

The instruction should:

1. Tell the model **what just happened** (the trigger's event, in plain prose, using
   `{{var}}` substitution if the game sends values).
2. Tell the model **what the character does in response** — physical action, emotional
   shift, intent. Not the literal words.
3. Anchor in the character. Refer to their values, their relationship to the thing that
   triggered the event, their typical register. The reader (the live LLM) already has
   `character_back_story.txt` loaded; lean on it.
4. Be short. Two to four sentences of instruction is plenty.

Example (good):
```
The player has just drawn a weapon. The keeper has seen wreckers do this before. Step back, keep the lantern between you and them, and say less than you'd like to. Do not raise the lantern as a threat, but do not lower it either.
```

Example (bad — scripts the line):
```
The player drew a weapon. The keeper says: "Now then. Let's all just calm down. Nobody needs to do anything rash."
```

Example (bad — generic):
```
The player drew a weapon. React appropriately.
```

## Voice — coherence with `character_back_story.txt`

Trigger output is spoken text by the same character whose `character_back_story.txt` you
wrote. The same voice rules apply: sentence length, punctuation signature, disfluency
rate, `[emotion, intensity]` tag discipline.

The cleanest way to enforce this: **write the prompt in language the character would
recognise**. If the character is a slow weather-worn keeper, the prompt that describes what
they do should itself be quiet and short. The model picks up on register.

## `{{var}}` substitution

The game sends an `info` dict at runtime; each `{{var}}` in your prompt is filled with the
value of that key. The blueprint should declare which keys each trigger expects.

Examples:
- `{{visitor_name}}` for a `greet` trigger that knows the player's chosen name.
- `{{weapon}}` for a `player_drew_weapon` trigger that knows what was drawn.
- `{{time}}` for a `night_falls` trigger that knows the in-game hour.

If a key is missing from `info` at runtime, the variable substitutes as an empty string —
write your prompt so it still parses if the variable is empty.

## `narrator.txt` — when to use it

`narrator.txt` is for events the **conversation history should remember** even though no
character speaks them. It's recorded into history; later turns see it as context.

Use when:
- The event is a *thing that happened* and the next character turn should reference it
  without the character explaining it. ("The player drew their {{weapon}}.")
- The event is something only the player did, with no NPC immediately reacting verbally,
  but later turns may bring it up.

Don't use when:
- The character's spoken response already covers it.
- The event has no later relevance.

Style: third person, present tense, short. **No `[emotion, intensity]` tags, no `[Name]:`
speaker tag** — this is narration, not dialogue.

Good:
```
The player draws their {{weapon}}.
```

Bad (this is a character line, not narration):
```
[Keeper]: [fear, low] Easy now.
```

## `greet` and `goodbye` — the conventions

- `greet` is the character's **opening beat** for this interaction. Most scenarios use
  `greet` instead of `opening_speech.txt` because the game decides when to fire it. Write
  it as the natural first thing the character does when this interaction starts.
- `goodbye` is the character's **closing beat**. Write it as the natural last thing the
  character does when the interaction ends. Often this is where a choice resolves
  (offers shelter / steps back; offers a deal / walks away).

Both are usually short prompts (one or two sentences of instruction) — the model fills the
rest from `character_back_story.txt`.

## Reactive triggers — the interweaving opportunity

Non-greet/goodbye triggers are the place where the world reaches the character. Per the
`scenario-architect/references/interweaving.md` "Triggers as relationships" section:

- `<other_character>_arrived` — different per character; reaction is the relationship.
- `player_mentioned_<topic>` — different per character; reaction is the history.
- `player_drew_weapon` — different per character; one steps back, one steps forward.

If two characters have the same reactive trigger name and the prompts produce reads that
sound the same, you've lost the interweaving. Fix one.

## Pre-flight (per trigger)

- [ ] `prompt.txt` is non-empty and reads as a tight stage direction (not a script).
- [ ] If `narrator.txt` exists, it's third-person present-tense, no speaker tag, no
      emotion tag.
- [ ] All `{{var}}` keys match what the blueprint declared for this trigger.
- [ ] The character's voice from `character_back_story.txt` is recognisable in the
      prompt's register.
- [ ] No em-dashes, no en-dashes, no unicode ellipsis.
