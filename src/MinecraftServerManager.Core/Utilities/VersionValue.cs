using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Core.Utilities;

/// <summary>數字版號（最多四段）與 SemVer 預發布／建置中繼資料</summary>
public readonly partial record struct VersionValue(
    int Major,
    int Minor,
    int Patch,
    int Revision = 0,
    string PreRelease = "",
    string BuildMetadata = "") : IComparable<VersionValue>
{
    /// <summary>預發布識別；<c>default</c> 執行個體回傳空字串</summary>
    public string PreRelease { get => field ?? string.Empty; init; } = PreRelease;

    /// <summary>建置中繼資料；<c>default</c> 執行個體回傳空字串</summary>
    public string BuildMetadata { get => field ?? string.Empty; init; } = BuildMetadata;

    public static VersionValue Zero => new(0, 0, 0);

    public static bool TryParse(string? value, out VersionValue result)
    {
        ReadOnlySpan<char> span = value.AsSpan().Trim();
        if (!span.IsEmpty && span[0] is 'v' or 'V')
        {
            span = span[1..];
        }

        if (span.IsEmpty)
        {
            result = default;
            return false;
        }

        string build = string.Empty;
        int plusIndex = span.IndexOf('+');
        if (plusIndex >= 0)
        {
            ReadOnlySpan<char> buildSpan = span[(plusIndex + 1)..];
            if (buildSpan.IsEmpty || !IsValidSemVerIdentifier(buildSpan))
            {
                result = default;
                return false;
            }

            build = buildSpan.ToString();
            span = span[..plusIndex];
        }

        string pre = string.Empty;
        int dashIndex = span.IndexOfAny('-', '_');
        if (dashIndex >= 0)
        {
            ReadOnlySpan<char> preSpan = span[(dashIndex + 1)..];
            if (preSpan.IsEmpty || !IsValidSemVerIdentifier(preSpan))
            {
                result = default;
                return false;
            }

            pre = preSpan.ToString();
            span = span[..dashIndex];
        }

        Span<int> numbers = stackalloc int[4];
        if (!DotSeparatedIntParser.TryParse(span, numbers, out int count) || count < 1)
        {
            result = default;
            return false;
        }

        result = new VersionValue(
            numbers[0],
            count > 1 ? numbers[1] : 0,
            count > 2 ? numbers[2] : 0,
            count > 3 ? numbers[3] : 0,
            pre,
            build);
        return true;
    }

    private static bool IsValidSemVerIdentifier(ReadOnlySpan<char> span)
    {
        foreach (char c in span)
        {
            if (!char.IsAsciiLetterOrDigit(c) && c is not ('.' or '-'))
            {
                return false;
            }
        }

        return true;
    }

    /// <summary>解析版本字串，失敗時回傳 <see cref="Zero"/></summary>
    public static VersionValue ParseOrZero(string? value) => TryParse(value, out var result) ? result : Zero;

    /// <summary>依數字段比較，再依 SemVer 2.0 規則比較預發布段；忽略建置中繼資料</summary>
    public int CompareTo(VersionValue other)
    {
        int numericComparison = (Major, Minor, Patch, Revision).CompareTo((other.Major, other.Minor, other.Patch, other.Revision));
        return numericComparison != 0 ? numericComparison : ComparePreRelease(PreRelease, other.PreRelease);
    }

    public bool Equals(VersionValue other) => CompareTo(other) == 0;

    public override int GetHashCode()
    {
        var hash = new HashCode();
        hash.Add(Major);
        hash.Add(Minor);
        hash.Add(Patch);
        hash.Add(Revision);
        foreach (Range range in PreRelease.AsSpan().Split('.'))
        {
            ReadOnlySpan<char> identifier = PreRelease.AsSpan()[range];
            if (IsNumericIdentifier(identifier))
            {
                hash.Add(string.GetHashCode(TrimLeadingZeros(identifier), StringComparison.Ordinal));
            }
            else
            {
                hash.Add(string.GetHashCode(identifier, StringComparison.OrdinalIgnoreCase));
            }
        }

        return hash.ToHashCode();
    }

    public static bool operator <(VersionValue left, VersionValue right) => left.CompareTo(right) < 0;

    public static bool operator <=(VersionValue left, VersionValue right) => left.CompareTo(right) <= 0;

    public static bool operator >(VersionValue left, VersionValue right) => left.CompareTo(right) > 0;

    public static bool operator >=(VersionValue left, VersionValue right) => left.CompareTo(right) >= 0;

    public override string ToString()
    {
        string core = Revision != 0
            ? $"{Major}.{Minor}.{Patch}.{Revision}"
            : $"{Major}.{Minor}.{Patch}";
        if (PreRelease.Length > 0)
        {
            core = $"{core}-{PreRelease}";
        }

        return BuildMetadata.Length == 0 ? core : $"{core}+{BuildMetadata}";
    }

    /// <summary>無預發布者較大；逐段比較，數字段以數值比較且小於英數段，前綴相同時段數少者較小</summary>
    private static int ComparePreRelease(string left, string right)
    {
        if (left.Length == 0 || right.Length == 0)
        {
            return right.Length.CompareTo(left.Length) switch
            {
                0 => 0,
                < 0 => -1,
                _ => 1,
            };
        }

        ReadOnlySpan<char> leftSpan = left;
        ReadOnlySpan<char> rightSpan = right;
        var leftParts = leftSpan.Split('.');
        var rightParts = rightSpan.Split('.');
        while (true)
        {
            bool hasLeft = leftParts.MoveNext();
            bool hasRight = rightParts.MoveNext();
            if (!hasLeft || !hasRight)
            {
                return hasLeft.CompareTo(hasRight);
            }

            int comparison = CompareIdentifier(leftSpan[leftParts.Current], rightSpan[rightParts.Current]);
            if (comparison != 0)
            {
                return comparison;
            }
        }
    }

    private static int CompareIdentifier(ReadOnlySpan<char> left, ReadOnlySpan<char> right)
    {
        bool leftNumeric = IsNumericIdentifier(left);
        bool rightNumeric = IsNumericIdentifier(right);
        if (leftNumeric && rightNumeric)
        {
            // 去前導零後以長度再逐字比較，避免大數溢位
            return NumericSegmentComparer.Compare(TrimLeadingZeros(left), TrimLeadingZeros(right));
        }

        if (leftNumeric != rightNumeric)
        {
            return leftNumeric ? -1 : 1;
        }

        return Math.Sign(left.CompareTo(right, StringComparison.OrdinalIgnoreCase));
    }

    private static bool IsNumericIdentifier(ReadOnlySpan<char> identifier) =>
        !identifier.IsEmpty && !identifier.ContainsAnyExceptInRange('0', '9');

    private static ReadOnlySpan<char> TrimLeadingZeros(ReadOnlySpan<char> identifier)
    {
        ReadOnlySpan<char> trimmed = identifier.TrimStart('0');
        return trimmed.IsEmpty ? "0" : trimmed;
    }
}
