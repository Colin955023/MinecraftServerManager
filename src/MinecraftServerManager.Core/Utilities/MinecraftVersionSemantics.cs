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

    [GeneratedRegex(@"[+]|-mc|-fabric|-forge|-kotlin|-api|-universal|-common|-b[0-9]*|-beta|-alpha|-snapshot", RegexOptions.IgnoreCase)]
    private static partial Regex ModVersionCleanPattern();

    [GeneratedRegex(@"\d+")]
    private static partial Regex DigitsPattern();

    [GeneratedRegex(@"\b(vanilla|official|minecraft server)\b", RegexOptions.IgnoreCase)]
    private static partial Regex VanillaLoaderPattern();

    [GeneratedRegex(@"\b(fabric|neoforge|forge|quilt)\b", RegexOptions.IgnoreCase)]
    private static partial Regex KnownLoaderPattern();

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

        string trimmed = version.Trim();
        return OfficialReleasePattern().IsMatch(trimmed);
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

    private static readonly string[] SubstringLoaders = ["fabric", "quilt", "neoforge"];

    /// <summary>
    /// 判斷 Minecraft 版本是否支援 Fabric / Quilt（1.14 以上或快照）
    /// </summary>
    public static bool IsFabricCompatible(string minecraftVersion)
    {
        if (string.IsNullOrWhiteSpace(minecraftVersion))
        {
            return false;
        }

        string trimmed = minecraftVersion.Trim();

        // 明確為舊版 1.0 ~ 1.13.x 則不支援
        if (VersionValue.TryParse(trimmed, out var parsed))
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

        var matches = DigitsPattern().Matches(trimmed);
        if (matches.Count >= 2 && int.TryParse(matches[0].Value, out int major) && int.TryParse(matches[1].Value, out int minor))
        {
            if (major == 1 && minor < 14)
            {
                return false;
            }
            return true;
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

        string trimmed = minecraftVersion.Trim();
        if (VersionValue.TryParse(trimmed, out var parsed))
        {
            if (parsed.Major > 1)
            {
                return true;
            }

            if (parsed.Major == 1)
            {
                if (parsed.Minor > 20)
                {
                    return true;
                }

                if (parsed.Minor == 20 && parsed.Patch >= 1)
                {
                    return true;
                }
            }
            return false;
        }

        var matches = DigitsPattern().Matches(trimmed);
        if (matches.Count >= 2 && int.TryParse(matches[0].Value, out int major) && int.TryParse(matches[1].Value, out int minor))
        {
            if (major > 1)
            {
                return true;
            }

            if (major == 1 && minor > 20)
            {
                return true;
            }

            if (major == 1 && minor == 20 && matches.Count >= 3 && int.TryParse(matches[2].Value, out int patch) && patch >= 1)
            {
                return true;
            }
        }

        return false;
    }

    /// <summary>
    /// 將載入器名稱正規化為標準領域值
    /// </summary>
    public static string StandardizeLoaderType(string? loaderType, string? loaderVersion = "")
    {
        string normalized = loaderType?.Trim().ToLowerInvariant() ?? string.Empty;
        if (normalized is "fabric" or "forge" or "quilt" or "neoforge")
        {
            return normalized;
        }

        if (normalized is "vanilla" or "原版")
        {
            return "vanilla";
        }

        if (normalized is "unknown" or "未知" or "")
        {
            string version = loaderVersion?.Trim().ToLowerInvariant() ?? string.Empty;
            if (version.Length > 0 && version.Replace(".", string.Empty).All(char.IsAsciiDigit))
            {
                return "forge";
            }

            foreach (string candidate in SubstringLoaders)
            {
                if (version.Contains(candidate, StringComparison.OrdinalIgnoreCase))
                {
                    return candidate;
                }
            }

            return "unknown";
        }

        if (normalized.Contains("vanilla", StringComparison.OrdinalIgnoreCase)
            || normalized.Contains("official", StringComparison.OrdinalIgnoreCase))
        {
            return "vanilla";
        }

        return "unknown";
    }

    /// <summary>
    /// 清除模組版本字串中的載入器與發行階段後綴
    /// </summary>
    public static string CleanModVersion(string? version)
    {
        if (string.IsNullOrWhiteSpace(version) || version == "未知")
        {
            return version ?? string.Empty;
        }

        var match = ModVersionCleanPattern().Match(version);
        string cleaned = match.Success ? version[..match.Index] : version;
        cleaned = TrailingJunkPattern().Replace(cleaned, string.Empty);
        return cleaned.Trim();
    }

    [GeneratedRegex(@"[^\w.]+$")]
    private static partial Regex TrailingJunkPattern();

    /// <summary>
    /// 正規化 Minecraft 版本字串，清除範圍修飾字元或提取有效版本號
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

    /// <summary>
    /// 從文字辨認受支援的伺服器載入器
    /// </summary>
    public static string DetectLoaderFromText(string? text)
    {
        string normalized = text?.Trim().ToLowerInvariant() ?? string.Empty;
        if (VanillaLoaderPattern().IsMatch(normalized))
        {
            return "vanilla";
        }

        var match = KnownLoaderPattern().Match(normalized);
        if (match.Success)
        {
            return match.Groups[1].Value.ToLowerInvariant();
        }

        return "unknown";
    }
}
