using System;
using System.Collections.Generic;

namespace MysteryGame.Core
{
    /// <summary>Per-NPC Trust Score, clamped to -2..+2, everyone starts at 0 (brief §2).</summary>
    public sealed class TrustTracker
    {
        public const int Min = -2, Max = 2;
        private readonly Dictionary<string, int> _scores = new Dictionary<string, int>();

        public event Action<string, int, int> Changed; // (npcId, oldValue, newValue)

        public TrustTracker(IEnumerable<string> npcIds)
        {
            foreach (var id in npcIds) _scores[id] = 0;
        }

        public int Get(string npcId) => _scores.TryGetValue(npcId, out var v) ? v : 0;

        /// <summary>Apply the LLM's trust_change. Values outside -1..+1 are clamped (defensive against bad JSON).</summary>
        public int Apply(string npcId, int trustChange)
        {
            int delta = Math.Max(-1, Math.Min(1, trustChange));
            int old = Get(npcId);
            int now = Math.Max(Min, Math.Min(Max, old + delta));
            _scores[npcId] = now;
            if (now != old) Changed?.Invoke(npcId, old, now);
            return now;
        }

        /// <summary>Positive trust: cooperates and agrees to use their skill.</summary>
        public bool WillUseSkill(string npcId) => Get(npcId) > 0;

        /// <summary>Negative trust: defensive, may lie, refuses skill even on 4-6.</summary>
        public bool IsHostile(string npcId) => Get(npcId) < 0;

        public void Remove(string npcId) => _scores.Remove(npcId);

        public IReadOnlyDictionary<string, int> All => _scores;
    }
}
