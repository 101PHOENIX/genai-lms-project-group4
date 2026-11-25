using System.Text.RegularExpressions;

namespace MysteryGame.Core
{
    /// <summary>
    /// Real-time word counter for the dialogue input (8 / 15 / 25 words).
    /// A "word" = a run of letters/digits, apostrophes and hyphens allowed inside
    /// (so "don't" and "well-known" count once; "?!" counts zero).
    /// </summary>
    public static class WordLimiter
    {
        private static readonly Regex Word = new Regex(@"[\p{L}\p{N}]+(?:['’\-][\p{L}\p{N}]+)*", RegexOptions.Compiled);

        public static int Count(string text) => string.IsNullOrWhiteSpace(text) ? 0 : Word.Matches(text).Count;

        public static bool IsWithin(string text, int limit) => Count(text) <= limit;

        /// <summary>Hard-truncate to the first <paramref name="limit"/> words, keeping original spacing/punctuation.</summary>
        public static string Truncate(string text, int limit)
        {
            if (string.IsNullOrEmpty(text) || limit <= 0) return string.Empty;
            var m = Word.Matches(text);
            if (m.Count <= limit) return text;
            var last = m[limit - 1];
            return text.Substring(0, last.Index + last.Length);
        }
    }
}
