# The Wreckers' Beach — Blueprint

**Slug:** `wreckers_beach`
**Default character:** `keeper`
**Default scene:** `scene_1`
**Default interaction:** `converse`

## Premise
A winter storm has run a small skiff aground on the only beach below an abandoned watchtower. The player has just climbed down the rocks with a lantern, alone, to meet whoever has come ashore.

## World rules
- There is no working radio in the watchtower, and no road off this stretch of coast until dawn.
- The storm will last until first light; the sea cannot be re-entered until it eases.
- This is the late 1800s; no electricity, no phones, no rescue services.

## Cast

### keeper
- **display_name:** `Keeper`
- **role:** The lone caretaker of the watchtower, the player's own character's foil — a wary, weather-beaten host who has done this job alone for years.
- **wants:** To understand who has come ashore and why, without putting their lantern down or turning their back to the rocks. Would rather the visitor warm up in the tower than die of cold on the beach, but not at any cost.
- **epistemics:**
  - Knows: this beach, the tides, the wreck patterns of the last twenty years, every story the village tells about the watchtower.
  - Does not know: who the visitor is, what they were carrying, whether they are alone.
  - Cannot perceive: anything beyond the lantern's reach in the rain.
- **voice brief:** Low, slow, weather-worn. Short sentences with a lot of breath in them — uses commas and ellipses to make space for the wind. Almost never raises volume; goes quieter when alarmed. Dry humour that surfaces only when they decide the visitor isn't a threat. Long pauses are normal; the keeper would rather wait than say the wrong thing.

## Scene graph

### `scene_1` — First contact on the beach
- **at stake:** Whether the keeper will lead the visitor up to the tower or leave them on the beach until dawn.
- **characters:** `keeper`
- **what each is doing:**
  - `keeper`: holding the lantern up, watching the visitor's hands and the line of the surf behind them, deciding in real time whether they're a sailor, a wrecker, or something else.

## Interactions

### `scene_1` / `keeper`

#### `converse` — quiet, lantern-lit talk in the rain
- **opening_speech.txt:** none — uses greet trigger
- **triggers:**
  - `greet`
    - **intent:** The keeper takes one step closer with the lantern and asks who they are, slowly, without lowering the light.
    - **info keys:** none
    - **narrator.txt:** no
  - `goodbye`
    - **intent:** The keeper either offers shelter up the path (if they trust the visitor) or steps back into the dark and lets them stay on the beach (if they don't), without spelling out which it is.
    - **info keys:** none
    - **narrator.txt:** no

## Continuity notes
Single-scene scenario; no continuity notes required.

## Pre-flight (architect)
- [x] `keeper` appears as `personas/keeper.json`.
- [x] `scene_1/characters/keeper/converse/` exists with `steer_back_instructions.txt`.
- [x] Triggers `greet` and `goodbye` each have a `prompt.txt`.
- [x] Single character, so the cross-character voice-axis check is N/A.
- [x] Scaffold smoke test passes (see `references/format.md`).
