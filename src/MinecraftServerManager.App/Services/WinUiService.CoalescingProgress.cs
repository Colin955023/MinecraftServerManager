using Microsoft.UI.Dispatching;

namespace MinecraftServerManager.App.Services;

public sealed partial class WinUiService
{
    /// <summary>合併進度回報：UI 執行緒同時最多一筆待處理，只顯示最新一筆，避免進度倒退</summary>
    private sealed class CoalescingProgress<TReport>(DispatcherQueue dispatcherQueue, Action<TReport> handler) : IProgress<TReport>
    {
        private readonly Lock _lock = new();
        private TReport? _latest;
        private bool _pending;

        public void Report(TReport value)
        {
            lock (_lock)
            {
                _latest = value;
                if (_pending)
                {
                    return;
                }

                _pending = true;
            }

            if (!dispatcherQueue.TryEnqueue(Flush))
            {
                lock (_lock)
                {
                    _pending = false;
                }
            }
        }

        private void Flush()
        {
            TReport report;
            lock (_lock)
            {
                report = _latest!;
                _pending = false;
            }

            handler(report);
        }
    }
}
