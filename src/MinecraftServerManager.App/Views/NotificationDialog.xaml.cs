using System.ComponentModel;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>具備自主倒數、滑鼠暫停功能的 WinUI 3 原生錯誤對話方塊</summary>
public sealed partial class NotificationDialog : ContentDialog, INotifyPropertyChanged
{
    private static readonly PropertyChangedEventArgs ButtonTextChangedArgs = new(nameof(ButtonText));

    private readonly IUiTimer _autoCloseTimer;
    private readonly double _totalSeconds;
    private double _elapsedSeconds;
    private bool _isPaused;
    private bool _isClosing;
    private string _buttonText;

    public event PropertyChangedEventHandler? PropertyChanged;

    public string DialogTitle { get; }
    public string Message { get; }
    public string IconGlyph { get; }

    public string ButtonText
    {
        get => _buttonText;
        private set
        {
            if (string.Equals(_buttonText, value, StringComparison.Ordinal))
            {
                return;
            }

            _buttonText = value;
            PropertyChanged?.Invoke(this, ButtonTextChangedArgs);
        }
    }

    public NotificationDialog(IUiService ui, string title, string message)
    {
        ArgumentNullException.ThrowIfNull(ui);
        InitializeComponent();

        DialogTitle = title;
        Message = message;
        IconGlyph = "❌";
        _totalSeconds = 10.0;
        _buttonText = $"確定 ({(int)_totalSeconds}s)";

        _autoCloseTimer = ui.CreateUiTimer(TimeSpan.FromMilliseconds(100), AutoCloseTimer_Tick);
        // 倒數僅於實際顯示期間進行：排隊等待或被巢狀對話框暫時隱藏時不計時，重新顯示後續算
        Opened += (_, _) =>
        {
            if (!_isClosing)
            {
                _autoCloseTimer.StartTimer();
            }
        };
        Closed += (_, _) => _autoCloseTimer.StopTimer();
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

        double percent = Math.Clamp(remaining / _totalSeconds * 100.0, 0, 100);
        CountdownProgress.Value = percent;
    }
}
