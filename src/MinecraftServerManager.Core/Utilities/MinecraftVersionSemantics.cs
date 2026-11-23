using System.Globalization;
using System.Text.RegularExpressions;
using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Core.Utilities;

/// <summary>Minecraft 版本與載入器純語意工具類別</summary>
public static partial class MinecraftVersionSemantics
{
    private const RegexOptions PatternOptions = RegexOptions.IgnoreCase | RegexOptions.CultureInvariant;

    /// <summary>NeoForge 可沿用 Forge 模組的唯一 Minecraft 版本</summary>
    public const string NeoForgeForgeCompatibleVersion = "1.20.1";

    // 版號後綴：-preN、-rcN、-snapshot-N
    private const string VersionWithSuffix = @"([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-(?:pre|rc)[0-9]+|-snapshot-[0-9]+)?)(?![0-9]|\.[0-9])";

    [GeneratedRegex(@"(?<![A-Za-z0-9])minecraft[-_.:\s]*" + VersionWithSuffix, PatternOptions)]
    private static partial Regex MinecraftPattern1();

    [GeneratedRegex(@"(?<![A-Za-z0-9])mc[-_.:\s]*" + VersionWithSuffix, PatternOptions)]
    private static partial Regex MinecraftPattern2();

    [GeneratedRegex(@"(?<![A-Za-z0-9])version[-_.:\s]+" + VersionWithSuffix, PatternOptions)]
    private static partial Regex MinecraftPattern3();

    [GeneratedRegex(@"(?<![0-9.])((?:1|2[6-9]|[3-9][0-9])\.[0-9]+(?:\.[0-9]+)?-(?:pre|rc)[0-9]+)(?![0-9])", PatternOptions)]
    private static partial Regex MinecraftPattern4();

    [GeneratedRegex(@"(?<![0-9.])((?:1|2[6-9]|[3-9][0-9])\.[0-9]+(?:\.[0-9]+)?-snapshot-[0-9]+)(?![0-9])", PatternOptions)]
    private static partial Regex MinecraftPattern5();

    [GeneratedRegex(@"(?<![A-Za-z0-9])((?:1[89]|[2-9][0-9])w[0-9]{2}[a-z])(?![A-Za-z0-9])", PatternOptions)]
    private static partial Regex MinecraftPattern6();

    // 泛用 x.y 僅接受 1.x 或 26.x 以上，避免誤抓模組自身版號
    [GeneratedRegex(@"(?<![0-9.])((?:1|2[6-9]|[3-9][0-9])\.[0-9]+(?:\.[0-9]+)?)(?![0-9]|\.[0-9])", PatternOptions)]
    private static partial Regex MinecraftPattern7();

    [GeneratedRegex(@"^(?<year>[0-9]{2})w(?<week>[0-9]{2})[a-z]$", PatternOptions)]
    private static partial Regex WeeklySnapshotPattern();

    private static readonly Regex[] MinecraftVersionPatterns =
    [
        MinecraftPattern1(),
        MinecraftPattern2(),
        MinecraftPattern3(),
        MinecraftPattern4(),
        MinecraftPattern5(),
        MinecraftPattern6(),
        MinecraftPattern7()
    ];

    /// <summary>是否為正式發布版本（純數字點分版號）</summary>
    public static bool IsOfficialReleaseVersion(string? version)
    {
        if (string.IsNullOrWhiteSpace(version))
        {
            return false;
        }

        return DotSeparatedIntParser.IsDotSeparatedNumeric(version.AsSpan().Trim());
    }

    /// <summary>是否支援 Fabric／Quilt（1.14 以上或 18w43b 起之快照）</summary>
    public static bool IsFabricCompatible(string? minecraftVersion)
    {
        if (string.IsNullOrWhiteSpace(minecraftVersion))
        {
            return false;
        }

        if (VersionValue.TryParse(minecraftVersion, out var parsed))
        {
            return parsed.Major > 1 || (parsed.Major == 1 && parsed.Minor >= 14);
        }

        var snapshot = WeeklySnapshotPattern().Match(minecraftVersion.Trim());
        if (snapshot.Success)
        {
            int year = int.Parse(snapshot.Groups["year"].ValueSpan, NumberStyles.None, CultureInfo.InvariantCulture);
            int week = int.Parse(snapshot.Groups["week"].ValueSpan, NumberStyles.None, CultureInfo.InvariantCulture);
            return year > 18 || (year == 18 && week >= 43);
        }

        // 其他非標準版本格式預設相容
        return true;
    }

    /// <summary>Minecraft 版本是否支援 NeoForge（>= 1.20.1）</summary>
    public static bool IsNeoForgeCompatible(string? minecraftVersion)
    {
        if (!VersionValue.TryParse(minecraftVersion, out var parsed))
        {
            return false;
        }

        return parsed.Major > 1
            || (parsed.Major == 1 && (parsed.Minor > 20 || (parsed.Minor == 20 && parsed.Patch >= 1)));
    }

    /// <summary>NeoForge 伺服器是否可載入 Forge 模組（僅 1.20.1，1.20.10 等不符）</summary>
    public static bool IsNeoForgeForgeCompatible(string? minecraftVersion) =>
        string.Equals(minecraftVersion?.Trim(), NeoForgeForgeCompatibleVersion, StringComparison.OrdinalIgnoreCase);

    /// <summary>從 NeoForge 版本推導對應的 Minecraft 版本；數字段含非數字時回傳 null</summary>
    public static string? DeriveMinecraftVersionFromNeoForge(string? neoForgeVersion)
    {
        if (string.IsNullOrWhiteSpace(neoForgeVersion))
        {
            return null;
        }

        ReadOnlySpan<char> span = neoForgeVersion.AsSpan().Trim();
        int dashOrPlus = span.IndexOfAny('-', '+');
        ReadOnlySpan<char> numericPart = dashOrPlus >= 0 ? span[..dashOrPlus] : span;

        Span<int> numbers = stackalloc int[4];
        if (!DotSeparatedIntParser.TryParse(numericPart, numbers, out int count) || count is < 3 or > 4)
        {
            return null;
        }

        int major = numbers[0];
        int minor = numbers[1];
        if (major == 47)
        {
            return NeoForgeForgeCompatibleVersion;
        }

        if (major >= 26)
        {
            // 26.x 起為「MC 版本.建置號」，如 26.1.2.36 對應 26.1.2；修訂號 0 對應 26.1
            int patch = numbers[2];
            return patch > 0 ? $"{major}.{minor}.{patch}" : $"{major}.{minor}";
        }

        if (major >= 20)
        {
            return minor == 0 ? $"1.{major}" : $"1.{major}.{minor}";
        }

        return null;
    }

    /// <summary>正規化 Minecraft 版本字串，清除範圍修飾字元或提取有效版本號碼</summary>
    public static string NormalizeMinecraftVersion(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return string.Empty;
        }

        string trimmed = raw.Trim();
        string? extracted = ExtractMinecraftVersionFromText(trimmed);
        if (!string.IsNullOrWhiteSpace(extracted))
        {
            return extracted;
        }

        return trimmed.Trim('~', '^', '=', '>', '<', ' ', '[', ']', '(', ')');
    }

    /// <summary>從文字中擷取 Minecraft 版本</summary>
    public static string? ExtractMinecraftVersionFromText(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        foreach (var pattern in MinecraftVersionPatterns)
        {
            var match = pattern.Match(text);
            if (match.Success)
            {
                return match.Groups[1].Value;
            }
        }

        return null;
    }
}
