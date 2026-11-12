using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>執行中伺服器行程登記：寫入 <c>running_servers.json</c>，以 PID 加啟動時間辨識上次遺留之行程</summary>
public sealed class RunningServerRegistry(string userDataDirectory, IProcessInspector inspector) : IRunningServerRegistry
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(RunningServerRegistry));
    private static readonly long StartTimeToleranceTicks = TimeSpan.FromSeconds(1).Ticks;

    private readonly string _filePath = Path.Combine(userDataDirectory, "running_servers.json");
    private readonly Dictionary<string, TrackedServerProcess> _session = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _removed = new(StringComparer.OrdinalIgnoreCase);
    private readonly Lock _lock = new();

    // 以單一鏈式工作序列化背景寫入，確保最後寫入者為最新狀態
    private Task _writeChain = Task.CompletedTask;

    public void Record(string serverName, int pid)
    {
        DateTime? startTime = inspector.GetStartTimeUtc(pid);
        if (startTime is null)
        {
            Logger.Warning("無法取得伺服器「{Server}」行程 (PID: {Pid}) 的啟動時間，略過登記", serverName, pid);
            return;
        }

        lock (_lock)
        {
            _session[serverName] = new TrackedServerProcess(serverName, pid, startTime.Value.Ticks);
            _removed.Remove(serverName);
            QueueWriteLocked();
        }
    }

    public void Remove(string serverName)
    {
        lock (_lock)
        {
            _session.Remove(serverName);
            _removed.Add(serverName);
            QueueWriteLocked();
        }
    }

    public Task<IReadOnlyList<TrackedServerProcess>> FindOrphansAsync(CancellationToken cancellationToken = default) =>
        Task.Run<IReadOnlyList<TrackedServerProcess>>(() =>
        {
            var tracked = ReadFile();
            if (tracked.Count == 0)
            {
                return [];
            }

            var survivors = new List<TrackedServerProcess>();
            lock (_lock)
            {
                foreach (var entry in tracked)
                {
                    if (!_session.ContainsKey(entry.ServerName) && IsSameProcess(entry))
                    {
                        survivors.Add(entry);
                    }
                }

                if (survivors.Count != tracked.Count)
                {
                    PersistLocked(survivors);
                }
            }

            return survivors;
        }, cancellationToken);

    public Task<bool> TerminateAsync(TrackedServerProcess process, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(process);
        return Task.Run(() =>
        {
            bool success = !IsSameProcess(process) || inspector.KillProcessTree(process.Pid);
            if (success)
            {
                lock (_lock)
                {
                    var remaining = ReadFile()
                        .Where(e => !(string.Equals(e.ServerName, process.ServerName, StringComparison.OrdinalIgnoreCase) && e.Pid == process.Pid))
                        .ToList();
                    PersistLocked(remaining);
                }
            }

            return success;
        }, cancellationToken);
    }

    private bool IsSameProcess(TrackedServerProcess entry)
    {
        DateTime? start = inspector.GetStartTimeUtc(entry.Pid);
        return start is not null && Math.Abs(start.Value.Ticks - entry.StartTimeUtcTicks) <= StartTimeToleranceTicks;
    }

    private List<TrackedServerProcess> ReadFile()
    {
        try
        {
            if (!SafeFileSystem.FileExists(_filePath))
            {
                return [];
            }

            return JsonCodec.ReadFile<List<TrackedServerProcess>>(_filePath) ?? [];
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Text.Json.JsonException)
        {
            Logger.Warning(ex, "讀取伺服器行程登記檔失敗");
            return [];
        }
    }

    private void PersistLocked(List<TrackedServerProcess> entries)
    {
        try
        {
            AtomicFileWriter.WriteJson(_filePath, entries);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "寫入伺服器行程登記檔失敗");
        }
    }

    // 呼叫端須已持有 _lock；背景工作取得鎖後才讀取最新快照
    private void QueueWriteLocked()
    {
        _writeChain = _writeChain.ContinueWith(
            _ =>
            {
                lock (_lock)
                {
                    var merged = ReadFile()
                        .Where(e => !_session.ContainsKey(e.ServerName) && !_removed.Contains(e.ServerName))
                        .Concat(_session.Values)
                        .ToList();
                    PersistLocked(merged);
                }
            },
            CancellationToken.None,
            TaskContinuationOptions.None,
            TaskScheduler.Default);
    }
}
