using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>依數字區段比較版本名稱（取路徑最後一段，如 1.20.1-47.2.0），非數字區段以序數比較</summary>
internal sealed class VersionNameComparer : IComparer<string>
{
    public static readonly VersionNameComparer Instance = new();

    public int Compare(string? x, string? y)
    {
        ReadOnlySpan<char> a = Path.GetFileName(x);
        ReadOnlySpan<char> b = Path.GetFileName(y);
        while (!a.IsEmpty && !b.IsEmpty)
        {
            ReadOnlySpan<char> segA = TakeSegment(ref a);
            ReadOnlySpan<char> segB = TakeSegment(ref b);
            int result = char.IsAsciiDigit(segA[0]) && char.IsAsciiDigit(segB[0])
                ? CompareNumeric(segA, segB)
                : segA.CompareTo(segB, StringComparison.OrdinalIgnoreCase);
            if (result != 0)
            {
                return result;
            }
        }

        return a.Length.CompareTo(b.Length);
    }

    private static ReadOnlySpan<char> TakeSegment(ref ReadOnlySpan<char> text)
    {
        bool digit = char.IsAsciiDigit(text[0]);
        int end = 1;
        while (end < text.Length && char.IsAsciiDigit(text[end]) == digit)
        {
            end++;
        }

        ReadOnlySpan<char> segment = text[..end];
        text = text[end..];
        return segment;
    }

    private static int CompareNumeric(ReadOnlySpan<char> a, ReadOnlySpan<char> b) => NumericSegmentComparer.Compare(a.TrimStart('0'), b.TrimStart('0'));
}
