using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed class ServerLaunchPlanner : IServerLaunchPlanner
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerLaunchPlanner));

    public ServerLaunchPlan CreatePlan(ServerConfig config, string launchTarget, string? javaPath = null, int? javaMajor = null)
    {
        ArgumentNullException.ThrowIfNull(config);

        string stableDir = SafeFileSystem.ResolveStableDirectory(config.Path);
        string targetFile = !string.IsNullOrWhiteSpace(launchTarget)
            ? launchTarget.Trim()
            : ServerDefaults.ServerJarFileName;

        // 防範 Path Traversal：僅允許相對於 stableDir 的內部檔案；@argfile 以實際檔案路徑檢查
        string targetFullPath = Path.GetFullPath(targetFile.TrimStart('@'), stableDir);
        if (!SafeFileSystem.IsPathWithin(stableDir, targetFullPath, strict: false))
        {
            throw new SafeFileSystemException($"偵測到非法的啟動目標路徑超出邊界：{targetFile}");
        }

        // 腳本啟動會把自訂參數寫入 user_jvm_args.txt，故兩種啟動方式都先檢查
        var customArgs = config.JvmArgs ?? [];
        if (customArgs.FirstOrDefault(static arg => JvmOptionPolicy.IsCommandExecutionOption(arg)) is { } blockedArg)
        {
            throw new InvalidOperationException($"JVM 參數「{blockedArg}」可執行外部命令，已阻擋啟動");
        }

        bool isScript = targetFile.EndsWith(ServerDefaults.BatchScriptExtension, StringComparison.OrdinalIgnoreCase);

        if (isScript)
        {
            if (!SafeScriptValidator.ValidateScriptContent(targetFullPath, stableDir))
            {
                throw new InvalidOperationException($"啟動腳本「{targetFile}」未通過安全性檢驗（可能包含未受信任的指令或批次注入字元）");
            }

            if (StartScriptWriter.UsesUserJvmArgsFile(config.LoaderType, stableDir))
            {
                StartScriptWriter.UpdateUserJvmArgs(stableDir, config, javaMajor);
            }

            IReadOnlyDictionary<string, string?>? env = null;
            if (!string.IsNullOrWhiteSpace(javaPath) && !string.Equals(javaPath.Trim(), ServerDefaults.DefaultJavaCommand, StringComparison.OrdinalIgnoreCase))
            {
                // 腳本經 JAVA_HOME／PATH 取用 Java，同樣須為實體 java 執行檔
                SafeScriptValidator.ValidateJavaPath(javaPath);
                env = BuildJavaEnvironment(javaPath.Trim());
            }

            return new ServerLaunchPlan(
                JavaExecutable: targetFullPath,
                WorkingDirectory: stableDir,
                Arguments: [],
                Loader: config.LoaderType,
                MinMemoryMb: MemoryHelpers.ResolveEffectiveMinMemoryMb(config.MemoryMinMb, config.MemoryMaxMb),
                MaxMemoryMb: config.MemoryMaxMb,
                IsScript: true,
                ServerName: config.Name.Value,
                Environment: env);
        }

        string executableJava = !string.IsNullOrWhiteSpace(javaPath)
            ? javaPath
            : ServerDefaults.DefaultJavaCommand;

        if (!string.IsNullOrWhiteSpace(javaPath))
        {
            SafeScriptValidator.ValidateJavaPath(javaPath);
        }

        int min = MemoryHelpers.ResolveEffectiveMinMemoryMb(config.MemoryMinMb, config.MemoryMaxMb);
        var args = BuildJvmAndTargetArgs(config.LoaderType, targetFile, min, config.MemoryMaxMb, customArgs, javaMajor);

        if (!SafeScriptValidator.ValidateCommandInputs(stableDir, args))
        {
            throw new InvalidOperationException($"伺服器啟動指令引用的檔案未通過安全性邊界檢驗");
        }

        // 直接啟動時以實際參數刷新受管腳本，使 start_server.bat 與程式內啟動參數一致
        if (javaMajor is not null)
        {
            RefreshManagedStartScript(stableDir, config, targetFile, javaPath, min, javaMajor.Value);
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

    /// <summary>
    /// 直接啟動時，若伺服器目錄存在本程式產生的 start_server.bat，以同一份參數重新寫入；寫入失敗僅記錄例外，不阻擋啟動。
    /// 僅在 javaPath 為絕對路徑時刷新，避免 <see cref="StartScriptWriter.Write"/> 改用預設 Java 路徑。
    /// </summary>
    private static void RefreshManagedStartScript(string stableDir, ServerConfig config, string targetFile, string? javaPath, int minMemoryMb, int javaMajor)
    {
        if (string.IsNullOrWhiteSpace(javaPath) || !Path.IsPathFullyQualified(javaPath.Trim()))
        {
            return;
        }

        string scriptPath = Path.Combine(stableDir, ServerDefaults.StartServerBatFileName);
        try
        {
            if (!SafeFileSystem.FileExists(scriptPath) || !StartScriptWriter.IsManagedStartScript(SafeFileSystem.ReadAllText(scriptPath)))
            {
                return;
            }

            StartScriptWriter.Write(stableDir, targetFile, config.MemoryMaxMb, minMemoryMb, javaPath.Trim(), config.JvmArgs, config.LoaderType, javaMajor);
            Logger.Information("已依直接啟動參數（Java {JavaMajor}）刷新受管啟動腳本: {Path}", javaMajor, scriptPath);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "刷新受管啟動腳本失敗，略過並繼續啟動: {Path}", scriptPath);
        }
    }

    /// <summary>
    /// 建立 JVM 參數與啟動目標參數清單（記憶體、UTF-8 編碼、推薦 GC、自訂參數、-jar 或 @argfile、nogui）；
    /// 直接啟動與 start_server.bat 共用同一份清單，避免兩者分歧。
    /// </summary>
    internal static IReadOnlyList<string> BuildJvmAndTargetArgs(
        LoaderKind loader,
        string targetFile,
        int minMemoryMb,
        int maxMemoryMb,
        IReadOnlyList<string> customArgs,
        int? javaMajor)
    {
        var args = new List<string>
        {
            $"-Xms{minMemoryMb}M",
            $"-Xmx{maxMemoryMb}M"
        };

        // 主控台以 UTF-8 讀取標準輸出／錯誤，Java 18+ 預設依系統字碼頁輸出，需明確指定；舊版 JVM 會忽略未知系統屬性
        AddDefaultSystemProperty(args, customArgs, "-Dstdout.encoding=", "UTF-8");
        AddDefaultSystemProperty(args, customArgs, "-Dstderr.encoding=", "UTF-8");

        // 注入推薦 GC 與 JVM 參數
        if (!JvmOptionPolicy.HasGcOption(customArgs))
        {
            args.AddRange(JvmOptionPolicy.RecommendGcArgs(maxMemoryMb, javaMajor, loader));
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

        args.Add(HasNoGuiArg(loader, targetFile) ? "--nogui" : "nogui");
        return args;
    }

    /// <summary>是否使用雙橫線 <c>--nogui</c> 旗標（Paper 核心）</summary>
    internal static bool HasNoGuiArg(LoaderKind loader, string target) =>
        loader == LoaderKind.Paper || target.StartsWith(LoaderLayout.For(LoaderKind.Paper).LaunchJarPrefix, StringComparison.OrdinalIgnoreCase);

    /// <summary>使用者自訂參數未指定該系統屬性時才加入預設值</summary>
    private static void AddDefaultSystemProperty(List<string> args, IReadOnlyList<string> customArgs, string prefix, string value)
    {
        foreach (string custom in customArgs)
        {
            if (custom.StartsWith(prefix, StringComparison.Ordinal))
            {
                return;
            }
        }

        args.Add(prefix + value);
    }

    /// <summary>建立 Java 環境變數（JAVA_HOME 與 PATH）</summary>
    private static Dictionary<string, string?> BuildJavaEnvironment(string javaExecutablePath)
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
