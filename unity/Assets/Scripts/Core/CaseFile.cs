using System;
using System.Collections.Generic;

namespace MysteryGame.Core
{
    // Mirrors narrative/master_system_prompt.md "Output". Public fields + [Serializable]
    // so it works with both UnityEngine.JsonUtility and Newtonsoft.Json.
    // NOTE: JsonUtility turns JSON null strings into "" - use IsNullOrEmpty checks.

    [Serializable]
    public class CaseFile
    {
        public int case_number;
        public string case_type;      // "standard" | "accomplice" | "suicide"
        public string victim;
        public string killer;         // null/"" for suicide
        public string accomplice;     // null/"" unless accomplice
        public string weapon;
        public string motive;
        public string crime_location;
        public string time_of_death;
        public string truth_summary;
        public string crime_scene_prompt;
        public string host_announcement;
        public List<KeyClue> key_clues = new List<KeyClue>();
        public List<MinorClue> minor_clues = new List<MinorClue>();
        public List<FalseClue> false_clues = new List<FalseClue>();
        public List<NpcSecret> npc_secrets = new List<NpcSecret>();

        public bool IsSuicide => case_type == "suicide";

        /// <summary>The id the Detective must vote for. Suicide -> the special "suicide" vote.</summary>
        public string CorrectVote => IsSuicide ? SuicideVote : killer;

        public const string SuicideVote = "__suicide__";
    }

    [Serializable]
    public class KeyClue
    {
        public string id, name, location, description, points_to, requires_skill, image_prompt;
    }

    [Serializable]
    public class MinorClue
    {
        public string id, location, description, source;
    }

    [Serializable]
    public class FalseClue
    {
        public string id, location, description, planted_by, points_to;
    }

    [Serializable]
    public class NpcSecret
    {
        public string character, alibi, secret;
        public bool is_lying;
        public List<string> knows = new List<string>();
    }
}
