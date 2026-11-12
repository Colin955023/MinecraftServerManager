using System.Collections.Frozen;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>建立、匯入與掃描伺服器時共用的設定輔助方法</summary>
internal static class ServerSetupHelpers
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerSetupHelpers));

    private static readonly FrozenSet<string> KnownStartupStems = new[]
    {
        "start", "run", "server", "launch", "startserver", "serverstart", "minecraft_server", "play"
    }.ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    /// <summary>在伺服器目錄中只保留標準 start_server.bat，清理其他多餘的 .bat、.ps1 與 .sh 啟動腳本。</summary>
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

                string ext = Path.GetExtension(entry.FullPath);
                if (string.Equals(ext, ".bat", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(ext, ".cmd", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(ext, ".ps1", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(ext, ".sh", StringComparison.OrdinalIgnoreCase))
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
                        catch (Exception ex)
                        {
                            Logger.Warning(ex, "清理多餘腳本 {File} 失敗", fileName);
                        }
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "清理多餘啟動腳本失敗");
        }
    }

    /// <summary>依偵測結果建立伺服器設定；無法辨識 Minecraft 版本時沿用預設 1.20.4</summary>
    internal static ServerConfig CreateConfigFromInspection(ServerName name, LoaderKind loader, ServerInspection inspection, string path) => new(
        name: name,
        minecraftVersion: MinecraftVersion.TryParse(inspection.MinecraftVersion, out var version) ? version : MinecraftVersion.Parse("1.20.4"),
        loaderType: loader,
        loaderVersion: inspection.LoaderVersion,
        memoryMaxMb: inspection.MemoryMaxMb,
        memoryMinMb: inspection.MemoryMinMb,
        path: path);

    /// <summary>檢查目標磁碟可用空間是否足夠。</summary>
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
}
