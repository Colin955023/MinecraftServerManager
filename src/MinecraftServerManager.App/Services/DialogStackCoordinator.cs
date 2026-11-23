using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Services;

/// <summary>對話框堆疊協調器：同一執行緒同時只能開一個 ContentDialog，巢狀時先隱藏上層、關閉後重現</summary>
public sealed class DialogStackCoordinator
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(DialogStackCoordinator));

    /// <summary>等待前一個對話框隱藏的逾時上限；對話框拒絕隱藏時避免永久卡住</summary>
    private static readonly TimeSpan PreviousHideTimeout = TimeSpan.FromSeconds(3);

    // 以串列保存堆疊：任一層（含中間層）結束時都能移除自身節點，不會殘留而攔截恢復訊號
    private readonly LinkedList<DialogEntry> _stack = new();
    private readonly Lock _lock = new();

    /// <summary>排隊顯示對話框；已有顯示中的對話框時先暫時隱藏，本對話框關閉後恢復</summary>
    /// <typeparam name="TResult">對話框傳回之結果型別</typeparam>
    /// <param name="showAsync">呼叫顯示對話框之委派</param>
    /// <param name="hideAction">要求對話框暫時隱藏之委派</param>
    /// <returns>對話框被使用者真正關閉時的結果</returns>
    public async Task<TResult> ShowDialogAsync<TResult>(
        Func<Task<TResult>> showAsync,
        Action hideAction)
    {
        ArgumentNullException.ThrowIfNull(showAsync);
        ArgumentNullException.ThrowIfNull(hideAction);

        DialogEntry currentEntry = new(hideAction);
        DialogEntry? previousActive = null;
        LinkedListNode<DialogEntry> node;
        lock (_lock)
        {
            if (_stack.Last is { } last)
            {
                previousActive = last.Value;
                previousActive.MarkInterrupted();
            }

            node = _stack.AddLast(currentEntry);
        }

        try
        {
            if (previousActive is not null)
            {
                // 等前一個對話框真正關閉後才顯示（同時只能開一個 ContentDialog）
                await HidePreviousAsync(previousActive);
            }

            while (true)
            {
                // 尚未顯示或顯示期間被更上層對話框中斷時，等待更上層對話框關閉後再（重新）顯示；
                // 檢查中斷與標記顯示需在同一鎖內，避免與新對話框的中斷判斷交錯而同時顯示兩個 ContentDialog
                Task? resumeTask = null;
                lock (_lock)
                {
                    if (currentEntry.IsInterrupted)
                    {
                        resumeTask = currentEntry.ResumeTask;
                        currentEntry.ResetInterrupted();
                    }
                    else
                    {
                        currentEntry.MarkShowing();
                    }
                }

                if (resumeTask is not null)
                {
                    await resumeTask;
                    continue;
                }

                TResult result;
                try
                {
                    result = await showAsync();
                }
                finally
                {
                    currentEntry.MarkHidden();
                }

                lock (_lock)
                {
                    if (!currentEntry.IsInterrupted)
                    {
                        return result;
                    }
                }
            }
        }
        finally
        {
            DialogEntry? toResume = null;
            lock (_lock)
            {
                // 只有最上層結束時才喚醒下一層；中間層結束只移除自身
                bool wasTop = ReferenceEquals(_stack.Last, node);
                _stack.Remove(node);
                if (wasTop && _stack.Last is { } last)
                {
                    toResume = last.Value;
                }
            }

            toResume?.SignalResume();
        }
    }

    private static async Task HidePreviousAsync(DialogEntry previous)
    {
        try
        {
            previous.RequestHide();
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "要求前一個對話框隱藏失敗");
        }

        using var timeoutCts = new CancellationTokenSource();
        Task completed = await Task.WhenAny(previous.HiddenTask, Task.Delay(PreviousHideTimeout, timeoutCts.Token));
        if (completed == previous.HiddenTask)
        {
            await timeoutCts.CancelAsync();
        }
        else
        {
            Logger.Warning("等待前一個對話框隱藏逾時（{Timeout} 秒），繼續顯示新對話框", PreviousHideTimeout.TotalSeconds);
        }
    }

    private sealed class DialogEntry(Action hideAction)
    {
        private TaskCompletionSource _resumeTcs = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private TaskCompletionSource _hiddenTcs = CreateCompleted();

        public bool IsInterrupted { get; private set; }

        public Task ResumeTask => _resumeTcs.Task;

        /// <summary>對話框目前未顯示時即為已完成狀態</summary>
        public Task HiddenTask => _hiddenTcs.Task;

        /// <summary>標記被上層對話框中斷，並於此時建立新的恢復訊號，確保上層關閉時的喚醒不會遺失</summary>
        public void MarkInterrupted()
        {
            IsInterrupted = true;
            _resumeTcs = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        }

        public void MarkShowing() => _hiddenTcs = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);

        public void MarkHidden() => _hiddenTcs.TrySetResult();

        public void RequestHide() => hideAction();

        public void ResetInterrupted() => IsInterrupted = false;

        public void SignalResume() => _resumeTcs.TrySetResult();

        private static TaskCompletionSource CreateCompleted()
        {
            var tcs = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            tcs.SetResult();
            return tcs;
        }
    }
}
