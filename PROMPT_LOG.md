# Prompt Log

Every prompt iteration goes here. Add your entries **before you leave each session** —
the commit dates are themselves evidence that the process was iterative.

This file exists because of one of the six peer-evaluation criteria:

> *"Iterative Prompt Design Process — Evaluation of the prompt design and refinement
> process: Were the iterations performed documented and were the changes justified?"*

Copy the template below. Keep it short. **The `Reason` line is the one that scores** —
it is what turns a list of prompts into a documented, justified process.

Numbering: `P-001`, `P-002`, … Just take the next free number.

---

## Template

```
### P-000 · <module> · <name> · YYYY-MM-DD
**Goal:**
**Model / settings:**
**Prompt:**
**Output:**
**Problem:**
**Change:**
**Reason:**
**Result:**
```

---

## Worked example — what a good entry looks like

### P-001 · dialogue · Doruk · 2026-11-18
**Goal:** Innkeeper NPC hands the player a quest, returned as JSON the game can parse.
**Model / settings:** openai/gpt-oss-20b via Groq, temperature 0.7
**Prompt:**
> You are the innkeeper in a small harbour town. The player has just walked in.
> Reply in character and return JSON with the fields text, emotion, intent, item.

**Output:** Valid JSON, but `intent` came back as `"trade"`.
**Problem:** `"trade"` is not one of the intents the game handles — game code raised a KeyError.
**Change:** Constrained the field with a Pydantic `Literal` and added an explicit
"use only these intents" line to the system message.
**Reason:** A free-form string lets the model invent values the game cannot act on.
Validating at the schema level fails loudly instead of corrupting game state.
**Result:** 20 runs, 20 valid intents.

---

## Entries

<!-- Add new entries below this line, newest last. -->

### P-002 · narrative · Borja · 2026-11-23
**Goal:** Generate the hidden truth of one murder case (victim, killer, clues, NPC lies) as a single JSON *case file* that Unity can load without human review.
**Model / settings:** Pollinations `openai` (free, no key), `response_format: json_object`, per-run seed in the user message.
**Prompt:** `narrative/master_system_prompt.md` v0: system-role Game Master, 9 hard rules taken from the brief (case types, 4–5 key clues, 2–3 false clues, one secret per NPC, filter-safe image wording) and the exact output shape.
**Output:** 5 runs (`baselines/baseline-v0-pollinations/`): JSON valid 4/5, logic checks 0/5, ~10–14 s per call.
**Problem:** Four repeating failure types found by `validate_case.py` (runs affected out of 5): (1) missing `npc_secrets` entries 3/5, (2) fewer than 2 innocent liars 3/5, (3) a false clue pointing at the real killer 2/5, (4) invented locations (`kitchen` is not in `locations`) 1/5. Plus one output cut off mid-JSON 1/5.
**Change:** Wrote v1 (P-003).
**Reason:** Each failure breaks the game, not just the story: an unknown location has no scene, an NPC without a secret has nothing to say, a false clue that accuses the killer is actually a true clue. Measuring first told us *which* rules the model ignores, so v1 targets those instead of rewriting everything.
**Result:** Baseline recorded; it is the reference every later version is compared against.

### P-003 · narrative · Borja · 2026-11-23 (measured 2026-11-25)
**Goal:** Fix the four v0 failure types without changing the schema.
**Model / settings:** Same as P-002, with `--retry` (one self-repair turn, see P-005).
**Prompt:** v1 = v0 + a `# Self-check before answering` block, one line per v0 failure: use only the listed location strings; `npc_secrets` count = alive − 2, walk the list id by id; ≥ 2 innocent liars; no false clue points to the culprit; ≥ 2 key clues point to the culprit; descriptions ≤ 2 sentences so the JSON is never truncated.
**Output:** 5 runs (`baselines/baseline-v1-pollinations/`): JSON valid 3/5, logic 0/5. Errors: 2 truncated outputs, `kitchen` again (1), `hanging` in the crime-scene prompt (1), only 1 innocent liar (1). The retry turn did not rescue the truncated run.
**Problem:** The checklist worked where it was specific: missing NPC secrets 3/5 → 0/5, false clue → killer 2/5 → 0/5, too few innocent liars 3/5 → 1/5. But truncation got worse (1/5 → 2/5), invented rooms stayed (1/5 → 1/5) and a banned word appeared (`hanging`, 1/5). Every run still fails at least one check.
**Change:** None merged yet. Next: move to a provider with schema-constrained output (Gemini `responseSchema` / Groq JSON schema) and keep the validator retry as a second net.
**Reason:** The remaining errors are things a checklist in the prompt cannot enforce on a free model (output length, closed vocabularies). Constraining the decoder enforces them by construction; prompt text only asks.
**Result:** Pending a Gemini/Groq run (`benchmark_llm.py --provider gemini --runs 20 --retry`).

### P-004 · images · Borja · 2026-11-23
**Goal:** Crime-scene and clue images in a consistent 2D anime visual-novel style that providers do not refuse.
**Model / settings:** Pollinations image API (free tier), 512–768 px, `nologo=true`, fixed seed per case.
**Prompt:** Fixed style prefix + case-specific middle + fixed suffix, e.g. *"2D stylized anime visual novel evidence photo, bold black ink outlines, sharp cel shading with subtle halftone dot texture, high-contrast lighting. Close-up top-down view of* {clue `image_prompt`} *, dramatic spotlight from above, mysterious atmosphere. Square composition, no text, no labels, no watermark."* The LLM writes only the middle part, under the filter-safe word rules (P-002 rule 8).
**Output:** 2/6 images on 11-23 (rest 402 rate limit / 503), off-style with a watermark; 6/11 on 11-25 before the server returned 503 for every request.
**Problem:** The free tier allows 1 image / 45 s per IP and has server-wide outages; style drifts between images.
**Change:** Split style (owned by the art team, fixed in code) from content (generated). Built `LiveImageQueue`: prefetch at case start, 46 s spacing, timeout, local fallback.
**Reason:** A consistent prefix is the cheapest style control we have. The rate limit is a provider property no prompt can fix, so the game is designed so the demo never waits for an image.
**Result:** Pipeline robust to outages; style consistency still weak (see limitations #4).

### P-005 · narrative · Borja · 2026-11-23
**Goal:** Recover invalid case files automatically instead of discarding them.
**Model / settings:** Same model, same system prompt, second user turn.
**Prompt:** *"Your previous answer was: {output}. It has these problems: - {validator error 1} - {validator error 2}… Return the corrected full JSON object only."*
**Output:** Implemented as `benchmark_llm.py --retry`, KPI `valid_after_retry_rate`.
**Problem:** On v1 the only retried truncated run failed again (new invalid JSON).
**Change:** Keep it, but only as a second net behind schema-constrained decoding.
**Reason:** Feeding back the exact validator messages turns a vague "try again" into a targeted fix, and costs one extra call only on failure. Its weak spot is truncation: the repaired answer is as long as the first one.
**Result:** Too few retries so far to give a rate.

---

## Model limitations encountered

Running list. Hallucinated APIs, inconsistent state across turns, broken generated code,
format drift, refusals, latency, cost, asset style inconsistency — anything where the
model got in our way and we had to work around it.

This feeds a second criterion:

> *"Creativity and Innovation — Did the team demonstrate originality in their approach,
> prompt design, or in how they addressed **the model's limitations**?"*

| # | Limitation | Where it hit us | What we did about it |
|---|---|---|---|
| 1 | Free API returned cached, identical cases for identical prompts | First LLM baseline was meaningless | Per-run seed in the user message (`benchmark_llm.py` v0.2) |
| 2 | Model ignores closed vocabularies (invents `kitchen`) | 1/5 v0 runs, 1/5 v1 runs | Validator rejects; next: schema-constrained decoding (P-003) |
| 3 | Long JSON gets truncated mid-string | 1/5 v0, 2/5 v1 | Short-description rule; retry with errors (P-005) |
| 4 | Image style drifts and adds watermarks | Pollinations baseline 11-23 | Fixed style prefix/suffix, `nologo=true`, fixed seed (P-004) |
| 5 | Image filters refuse violent words | Crime-scene prompts | Banned word list + visual-novel substitutes, enforced by the validator |
| 6 | Free image tier: 1 img / 45 s per IP + 503 outages | Live images | `LiveImageQueue` prefetch + timeout + offline fallback |

---

## Prompting techniques used

Tick these off as they appear in the log. The rubric scores **variety**, not just quality:

- [x] Zero-shot (P-002)
- [ ] One-shot / few-shot
- [x] System-role design (P-002)
- [x] Structured output (Pydantic / JSON schema) (P-002, JSON mode + validator)
- [ ] Chain-of-thought
- [x] Iterative refinement on a failing output (P-003, P-005)
- [x] Image generation prompt (P-004)
- [ ] Audio / music prompt
- [ ] Code generation prompt
