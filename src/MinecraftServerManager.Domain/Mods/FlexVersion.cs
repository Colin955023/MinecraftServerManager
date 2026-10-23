namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 彈性語意版本比較引擎（FlexVersion）。
/// 規格參照 Prism Launcher 之版本解析標準，以原生 C# / .NET 10 落實乾淨室獨立實作（Clean-room implementation）。
/// 能精準解析 Minecraft 自由格式之模組版本字串，支援多區段比對、前導零正規化、忽略 '+' 建置中繼資料與預發布版降級，提供與人類直覺完全相符之版本排序與比較。
/// </summary>
public sealed class FlexVersion : IComparable<FlexVersion>, IEquatable<FlexVersion>, IComparable
{
    public enum SectionType : byte
    {
        Null = 0,
        Textual = 1,
        Numeric = 2,
        PreRelease = 3,
    }

    public readonly record struct Section(SectionType Type, string Value) : IComparable<Section>
    {
        public static readonly Section Null = new(SectionType.Null, string.Empty);

        public int CompareTo(Section other)
        {
            // 若兩者皆為 Numeric，比較數值大小（去除前導 0 後長度較長者為大，長度相同則比字元字典序）
            if (Type == SectionType.Numeric && other.Type == SectionType.Numeric)
            {
                if (Value.Length != other.Value.Length)
                {
                    return Value.Length.CompareTo(other.Value.Length);
                }
                return string.Compare(Value, other.Value, StringComparison.Ordinal);
            }

            // 兩者皆為 Null
            if (Type == SectionType.Null && other.Type == SectionType.Null)
            {
                return 0;
            }

            // 其中一個為 Null
            if (Type == SectionType.Null)
            {
                // 正式版 (Null) 優先於 PreRelease 版 (例如 1.0.0 比 1.0.0-beta 大)
                return other.Type == SectionType.PreRelease ? 1 : -1;
            }
            if (other.Type == SectionType.Null)
            {
                return Type == SectionType.PreRelease ? -1 : 1;
            }

            // 文字或不同類型比較 (區段代碼 Unicode 順序)
            int minLen = Math.Min(Value.Length, other.Value.Length);
            for (int i = 0; i < minLen; i++)
            {
                char a = Value[i];
                char b = other.Value[i];
                if (a != b)
                {
                    return a.CompareTo(b);
                }
            }

            return Value.Length.CompareTo(other.Value.Length);
        }

        public static bool operator <(Section left, Section right) => left.CompareTo(right) < 0;

        public static bool operator <=(Section left, Section right) => left.CompareTo(right) <= 0;

        public static bool operator >(Section left, Section right) => left.CompareTo(right) > 0;

        public static bool operator >=(Section left, Section right) => left.CompareTo(right) >= 0;

    }

    private readonly List<Section> _sections;

    /// <summary>
    /// 取得原始版本字串。
    /// </summary>
    public string OriginalString { get; }

    public FlexVersion(string? raw)
    {
        OriginalString = raw ?? string.Empty;
        _sections = ParseSections(OriginalString);
    }

    /// <summary>
    /// 比較兩個模組版本字串之新舊先後關係。
    /// 若 a > b 回傳正數；若 a &lt; b 回傳負數；若相同回傳 0。
    /// </summary>
    public static int Compare(string? a, string? b)
    {
        if (string.Equals(a, b, StringComparison.OrdinalIgnoreCase))
        {
            return 0;
        }

        string cleanA = NormalizeModVersionString(a);
        string cleanB = NormalizeModVersionString(b);

        var vA = new FlexVersion(cleanA);
        var vB = new FlexVersion(cleanB);
        return vA.CompareTo(vB);
    }

    /// <summary>
    /// 正規化 Minecraft 模組常見的版本字串前綴與中繼資料。
    /// 例如：v1.2.3 -> 1.2.3, mc1.21.1-0.15.2-fabric -> 0.15.2-fabric
    /// </summary>
    public static string NormalizeModVersionString(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return string.Empty;
        }

        ReadOnlySpan<char> span = raw.Trim().AsSpan();

        // 去除開頭的 'v' 或 'V' (若其後直接接數字，例如 v1.2.0 -> 1.2.0)
        if (span.StartsWith("v", StringComparison.OrdinalIgnoreCase) && span.Length > 1 && char.IsAsciiDigit(span[1]))
        {
            span = span[1..];
        }

        // 去除常見 Minecraft 版本前綴，如 mc1.21.1-0.15.2 或 1.21-15.1.4
        if (span.StartsWith("mc", StringComparison.OrdinalIgnoreCase) && span.Length > 2 && char.IsAsciiDigit(span[2]))
        {
            int sepIndex = span.IndexOfAny('-', '_');
            if (sepIndex > 2 && sepIndex + 1 < span.Length && char.IsAsciiDigit(span[sepIndex + 1]))
            {
                span = span[(sepIndex + 1)..];
            }
        }
        else if (char.IsAsciiDigit(span[0]))
        {
            int firstDash = span.IndexOf('-');
            if (firstDash > 0 && firstDash + 1 < span.Length && char.IsAsciiDigit(span[firstDash + 1]))
            {
                ReadOnlySpan<char> prefix = span[..firstDash];
                ReadOnlySpan<char> remainder = span[(firstDash + 1)..];
                if (prefix.StartsWith("1.") && remainder.Contains('.'))
                {
                    span = remainder;
                }
            }
        }

        return span.ToString();
    }

    private static List<Section> ParseSections(string raw)
    {
        var sections = new List<Section>();
        ReadOnlySpan<char> span = raw.AsSpan();
        int len = span.Length;

        for (int i = 0; i < len;)
        {
            char c = span[i];
            if (c == '+')
            {
                // 依照 FlexVer 規範：忽略 '+' 之後的建置中繼資料 (Build Metadata)
                break;
            }

            var type = SectionType.Textual;
            int start = i;

            if (c is '-' or ' ')
            {
                i++;
                if (i < len && !char.IsAsciiDigit(span[i]))
                {
                    type = SectionType.PreRelease;
                }
            }
            else if (char.IsAsciiDigit(c))
            {
                type = SectionType.Numeric;
            }

            while (i < len)
            {
                char r = span[i];
                if ((char.IsAsciiDigit(r) != (type == SectionType.Numeric))
                    || (r == ' ' && type == SectionType.Numeric)
                    || (r == '-' && type != SectionType.PreRelease)
                    || r == '+')
                {
                    break;
                }
                i++;
            }

            ReadOnlySpan<char> secSpan = span[start..i];
            if (!secSpan.IsEmpty)
            {
                if (type == SectionType.Numeric)
                {
                    secSpan = secSpan.TrimStart('0');
                }
                sections.Add(new Section(type, secSpan.ToString()));
            }
        }

        return sections;
    }

    public int CompareTo(FlexVersion? other)
    {
        if (ReferenceEquals(this, other))
        {
            return 0;
        }
        if (other is null)
        {
            return 1;
        }

        int maxSections = Math.Max(_sections.Count, other._sections.Count);
        for (int i = 0; i < maxSections; i++)
        {
            var secA = i < _sections.Count ? _sections[i] : Section.Null;
            var secB = i < other._sections.Count ? other._sections[i] : Section.Null;

            int cmp = secA.CompareTo(secB);
            if (cmp != 0)
            {
                return cmp;
            }
        }

        return 0;
    }

    public int CompareTo(object? obj) => obj is FlexVersion fv ? CompareTo(fv) : 1;

    public bool Equals(FlexVersion? other) => CompareTo(other) == 0;

    public override bool Equals(object? obj) => obj is FlexVersion fv && Equals(fv);

    public override int GetHashCode()
    {
        var hash = new HashCode();
        foreach (var section in _sections)
        {
            if (section.Type != SectionType.Null)
            {
                hash.Add(section.Type);
                hash.Add(section.Value, StringComparer.Ordinal);
            }
        }

        return hash.ToHashCode();
    }

    public override string ToString() => OriginalString;

    public static bool operator ==(FlexVersion? left, FlexVersion? right) =>
        ReferenceEquals(left, right) || (left is not null && right is not null && left.CompareTo(right) == 0);

    public static bool operator !=(FlexVersion? left, FlexVersion? right) => !(left == right);

    public static bool operator <(FlexVersion? left, FlexVersion? right) =>
        left is null ? right is not null : left.CompareTo(right) < 0;

    public static bool operator <=(FlexVersion? left, FlexVersion? right) =>
        left is null || left.CompareTo(right) <= 0;

    public static bool operator >(FlexVersion? left, FlexVersion? right) =>
        left is not null && (right is null || left.CompareTo(right) > 0);

    public static bool operator >=(FlexVersion? left, FlexVersion? right) =>
        right is null || (left is not null && left.CompareTo(right) >= 0);
}
