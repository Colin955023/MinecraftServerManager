using System.Globalization;
using System.Text;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>啟動腳本與 JVM 參數檔的寫入入口</summary>
public static class StartScriptWriter
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(StartScriptWriter));

    // 受管 start_server.bat 固定表頭，須與 Write 輸出一致
    private static readonly string[] ManagedScriptHeaderLines = ["@echo off", "chcp 65001 > nul", "cd /d \"%~dp0\""];

    /// <summary>生成統一規範之 start_server.bat 啟動腳本</summary>
    public static void Write(
        string directory,
        string launchTarget,
        int memoryMaxMb,
        int memoryMinMb,
        string? javaPath,
        IReadOnlyList<string>? jvmArgs = null,
        LoaderKind loader = LoaderKind.Unknown,
        int? javaMajor = null)
    {
        string resolvedPath = javaPath ?? string.Empty;
        if (!Path.IsPathFullyQualified(resolvedPath))
        {
            string pf = RuntimePaths.GetProgramFilesDir();
            resolvedPath = Path.Combine(pf, "Java", "bin", "java.exe");
        }

        ValidateJvmArguments(jvmArgs);

        // 與直接啟動共用同一份 JVM 與目標參數清單
        string target = launchTarget.StartsWith('@')
            ? "@" + launchTarget[1..].Trim('"')
            : launchTarget.EndsWith(ServerDefaults.BatchScriptExtension, StringComparison.OrdinalIgnoreCase) ? ServerDefaults.ServerJarFileName : launchTarget;
        var tokens = ServerLaunchPlanner.BuildJvmAndTargetArgs(loader, target, memoryMinMb, memoryMaxMb, jvmArgs ?? [], javaMajor);

        // 目標參數（-jar 之後的檔名或 @argfile）固定為倒數第二個 token，須一律以雙引號包住
        int targetIndex = tokens.Count - 2;
        string commandTokens = string.Join(' ', tokens.Select((token, index) => index == targetIndex ? FormatLaunchTarget(token) : FormatBatchArgument(token)));

        var builder = new StringBuilder();
        builder.AppendLine("@echo off");
        builder.AppendLine("chcp 65001 > nul");
        builder.AppendLine("cd /d \"%~dp0\"");
        builder.AppendLine();
        builder.AppendLine(CultureInfo.InvariantCulture, $"\"{resolvedPath}\" {commandTokens} %*");

        AtomicFileWriter.WriteTextOrThrow(Path.Combine(directory, ServerDefaults.StartServerBatFileName), builder.ToString());
    }

    /// <summary>更新 user_jvm_args.txt</summary>
    public static void UpdateUserJvmArgs(string serverDirectory, ServerConfig config, int? javaMajor = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        ArgumentNullException.ThrowIfNull(config);

        string stableDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
        var lines = new List<string>();

        var customJvmArgs = config.JvmArgs ?? [];
        ValidateJvmArguments(customJvmArgs);
        if (!JvmOptionPolicy.HasGcOption(customJvmArgs))
        {
            var recommendedGc = JvmOptionPolicy.RecommendGcArgs(config.MemoryMaxMb, javaMajor: javaMajor, loaderType: config.LoaderType, existingArgs: customJvmArgs);
            lines.AddRange(recommendedGc);
        }

        // java 引數檔以空白分隔，含空白者須加引號
        lines.AddRange(customJvmArgs.Select(FormatBatchArgument));

        if (config.MemoryMinMb.HasValue)
        {
            lines.Add($"-Xms{config.MemoryMinMb.Value}M");
        }

        if (config.MemoryMaxMb > 0)
        {
            lines.Add($"-Xmx{config.MemoryMaxMb}M");
        }

        string userJvmArgsPath = Path.Combine(stableDir, ServerDefaults.UserJvmArgsFileName);
        string content = string.Join(Environment.NewLine, lines) + Environment.NewLine;
        AtomicFileWriter.WriteTextOrThrow(userJvmArgsPath, content);
        Logger.Information("已更新 Forge/NeoForge 參數檔: {Path}", userJvmArgsPath);
    }

    /// <summary>更新 start_server.bat 的記憶體設定</summary>
    public static void UpdateMemory(string serverDirectory, ServerConfig config)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        ArgumentNullException.ThrowIfNull(config);

        string stableDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
        string scriptPath = Path.Combine(stableDir, ServerDefaults.StartServerBatFileName);
        if (!SafeFileSystem.FileExists(scriptPath))
        {
            return;
        }

        string content = SafeFileSystem.ReadAllText(scriptPath);
        int minMb = MemoryHelpers.ResolveEffectiveMinMemoryMb(config.MemoryMinMb, config.MemoryMaxMb);
        int maxMb = config.MemoryMaxMb;

        content = MemoryHelpers.ApplyMemoryFlags(content, minMb, maxMb);
        AtomicFileWriter.WriteTextOrThrow(scriptPath, content);
        Logger.Information("已更新統一啟動腳本記憶體設定: {Path} (-Xms{Min}M -Xmx{Max}M)", scriptPath, minMb, maxMb);
    }

    /// <summary>以設定中的自訂 JVM 參數取代受管 start_server.bat 的既有參數（非 user_jvm_args.txt 啟動方式使用）</summary>
    public static void UpdateScriptJvmArgs(string serverDirectory, ServerConfig config)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        ArgumentNullException.ThrowIfNull(config);

        string stableDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
        string scriptPath = Path.Combine(stableDir, ServerDefaults.StartServerBatFileName);
        if (!SafeFileSystem.FileExists(scriptPath))
        {
            return;
        }

        ValidateJvmArguments(config.JvmArgs);
        string extraArgs = FormatExtraArguments(config.JvmArgs);
        string content = SafeFileSystem.ReadAllText(scriptPath);
        if (!MemoryHelpers.TryReplaceScriptJvmArgs(content, extraArgs, out string updated))
        {
            Logger.Warning("啟動腳本非受管格式，略過同步 JVM 參數: {Path}", scriptPath);
            return;
        }

        if (!string.Equals(updated, content, StringComparison.Ordinal))
        {
            AtomicFileWriter.WriteTextOrThrow(scriptPath, updated);
            Logger.Information("已同步啟動腳本 JVM 參數: {Path}", scriptPath);
        }
    }

    /// <summary>拒絕含換行、批次注入字元或可執行外部命令之 JVM 參數</summary>
    public static void ValidateJvmArguments(IReadOnlyList<string>? arguments)
    {
        if (DescribeRejectedJvmArgument(arguments) is { } reason)
        {
            throw new InvalidOperationException(reason);
        }
    }

    /// <summary>回傳第一個不得寫入之 JVM 參數的拒絕原因；全部可寫入時回傳 null</summary>
    public static string? DescribeRejectedJvmArgument(IReadOnlyList<string>? arguments)
    {
        foreach (string argument in arguments ?? [])
        {
            if (JvmOptionPolicy.ContainsScriptUnsafeChars(argument))
            {
                return $"JVM 參數「{argument}」含有不允許的字元（換行或批次特殊字元）";
            }

            if (JvmOptionPolicy.IsCommandExecutionOption(argument))
            {
                return $"JVM 參數「{argument}」可執行外部命令，已拒絕寫入";
            }
        }

        return null;
    }

    private static string FormatExtraArguments(IReadOnlyList<string>? jvmArgs) =>
        jvmArgs is { Count: > 0 } ? string.Join(' ', jvmArgs.Select(FormatBatchArgument)) + " " : string.Empty;

    /// <summary>含空白的 JVM 參數寫入批次檔時須加雙引號，避免被 cmd 切成多個參數</summary>
    internal static string FormatBatchArgument(string argument) =>
        argument.AsSpan().ContainsAny(' ', '\t') ? $"\"{argument}\"" : argument;

    /// <summary>啟動目標一律加雙引號：-jar 檔名，或 @argfile 寫為 <c>@"路徑"</c>（與舊版腳本一致，避免 &amp;、^、% 等字元破壞批次檔）</summary>
    private static string FormatLaunchTarget(string token) =>
        token.StartsWith('@') ? $"@\"{token[1..]}\"" : $"\"{token}\"";

    /// <summary>是否為本程式產生的受管 start_server.bat（依 <see cref="Write"/> 固定表頭辨識）</summary>
    internal static bool IsManagedStartScript(string content)
    {
        using var reader = new StringReader(content);
        foreach (string expected in ManagedScriptHeaderLines)
        {
            if (!string.Equals(reader.ReadLine()?.Trim(), expected, StringComparison.Ordinal))
            {
                return false;
            }
        }

        return true;
    }

    /// <summary>是否以 <c>user_jvm_args.txt</c> 傳遞 JVM 參數</summary>
    public static bool UsesUserJvmArgsFile(LoaderKind loader, string serverDir) =>
        loader is LoaderKind.Forge or LoaderKind.NeoForge ||
        SafeFileSystem.FileExists(Path.Combine(serverDir, ServerDefaults.UserJvmArgsFileName)) ||
        SafeFileSystem.FileExists(Path.Combine(serverDir, ServerDefaults.RunBatFileName));
}
