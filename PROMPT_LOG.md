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
| 1 | | | |

---

## Prompting techniques used

Tick these off as they appear in the log. The rubric scores **variety**, not just quality:

- [ ] Zero-shot
- [ ] One-shot / few-shot
- [ ] System-role design
- [ ] Structured output (Pydantic / JSON schema)
- [ ] Chain-of-thought
- [ ] Iterative refinement on a failing output
- [ ] Image generation prompt
- [ ] Audio / music prompt
- [ ] Code generation prompt
