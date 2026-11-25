using System;

namespace MysteryGame.Core
{
    /// <summary>Action tiers from the locked dice rules (brief §2).</summary>
    public enum ActionTier { LostTurn, Basic, Targeted, Master }

    /// <summary>What the Detective may do this round, derived from the d6 roll.</summary>
    public readonly struct RoundAllowance
    {
        public readonly int Roll;
        public readonly ActionTier Tier;
        public readonly int Actions;          // number of actions this round
        public readonly int WordLimit;        // max words per action (0 = none allowed)
        public readonly bool CanAskNpcSkill;  // ask an NPC to use their skill (needs trust > 0)
        public readonly bool CanUseOwnSkill;  // Detective's own Special Skill

        public RoundAllowance(int roll, ActionTier tier, int actions, int wordLimit, bool askNpc, bool ownSkill)
        {
            Roll = roll; Tier = tier; Actions = actions; WordLimit = wordLimit;
            CanAskNpcSkill = askNpc; CanUseOwnSkill = ownSkill;
        }
    }

    public static class DiceRules
    {
        public static RoundAllowance ForRoll(int roll)
        {
            switch (roll)
            {
                case 1: return new RoundAllowance(1, ActionTier.LostTurn, 0, 0, false, false);
                case 2:
                case 3: return new RoundAllowance(roll, ActionTier.Basic, 1, 8, false, false);
                case 4:
                case 5: return new RoundAllowance(roll, ActionTier.Targeted, 1, 15, true, false);
                case 6: return new RoundAllowance(6, ActionTier.Master, 2, 25, true, true);
                default: throw new ArgumentOutOfRangeException(nameof(roll), roll, "d6 roll must be 1-6");
            }
        }
    }

    /// <summary>Injectable d6 so tests and the demo can use fixed sequences.</summary>
    public interface IDice { int Roll(); }

    public sealed class RandomDice : IDice
    {
        private readonly Random _rng;
        public RandomDice(int? seed = null) { _rng = seed.HasValue ? new Random(seed.Value) : new Random(); }
        public int Roll() => _rng.Next(1, 7);
    }

    /// <summary>Plays back a fixed sequence (for demo safety / tests), then repeats the last value.</summary>
    public sealed class ScriptedDice : IDice
    {
        private readonly int[] _seq; private int _i;
        public ScriptedDice(params int[] seq) { _seq = seq; }
        public int Roll() => _seq[Math.Min(_i++, _seq.Length - 1)];
    }
}
