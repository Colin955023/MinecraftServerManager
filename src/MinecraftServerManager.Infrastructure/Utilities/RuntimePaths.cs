using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>執行時路徑管理工具</summary>
public static class RuntimePaths
{
    private const string UserDataEnvironmentVariable = "MSM_USER_DATA_DIR";
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(RuntimePaths));

    /// <summary>取得目前使用者設定檔目錄（%USERPROFILE%）</summary>
    public static string GetUserProfileDir() => Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

    /// <summary>取得目前使用者本機應用程式資料目錄（%LOCALAPPDATA%）</summary>
    public static string GetLocalAppDataDir() => Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);

    /// <summary>取得 Program Files 目錄（依目前行程位元數）</summary>
    public static string GetProgramFilesDir() => Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);

    /// <summary>取得 32 位元 Program Files (x86) 目錄</summary>
    public static string GetProgramFilesX86Dir() => Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);

    /// <summary>取得 Windows System32 目錄</summary>
    public static string GetSystemDir() => Environment.GetFolderPath(Environment.SpecialFolder.System);

    /// <summary>取得目前使用者暫存目錄</summary>
    public static string GetTempDir() => Path.GetTempPath();

    /// <summary>取得應用程式的使用者資料存放目錄</summary>
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

    /// <summary>取得快取資料目錄</summary>
    public static string GetCacheDir() => Path.Combine(GetUserDataDir(), "Cache");

    /// <summary>取得版本清單快取目錄（確保目錄安全存在）</summary>
    public static string GetVersionCacheDir()
    {
        string path = Path.Combine(GetCacheDir(), "versions");
        return SafeFileSystem.ResolveStableDirectory(path, create: true);
    }

    /// <summary>取得模組安裝器快取目錄（確保目錄安全存在）</summary>
    public static string GetInstallerCacheDir()
    {
        string path = Path.Combine(GetCacheDir(), "installers");
        return SafeFileSystem.ResolveStableDirectory(path, create: true);
    }

    /// <summary>取得記錄檔存放目錄</summary>
    public static string GetLogDir() => Path.Combine(GetUserDataDir(), "Logs");

    /// <summary>清理單一執行檔解壓母目錄（%TEMP%\.net\MinecraftServerManager）下非目前執行個體的舊版殘留目錄</summary>
    public static int CleanupStaleSingleFileExtractDirectories(string? currentBaseDirectory = null)
    {
        try
        {
            string currentDir = Path.TrimEndingDirectorySeparator(Path.GetFullPath(currentBaseDirectory ?? AppContext.BaseDirectory));
            string? extractRoot = Path.GetDirectoryName(currentDir);
            if (string.IsNullOrWhiteSpace(extractRoot))
            {
                return 0;
            }

            string expectedRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(Path.Combine(GetTempDir(), ".net", "MinecraftServerManager")));
            if (!string.Equals(Path.TrimEndingDirectorySeparator(extractRoot), expectedRoot, StringComparison.OrdinalIgnoreCase) ||
                !SafeFileSystem.DirectoryExists(expectedRoot))
            {
                return 0;
            }

            int removed = 0;
            foreach (var entry in SafeFileSystem.ListBoundedDirectory(expectedRoot, rejectReparse: false))
            {
                if (!entry.IsDirectory)
                {
                    continue;
                }

                string candidate = Path.TrimEndingDirectorySeparator(Path.GetFullPath(entry.FullPath));
                if (string.Equals(candidate, currentDir, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                if (SafeFileSystem.DeleteWithin(expectedRoot, candidate))
                {
                    removed++;
                }
            }

            if (removed > 0)
            {
                Logger.Information("已清理 {Count} 個舊版單檔解壓暫存目錄", removed);
            }

            return removed;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "清理舊版單檔解壓暫存目錄失敗");
            return 0;
        }
    }
}
