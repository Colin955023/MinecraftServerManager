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
    private static readonly string[] QuiltMissingList = ["quilt-server-launch.jar"];
    private static readonly string[] ServerJarMissingList = ["server.jar"];
    private static readonly string[] UnexpectedErrorMissingList = ["未預期的檔案系統錯誤"];

    public ServerIntegrityResult CheckImportantFiles(string serverPath, LoaderKind loader)
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
                                        SafeFileSystem.FileExists(Path.Combine(serverPath, "server.jar")) ||
                                        SafeFileSystem.HasAnyFile(serverPath, "paper*.jar");
                        return hasPaper
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, PaperMissingList);
                    }

                case LoaderKind.Vanilla:
                    {
                        bool hasServer = SafeFileSystem.FileExists(Path.Combine(serverPath, "server.jar")) ||
                                         SafeFileSystem.HasAnyFile(serverPath, "minecraft_server*.jar");
                        return hasServer
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, ServerJarMissingList);
                    }

                case LoaderKind.Fabric:
                    {
                        var missing = new List<string>(2);
                        if (!SafeFileSystem.FileExists(Path.Combine(serverPath, "fabric-server-launch.jar")))
                        {
                            missing.Add("fabric-server-launch.jar");
                        }
                        if (!SafeFileSystem.FileExists(Path.Combine(serverPath, "server.jar")))
                        {
                            missing.Add("server.jar");
                        }
                        return missing.Count == 0
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, missing);
                    }

                case LoaderKind.Quilt:
                    {
                        bool hasQuilt = SafeFileSystem.FileExists(Path.Combine(serverPath, "quilt-server-launch.jar")) ||
                                        SafeFileSystem.FileExists(Path.Combine(serverPath, "server.jar"));
                        return hasQuilt
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, QuiltMissingList);
                    }

                case LoaderKind.NeoForge:
                    return CheckForgeLike(serverPath, "neoforged", "neoforge");

                case LoaderKind.Forge:
                    return SafeFileSystem.HasAnyFile(serverPath, "forge*.jar")
                        ? new ServerIntegrityResult(false, EmptyList)
                        : CheckForgeLike(serverPath, "minecraftforge", "forge");

                default:
                    {
                        bool hasAnyServer = SafeFileSystem.FileExists(Path.Combine(serverPath, "server.jar")) ||
                                            SafeFileSystem.FileExists(Path.Combine(serverPath, "run.bat")) ||
                                            SafeFileSystem.HasAnyFile(serverPath, "*.jar", SearchOption.TopDirectoryOnly);
                        return hasAnyServer
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, ServerJarMissingList);
                    }
            }
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "檢查伺服器完整性時發生非預期例外: {Path}", serverPath);
            return new ServerIntegrityResult(true, UnexpectedErrorMissingList);
        }
    }

    /// <summary>檢查啟動腳本與函式庫內的 win_args.txt</summary>
    private static ServerIntegrityResult CheckForgeLike(string serverPath, string vendor, string artifact)
    {
        var missing = new List<string>(2);
        if (!HasRunScript(serverPath))
        {
            missing.Add("start_server.bat / run.bat");
        }

        string library = Path.Combine(serverPath, "libraries", "net", vendor, artifact);
        if (!SafeFileSystem.HasAnyFile(library, "*args.txt", SearchOption.AllDirectories))
        {
            missing.Add("win_args.txt");
        }

        return missing.Count == 0
            ? new ServerIntegrityResult(false, EmptyList)
            : new ServerIntegrityResult(true, missing);
    }

    private static bool HasRunScript(string serverPath) =>
        SafeFileSystem.FileExists(Path.Combine(serverPath, ServerDefaults.StartServerBatFileName)) ||
        SafeFileSystem.FileExists(Path.Combine(serverPath, "run.bat")) ||
        SafeFileSystem.FileExists(Path.Combine(serverPath, "run.sh"));
}
