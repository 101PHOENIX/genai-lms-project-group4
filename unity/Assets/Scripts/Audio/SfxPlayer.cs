using System.Collections.Generic;
using UnityEngine;

namespace MysteryGame.Audio
{
    /// <summary>
    /// One-shot sound effects by id (dice, alarm, chime, dialogue blips...). Clips are static assets
    /// in Assets/Audio/SFX. Long effects such as the body alarm can duck the music while they play.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class SfxPlayer : MonoBehaviour
    {
        /// <summary>Ids from the "sfx" list in audio/audio_cues.json.</summary>
        public static class Ids
        {
            public const string DiceRoll = "dice_roll";
            public const string BodyAlarm = "body_alarm";
            public const string Footsteps = "footsteps";
            public const string DoorOpen = "door_open";
            public const string ClueFound = "clue_found";
            public const string DialogueBlip = "dialogue_blip";
            public const string VerdictCorrect = "verdict_correct";
            public const string VerdictWrong = "verdict_wrong";
        }

        [SerializeField] private List<MusicDirector.CueClip> clips = new List<MusicDirector.CueClip>();
        [SerializeField] private MusicDirector music;
        [SerializeField, Range(0f, 1f)] private float volume = 0.9f;
        [Tooltip("Random pitch spread so repeated sounds (blips, footsteps) do not sound identical.")]
        [SerializeField, Range(0f, 0.2f)] private float pitchJitter = 0.05f;

        private readonly Dictionary<string, AudioClip> _byId = new Dictionary<string, AudioClip>();
        private AudioSource _src;
        private float _unduckAt = -1f;

        private void Awake()
        {
            foreach (var c in clips)
                if (!string.IsNullOrEmpty(c.cue) && c.clip != null && !_byId.ContainsKey(c.cue))
                    _byId.Add(c.cue, c.clip);
            _src = gameObject.AddComponent<AudioSource>();
            _src.playOnAwake = false;
            _src.spatialBlend = 0f;
        }

        /// <summary>Play an effect. With duckMusic the music is lowered for the clip's length.</summary>
        public void Play(string id, bool duckMusic = false)
        {
            if (!_byId.TryGetValue(id, out AudioClip clip))
            {
                Debug.LogWarning($"[SfxPlayer] no clip for '{id}'");
                return;
            }
            _src.pitch = 1f + Random.Range(-pitchJitter, pitchJitter);
            _src.PlayOneShot(clip, volume);
            if (duckMusic && music != null)
            {
                music.SetDucked(true);
                _unduckAt = Mathf.Max(_unduckAt, Time.unscaledTime + clip.length);
            }
        }

        private void Update()
        {
            if (_unduckAt < 0f || Time.unscaledTime < _unduckAt) return;
            _unduckAt = -1f;
            if (music != null) music.SetDucked(false);
        }
    }
}
