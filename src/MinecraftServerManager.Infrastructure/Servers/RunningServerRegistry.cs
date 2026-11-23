using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>執行中伺服器行程登記，以 PID 與啟動時間辨識遺留行程</summary>
public sealed class RunningServerRegistry : IRunningServerRegistry
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(RunningServerRegistry));
    private static readonly long StartTimeToleranceTicks = TimeSpan.FromSeconds(1).Ticks;

    private readonly string _filePath;
    private readonly IProcessInspector _inspector;
    private readonly Dictionary<string, TrackedServerProcess> _session = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _removed = new(StringComparer.OrdinalIgnoreCase);
    private readonly Lock _lock = new();

    // 以單一鏈式工作序列化背景寫入，確保最後寫入者為最新狀態
    private Task _writeChain = Task.CompletedTask;

    public RunningServerRegistry(string userDataDirectory, IProcessInspector inspector)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(userDataDirectory);
        ArgumentNullException.ThrowIfNull(inspector);
        _filePath = Path.Combine(userDataDirectory, "running_servers.json");
        _inspector = inspector;
    }

    public void Record(string serverName, int pid)
    {
        DateTimeOffset? startTime = _inspector.GetStartTimeUtc(pid);
        if (startTime is null)
        {
            Logger.Warning("無法取得伺服器「{Server}」行程 (PID: {Pid}) 的啟動時間，略過登記", serverName, pid);
            return;
        }

        lock (_lock)
        {
            _session[serverName] = new TrackedServerProcess(serverName, pid, startTime.Value.UtcTicks);
            _removed.Remove(serverName);
            QueueWriteLockedAsync();
        }
    }

    public void Remove(string serverName)
    {
        lock (_lock)
        {
            _session.Remove(serverName);
            _removed.Add(serverName);
            QueueWriteLockedAsync();
        }
    }

    public Task<IReadOnlyList<TrackedServerProcess>> FindOrphansAsync(CancellationToken cancellationToken = default) =>
        Task.Run<IReadOnlyList<TrackedServerProcess>>(async () =>
        {
            var tracked = ReadFile();
            if (tracked.Count == 0)
            {
                return [];
            }

            HashSet<string> sessionNames;
            lock (_lock)
            {
                sessionNames = new HashSet<string>(_session.Keys, StringComparer.OrdinalIgnoreCase);
            }

            // 查詢作業系統行程資訊較慢，於鎖外進行
            var survivors = tracked.Where(e => !sessionNames.Contains(e.ServerName) && IsSameProcess(e)).ToList();
            if (survivors.Count != tracked.Count)
            {
                var dead = tracked.Except(survivors).ToHashSet();
                Task write;
                lock (_lock)
                {
                    write = QueueWriteLockedAsync(dead.Contains);
                }

                await write.ConfigureAwait(false);
            }

            return survivors;
        }, cancellationToken);

    public Task<bool> TerminateAsync(TrackedServerProcess process, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(process);
        return Task.Run(async () =>
        {
            bool success = !IsSameProcess(process) || _inspector.KillProcessTree(process.Pid);
            if (success)
            {
                Task write;
                lock (_lock)
                {
                    write = QueueWriteLockedAsync(e => string.Equals(e.ServerName, process.ServerName, StringComparison.OrdinalIgnoreCase) && e.Pid == process.Pid);
                }

                await write.ConfigureAwait(false);
            }

            return success;
        }, cancellationToken);
    }

    public Task FlushAsync()
    {
        lock (_lock)
        {
            return _writeChain;
        }
    }

    private bool IsSameProcess(TrackedServerProcess entry)
    {
        DateTimeOffset? start = _inspector.GetStartTimeUtc(entry.Pid);
        return start is not null && Math.Abs(start.Value.UtcTicks - entry.StartTimeUtcTicks) <= StartTimeToleranceTicks;
    }

    private List<TrackedServerProcess> ReadFile() =>
        JsonCodec.TryReadFile<List<TrackedServerProcess>>(_filePath) ?? [];

    private void PersistLocked(List<TrackedServerProcess> entries)
    {
        if (!AtomicFileWriter.WriteJson(_filePath, entries))
        {
            Logger.Warning("寫入伺服器行程登記檔失敗: {Path}", _filePath);
        }
    }

    /// <summary>排入背景寫入：讀取檔案、排除 <paramref name="discard"/> 指定項目後與本次工作階段登記合併；呼叫端須已持有 _lock</summary>
    private Task QueueWriteLockedAsync(Func<TrackedServerProcess, bool>? discard = null)
    {
        _writeChain = _writeChain.ContinueWith(
            _ =>
            {
                try
                {
                    lock (_lock)
                    {
                        var merged = ReadFile()
                            .Where(e => !_session.ContainsKey(e.ServerName) && !_removed.Contains(e.ServerName) && discard?.Invoke(e) != true)
                            .Concat(_session.Values)
                            .ToList();
                        PersistLocked(merged);
                    }
                }
                catch (Exception ex)
                {
                    // 寫入鏈須持續可用，失敗記錄後不中斷後續寫入
                    Logger.Warning(ex, "更新伺服器行程登記檔失敗: {Path}", _filePath);
                }
            },
            CancellationToken.None,
            TaskContinuationOptions.None,
            TaskScheduler.Default);
        return _writeChain;
    }
}
