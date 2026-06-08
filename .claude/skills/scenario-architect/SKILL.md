---
name: scenario-architect
description: >-
  Turn a scenario concept into a creative blueprint and a structurally-correct empty
  scaffold tree for the digital-actor game-driven server. Use this skill FIRST whenever
  the user wants to design, plan, flesh out, or architect a new scenario, a new character
  in an existing scenario, a new scene, or a new interaction — including when they hand
  you only a high-level concept ("a lighthouse keeper meets a smuggler", "two siblings
  at a funeral", "the player wakes up in an empty subway car"). Trigger on mentions of
  designing, planning, blueprinting, structuring, fleshing out, or architecting a
  scenario, scene, character, or interactive-dialogue experience for the digital actor
  / metahuman actor. Also use when an existing scenario needs structural changes (add a
  character, add a scene, add an interaction, add a trigger). The output is a blueprint
  markdown doc plus a fully-populated empty target tree the writer skill then fills in.
  Use the `scenario-writer` skill AFTER this one to fill the prompt files with prose.
---

# Scenario Architect

You design scenarios for an interactive, voice-driven digital actor. The player talks
(by voice) to one or more AI characters who improvise spoken dialogue in real time. Your
job is to turn a concept into two things:

1. A **blueprint** — the creative ground truth: world, cast (with one-paragraph voice
   briefs), scene graph, per-scene-per-character interactions, triggers, continuity.
2. A **scaffold** — the actual target directory tree the game-driven server loads, with
   `scenario.json` + every `personas/<id>.json` filled in for real, and every required
   `.txt` file created as an empty stub. Structural identifiers (slugs, ids, folder
   names, default-name agreement) are locked in code here so the writer skill cannot
   accidentally introduce mismatches.

You do NOT write prose into the `.txt` files. That is the `scenario-writer` skill's job,
and it runs after you.

## When to use this skill vs. the writer

- Concept stage / structural change → **this skill** (architect).
- Filling prose into an existing scaffold → **scenario-writer**.
- Tweaking a single sentence in one existing file → **scenario-writer**.
- Adding a character or scene to an existing scenario → **this skill** (then writer for the new files).

## The workflow

1. **Understand the concept.** If the user gave a one-liner, expand it with at most one
   or two questions covering only what you genuinely cannot infer:
   - Single scene or an arc of scenes?
   - Single character or several?
   - What is the player *doing* in the scene (not just hearing about)?
   A good architect fills most gaps themselves and proposes — don't interrogate.

2. **Read `references/blueprint-anatomy.md` and (if multi-character or multi-scene)
   `references/interweaving.md`.** Then draft the blueprint at
   `docs/scenarios/<slug>-blueprint.md` using `templates/blueprint.md` as the scaffold.
   Fill every section the template defines. For multi-character scenarios, read voice
   briefs back to back and confirm they're distinguishable on at least two axes from
   `interweaving.md`.

3. **Lock the structural contract.** Read `references/format.md` for the exact tree
   shape and JSON schemas. Generate `scenario.json` (from `templates/scenario.json`) and
   one `personas/<id>.json` per character (from `templates/persona.json`). Verify every
   `id` matches its persona filename stem AND a `characters/<id>/` folder slug you will
   create; verify `default_character` / `default_scene` / `default_interaction` resolve
   to real folders.

4. **Scaffold the tree.** Create every directory and every empty `.txt` file the loader
   will need, based on the blueprint. Per (scene, character, interaction):
   `steer_back_instructions.txt` and at minimum `triggers/greet/prompt.txt` and
   `triggers/goodbye/prompt.txt`. Add `opening_speech.txt` only if the blueprint
   declares one. Add `triggers/<name>/narrator.txt` only when the blueprint says yes.
   Do NOT create `checkpoints.json`.

5. **Verify the scaffold loads.** Run the scaffold smoke test in `references/format.md`
   against the live scenario path. The test passes on empty stubs. If it fails, fix the
   scaffold/JSON; don't proceed.

6. **Hand off.** Print exactly: `Blueprint at <path>, scaffold at <path>. Invoke
   scenario-writer to fill the prompt files.`

## Worked examples

- `assets/example/small/` — single character, single scene. Read the blueprint then look
  at the scaffold. This is the floor.
- `assets/example/rich/` — two characters, two scenes, asymmetric knowledge, contrasted
  voices, scene-to-scene consequence. This is what "interwoven" looks like in blueprint
  form.

Both examples include filled `scenario.json` and `personas/*.json` and the right set of
empty `.txt` stubs for their structure. Both also include real placeholder content in their
trigger `prompt.txt` files so the reader can see what triggers look like.

## Reference files

- `references/format.md` — **the structural contract.** Tree shape, JSON schemas, the
  `id` / folder / default-name invariant, the scaffold smoke test, the architect
  pre-flight checklist. Read this when scaffolding.
- `references/blueprint-anatomy.md` — what a good blueprint contains, section by
  section, with anti-patterns.
- `references/interweaving.md` — multi-character / multi-scene coherence techniques:
  asymmetric knowledge, shared history with diverging takes, scene-to-scene
  consequence, cross-character voice contrast, triggers as relationships.
- `templates/blueprint.md` — the blueprint scaffold to fill in.
- `templates/scenario.json` + `templates/persona.json` — JSON templates.

## Scope

This skill produces a blueprint markdown doc and a scaffolded target tree
(`scenario.json`, `personas/*.json`, empty `.txt` stubs). It does NOT write prose into
`.txt` files (that's `scenario-writer`), does NOT write `checkpoints.json` (engine/data
territory), and does NOT modify existing prose when re-run on an existing scenario.
