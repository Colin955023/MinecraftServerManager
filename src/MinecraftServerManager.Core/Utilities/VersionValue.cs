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


        string[] components = match.Groups["version"].Value.Split('.');
        if (!int.TryParse(components[0], CultureInfo.InvariantCulture, out int major)
            || !TryParseComponent(components, 1, out int minor)
            || !TryParseComponent(components, 2, out int patch))
        {
            result = default;
            return false;
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

    private static bool TryParseComponent(string[] components, int index, out int value)
    {
        value = 0;
        return index >= components.Length
            || int.TryParse(components[index], CultureInfo.InvariantCulture, out value);
    }
}
