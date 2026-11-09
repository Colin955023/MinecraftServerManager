using System.Globalization;
using System.Text.RegularExpressions;

namespace MinecraftServerManager.Core.Utilities;

public readonly partial record struct VersionValue(
    int Major,
    int Minor,
    int Patch,
    string PreRelease = "",
    string BuildMetadata = "") : IComparable<VersionValue>
{
    [GeneratedRegex(
        @"(?<version>\d+(?:\.\d+){0,3})(?:[-_](?<pre>[0-9A-Za-z.-]+))?(?:\+(?<build>[0-9A-Za-z.-]+))?",
        RegexOptions.CultureInvariant)]
    private static partial Regex NumericVersionPattern();

    public static VersionValue Zero => new(0, 0, 0);

    public static bool TryParse(string? value, out VersionValue result)
    {
        string candidate = value?.Trim() ?? string.Empty;
        if (candidate.StartsWith('v') || candidate.StartsWith('V'))
        {
            candidate = candidate[1..];
        }

        var match = NumericVersionPattern().Match(candidate);
        if (!match.Success)
        {
            result = default;
            return false;
        }

        // 正規表示式已保證各段皆為數字，僅需處理溢位；第四段以後忽略
        ReadOnlySpan<char> versionSpan = match.Groups["version"].ValueSpan;
        Span<Range> parts = stackalloc Range[4];
        int count = versionSpan.Split(parts, '.');
        Span<int> numbers = stackalloc int[3];
        for (int i = 0; i < Math.Min(count, 3); i++)
        {
            if (!int.TryParse(versionSpan[parts[i]], CultureInfo.InvariantCulture, out numbers[i]))
            {
                result = default;
                return false;
            }
        }

        result = new VersionValue(numbers[0], numbers[1], numbers[2], match.Groups["pre"].Value, match.Groups["build"].Value);
        return true;
    }

    /// <summary>解析版本字串，失敗時回傳 <see cref="Zero"/>。</summary>
    public static VersionValue ParseOrZero(string? value) => TryParse(value, out var result) ? result : Zero;

    public int CompareTo(VersionValue other)
    {
        int numericComparison = (Major, Minor, Patch).CompareTo((other.Major, other.Minor, other.Patch));
        if (numericComparison != 0)
        {
            return numericComparison;
        }

        if (string.IsNullOrEmpty(PreRelease) && !string.IsNullOrEmpty(other.PreRelease))
        {
            return 1;
        }

        if (!string.IsNullOrEmpty(PreRelease) && string.IsNullOrEmpty(other.PreRelease))
        {
            return -1;
        }

        return string.Compare(PreRelease, other.PreRelease, StringComparison.OrdinalIgnoreCase);
    }

    public bool Equals(VersionValue other) => CompareTo(other) == 0;

    public override int GetHashCode() =>
        HashCode.Combine(Major, Minor, Patch, StringComparer.OrdinalIgnoreCase.GetHashCode(PreRelease ?? string.Empty));

    public static bool operator <(VersionValue left, VersionValue right) => left.CompareTo(right) < 0;

    public static bool operator <=(VersionValue left, VersionValue right) => left.CompareTo(right) <= 0;

    public static bool operator >(VersionValue left, VersionValue right) => left.CompareTo(right) > 0;

    public static bool operator >=(VersionValue left, VersionValue right) => left.CompareTo(right) >= 0;

    public override string ToString()
    {
        string core = $"{Major}.{Minor}.{Patch}";
        if (!string.IsNullOrEmpty(PreRelease))
        {
            core = $"{core}-{PreRelease}";
        }

        return string.IsNullOrEmpty(BuildMetadata) ? core : $"{core}+{BuildMetadata}";
    }
}
