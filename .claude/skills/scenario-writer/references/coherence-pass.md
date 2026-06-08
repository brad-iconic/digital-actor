# Coherence Pass

After you've drafted **all the files for one character** in one scene
(`character_back_story.txt`, `steer_back_instructions.txt`, every trigger `prompt.txt` and
`narrator.txt`, and `opening_speech.txt` if it exists), STOP and run this pass before moving
on. Then, if the scenario has multiple characters in this scene, run the cross-character
pass after every character's per-character pass is done.

This is not optional. The single most common failure in this domain is files that describe
slightly different people, who know slightly different things, and sound slightly different.
The reader (the live LLM) sees them all and averages — producing a character who is no one.

## Per-character pass

Open every file you just wrote for this character side by side and re-read them as one
document. For each check, write down (mentally) the specific line(s) you'd point at. If
you can't point at a line, the file isn't doing its job.

### Identity
- [ ] Is this the same person in every file? (history, age, role, relationships)
- [ ] Are their values consistent — what they would and wouldn't do, what they care about?
- [ ] Are their wants stated the same way in every file that touches them?

### Voice
- [ ] Pull every *spoken* line from these files (opening_speech if present; any example
      lines in character_back_story; every trigger prompt's instruction wording — read the
      *implied* voice the prompt asks for; narrator lines too).
- [ ] Do they sound like one mouth? Sentence length, punctuation signature, register,
      disfluency rate — all the dimensions the blueprint's voice brief named?
- [ ] If a trigger prompt asks the character to do something at a register or volume that
      contradicts what `character_back_story.txt` says, that's a coherence break. Fix one
      of them.
- [ ] Cross-check against the blueprint's voice brief for this character. If the prose has
      drifted from the brief, decide whether the brief was wrong (rare) or the prose is
      (usual) and fix the prose.

### Epistemics
- [ ] Does the character "know" the same things in every file?
- [ ] Does the character *not* know the same things in every file?
- [ ] Crucial: do any of the triggers reveal information the `character_back_story` says
      the character cannot perceive? (Example: a `night_falls` trigger that has the
      character describe the colour of the sky when the back_story says they're blind.)

### Tactic consistency
- [ ] Does the steer-back tactic in `steer_back_instructions.txt` flow from the same
      character the back_story describes? A deadpan character does not steer back with
      cheery deflection.
- [ ] Do triggers respond *in the same tactic register* as steer-back? A character who
      refuses to break the fourth wall in steer-back shouldn't be visibly winking in a
      trigger.

### TTS safety
- [ ] No em-dashes (—) or en-dashes (–) anywhere a spoken line lives.
- [ ] No unicode ellipsis `…`; use `...`.
- [ ] No `{{...}}` tokens outside trigger files.
- [ ] Numbers spoken aloud are spelled out.

If anything fails, fix it inline and re-run the failing section. When everything passes,
this character is ready. Move on to the next character (or to the cross-character pass).

## Cross-character pass (multi-character scenes only)

After every character in this scene has passed their per-character pass, open all of their
files side by side.

### Distinctness
- [ ] Read the spoken-text lines for character A and character B back to back. Could you
      tell them apart without the speaker tags? If not, sharpen — usually by tightening
      one character toward the axes their voice brief named (sentence-length,
      disfluency, punctuation signature).
- [ ] If two characters have the same trigger name (e.g. both have `player_drew_weapon`),
      do they react differently? They must.

### World consistency
- [ ] Do shared events appear consistently across files? If both characters' back_stories
      reference the same incident, do they describe the same physical facts (people may
      *interpret* them differently — but the facts shouldn't contradict)?
- [ ] Do the characters obey the world rules in `back_story.txt`? No one invents an escape
      hatch a hard constraint forbids.

### Asymmetric knowledge
- [ ] If the blueprint marked some knowledge as asymmetric (character A knows X, B doesn't),
      is that actually enforced in the files? Does A's back_story say they know X? Does B's
      say they don't? Does no trigger casually leak X from B?

If anything fails, fix it inline and re-run the failing section. When this pass clears,
the scene is ready for the pre-flight checklist.
