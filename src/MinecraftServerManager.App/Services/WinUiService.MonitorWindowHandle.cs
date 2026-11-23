using MinecraftServerManager.App.Views;

namespace MinecraftServerManager.App.Services;

public sealed partial class WinUiService
{
    /// <summary>監控視窗控制點；視窗於 UI 執行緒建立後才附加，所有操作皆派送至 UI 執行緒</summary>
    private sealed class MonitorWindowHandle(WinUiService owner) : IMonitorWindow
    {
        private ServerMonitorWindow? _window;
        private bool _closeRequested;
        private volatile bool _isOpen = true;

        public bool IsOpen => _isOpen;

        public event Action? Closed;

        public void Attach(ServerMonitorWindow window)
        {
            _window = window;
            window.Closed += (_, _) =>
            {
                _isOpen = false;
                Closed?.Invoke();
            };
            if (_closeRequested)
            {
                window.Close();
            }
        }

        public void BringToFront() => owner.RunOnUi(() =>
        {
            if (_window is not null)
            {
                BringWindowToFront(_window);
            }
        });

        public void Close() => owner.RunOnUi(() =>
        {
            _closeRequested = true;
            _window?.Close();
        });
    }
}
