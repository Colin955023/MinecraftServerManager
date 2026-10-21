using System.Diagnostics.CodeAnalysis;
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
    /// 取得記錄檔存放目錄
    /// </summary>
    public static string GetLogDir() => Path.Combine(GetUserDataDir(), "Logs");

    /// <summary>
    /// 判斷目前是否為開發或偵錯環境
    /// </summary>
    [UnconditionalSuppressMessage("SingleFile", "IL3000:Avoid accessing Assembly.Location when publishing as a single-file", Justification = "藉由 Location 為空字串之特性判定是否為 Single-File 封裝")]
    public static bool IsDevelopmentEnvironment()
    {
        if (string.Equals(Environment.GetEnvironmentVariable("MSM_DEBUG_LOG"), "1", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        // 判定是否為 Single-File 發布之獨立 EXE：
        // 1. .NET 官方 Single-File Host 在啟動打包應用程式時會主動在 AppContext 注入 APP_CONTEXT_PUBLISH_SINGLE_FILE == true (亦可能為字串 "true")
        // 2. 於 Single-File bundle 模式下，進入點組件嵌入於 bundle 內，其 Assembly.Location 依官方規範為空字串 ("")
        object? singleFileFlag = AppContext.GetData("APP_CONTEXT_PUBLISH_SINGLE_FILE");
#pragma warning disable IL3000 // 藉由 Location 為空字串之特性判定是否為 Single-File 封裝
        bool isSingleFilePackaged = singleFileFlag is true
            || (singleFileFlag is string str && string.Equals(str, "true", StringComparison.OrdinalIgnoreCase))
            || string.IsNullOrEmpty(System.Reflection.Assembly.GetEntryAssembly()?.Location);
#pragma warning restore IL3000

        return !isSingleFilePackaged;
    }
}
