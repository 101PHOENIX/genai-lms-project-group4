using System;
using System.Collections.Generic;
using System.Linq;

namespace MysteryGame.Core
{
    public enum CasePhase { Incident, Investigation, Trial, Solved, GameOver }

    /// <summary>
    /// One Case: 7 investigation rounds -> trial vote. Pure logic, no Unity types,
    /// so the UI layer (Team 4) just reads state and calls these methods.
    /// </summary>
    public sealed class CaseSession
    {
        public const int RoundsPerCase = 7;

        public CaseFile Case { get; }
        public string DetectiveId { get; }
        public TrustTracker Trust { get; }
        public CasePhase Phase { get; private set; } = CasePhase.Incident;
        public int Round { get; private set; }               // 1..7 during investigation
        public RoundAllowance? Current { get; private set; }
        public int ActionsLeft { get; private set; }
        public HashSet<string> FoundClues { get; } = new HashSet<string>();

        private readonly IDice _dice;

        public event Action<KeyClue> KeyClueFound;

        public CaseSession(CaseFile caseFile, string detectiveId, IEnumerable<string> aliveIds, IDice dice)
        {
            Case = caseFile ?? throw new ArgumentNullException(nameof(caseFile));
            DetectiveId = detectiveId;
            _dice = dice;
            Trust = new TrustTracker(aliveIds.Where(id => id != detectiveId && id != caseFile.victim));
        }

        /// <summary>Called after the discovery sequence. Starts round 1.</summary>
        public void BeginInvestigation()
        {
            if (Phase != CasePhase.Incident) throw new InvalidOperationException($"Cannot begin from {Phase}");
            Phase = CasePhase.Investigation;
            Round = 0;
        }

        /// <summary>Roll the d6 for the next round. Returns the allowance (LostTurn ends the round immediately).</summary>
        public RoundAllowance RollForRound()
        {
            if (Phase != CasePhase.Investigation) throw new InvalidOperationException("Not investigating");
            if (ActionsLeft > 0) throw new InvalidOperationException("Finish current round first");
            Round++;
            var a = DiceRules.ForRoll(_dice.Roll());
            Current = a;
            ActionsLeft = a.Actions;
            if (ActionsLeft == 0) EndRound();
            return a;
        }

        /// <summary>
        /// Validate a Detective action before it is sent to the LLM.
        /// Returns null if allowed, otherwise a player-facing reason.
        /// </summary>
        public string CheckAction(string text, string targetNpc = null, bool usesOwnSkill = false, bool asksNpcSkill = false)
        {
            if (Phase != CasePhase.Investigation || Current == null || ActionsLeft <= 0) return "No actions left this round.";
            var a = Current.Value;
            int words = WordLimiter.Count(text);
            if (words == 0) return "Type an action.";
            if (words > a.WordLimit) return $"Too many words: {words}/{a.WordLimit}.";
            if (usesOwnSkill && !a.CanUseOwnSkill) return "Your Special Skill needs a 6.";
            if (asksNpcSkill)
            {
                if (!a.CanAskNpcSkill) return "Asking for an NPC's skill needs a 4 or more.";
                if (targetNpc == null || !Trust.WillUseSkill(targetNpc)) return "They don't trust you enough to help.";
            }
            return null;
        }

        /// <summary>Consume one action after the LLM answered. trustChange comes from the LLM response.</summary>
        public void CompleteAction(string targetNpc, int trustChange, IEnumerable<string> revealedClueIds)
        {
            if (ActionsLeft <= 0) throw new InvalidOperationException("No actions left");
            if (!string.IsNullOrEmpty(targetNpc)) Trust.Apply(targetNpc, trustChange);
            foreach (var id in revealedClueIds ?? Enumerable.Empty<string>())
            {
                if (!FoundClues.Add(id)) continue;
                var kc = Case.key_clues.FirstOrDefault(k => k.id == id);
                if (kc != null) KeyClueFound?.Invoke(kc);
            }
            ActionsLeft--;
            if (ActionsLeft == 0) EndRound();
        }

        private void EndRound()
        {
            Current = null;
            if (Round >= RoundsPerCase) Phase = CasePhase.Trial;
        }

        public int RoundsRemaining => Phase == CasePhase.Investigation ? RoundsPerCase - Round : 0;

        /// <summary>Trial vote. Pass a character id, or CaseFile.SuicideVote.</summary>
        public bool Vote(string accusedId)
        {
            if (Phase != CasePhase.Trial) throw new InvalidOperationException("Not in trial");
            bool correct = accusedId == Case.CorrectVote;
            Phase = correct ? CasePhase.Solved : CasePhase.GameOver;
            return correct;
        }

        /// <summary>Who leaves the cast after a solved case: victim + punished killer (accomplice stays).</summary>
        public IEnumerable<string> Eliminated()
        {
            yield return Case.victim;
            if (!Case.IsSuicide && !string.IsNullOrEmpty(Case.killer)) yield return Case.killer;
        }
    }
}
