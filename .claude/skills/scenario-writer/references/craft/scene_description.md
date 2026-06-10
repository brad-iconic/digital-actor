# Craft — `scene_description.txt`

What is happening in this scene, and — above all — **what every character in this scene is
trying to achieve**. Scene-wide; read by every character that appears in this scene.

## What this file does

- Establishes the physical situation right now (place inside the world, time, what just
  happened to bring everyone here).
- Names every character's **goal in this scene** and the rough beats their pursuit of it
  follows: this, then this, then this.
- Names the **contingencies** — how each character reacts to likely player moves: refusal,
  rushing, freezing, going off-topic. Write the *intent*, not a rigid script; the live LLM
  improvises the words.
- Names any Narrator / game-state signals the characters should pay attention to so live
  dialogue stays in sync with what the game has done.

## What it does NOT do

- It does NOT describe the world's hard constraints. Those are in `back_story.txt`.
- It does NOT describe character interior. That's `character_back_story.txt`.
- It does NOT define the character's speech style. That's `character_back_story.txt` Part 2.
- It does NOT handle off-topic / off-character players. That's
  `steer_back_instructions.txt`.

## Anchor on the blueprint

The architect's scene-graph entry for this scene names: what's at stake, what changed since
the prior scene (if any), which characters appear, and what each is doing in one sentence.
Take that as your spine. Expand each "what each is doing" sentence into a paragraph that
gives the live LLM enough to improvise: their goal, the beats they expect, the
contingencies.

## Style

Stage-direction prose. Third-person and instructional ("The character is doing X. If the
player does Y, the character should..."). Not narrative third person, not the character's
own voice.

## What "enough" looks like

Typically 200-500 words for a single-character scene, longer for multi-character. The bar
is the same as `back_story.txt`: specific over vague, contingencies over scripts, every
character's *goal* and *what would change their behaviour* explicitly named.

## Anti-patterns

- **Scene with no goal.** "The character talks to the player." → what does the character
  *want*? Without a want, you get aimless chatter.
- **Script not direction.** A line-by-line script of what the character should say. The
  live LLM should improvise. Write intent.
- **Missing contingencies.** A scene that only describes the happy path. The player WILL
  go sideways. Write what the character does when they do.
- **Hidden world-building.** New facts about the world that aren't in `back_story.txt`.
  Either move them there or drop them.

## A good drafting pass

1. Re-read the blueprint's scene-graph entry for this scene.
2. Open with the physical situation as it stands at the moment the scene begins. One
   short paragraph.
3. For each character in the scene, write: their goal here (one sentence), the beats
   their pursuit follows (a short paragraph), the contingencies (what they do if the
   player rushes, freezes, refuses, goes sideways).
4. If there are Narrator / game-state signals, name them and what they should cue.
5. Read back. Is every character's want concrete enough to drive a five-minute
   improvised conversation? If not, sharpen.
