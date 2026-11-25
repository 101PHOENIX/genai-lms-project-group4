using Xunit;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using MysteryGame.Core;

namespace CoreTests
{
    public class DiceRulesTests
    {
        [Theory]
        [InlineData(1, ActionTier.LostTurn, 0, 0, false, false)]
        [InlineData(2, ActionTier.Basic, 1, 8, false, false)]
        [InlineData(3, ActionTier.Basic, 1, 8, false, false)]
        [InlineData(4, ActionTier.Targeted, 1, 15, true, false)]
        [InlineData(5, ActionTier.Targeted, 1, 15, true, false)]
        [InlineData(6, ActionTier.Master, 2, 25, true, true)]
        public void Roll_maps_to_locked_tier(int roll, ActionTier tier, int actions, int words, bool askNpc, bool own)
        {
            var a = DiceRules.ForRoll(roll);
            Assert.Equal(tier, a.Tier);
            Assert.Equal(actions, a.Actions);
            Assert.Equal(words, a.WordLimit);
            Assert.Equal(askNpc, a.CanAskNpcSkill);
            Assert.Equal(own, a.CanUseOwnSkill);
        }

        [Theory]
        [InlineData(0)]
        [InlineData(7)]
        public void Invalid_roll_throws(int roll) =>
            Assert.Throws<System.ArgumentOutOfRangeException>(() => DiceRules.ForRoll(roll));

        [Fact]
        public void RandomDice_stays_in_range()
        {
            var d = new RandomDice(42);
            var rolls = Enumerable.Range(0, 600).Select(_ => d.Roll()).ToList();
            Assert.All(rolls, r => Assert.InRange(r, 1, 6));
            Assert.Equal(6, rolls.Distinct().Count());
        }
    }

    public class WordLimiterTests
    {
        [Theory]
        [InlineData("", 0)]
        [InlineData("   ", 0)]
        [InlineData("Inspect the crime scene", 4)]
        [InlineData("Interrogate the chef", 3)]
        [InlineData("Where were you at 23:40?", 6)]
        [InlineData("Don't lie, it's well-known!", 4)]
        [InlineData("¿Dónde estabas, Jesús?", 3)]
        [InlineData("?! ... --", 0)]
        public void Counts_words(string text, int expected) => Assert.Equal(expected, WordLimiter.Count(text));

        [Fact]
        public void Truncate_keeps_first_n_words()
        {
            Assert.Equal("one two three", WordLimiter.Truncate("one two three four five", 3));
            Assert.Equal("short text", WordLimiter.Truncate("short text", 8));
            Assert.Equal("", WordLimiter.Truncate("anything", 0));
        }

        [Fact]
        public void Eight_word_limit_boundary()
        {
            Assert.True(WordLimiter.IsWithin("a b c d e f g h", 8));
            Assert.False(WordLimiter.IsWithin("a b c d e f g h i", 8));
        }
    }

    public class TrustTrackerTests
    {
        [Fact]
        public void Starts_at_zero_and_clamps_to_range()
        {
            var t = new TrustTracker(new[] { "alba" });
            Assert.Equal(0, t.Get("alba"));
            for (int i = 0; i < 5; i++) t.Apply("alba", +1);
            Assert.Equal(2, t.Get("alba"));
            for (int i = 0; i < 9; i++) t.Apply("alba", -1);
            Assert.Equal(-2, t.Get("alba"));
        }

        [Fact]
        public void Out_of_range_llm_change_is_clamped_to_one_step()
        {
            var t = new TrustTracker(new[] { "marco" });
            t.Apply("marco", 5);
            Assert.Equal(1, t.Get("marco"));
            t.Apply("marco", -7);
            Assert.Equal(0, t.Get("marco"));
        }

        [Fact]
        public void Skill_needs_positive_trust_and_hostile_below_zero()
        {
            var t = new TrustTracker(new[] { "a", "b" });
            Assert.False(t.WillUseSkill("a"));
            t.Apply("a", 1);
            Assert.True(t.WillUseSkill("a"));
            t.Apply("b", -1);
            Assert.True(t.IsHostile("b"));
            Assert.False(t.WillUseSkill("b"));
        }

        [Fact]
        public void Changed_event_fires_only_on_change()
        {
            var t = new TrustTracker(new[] { "a" });
            int fired = 0;
            t.Changed += (_, __, ___) => fired++;
            t.Apply("a", 0);
            t.Apply("a", 1);
            t.Apply("a", 1);
            t.Apply("a", 1); // already at +2
            Assert.Equal(2, fired);
        }
    }

    public class CaseSessionTests
    {
        private static readonly string[] Alive =
            { "alba", "marco", "chechu", "mario", "angela", "andrea", "serafettin", "borja", "pablo", "jesus" };

        private static CaseFile Sample()
        {
            var json = File.ReadAllText(Path.Combine(System.AppContext.BaseDirectory, "sample_case.json"));
            return JsonSerializer.Deserialize<CaseFile>(json, new JsonSerializerOptions { IncludeFields = true });
        }

        [Fact]
        public void Sample_case_deserializes_into_model()
        {
            var c = Sample();
            Assert.Equal("jesus", c.killer);
            Assert.Equal(5, c.key_clues.Count);
            Assert.Equal("Hacker", c.key_clues.Single(k => k.id == "k4").requires_skill);
            Assert.Equal(8, c.npc_secrets.Count);
        }

        [Fact]
        public void Trust_excludes_detective_and_victim()
        {
            var s = new CaseSession(Sample(), "borja", Alive, new ScriptedDice(3));
            Assert.Equal(8, s.Trust.All.Count);
            Assert.DoesNotContain("borja", s.Trust.All.Keys);
            Assert.DoesNotContain("mario", s.Trust.All.Keys);
        }

        [Fact]
        public void Seven_rounds_then_trial_and_correct_vote_solves()
        {
            // rolls: lost, basic, targeted, master(2 actions), basic, lost, targeted
            var s = new CaseSession(Sample(), "borja", Alive, new ScriptedDice(1, 2, 4, 6, 3, 1, 5));
            s.BeginInvestigation();
            for (int r = 1; r <= 7; r++)
            {
                var a = s.RollForRound();
                for (int k = 0; k < a.Actions; k++)
                    s.CompleteAction("angela", +1, new[] { $"k{r}" });
            }
            Assert.Equal(CasePhase.Trial, s.Phase);
            Assert.Equal(0, s.RoundsRemaining);
            Assert.True(s.Vote("jesus"));
            Assert.Equal(CasePhase.Solved, s.Phase);
            Assert.Equal(new[] { "mario", "jesus" }, s.Eliminated().ToArray());
        }

        [Fact]
        public void Wrong_vote_is_game_over()
        {
            var s = new CaseSession(Sample(), "borja", Alive, new ScriptedDice(1));
            s.BeginInvestigation();
            for (int r = 0; r < 7; r++) s.RollForRound(); // all lost turns
            Assert.Equal(CasePhase.Trial, s.Phase);
            Assert.False(s.Vote("chechu"));
            Assert.Equal(CasePhase.GameOver, s.Phase);
        }

        [Fact]
        public void Action_checks_enforce_words_and_skills()
        {
            var s = new CaseSession(Sample(), "borja", Alive, new ScriptedDice(2, 4, 6));
            s.BeginInvestigation();

            s.RollForRound(); // 2 -> basic, 8 words
            Assert.Null(s.CheckAction("Inspect the crime scene"));
            Assert.Contains("Too many words", s.CheckAction("Tell me exactly where you were last night at midnight"));
            Assert.NotNull(s.CheckAction("hack the tablet", usesOwnSkill: true));
            s.CompleteAction(null, 0, null);

            s.RollForRound(); // 4 -> targeted, may ask NPC skill only with trust > 0
            Assert.Contains("trust", s.CheckAction("Paint the scene for me", "andrea", asksNpcSkill: true));
            s.Trust.Apply("andrea", 1);
            Assert.Null(s.CheckAction("Paint the scene for me", "andrea", asksNpcSkill: true));
            Assert.NotNull(s.CheckAction("hack the tablet", usesOwnSkill: true));
            s.CompleteAction("andrea", 0, null);

            s.RollForRound(); // 6 -> master, own skill allowed, 25 words, 2 actions
            Assert.Null(s.CheckAction("Hack Jesús's tablet and recover deleted messages", usesOwnSkill: true));
            s.CompleteAction(null, 0, new[] { "k4" });
            Assert.Equal(1, s.ActionsLeft);
        }

        [Fact]
        public void Key_clue_event_fires_once_per_clue()
        {
            var s = new CaseSession(Sample(), "borja", Alive, new ScriptedDice(6));
            var found = new List<string>();
            s.KeyClueFound += k => found.Add(k.id);
            s.BeginInvestigation();
            s.RollForRound();
            s.CompleteAction(null, 0, new[] { "k1", "m1" });
            s.CompleteAction(null, 0, new[] { "k1", "k2" });
            Assert.Equal(new[] { "k1", "k2" }, found);
        }

        [Fact]
        public void Suicide_case_expects_suicide_vote_and_one_elimination()
        {
            var c = Sample();
            c.case_type = "suicide"; c.killer = null;
            var s = new CaseSession(c, "borja", Alive, new ScriptedDice(1));
            s.BeginInvestigation();
            for (int r = 0; r < 7; r++) s.RollForRound();
            Assert.True(s.Vote(CaseFile.SuicideVote));
            Assert.Equal(new[] { "mario" }, s.Eliminated().ToArray());
        }
    }
}
