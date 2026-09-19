using System.Text.RegularExpressions;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Mods;

/// <summary>
/// 模組檔名與識別字輔助工具
/// </summary>
public static partial class ModHelpers
{
    public const string PreferredHashAlgorithm = "sha512";

    public static string ModFilenameStem(string? filename)
    {
        string raw = (filename ?? string.Empty).Trim();
        if (raw.EndsWith(".jar.disabled", StringComparison.OrdinalIgnoreCase))
        {
            return raw[..^13];
        }
        if (raw.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
        {
            return raw[..^4];
        }
        return raw;
    }

    public static string NormalizeIdentifier(string? value) =>
        (value ?? string.Empty).Trim().ToLowerInvariant();

    public static string NormalizeHashAlgorithm(string? algorithm)
    {
        string norm = NormalizeIdentifier(algorithm);
        return norm is "sha512" or "sha256" or "sha1" ? norm : PreferredHashAlgorithm;
    }

    public static string NormalizeModSearchQuery(string rawQuery)
    {
        if (string.IsNullOrWhiteSpace(rawQuery))
        {
            return string.Empty;
        }

        string clean = ModFilenameStem(rawQuery);
        clean = CamelCaseRegex().Replace(clean, " $1");
        clean = clean.Replace('_', ' ').Replace('-', ' ');
        clean = LoaderNoiseRegex().Replace(clean, " ");
        clean = McVersionNoiseRegex().Replace(clean, " ");
        clean = VersionDigitNoiseRegex().Replace(clean, " ");

        return string.Join(" ", clean.Split(' ', StringSplitOptions.RemoveEmptyEntries)).Trim();
    }

    public static bool IsAllowedVersionType(string? versionType)
    {
        string norm = NormalizeIdentifier(versionType);
        return norm is "" or "release" or "stable" or "beta" || norm.Contains("beta", StringComparison.OrdinalIgnoreCase);
    }

    public static OnlineModVersion? SelectBestModVersion(IEnumerable<OnlineModVersion> versions)
    {
        return versions
            .OrderByDescending(v => v.PrimaryFile is not null ? 1 : 0)
            .ThenByDescending(v => GetVersionTypePriority(v.VersionType))
            .ThenByDescending(v => v.DatePublished)
            .ThenByDescending(v => v.VersionNumber)
            .FirstOrDefault();
    }

    private static int GetVersionTypePriority(string versionType)
    {
        string norm = NormalizeIdentifier(versionType);
        if (norm == "release")
        {
            return 3;
        }

        if (norm is "beta" or "snapshot")
        {
            return 2;
        }

        if (norm == "alpha")
        {
            return 1;
        }

        return 0;
    }

    [GeneratedRegex(@"(?<=[a-z0-9])([A-Z])")]
    private static partial Regex CamelCaseRegex();

    [GeneratedRegex(@"(?i)\b(?:fabric|forge|loader|quilt|neoforge)\b")]
    private static partial Regex LoaderNoiseRegex();

    [GeneratedRegex(@"(?i)\bmc\s*\d+(?:\.\d+){1,2}[a-z0-9.-]*\b")]
    private static partial Regex McVersionNoiseRegex();

    [GeneratedRegex(@"\b\d+(?:\.\d+){1,3}[a-z0-9.-]*\b")]
    private static partial Regex VersionDigitNoiseRegex();
}
