# The Drunken Skull — Social Puzzle Design

**Date:** 2026-06-04
**Scenario slug:** `pirate_tavern`
**Type:** First-person single-player puzzle scene; one room, four live AI characters.
**Status:** Approved design (brainstorm). Feeds the `scenario-architect` rework, then `scenario-writer`.

## 1. Player-facing goal

Open the **captain's locked box** sitting on the corner table. It has a **3-digit
combination lock**. To open it the player needs **all three digits AND the correct order**.

Inside is a **map** — the dead captain's secret final destination. Opening the box is the
win condition and the gateway to the next scene of the larger game.

The goal is legible to a zero-knowledge player the moment they see the box: *a locked box,
a number lock, get the numbers.* No world lore is required to understand what to do.

## 2. Situation (the room)

The Drunken Skull, a smugglers'-island pirate tavern. **Tonight the players' old captain
died** in the back. His crew is still here, and his locked box is on the corner table —
nobody can open it alone, because the captain split the combination among them deliberately:
each was given **one digit "in case,"** and the **barkeep was given the order**, so that no
single crew member could ever claim the voyage without the others.

The crew no longer trust each other enough to stand at the box together (each privately
wonders how the captain really died — see §6). The player is a **stranger with no loyalty
to the captain** — and therefore the one neutral party all four will deal with. The player
is the courier the locked room needs.

## 3. Cast (four characters)

| id | display | role |
|----|---------|------|
| `grizzlewick` | Grizzlewick | Goblin barkeep. Former crew quartermaster-by-the-bar; kept the captain's secrets. **Tutorial + holds the ORDER.** |
| `grog` | Grog | Eldest orc brother. Loud, proud, sure the voyage is rightfully his. **Holds digit 1.** |
| `tog` | Tog | Younger orc brother. Schemer; terrified of being cut out of the voyage. **Holds digit 2.** |
| `bralt` | Bralt | The captain's enforcer/bosun — not a brother. Grieving, loyal to the dead captain, dangerous. **Holds digit 3.** |

> Naming note: the brothers keep their rhyming pair (Grog/Tog). The enforcer is
> deliberately *not* a rhyming name (`bralt`) to mark him as outside the family. Final
> display name is the architect's to confirm; `bralt` is the working id.

## 4. The puzzle: social triangulation

The player's only tool is **information** — what one character will tell them about, or
demand about, another. Each gate is a **specific, checkable fact** the character can
verify, not a vibe. No gate ever requires the player to *accuse* anyone (see §6).

### The dependency graph (forced, acyclic)

```
START
  │
  ├─ Grizzlewick (barkeep, first contact = TUTORIAL)
  │     • Explains: the box, the 3-digit lock, "each of the three orcs holds a digit,
  │       and I keep the order." Teaches that the currency here is information.
  │     • Gives FREE (tutorial trade): the captain's REAL NAME.
  │
  ├─ Grog ───────────────► DIGIT 1   (free — just let him posture as rightful heir)
  │
  ├─ Bralt (enforcer) ───► DIGIT 3   gate: speak the captain's REAL NAME (from Grizzlewick)
  │     • On being satisfied, Bralt also reveals his INTENT for the map.
  │
  ├─ Tog ────────────────► DIGIT 2   gate: tell him BRALT'S INTENT for the map (from Bralt)
  │
  └─ Grizzlewick (return) ► THE ORDER   gate: recite ALL THREE DIGITS **and** give him
        one fresh piece of gossip learned tonight (e.g. Bralt's intent).
        → player sets digits in order → box opens → MAP → scene complete.
```

### Why each gate forces triangulation

- **Grog (digit 1, free):** the easy win that teaches "digits come from orcs." A
  zero-knowledge player gets one number almost immediately and learns the table is crackable.
- **Bralt (digit 3):** won't deal with a stranger who didn't know the captain. The gate
  is the **captain's true name**, which only Grizzlewick knows — so the player must have
  visited the barkeep first. Satisfying Bralt also yields **his intent for the map**.
- **Tog (digit 2):** terrified Bralt will seize the voyage and cut the brothers out. He
  pays his digit only for **Bralt's stated intent** — so the player must crack Bralt first
  and carry his words across the room. This is the deepest interlock.
- **Grizzlewick (order, final gate):** trades the order only once the player can recite
  **all three digits** (proof the game is nearly up, so his gossip is worth selling) **and**
  hands him **one fresh rumor** from the night. Belt-and-suspenders final gate — nothing can
  be skipped.

### Two-stage Grizzlewick

Grizzlewick bookends the puzzle: **cheap intel early** (the name, plus the tutorial
explanation) and **the prize-piece last** (the order). This is consistent with his fixer
character — small talk is free-ish, the thing that actually unlocks the win costs the most.

## 5. Currency model (no-escalation rule)

Every payment is a **fact, flatter, or reassurance that moves sideways** — never an
accusation. The player carries "here is what the big man plans to do," "here is the
captain's true name," "here is where things stand" — intel and deference, never "I know
you killed him." This is a hard design constraint: see §6.

## 6. The unresolved-killing constraint (important)

The captain died tonight and **each character privately suspects the killing was not
natural.** This suspicion is **flavour and leverage only** — it makes the crew tense, makes
them talk to a neutral stranger rather than each other, and gives every line an undercurrent.

**The killer is never revealed and the mystery is never resolved by the puzzle.** No gate
requires the player to name or expose a killer. Rationale: if the player could *expose* the
killer, the natural consequence would be **escalation** — a fight, a flight, a death — and
the engine cannot reliably script four live AI characters through a dramatic blow-up. So we
keep the murder as a permanent low simmer that colours the scene and is never paid off
in-scene. The map (not justice) is the prize.

The writer must therefore give each character private suspicions in their back-story but
**must not** give any character a "reveal the killer / confess / escalate" trigger or tactic.

## 7. Structural mapping (for the architect)

- **One scene** (`scene_1`), **four characters**, each with a `converse` interaction.
- `scenario.json`: `default_character` = `grizzlewick` (first contact / tutorial),
  `default_scene` = `scene_1`, `default_interaction` = `converse`.
- Personas: `grizzlewick`, `grog`, `tog`, `bralt` (rename of the current 3-char scaffold:
  keep `grizzlewick`/`grog`/`tog`, **add** `bralt`).
- Each character's `converse` keeps the conventional `greet` and `goodbye` triggers.
- **The box is a world object, not a character.** It is described in `back_story.txt` /
  `scene_description.txt`. How the player physically "operates" the lock (UI/engine) is out
  of scope for the prompt files — the prompts only need the characters to know the box, the
  rule, and their own digit/order. (Whether the engine needs a non-`greet/goodbye` trigger
  such as `box_opened` is an open engine question for the game team; not required for the
  scaffold.)
- The interlocking facts (captain's real name, Bralt's intent, the three digits, the order)
  live as canon in `back_story.txt` and each character's `character_back_story.txt`; the
  gates live in each `steer_back_instructions.txt` as the tactic for what the character will
  and won't give, and for what.

## 8. Open items (resolve during architect/writer pass, not blocking)

- **Captain's name + true name:** the writer picks a nickname everyone uses and a real name
  only Grizzlewick knows. (e.g. "the Skull" vs. a real name.)
- **The three digit values and the order:** concrete numbers chosen at write time and
  recorded as canon so every character's prompt is consistent.
- **Bralt's display name** and final voice brief (must contrast with Grog and Tog — grief +
  menace, vs. Grog's bluster and Tog's quick evasion).
- **Engine question (game team):** does opening the box need a server trigger, or is it
  handled entirely UE-side once the player has the numbers? Does not block the scaffold.

## 9. Success criteria

- A zero-knowledge player understands the goal (open the box) on sight.
- The player cannot win without talking to all four characters and carrying at least two
  facts between them (the name → Bralt, Bralt's intent → Tog).
- No path lets the player collect all pieces from a single character or in a trivial order.
- No character ever needs to escalate, confess, or expose the killer for the player to win.
- The four voices are distinguishable on at least two axes each (existing briefs cover
  Grizzlewick/Grog/Tog; Bralt to be added).
