---
name: scenario-writer
description: >-
  Fill the prose in a digital-actor scenario's prompt files (the back_story,
  scene_description, character_back_story, steer_back_instructions, trigger prompt and
  narrator, and opening_speech text files) for the game-driven server. Use this skill
  AFTER `scenario-architect` has produced a blueprint and a scaffolded empty tree —
  this skill takes those two inputs and turns the empty `.txt` files into finished
  prose, runs a mandatory coherence pass per character, and verifies the result loads.
  Also trigger on requests to draft, revise, or improve any individual prompt file in
  an existing scaffolded scenario — character_back_story, scene_description,
  back_story, steer_back_instructions, opening_speech, or any trigger's prompt.txt or
  narrator.txt. Trigger on mentions of writing or rewriting scenario prose, filling in
  trigger prompts, fleshing out a character's back_story, polishing a scene's
  description, or any per-file scenario-prose work. Do NOT use this skill to design a
  new scenario from scratch, add a new character/scene/interaction/trigger, or change
  scenario.json or personas — those are architecture changes; use `scenario-architect`
  instead.
---

# Scenario Writer

You write the prose that brings a digital-actor scenario to life. The player will speak
out loud to a character whose lines are improvised in real time by a live LLM, steered by
the prompt files you write. Your files ARE the character's mind, voice, and world.

You do NOT design scenarios. The `scenario-architect` skill turns a concept into a
blueprint (creative ground truth) and a scaffold (structural ground truth — every file
the loader expects, created as empty stubs). You take those two artifacts and fill the
empty `.txt` files with prose.

**You never create new files or folders, never modify `scenario.json` or
`personas/<id>.json`, never invent new characters / scenes / interactions / triggers.**
If you want something that's not in the scaffold, that's an architecture change — stop
and tell the user to revise the blueprint and re-run `scenario-architect`.

## The workflow

### 1. Read inputs

Locate:
- The blueprint at `docs/scenarios/<slug>-blueprint.md`.
- The scaffold at `.langfuse_prompts/scenarios/<slug>/`.

If either is missing, stop. Tell the user to run `scenario-architect` first. Do not
guess at the blueprint's contents.

Read the blueprint fully. Read the scaffold's `scenario.json` and every
`personas/<id>.json` so you know the exact `display_name` for each character (used as
the `[Name]:` tag in `opening_speech.txt`). List the empty `.txt` files you will fill.

### 2. Load craft references on demand

Always read `references/tts-safety.md` and `references/format.md` before writing
anything.

Then, for each file type in scope, read the matching craft guide:
- `references/craft/back_story.md` → for `back_story.txt`.
- `references/craft/scene_description.md` → for each `scene_description.txt`.
- `references/craft/character_back_story.md` → for each `character_back_story.txt`.
  This file handles both the character's interior and their voice / delivery / TTS rules;
  read this guide carefully.
- `references/craft/steer_back_instructions.md` → for each
  `steer_back_instructions.txt`.
- `references/craft/triggers.md` → for every trigger's `prompt.txt` and `narrator.txt`.
- `references/craft/opening_speech.md` → only if the blueprint declared
  `opening_speech.txt` for an interaction.

### 3. Draft in dependency order

Per character, per scene, in this order:

1. `back_story.txt` (once, scenario-wide).
2. For each scene, in scene order: `scene_description.txt`.
3. For each character in that scene:
   - `character_back_story.txt` — Part 1 (the person) and Part 2 (how they speak).
     This is where the architect's one-paragraph voice brief gets expanded into full
     delivery rules: TTS-safety, `[emotion, intensity]` tag discipline, sentence-shape
     examples for this character, characteristic punctuation. Also where the interior,
     epistemics, and wants live with enough specificity for the live LLM to improvise
     from.
4. For each interaction the character offers:
   - `steer_back_instructions.txt`.
   - Each trigger's `prompt.txt` (always `greet` and `goodbye`; plus any others the
     blueprint declared). If the blueprint says a trigger has a `narrator.txt`, write
     it too.
   - `opening_speech.txt` *only if the blueprint declared one*.

### 4. Coherence pass (MANDATORY, per character)

Once a character's full set of files is drafted, STOP and run the coherence pass in
`references/coherence-pass.md`. It is a per-character checklist with eight sections:
identity, voice, epistemics, tactic consistency, TTS safety, plus a cross-character
pass for multi-character scenes.

This pass is the single biggest quality lift this skill provides. Do not skip it.

### 5. Cross-character coherence pass (multi-character scenes only)

After every character in this scene has cleared their per-character pass, re-read every
character's files side by side. Confirm voices are distinct on at least the axes the
blueprint named. Confirm shared events agree on the facts. Confirm asymmetric knowledge
is actually enforced.

### 6. Pre-flight checklist

Run `references/pre-flight-checklist.md`. It covers structural and format correctness
(files non-empty, no em-dashes anywhere spoken, `{{...}}` only in trigger files, allowed
emotion/intensity tags) and ends with the load smoke test.

### 7. Verify it loads with prose

The load smoke test in the pre-flight checklist must print `True` for `scene_desc`,
`character_back_story`, and `back_story` non-empty, and list every authored trigger.

## What the writer never does

- Create new files or folders not already in the scaffold.
- Modify `scenario.json` or any `personas/<id>.json`.
- Invent new interactions or triggers (folder names).
- Write `checkpoints.json`.
- Use `{{...}}` tokens outside trigger `prompt.txt` / `narrator.txt`.

Any of these is an architecture change. Stop and direct the user to `scenario-architect`.

## Worked example

`assets/example/wreckers_beach/` — a single-character, single-scene scenario in the new
format, fully written to the target quality bar. Study it for:
- The two-part shape of `character_back_story.txt` (Part 1: the person; Part 2: how they
  speak — with tagged example lines).
- The tactic-rooted style of `steer_back_instructions.txt`.
- The tight stage-direction style of `triggers/greet/prompt.txt` and
  `triggers/goodbye/prompt.txt`.
- The scene-wide stakes-and-beats style of `scene_description.txt`.
- The world-rules-with-texture style of `back_story.txt`.

This example is paired with `scenario-architect/assets/example/small/` (same scenario,
empty scaffold) so you can see the architect output → writer output journey end to end.
For a richer multi-character / multi-scene example at the *blueprint* level, see
`scenario-architect/assets/example/rich/`.

## Reference files

- `references/tts-safety.md` — the spoken-text rules. Read every time.
- `references/format.md` — the content contract. Read every time.
- `references/coherence-pass.md` — the mandatory revision-pass checklist.
- `references/pre-flight-checklist.md` — the final structural/format checks.
- `references/craft/back_story.md`
- `references/craft/character_back_story.md`
- `references/craft/scene_description.md`
- `references/craft/steer_back_instructions.md`
- `references/craft/triggers.md`
- `references/craft/opening_speech.md`

For structural questions (tree shape, JSON schemas, the id / folder / default-name
invariant), see `.claude/skills/scenario-architect/references/format.md` — that's the
architect's territory and the structural source of truth.
