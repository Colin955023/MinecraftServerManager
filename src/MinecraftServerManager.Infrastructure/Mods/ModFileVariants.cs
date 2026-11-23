using System.Diagnostics.CodeAnalysis;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>模組檔案啟用／停用變體路徑解析與管理輔助</summary>
internal static class ModFileVariants
{
    /// <summary>依檔名或主幹解析啟用／停用兩種路徑；超出目錄邊界時回傳 false</summary>
    public static bool TryGetPaths(
        string modsDir,
        string? fileNameOrStem,
        [NotNullWhen(true)] out string? enabledPath,
        [NotNullWhen(true)] out string? disabledPath,
        bool requireModExtension = true)
    {
        enabledPath = disabledPath = null;
        string name = Path.GetFileName(fileNameOrStem ?? string.Empty);
        if (string.IsNullOrWhiteSpace(name) || (requireModExtension && !ModHelpers.IsModFileName(name)))
        {
            return false;
        }

        string stem = ModHelpers.ModFilenameStem(name);
        if (string.IsNullOrWhiteSpace(stem))
        {
            return false;
        }

        string enabled = Path.Combine(modsDir, ModHelpers.ToEnabledModFileName(stem));
        string disabled = Path.Combine(modsDir, ModHelpers.ToDisabledModFileName(stem));
        if (!SafeFileSystem.IsPathWithin(modsDir, enabled, strict: false) || !SafeFileSystem.IsPathWithin(modsDir, disabled, strict: false))
        {
            return false;
        }

        enabledPath = enabled;
        disabledPath = disabled;
        return true;
    }

    /// <summary>嘗試刪除模組之啟用與停用兩種變體路徑；回傳是否找到任何變體且全數刪除成功</summary>
    public static (bool Found, bool AllSucceeded) DeleteVariants(string modsDir, string enabledPath, string disabledPath)
    {
        bool found = false;
        bool allSucceeded = true;

        foreach (string candidate in (ReadOnlySpan<string>)[enabledPath, disabledPath])
        {
            if (!SafeFileSystem.FileExists(candidate))
            {
                continue;
            }

            found = true;
            if (!SafeFileSystem.DeleteWithin(modsDir, candidate))
            {
                allSucceeded = false;
            }
        }

        return (found, allSucceeded);
    }
}
