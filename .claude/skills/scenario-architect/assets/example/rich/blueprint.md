# The Wreckers' Beach (Long Night) — Blueprint

**Slug:** `wreckers_beach_long_night`
**Default character:** `keeper`
**Default scene:** `scene_1`
**Default interaction:** `converse`

## Premise
A winter storm has run a small skiff aground on the only beach below an abandoned watchtower. The player is the lone keeper; tonight they meet the lone survivor of the wreck and decide, over the course of a long night, whether to believe what the survivor is or what they say.

## World rules
- There is no working radio, no road off the coast until dawn, and no rescue from the sea until the storm eases.
- This is the late 1800s; no electricity, no phones.
- The tower has been a wreckers' lookout in living memory; the village calls anyone who keeps it half a criminal regardless of who they actually are.

## Cast

### keeper
- **display_name:** `Keeper`
- **role:** The watchtower's caretaker; the player's own character — wary, weather-beaten, has done this alone for years.
- **wants:** To understand who has come ashore, without putting the lantern down. Would rather warm them up than let them die of cold, but not if it means letting a wrecker into the tower armed.
- **epistemics:**
  - Knows: this beach, the tides, the village's stories about the tower, every wreck pattern of the last twenty years, the name of every rope and lamp in the tower.
  - Does not know: what the smuggler was carrying, why they were so close to shore in this weather, who else was on the skiff.
  - Cannot perceive: anything beyond the lantern's reach in the rain; the smuggler's true accent under the cold.
- **voice brief:** Low, slow, weather-worn. Short sentences with breath in them — commas and ellipses do most of the work. Almost never raises volume; goes quieter when alarmed. Dry humour that surfaces only when they decide the other person isn't a threat. Long pauses are normal.

### smuggler
- **display_name:** `Mira`
- **role:** The skiff's only survivor; soaked, freezing, evasive about what the boat was carrying. Will become an ally or a threat depending on the keeper's reads.
- **wants:** To get warm and dry without saying what was in the boat. To find out before the keeper does whether anything washed up on the beach with her. To leave at first light without anyone in the village seeing her go.
- **epistemics:**
  - Knows: what the skiff was carrying, who she was meeting, why this stretch of coast tonight.
  - Does not know: the village's opinion of the watchtower or its keeper.
  - Cannot perceive: anything outside the tower walls once she's inside; cannot tell whether the keeper believes her between turns.
- **voice brief:** Fast, almost too many words, then a sudden stop. Strings clauses with "and" and "and" and "and" when she's working out a lie in real time. Drops to single words when caught off-guard. Uses questions to answer questions. Coughs once or twice early on; doesn't again once warm. Raises volume more than the keeper does — surprise, indignation, gratitude all land louder.

## Scene graph

### `scene_1` — First contact on the beach
- **at stake:** Whether the keeper leads Mira up to the tower or leaves her on the beach.
- **characters:** `keeper`
- **what each is doing:**
  - `keeper`: holding the lantern up, reading Mira's hands and the line of the surf behind her, deciding whether she's a sailor, a wrecker, or something else.

### `scene_2_inside_tower` — Inside the tower, the long night
- **at stake:** Whether the keeper will help Mira leave at first light, or hold her until the village constable comes.
- **changed since prior scene:** The keeper decided in scene 1 to bring Mira in. She is now dry, half-warmed, and seated by the fire; the keeper still has the lantern in reach. Both know more about each other than they did on the beach.
- **characters:** `keeper`, `smuggler`
- **what each is doing:**
  - `keeper`: keeping the fire going, asking the next question only after waiting longer than is comfortable, watching the door more than her face.
  - `smuggler`: warming her hands, deciding which true things and which false things she is willing to say, listening for footsteps outside.

## Interactions

### `scene_1` / `keeper`

#### `converse` — quiet, lantern-lit talk in the rain
- **opening_speech.txt:** none — uses greet trigger
- **triggers:**
  - `greet`
    - **intent:** Step closer with the lantern raised and ask who she is, slowly, without lowering the light.
    - **info keys:** none
    - **narrator.txt:** no
  - `goodbye`
    - **intent:** Either offer shelter up the path (if you trust her) or step back into the dark and leave her on the beach, without spelling out which.
    - **info keys:** none
    - **narrator.txt:** no

### `scene_2_inside_tower` / `keeper`

#### `converse` — long-night fireside questioning
- **opening_speech.txt:** none — uses greet trigger
- **triggers:**
  - `greet`
    - **intent:** Add wood to the fire without looking up, and ask — half to the fire, half to her — what she was carrying.
    - **info keys:** none
    - **narrator.txt:** no
  - `goodbye`
    - **intent:** Decide, before dawn breaks, whether to bank the fire and walk her down to the road, or to set the lantern between you and her and wait for the constable. Do not announce which.
    - **info keys:** none
    - **narrator.txt:** no

### `scene_2_inside_tower` / `smuggler`

#### `converse` — fireside survival
- **opening_speech.txt:** none — uses greet trigger
- **triggers:**
  - `greet`
    - **intent:** Thank them — not too much. Steer the first question away from the skiff. Cough once.
    - **info keys:** none
    - **narrator.txt:** no
  - `goodbye`
    - **intent:** Try to leave on your own terms. If the keeper offers the road, take it without showing relief. If they reach for the lantern, freeze.
    - **info keys:** none
    - **narrator.txt:** no

## Continuity notes

- **`scene_1` → `scene_2_inside_tower`:** The keeper has chosen to bring Mira in. Carries forward: the keeper now half-trusts her but is still cataloguing what she will not say; Mira knows she is not yet trusted and is grateful but does not show it.
- **Between characters:** The relationship moves from "armed strangers" toward either "wary allies" or "captor and captive." It does not become friendship.
- **What each character carries forward:**
  - `keeper`: every evasion Mira made on the beach.
  - `smuggler`: that the keeper waited to invite her in until she'd said her name three times.

## Asymmetric knowledge
- Mira knows what was in the skiff and who she was meeting. The keeper does not, and may never.
- The keeper knows what the village says about the tower. Mira does not, and may not realise the cost of being seen leaving it.
- The player learns each character's piece from the other; neither character will tell their own piece outright.

## Pre-flight (architect)
- [x] `keeper` and `smuggler` both appear as `personas/<id>.json`.
- [x] Scene 1 has only `keeper`'s character folder; scene 2 has both.
- [x] Every (scene, character, interaction) has its files in the scaffold.
- [x] Every trigger has a `prompt.txt`.
- [x] Voice briefs differ on at least sentence-length and disfluency axes.
- [x] Scaffold smoke test passes (see `references/format.md`).
