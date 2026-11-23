using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器啟動目標（JAR、腳本或引數檔）解析</summary>
internal static partial class ServerLaunchTargetResolver
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerLaunchTargetResolver));

    internal static readonly string[] PreferredLaunchJars =
    [
        "paper.jar",
        "fabric-server-launch.jar",
        "quilt-server-launch.jar",
        ServerDefaults.ServerJarFileName,
        "minecraft_server.jar",
    ];

    [GeneratedRegex(@"(?i)@([^\s""]+win_args\.txt)", RegexOptions.CultureInvariant)]
    private static partial Regex WinArgsRegex();

    /// <summary>解析伺服器目錄的啟動目標</summary>
    public static string ResolveLaunchTarget(string serverDirectory, LoaderKind loader = LoaderKind.Unknown)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);

        string stableDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);

        // 1. 優先從 Forge / NeoForge 的 run.bat 提取 @...win_args.txt
        string runBat = Path.Combine(stableDir, ServerDefaults.RunBatFileName);
        if (SafeFileSystem.FileExists(runBat))
        {
            try
            {
                string runBatContent = SafeFileSystem.ReadAllText(runBat);
                var match = WinArgsRegex().Match(runBatContent);
                if (match.Success)
                {
                    string matchedArgs = match.Groups[1].Value.Trim().Trim('"').Replace('\\', '/');
                    string argsFullPath = Path.GetFullPath(matchedArgs, stableDir);
                    if (SafeFileSystem.IsPathWithin(stableDir, argsFullPath, strict: true) && SafeFileSystem.FileExists(argsFullPath))
                    {
                        return "@" + matchedArgs;
                    }

                    Logger.Warning("run.bat 引用之引數檔不存在或超出伺服器目錄，改用其他啟動目標: {Target}", argsFullPath);
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "解析 run.bat 啟動參數失敗");
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
            .Where(static e => !e.IsDirectory && ModHelpers.IsJarFileName(e.FullPath))
            .Select(static e => Path.GetFileName(e.FullPath))
            .ToList();

        var layout = LoaderLayout.For(loader);
        string? preferredByLoader = jarFiles.FirstOrDefault(layout.IsLaunchJarName);
        if (preferredByLoader is not null)
        {
            return preferredByLoader;
        }

        // 4. 通用 Paper JAR 搜尋
        string? paperJar = jarFiles.FirstOrDefault(LoaderLayout.IsPaperJarName);
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

        // 7. 改用 run.bat 或預設 server.jar
        if (SafeFileSystem.FileExists(runBat))
        {
            return ServerDefaults.RunBatFileName;
        }

        return ServerDefaults.ServerJarFileName;
    }

    /// <summary>具 win_args.txt 函式庫之載入器（依序搜尋）</summary>
    private static readonly LoaderKind[] WinArgsLoaderKinds = [LoaderKind.Forge, LoaderKind.NeoForge];

    internal static string? FindLibraryWinArgs(string directory)
    {
        foreach (var kind in WinArgsLoaderKinds)
        {
            string libDir = LoaderLayout.For(kind).GetLibraryDirectory(directory);
            if (!SafeFileSystem.DirectoryExists(libDir))
            {
                continue;
            }

            // 同時存在多個版本時取最新版
            foreach (string sub in SafeFileSystem.EnumerateDirectories(libDir).OrderDescending(VersionNameComparer.Instance))
            {
                string winArgs = Path.Combine(sub, ServerDefaults.WinArgsFileName);
                if (SafeFileSystem.FileExists(winArgs))
                {
                    return "@" + Path.GetRelativePath(directory, winArgs).Replace('\\', '/');
                }
            }
        }

        return null;
    }
}
