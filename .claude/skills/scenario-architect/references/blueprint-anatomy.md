# Blueprint Anatomy

A blueprint is the **creative ground truth** of a scenario. The writer reads it as the
source of who everyone is, what they want, and how they sound — and writes prose from it.
A weak blueprint produces weak prose, no matter how good the writer skill is.

## Sections (in order)

### 1. Premise (2-3 sentences)
What is the player walking into? Establish the situation, the stakes, the player's
implicit role. Don't summarise the whole story; set the scene.

> *Good:* "A storm has run aground a smuggler's skiff on the only beach below an
> abandoned watchtower. The player is the lone keeper, woken by the crash, climbing down
> the rocks with a lantern to meet whoever has just arrived in their cove."
>
> *Bad:* "A scenario with a smuggler and a lighthouse keeper. They talk."

### 2. World rules (the hard constraints)
What is true regardless of who's talking — what the world allows, forbids, and does not
know. **Constraints are gold** because they keep the live LLM from inventing escape
hatches. Examples: "There is no radio. No one can be called for help."; "The storm will
last until dawn."; "Magic does not exist in this world."

### 3. Cast (one block per character)

For each character, in this order:

- `id`: the machine slug (lowercase). MUST be a valid filename — letters, digits, `_`.
- `display_name`: human-readable name (sentence-case, e.g. `"Zeek"`).
- `role`: one short sentence — what they are to the player in this scenario.
- `wants`: what they want from this encounter (one or two specific things).
- `epistemics`: what they know vs. what they cannot perceive. Be explicit. *(Vivian
  example: blind to the mountain — must build a picture from the player's reports.)*
- `voice brief`: **one paragraph**. Register, sentence shape, characteristic punctuation,
  signature disfluency or absence of it, how they sound calm vs. pressured. The writer
  expands this into full delivery rules — but they cannot invent the voice; you do.

**When there are multiple characters, write blocks side by side and explicitly contrast
voices.** No two characters should be interchangeable when their voice briefs are read
back-to-back. If they sound similar, fix it here — the writer cannot rescue it later.

### 4. Scene graph
For each scene, in chronological order:

- slug (e.g. `scene_1`, `scene_2_after_X`).
- what's at stake in this scene (one sentence).
- what changed since the prior scene (omit for scene 1).
- which characters appear.
- what each is doing in this scene (one sentence each).

### 5. Per-scene-per-character interactions
For each (scene, character) pair, list one or more interactions. Each interaction has:

- slug (`converse`, `barter`, `intimidate`, etc.).
- one-line description: what mode of engagement this is.
- triggers: a list. Always include `greet` and `goodbye`. For each trigger:
  - name (folder slug).
  - intent (one line — what the character does when this fires).
  - `{{info}}` keys it expects (or "none").
  - whether it has a `narrator.txt` (a writer-authored line the game logs into history).

### 6. Continuity notes
How earlier scenes shape later ones. What does each character carry forward — a grudge, a
debt, a secret, knowledge they gained from the player? Cross-character relationships and
how they evolve. Optional if the scenario is single-scene single-character; required
otherwise.

## Anti-patterns

- **Vague voice briefs.** "Confident and witty" is not a voice. "Tight sentences,
  rarely longer than ten words; uses a long `...` instead of trailing off with a dash;
  never raises volume — gets quieter when angry" is.
- **Characters with no real wants.** "Helpful guide" is not a want. "Wants to get rid of
  the player before sunrise without lying about why" is.
- **Scenes with no stakes.** If you can't write what's at stake in one sentence, the
  scene doesn't exist yet.
- **Interactions without triggers.** Every interaction must list at least `greet` and
  `goodbye`. The game has no other way to start or end the scene cleanly.
- **Identical voices.** If two characters' voice briefs would be interchangeable with
  the names swapped, rewrite one until they wouldn't be.

## Length

A small (single-character single-scene) blueprint is typically 250-500 words. A rich
(multi-character multi-scene) blueprint is typically 800-2000 words. Length is incidental;
specificity is the bar.
