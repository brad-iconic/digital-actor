# Format — the structural contract

The game-driven server loads scenarios by walking the on-disk tree under
`.langfuse_prompts/scenarios/<scenario_name>/`. This file documents the structure the
**architect** must produce. Per-file content rules (what each `.txt` is *for*, the
`[Name]:` and `[emotion, intensity]` conventions, TTS-safety) live in the
`scenario-writer` skill's `references/format.md`. Architect owns *structure*; writer owns
*content*.

Source of truth in code: `metahuman_actor/game_driven/scenario.py` and
`metahuman_actor/game_driven/scene_data.py`.

## Required tree

```
.langfuse_prompts/scenarios/<scenario_name>/
├── scenario.json                                    # required
├── back_story.txt                                   # required (scenario-wide world lore)
├── personas/
│   └── <character>.json                             # one per character; required
└── <scene>/                                         # one or more scene folders
    ├── scene_description.txt                        # required (per scene)
    └── characters/
        └── <character>/                             # one folder per character in this scene
            ├── character_back_story.txt             # required
            └── <interaction>/                       # one or more interactions
                ├── steer_back_instructions.txt      # required
                ├── opening_speech.txt               # OPTIONAL
                ├── checkpoints.json                 # OPTIONAL (engine/data; not the architect's job)
                └── triggers/                        # OPTIONAL folder; if present, each subfolder is a trigger
                    └── <trigger_name>/
                        ├── prompt.txt               # required if the trigger folder exists
                        └── narrator.txt             # OPTIONAL
```

`<scenario_name>` is a short lowercase slug (e.g. `zeek_gd`, `lighthouse`, `negotiation`).
`<character>`, `<scene>`, `<interaction>`, `<trigger_name>` are also lowercase slugs.

## `scenario.json` — required at the scenario root

```json
{"default_character": "zeek", "default_scene": "scene_1", "default_interaction": "converse"}
```

All three values MUST exist in the tree:

- `default_character` must equal a `personas/<character>.json` filename stem AND a
  `characters/<character>/` folder name under the scene.
- `default_scene` must equal a `<scene>` folder name at the scenario root.
- `default_interaction` must equal an `<interaction>` folder name under
  `<default_scene>/characters/<default_character>/`.

Loader will raise on a missing `scenario.json` (`GameDrivenScenarioNotFoundError`) or a
missing key (`KeyError`).

## `personas/<character>.json` — one per character

```json
{
  "id": "zeek",
  "display_name": "Zeek",
  "voice": {
    "provider": "omnivoice",
    "voice_id": "default",
    "model_id": "IconicAI/omnivoice_johnny_v1_step300"
  }
}
```

**Critical invariant** (caused a real bug — keep this exact):
- `id` is the **machine key**. It is case-sensitive and used everywhere the game routes by
  `npc`. It MUST equal the `<character>` folder name under each scene AND the persona
  filename stem AND `default_character` (when this is the default).
- `display_name` is the **spoken/label name** (e.g. `"Zeek"`) shown to the player.
- Use lowercase slug for `id` (`"zeek"`) and human-readable for `display_name` (`"Zeek"`).
- Do NOT make them differ only by case in a way that confuses routing.

If the user has no voice preference, default to the block shown above (`omnivoice` /
`default` / `IconicAI/omnivoice_johnny_v1_step300`); the user can swap it later.

## Scene, character, interaction, trigger slugs

- **Scene** is a *narrative stage* of the whole scenario (scenario-wide; advancing the scene
  affects every character). Convention: `scene_1`, `scene_2_after_X`. Any slug is allowed
  as long as `scenario.json.default_scene` points at the first one.
- **Character** is an NPC. v1 is single-character per scenario, but the layout is
  multi-character-ready (one folder per character under `<scene>/characters/`).
- **Interaction** is *how the player is engaging this character right now* — `converse`,
  `barter`, `intimidate`, etc. Each is a self-contained folder.
- **Trigger** is a named event the game can fire. Folder name MUST equal the event name the
  game sends. `greet` and `goodbye` are the conventional opening/closing beats; coordinate
  other names with the game/Unreal team.

## Files the architect writes vs. stubs

The architect:
- Writes `scenario.json` and every `personas/<id>.json` with full real values.
- Creates every `.txt` file the writer will fill, as **empty stub files**. Empty stubs are
  fine — `get_prompt(...).compile()` on an empty file returns `""`, so the loader will
  accept the scaffold (the scenario_loads smoke test from §"Scaffold smoke test" passes on
  an empty-stub scaffold).
- Does NOT write `checkpoints.json` (engine/data territory; out of scope).
- Does NOT create `opening_speech.txt` unless the blueprint explicitly declares one
  (it's optional, and `greet` triggers are usually the better entry beat).

## Scaffold smoke test

After scaffolding, the architect MUST run this and confirm output before declaring done:

```bash
uv run python -c "
from langfuse_utils import langfuse_session
from metahuman_actor.game_driven.scenario import GameDrivenScenario, list_game_driven_scenarios
from metahuman_actor.game_driven.scene_data import GameDrivenSceneData
with langfuse_session(local=True):
    print('listed:', '<slug>' in list_game_driven_scenarios())
    s = GameDrivenScenario.load('<slug>')
    d = GameDrivenSceneData.load(s, scene=s.default_scene, character=s.default_character, interaction=s.default_interaction)
    print('triggers:', sorted(d.triggers))
"
```

Expected: `listed: True` and `triggers:` lists every authored trigger folder name (sorted).
Required `.txt` content may be empty at this stage; the smoke test passes regardless.

## Architect pre-flight checklist

- [ ] `scenario.json` exists at the scenario root with all three keys.
- [ ] `personas/<id>.json` exists for every character listed in the blueprint.
- [ ] Every persona's `id` equals its filename stem AND a `characters/<id>/` folder name in
      every scene that character appears in.
- [ ] `default_character`, `default_scene`, `default_interaction` all resolve to real
      folders/files.
- [ ] `back_story.txt` exists at the scenario root (may be empty).
- [ ] For every scene: `scene_description.txt` exists.
- [ ] For every (scene, character): `character_back_story.txt` exists.
- [ ] For every (scene, character, interaction): `steer_back_instructions.txt` exists.
- [ ] For every declared trigger: `<interaction>/triggers/<name>/prompt.txt` exists; if the
      blueprint says it has a narrator, `narrator.txt` exists too.
- [ ] Smoke test above prints `listed: True` and the expected trigger list.
