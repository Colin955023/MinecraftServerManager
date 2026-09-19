using System.Text.RegularExpressions;
using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Core.Utilities;

/// <summary>
/// 依據 Minecraft 版本提供 Java 建議版本工具
/// </summary>
public static partial class MinecraftJavaRecommendation
{
    [GeneratedRegex(@"^(\d{2})w(\d{2})[a-z]$", RegexOptions.IgnoreCase)]
    private static partial Regex SnapshotPattern();

    [GeneratedRegex(@"\d+")]
    private static partial Regex DigitsPattern();

    /// <summary>
    /// 取得指定 Minecraft 版本推薦的 Java 主要版本
    /// </summary>
    public static int GetRecommendedMajor(MinecraftVersion version) =>
        GetRecommendedMajor(version.Value);

    /// <summary>
    /// 取得指定 Minecraft 版本文字推薦的 Java 主要版本
    /// </summary>
    public static int GetRecommendedMajor(string? minecraftVersion)
    {
        if (string.IsNullOrWhiteSpace(minecraftVersion))
        {
            return 21;
        }

        string cleaned = minecraftVersion.Trim();

        // 檢查快照格式 (例如 24w14a)
        var snapshotMatch = SnapshotPattern().Match(cleaned);
        if (snapshotMatch.Success &&
            int.TryParse(snapshotMatch.Groups[1].Value, out int year))
        {
            if (year >= 24)
            {
                return 21;
            }

            if (year >= 22)
            {
                return 17;
            }

            if (year == 21)
            {
                if (int.TryParse(snapshotMatch.Groups[2].Value, out int week) && week >= 37)
                {
                    return 17;
                }

                return 16;
            }

            return 8;
        }

        // 一般發行版格式比對
        if (VersionValue.TryParse(cleaned, out var semver))
        {
            if (semver.Major > 1)
            {
                return 21;
            }

            if (semver.Major == 1)
            {
                if (semver.Minor <= 16)
                {
                    return 8;
                }

                if (semver.Minor == 17)
                {
                    return 16;
                }

                if (semver.Minor < 20)
                {
                    return 17;
                }

                if (semver.Minor == 20)
                {
                    return semver.Patch >= 5 ? 21 : 17;
                }

                return 21;
            }

            return 8;
        }

        // 正規表達式容錯比對
        var matches = DigitsPattern().Matches(cleaned);
        if (matches.Count >= 2 &&
            int.TryParse(matches[0].Value, out int major) &&
            int.TryParse(matches[1].Value, out int minor))
        {
            if (major == 1)
            {
                if (minor <= 16)
                {
                    return 8;
                }

                if (minor == 17)
                {
                    return 16;
                }

                if (minor < 20)
                {
                    return 17;
                }

                if (minor == 20)
                {
                    int patch = matches.Count >= 3 && int.TryParse(matches[2].Value, out int p) ? p : 0;
                    return patch >= 5 ? 21 : 17;
                }

                return 21;
            }
        }

        return 21;
    }
}
