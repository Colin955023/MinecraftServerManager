using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>測試用 UI 服務：PostToUi 立即執行、計時器改為手動觸發，並記錄提示與對話方塊呼叫</summary>
internal class ManualUiService : NoOpUiService
{
    private readonly List<ManualUiTimer> _timers = [];

    public bool ConfirmResult { get; set; } = true;
    public bool ConfirmThrows { get; set; }
    public List<string> ConfirmMessages { get; } = [];
    public Queue<bool> ChoiceResults { get; } = new();
    public TaskCompletionSource<bool>? ChoiceGate { get; set; }
    public List<(string Message, string PrimaryText)> ChoiceMessages { get; } = [];
    public bool? YesNoCancelDecision { get; set; } = true;
    public string? FolderToPick { get; set; }
    public string? SaveFileResult { get; set; }
    public bool? ImportServerResult { get; set; }
    public List<ModUpdateCandidateItem> ShownModUpdateCandidates { get; } = [];
    public int ActivateMainWindowCount { get; private set; }
    public bool RestartCalled { get; private set; }
    public Exception? RestartException { get; set; }
    public List<string> ErrorMessages { get; } = [];
    public string? LastErrorMessage => ErrorMessages.Count > 0 ? ErrorMessages[^1] : null;
    public List<(string Message, NotificationType Type)> Notifications { get; } = [];
    public (string Message, NotificationType Type)? LastNotification => Notifications.Count > 0 ? Notifications[^1] : null;

    public override void PostToUi(Action action, bool afterLayout = false) => action();

    public override IUiTimer CreateUiTimer(TimeSpan interval, Action tick)
    {
        _ = interval;
        var timer = new ManualUiTimer(tick);
        _timers.Add(timer);
        return timer;
    }

    /// <summary>觸發所有執行中的計時器一次</summary>
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
        if (ConfirmThrows)
        {
            return Task.FromException<bool>(new InvalidOperationException("Only a single ContentDialog can be open at any time."));
        }

        ConfirmMessages.Add(message);
        return Task.FromResult(ConfirmResult);
    }

    public override Task<bool> ConfirmChoiceAsync(string message, string title, string primaryText, string closeText, UiMessageLevel level = UiMessageLevel.Question)
    {
        ChoiceMessages.Add((message, primaryText));
        if (ChoiceGate is not null)
        {
            return ChoiceGate.Task;
        }

        return Task.FromResult(ChoiceResults.Count > 0 ? ChoiceResults.Dequeue() : ConfirmResult);
    }

    public override Task<bool?> ConfirmYesNoCancelAsync(
        string message,
        string title,
        string yesText = "是",
        string noText = "否",
        string cancelText = "取消",
        UiMessageLevel level = UiMessageLevel.Question) =>
        Task.FromResult(YesNoCancelDecision);

    public override Task<string?> PickFolderAsync(string title, string? initialDirectory = null) =>
        Task.FromResult(FolderToPick);

    public override Task<string?> PickSaveFileAsync(string title, string defaultFileName, FileTypeChoice fileType) =>
        Task.FromResult(SaveFileResult);

    public override Task<bool?> ShowImportServerAsync(ImportServerViewModel viewModel) =>
        Task.FromResult(ImportServerResult);

    public override Task<IReadOnlyList<ModUpdateCandidateItem>?> ShowModUpdatesAsync(IEnumerable<ModUpdateCandidateItem> items)
    {
        ShownModUpdateCandidates.AddRange(items);
        return Task.FromResult<IReadOnlyList<ModUpdateCandidateItem>?>(null);
    }

    public override void ActivateMainWindow() => ActivateMainWindowCount++;

    public override void RestartApplication()
    {
        RestartCalled = true;
        if (RestartException is not null)
        {
            throw RestartException;
        }
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
