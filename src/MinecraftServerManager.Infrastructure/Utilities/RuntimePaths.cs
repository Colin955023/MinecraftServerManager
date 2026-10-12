using System.Text.RegularExpressions;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>
/// 執行時路徑管理工具
/// </summary>
public static partial class RuntimePaths
{
    private const string UserDataEnvironmentVariable = "MSM_USER_DATA_DIR";

    [GeneratedRegex(@"^[0-9A-Za-z][0-9A-Za-z._-]*$")]
    private static partial Regex SafeVersionNameRegex();

    [GeneratedRegex(@"^\d+(?:\.\d+){1,4}(?:[-._][0-9A-Za-z.-]+)?$")]
    private static partial Regex VersionPatternRegex();

    /// <summary>
    /// 取得應用程式的使用者資料存放目錄
    /// </summary>
    public static string GetUserDataDir()
    {
        string? overridePath = Environment.GetEnvironmentVariable(UserDataEnvironmentVariable);
        if (!string.IsNullOrWhiteSpace(overridePath))
        {
            return Path.GetFullPath(overridePath);
        }

        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(localAppData))
        {
            localAppData = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "AppData", "Local");
        }

        return Path.Combine(localAppData, "Programs", "MinecraftServerManager");
    }

    /// <summary>
    /// 取得快取資料目錄
    /// </summary>
    public static string GetCacheDir() => Path.Combine(GetUserDataDir(), "Cache");

    /// <summary>
    /// 取得版本列表快取目錄（確保目錄安全存在）
    /// </summary>
    public static string GetVersionCacheDir()
    {
        string path = Path.Combine(GetCacheDir(), "versions");
        return SafeFileSystem.ResolveStableDirectory(path, create: true);
    }

    /// <summary>
    /// 取得模組安裝器快取目錄（確保目錄安全存在）
    /// </summary>
    public static string GetInstallerCacheDir()
    {
        string path = Path.Combine(GetCacheDir(), "installers");
        return SafeFileSystem.ResolveStableDirectory(path, create: true);
    }

    /// <summary>
    /// 取得記錄檔存放目錄
    /// </summary>
    public static string GetLogDir() => Path.Combine(GetUserDataDir(), "Logs");

    /// <summary>
    /// 判斷目前是否為打包執行的單一檔案環境
    /// </summary>
    public static bool IsPackaged()
    {
        string? processPath = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(processPath))
        {
            return false;
        }

        string baseDir = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        string? procDir = Path.GetDirectoryName(processPath)?.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

        return !string.IsNullOrEmpty(procDir) && !string.Equals(baseDir, procDir, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// 判斷目前是否為開發環境
    /// </summary>
    public static bool IsDevelopmentEnvironment() => !IsPackaged();

    /// <summary>
    /// 清理可辨識且已不再使用的舊版本暫存快取目錄（相容舊版本快取目錄之維護機制）
    /// </summary>
    public static void CleanupOldVersionCaches(string currentVersion)
    {
        if (string.IsNullOrWhiteSpace(currentVersion))
        {
            return;
        }

        string currentName = currentVersion.Trim();
        if (!SafeVersionNameRegex().IsMatch(currentName))
        {
            return;
        }

        string root = GetUserDataDir();
        if (!Directory.Exists(root))
        {
            return;
        }

        try
        {
            var entries = SafeFileSystem.ListBoundedDirectory(root);
            foreach (var entry in entries)
            {
                if (!entry.IsDirectory)
                {
                    continue;
                }

                string name = Path.GetFileName(entry.FullPath);
                if (string.Equals(name, currentName, StringComparison.OrdinalIgnoreCase) ||
                    name.StartsWith(currentName + ".", StringComparison.OrdinalIgnoreCase) ||
                    name.StartsWith(currentName + "-", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(name, "Cache", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(name, "Logs", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(name, "servers", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                if (VersionPatternRegex().IsMatch(name))
                {
                    SafeFileSystem.DeleteWithin(root, entry.FullPath);
                }
            }
        }
        catch
        {
            // 清理舊版本快取失敗不影響主程序運作
        }
    }
}
