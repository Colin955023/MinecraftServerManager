using System.Collections.Concurrent;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Services;

/// <summary>伺服器平順停止流程：送出 stop 後等待，逾時由使用者決定繼續等待或強制終止</summary>
public sealed class ServerStopCoordinator(IUiService ui, IServerRuntimeHost runtimeHost)
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerStopCoordinator));

    private readonly ConcurrentDictionary<string, bool> _stopping = new(StringComparer.OrdinalIgnoreCase);

    /// <summary>停止中狀態變更時觸發，參數為伺服器名稱</summary>
    public event Action<string>? StoppingStateChanged;

    /// <summary>指定伺服器是否正在執行平順停止流程</summary>
    public bool IsStopping(string serverName) => _stopping.ContainsKey(serverName);

    /// <summary>平順停止單一伺服器；已停止（或原本未執行）回傳 true，重複呼叫回傳 false</summary>
    public async Task<bool> StopAsync(string serverName)
    {
        var runtime = runtimeHost.GetRuntime(serverName);
        if (!runtime.IsRunning)
        {
            return true;
        }

        if (!_stopping.TryAdd(serverName, true))
        {
            ui.Notify($"伺服器「{serverName}」正在停止中，請稍候", NotificationType.Info);
            return false;
        }

        StoppingStateChanged?.Invoke(serverName);
        try
        {
            ui.Notify($"已送出停止指令，等待伺服器「{serverName}」儲存世界並關閉...", NotificationType.Info);
            await runtime.SendCommandAsync("stop").ConfigureAwait(true);

            while (true)
            {
                var result = await runtime.WaitForExitAsync(ServerDefaults.GracefulStopTimeout).ConfigureAwait(true);
                if (result is not null)
                {
                    ui.Notify($"伺服器「{serverName}」已停止", NotificationType.Success);
                    break;
                }

                ui.ActivateMainWindow();
                bool force = await ui.ConfirmChoiceAsync(
                    $"伺服器「{serverName}」在 {ServerDefaults.GracefulStopTimeout.TotalSeconds:0} 秒內尚未完成關閉，可能仍在儲存世界。\n\n強制終止可能導致尚未寫入的世界資料遺失。",
                    "伺服器尚未關閉",
                    primaryText: "強制終止",
                    closeText: "繼續等待",
                    UiMessageLevel.Warning).ConfigureAwait(true);

                if (!runtime.IsRunning)
                {
                    ui.Notify($"伺服器「{serverName}」已停止", NotificationType.Success);
                    break;
                }

                if (force)
                {
                    Logger.Warning("使用者選擇強制終止伺服器「{Server}」", serverName);
                    await runtime.StopAsync(TimeSpan.Zero).ConfigureAwait(true);
                    ui.Notify($"已強制終止伺服器「{serverName}」", NotificationType.Warning);
                    break;
                }
            }

            return true;
        }
        finally
        {
            _stopping.TryRemove(serverName, out _);
            StoppingStateChanged?.Invoke(serverName);
        }
    }

    /// <summary>結束程式前停止全部執行中的伺服器；使用者取消回傳 false</summary>
    public async Task<bool> StopAllForShutdownAsync()
    {
        var names = runtimeHost.GetRunningServerNames();
        if (names.Count == 0)
        {
            return true;
        }

        bool confirmed = await ui.ConfirmChoiceAsync(
            $"目前有 {names.Count} 台伺服器正在執行：\n{FormatList(names)}\n\n結束程式前會先送出 stop 指令，等待伺服器儲存世界後關閉。",
            "結束程式",
            primaryText: "停止伺服器並結束",
            closeText: "取消",
            UiMessageLevel.Warning).ConfigureAwait(true);
        if (!confirmed)
        {
            return false;
        }

        using var progress = ui.ShowModOperationProgress("正在停止伺服器", "已送出停止指令，等待伺服器儲存世界並關閉...");
        foreach (string name in names)
        {
            await runtimeHost.GetRuntime(name).SendCommandAsync("stop").ConfigureAwait(true);
        }

        while (true)
        {
            await Task.WhenAll(names.Select(n => runtimeHost.GetRuntime(n).WaitForExitAsync(ServerDefaults.GracefulStopTimeout))).ConfigureAwait(true);

            var remaining = names.Where(runtimeHost.IsRunning).ToList();
            progress.UpdateProgress(names.Count - remaining.Count, names.Count, $"已停止 {names.Count - remaining.Count}／{names.Count} 台伺服器...");
            if (remaining.Count == 0)
            {
                return true;
            }

            ui.ActivateMainWindow();
            bool force = await ui.ConfirmChoiceAsync(
                $"下列伺服器在 {ServerDefaults.GracefulStopTimeout.TotalSeconds:0} 秒內尚未完成關閉：\n{FormatList(remaining)}\n\n強制終止可能導致尚未寫入的世界資料遺失。",
                "伺服器尚未關閉",
                primaryText: "強制終止",
                closeText: "繼續等待",
                UiMessageLevel.Warning).ConfigureAwait(true);

            if (force)
            {
                foreach (string name in remaining.Where(runtimeHost.IsRunning))
                {
                    await runtimeHost.GetRuntime(name).StopAsync(TimeSpan.Zero).ConfigureAwait(true);
                }

                return true;
            }
        }
    }

    private static string FormatList(IEnumerable<string> names) => string.Join("\n", names.Select(static n => $"• {n}"));
}
