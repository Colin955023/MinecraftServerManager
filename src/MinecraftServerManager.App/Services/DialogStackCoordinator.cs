namespace MinecraftServerManager.App.Services;

/// <summary>
/// 對話框堆疊協調器：處理同一 UI 執行緒中巢狀對話框的中斷、自動隱藏、重現與狀態恢復。
/// WinUI 同一執行緒同時只能開啟一個 ContentDialog，因此新對話框必須等待前一個對話框真正隱藏後才顯示。
/// 此類別不直接相依 UI 框架型別，具備完整的執行緒安全與單元測試支援。
/// </summary>
public sealed class DialogStackCoordinator
{
    /// <summary>
    /// 等待前一個對話框隱藏的逾時上限；對話框拒絕隱藏時避免永久卡住
    /// </summary>
    private static readonly TimeSpan PreviousHideTimeout = TimeSpan.FromSeconds(3);

    private readonly Stack<DialogEntry> _stack = new();
    private readonly Lock _lock = new();

    /// <summary>
    /// 以非同步方式排隊並顯示對話框；若已有顯示中之對話框，自動中斷並暫存其狀態，待本對話框關閉後自動喚醒恢復。
    /// </summary>
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
        lock (_lock)
        {
            if (_stack.Count > 0)
            {
                previousActive = _stack.Peek();
                previousActive.MarkInterrupted();
            }
            _stack.Push(currentEntry);
        }

        try
        {
            if (previousActive is not null)
            {
                // 要求前一個對話框隱藏，並等待其真正關閉後才顯示本對話框，避免「同時只能開啟一個 ContentDialog」例外
                previousActive.RequestHide();
                await Task.WhenAny(previousActive.HiddenTask, Task.Delay(PreviousHideTimeout)).ConfigureAwait(true);
            }

            while (true)
            {
                // 尚未顯示或顯示期間被更上層對話框中斷時，等待更上層對話框關閉後再（重新）顯示
                Task? resumeTask = null;
                lock (_lock)
                {
                    if (currentEntry.IsInterrupted)
                    {
                        resumeTask = currentEntry.ResumeTask;
                        currentEntry.ResetInterrupted();
                    }
                }

                if (resumeTask is not null)
                {
                    await resumeTask.ConfigureAwait(true);
                    continue;
                }

                TResult result;
                currentEntry.MarkShowing();
                try
                {
                    result = await showAsync().ConfigureAwait(true);
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
                if (_stack.Count > 0 && ReferenceEquals(_stack.Peek(), currentEntry))
                {
                    _stack.Pop();
                }
                if (_stack.Count > 0)
                {
                    toResume = _stack.Peek();
                }
            }

            // 喚醒前一層對話框重新顯示
            toResume?.SignalResume();
        }
    }

    private sealed class DialogEntry(Action hideAction)
    {
        private readonly Action _hideAction = hideAction;
        private TaskCompletionSource _resumeTcs = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private TaskCompletionSource _hiddenTcs = CreateCompleted();

        public bool IsInterrupted { get; private set; }

        public Task ResumeTask => _resumeTcs.Task;

        /// <summary>
        /// 對話框目前未顯示時即為已完成狀態
        /// </summary>
        public Task HiddenTask => _hiddenTcs.Task;

        /// <summary>
        /// 標記被上層對話框中斷，並於此時建立新的恢復訊號，確保上層關閉時的喚醒不會遺失
        /// </summary>
        public void MarkInterrupted()
        {
            IsInterrupted = true;
            _resumeTcs = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        }

        public void MarkShowing() => _hiddenTcs = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);

        public void MarkHidden() => _hiddenTcs.TrySetResult();

        public void RequestHide() => _hideAction();

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
