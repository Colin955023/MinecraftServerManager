using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器啟動規劃器實作</summary>
public sealed class ServerLaunchPlanner : IServerLaunchPlanner
{
    public ServerLaunchPlan CreatePlan(ServerConfig config, string launchTarget, string? javaPath = null)
    {
        ArgumentNullException.ThrowIfNull(config);

        string stableDir = SafeFileSystem.ResolveStableDirectory(config.Path);
        string targetFile = !string.IsNullOrWhiteSpace(launchTarget)
            ? launchTarget.Trim()
            : "server.jar";

        // 防範 Path Traversal：僅允許相對於 stableDir 的內部檔案
        string targetFullPath = Path.GetFullPath(Path.Combine(stableDir, targetFile));
        if (!SafeFileSystem.IsPathWithin(stableDir, targetFullPath, strict: false))
        {
            throw new SafeFileSystemException($"偵測到非法的啟動目標路徑超出邊界：{targetFile}");
        }

        bool isScript = targetFile.EndsWith(".bat", StringComparison.OrdinalIgnoreCase);

        if (isScript)
        {
            if (!SafeScriptValidator.ValidateScriptContent(targetFullPath, stableDir))
            {
                throw new InvalidOperationException($"啟動腳本「{targetFile}」未通過安全性檢驗（可能包含未受信任的指令或批次注入字元）");
            }

            if (config.LoaderType is LoaderKind.Forge or LoaderKind.NeoForge || SafeFileSystem.FileExists(Path.Combine(stableDir, ServerDefaults.UserJvmArgsFileName)))
            {
                StartScriptWriter.UpdateUserJvmArgs(stableDir, config);
            }

            IReadOnlyDictionary<string, string?>? env = null;
            if (!string.IsNullOrWhiteSpace(javaPath) && !string.Equals(javaPath.Trim(), "java", StringComparison.OrdinalIgnoreCase))
            {
                env = BuildJavaEnvironment(javaPath.Trim());
            }

            return new ServerLaunchPlan(
                JavaExecutable: targetFullPath,
                WorkingDirectory: stableDir,
                Arguments: [],
                Loader: config.LoaderType,
                MinMemoryMb: config.MemoryMinMb ?? ServerDefaults.DefaultMemoryMinMb,
                MaxMemoryMb: config.MemoryMaxMb,
                IsScript: true,
                ServerName: config.Name.Value,
                Environment: env);
        }

        string executableJava = !string.IsNullOrWhiteSpace(javaPath)
            ? javaPath
            : "java";

        // 指定的 Java 路徑須為實體 java 執行檔（拒絕 reparse point 與非 java 檔名）；純檔名僅接受 java 系列名稱並交由 PATH 搜尋
        if (!string.IsNullOrWhiteSpace(javaPath))
        {
            string trimmedJava = javaPath.Trim();
            bool isBareName = Path.GetFileName(trimmedJava) == trimmedJava;
            if (isBareName ? !SafeScriptValidator.IsJavaExecutableName(trimmedJava) : !SafeScriptValidator.IsSafeJavaExecutable(trimmedJava))
            {
                throw new InvalidOperationException($"指定的 Java 執行檔未通過安全性檢驗：{javaPath}");
            }
        }

        int min = MemoryUtils.ResolveEffectiveMinMemoryMb(config.MemoryMinMb, config.MemoryMaxMb);
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

        if (customArgs.FirstOrDefault(static arg => JvmOptionPolicy.IsCommandExecutionOption(arg)) is { } blockedArg)
        {
            throw new InvalidOperationException($"JVM 參數「{blockedArg}」可執行外部命令，已阻擋啟動");
        }

        args.AddRange(customArgs);

        if (targetFile.StartsWith('@'))
        {
            args.Add(targetFile);
        }
        else
        {
            args.Add("-jar");
            args.Add(targetFile);
        }

        string guiArg = (config.LoaderType == LoaderKind.Paper || targetFile.StartsWith("paper", StringComparison.OrdinalIgnoreCase))
            ? "--nogui"
            : "nogui";
        args.Add(guiArg);

        if (!SafeScriptValidator.ValidateCommandInputs(stableDir, args))
        {
            throw new InvalidOperationException($"伺服器啟動指令引用的檔案未通過安全性邊界檢驗");
        }

        return new ServerLaunchPlan(
            JavaExecutable: executableJava,
            WorkingDirectory: stableDir,
            Arguments: args,
            Loader: config.LoaderType,
            MinMemoryMb: min,
            MaxMemoryMb: config.MemoryMaxMb,
            IsScript: false,
            ServerName: config.Name.Value);
    }

    /// <summary>為指定的 Java 執行檔建置注入用的環境變數（設定 JAVA_HOME 並將 java bin 目錄置於 PATH 最前端）</summary>
    public static IReadOnlyDictionary<string, string?> BuildJavaEnvironment(string javaExecutablePath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(javaExecutablePath);

        string javaBinDir = Path.GetDirectoryName(javaExecutablePath) ?? string.Empty;
        string javaHome = javaBinDir;

        string dirName = Path.GetFileName(javaBinDir);
        if (dirName.Equals("bin", StringComparison.OrdinalIgnoreCase))
        {
            string? parent = Path.GetDirectoryName(javaBinDir);
            if (!string.IsNullOrWhiteSpace(parent))
            {
                javaHome = parent;
            }
        }

        string currentPath = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
        string newPath = string.IsNullOrWhiteSpace(javaBinDir)
            ? currentPath
            : $"{javaBinDir}{Path.PathSeparator}{currentPath}";

        return new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase)
        {
            ["JAVA_HOME"] = javaHome,
            ["PATH"] = newPath
        };
    }
}
