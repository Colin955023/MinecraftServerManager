using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed class ServerIntegrityService : IServerIntegrityService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerIntegrityService));
    private static readonly string[] EmptyList = [];
    private static readonly string[] DirectoryNotFoundMissingList = ["伺服器目錄不存在"];
    private static readonly string[] PaperMissingList = ["paper.jar"];
    private static readonly string[] ServerJarMissingList = [ServerDefaults.ServerJarFileName];
    private static readonly string[] UnexpectedErrorMissingList = ["未預期的檔案系統錯誤"];

    public Task<ServerIntegrityResult> CheckImportantFilesAsync(string serverPath, LoaderKind loader, CancellationToken cancellationToken = default) =>
        Task.Run(() => CheckImportantFiles(serverPath, loader), cancellationToken);

    private static ServerIntegrityResult CheckImportantFiles(string serverPath, LoaderKind loader)
    {
        if (string.IsNullOrWhiteSpace(serverPath) || !SafeFileSystem.DirectoryExists(serverPath))
        {
            return new ServerIntegrityResult(true, DirectoryNotFoundMissingList);
        }

        try
        {
            switch (loader)
            {
                case LoaderKind.Paper:
                    {
                        bool hasPaper = SafeFileSystem.FileExists(Path.Combine(serverPath, "paper.jar")) ||
                                        SafeFileSystem.FileExists(Path.Combine(serverPath, ServerDefaults.ServerJarFileName)) ||
                                        SafeFileSystem.HasAnyFile(serverPath, "paper*.jar");
                        return hasPaper
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, PaperMissingList);
                    }

                case LoaderKind.Vanilla:
                    {
                        bool hasServer = SafeFileSystem.FileExists(Path.Combine(serverPath, ServerDefaults.ServerJarFileName)) ||
                                         SafeFileSystem.HasAnyFile(serverPath, "minecraft_server*.jar");
                        return hasServer
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, ServerJarMissingList);
                    }

                // Fabric 與 Quilt 皆由啟動器 jar 載入原版 server.jar
                case LoaderKind.Fabric:
                case LoaderKind.Quilt:
                    return CheckLauncherWithServerJar(serverPath, LoaderLayout.For(loader).LauncherJarFileName);

                case LoaderKind.NeoForge:
                    return CheckForgeLike(serverPath, LoaderKind.NeoForge);

                case LoaderKind.Forge:
                    return HasForgeServerJar(serverPath)
                        ? new ServerIntegrityResult(false, EmptyList)
                        : CheckForgeLike(serverPath, LoaderKind.Forge);

                default:
                    {
                        bool hasAnyServer = SafeFileSystem.FileExists(Path.Combine(serverPath, ServerDefaults.ServerJarFileName)) ||
                                            SafeFileSystem.FileExists(Path.Combine(serverPath, ServerDefaults.RunBatFileName)) ||
                                            SafeFileSystem.HasAnyFile(serverPath, "*.jar", SearchOption.TopDirectoryOnly);
                        return hasAnyServer
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, ServerJarMissingList);
                    }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "檢查伺服器完整性時發生非預期例外: {Path}", serverPath);
            return new ServerIntegrityResult(true, UnexpectedErrorMissingList);
        }
    }

    private static ServerIntegrityResult CheckLauncherWithServerJar(string serverPath, string launcherJar)
    {
        var missing = new List<string>(2);
        if (!SafeFileSystem.FileExists(Path.Combine(serverPath, launcherJar)))
        {
            missing.Add(launcherJar);
        }
        if (!SafeFileSystem.FileExists(Path.Combine(serverPath, ServerDefaults.ServerJarFileName)))
        {
            missing.Add(ServerDefaults.ServerJarFileName);
        }
        return missing.Count == 0
            ? new ServerIntegrityResult(false, EmptyList)
            : new ServerIntegrityResult(true, missing);
    }

    /// <summary>舊版 Forge 根目錄伺服器 jar（排除安裝器）</summary>
    private static bool HasForgeServerJar(string serverPath) =>
        SafeFileSystem.EnumerateFiles(serverPath, LoaderLayout.For(LoaderKind.Forge).LaunchJarPrefix + "*.jar")
            .Any(static path => !Path.GetFileNameWithoutExtension(path).EndsWith("-installer", StringComparison.OrdinalIgnoreCase));

    /// <summary>檢查 Windows 啟動腳本與函式庫內的 win_args.txt</summary>
    private static ServerIntegrityResult CheckForgeLike(string serverPath, LoaderKind loader)
    {
        var missing = new List<string>(2);
        if (!HasRunScript(serverPath))
        {
            missing.Add($"{ServerDefaults.StartServerBatFileName} / {ServerDefaults.RunBatFileName}");
        }

        string library = LoaderLayout.For(loader).GetLibraryDirectory(serverPath);
        if (!SafeFileSystem.HasAnyFile(library, ServerDefaults.WinArgsFileName, SearchOption.AllDirectories))
        {
            missing.Add(ServerDefaults.WinArgsFileName);
        }

        return missing.Count == 0
            ? new ServerIntegrityResult(false, EmptyList)
            : new ServerIntegrityResult(true, missing);
    }

    private static bool HasRunScript(string serverPath) =>
        SafeFileSystem.FileExists(Path.Combine(serverPath, ServerDefaults.StartServerBatFileName)) ||
        SafeFileSystem.FileExists(Path.Combine(serverPath, ServerDefaults.RunBatFileName));
}
