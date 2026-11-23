using System.Collections.Concurrent;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Services;

/// <summary>伺服器平順停止流程：送出 stop 後等待，逾時由使用者決定繼續等待或強制終止</summary>
public sealed class ServerStopCoordinator
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerStopCoordinator));

    private readonly IUiService _ui;
    private readonly IServerRuntimeHost _runtimeHost;
    private readonly ConcurrentDictionary<string, bool> _stopping = new(StringComparer.OrdinalIgnoreCase);

    public ServerStopCoordinator(IUiService ui, IServerRuntimeHost runtimeHost)
    {
        ArgumentNullException.ThrowIfNull(ui);
        ArgumentNullException.ThrowIfNull(runtimeHost);

        _ui = ui;
        _runtimeHost = runtimeHost;
    }

    /// <summary>停止中狀態變更時觸發，參數為伺服器名稱</summary>
    public event Action<string>? StoppingStateChanged;

    /// <summary>指定伺服器是否正在執行平順停止流程</summary>
    public bool IsStopping(string serverName) => _stopping.ContainsKey(serverName);

    /// <summary>平順停止伺服器；已停止回傳 true，重複呼叫回傳 false</summary>
    public async Task<bool> StopAsync(string serverName)
    {
        var runtime = _runtimeHost.GetRuntime(serverName);
        if (!runtime.IsRunning)
        {
            return true;
        }

        if (!_stopping.TryAdd(serverName, true))
        {
            _ui.Notify($"伺服器「{serverName}」正在停止中，請稍候", NotificationType.Info);
            return false;
        }

        StoppingStateChanged?.Invoke(serverName);
        try
        {
            _ui.Notify($"已送出停止指令，等待伺服器「{serverName}」儲存世界並關閉...", NotificationType.Info);
            string[] singleTarget = [serverName];
            bool stopped = await StopServersCoreAsync(singleTarget, singleTarget);
            if (stopped && !runtime.IsRunning)
            {
                _ui.Notify($"伺服器「{serverName}」已停止", NotificationType.Success);
            }

            return stopped;
        }
        finally
        {
            _stopping.TryRemove(serverName, out _);
            StoppingStateChanged?.Invoke(serverName);
        }
    }

    /// <summary>結束程式前停止全部執行中的伺服器；使用者取消回傳 false。已在停止中的伺服器不重送 stop，只一併等待</summary>
    public async Task<bool> StopAllForShutdownAsync()
    {
        var names = _runtimeHost.GetRunningServerNames();
        if (names.Count == 0)
        {
            return true;
        }

        bool confirmed = await _ui.ConfirmChoiceAsync(
            $"目前有 {names.Count} 台伺服器正在執行：\n{FormatList(names)}\n\n結束程式前會先送出 stop 指令，等待伺服器儲存世界後關閉。",
            "結束程式",
            primaryText: "停止伺服器並結束",
            closeText: "取消",
            UiMessageLevel.Warning);
        if (!confirmed)
        {
            return false;
        }

        var claimed = names.Where(name => _stopping.TryAdd(name, true)).ToList();
        foreach (string name in claimed)
        {
            StoppingStateChanged?.Invoke(name);
        }

        try
        {
            using var progress = _ui.ShowOperationProgress("正在停止伺服器", "已送出停止指令，等待伺服器儲存世界並關閉...");
            return await StopServersCoreAsync(names, claimed, progress);
        }
        finally
        {
            foreach (string name in claimed)
            {
                _stopping.TryRemove(name, out _);
                StoppingStateChanged?.Invoke(name);
            }
        }
    }

    private async Task<bool> StopServersCoreAsync(
        IReadOnlyList<string> targets,
        IReadOnlyList<string> sendStopTargets,
        IOperationProgress? progress = null)
    {
        foreach (string name in sendStopTargets)
        {
            try
            {
                await _runtimeHost.GetRuntime(name).SendCommandAsync("stop");
            }
            catch (Exception ex) when (ProcessControlExceptions.IsExpected(ex))
            {
                Logger.Warning(ex, "傳送 stop 指令至伺服器「{Server}」失敗", name);
            }
        }

        var remaining = targets.Where(_runtimeHost.IsRunning).ToList();
        if (remaining.Count == 0)
        {
            return true;
        }

        while (true)
        {
            if (remaining.Count == 1)
            {
                await _runtimeHost.GetRuntime(remaining[0]).WaitForExitAsync(ServerDefaults.GracefulStopTimeout);
            }
            else
            {
                await Task.WhenAll(remaining.Select(n => _runtimeHost.GetRuntime(n).WaitForExitAsync(ServerDefaults.GracefulStopTimeout)));
            }

            remaining = remaining.Where(_runtimeHost.IsRunning).ToList();
            if (progress is not null)
            {
                int stopped = targets.Count - remaining.Count;
                progress.UpdateProgress(stopped, targets.Count, $"已停止 {stopped}／{targets.Count} 台伺服器...");
            }

            if (remaining.Count == 0)
            {
                return true;
            }

            _ui.ActivateMainWindow();
            string prompt = remaining.Count == 1
                ? $"伺服器「{remaining[0]}」在 {ServerDefaults.GracefulStopTimeout.TotalSeconds:0} 秒內尚未完成關閉，可能仍在儲存世界。\n\n強制終止可能導致尚未寫入的世界資料遺失。"
                : $"下列伺服器在 {ServerDefaults.GracefulStopTimeout.TotalSeconds:0} 秒內尚未完成關閉：\n{FormatList(remaining)}\n\n強制終止可能導致尚未寫入的世界資料遺失。";

            bool force = await _ui.ConfirmChoiceAsync(
                prompt,
                "伺服器尚未關閉",
                primaryText: "強制終止",
                closeText: "繼續等待",
                UiMessageLevel.Warning);

            remaining = remaining.Where(_runtimeHost.IsRunning).ToList();
            if (remaining.Count == 0)
            {
                return true;
            }

            if (force)
            {
                foreach (string name in remaining)
                {
                    Logger.Warning("使用者選擇強制終止伺服器「{Server}」", name);
                    try
                    {
                        await _runtimeHost.GetRuntime(name).StopAsync(TimeSpan.Zero);
                        if (targets.Count == 1)
                        {
                            _ui.Notify($"已強制終止伺服器「{name}」", NotificationType.Warning);
                        }
                    }
                    catch (Exception ex) when (ProcessControlExceptions.IsExpected(ex))
                    {
                        Logger.Error(ex, "強制終止伺服器「{Server}」失敗", name);
                        if (targets.Count == 1)
                        {
                            _ui.Notify($"強制終止伺服器「{name}」失敗：{ex.Message}", NotificationType.Error);
                        }
                    }
                }

                return true;
            }
        }
    }

    private static string FormatList(IEnumerable<string> names) => string.Join("\n", names.Select(static n => $"• {n}"));
}
