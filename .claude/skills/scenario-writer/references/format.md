# Format — the content contract

This file documents what each `.txt` file in the scaffold is *for* and the format conventions
the engine expects inside spoken-line files. It does NOT document the on-disk tree, JSON
schemas, or scaffolding — those are the architect's concerns. For structural questions, see
`.claude/skills/scenario-architect/references/format.md`.

The writer fills files that the architect has already created. If a file you want to write
doesn't already exist as an empty stub in the scaffold, **stop** — that's an architecture
change. Tell the user to revise the blueprint and re-run `scenario-architect`.

## The files you fill

| File | Purpose |
|---|---|
| `back_story.txt` | The world / setting / hard constraints, shared across all scenes and characters. |
| `<scene>/scene_description.txt` | What's happening in this scene; what's at stake for every character in it. Scene-wide. |
| `<scene>/characters/<char>/character_back_story.txt` | Who this character is in this scene: history, voice (expanded from the blueprint brief), epistemics, wants, delivery rules. The deepest file. |
| `<scene>/characters/<char>/<interaction>/steer_back_instructions.txt` | How this character handles an off-topic / off-character player, *in character*. |
| `<scene>/characters/<char>/<interaction>/opening_speech.txt` | OPTIONAL. Pre-authored opening line(s) spoken without an LLM call. Most scenarios use a `greet` trigger instead — author this only when the blueprint declared it. |
| `<scene>/characters/<char>/<interaction>/triggers/<name>/prompt.txt` | The instruction the live LLM uses to produce the reactive line when this trigger fires. |
| `<scene>/characters/<char>/<interaction>/triggers/<name>/narrator.txt` | OPTIONAL. A writer-authored line dropped into conversation history (NOT model-generated) recording that the event happened. |

You do NOT write: `scenario.json`, any `personas/<id>.json`, or `checkpoints.json`. The
architect owns the first two; the third is out of scope.

## The two hard format conventions

### 1. `[Name]:` speaker tag and `[emotion, intensity]` tags in `opening_speech.txt`

`opening_speech.txt` is sent straight to TTS without an LLM call, so its formatting is
parsed strictly. The dialogue parser reads two kinds of bracket tokens:

- **Speaker tag** at the start of a line: `[Name]: ` — the character's `display_name`
  followed by colon-space. The engine strips this before speaking. Use the persona's
  `display_name` exactly (e.g. `[Keeper]:`, not `[keeper]:`).
- **Emotion/intensity tag**: `[emotion, intensity]` — drives vocal delivery; stripped from
  the spoken text but parsed into expression metadata.

Format:
```
[Keeper]: [neutral, low] Stop where you are. [neutral, medium] Lift your hands so I can see them.
```

You can script a short exchange with the player's silence:
```
[Keeper]: [neutral, low] Stop where you are.
[Player]: ...
[Keeper]: [surprise, low] A name. Good. A name's a place to start.
```

**Allowed emotions** (exactly one per tag, lowercase): `anger`, `fear`, `joy`, `sadness`,
`disgust`, `surprise`, `neutral`.
**Allowed intensities** (exactly one, lowercase): `low`, `medium`, `high`.

The tag regex matches `[word]` or `[word, word, ...]` made of letters and commas only.

### 2. `{{var}}` substitution in trigger files

The ONLY files where you may use `{{...}}` tokens are trigger `prompt.txt` and `narrator.txt`.
The game's `info` payload for that event fills the variables. Use `{{double_curly}}` tokens
with no internal spaces, e.g. `The player has drawn {{weapon}}. React in character.`

- The game team decides which `info` keys each trigger receives — the blueprint should
  declare them per trigger.
- Do NOT use `{{...}}` in any other file. The loader will not substitute it and the literal
  tokens will appear in the prompt.

## Runtime context the game injects (you do not author)

A `world_state` block is injected by the game at runtime as `key: value` lines. Time of day,
player reputation, ambient temperature — anything that changes during play — is the game's
job, not yours. Write stable lore in `back_story.txt` and `character_back_story.txt`; the
game supplies the churn.

## Spoken vs. written contexts

- **Spoken** (TTS rules from `tts-safety.md` apply): `opening_speech.txt`, the *output* of
  any trigger `prompt.txt`, any *spoken-line example* you include inside other files, and
  the live LLM's generated turns.
- **Written** (clean written English; no TTS rules): the prose of `back_story.txt`,
  `scene_description.txt`, `steer_back_instructions.txt`, and the *non-example* prose of
  `character_back_story.txt`.

## Where the architect's voice brief becomes delivery rules

The writer **must** fold TTS-safety rules, `[emotion, intensity]` tag discipline,
sentence-length targets, and punctuation usage into `character_back_story.txt`, expanding
the architect's one-paragraph voice brief into something the live LLM can follow on every
generated line. See `references/craft/character_back_story.md` for how to do this.

## Trigger conventions

- `greet` and `goodbye` are the conventional opening/closing triggers and should be present
  on every interaction.
- Other trigger names are coordinated with the game/Unreal team and named after the event
  (e.g. `player_drew_weapon`, `player_offered_gold`, `night_falls`).
- A `narrator.txt` is a third-person event line (e.g. "The player draws their {{weapon}}.")
  the game logs into history. It is NOT spoken by the character.

## Pre-flight before declaring done

See `references/pre-flight-checklist.md`.
