using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>
/// 執行時路徑管理工具
/// </summary>
public static class RuntimePaths
{
    private const string UserDataEnvironmentVariable = "MSM_USER_DATA_DIR";

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
    /// 取得日誌檔案存放目錄
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
}
