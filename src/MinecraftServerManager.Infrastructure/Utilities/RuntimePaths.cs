using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>
/// 執行時路徑管理工具
/// </summary>
public static class RuntimePaths
{
    private const string UserDataEnvironmentVariable = "MSM_USER_DATA_DIR";

    /// <summary>
    /// 取得目前使用者設定檔目錄（%USERPROFILE%）
    /// </summary>
    public static string GetUserProfileDir() => Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

    /// <summary>
    /// 取得目前使用者本機應用程式資料目錄（%LOCALAPPDATA%）
    /// </summary>
    public static string GetLocalAppDataDir() => Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);

    /// <summary>
    /// 取得 Program Files 目錄（依目前行程位元數）
    /// </summary>
    public static string GetProgramFilesDir() => Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);

    /// <summary>
    /// 取得 32 位元 Program Files (x86) 目錄
    /// </summary>
    public static string GetProgramFilesX86Dir() => Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);

    /// <summary>
    /// 取得 Windows System32 目錄
    /// </summary>
    public static string GetSystemDir() => Environment.GetFolderPath(Environment.SpecialFolder.System);

    /// <summary>
    /// 取得目前使用者暫存目錄
    /// </summary>
    public static string GetTempDir() => Path.GetTempPath();

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

        string localAppData = GetLocalAppDataDir();
        if (string.IsNullOrWhiteSpace(localAppData))
        {
            localAppData = Path.Combine(GetUserProfileDir(), "AppData", "Local");
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
}
