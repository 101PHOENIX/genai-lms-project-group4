using System;
using System.Collections.Generic;
using UnityEngine;
using MysteryGame.Core;

namespace MysteryGame.Audio
{
    /// <summary>
    /// Plays the pre-generated music (Team 3) and follows the CaseSession state. No network calls:
    /// clips are static assets in Assets/Audio/Music, produced by tools/generate_audio.py.
    /// Two AudioSources crossfade: between cues when the state changes, and from a clip's tail into
    /// its own head, so AI-generated loops that do not end cleanly still loop without a click.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class MusicDirector : MonoBehaviour
    {
        [Serializable]
        public struct CueClip
        {
            public string cue;
            public AudioClip clip;
        }

        [Header("Clips (ids from MusicCues)")]
        [SerializeField] private List<CueClip> clips = new List<CueClip>();

        [Header("Mix")]
        [SerializeField, Range(0f, 1f)] private float volume = 0.6f;
        [SerializeField, Range(0f, 1f)] private float duckedGain = 0.35f;
        [SerializeField, Min(0.05f)] private float duckFadeSeconds = 0.3f;

        [Header("Crossfades")]
        [SerializeField, Min(0.05f)] private float cueCrossfadeSeconds = 1.5f;
        [Tooltip("Overlap that hides the seam when a loop restarts (capped at 25% of the clip). 0 = Unity's native loop.")]
        [SerializeField, Min(0f)] private float loopCrossfadeSeconds = 2f;

        private const float Instant = 1e6f;

        private readonly Dictionary<string, AudioClip> _byCue = new Dictionary<string, AudioClip>();
        private readonly AudioSource[] _src = new AudioSource[2];
        private readonly float[] _gain = new float[2];
        private readonly float[] _target = new float[2];
        private readonly float[] _rate = new float[2];
        private int _active;
        private float _duck = 1f;
        private float _duckTarget = 1f;
        private CaseSession _session;
        private CasePhase _lastPhase;
        private int _lastRound = -1;

        /// <summary>Cue actually playing (after fallback), or null when silent.</summary>
        public string CurrentCue { get; private set; }

        /// <summary>Fired with the new cue id (null = silence). Useful for the debug overlay and the KPI log.</summary>
        public event Action<string> CueChanged;

        private void Awake()
        {
            foreach (var c in clips)
            {
                if (string.IsNullOrEmpty(c.cue) || c.clip == null) continue;
                if (_byCue.ContainsKey(c.cue)) Debug.LogWarning($"[MusicDirector] duplicate cue '{c.cue}', keeping the first");
                else _byCue.Add(c.cue, c.clip);
            }
            for (int i = 0; i < _src.Length; i++)
            {
                var s = gameObject.AddComponent<AudioSource>();
                s.playOnAwake = false;
                s.loop = false;
                s.spatialBlend = 0f;
                s.volume = 0f;
                _src[i] = s;
            }
        }

        /// <summary>Follow a case: the cue changes with its phase and round. Pass null to stop following.</summary>
        public void Bind(CaseSession session)
        {
            _session = session;
            _lastRound = -1;
            if (session != null) Sync();
        }

        /// <summary>Play a cue by id, e.g. MusicCues.Exploration on the map. The same cue does not restart.</summary>
        public void Play(string cue)
        {
            string resolved = Resolve(cue, out AudioClip clip);
            if (resolved != null && resolved == CurrentCue && _src[_active].isPlaying) return;
            if (clip == null)
            {
                if (!string.IsNullOrEmpty(cue)) Debug.LogWarning($"[MusicDirector] no clip for '{cue}', fading to silence");
                Stop();
                return;
            }
            bool nativeLoop = MusicCues.Loops(resolved) && loopCrossfadeSeconds <= 0f;
            StartOnOther(clip, cueCrossfadeSeconds, nativeLoop);
            SetCue(resolved);
        }

        /// <summary>Fade everything out.</summary>
        public void Stop()
        {
            FadeTo(0, 0f, cueCrossfadeSeconds);
            FadeTo(1, 0f, cueCrossfadeSeconds);
            SetCue(null);
        }

        /// <summary>Lower the music under the alarm, stingers or Host lines.</summary>
        public void SetDucked(bool ducked) => _duckTarget = ducked ? duckedGain : 1f;

        private void Update()
        {
            if (_session != null) Sync();
            KeepLooping();
            ApplyGains(Time.unscaledDeltaTime);
        }

        private void Sync()
        {
            if (_session.Phase == _lastPhase && _session.Round == _lastRound) return;
            _lastPhase = _session.Phase;
            _lastRound = _session.Round;
            Play(MusicCues.ForState(_lastPhase, _lastRound));
        }

        private string Resolve(string cue, out AudioClip clip)
        {
            for (string c = cue; c != null; c = MusicCues.Fallback(c))
                if (_byCue.TryGetValue(c, out clip)) return c;
            clip = null;
            return null;
        }

        private void KeepLooping()
        {
            if (CurrentCue == null) return;
            var s = _src[_active];
            if (s.clip == null || s.loop) return;
            if (MusicCues.Loops(CurrentCue))
            {
                float overlap = Mathf.Min(loopCrossfadeSeconds, s.clip.length * 0.25f);
                if (s.isPlaying && s.clip.length - s.time <= overlap) StartOnOther(s.clip, overlap, false);
            }
            else if (!s.isPlaying)
            {
                string next = MusicCues.After(CurrentCue);
                SetCue(null);
                if (next != null) Play(next);
            }
        }

        private void StartOnOther(AudioClip clip, float fadeSeconds, bool nativeLoop)
        {
            int next = 1 - _active;
            var s = _src[next];
            s.Stop();
            s.clip = clip;
            s.loop = nativeLoop;
            s.time = 0f;
            s.Play();
            _gain[next] = 0f;
            FadeTo(next, 1f, fadeSeconds);
            FadeTo(_active, 0f, fadeSeconds);
            _active = next;
        }

        private void FadeTo(int i, float target, float seconds)
        {
            _target[i] = target;
            _rate[i] = seconds > 0f ? 1f / seconds : Instant;
        }

        private void ApplyGains(float dt)
        {
            _duck = Mathf.MoveTowards(_duck, _duckTarget, dt / duckFadeSeconds);
            for (int i = 0; i < _src.Length; i++)
            {
                _gain[i] = Mathf.MoveTowards(_gain[i], _target[i], _rate[i] * dt);
                var s = _src[i];
                s.volume = _gain[i] * _duck * volume;
                if (_gain[i] <= 0f && _target[i] <= 0f && s.isPlaying) s.Stop();
            }
        }

        private void SetCue(string cue)
        {
            if (cue == CurrentCue) return;
            CurrentCue = cue;
            CueChanged?.Invoke(cue);
        }
    }
}
