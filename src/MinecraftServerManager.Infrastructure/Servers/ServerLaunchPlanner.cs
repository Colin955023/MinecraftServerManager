using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器啟動規劃器實作
/// </summary>
public sealed class ServerLaunchPlanner : IServerLaunchPlanner
{
    public ServerLaunchPlan CreatePlan(ServerConfig config, ServerInspection inspection, string? javaPath = null)
    {
        ArgumentNullException.ThrowIfNull(config);
        ArgumentNullException.ThrowIfNull(inspection);

        string stableDir = SafeFileSystem.ResolveStableDirectory(config.Path);
        string targetFile = !string.IsNullOrWhiteSpace(inspection.LaunchTarget.Value)
            ? inspection.LaunchTarget.Value.Trim()
            : "server.jar";

        // 防範 Path Traversal：僅允許相對於 stableDir 的內部檔案
        string targetFullPath = Path.GetFullPath(Path.Combine(stableDir, targetFile));
        if (!SafeFileSystem.IsPathWithin(stableDir, targetFullPath, strict: false))
        {
            throw new SafeFileSystemException($"偵測到非法的啟動目標路徑越界：{targetFile}");
        }

        bool isScript = targetFile.EndsWith(".bat", StringComparison.OrdinalIgnoreCase);

        if (isScript)
        {
            return new ServerLaunchPlan(
                JavaExecutable: targetFullPath,
                WorkingDirectory: stableDir,
                Arguments: [],
                Loader: config.LoaderType,
                MinMemoryMb: config.MemoryMinMb ?? 1024,
                MaxMemoryMb: config.MemoryMaxMb,
                IsScript: true);
        }

        string executableJava = !string.IsNullOrWhiteSpace(javaPath)
            ? javaPath
            : "java";

        int min = config.MemoryMinMb ?? (config.MemoryMaxMb > 1024 ? 1024 : config.MemoryMaxMb);
        var args = new List<string>
        {
            $"-Xms{min}M",
            $"-Xmx{config.MemoryMaxMb}M"
        };

        // 注入推薦 GC 與 JVM 參數
        var customArgs = config.JvmArgs ?? [];
        if (!JvmOptionPolicy.HasGcOption(customArgs))
        {
            var recommendedGc = JvmOptionPolicy.RecommendGcArgs(config.MemoryMaxMb, loaderType: config.LoaderType.ToString());
            args.AddRange(recommendedGc);
        }

        args.AddRange(customArgs);

        args.Add("-jar");
        args.Add(targetFile);
        args.Add("nogui");

        return new ServerLaunchPlan(
            JavaExecutable: executableJava,
            WorkingDirectory: stableDir,
            Arguments: args,
            Loader: config.LoaderType,
            MinMemoryMb: min,
            MaxMemoryMb: config.MemoryMaxMb,
            IsScript: false);
    }
}
