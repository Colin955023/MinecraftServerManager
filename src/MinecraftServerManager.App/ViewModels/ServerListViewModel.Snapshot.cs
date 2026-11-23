using System.Globalization;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.ViewModels;

public sealed partial class ServerListViewModel
{
    private static void ApplySnapshot(ServerRowItem row, ServerRowSnapshot snapshot, string? baseDirectory)
    {
        ServerConfig s = snapshot.Config;
        row.Version = s.MinecraftVersion.Value;
        row.Loader = s.LoaderType.ToString();
        row.Status = snapshot.Status;
        row.IsRunning = snapshot.IsRunning;
        row.IsStopping = snapshot.IsStopping;
        row.BackupStatus = snapshot.BackupStatus;
        row.LastModified = snapshot.LastModified;
        row.RawLastModifiedTicks = snapshot.RawLastModifiedTicks;
        row.Path = s.Path;
        row.RelativePath = !string.IsNullOrWhiteSpace(baseDirectory) && !string.IsNullOrWhiteSpace(s.Path)
            ? Path.GetRelativePath(baseDirectory, s.Path)
            : s.Path;
        row.MemoryMaxMb = s.MemoryMaxMb;
        row.MemoryMinMb = s.MemoryMinMb;
        row.BackupPath = s.BackupPath;
        row.HasMissingFiles = snapshot.HasMissingFiles;
    }

    private sealed record ServerRowSnapshot(
        ServerConfig Config,
        string BackupStatus,
        string Status,
        bool IsRunning,
        bool IsStopping,
        string LastModified,
        long RawLastModifiedTicks,
        bool HasMissingFiles);

    private sealed record ServerStatusProbe(string Status, bool IsRunning, bool IsStopping, bool HasMissingFiles, DateTimeOffset? LastModified);

    private async Task<ServerRowSnapshot> BuildServerSnapshotAsync(ServerConfig s, bool isThisServerRunning, CancellationToken cancellationToken = default)
    {
        var probeTask = ProbeServerStatusAsync(s.Path, s.LoaderType, isThisServerRunning, _stopCoordinator.IsStopping(s.Name.Value), cancellationToken);
        var summaryTask = _backupService.GetBackupSummaryAsync(s.Name.Value, s.BackupPath, cancellationToken);
        ServerStatusProbe probe = await probeTask.ConfigureAwait(false);
        ServerBackupSummary summary = await summaryTask.ConfigureAwait(false);
        return new ServerRowSnapshot(
            Config: s,
            BackupStatus: ServerStatusFormatter.FormatBackupStatus(summary),
            Status: probe.Status,
            IsRunning: probe.IsRunning,
            IsStopping: probe.IsStopping,
            LastModified: probe.LastModified?.ToString("yyyy/MM/dd HH:mm", CultureInfo.InvariantCulture) ?? "-",
            RawLastModifiedTicks: probe.LastModified?.Ticks ?? -1,
            HasMissingFiles: probe.HasMissingFiles);
    }

    private async Task<ServerStatusProbe> ProbeServerStatusAsync(
        string path,
        LoaderKind loader,
        bool isRunning,
        bool stopping,
        CancellationToken cancellationToken = default)
    {
        if (isRunning)
        {
            return new ServerStatusProbe(stopping ? StoppingStatusText : RunningStatusText, true, stopping, false, await GetLastModifiedTimeAsync(path, cancellationToken).ConfigureAwait(false));
        }

        var result = await _integrityService.CheckImportantFilesAsync(path, loader, cancellationToken).ConfigureAwait(false);
        string status = result.HasMissing ? $"缺少重要檔案：{string.Join("、", result.MissingFiles)}" : "已停止";
        return new ServerStatusProbe(status, false, false, result.HasMissing, await GetLastModifiedTimeAsync(path, cancellationToken).ConfigureAwait(false));
    }

    private async Task<DateTimeOffset?> GetLastModifiedTimeAsync(string path, CancellationToken cancellationToken = default)
    {
        try
        {
            return await _fileSystem.GetDirectoryLastWriteTimeAsync(path, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "取得目錄最後修改時間失敗：{Path}", path);
            return null;
        }
    }
}
