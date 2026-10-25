using System.Globalization;
using System.Text.RegularExpressions;

namespace MinecraftServerManager.Core.Utilities;

/// <summary>
/// Minecraft 版本與載入器純語意工具類別
/// </summary>
public static partial class MinecraftVersionSemantics
{
    [GeneratedRegex(@"minecraft[-_.:\s]*([0-9]+\.[0-9]+(?:\.[0-9]+)?)", RegexOptions.IgnoreCase)]
    private static partial Regex MinecraftPattern1();

    [GeneratedRegex(@"mc[-_.:\s]*([0-9]+\.[0-9]+(?:\.[0-9]+)?)", RegexOptions.IgnoreCase)]
    private static partial Regex MinecraftPattern2();

    [GeneratedRegex(@"version[-_.:\s]+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", RegexOptions.IgnoreCase)]
    private static partial Regex MinecraftPattern3();

    [GeneratedRegex(@"\b([0-9]+\.[0-9]+(?:\.[0-9]+)?-(?:pre|rc)[0-9]+)\b", RegexOptions.IgnoreCase)]
    private static partial Regex MinecraftPattern4();

    [GeneratedRegex(@"\b([0-9]+\.[0-9]+-snapshot-[0-9]+)\b", RegexOptions.IgnoreCase)]
    private static partial Regex MinecraftPattern5();

    [GeneratedRegex(@"\b(2[0-9]w[0-9]{1,2}[a-z])\b", RegexOptions.IgnoreCase)]
    private static partial Regex MinecraftPattern6();

    [GeneratedRegex(@"\b([0-9]+\.[0-9]+(?:\.[0-9]+)?)\b", RegexOptions.IgnoreCase)]
    private static partial Regex MinecraftPattern7();

    [GeneratedRegex(@"^\d+\.\d+(?:\.\d+)*$")]
    private static partial Regex OfficialReleasePattern();

    /// <summary>
    /// 判斷 Minecraft 版本字串是否為標準正式發布版本（純數字點分版號，排除 pre、rc、snapshot、experiment 等測試版）
    /// </summary>
    public static bool IsOfficialReleaseVersion(string? version)
    {
        if (string.IsNullOrWhiteSpace(version))
        {
            return false;
        }

        return OfficialReleasePattern().IsMatch(version.AsSpan().Trim());
    }

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

    /// <summary>
    /// 判斷 Minecraft 版本是否支援 Fabric / Quilt（1.14 以上或快照）
    /// </summary>
    public static bool IsFabricCompatible(string minecraftVersion)
    {
        if (string.IsNullOrWhiteSpace(minecraftVersion))
        {
            return false;
        }

        // 明確為舊版 1.0～1.13.x 則不支援
        if (VersionValue.TryParse(minecraftVersion, out var parsed))
        {
            if (parsed.Major == 1 && parsed.Minor < 14)
            {
                return false;
            }
            if (parsed.Major >= 1)
            {
                return true;
            }
        }

        // 快照版本或非標準版本格式（如 24w..., 26.3...），預設相容
        return true;
    }

    /// <summary>
    /// 判斷 Minecraft 版本是否支援 NeoForge（>= 1.20.1）
    /// </summary>
    public static bool IsNeoForgeCompatible(string minecraftVersion)
    {
        if (string.IsNullOrWhiteSpace(minecraftVersion))
        {
            return false;
        }

        if (VersionValue.TryParse(minecraftVersion, out var parsed))
        {
            if (parsed.Major > 1)
            {
                return true;
            }

            if (parsed.Major == 1)
            {
                return parsed.Minor > 20 || (parsed.Minor == 20 && parsed.Patch >= 1);
            }
            return false;
        }

        return false;
    }

    /// <summary>
    /// 從 NeoForge 座標或版本字串推導對應之 Minecraft 版本（支援 47.x -> 1.20.1、20.x/21.x -> 1.20.x/1.21.x 以及 >= 26.x 新版規範）
    /// </summary>
    public static string? DeriveMinecraftVersionFromNeoForge(string? neoForgeVersion)
    {
        if (string.IsNullOrWhiteSpace(neoForgeVersion))
        {
            return null;
        }

        ReadOnlySpan<char> span = neoForgeVersion.AsSpan().Trim();
        int dashOrPlus = span.IndexOfAny('-', '+');
        ReadOnlySpan<char> numericPart = dashOrPlus >= 0 ? span[..dashOrPlus] : span;

        int firstDot = numericPart.IndexOf('.');
        if (firstDot <= 0)
        {
            return null;
        }

        ReadOnlySpan<char> majorSpan = numericPart[..firstDot];
        ReadOnlySpan<char> remainder = numericPart[(firstDot + 1)..];
        int secondDot = remainder.IndexOf('.');
        if (secondDot < 0)
        {
            return null;
        }

        ReadOnlySpan<char> minorSpan = remainder[..secondDot];
        if (!int.TryParse(majorSpan, NumberStyles.None, CultureInfo.InvariantCulture, out int major) ||
            !int.TryParse(minorSpan, NumberStyles.None, CultureInfo.InvariantCulture, out int minor))
        {
            return null;
        }

        if (major == 47)
        {
            return "1.20.1";
        }

        if (major >= 26)
        {
            return minor == 0 ? $"{major}.0" : $"{major}.{minor}";
        }

        if (major >= 20)
        {
            return minor == 0 ? $"1.{major}" : $"1.{major}.{minor}";
        }

        return null;
    }

    /// <summary>
    /// 正規化 Minecraft 版本字串，清除範圍修飾字元或提取有效版本號碼
    /// </summary>
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

    /// <summary>
    /// 從文字中擷取 Minecraft 版本
    /// </summary>
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
