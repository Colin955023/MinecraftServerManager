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
    /// 從版本清單中挑選最適合的候選版本（單次線性掃描 O(N)，零配置）
    /// </summary>
    public static OnlineModVersion? SelectBestModVersion(IEnumerable<OnlineModVersion> versions)
    {
        if (versions is null)
        {
            return null;
        }

        OnlineModVersion? best = null;
        int bestHasFile = -1;
        int bestTypePriority = -1;
        string bestDate = string.Empty;
        string bestVersionNumber = string.Empty;

        foreach (var v in versions)
        {
            if (v is null)
            {
                continue;
            }

            int hasFile = v.PrimaryFile != null ? 1 : 0;
            int typePriority = GetVersionTypePriority(v.VersionType);
            string date = v.DatePublished ?? string.Empty;
            string verNum = v.VersionNumber ?? string.Empty;

            if (best is null)
            {
                best = v;
                bestHasFile = hasFile;
                bestTypePriority = typePriority;
                bestDate = date;
                bestVersionNumber = verNum;
                continue;
            }

            if (hasFile != bestHasFile)
            {
                if (hasFile > bestHasFile)
                {
                    best = v;
                    bestHasFile = hasFile;
                    bestTypePriority = typePriority;
                    bestDate = date;
                    bestVersionNumber = verNum;
                }
                continue;
            }

            if (typePriority != bestTypePriority)
            {
                if (typePriority > bestTypePriority)
                {
                    best = v;
                    bestHasFile = hasFile;
                    bestTypePriority = typePriority;
                    bestDate = date;
                    bestVersionNumber = verNum;
                }
                continue;
            }

            int dateCmp = string.Compare(date, bestDate, StringComparison.Ordinal);
            if (dateCmp != 0)
            {
                if (dateCmp > 0)
                {
                    best = v;
                    bestHasFile = hasFile;
                    bestTypePriority = typePriority;
                    bestDate = date;
                    bestVersionNumber = verNum;
                }
                continue;
            }

            if (string.Compare(verNum, bestVersionNumber, StringComparison.Ordinal) > 0)
            {
                best = v;
                bestHasFile = hasFile;
                bestTypePriority = typePriority;
                bestDate = date;
                bestVersionNumber = verNum;
            }
        }

        return best;
    }
}
