# Pre-flight Checklist

Run this last, after every character's coherence pass has cleared. It checks structural and
format correctness only — coherence and craft are already covered.

## Coherence (precondition)

- [ ] Per-character coherence pass has been run for **every** character: identity, voice,
      epistemics, tactic consistency, TTS safety. (See `coherence-pass.md`.)
- [ ] Cross-character coherence pass has been run if the scene has multiple characters.

If either is no, stop and run `coherence-pass.md` before continuing this checklist.

## Files

- [ ] Every empty stub `.txt` the architect created is now non-empty (except `narrator.txt`
      files for triggers that don't have one — those shouldn't exist at all).
- [ ] No new files or folders were created that weren't already in the scaffold. (If you
      need one, that's an architecture change — stop and revise the blueprint.)
- [ ] `scenario.json` and `personas/<id>.json` are unchanged from what the architect wrote.

## Spoken-line files (`opening_speech.txt`, trigger `prompt.txt`, trigger `narrator.txt`)

- [ ] Grep for em-dashes (`—`) and en-dashes (`–`) — none allowed.
- [ ] Grep for unicode ellipsis `…` — none allowed; use `...`.
- [ ] `opening_speech.txt` (if present) starts speaker lines with `[<display_name>]: ` using
      the persona's exact `display_name`.
- [ ] All emotion tags in `opening_speech.txt` use only `anger`, `fear`, `joy`, `sadness`,
      `disgust`, `surprise`, `neutral`.
- [ ] All intensity tags use only `low`, `medium`, `high`.

## Variable tokens

- [ ] `{{...}}` tokens appear ONLY in trigger `prompt.txt` and `narrator.txt`. Grep
      everywhere else for them — none allowed.
- [ ] Trigger `{{var}}` tokens use only the keys declared in the blueprint's trigger
      `info keys` line.

## Load smoke test

Run:
```bash
uv run python -c "
from langfuse_utils import langfuse_session
from metahuman_actor.game_driven.scenario import GameDrivenScenario, list_game_driven_scenarios
from metahuman_actor.game_driven.scene_data import GameDrivenSceneData
with langfuse_session(local=True):
    print('listed:', '<slug>' in list_game_driven_scenarios())
    s = GameDrivenScenario.load('<slug>')
    d = GameDrivenSceneData.load(s, scene=s.default_scene, character=s.default_character, interaction=s.default_interaction)
    print('scene_desc non-empty:', bool(d.scene_description.strip()))
    print('character_back_story non-empty:', bool(d.character_back_story.strip()))
    print('triggers:', sorted(d.triggers))
"
```

Expected:
- `listed: True`
- `scene_desc non-empty: True`
- `character_back_story non-empty: True`
- `triggers:` lists every authored trigger (sorted).

If any line prints `False` or the script errors, fix the underlying file and re-run.

## Final read-through

Read every file you wrote for this scenario as one document. Is this one coherent world
with one (or several distinct) coherent character(s)? If something feels off, fix it.
