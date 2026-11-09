using System.ComponentModel;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 具備自主倒數、滑鼠暫停功能的 WinUI 3 原生 NotificationDialog
/// </summary>
public sealed partial class NotificationDialog : ContentDialog, INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    private readonly IUiTimer _autoCloseTimer;
    private readonly double _totalSeconds;
    private double _elapsedSeconds;
    private bool _isPaused;
    private bool _isClosing;

    public string DialogTitle { get; }
    public string Message { get; }
    public string IconGlyph { get; }
    public string ButtonText { get; private set; }

    public NotificationDialog(IUiService ui, string title, string message, NotificationLevel level = NotificationLevel.Warning)
    {
        ArgumentNullException.ThrowIfNull(ui);
        InitializeComponent();

        DialogTitle = title;
        Message = message;
        IconGlyph = level == NotificationLevel.Error ? "❌" : "⚠️";
        _totalSeconds = level == NotificationLevel.Error ? 10.0 : 6.0;
        ButtonText = $"確定 ({(int)_totalSeconds}s)";

        _autoCloseTimer = ui.CreateUiTimer(TimeSpan.FromMilliseconds(100), AutoCloseTimer_Tick);
        // 任何關閉途徑（含 Esc）皆停止倒數，避免關閉後計時器持續觸發 Hide()
        Closed += (_, _) =>
        {
            _isClosing = true;
            _autoCloseTimer.StopTimer();
        };
        _autoCloseTimer.StartTimer();
    }

    private void Dialog_PointerEntered(object sender, PointerRoutedEventArgs e)
    {
        _isPaused = true;
        UpdateCountdownUi();
    }

    private void Dialog_PointerExited(object sender, PointerRoutedEventArgs e)
    {
        _isPaused = false;
        UpdateCountdownUi();
    }

    private void Dialog_PrimaryButtonClick(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        _autoCloseTimer.StopTimer();
        _isClosing = true;
    }

    private void AutoCloseTimer_Tick()
    {
        if (_isPaused || _isClosing)
        {
            return;
        }

        _elapsedSeconds += 0.1;
        if (_elapsedSeconds >= _totalSeconds)
        {
            _autoCloseTimer.StopTimer();
            _isClosing = true;
            Hide();
        }
        else
        {
            UpdateCountdownUi();
        }
    }

    private void UpdateCountdownUi()
    {
        double remaining = Math.Max(0, _totalSeconds - _elapsedSeconds);
        int ceilSeconds = (int)Math.Ceiling(remaining);

        ButtonText = _isPaused ? "確定 (已暫停)" : $"確定 ({ceilSeconds}s)";
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ButtonText)));

        double percent = Math.Clamp(remaining / _totalSeconds * 100.0, 0, 100);
        CountdownProgress.Value = percent;
    }
}
