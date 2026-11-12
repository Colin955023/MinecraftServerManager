using System.Globalization;
using System.Text;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器啟動腳本與 JVM 參數檔（start_server.bat、user_jvm_args.txt）的唯一寫入入口</summary>
public static class StartScriptWriter
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(StartScriptWriter));

    /// <summary>生成統一規範之 start_server.bat 啟動腳本。</summary>
    public static void Write(
        string directory,
        string launchTarget,
        int memoryMaxMb,
        int memoryMinMb,
        string? javaPath,
        IReadOnlyList<string>? jvmArgs = null,
        LoaderKind loader = LoaderKind.Unknown)
    {
        string resolvedPath = javaPath ?? string.Empty;
        if (!Path.IsPathFullyQualified(resolvedPath))
        {
            string pf = RuntimePaths.GetProgramFilesDir();
            resolvedPath = Path.Combine(pf, "Java", "bin", "java.exe");
        }

        string javaCommand = $"\"{resolvedPath}\"";
        var builder = new StringBuilder();
        builder.AppendLine("@echo off");
        builder.AppendLine("chcp 65001 > nul");
        builder.AppendLine("cd /d \"%~dp0\"");
        builder.AppendLine();

        string extraArgs = (jvmArgs is not null && jvmArgs.Count > 0)
            ? string.Join(' ', jvmArgs.Select(FormatBatchArgument)) + " "
            : string.Empty;

        if (launchTarget.StartsWith('@'))
        {
            string argsFile = launchTarget[1..].Trim('"');
            builder.AppendLine(CultureInfo.InvariantCulture, $"{javaCommand} -Xms{memoryMinMb}M -Xmx{memoryMaxMb}M {extraArgs}@\"{argsFile}\" nogui %*");
        }
        else
        {
            string jarName = launchTarget.EndsWith(".bat", StringComparison.OrdinalIgnoreCase) ? "server.jar" : launchTarget;
            string guiFlag = (loader == LoaderKind.Paper || jarName.StartsWith("paper", StringComparison.OrdinalIgnoreCase)) ? "--nogui" : "nogui";
            builder.AppendLine(CultureInfo.InvariantCulture, $"{javaCommand} -Xms{memoryMinMb}M -Xmx{memoryMaxMb}M {extraArgs}-jar \"{jarName}\" {guiFlag} %*");
        }

        AtomicFileWriter.WriteTextOrThrow(Path.Combine(directory, ServerDefaults.StartServerBatFileName), builder.ToString());
    }

    /// <summary>更新 Forge / NeoForge 之 user_jvm_args.txt 啟動與記憶體參數檔案（原子安全寫入）</summary>
    public static void UpdateUserJvmArgs(string serverDirectory, ServerConfig config)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        ArgumentNullException.ThrowIfNull(config);

        string stableDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
        var lines = new List<string>();

        var customJvmArgs = config.JvmArgs ?? [];
        if (!JvmOptionPolicy.HasGcOption(customJvmArgs))
        {
            var recommendedGc = JvmOptionPolicy.RecommendGcArgs(config.MemoryMaxMb, javaMajor: null, loaderType: config.LoaderType.ToString(), existingArgs: customJvmArgs);
            lines.AddRange(recommendedGc);
        }

        lines.AddRange(customJvmArgs);

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

    /// <summary>更新統一啟動腳本 start_server.bat 中的記憶體設定（-Xms 與 -Xmx）</summary>
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
        int minMb = MemoryUtils.ResolveEffectiveMinMemoryMb(config.MemoryMinMb, config.MemoryMaxMb);
        int maxMb = config.MemoryMaxMb;

        content = MemoryUtils.ApplyMemoryFlags(content, minMb, maxMb);
        AtomicFileWriter.WriteTextOrThrow(scriptPath, content);
        Logger.Information("已更新統一啟動腳本記憶體設定: {Path} (-Xms{Min}M -Xmx{Max}M)", scriptPath, minMb, maxMb);
    }

    /// <summary>含空白的 JVM 參數寫入批次檔時須加雙引號，避免被 cmd 切成多個參數</summary>
    internal static string FormatBatchArgument(string argument) =>
        argument.AsSpan().ContainsAny(' ', '\t') ? $"\"{argument}\"" : argument;

    /// <summary>是否以 <c>user_jvm_args.txt</c> 傳遞 JVM 參數（Forge／NeoForge，或目錄內已有該檔或 run.bat）</summary>
    public static bool UsesUserJvmArgsFile(LoaderKind loader, string serverDir) =>
        loader is LoaderKind.Forge or LoaderKind.NeoForge ||
        SafeFileSystem.FileExists(Path.Combine(serverDir, ServerDefaults.UserJvmArgsFileName)) ||
        SafeFileSystem.FileExists(Path.Combine(serverDir, "run.bat"));
}
