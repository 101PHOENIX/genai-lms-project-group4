# Audio Studio tutorial

Audio Studio is a local web app for the game's music and sound effects. It covers the steps of
[`AUDIO.md`](AUDIO.md) from the browser: generate takes, filter out technically broken ones, listen
and decide, copy the winners into Unity and keep the provenance and logs up to date.

It runs on your machine only. It never calls an audio API by itself, except ACE-Step when you press
**Generate locally** with that provider.

- [1. Install and start](#1-install-and-start)
- [2. The screen at a glance](#2-the-screen-at-a-glance)
- [3. Edit the manifest](#3-edit-the-manifest)
- [4. Get takes](#4-get-takes)
- [5. Review: technical filter](#5-review-technical-filter)
- [6. Review: listen and decide](#6-review-listen-and-decide)
- [7. Apply to Unity and the docs](#7-apply-to-unity-and-the-docs)
- [8. What gets written where](#8-what-gets-written-where)
- [9. Typical sessions](#9-typical-sessions)
- [10. Troubleshooting](#10-troubleshooting)

## 1. Install and start

```bash
pip install -r requirements-audio.txt     # streamlit, numpy, scipy, soundfile, pandas
python tools/audio_studio.py               # opens http://localhost:8501
```

- Any `streamlit run` flag can be added, e.g. `python tools/audio_studio.py --server.port 8600`.
- The first start on a machine can take up to a minute while numpy and scipy load. Later starts are
  quick.
- Stop it with `Ctrl+C` in the terminal.
- `tools/generate_audio.py` still needs no extra packages. The CLI and the Studio write the same files,
  so you can mix them.

## 2. The screen at a glance

**Sidebar**

| Setting | What it does |
| --- | --- |
| Unity audio folder | Where approved takes are copied. Music goes to `<folder>/Music/`, SFX to `<folder>/SFX/`. Default `unity/Assets/Audio`. Relative paths start at the repo root, so `AudioTest/AudioTest/Assets` targets a local test project. |
| ACE-Step URL | REST server used by **Generate locally** with `acestep`. Default `http://127.0.0.1:8001`, or `ACESTEP_URL` from the environment or `.env`. |
| Apply on approve | On (default): approving a take copies it into Unity and updates provenance and docs immediately. Off: decisions are only recorded until you press **Apply changes & update project**. |
| Job | Status of the generation running in the background, if any. |

**Tabs**

1. **Manifest & generation**: edit `audio/audio_cues.json`, add cues, generate or import takes.
2. **Review**: technical filter, players and approve / reject buttons.
3. **Apply to Unity & docs**: what is approved, what is still pending, and the apply button.

## 3. Edit the manifest

The manifest (`audio/audio_cues.json`) is the contract with Unity: music ids must match
`MusicCues.cs`, SFX ids must match `SfxPlayer.Ids`.

### Edit existing cues

1. In **Manifest & generation**, change any cell of the **Music** or **SFX** tables: prompt,
   duration, bpm, key, loop. Ids are read-only (renaming would break the Unity contract).
2. **Version**, **Music style** (prefix of every music prompt) and **Loop rules** (appended to
   looping music prompts) are editable above the tables.
3. Press **Save manifest**. The file is validated first (ids, empty prompts, bpm 30-300,
   durations). If anything is wrong, nothing is written and the errors are listed.

The file keeps its hand-written layout, so the git diff shows only what you changed.

> Bump **Version** when you change prompts in a way you want to measure. It is copied into each
> run's `summary.json` and into the `ITERATION_LOG.md` row.

### Add a new track or SFX

1. Open **Add a music track or SFX**.
2. Fill in:
   - **Id**: lowercase letters and underscores only, e.g. `door_slam`.
   - **Kind**: `music` or `sfx`.
   - **Duration (s)** and **Playback** (`loop` or `one-shot`).
   - **BPM** and **Key**: music only (0 / empty = none).
   - **Prompt**: what it should sound like. Never name artists, songs or game franchises.
3. Keep **Add the C# constant** ticked. It inserts `public const string DoorSlam = "door_slam";`
   into `SfxPlayer.Ids` (SFX) or `MusicCues` (music), so the id tests keep passing.
4. Press **Add cue**.

For a new **music** cue, the constant alone does not make the game play it: wire it in
`MusicCues.ForState` (and `Loops` if it is a one-shot) by hand, then drag the clip into
`MusicDirector` in Unity.

## 4. Get takes

Every source ends up as a **run**: a folder `baselines/<date>-audio-<provider>/` with the takes
(`<cue>_c01.wav`, `_c02`...) and a `summary.json`. The Review tab works the same for all of them.

Pick the source with the **Provider** selector:

| Provider | Use it for | How |
| --- | --- | --- |
| `acestep` | Music on a GPU | Local server, or Colab (below) |
| `mock` | Testing the pipeline and the Unity import | Sine tones, instant, no network |
| `stable-audio` | SFX with Stable Audio 3 Small-SFX | Colab (4c), or import files made in its UI (4d) |
| `freesound` | SFX downloaded from Freesound | Import files |

### 4a. Generate locally (acestep or mock)

1. Choose the **Cues**. Leave the field empty for all cues (for `acestep`, all music cues: ACE-Step
   does not render SFX).
2. Set **Candidates per cue** (3 is a good start) and check the **Output folder**.
3. Press **Generate locally**. The job runs in the background and its log appears below,
   refreshing every 2 seconds. You can keep working in other tabs meanwhile. Only one job runs at a time.
4. When it finishes, press **Review this run**.

For `acestep`, a server must be running at the **ACE-Step URL**. The Studio checks `GET /health`
(re-checked every 15 s or with **Check again**). While no server answers, **Generate locally** is
disabled and a warning explains why. You have two ways to get a server:

- **Colab (recommended)**: no install, free GPU. Use 4b instead of this section.
- **Your own NVIDIA GPU** (about 4 GB of VRAM; a 4 GB card such as a GTX 1650 is at the limit, so
  use short cues and one candidate first):
  ```bash
  pip install uv
  git clone --depth 1 https://github.com/ACE-Step/ACE-Step-1.5 && cd ACE-Step-1.5 && uv sync
  uv run acestep-api        # keep this terminal open; the first start downloads the weights
  ```
  On Windows, ACE-Step also ships a portable package with a `start_api_server.bat`. When the
  terminal says the server is up on port 8001, press **Check again** in the Studio.

### 4b. Generate on Google Colab (free GPU)

1. Choose cues and candidates as above, then open **Run on Google Colab**.
2. In a Colab notebook with a GPU runtime (*Runtime → Change runtime type → T4 GPU*), paste each of
   the five blocks into its own cell and run them in order:
   1. **Install** (3-6 min): checks the GPU, clones ACE-Step and installs it with `uv sync`
      (this pulls PyTorch, so it is slow but shows progress), clones this repo on the current branch.
   2. **Start the server**: launches `acestep-api` in the background and polls `GET /health`.
      The **first** start downloads the model weights (several GB, 5-15 min). Every 20 s it prints
      the elapsed time and the last line of `api.log`, so you can tell it is still working. If the server
      crashes, the cell stops at once and shows the last 30 log lines. If nothing is up after 30 min, it fails with a
      timeout. Running the cell again reuses a server that is already up.
   3. `%%writefile` writes **your current local manifest** into the clone, so prompt edits you have
      not pushed are used too.
   4. `%%writefile` writes **your current local `tools/generate_audio.py`** the same way, so Colab runs
      exactly the code you have (seed logging, new providers) even before you push it. It is long:
      copy it with the icon at the top right of the box.
   5. Mounts Google Drive, generates, and saves the run as `MyDrive/audio_runs/<run>.zip`.
3. Back in the Studio, open **Import a run from Colab / Google Drive** and either upload the `.zip`
   or paste the path of the run folder if Google Drive is synced on your computer. Press
   **Import run**.

The imported run is copied into `baselines/` and selected in the Review tab.

If the Colab session ends before the last cell finishes, the takes already written are in
`/content/<repo>/baselines/<run>/` but there is no `summary.json`. Zip and download that folder anyway:
the summary can be rebuilt from the files.

### 4c. Generate SFX on Google Colab with Stable Audio 3

Same flow as 4b, with Stable Audio 3 Small-SFX running on the Colab GPU instead of the web UI, so
there are no demo-page quotas. Each take takes seconds once the model is loaded.

**Once per Hugging Face account:** the model is gated. Log in at huggingface.co, open
`stabilityai/stable-audio-3-small-sfx` and accept its licence, then create a **read** access token
(*Settings → Access Tokens*). Optional: save it in Colab as a secret named `HF_TOKEN` (key icon in the
left bar, *Notebook access* on) so you don't have to paste it every session.

1. Manifest & generation → provider **`stable-audio`**. Choose the SFX **Cues** (empty = all eight)
   and **Candidates per cue** (3-5 is cheap here), then open **Run on Google Colab**.
2. Paste the five blocks into separate cells and run them in order:
   1. **Install** (3-6 min): clones `Stability-AI/stable-audio-3` and runs `uv sync`, which creates its
      own environment with PyTorch 2.7. Also clones this repo.
   2. **Log in to Hugging Face**: uses the `HF_TOKEN` secret if there is one, otherwise shows a box to
      paste the token. It prints your user name when it works.
   3. Writes your current manifest (prompts and durations).
   4. Writes your current `tools/generate_audio.py`, which contains the `stable-audio` provider.
   5. Generates with `uv run python tools/generate_audio.py generate --provider stable-audio …` inside the
      Stable Audio environment, then zips the run into `MyDrive/audio_runs/<run>.zip`.
3. Import the zip (**Import a run from Colab / Google Drive**) and review it like any other run.

Each take is a 16-bit WAV of exactly the cue's duration. The run's `summary.json` records the model,
steps, CFG scale, sample rate, the seed of every take and its latency. The licence recorded is the
Stability AI Community License. Optional environment variables for cell 5: `SA3_MODEL` (default
`small-sfx`), `SA3_STEPS` (8), `SA3_CFG` (1.0).

If the run stops with *auth error 401*, the licence was not accepted or the token is wrong: fix it and
run cell 2 again.

### 4d. Import SFX made by hand (Stable Audio UI or Freesound)

For `stable-audio` this is under **Or import files made by hand in the Stable Audio UI**. For `freesound` it is
the whole panel.

1. Choose provider `stable-audio` or `freesound`, then pick the **Cue** (for `stable-audio` only SFX
   are listed: Small SFX makes effects only).
2. The card under the selector shows the exact prompt and duration. **Copy prompt** and
   **Copy duration** put each one on the clipboard, ready to paste into the Stable Audio 3 UI's
   prompt and seconds fields. The text box also has its own copy icon on hover.
   For a batch session, turn on **Show all SFX prompts** to list every SFX with the same buttons.
3. Make 2-3 takes in the Stable Audio 3 Small SFX UI and download them as WAV (or download
   candidates from Freesound).
4. Upload the files (one per take; wav, mp3, ogg, aiff or flac).
5. Fill in **Source** and **Licence**. Both are required: they go to `audio/provenance.json`, which
   is the attribution record for the credits.
   - Stable Audio 3: `Stable Audio 3 Small SFX` / `Stability AI Community License` (prefilled).
   - Freesound: `Freesound: <author>, <sound id>` and that sound's licence (prefer CC0; keep the
     author for CC-BY). Import sounds with different licences separately.
6. Press **Import takes**.

## 5. Review: technical filter

Open **Review** and pick the **Run**. Every take is analyzed automatically. The results are cached in
`baselines/<run>/qc.json` and recomputed only when a file changes (**Re-analyze** forces it).

| Check | Rule | Result |
| --- | --- | --- |
| Duration | Differs from the requested length by more than 5 % and more than 0.5 s | fail |
| Silence (loops) | More than 0.25 s below -50 dBFS at the start or end | fail |
| Silence (one-shots) | Starts more than 0.3 s late | warn |
| Muted | No signal, or integrated loudness below -35 LUFS | fail |
| Clipping | More than 0.1 % of samples at full scale | fail |
| Loudness | Louder than -8 LUFS or quieter than -26 LUFS | warn |
| Loudness jumps | More than 10 LU between consecutive 3 s windows (takes of 6 s or more) | warn |
| Loop seam (loops) | Level step > 6 dB, a click at the join, or a timbre change between the last and first second | warn |
| Unreadable / missing | The file cannot be decoded or is gone | fail |

Each take also gets a **score from 0 to 100**. It starts at 100 and loses points for each issue,
for distance from about -16 LUFS, and for seam roughness. Use it to rank takes, not as an absolute grade.

How the list is ordered for each cue:

- **PASS** takes first, best score on top, then **WARN** takes.
- **FAIL** takes are folded under **Auto-discarded (n)** with their reasons. You can still open
  and approve one if you disagree with the filter.
- Takes that failed to generate are listed with the provider's error.

Seam problems are warnings, not failures, because `MusicDirector` crossfades the loop point in
Unity. Still listen to those takes with **Loop** on.

The thresholds are constants at the top of `tools/audio_qc.py`.

### Trim silence

ACE-Step often ends a piece a few seconds early and pads the rest with digital silence, despite
the loop rules. Those takes fail on *loop ends with N s of silence*, but the music itself may be fine.

- **Trim silence on N take(s)** (top of the run) or **Trim silence** (on a take card) cuts the
  silent head and tail into a **new take** of the same run: `<cue>_cNN.wav` (16-bit WAV, next free
  take number). It keeps 20 ms past the last audible frame and adds 10 ms fades so the cut can't click.
- The original file is kept. The new take is added to `summary.json` with `derived_from`,
  `edit: "trim"` and the seconds removed (`trim_s`). Its `requested_s` is the trimmed length, so the
  duration check doesn't reject it (the original length is kept in `original_requested_s`).
- The new take is analyzed straight away and listed with **✂️ trimmed**. If you promote it,
  `provenance.json` records which take it was cut from.
- A take is trimmed only once, and a trim that would remove more than half the take is refused.

After trimming, the remaining warnings are usually about the loop seam: the music ends with a cadence
instead of flowing into its start. Judge that by ear with **Loop** on. In the game, `MusicDirector`
crossfades the last 2 s into the start, which hides a lot of it.

## 6. Review: listen and decide

Each take card shows the metrics, any issues, a player and the decision buttons.

- **Loop**: plays the take in a loop (on by default for looping cues). Listen to the join: a gap, a
  click, or a beat that stumbles means a bad loop.
- **Approve & promote** (or **Approve** when *Apply on approve* is off): this take becomes the
  cue's winner. A previously approved take for the same cue, from any run, becomes *superseded*.
- **Reject**: first select one or more reasons (**Vocals**, **Random notes**, **Style mismatch**,
  **Bad loop**, **Odd volume**), then press **Reject**. Rejecting without a reason is allowed, but
  the reasons are what the iteration log counts.
- **Undo**: removes the decision of that take.

Useful filters at the top: **Cues** (show only some cues) and **Undecided only**.

### Edit a prompt and regenerate

If no take of a cue convinces you, open **Edit prompt & regenerate** under that cue:

1. Edit the cue prompt. **Sent as** shows the full prompt the provider will receive (music style +
   prompt + bpm/key + loop rules).
2. **Save prompt** only updates the manifest. **Save & regenerate** also starts a new run for that
   cue with the chosen provider and number of candidates. Review it when the job finishes.
3. For SFX, generate new takes on Colab (4c) or import hand-made ones (4d). Only `mock` can
   regenerate SFX here.

Rejection reasons point to the fix: *Vocals* → reinforce "no vocals" in the music style;
*Bad loop* → check the loop rules; *Style mismatch* → rewrite the cue prompt.

## 7. Apply to Unity and the docs

Open **Apply to Unity & docs**. The table lists every cue with its approved take, whether it is
already in Unity (`yes`, `no` or `pending`) and its provenance.

Press **Apply changes & update project**. You can press it as often as you like: nothing is duplicated.

1. Copies each approved take that is not in the Unity folder yet to
   `<Unity audio folder>/Music|SFX/<cue id>.<ext>`. A file of the same cue in another format is
   replaced; re-assign the clip in the Inspector if the extension changed.
2. Writes the cue's record in `audio/provenance.json`.
3. Updates `ITERATION_LOG.md` and the inventory in `docs/AUDIO.md` (see below).

With **Apply on approve** on, the same thing already happens on every approval. Use the button
after rejections (so the log counts them), or after changing the Unity folder.

Then, in Unity, assign the new clips in the `clips` lists of `MusicDirector` / `SfxPlayer` (see
`AUDIO.md` §4).

## 8. What gets written where

| File | Written by | Content |
| --- | --- | --- |
| `audio/audio_cues.json` | Save manifest, Add cue, Save prompt | The cues |
| `unity/Assets/Scripts/Core/MusicCues.cs`, `.../Audio/SfxPlayer.cs` | Add cue (if ticked) | One new id constant |
| `baselines/<run>/` | Generate, imports | Takes, `summary.json`, `generate.log` |
| `baselines/<run>/qc.json` | Review | Technical filter results |
| `audio/review.json` | Approve, Reject, Undo | Every decision: run, cue, take, status, reasons, QC score, dates |
| `<Unity audio folder>/Music\|SFX/` | Apply | The winning files |
| `audio/provenance.json` | Apply | Per cue: file, provider, licence, prompt, settings, run, take, seed, latency, manifest version, QC, dates, source (imports) |
| `ITERATION_LOG.md` | Apply | One row per reviewed run in the main table (QC pass/warn/discarded, cues approved, takes per accepted cue, latency p50, top reject reasons), plus a take-level section between `<!-- audio-studio:start -->` / `end` markers |
| `docs/AUDIO.md` | Apply | Section *7. Inventory* between `<!-- audio-inventory:start -->` / `end` markers: every cue as approved, pending or promoted (CLI) |

Only the marked blocks and the rows tagged `<!-- audio-studio-run:<run> -->` are regenerated.
Everything else in those files is never touched, so the team can keep editing them by hand.
Don't edit inside the markers: it is overwritten.

Commit `audio_cues.json`, `review.json`, `provenance.json`, the `summary.json` / `qc.json` of runs
you used, the logs and the Unity assets. Large take files in `baselines/` are not meant to be committed.

## 9. Typical sessions

**First pass on the music, with Colab**

1. Manifest & generation → provider `acestep` → leave cues empty → 3 candidates → **Run on Google
   Colab** → run the three cells.
2. Import the zip from Drive.
3. Review: listen to the PASS takes of each cue with Loop on, approve one, reject the rest with a
   reason.
4. For cues where nothing works: **Edit prompt & regenerate** (or a new Colab run with only those
   cues).
5. Apply → commit.

**Adding a new sound effect**

1. Add cue (`sfx`, id, duration, prompt, C# constant ticked).
2. Make takes in Stable Audio 3, import them with source and licence.
3. Review, approve, Apply. In Unity, add the clip to `SfxPlayer` and call
   `sfx.Play(SfxPlayer.Ids.YourId)` where it belongs.

**Checking the Unity wiring without a GPU**

Generate with `mock`, approve one take per cue, Apply. Unity then gets test tones for every cue, and
the inventory marks them with the licence "test tone, replace before release".

## 10. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Streamlit is not installed` | `pip install -r requirements-audio.txt` |
| Every MP3 take is *unreadable* | Old soundfile: `pip install -U soundfile` (needs libsndfile ≥ 1.1, bundled in the wheels). |
| *Generate locally is off: no ACE-Step server at …* | Nothing is listening at the ACE-Step URL. Start `uv run acestep-api` (4a), point the URL to your server, or use Colab (4b). |
| Colab cell 2 keeps printing `waiting...` | Normal on the first start while the weights download; the log line shows what it is doing. If the last line doesn't change for more than 10 min, open `/content/ACE-Step-1.5/api.log`. |
| Colab cell 2 says the server exited | Read the log lines it prints. `CUDA out of memory` or no GPU listed in cell 1 → switch the runtime to a GPU and run again from cell 1. |
| Colab cell 2: server exited with `Key backend: 'module://matplotlib_inline.backend_inline' is not a valid value` | Colab's matplotlib setting leaked into ACE-Step. The current cell 2 sets `MPLBACKEND=Agg` for the server: copy it again from the Studio. With an old copy, run `import os; os.environ["MPLBACKEND"] = "Agg"` and then cell 2 again. |
| Colab cell 1 says `NO GPU` | *Runtime → Change runtime type → T4 GPU*, then run again from cell 1. |
| `auth error 401/403` | Set `ACESTEP_API_KEY` in `.env`. |
| *Import run* says no audio run | The zip or folder must contain the run's `summary.json` (at the root or in one sub-folder). |
| A cue appears as "not in the manifest any more" | The run was made with a cue that was removed or renamed; it is skipped. |
| Id tests fail after adding a cue | The C# constant was not added: add it by hand (see `AUDIO.md` §5). |
| Approved, but Unity does not play it | Assign the clip in the `clips` list of `MusicDirector` / `SfxPlayer`. The id must match. |
| Port 8501 is busy | `python tools/audio_studio.py --server.port 8600` |
