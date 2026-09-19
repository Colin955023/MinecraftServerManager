using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Utilities;

/// <summary>
/// 模組 metadata 與版本篩選純語意工具類別
/// </summary>
public static class ModSemantics
{
    public const string ModrinthPreferredHashAlgorithm = "sha512";

    /// <summary>
    /// 正規化識別碼字串（小寫並去除前後空白）
    /// </summary>
    public static string NormalizeIdentifier(string? value) => value?.Trim().ToLowerInvariant() ?? string.Empty;

    /// <summary>
    /// 正規化 Modrinth 雜湊演算法名稱
    /// </summary>
    public static string NormalizeHashAlgorithm(string? algorithm)
    {
        string normalized = NormalizeIdentifier(algorithm);
        if (normalized is "sha512" or "sha1" or "sha256")
        {
            return normalized;
        }

        return ModrinthPreferredHashAlgorithm;
    }

    /// <summary>
    /// 回傳版本類型的排序優先權數值
    /// </summary>
    public static int GetVersionTypePriority(string? versionType)
    {
        string normalized = NormalizeIdentifier(versionType);
        if (normalized == "release")
        {
            return 3;
        }
        if (normalized is "beta" or "snapshot")
        {
            return 2;
        }
        if (normalized == "alpha")
        {
            return 1;
        }
        return 0;
    }

    /// <summary>
    /// 判斷版本類型是否在允許範圍內（正式版或 Beta 版）
    /// </summary>
    public static bool IsAllowedVersionType(string? versionType)
    {
        string normalized = NormalizeIdentifier(versionType);
        if (normalized is "" or "release" or "stable" or "beta")
        {
            return true;
        }

        return normalized.Contains("beta", StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// 從版本清單中挑選最適合的候選版本
    /// </summary>
    public static OnlineModVersion? SelectBestModVersion(IEnumerable<OnlineModVersion> versions)
    {
        return versions
            .OrderByDescending(v => v.PrimaryFile != null ? 1 : 0)
            .ThenByDescending(v => GetVersionTypePriority(v.VersionType))
            .ThenByDescending(v => v.DatePublished)
            .ThenByDescending(v => v.VersionNumber)
            .FirstOrDefault();
    }
}
