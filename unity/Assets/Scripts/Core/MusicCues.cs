namespace MysteryGame.Core
{
    /// <summary>
    /// Which music cue fits the game state. Pure logic (no UnityEngine) so it is tested with Core.
    /// The ids are the contract with audio/audio_cues.json and the clips in Assets/Audio/Music;
    /// tests/test_generate_audio.py fails if the two drift apart.
    /// </summary>
    public static class MusicCues
    {
        public const string Exploration = "exploration";
        public const string CrimeDiscovery = "crime_discovery";
        public const string Investigation = "investigation";
        public const string InvestigationLate = "investigation_late";
        public const string Trial = "trial";
        public const string Victory = "victory";
        public const string GameOver = "game_over";

        /// <summary>First round that switches to the tense variant (rounds 6 and 7 of 7).</summary>
        public const int LateRoundFrom = CaseSession.RoundsPerCase - 1;

        /// <summary>Cue for a CaseSession state. Exploration (map, menus, between cases) is set by the UI.</summary>
        public static string ForState(CasePhase phase, int round)
        {
            switch (phase)
            {
                case CasePhase.Incident: return CrimeDiscovery;
                case CasePhase.Investigation: return round >= LateRoundFrom ? InvestigationLate : Investigation;
                case CasePhase.Trial: return Trial;
                case CasePhase.Solved: return Victory;
                case CasePhase.GameOver: return GameOver;
                default: return Exploration;
            }
        }

        /// <summary>Endings are one-shot stingers; everything else loops.</summary>
        public static bool Loops(string cue) => cue != Victory && cue != GameOver;

        /// <summary>Cue to play when this one has no clip imported yet. Null means silence.</summary>
        public static string Fallback(string cue) => cue == InvestigationLate ? Investigation : null;

        /// <summary>Cue that follows a one-shot once it ends. Null means silence.</summary>
        public static string After(string cue) => cue == Victory ? Exploration : null;
    }
}
