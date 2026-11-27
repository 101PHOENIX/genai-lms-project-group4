"""Audio Studio: a local web app for the game's audio lifecycle.

    python tools/audio_studio.py            # opens http://localhost:8501

1. Manifest & generation: edit audio/audio_cues.json, add cues, generate takes locally
   (acestep / mock), export Colab cells, import a Colab/Drive run or Stable Audio 3 / Freesound files.
2. Review: automatic technical filter (tools/audio_qc.py), players with loop mode,
   one-click approve / reject with reasons, edit a prompt and regenerate.
3. Apply: promote approved takes into Unity, update audio/provenance.json, ITERATION_LOG.md
   and the inventory in docs/AUDIO.md.

Needs requirements-audio.txt (streamlit, numpy, scipy, soundfile). Logic lives in audio_ops.py.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))


def _launched_by_streamlit() -> bool:
    # `streamlit run` and AppTest import streamlit before executing this file; plain `python` does not.
    return "streamlit" in sys.modules


if __name__ == "__main__" and not _launched_by_streamlit():
    # `python tools/audio_studio.py [streamlit flags]` -> `streamlit run tools/audio_studio.py [flags]`
    try:
        import streamlit  # noqa: F401
    except ImportError:
        sys.exit("Streamlit is not installed: pip install -r requirements-audio.txt")
    sys.exit(subprocess.call([sys.executable, "-m", "streamlit", "run", __file__, *sys.argv[1:]]))

import html  # noqa: E402
import json  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import audio_ops as ops  # noqa: E402
import audio_qc as qc  # noqa: E402
import generate_audio as ga  # noqa: E402

STATUS_BADGE = {"pass": ":green-badge[PASS]", "warn": ":orange-badge[WARN]", "fail": ":red-badge[FAIL]"}
DECISION_BADGE = {"approved": ":green-badge[:material/check: approved]",
                  "rejected": ":red-badge[:material/close: rejected]",
                  "superseded": ":gray-badge[superseded]"}


# --------------------------------------------------------------------------- state helpers

def flash(msg: str, kind: str = "success") -> None:
    st.session_state.setdefault("flash", []).append((kind, msg))


def show_flash() -> None:
    for kind, msg in st.session_state.pop("flash", []):
        getattr(st, kind)(msg)


def unity_root() -> Path:
    p = Path(st.session_state.get("unity_root", "unity/Assets/Audio")).expanduser()
    return p if p.is_absolute() else ops.ROOT / p


def job_running() -> bool:
    job = st.session_state.get("job")
    return bool(job and job["proc"].poll() is None)


def launch_job(provider: str, cue_ids: list[str], candidates: int, out_dir: Path, label: str) -> None:
    if job_running():
        flash("A generation job is already running; wait for it to finish.", "warning")
        return
    if provider == "acestep":
        acestep_status.clear()
        problem = acestep_status(st.session_state.get("acestep_url", ""))
        if problem:
            flash(f"Not started: {problem}. Start the server or use Run on Google Colab in the Generate section.",
                  "warning")
            return
    cmd =ops.generate_command(provider, cue_ids, candidates, out_dir)
    env = {"ACESTEP_URL": st.session_state.get("acestep_url", "")} if provider == "acestep" else {}
    proc, log = ops.start_generation(cmd, out_dir, {k: v for k, v in env.items() if v})
    st.session_state.job = {"proc": proc, "log": log, "out": out_dir, "label": label, "cmd": cmd}
    flash(f"Started: {label} -> {ops.rel(out_dir)}", "info")


# --------------------------------------------------------------------------- sidebar

def sidebar() -> None:
    with st.sidebar:
        st.header("Audio Studio")
        st.text_input("Unity audio folder", key="unity_root",
                      help="Approved takes go to <folder>/Music and <folder>/SFX. Relative paths start at the repo "
                           "root, e.g. unity/Assets/Audio or AudioTest/AudioTest/Assets.")
        root = unity_root()
        st.caption(f"{'Exists' if root.is_dir() else 'Will be created'}: `{root}`")
        st.text_input("ACE-Step URL", key="acestep_url",
                      help="REST server for --provider acestep (local GPU or a tunnel to Colab).")
        st.toggle("Apply on approve", key="auto_apply",
                  help="Approving a take immediately copies it into Unity and updates provenance and the docs.")
        st.divider()
        job = st.session_state.get("job")
        if job:
            code = job["proc"].poll()
            state = "running" if code is None else ("done" if code == 0 else f"finished with exit code {code}")
            st.markdown(f"**Job:** {job['label']} · {state}")
        st.caption(f"Manifest: `{ops.rel(ops.MANIFEST)}` · Review: `{ops.rel(ops.REVIEW)}`")


# --------------------------------------------------------------------------- tab 1: manifest & generation

def _cue_frame(cues: list[dict], kind: str) -> pd.DataFrame:
    cols = ["id", "prompt", "duration_s", "bpm", "key", "loop"] if kind == "music" else ["id", "prompt", "duration_s", "loop"]
    return pd.DataFrame([{c: cue.get(c) for c in cols} for cue in cues], columns=cols)


def _frame_to_cues(df: pd.DataFrame, kind: str) -> list[dict]:
    out = []
    for rec in df.to_dict("records"):
        rec = {k: (None if isinstance(v, float) and v != v else v) for k, v in rec.items()}
        out.append(ops.normalize_cue(kind, rec))
    return out


def manifest_editor(manifest: dict) -> None:
    st.subheader("Manifest")
    st.caption(f"`audio/audio_cues.json` · version **{manifest.get('version')}** · ids must match "
               "`MusicCues.cs` and `SfxPlayer.Ids`.")
    with st.form("manifest_form"):
        c1, c2 = st.columns([1, 5])
        version = c1.text_input("Version", manifest.get("version", ""))
        style = c2.text_area("Music style (prefix of every music prompt)", manifest.get("music_style", ""), height=68)
        loop_rules = st.text_area("Loop rules (appended to looping music prompts)", manifest.get("loop_rules", ""), height=68)
        st.markdown("**Music**")
        music = st.data_editor(
            _cue_frame(manifest.get("music", []), "music"), key="music_editor", hide_index=True,
            width="stretch", disabled=["id"], num_rows="fixed",
            column_config={"prompt": st.column_config.TextColumn(width="large"),
                           "duration_s": st.column_config.NumberColumn("duration (s)", min_value=0.1, step=0.5),
                           "bpm": st.column_config.NumberColumn(min_value=30, max_value=300, step=1),
                           "loop": st.column_config.CheckboxColumn()})
        st.markdown("**SFX**")
        sfx = st.data_editor(
            _cue_frame(manifest.get("sfx", []), "sfx"), key="sfx_editor", hide_index=True,
            width="stretch", disabled=["id"], num_rows="fixed",
            column_config={"prompt": st.column_config.TextColumn(width="large"),
                           "duration_s": st.column_config.NumberColumn("duration (s)", min_value=0.1, step=0.1),
                           "loop": st.column_config.CheckboxColumn()})
        if st.form_submit_button("Save manifest", type="primary"):
            new = dict(manifest)
            new.update(version=version.strip(), music_style=style.strip(), loop_rules=loop_rules.strip(),
                       music=_frame_to_cues(music, "music"), sfx=_frame_to_cues(sfx, "sfx"))
            errors = ops.save_manifest(new)
            if errors:
                st.error("Not saved:\n\n- " + "\n- ".join(errors))
            else:
                flash("Manifest saved.")
                st.rerun()


def add_cue_form(manifest: dict) -> None:
    with st.expander("Add a music track or SFX", icon=":material/add:"):
        with st.form("add_cue", clear_on_submit=False):
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            cid = c1.text_input("Id", placeholder="door_slam", help="Lowercase letters and underscores.")
            kind = c2.radio("Kind", ["music", "sfx"], horizontal=True)
            duration = c3.number_input("Duration (s)", min_value=0.1, max_value=600.0, value=3.0, step=0.5)
            loop = c4.radio("Playback", ["one-shot", "loop"], horizontal=True) == "loop"
            c5, c6 = st.columns(2)
            bpm = c5.number_input("BPM (music, 0 = none)", min_value=0, max_value=300, value=0)
            key = c6.text_input("Key (music, optional)", placeholder="A minor")
            prompt = st.text_area("Prompt", placeholder="What it should sound like. No artist, song or franchise names.")
            add_cs = st.checkbox("Add the C# constant (MusicCues / SfxPlayer.Ids) so the id tests keep passing", value=True)
            if st.form_submit_button("Add cue", type="primary"):
                new, errors = ops.add_cue(manifest, kind, {"id": cid, "prompt": prompt, "duration_s": duration,
                                                           "loop": loop, "bpm": bpm, "key": key})
                if errors:
                    st.error("Not added:\n\n- " + "\n- ".join(errors))
                    return
                ops.save_manifest(new)
                flash(f"Added {kind} cue '{cid.strip()}'.")
                if add_cs:
                    try:
                        flash(ops.add_csharp_constant(kind, cid.strip()), "info")
                    except (OSError, ValueError) as e:
                        flash(f"C# constant not added: {e}", "warning")
                st.rerun()


def generation_panel(manifest: dict) -> None:
    st.subheader("Generate")
    cues = ops.all_cues(manifest)
    provider = st.segmented_control("Provider", ["acestep", "mock", "stable-audio", "freesound"], default="acestep",
                                    key="gen_provider")
    if provider == "freesound":
        import_takes_form(manifest, provider)
        return
    if provider is None:
        return
    music_only = provider == "acestep"
    sfx_only = provider == "stable-audio"
    if sfx_only:
        st.caption("Stable Audio 3 Small-SFX renders SFX only. Generate the takes on a free Colab GPU (below), or "
                   "make them by hand in the Stable Audio UI and import the files.")
    kind = "music" if music_only else "sfx" if sfx_only else None
    choices = [c for c, v in cues.items() if kind is None or v["kind"] == kind]
    picked = st.multiselect("Cues", choices, format_func=lambda c: f"{c} ({cues[c]['kind']})",
                            placeholder="All" + (f" {kind} cues" if kind else " cues"), key=f"gen_cues_{provider}")
    c1, c2 = st.columns([1, 3])
    candidates = c1.number_input("Candidates per cue", 1, 10, 3, key=f"gen_candidates_{provider}")
    default_out = ops.rel(ops.default_run_dir(provider))
    out = c2.text_input("Output folder", value=default_out, key=f"gen_out_{provider}")
    server_down = None
    if music_only:
        st.caption("ACE-Step renders music only. For SFX use Stable Audio 3 or Freesound and import the files.")
        url = st.session_state.get("acestep_url", "")
        server_down = acestep_status(url)
        s1, s2 = st.columns([5, 1])
        if server_down:
            s1.warning(f"**Generate locally is off:** {server_down}.  \nUse **Run on Google Colab** (recommended, "
                       "free GPU), or start a local server: in the ACE-Step-1.5 folder run `uv run acestep-api` "
                       "(NVIDIA GPU with about 4 GB of VRAM), then press *Check again*. "
                       "To use a server on another machine, set **ACE-Step URL** in the sidebar.",
                       icon=":material/cloud_off:")
        else:
            s1.success(f"ACE-Step server ready at {url}", icon=":material/check_circle:")
        if s2.button("Check again", icon=":material/refresh:"):
            acestep_status.clear()
            st.rerun()
    local, colab = st.columns(2)
    if sfx_only:
        local.caption("Local generation needs the stable-audio-3 environment (PyTorch); use Colab.")
    elif local.button("Generate locally", type="primary", icon=":material/play_arrow:",
                      disabled=job_running() or bool(server_down)):
        out_dir = Path(out) if Path(out).is_absolute() else ops.ROOT / out
        launch_job(provider, picked, candidates, out_dir, f"{provider} × {candidates} ({', '.join(picked) or 'all'})")
        st.rerun()
    if provider in ops.COLAB_PROVIDERS:
        with colab.popover("Run on Google Colab", icon=":material/cloud:", width="stretch",
                           type="primary" if sfx_only else "secondary"):
            colab_panel(provider, picked, candidates, Path(out).name)
    job_log()
    import_run_form()
    if sfx_only:
        with st.expander("Or import files made by hand in the Stable Audio UI", icon=":material/upload:"):
            import_takes_form(manifest, provider)


def colab_panel(provider: str, picked: list[str], candidates: int, run_name: str) -> None:
    st.markdown("Paste each block into its own Colab cell (GPU runtime) and run them in order. The run is "
                f"zipped into `MyDrive/audio_runs/{run_name}.zip`; import it with *Import a run from Colab / "
                "Google Drive* when it is done.")
    if provider == "stable-audio":
        st.info("Before the first run: log in at huggingface.co, accept the licence of "
                "**stabilityai/stable-audio-3-small-sfx**, and create a *read* access token "
                "(Settings → Access Tokens). Cell 2 asks for it, or reads a Colab secret named `HF_TOKEN`.",
                icon=":material/key:")
    cells = ops.colab_cells(ops.MANIFEST.read_text(encoding="utf-8"), picked, candidates, run_name, provider=provider)
    for title, code in cells:
        st.markdown(f"**{title}**")
        long = code.count("\n") > 60
        st.code(code, language="python", height=220 if long else "content")
        if long:
            st.caption("Long cell: use the copy icon at the top right of the box to copy all of it.")


@st.cache_data(ttl=15, show_spinner=False)
def acestep_status(url: str) -> str | None:
    return ops.acestep_status(url)


@st.fragment(run_every=2)
def job_log() -> None:
    job = st.session_state.get("job")
    if not job:
        return
    code = job["proc"].poll()
    try:
        lines = job["log"].read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
    except OSError:
        lines = []
    with st.container(border=True):
        state = "running…" if code is None else ("finished" if code == 0 else f"finished with exit code {code}")
        st.markdown(f"**{job['label']}** · {state}")
        st.code("\n".join(lines) or "(waiting for output)", language="log")
        if code is not None and (job["out"] / "summary.json").is_file():
            if st.button("Review this run", key="review_job", icon=":material/arrow_forward:"):
                st.session_state.review_run = job["out"].name
                st.session_state.pop("job")
                st.rerun(scope="app")


def import_run_form() -> None:
    with st.expander("Import a run from Colab / Google Drive", icon=":material/download:"):
        up = st.file_uploader("Zipped run folder (.zip)", type=["zip"], key="run_zip")
        folder = st.text_input("…or a local folder (e.g. a synced Google Drive folder)", key="run_folder")
        if st.button("Import run", disabled=not (up or folder.strip())):
            try:
                if up:
                    with tempfile.TemporaryDirectory() as d:
                        z = Path(d) / up.name
                        z.write_bytes(up.getvalue())
                        dest = ops.import_run_zip(z)
                else:
                    dest = ops.import_run_folder(Path(folder.strip().strip('"')))
            except (ValueError, OSError) as e:
                st.error(f"Import failed: {e}")
                return
            st.session_state.review_run = dest.name
            flash(f"Imported {ops.rel(dest)}. It is selected in the Review tab.")
            st.rerun()


def copy_button(label: str, text: str) -> None:
    """A button that puts `text` on the clipboard (Clipboard API, with a fallback for older browsers)."""
    payload = json.dumps(text).replace("</", "<\\/")
    # The text comes from our own manifest, never from viewers, so embedding it in the iframe is safe.
    st.iframe(f"""
<button id="b" style="font:14px/1 system-ui,sans-serif;padding:7px 12px;border-radius:8px;cursor:pointer;
  border:1px solid rgba(128,128,128,.45);background:transparent;color:#888;white-space:nowrap">📋 {html.escape(label)}</button>
<script>
const text = {payload}, b = document.getElementById("b"), label = b.textContent;
function done(ok) {{ b.textContent = ok ? "✓ Copied" : "Select and copy manually"; setTimeout(() => b.textContent = label, 1500); }}
function fallback() {{
  const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select();
  let ok = false; try {{ ok = document.execCommand("copy"); }} catch (e) {{}} t.remove(); done(ok);
}}
b.onclick = () => navigator.clipboard ? navigator.clipboard.writeText(text).then(() => done(true), fallback) : fallback();
</script>""", height=42)


def prompt_card(manifest: dict, cue: dict, provider: str, compact: bool = False) -> None:
    """The exact prompt and duration to paste into the Stable Audio 3 UI, each with a copy button."""
    prompt = ga.build_prompt(manifest, ops._cue_obj(cue))
    duration = f"{float(cue['duration_s']):g}"
    with st.container(border=True):
        if compact:
            st.markdown(f"**{cue['id']}** · {duration} s")
        else:
            st.markdown(f"**Paste into {'Stable Audio 3' if provider == 'stable-audio' else 'your Freesound search'}**")
        st.code(prompt, language=None, wrap_lines=True)
        b1, b2, _ = st.columns([2, 2, 3])
        with b1:
            copy_button("Copy prompt", prompt)
        with b2:
            copy_button(f"Copy duration ({duration} s)", duration)
        if not compact and provider == "stable-audio":
            st.caption("Make 2-3 takes, download them as WAV and upload them below.")


def import_takes_form(manifest: dict, provider: str) -> None:
    defaults = ops.IMPORTERS[provider]
    cues = ops.all_cues(manifest)
    st.caption("Make the takes in the Stable Audio 3 Small SFX UI or download them from Freesound, then import "
               "them here: they get the same technical filter and review as generated runs.")
    # Stable Audio 3 Small SFX only makes effects; Freesound can supply anything.
    ids = [c for c in cues if provider != "stable-audio" or cues[c]["kind"] == "sfx"]
    cid = st.selectbox("Cue", ids, key=f"import_cue_{provider}",
                       format_func=lambda c: f"{c} ({cues[c]['kind']}, {cues[c]['duration_s']} s)")
    if cid:
        prompt_card(manifest, cues[cid], provider)
    if provider == "stable-audio" and st.toggle("Show all SFX prompts (for a batch session in the Stable Audio UI)",
                                                key="all_sfx_prompts"):
        for sid in ids:
            prompt_card(manifest, cues[sid], provider, compact=True)
    with st.form(f"import_{provider}"):
        files = st.file_uploader("Audio files (one per take)", type=sorted(s.lstrip(".") for s in ops.IMPORT_SUFFIXES),
                                 accept_multiple_files=True)
        c1, c2 = st.columns(2)
        source = c1.text_input("Source", defaults["source"], help="For Freesound: author and sound id.")
        licence = c2.text_input("Licence", defaults["licence"])
        if st.form_submit_button("Import takes", type="primary"):
            try:
                run = ops.import_external_takes(cues[cid], [(f.name, f.getvalue()) for f in files or []],
                                                provider, source, licence, manifest)
            except ValueError as e:
                st.error(str(e))
                return
            st.session_state.review_run = run.name
            flash(f"Imported {len(files)} take(s) into {ops.rel(run)}. It is selected in the Review tab.")
            st.rerun()


# --------------------------------------------------------------------------- tab 2: review

def _on_approve(run: str, row: dict, res) -> None:
    review = ops.load_review()
    d = ops.approve(review, run, row, res)
    if st.session_state.get("auto_apply"):
        report = ops.apply_changes(ops.load_manifest(), review, unity_root())
        flash(f"Approved {row['cue']} take {row['candidate']}. " + " · ".join(report))
    else:
        ops.save_review(review)
        flash(f"Approved {d['cue']} take {d['take']}. Apply it from the Apply tab.")


def _on_reject(run: str, row: dict, res, key: str) -> None:
    reasons = st.session_state.get(key) or []
    review = ops.load_review()
    ops.reject(review, run, row, reasons, res)
    ops.save_review(review)
    flash(f"Rejected {row['cue']} take {row['candidate']}" + (f": {', '.join(reasons)}" if reasons else "."), "info")


def _on_undo(run: str, file: str) -> None:
    review = ops.load_review()
    ops.undo(review, run, file)
    ops.save_review(review)


def _on_trim(run_dir: Path, files: list[str]) -> None:
    made, failed = [], []
    for f in files:
        try:
            row = ops.trim_take(run_dir, f)
            made.append(f"{f} → {row['file']} (−{row['trim_s']['head']} s head, −{row['trim_s']['tail']} s tail)")
        except (ValueError, RuntimeError) as e:
            failed.append(str(e))
    if made:
        flash("Trimmed, new takes added to this run and analyzed:\n\n- " + "\n- ".join(made))
    if failed:
        flash("Not trimmed:\n\n- " + "\n- ".join(failed), "warning")


def metrics_line(res) -> str:
    parts = [STATUS_BADGE.get(res.status, res.status), f"score **{res.score}**"]
    if res.lufs is not None:
        parts.append(f"{res.lufs} LUFS")
    if res.peak_dbfs is not None:
        parts.append(f"peak {res.peak_dbfs} dBFS")
    if res.duration_s is not None:
        parts.append(f"{res.duration_s:.1f}/{res.requested_s:g} s" if res.requested_s else f"{res.duration_s:.1f} s")
    if res.head_silence_s is not None:
        parts.append(f"silence {res.head_silence_s}s / {res.tail_silence_s}s")
    if res.seam:
        parts.append(f"seam {res.seam['level_step_db']} dB · click ×{res.seam['click_ratio']} · "
                     f"timbre {res.seam['spectral_distance']}")
    return " · ".join(parts)


def take_row(run_dir: Path, row: dict, res, cue: dict, decision: dict | None, summary: dict) -> None:
    run, kid = run_dir.name, f"{run_dir.name}|{row['file']}"
    with st.container(border=True):
        head, badge = st.columns([5, 2])
        head.markdown(f"**Take {row['candidate']}**" + (" · ✂️ trimmed" if row.get("edit") == "trim" else "")
                      + f" · `{row['file']}`"
                      + (f" · seed {row['seed']}" if row.get("seed") is not None else "")
                      + (f" · {row['latency_s']} s" if row.get("latency_s") is not None else ""))
        if decision:
            badge.markdown(DECISION_BADGE.get(decision["status"], decision["status"])
                           + (f" {', '.join(decision['reasons'])}" if decision.get("reasons") else ""))
        st.markdown(metrics_line(res))
        for i in res.issues:
            st.caption(f"{'⛔' if i.severity == 'fail' else '⚠️'} {i.message}")
        if row.get("derived_from"):
            t = row.get("trim_s", {})
            st.caption(f"✂️ Trimmed from `{row['derived_from']}`: −{t.get('head')} s at the start, "
                       f"−{t.get('tail')} s at the end (originally {row.get('original_requested_s')} s).")
        elif any(i.code == "silence" for i in res.issues):
            done = ops.trimmed_of(summary, row["file"])
            if done:
                st.caption(f"✂️ Trimmed version: `{done['file']}` (take {done['candidate']})")
            else:
                st.button("Trim silence", key=f"trim|{kid}", icon=":material/content_cut:",
                          help="Cut the silent head/tail into a new take (WAV) of this run; this file is kept.",
                          on_click=_on_trim, args=(run_dir, [row["file"]]))
        play, actions = st.columns([3, 2])
        loop = play.toggle("Loop", value=bool(cue.get("loop")), key=f"loop|{kid}")
        path = run_dir / row["file"]
        if path.is_file():
            play.audio(str(path), loop=loop)
        with actions:
            a, u = st.columns(2)
            a.button("Approve & promote" if st.session_state.get("auto_apply") else "Approve", key=f"ok|{kid}",
                     type="primary", icon=":material/check:", on_click=_on_approve, args=(run, row, res),
                     disabled=bool(decision and decision["status"] == "approved"))
            if decision:
                u.button("Undo", key=f"undo|{kid}", icon=":material/undo:", on_click=_on_undo, args=(run, row["file"]))
            pk = f"why|{kid}"
            st.pills("Reject reasons", ops.REJECT_REASONS, selection_mode="multi", key=pk, label_visibility="collapsed")
            st.button("Reject", key=f"no|{kid}", icon=":material/close:", on_click=_on_reject, args=(run, row, res, pk))


def regenerate_box(manifest: dict, cue: dict) -> None:
    with st.expander("Edit prompt & regenerate", icon=":material/edit:"):
        kid = cue["id"]
        prompt = st.text_area("Cue prompt (saved to the manifest)", cue.get("prompt", ""), key=f"prompt|{kid}")
        st.caption("Sent as: " + ga.build_prompt(manifest, ops._cue_obj({**cue, "prompt": prompt})))
        c1, c2, c3 = st.columns(3)
        providers = ["acestep", "mock"] if cue["kind"] == "music" else ["mock"]
        provider = c1.selectbox("Provider", providers, key=f"regen_p|{kid}")
        n = c2.number_input("Candidates", 1, 10, 3, key=f"regen_n|{kid}")
        if c3.button("Save prompt", key=f"save_p|{kid}"):
            ops.save_manifest(ops.set_prompt(manifest, kid, prompt))
            flash(f"Prompt of {kid} saved.")
            st.rerun()
        if st.button("Save & regenerate", key=f"regen|{kid}", type="primary", icon=":material/refresh:",
                     disabled=job_running()):
            errors = ops.save_manifest(ops.set_prompt(manifest, kid, prompt))
            if errors:
                st.error("; ".join(errors))
                return
            launch_job(provider, [kid], n, ops.default_run_dir(provider), f"regenerate {kid} ({provider} × {n})")
            st.rerun()
        if cue["kind"] == "sfx":
            st.caption("Real SFX come from Stable Audio 3 / Freesound: import new takes in the Generate tab.")


def review_tab(manifest: dict) -> None:
    runs = ops.list_runs()
    if not runs:
        st.info("No audio runs in baselines/ yet. Generate or import one in the first tab.")
        return
    names = [r.name for r in runs]
    if st.session_state.get("review_run") not in names:
        st.session_state.review_run = names[0]
    c1, c2, c3 = st.columns([3, 2, 1])
    run = c1.selectbox("Run", names, key="review_run")
    run_dir = ops.BASELINES / run
    summary = ops.load_summary(run_dir)
    cues = ops.all_cues(manifest)
    with st.spinner("Analyzing takes…"):
        results = qc.analyze_run(run_dir, {c: bool(v.get("loop")) for c, v in cues.items()},
                                 force=st.session_state.pop("force_qc", False))
    if c3.button("Re-analyze", icon=":material/refresh:"):
        st.session_state.force_qc = True
        st.rerun()
    counts = {s: sum(r.status == s for r in results.values()) for s in ("pass", "warn", "fail")}
    c2.markdown(f"**{summary.get('provider')}** · {summary.get('runs', len(summary['rows']))} takes · "
                f"success {summary.get('success_rate')} · p50 {summary.get('latency_p50_s')} s  \n"
                f"{STATUS_BADGE['pass']} {counts['pass']} {STATUS_BADGE['warn']} {counts['warn']} "
                f"{STATUS_BADGE['fail']} {counts['fail']}")
    if summary.get("aborted"):
        st.warning(f"Run aborted: {summary['aborted']}")
    if summary.get("reconstructed"):
        st.caption(f"ℹ️ summary.json was reconstructed: {summary['reconstructed'].get('reason', '')}")
    to_trim = ops.trim_candidates(run_dir, results)
    if to_trim:
        t1, t2 = st.columns([3, 2])
        t1.info(f"{len(to_trim)} take(s) fail or warn on silent head/tail. Trimming makes a new WAV take next to "
                "each one (originals kept) and analyzes it.", icon=":material/content_cut:")
        t2.button(f"Trim silence on {len(to_trim)} take(s)", icon=":material/content_cut:", type="primary",
                  on_click=_on_trim, args=(run_dir, to_trim))

    review = ops.load_review()
    run_cues = list(dict.fromkeys(r["cue"] for r in summary["rows"]))
    f1, f2 = st.columns([3, 1])
    shown = f1.multiselect("Cues", run_cues, placeholder="All cues in this run", key=f"cue_filter|{run}")
    undecided = f2.toggle("Undecided only", key="undecided_only")
    win = ops.winners(review)
    for cid in shown or run_cues:
        cue = cues.get(cid)
        rows = [r for r in summary["rows"] if r["cue"] == cid]
        if cue is None:
            st.warning(f"{cid}: not in the manifest any more; skipped.")
            continue
        ok = [r for r in rows if r.get("ok") and r["file"] in results]
        if undecided:
            ok = [r for r in ok if ops.decision_key(run, r["file"]) not in review["decisions"]]
        order = {"pass": 0, "warn": 1, "fail": 2}
        ok.sort(key=lambda r: (order[results[r["file"]].status], -results[r["file"]].score))
        good = [r for r in ok if results[r["file"]].status != "fail"]
        bad = [r for r in ok if results[r["file"]].status == "fail"]
        w = win.get(cid)
        st.markdown(f"### {cid}")
        st.caption(f"{cue['kind']} · {'loop' if cue.get('loop') else 'one-shot'} · {cue['duration_s']} s"
                   + (f" · current winner: {w['run']} take {w['take']}" if w else " · no winner yet"))
        for r in good:
            take_row(run_dir, r, results[r["file"]], cue,
                     review["decisions"].get(ops.decision_key(run, r["file"])), summary)
        if bad:
            with st.expander(f"Auto-discarded ({len(bad)})", icon=":material/block:"):
                for r in bad:
                    take_row(run_dir, r, results[r["file"]], cue,
                             review["decisions"].get(ops.decision_key(run, r["file"])), summary)
        for r in rows:
            if not r.get("ok"):
                st.caption(f"Take {r['candidate']} failed to generate: {r.get('error')}")
        regenerate_box(manifest, cue)


# --------------------------------------------------------------------------- tab 3: apply

def apply_tab(manifest: dict) -> None:
    review = ops.load_review()
    prov = ops.read_json(ops.PROVENANCE, {})
    win = ops.winners(review)
    root = unity_root()
    rows = []
    for cid, c in ops.all_cues(manifest).items():
        d, p = win.get(cid), prov.get(cid, {})
        rows.append({"cue": cid, "kind": c["kind"],
                     "approved take": f"{d['run']} / {d['take']}" if d else "",
                     "in Unity": "pending" if d and ops.needs_promotion(d, root) else ("yes" if d or p else "no"),
                     "provenance": f"{p.get('provider', '')} · {p.get('licence', '')}" if p else "",
                     "QC": d.get("qc_score") if d else p.get("qc_score")})
    pending = [r["cue"] for r in rows if r["in Unity"] == "pending"]
    st.subheader("Apply changes & update project")
    st.markdown(f"Promotes approved takes into `{ops.rel(root)}/Music|SFX/<cue>.<ext>`, updates "
                "`audio/provenance.json`, the run rows and take-level section of `ITERATION_LOG.md`, and the "
                "inventory in `docs/AUDIO.md`. Safe to run again.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(f"{len(pending)} approved take(s) waiting for promotion"
               + (f": {', '.join(pending)}" if pending else ""))
    if st.button("Apply changes & update project", type="primary", icon=":material/publish:"):
        report = ops.apply_changes(manifest, review, root)
        for line in report:
            (st.error if line.startswith("FAILED") else st.success)(line)
    rejected = [d for d in review["decisions"].values() if d["status"] == "rejected"]
    if rejected:
        with st.expander(f"Rejected takes ({len(rejected)})"):
            st.dataframe(pd.DataFrame([{"run": d["run"], "cue": d["cue"], "take": d["take"],
                                        "reasons": ", ".join(d["reasons"]), "QC": d.get("qc_score")}
                                       for d in rejected]), hide_index=True, width="stretch")
    with st.expander("Inventory preview (docs/AUDIO.md)"):
        st.markdown(ops.inventory_markdown(manifest, review, prov))


# --------------------------------------------------------------------------- main

def main() -> None:
    st.set_page_config(page_title="Audio Studio", page_icon=":material/graphic_eq:", layout="wide")
    st.session_state.setdefault("unity_root", ops.rel(ops.UNITY_AUDIO))
    st.session_state.setdefault("acestep_url", os.environ.get("ACESTEP_URL", "http://127.0.0.1:8001"))
    st.session_state.setdefault("auto_apply", True)
    ga.load_dotenv(ops.ROOT / ".env")
    sidebar()
    show_flash()
    try:
        manifest = ops.load_manifest()
    except ValueError as e:
        st.error(f"audio/audio_cues.json is invalid: {e}")
        return
    t1, t2, t3 = st.tabs([":material/library_music: Manifest & generation", ":material/hearing: Review",
                          ":material/publish: Apply to Unity & docs"])
    with t1:
        manifest_editor(manifest)
        add_cue_form(manifest)
        st.divider()
        generation_panel(manifest)
    with t2:
        review_tab(manifest)
    with t3:
        apply_tab(manifest)


main()
