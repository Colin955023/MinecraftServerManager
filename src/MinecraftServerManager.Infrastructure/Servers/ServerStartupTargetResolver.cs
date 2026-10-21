namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器初次啟動目標解析器：依「統一啟動腳本、啟動腳本、伺服器核心」的順序決定要執行的檔案
/// </summary>
public static class ServerStartupTargetResolver
{
    private const string UnifiedScript = "start_server.bat";
    private const string FallbackScript = "run.bat";
    private const string DefaultCoreJar = "server.jar";

    /// <summary>
    /// 解析伺服器目錄中初次啟動應執行的檔案名稱
    /// </summary>
    public static string Resolve(string serverDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);

        if (File.Exists(Path.Combine(serverDirectory, UnifiedScript)))
        {
            return UnifiedScript;
        }

        if (File.Exists(Path.Combine(serverDirectory, FallbackScript)))
        {
            return FallbackScript;
        }

        if (File.Exists(Path.Combine(serverDirectory, DefaultCoreJar)))
        {
            return DefaultCoreJar;
        }

        string? firstJar = Directory.EnumerateFiles(serverDirectory, "*.jar").FirstOrDefault();
        return firstJar is not null ? Path.GetFileName(firstJar) : DefaultCoreJar;
    }
}
