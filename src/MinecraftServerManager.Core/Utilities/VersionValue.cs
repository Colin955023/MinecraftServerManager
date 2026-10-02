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

    public static VersionValue? ParseOrDefault(string? value, VersionValue? fallback = null) => TryParse(value, out var result) ? result : fallback;

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


        ReadOnlySpan<char> versionSpan = match.Groups["version"].ValueSpan;
        int firstDot = versionSpan.IndexOf('.');
        if (firstDot < 0)
        {
            if (!int.TryParse(versionSpan, CultureInfo.InvariantCulture, out int singleMajor))
            {
                result = default;
                return false;
            }

            result = new VersionValue(singleMajor, 0, 0, match.Groups["pre"].Value, match.Groups["build"].Value);
            return true;
        }

        if (!int.TryParse(versionSpan[..firstDot], CultureInfo.InvariantCulture, out int major))
        {
            result = default;
            return false;
        }

        ReadOnlySpan<char> rest = versionSpan[(firstDot + 1)..];
        int secondDot = rest.IndexOf('.');
        int patch = 0;

        int minor;
        if (secondDot < 0)
        {
            if (!int.TryParse(rest, CultureInfo.InvariantCulture, out minor))
            {
                result = default;
                return false;
            }
        }
        else
        {
            if (!int.TryParse(rest[..secondDot], CultureInfo.InvariantCulture, out minor)
                || !int.TryParse(rest[(secondDot + 1)..], CultureInfo.InvariantCulture, out patch))
            {
                result = default;
                return false;
            }
        }

        result = new VersionValue(
            major,
            minor,
            patch,
            match.Groups["pre"].Value,
            match.Groups["build"].Value);
        return true;
    }

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
