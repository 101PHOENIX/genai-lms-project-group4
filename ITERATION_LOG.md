# Iteration Log

One row per change to a prompt, model, asset pipeline or build. Newest first.
Always record the KPI that moved and link the `baselines/<label>/summary.json` when there is one.

| Date | Team | Artifact | Version | Change | KPI before → after | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-11-25 | 5 | audit_case.py | v0 | Design-audit KPIs from the jury self-critique: solver (min actions to prove the culprit), exact P(enough actions in 7 rolls), culprit margin, filter-risk and derivative-host checks | v1 runs: solvable 3/5, singles out culprit 2/5 | `python tools/audit_case.py baselines/baseline-v1-pollinations/run*.txt`, `docs/self_critique_jury.pdf` |
| 2026-11-25 | 5 | Pollinations images | — | Re-run of the image benchmark | success 2/6 → 6/11 (then server-wide 503s) | `baselines/20261125-1331-images/`, `baselines/_v1_images.log` |
| 2026-11-25 | 1 | Master System Prompt | v1 (measured) | 5 runs, `--retry` | JSON 4/5 → 3/5, logic 0/5 → 0/5; missing NPC secrets 3/5 → 0/5, false clue → killer 2/5 → 0/5, truncation 1/5 → 2/5 | `baselines/baseline-v1-pollinations/`, `baselines/_v1_llm.log`, PROMPT_LOG P-003 |
| 2026-11-23 | 1 | Master System Prompt | v1 | Added self-check block targeting the 4 baseline failure types (invented locations, missing npc_secrets, <2 innocent liars, false clue → killer) + short descriptions to avoid truncation | logic pass 0/5 → 0/5 (see 2026-11-25 row) | PROMPT_LOG P-003 |
| 2026-11-23 | 5 | LLM baseline | v0 | 5 completed runs (6-7 lost to a network drop, run stopped for low memory) | JSON 4/5, logic 0/5, ~10-14 s/call + 45 s rate-limit waits | `baselines/baseline-v0-pollinations/` |
| 2026-11-23 | 5 | Image baseline | — | 6 runs, 46 s apart | success 2/6, 3.1-3.9 s, off-style + watermark | `baselines/20261123-2002-images/` |
| 2026-11-23 | 4 | Core rules (C#) | v0 | Dice tiers, word limiter, trust tracker, 7-round CaseSession | rule tests: — → 30/30 pass | `dotnet test tests/CoreTests` |
| 2026-11-23 | 5 | benchmark_llm.py | v0.2 | Added per-run seed (free API was returning cached identical cases) + 402 backoff | cached run invalid → see baseline-v0 | `baselines/baseline-v0-pollinations/` |
| 2026-11-23 | 1 | Master System Prompt | v0 | First draft from brief §2-3: case types, 4-5 key clues, false clues, NPC secrets, filter-safe image rules | baseline | `baselines/baseline-v0-pollinations/summary.json` |
| 2026-11-23 | 5 | Pollinations images | — | Free tier measured: 1 img / 45 s per IP (402) + server-wide 503s | baseline | `baselines/*-images/summary.json` |
