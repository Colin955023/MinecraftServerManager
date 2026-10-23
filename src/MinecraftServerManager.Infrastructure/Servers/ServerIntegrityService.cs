using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed class ServerIntegrityService : IServerIntegrityService
{
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
                                        SafeFileSystem.EnumerateFiles(serverPath, "paper*.jar", SearchOption.TopDirectoryOnly).Count > 0;
                        return hasPaper
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, PaperMissingList);
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
                        bool hasQuiltLaunch = SafeFileSystem.FileExists(Path.Combine(serverPath, "quilt-server-launch.jar")) ||
                                              SafeFileSystem.FileExists(Path.Combine(serverPath, "server", "quilt-server-launch.jar"));
                        bool hasVanillaServer = SafeFileSystem.FileExists(Path.Combine(serverPath, "server.jar"));

                        return (hasQuiltLaunch || hasVanillaServer)
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, QuiltMissingList);
                    }

                case LoaderKind.NeoForge:
                    {
                        bool hasRunScript = SafeFileSystem.FileExists(Path.Combine(serverPath, "start_server.bat")) ||
                                            SafeFileSystem.FileExists(Path.Combine(serverPath, "run.bat")) ||
                                            SafeFileSystem.FileExists(Path.Combine(serverPath, "run.sh"));
                        string neoLib = Path.Combine(serverPath, "libraries", "net", "neoforged", "neoforge");
                        bool hasWinArgs = SafeFileSystem.DirectoryExists(neoLib) && SafeFileSystem.EnumerateFiles(neoLib, "*args.txt", SearchOption.AllDirectories).Count > 0;

                        var missing = new List<string>(2);
                        if (!hasRunScript)
                        {
                            missing.Add("start_server.bat / run.bat");
                        }
                        if (!hasWinArgs)
                        {
                            missing.Add("win_args.txt");
                        }

                        return missing.Count == 0
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, missing);
                    }

                case LoaderKind.Forge:
                    {
                        bool hasLegacyForge = SafeFileSystem.EnumerateFiles(serverPath, "forge*.jar", SearchOption.TopDirectoryOnly).Count > 0;
                        if (hasLegacyForge)
                        {
                            return new ServerIntegrityResult(false, EmptyList);
                        }

                        bool hasRunScript = SafeFileSystem.FileExists(Path.Combine(serverPath, "start_server.bat")) ||
                                            SafeFileSystem.FileExists(Path.Combine(serverPath, "run.bat")) ||
                                            SafeFileSystem.FileExists(Path.Combine(serverPath, "run.sh"));
                        string forgeLib = Path.Combine(serverPath, "libraries", "net", "minecraftforge", "forge");
                        bool hasForgeArgs = SafeFileSystem.DirectoryExists(forgeLib) && SafeFileSystem.EnumerateFiles(forgeLib, "*args.txt", SearchOption.AllDirectories).Count > 0;

                        var missing = new List<string>(2);
                        if (!hasRunScript)
                        {
                            missing.Add("start_server.bat / run.bat");
                        }
                        if (!hasForgeArgs)
                        {
                            missing.Add("win_args.txt");
                        }

                        return missing.Count == 0
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, missing);
                    }

                default:
                    {
                        bool hasAnyServer = SafeFileSystem.FileExists(Path.Combine(serverPath, "server.jar")) ||
                                            SafeFileSystem.FileExists(Path.Combine(serverPath, "run.bat")) ||
                                            SafeFileSystem.EnumerateFiles(serverPath, "*.jar", SearchOption.TopDirectoryOnly).Count > 0;
                        return hasAnyServer
                            ? new ServerIntegrityResult(false, EmptyList)
                            : new ServerIntegrityResult(true, ServerJarMissingList);
                    }
            }
        }
        catch
        {
            return new ServerIntegrityResult(true, UnexpectedErrorMissingList);
        }
    }
}
