using System.Text.RegularExpressions;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器啟動目標（JAR、腳本或引數檔）解析輔助工具
/// </summary>
internal static partial class ServerLaunchTargetResolver
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerLaunchTargetResolver");

    internal static readonly string[] PreferredLaunchJars =
    [
        "paper.jar",
        "fabric-server-launch.jar",
        "quilt-server-launch.jar",
        "server.jar",
        "minecraft_server.jar",
    ];

    [GeneratedRegex(@"(?i)@([^\s""]+win_args\.txt)")]
    private static partial Regex WinArgsRegex();

    /// <summary>
    /// 解析指定伺服器目錄之最佳啟動目標檔名或引數檔標記（如 @args.txt、server.jar、run.bat 等）
    /// </summary>
    public static string ResolveLaunchTarget(string serverDirectory, LoaderKind loader = LoaderKind.Unknown)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);

        string stableDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);

        // 1. 優先從 Forge / NeoForge 的 run.bat 提取 @...win_args.txt
        string runBat = Path.Combine(stableDir, "run.bat");
        if (SafeFileSystem.FileExists(runBat))
        {
            try
            {
                string runBatContent = SafeFileSystem.ReadAllText(runBat);
                var match = WinArgsRegex().Match(runBatContent);
                if (match.Success)
                {
                    string matchedArgs = match.Groups[1].Value.Trim().Trim('"').Replace('\\', '/');
                    return "@" + matchedArgs;
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning("解析 run.bat 啟動參數異常: {0}", ex.Message);
            }
        }

        // 2. 檢查 Forge / NeoForge libraries 中的 win_args.txt
        string? libraryWinArgs = FindLibraryWinArgs(stableDir);
        if (libraryWinArgs is not null)
        {
            return libraryWinArgs;
        }

        // 3. 若指定了載入器，優先依照載入器特徵尋找目標 JAR
        var jarFiles = SafeFileSystem.ListBoundedDirectory(stableDir, rejectReparse: false)
            .Where(static e => !e.IsDirectory && e.FullPath.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
            .Select(static e => Path.GetFileName(e.FullPath))
            .ToList();

        string? preferredByLoader = loader switch
        {
            LoaderKind.Paper => jarFiles.FirstOrDefault(static f => f.StartsWith("paper", StringComparison.OrdinalIgnoreCase)),
            LoaderKind.Fabric => jarFiles.FirstOrDefault(static f => f.StartsWith("fabric-server-launch", StringComparison.OrdinalIgnoreCase)),
            LoaderKind.Quilt => jarFiles.FirstOrDefault(static f => f.StartsWith("quilt-server-launch", StringComparison.OrdinalIgnoreCase)),
            LoaderKind.Forge => jarFiles.FirstOrDefault(static f => f.StartsWith("forge", StringComparison.OrdinalIgnoreCase) && !f.Contains("installer", StringComparison.OrdinalIgnoreCase)),
            LoaderKind.NeoForge => jarFiles.FirstOrDefault(static f => f.StartsWith("neoforge", StringComparison.OrdinalIgnoreCase) && !f.Contains("installer", StringComparison.OrdinalIgnoreCase)),
            _ => null
        };

        if (preferredByLoader is not null)
        {
            return preferredByLoader;
        }

        // 4. 通用 Paper JAR 搜尋
        string? paperJar = jarFiles.FirstOrDefault(static f => f.StartsWith("paper", StringComparison.OrdinalIgnoreCase));
        if (paperJar is not null)
        {
            return paperJar;
        }

        // 5. 常用標準 JAR 候選清單
        foreach (string candidate in PreferredLaunchJars)
        {
            if (jarFiles.Any(f => string.Equals(f, candidate, StringComparison.OrdinalIgnoreCase)))
            {
                return candidate;
            }
        }

        // 6. 其他非 installer 之 JAR 檔
        string? anyJar = jarFiles.FirstOrDefault(static name => !name.Contains("installer", StringComparison.OrdinalIgnoreCase));
        if (anyJar is not null)
        {
            return anyJar;
        }

        // 7. 回退至 run.bat 或預設 server.jar
        if (SafeFileSystem.FileExists(runBat))
        {
            return "run.bat";
        }

        return "server.jar";
    }

    internal static string? FindLibraryWinArgs(string directory)
    {
        string forgeLib = Path.Combine(directory, "libraries", "net", "minecraftforge", "forge");
        if (SafeFileSystem.DirectoryExists(forgeLib))
        {
            foreach (string sub in SafeFileSystem.EnumerateDirectories(forgeLib))
            {
                string winArgs = Path.Combine(sub, "win_args.txt");
                if (SafeFileSystem.FileExists(winArgs))
                {
                    return "@" + Path.GetRelativePath(directory, winArgs).Replace('\\', '/');
                }
            }
        }

        string neoLib = Path.Combine(directory, "libraries", "net", "neoforged", "neoforge");
        if (SafeFileSystem.DirectoryExists(neoLib))
        {
            foreach (string sub in SafeFileSystem.EnumerateDirectories(neoLib))
            {
                string winArgs = Path.Combine(sub, "win_args.txt");
                if (SafeFileSystem.FileExists(winArgs))
                {
                    return "@" + Path.GetRelativePath(directory, winArgs).Replace('\\', '/');
                }
            }
        }

        return null;
    }
}
