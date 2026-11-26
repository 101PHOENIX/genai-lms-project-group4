using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Xunit;
using MysteryGame.Core;

namespace CoreTests
{
    public class MusicCuesTests
    {
        [Theory]
        [InlineData(CasePhase.Incident, 0, MusicCues.CrimeDiscovery)]
        [InlineData(CasePhase.Investigation, 0, MusicCues.Investigation)]
        [InlineData(CasePhase.Investigation, 5, MusicCues.Investigation)]
        [InlineData(CasePhase.Investigation, 6, MusicCues.InvestigationLate)]
        [InlineData(CasePhase.Investigation, 7, MusicCues.InvestigationLate)]
        [InlineData(CasePhase.Trial, 7, MusicCues.Trial)]
        [InlineData(CasePhase.Solved, 7, MusicCues.Victory)]
        [InlineData(CasePhase.GameOver, 7, MusicCues.GameOver)]
        public void Phase_and_round_pick_the_cue(CasePhase phase, int round, string expected) =>
            Assert.Equal(expected, MusicCues.ForState(phase, round));

        [Fact]
        public void Only_endings_are_one_shots()
        {
            Assert.False(MusicCues.Loops(MusicCues.Victory));
            Assert.False(MusicCues.Loops(MusicCues.GameOver));
            Assert.True(MusicCues.Loops(MusicCues.Investigation));
            Assert.True(MusicCues.Loops(MusicCues.Trial));
        }

        [Fact]
        public void Missing_late_variant_falls_back_to_investigation_then_silence()
        {
            Assert.Equal(MusicCues.Investigation, MusicCues.Fallback(MusicCues.InvestigationLate));
            Assert.Null(MusicCues.Fallback(MusicCues.Investigation));
        }

        [Fact]
        public void Victory_returns_to_exploration_and_game_over_to_silence()
        {
            Assert.Equal(MusicCues.Exploration, MusicCues.After(MusicCues.Victory));
            Assert.Null(MusicCues.After(MusicCues.GameOver));
        }

        [Fact]
        public void Full_case_produces_the_expected_cue_sequence()
        {
            var json = File.ReadAllText(Path.Combine(System.AppContext.BaseDirectory, "sample_case.json"));
            var c = JsonSerializer.Deserialize<CaseFile>(json, new JsonSerializerOptions { IncludeFields = true });
            var alive = new[] { "alba", "marco", "chechu", "mario", "angela", "andrea", "serafettin", "borja", "pablo", "jesus" };
            var s = new CaseSession(c, "borja", alive, new ScriptedDice(2));
            var cues = new List<string>();
            void Record() { var cue = MusicCues.ForState(s.Phase, s.Round); if (cues.LastOrDefault() != cue) cues.Add(cue); }

            Record();
            s.BeginInvestigation();
            Record();
            for (int r = 1; r <= CaseSession.RoundsPerCase; r++)
            {
                s.RollForRound();
                Record();
                s.CompleteAction("angela", 0, null);
                Record();
            }
            s.Vote("jesus");
            Record();

            Assert.Equal(new[]
            {
                MusicCues.CrimeDiscovery, MusicCues.Investigation, MusicCues.InvestigationLate,
                MusicCues.Trial, MusicCues.Victory,
            }, cues);
        }
    }
}
