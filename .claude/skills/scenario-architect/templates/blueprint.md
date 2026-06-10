# <Scenario display title> — Blueprint

**Slug:** `<lowercase_slug>`
**Default character:** `<character_id>`
**Default scene:** `<scene_slug>`
**Default interaction:** `<interaction_slug>`

## Premise
<2-3 sentences. What is the player walking into?>

## World rules
- <hard constraint>
- <hard constraint>
- <what this world does not know or does not allow>

## Cast

### <character_id>
- **display_name:** `<Display Name>`
- **role:** <one sentence — what this character is to the player>
- **wants:** <one or two specific things they want from this encounter>
- **epistemics:**
  - Knows: <…>
  - Does not know: <…>
  - Cannot perceive: <…>
- **voice brief:** <one paragraph: register, sentence shape, characteristic punctuation, signature disfluency or absence of it, how they sound calm vs. pressured>

*(Repeat the block above for each character. When there are multiple characters,
read the voice briefs back to back and confirm they are distinguishable on at least two
of the axes in `references/interweaving.md`. If not, sharpen.)*

## Scene graph

### `<scene_1_slug>` — <name>
- **at stake:** <one sentence>
- **characters:** `<character_id>`, `<character_id>`
- **what each is doing:**
  - `<character_id>`: <one sentence>
  - `<character_id>`: <one sentence>

### `<scene_2_slug>` — <name>
- **at stake:** <one sentence>
- **changed since prior scene:** <one or two facts>
- **characters:** `<character_id>`
- **what each is doing:**
  - `<character_id>`: <one sentence>

*(Add scenes as needed. Single-scene scenarios stop after scene 1.)*

## Interactions

### `<scene_slug>` / `<character_id>`

#### `<interaction_slug>` — <one-line description of this mode of engagement>
- **opening_speech.txt:** <"none — uses greet trigger" | "present — see below">
- **triggers:**
  - `greet`
    - **intent:** <one line>
    - **info keys:** <none | `{{key1}}`, `{{key2}}`>
    - **narrator.txt:** <yes / no>
  - `goodbye`
    - **intent:** <one line>
    - **info keys:** <…>
    - **narrator.txt:** <yes / no>
  - `<other_trigger_name>` *(optional)*
    - **intent:** <…>
    - **info keys:** <…>
    - **narrator.txt:** <yes / no>

*(Repeat the interaction block for every interaction this character offers in this scene.
Repeat the whole `### <scene_slug> / <character_id>` block for every (scene, character)
pair.)*

## Continuity notes
<Optional for single-scene single-character. Required otherwise.>

- **`<scene_1>` → `<scene_2>`:** <what carries forward — facts, relationships, mood>
- **Between characters:** <how relationships evolve across the scenario>
- **What each character carries forward:**
  - `<character_id>`: <…>

## Asymmetric knowledge (optional but recommended for multi-character)
- `<character_a>` knows <X>; `<character_b>` does not.
- The player can learn <Y> from `<character_a>` and use it with `<character_b>`.

## Pre-flight (architect)
- [ ] Every `<character_id>` listed in **Cast** appears as a `personas/<id>.json` file.
- [ ] Every (scene, character, interaction) declared above has its files in the scaffold.
- [ ] Every trigger declared above has a `prompt.txt` (and `narrator.txt` if marked yes).
- [ ] Voice briefs are distinct on at least two axes when multi-character.
- [ ] Scaffold smoke test from `references/format.md` passes.
