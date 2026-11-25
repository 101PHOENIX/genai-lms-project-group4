using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using MysteryGame.Core;

namespace MysteryGame.Net
{
    /// <summary>
    /// Option B live images (Pollinations) with the constraints we measured on 2026-11-23:
    ///   - free tier = 1 image / 45 s per IP (HTTP 402 "FREE_LIMIT" otherwise)
    ///   - so we PREFETCH: as soon as the case file arrives, enqueue the crime scene first,
    ///     then every key clue, one request every <see cref="minIntervalSeconds"/>.
    ///   - every request has a timeout and falls back to a local generic image.
    /// UI asks <see cref="TryGet"/> when a clue is discovered; if not ready yet it shows
    /// the fallback and swaps in the real image via <see cref="Ready"/> when it lands.
    /// </summary>
    public sealed class LiveImageQueue : MonoBehaviour
    {
        [Header("Pollinations")]
        [SerializeField] private string endpoint = "https://image.pollinations.ai/prompt/";
        [Tooltip("Leave empty for free tier. A pollen key lifts the 45 s limit.")]
        [SerializeField] private string apiKey = "";
        [SerializeField] private float minIntervalSeconds = 46f;
        [SerializeField] private int timeoutSeconds = 40;
        [SerializeField] private int size = 768;

        [Header("Style (Team 2 owns these strings)")]
        [TextArea] [SerializeField] private string crimeSceneStyle =
            "2.5D stylized anime visual novel illustration, bold black ink outlines, sharp cel shading with subtle halftone dot texture, vibrant high-contrast colors, mysterious atmosphere, ";
        [TextArea] [SerializeField] private string clueStyle =
            "2D stylized anime visual novel evidence photo, bold black ink outlines, sharp cel shading with subtle halftone dot texture, high-contrast lighting. Close-up top-down view of ";
        [SerializeField] private string suffix = ", no text, no labels, no watermark";

        [Header("Offline fallback")]
        [SerializeField] private Texture2D fallbackCrimeScene;
        [SerializeField] private Texture2D fallbackClue;

        public const string CrimeSceneKey = "__crime_scene__";

        /// <summary>Fired when an image (real or fallback) is available for a key.</summary>
        public event Action<string, Texture2D, bool> Ready; // (key, texture, isLive)

        private readonly Queue<(string key, string prompt)> _pending = new Queue<(string, string)>();
        private readonly Dictionary<string, Texture2D> _done = new Dictionary<string, Texture2D>();
        private Coroutine _worker;
        private float _lastRequestTime = -999f;

        // --- metrics for the KPI log (Team 5) ---
        public int Requested { get; private set; }
        public int Succeeded { get; private set; }
        public List<float> Latencies { get; } = new List<float>();

        /// <summary>Call right after the case file is parsed. Crime scene goes first (it is shown at discovery).</summary>
        public void PrefetchCase(CaseFile c, int seed)
        {
            _pending.Clear();
            _done.Clear();
            _pending.Enqueue((CrimeSceneKey, crimeSceneStyle + c.crime_scene_prompt + suffix));
            foreach (var k in c.key_clues)
                _pending.Enqueue((k.id, clueStyle + k.image_prompt + suffix));
            _seed = seed;
            if (_worker == null) _worker = StartCoroutine(Work());
        }

        private int _seed;

        public bool TryGet(string key, out Texture2D tex) => _done.TryGetValue(key, out tex);

        public Texture2D Fallback(string key) => key == CrimeSceneKey ? fallbackCrimeScene : fallbackClue;

        private IEnumerator Work()
        {
            while (_pending.Count > 0)
            {
                float wait = (string.IsNullOrEmpty(apiKey) ? minIntervalSeconds : 0f) - (Time.realtimeSinceStartup - _lastRequestTime);
                if (wait > 0) yield return new WaitForSecondsRealtime(wait);

                var (key, prompt) = _pending.Dequeue();
                string url = endpoint + UnityWebRequest.EscapeURL(prompt).Replace("+", "%20") +
                             $"?width={size}&height={size}&nologo=true&seed={_seed}";
                _lastRequestTime = Time.realtimeSinceStartup;
                Requested++;

                using (var req = UnityWebRequestTexture.GetTexture(url))
                {
                    req.timeout = timeoutSeconds;
                    if (!string.IsNullOrEmpty(apiKey)) req.SetRequestHeader("Authorization", "Bearer " + apiKey);
                    float t0 = Time.realtimeSinceStartup;
                    yield return req.SendWebRequest();

                    if (req.result == UnityWebRequest.Result.Success)
                    {
                        var tex = DownloadHandlerTexture.GetContent(req);
                        Latencies.Add(Time.realtimeSinceStartup - t0);
                        Succeeded++;
                        _done[key] = tex;
                        Ready?.Invoke(key, tex, true);
                    }
                    else
                    {
                        Debug.LogWarning($"[LiveImageQueue] {key} failed ({req.responseCode}): {req.error}. Using fallback.");
                        var fb = Fallback(key);
                        _done[key] = fb;
                        Ready?.Invoke(key, fb, false);
                    }
                }
            }
            _worker = null;
        }
    }
}
