# Iteration Log

One row per change to a prompt, model, asset pipeline or build. Newest first.
Always record the KPI that moved and link the `baselines/<label>/summary.json` when there is one.

| Date | Team | Artifact | Version | Change | KPI before → after | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-11-28 | 3 | Audio (stable-audio) | manifest v0 | Audio Studio review of 5 takes (1 cues). Approved: dialogue_blip | QC pass 0/5 (warn 4, auto-discarded 1); approved 1/1 cues; takes per accepted cue 5.0; latency p50 23.13 s; rejects: none | `baselines/20261128-0012-audio-stable-audio-3/summary.json`, `baselines/20261128-0012-audio-stable-audio-3/qc.json`, `audio/review.json` <!-- audio-studio-run:20261128-0012-audio-stable-audio-3 --> |
| 2026-11-27 | 3 | Audio (stable-audio) | manifest v0 | Audio Studio review of 26 takes (8 cues). Approved: clue_found, door_open, footsteps, verdict_correct | QC pass 9/26 (warn 8, auto-discarded 9); approved 4/8 cues; takes per accepted cue 3.0; latency p50 25.57 s; rejects: none | `baselines/20261127-2326-audio-stable-audio/summary.json`, `baselines/20261127-2326-audio-stable-audio/qc.json`, `audio/review.json` <!-- audio-studio-run:20261127-2326-audio-stable-audio --> |
| 2026-11-27 | 3 | Audio (stable-audio) | manifest v0 | Audio Studio review of 9 takes (3 cues). Approved: body_alarm, dice_roll, verdict_wrong | QC pass 3/9 (warn 6, auto-discarded 0); approved 3/3 cues; takes per accepted cue 3.0; latency p50 25.64 s; rejects: none | `baselines/20261127-2326-audio-stable-audio-2/summary.json`, `baselines/20261127-2326-audio-stable-audio-2/qc.json`, `audio/review.json` <!-- audio-studio-run:20261127-2326-audio-stable-audio-2 --> |
| 2026-11-27 | 3 | Audio (acestep) | manifest v0 | Audio Studio review of 9 takes (3 cues). Approved: game_over | QC pass 3/9 (warn 3, auto-discarded 3); approved 1/3 cues; takes per accepted cue 3.0; latency p50 255.73 s; rejects: Random notes 3 | `baselines/20261127-2115-audio-acestep-part2/summary.json`, `baselines/20261127-2115-audio-acestep-part2/qc.json`, `audio/review.json` <!-- audio-studio-run:20261127-2115-audio-acestep-part2 --> |
| 2026-11-27 | 3 | Audio (acestep) | manifest v0 | Audio Studio review of 24 takes (4 cues). Approved: crime_discovery, exploration, investigation, investigation_late | QC pass 0/24 (warn 12, auto-discarded 12); approved 4/4 cues; takes per accepted cue 6.0; latency p50 262.0 s; rejects: none | `baselines/20261127-1942-audio-acestep/summary.json`, `baselines/20261127-1942-audio-acestep/qc.json`, `audio/review.json` <!-- audio-studio-run:20261127-1942-audio-acestep --> |
| 2026-11-26 | 3 | Audio (acestep) | manifest v0 | Audio Studio review of 3 takes (2 cues). Approved: trial, victory | QC pass 1/3 (warn 1, auto-discarded 1); approved 2/2 cues; takes per accepted cue 1.5; latency p50 n/a; rejects: none | `baselines/20261126-2045-audio-acestep/summary.json`, `baselines/20261126-2045-audio-acestep/qc.json`, `audio/review.json` <!-- audio-studio-run:20261126-2045-audio-acestep --> |
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

<!-- audio-studio:start -->
## Audio Studio: take-level results

_Generated by `tools/audio_studio.py` from `baselines/<run>/qc.json` and `audio/review.json`. Edits inside this block are overwritten._

### 20261128-0012-audio-stable-audio-3 (stable-audio)

| Cue | Take | QC | Score | LUFS | Duration (s) | Seam (dB / click / timbre) | Auto issues | Decision | Reasons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dialogue_blip | 1 | warn | 73 | -32.0 | 1.0 | — | quiet: -32.0 LUFS (< -26) | undecided | — |
| dialogue_blip | 2 | warn | 73 | -31.9 | 1.0 | — | quiet: -31.9 LUFS (< -26) | undecided | — |
| dialogue_blip | 3 | fail | 45 | -37.6 | 1.0 | — | almost muted: -37.6 LUFS | undecided | — |
| dialogue_blip | 4 | warn | 73 | -33.5 | 1.0 | — | quiet: -33.5 LUFS (< -26) | undecided | — |
| dialogue_blip | 5 | warn | 73 | -34.1 | 1.0 | — | quiet: -34.1 LUFS (< -26) | approved | — |

### 20261127-2326-audio-stable-audio (stable-audio)

| Cue | Take | QC | Score | LUFS | Duration (s) | Seam (dB / click / timbre) | Auto issues | Decision | Reasons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dice_roll | 1 | pass | 97 | -19.3 | 1.5 | — | — | undecided | — |
| dice_roll | 2 | pass | 97 | -19.1 | 1.5 | — | — | undecided | — |
| dice_roll | 3 | pass | 97 | -18.7 | 1.5 | — | — | undecided | — |
| body_alarm | 1 | pass | 92 | -23.8 | 4.0 | — | — | undecided | — |
| body_alarm | 2 | pass | 95 | -20.7 | 4.0 | — | — | undecided | — |
| body_alarm | 3 | pass | 91 | -24.8 | 4.0 | — | — | undecided | — |
| footsteps | 1 | warn | 73 | -32.5 | 3.0 | — | quiet: -32.5 LUFS (< -26) | undecided | — |
| footsteps | 2 | warn | 73 | -31.4 | 3.0 | — | quiet: -31.4 LUFS (< -26) | undecided | — |
| footsteps | 3 | warn | 73 | -32.1 | 3.0 | — | quiet: -32.1 LUFS (< -26) | approved | — |
| door_open | 1 | fail | 45 | -36.8 | 2.0 | — | almost muted: -36.8 LUFS | approved | — |
| door_open | 2 | fail | 45 | -44.0 | 2.0 | — | almost muted: -44.0 LUFS | undecided | — |
| door_open | 3 | fail | 45 | -42.7 | 2.0 | — | almost muted: -42.7 LUFS | undecided | — |
| clue_found | 1 | fail | 36 | -3.6 | 1.5 | — | clipping: 3.65% of samples at full scale; very loud: -3.6 LUFS (> -8) | undecided | — |
| clue_found | 2 | fail | 35 | -3.2 | 1.5 | — | clipping: 3.59% of samples at full scale; very loud: -3.2 LUFS (> -8) | approved | — |
| clue_found | 3 | fail | 53 | -8.8 | 1.5 | — | clipping: 1.97% of samples at full scale | undecided | — |
| dialogue_blip | 1 | fail | 33 | 4.3 | 0.5 | — | clipping: 73.89% of samples at full scale; very loud: 4.3 LUFS (> -8) | undecided | — |
| dialogue_blip | 2 | fail | 33 | 4.7 | 0.5 | — | clipping: 72.90% of samples at full scale; very loud: 4.7 LUFS (> -8) | undecided | — |
| dialogue_blip | 3 | fail | 33 | 4.7 | 0.5 | — | clipping: 79.78% of samples at full scale; very loud: 4.7 LUFS (> -8) | undecided | — |
| verdict_correct | 1 | pass | 97 | -19.4 | 3.0 | — | — | undecided | — |
| verdict_correct | 2 | pass | 97 | -19.4 | 3.0 | — | — | undecided | — |
| verdict_correct | 3 | pass | 98 | -18.3 | 3.0 | — | — | approved | — |
| verdict_wrong | 1 | warn | 79 | -25.4 | 3.0 | — | one-shot starts 0.56s late | undecided | — |
| verdict_wrong | 2 | warn | 77 | -27.2 | 3.0 | — | quiet: -27.2 LUFS (< -26) | undecided | — |
| verdict_wrong | 3 | warn | 65 | -27.0 | 3.0 | — | quiet: -27.0 LUFS (< -26); one-shot starts 0.54s late | undecided | — |
| verdict_wrong | 4 | warn | 76 | -28.0 | 1.81 | — | quiet: -28.0 LUFS (< -26) | undecided | — |
| verdict_wrong | 5 | warn | 74 | -30.1 | 1.94 | — | quiet: -30.1 LUFS (< -26) | undecided | — |

### 20261127-2326-audio-stable-audio-2 (stable-audio)

| Cue | Take | QC | Score | LUFS | Duration (s) | Seam (dB / click / timbre) | Auto issues | Decision | Reasons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dice_roll | 1 | warn | 77 | -27.3 | 2.0 | — | quiet: -27.3 LUFS (< -26) | undecided | — |
| dice_roll | 2 | warn | 76 | -27.7 | 2.0 | — | quiet: -27.7 LUFS (< -26) | undecided | — |
| dice_roll | 3 | warn | 77 | -27.1 | 2.0 | — | quiet: -27.1 LUFS (< -26) | approved | — |
| body_alarm | 1 | pass | 94 | -22.5 | 4.0 | — | — | undecided | — |
| body_alarm | 2 | pass | 95 | -21.4 | 4.0 | — | — | approved | — |
| body_alarm | 3 | pass | 95 | -21.1 | 4.0 | — | — | undecided | — |
| verdict_wrong | 1 | warn | 81 | -22.9 | 3.0 | — | one-shot starts 0.57s late | undecided | — |
| verdict_wrong | 2 | warn | 79 | -25.2 | 3.0 | — | one-shot starts 0.60s late | approved | — |
| verdict_wrong | 3 | warn | 83 | -20.8 | 3.0 | — | one-shot starts 0.57s late | undecided | — |

### 20261127-2115-audio-acestep-part2 (acestep)

| Cue | Take | QC | Score | LUFS | Duration (s) | Seam (dB / click / timbre) | Auto issues | Decision | Reasons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| trial | 1 | fail | 14 | -16.4 | 75.0 | 9.8 / 0.11 / 0.962 | loop ends with 4.77s of silence; loudness jumps 25.9 LU between 3 s windows; loop seam level step 9.8 dB; timbre changes across the loop seam (0.96) | undecided | — |
| trial | 2 | fail | 12 | -17.7 | 75.0 | 10.82 / 0.26 / 0.963 | loop ends with 1.94s of silence; loudness jumps 13.7 LU between 3 s windows; loop seam level step 10.8 dB; timbre changes across the loop seam (0.96) | undecided | — |
| trial | 3 | fail | 15 | -12.8 | 75.0 | 0.0 / 8.15 / 0.952 | loop ends with 2.53s of silence; click at the loop seam (x8.2 the usual step); timbre changes across the loop seam (0.95) | undecided | — |
| victory | 1 | warn | 85 | -13.3 | 10.0 | — | loudness jumps 11.5 LU between 3 s windows | rejected | Random notes |
| victory | 2 | warn | 86 | -14.2 | 10.0 | — | loudness jumps 14.7 LU between 3 s windows | rejected | Random notes |
| victory | 3 | pass | 98 | -14.2 | 10.0 | — | — | rejected | Random notes |
| game_over | 1 | pass | 99 | -15.1 | 10.0 | — | — | undecided | — |
| game_over | 2 | pass | 98 | -17.9 | 10.0 | — | — | approved | — |
| game_over | 3 | warn | 86 | -14.0 | 10.0 | — | loudness jumps 10.6 LU between 3 s windows | undecided | — |

### 20261127-1942-audio-acestep (acestep)

| Cue | Take | QC | Score | LUFS | Duration (s) | Seam (dB / click / timbre) | Auto issues | Decision | Reasons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exploration | 1 | fail | 13 | -14.8 | 60.0 | 20.19 / 0.27 / 0.964 | loop ends with 4.27s of silence; loudness jumps 13.7 LU between 3 s windows; loop seam level step 20.2 dB; timbre changes across the loop seam (0.96) | undecided | — |
| exploration | 2 | fail | 0 | -17.1 | 60.0 | 0.0 / 20.2 / 0.962 | loop starts with 0.72s of silence; loop ends with 3.12s of silence; click at the loop seam (x20.2 the usual step); timbre changes across the loop seam (0.96) | undecided | — |
| exploration | 3 | fail | 26 | -16.0 | 60.0 | 29.65 / 0.3 / 0.969 | loop ends with 6.28s of silence; loop seam level step 29.6 dB; timbre changes across the loop seam (0.97) | undecided | — |
| crime_discovery | 1 | fail | 25 | -15.5 | 30.0 | 24.31 / 0.26 / 0.975 | loop ends with 1.65s of silence; loop seam level step 24.3 dB; timbre changes across the loop seam (0.97) | undecided | — |
| crime_discovery | 2 | fail | 10 | -16.1 | 30.0 | 2.81 / 5.32 / 0.851 | loop ends with 5.86s of silence; loudness jumps 30.4 LU between 3 s windows; click at the loop seam (x5.3 the usual step); timbre changes across the loop seam (0.85) | undecided | — |
| crime_discovery | 3 | fail | 14 | -16.1 | 30.0 | 32.29 / 0.3 / 0.976 | loop ends with 4.58s of silence; loudness jumps 20.5 LU between 3 s windows; loop seam level step 32.3 dB; timbre changes across the loop seam (0.98) | undecided | — |
| investigation | 1 | fail | 14 | -15.2 | 75.0 | 37.88 / 0.02 / 0.96 | loop ends with 4.77s of silence; loudness jumps 13.0 LU between 3 s windows; loop seam level step 37.9 dB; timbre changes across the loop seam (0.96) | undecided | — |
| investigation | 2 | fail | 13 | -15.0 | 75.0 | 22.27 / 0.6 / 0.972 | loop ends with 2.93s of silence; loudness jumps 24.3 LU between 3 s windows; loop seam level step 22.3 dB; timbre changes across the loop seam (0.97) | undecided | — |
| investigation | 3 | fail | 12 | -14.1 | 75.0 | 17.68 / 0.47 / 0.969 | loop ends with 6.70s of silence; loudness jumps 19.8 LU between 3 s windows; loop seam level step 17.7 dB; timbre changes across the loop seam (0.97) | undecided | — |
| investigation_late | 1 | fail | 11 | -13.7 | 60.0 | 38.74 / 0.54 / 0.98 | loop ends with 6.94s of silence; loudness jumps 32.2 LU between 3 s windows; loop seam level step 38.7 dB; timbre changes across the loop seam (0.98) | undecided | — |
| investigation_late | 2 | fail | 12 | -13.9 | 60.0 | 12.82 / 0.14 / 0.978 | loop ends with 4.72s of silence; loudness jumps 21.2 LU between 3 s windows; loop seam level step 12.8 dB; timbre changes across the loop seam (0.98) | undecided | — |
| investigation_late | 3 | fail | 36 | -14.3 | 60.0 | 0.0 / 0.72 / 0.966 | loop ends with 3.27s of silence; timbre changes across the loop seam (0.97) | undecided | — |
| exploration | 4 | warn | 66 | -14.8 | 55.73 | 32.35 / 0.0 / 0.862 | loop seam level step 32.4 dB; timbre changes across the loop seam (0.86) | approved | — |
| exploration | 5 | warn | 70 | -17.1 | 56.2 | 23.27 / 0.0 / 0.452 | loop seam level step 23.3 dB; timbre changes across the loop seam (0.45) | undecided | — |
| exploration | 6 | warn | 69 | -16.0 | 53.74 | 29.65 / 0.0 / 0.745 | loop seam level step 29.6 dB; timbre changes across the loop seam (0.74) | undecided | — |
| crime_discovery | 4 | warn | 84 | -15.5 | 28.36 | 29.64 / 0.0 / 0.329 | loop seam level step 29.6 dB | approved | — |
| crime_discovery | 5 | warn | 83 | -16.1 | 24.16 | 2.45 / 0.0 / 0.448 | timbre changes across the loop seam (0.45) | undecided | — |
| crime_discovery | 6 | warn | 67 | -16.0 | 25.44 | 32.01 / 0.0 / 0.922 | loop seam level step 32.0 dB; timbre changes across the loop seam (0.92) | undecided | — |
| investigation | 4 | warn | 54 | -15.2 | 70.25 | 37.88 / 0.0 / 0.903 | loudness jumps 13.0 LU between 3 s windows; loop seam level step 37.9 dB; timbre changes across the loop seam (0.90) | undecided | — |
| investigation | 5 | warn | 70 | -14.9 | 72.08 | 16.31 / 0.0 / 0.507 | loop seam level step 16.3 dB; timbre changes across the loop seam (0.51) | approved | — |
| investigation | 6 | warn | 67 | -14.1 | 68.31 | 22.91 / 0.0 / 0.7 | loop seam level step 22.9 dB; timbre changes across the loop seam (0.70) | undecided | — |
| investigation_late | 4 | warn | 69 | -13.7 | 53.08 | 38.73 / 0.0 / 0.429 | loop seam level step 38.7 dB; timbre changes across the loop seam (0.43) | approved | — |
| investigation_late | 5 | warn | 64 | -13.9 | 55.3 | 12.76 / 0.0 / 0.979 | loop seam level step 12.8 dB; timbre changes across the loop seam (0.98) | undecided | — |
| investigation_late | 6 | warn | 84 | -14.3 | 56.64 | 27.03 / 0.0 / 0.193 | loop seam level step 27.0 dB | undecided | — |

### 20261126-2045-audio-acestep (acestep)

| Cue | Take | QC | Score | LUFS | Duration (s) | Seam (dB / click / timbre) | Auto issues | Decision | Reasons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| trial | 1 | fail | 6 | -13.4 | 75.0 | 0.0 / 5.29 / 0.964 | loop ends with 1.46s of silence; loudness jumps 10.1 LU between 3 s windows; click at the loop seam (x5.3 the usual step); timbre changes across the loop seam (0.96) | undecided | — |
| victory | 2 | pass | 98 | -13.9 | 10.0 | — | — | approved | — |
| trial | 2 | warn | 63 | -13.4 | 73.51 | 17.01 / 0.0 / 0.994 | loop seam level step 17.0 dB; timbre changes across the loop seam (0.99) | approved | — |
<!-- audio-studio:end -->
