# Moodle PDF: outline and sources

Structure of the PDF one member submits on Moodle before the first presentation on 16 Dec.
The brief requires *"names of team members, code links, task distribution, instructions for
loading code, prompt examples"*. The rest follows the six peer-evaluation criteria, one
section each, so a reader scoring the rubric finds every answer under its own heading.

Each section lists the repository file it is built from. The PDF summarises and links; the
repository holds the evidence.

## 1. Team and links

| Content | Source |
| --- | --- |
| Group 4, the ten members, GitHub handles | `docs/TASK_DISTRIBUTION.md` → Team |
| Repository URL, demo video URL, build download | README |

## 2. The game in one page

| Content | Source |
| --- | --- |
| Premise, setting, cast, Host | README → Concept, `narrative/game_context.json` |
| One case from incident to trial, with screenshots | Playthrough of the build |
| Why the game needs GenAI: every case is generated, every NPC is an LLM | README → Concept |

## 3. How to run

| Content | Source |
| --- | --- |
| Requirements, API keys via environment variables, commands | README → How to run |

## 4. Quality and variety of prompts

*Are the designed prompts clear, well-structured, and diverse, containing the necessary
elements to generate results aligned with the challenge?*

| Content | Source |
| --- | --- |
| Case-file generator (system role, hard rules, self-check, output schema) | `narrative/master_system_prompt.md` |
| NPC dialogue prompt and its JSON reply schema | `dialogue/` |
| Image prompts: character sprite, expression, background, key clue, map | `PROMPT_LOG.md` P-004 |
| Music and sound prompts | `PROMPT_LOG.md` |
| Table of prompting techniques used | `PROMPT_LOG.md` → Prompting techniques used |

## 5. Iterative prompt design process

*Were the iterations performed documented and were the changes justified?*

| Content | Source |
| --- | --- |
| Two or three iterations shown in full: prompt, failure, change, reason, measured result | `PROMPT_LOG.md` (P-002 → P-003 → P-005 is the model) |
| KPI table across versions | `ITERATION_LOG.md`, `docs/ARCHITECTURE.md` → Current numbers |
| Raw evidence | `baselines/` |

## 6. Quality of final result

*How well was the challenge solved and how functional and coherent is the prototype?*

| Content | Source |
| --- | --- |
| What is playable end to end, what is shown as separate modules | Build, README → Status |
| Test and validation results | CI run on `main` (`.github/workflows/ci.yml`) |
| Prompt-injection results against the NPCs | `tests/injection/` |

## 7. Creativity and innovation

*Did the team demonstrate originality in their approach, prompt design, or in how they
addressed the model's limitations?*

| Content | Source |
| --- | --- |
| Model limitations and the workaround for each | `PROMPT_LOG.md` → Model limitations encountered |
| "The LLM proposes, the game disposes": validator, retry with errors, clamped trust | `docs/ARCHITECTURE.md` §2 |

## 8. Task division and integration

*Did the team work collaboratively, with adequate task distribution and coherent integration
of individual contributions?*

| Content | Source |
| --- | --- |
| Pairs, owners, deliverables | `docs/TASK_DISTRIBUTION.md` |
| Contracts between teams (case file, NPC reply) | `narrative/sample_case.json`, `dialogue/schema.py` |
| Contribution history | GitHub commits and pull requests |
