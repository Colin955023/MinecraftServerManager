using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>
/// 測試用 UI 服務：PostToUi 立即執行、計時器改為手動觸發，並記錄提示與對話方塊呼叫
/// </summary>
internal sealed class ManualUiService : NoOpUiService
{
    private readonly List<ManualUiTimer> _timers = [];

    public bool ConfirmResult { get; set; } = true;
    public List<string> ConfirmMessages { get; } = [];
    public List<string> ErrorMessages { get; } = [];
    public List<(string Message, NotificationType Type)> Notifications { get; } = [];

    public override void PostToUi(Action action, bool afterLayout = false) => action();

    public override IUiTimer CreateUiTimer(TimeSpan interval, Action tick)
    {
        _ = interval;
        var timer = new ManualUiTimer(tick);
        _timers.Add(timer);
        return timer;
    }

    /// <summary>
    /// 觸發所有執行中的計時器一次
    /// </summary>
    public void TickRunningTimers()
    {
        foreach (var timer in _timers.ToArray())
        {
            if (timer.IsRunning)
            {
                timer.Tick();
            }
        }
    }

    public override Task<bool> ConfirmAsync(string message, string title, UiMessageLevel level = UiMessageLevel.Question)
    {
        ConfirmMessages.Add(message);
        return Task.FromResult(ConfirmResult);
    }

    public override Task ShowErrorAsync(string message, string title)
    {
        ErrorMessages.Add(message);
        return Task.CompletedTask;
    }

    public override void ShowNotification(string message, string? title = null, NotificationType type = NotificationType.Info) =>
        Notifications.Add((message, type));

    private sealed class ManualUiTimer(Action tick) : IUiTimer
    {
        public bool IsRunning { get; private set; }

        public void StartTimer() => IsRunning = true;

        public void StopTimer() => IsRunning = false;

        public void Tick() => tick();
    }
}
