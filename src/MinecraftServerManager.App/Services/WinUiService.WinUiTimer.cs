using Microsoft.UI.Dispatching;

namespace MinecraftServerManager.App.Services;

public sealed partial class WinUiService
{
    private sealed partial class WinUiTimer : IUiTimer
    {
        private readonly DispatcherQueueTimer _timer;
        private readonly Action _tick;
        private bool _disposed;

        public WinUiTimer(DispatcherQueue dispatcherQueue, TimeSpan interval, Action tick)
        {
            _tick = tick;
            _timer = dispatcherQueue.CreateTimer();
            _timer.Interval = interval;
            _timer.IsRepeating = true;
            _timer.Tick += OnTick;
        }

        public void StartTimer()
        {
            if (!_disposed)
            {
                _timer.Start();
            }
        }

        public void StopTimer() => _timer.Stop();

        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            _timer.Stop();
            _timer.Tick -= OnTick;
        }

        private void OnTick(DispatcherQueueTimer sender, object args) => _tick();
    }
}
