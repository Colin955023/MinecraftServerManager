using System.Collections.Frozen;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>建立、匯入與掃描伺服器時共用的設定輔助方法</summary>
internal static class ServerSetupHelpers
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerSetupHelpers));

    private static readonly FrozenSet<string> KnownStartupStems = FrozenSet.Create(
        StringComparer.OrdinalIgnoreCase,
        "start", "run", "server", "launch", "startserver", "serverstart", "minecraft_server", "play");

    private static readonly FrozenSet<string> StartupScriptExtensions = FrozenSet.Create(
        StringComparer.OrdinalIgnoreCase,
        ".bat", ".cmd", ".ps1", ".sh");

    /// <summary>只保留 start_server.bat，清除其他啟動腳本</summary>
    internal static void CleanupRedundantStartupScripts(string directory)
    {
        if (!SafeFileSystem.DirectoryExists(directory))
        {
            return;
        }

        try
        {
            var entries = SafeFileSystem.ListBoundedDirectory(directory, rejectReparse: false);
            foreach (var entry in entries)
            {
                if (entry.IsDirectory)
                {
                    continue;
                }

                if (StartupScriptExtensions.Contains(Path.GetExtension(entry.FullPath)))
                {
                    string fileName = Path.GetFileName(entry.FullPath);
                    if (string.Equals(fileName, ServerDefaults.StartServerBatFileName, StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(fileName, ServerDefaults.StartServerBatFileName + ".bak", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    string stem = Path.GetFileNameWithoutExtension(entry.FullPath);
                    if (KnownStartupStems.Contains(stem))
                    {
                        try
                        {
                            SafeFileSystem.DeleteWithin(directory, entry.FullPath);
                            Logger.Information("已清理多餘啟動腳本: {File}", fileName);
                        }
                        catch (Exception ex) when (ex is not OperationCanceledException)
                        {
                            Logger.Warning(ex, "清理多餘腳本 {File} 失敗", fileName);
                        }
                    }
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "清理多餘啟動腳本失敗");
        }
    }

    /// <summary>無法辨識 Minecraft 版本時回報給使用者的訊息</summary>
    internal const string UnknownVersionMessage = "無法辨識伺服器的 Minecraft 版本（未找到版本資訊）";

    /// <summary>依偵測結果建立伺服器設定；呼叫端須先確認已辨識 Minecraft 版本</summary>
    internal static ServerConfig CreateConfigFromInspection(ServerName name, LoaderKind loader, ServerInspection inspection, string path)
    {
        if (inspection.MinecraftVersion is not { } version)
        {
            throw new InvalidOperationException(UnknownVersionMessage);
        }

        int memoryMaxMb = inspection.MemoryMaxMb > 0 ? inspection.MemoryMaxMb : ServerDefaults.DefaultMemoryMaxMb;
        return new ServerConfig(
            name: name,
            minecraftVersion: version,
            loaderType: loader,
            loaderVersion: inspection.LoaderVersion ?? ServerDefaults.UnknownLoaderVersion,
            memoryMaxMb: memoryMaxMb,
            memoryMinMb: inspection.MemoryMinMb is > 0 and var min && min <= memoryMaxMb ? min : null,
            path: path);
    }

    /// <summary>解析伺服器目錄；名稱須為單一路徑片段且結果須位於根目錄內</summary>
    internal static string ResolveServerDirectory(string stableServersRoot, string serverName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        if (serverName is "." or ".."
            || !string.Equals(Path.GetFileName(serverName), serverName, StringComparison.Ordinal))
        {
            throw new ArgumentException($"伺服器名稱無效：{serverName}", nameof(serverName));
        }

        string serverDir = SafeFileSystem.ResolveStableDirectory(Path.Combine(stableServersRoot, serverName));
        if (!SafeFileSystem.IsPathWithin(stableServersRoot, serverDir, strict: true))
        {
            throw new ArgumentException($"伺服器目錄超出根目錄：{serverName}", nameof(serverName));
        }

        return serverDir;
    }

    /// <summary>整合記憶體計算、產生啟動腳本與清理多餘腳本</summary>
    internal static void FinalizeLaunchScripts(
        string targetDirectory,
        string launchTarget,
        int memoryMaxMb,
        int? configuredMemoryMinMb,
        string? javaExecutablePath,
        IReadOnlyList<string>? jvmArgs,
        LoaderKind loader,
        int? javaMajorVersion = null)
    {
        int memoryMinMb = MemoryHelpers.ResolveEffectiveMinMemoryMb(
            configuredMemoryMinMb is > 0 and var min && min <= memoryMaxMb ? min : null,
            memoryMaxMb);
        StartScriptWriter.Write(targetDirectory, launchTarget, memoryMaxMb, memoryMinMb, javaExecutablePath, jvmArgs, loader, javaMajorVersion);
        CleanupRedundantStartupScripts(targetDirectory);
    }

    /// <summary>目標磁碟可用空間是否足夠</summary>
    internal static string? CheckFreeSpace(string directory, long requiredBytes)
    {
        long? freeSpace = SafeFileSystem.GetAvailableFreeSpace(directory);
        if (freeSpace.HasValue && freeSpace.Value < requiredBytes)
        {
            string? root = Path.GetPathRoot(Path.GetFullPath(directory));
            return $"磁碟 {root} 可用空間不足（需要至少 {UnitFormatter.FormatBytes(requiredBytes)}）";
        }

        return null;
    }

    /// <summary>檢查目標伺服器目錄是否可用（不存在或為空），並回傳是否原已存在</summary>
    internal static string? ValidateEmptyTargetDirectory(string targetDir, out bool targetExisted)
    {
        targetExisted = SafeFileSystem.DirectoryExists(targetDir);
        return targetExisted && !SafeFileSystem.IsDirectoryEmpty(targetDir)
            ? $"目標目錄已存在且非空：{targetDir}"
            : null;
    }

    /// <summary>建立或匯入失敗時清理目標伺服器目錄；若建立／匯入前已存在空目錄則重新建立保留</summary>
    internal static void CleanupFailedServerDirectory(string serversRoot, string serverDir, bool existedBefore)
    {
        try
        {
            SafeFileSystem.DeleteWithin(serversRoot, serverDir);
            if (existedBefore && !SafeFileSystem.DirectoryExists(serverDir))
            {
                SafeFileSystem.CreateDirectory(serverDir);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "還原或清理失敗的伺服器目錄時發生錯誤: {Path}", serverDir);
        }
    }
}

/// <summary>建立與匯入伺服器共用的暫存提交生命週期：管理暫存目錄、EULA、原子移動與失敗自動回滾</summary>
internal sealed class EphemeralStagingScope : IDisposable
{
    private readonly string _serversRoot;
    private readonly string _targetDir;
    private readonly bool _targetExisted;
    private bool _commitTouchedTarget;
    private bool _completed;

    public string StagingDir { get; }
    public string StableStaging { get; }

    public EphemeralStagingScope(string serversRoot, string targetDir, bool targetExisted, string stagingPrefix)
    {
        _serversRoot = serversRoot;
        _targetDir = targetDir;
        _targetExisted = targetExisted;
        StagingDir = Path.Combine(serversRoot, $"{ServerDefaults.InternalPrefix}{stagingPrefix}-{Guid.NewGuid():N}");
        StableStaging = SafeFileSystem.ResolveStableDirectory(StagingDir, create: true);
    }

    public void EnsureEula()
    {
        string eulaFile = Path.Combine(StableStaging, ServerDefaults.EulaFileName);
        if (!SafeFileSystem.FileExists(eulaFile))
        {
            AtomicFileWriter.WriteTextOrThrow(eulaFile, "eula=true\n");
        }
    }

    public bool TryCommitToTarget()
    {
        _commitTouchedTarget = true;
        if (_targetExisted)
        {
            SafeFileSystem.DeleteDirectory(_targetDir, recursive: false);
        }

        return SafeFileSystem.MoveWithin(_serversRoot, StableStaging, _targetDir);
    }

    public void Complete() => _completed = true;

    public void Dispose()
    {
        if (!_completed && _commitTouchedTarget)
        {
            ServerSetupHelpers.CleanupFailedServerDirectory(_serversRoot, _targetDir, _targetExisted);
        }

        SafeFileSystem.DeleteWithin(_serversRoot, StagingDir);
    }
}
