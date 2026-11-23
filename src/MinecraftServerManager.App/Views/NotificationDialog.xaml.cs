using System.ComponentModel;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>具備自主倒數的錯誤對話框；滑鼠停留或鍵盤焦點在內時暫停倒數</summary>
public sealed partial class NotificationDialog : ContentDialog, INotifyPropertyChanged, INestableContentDialog
{
    private static readonly PropertyChangedEventArgs ButtonTextChangedArgs = new(nameof(ButtonText));

    private readonly IUiTimer _autoCloseTimer;
    private readonly double _totalSeconds;
    private double _elapsedSeconds;
    private bool _pointerInside;
    private bool _keyboardFocused;
    private bool _isClosing;
    private bool _temporarilyHidden;
    private string _buttonText;

    public NotificationDialog(IUiService ui, string title, string message)
    {
        ArgumentNullException.ThrowIfNull(ui);

        DialogTitle = title;
        Message = message;
        _totalSeconds = 10.0;
        _buttonText = $"確定（{(int)_totalSeconds}s）";

        InitializeComponent();

        _autoCloseTimer = ui.CreateUiTimer(TimeSpan.FromMilliseconds(100), OnAutoCloseTimerTick);
        // 倒數僅於實際顯示期間進行：排隊等待或被巢狀對話框暫時隱藏時不計時，重新顯示後續算
        Opened += (_, _) =>
        {
            _temporarilyHidden = false;
            if (!_isClosing)
            {
                _autoCloseTimer.StartTimer();
            }
        };
        GotFocus += (_, e) => SetPauseState(ref _keyboardFocused, e.OriginalSource is Control { FocusState: FocusState.Keyboard });
        LostFocus += (_, _) => SetPauseState(ref _keyboardFocused, false);
        // 巢狀隱藏也會觸發 Closed，僅停止計時；真正關閉（含按 Escape）後立即釋放計時器
        Closed += (_, _) =>
        {
            _autoCloseTimer.StopTimer();
            if (!_temporarilyHidden)
            {
                _isClosing = true;
                _autoCloseTimer.Dispose();
                Bindings.StopTracking();
            }
        };
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public string DialogTitle { get; }

    public string Message { get; }

    /// <summary>圖示前景主題資源鍵</summary>
    public string IconBrushKey { get; } = UiBindHelpers.DangerTextBrushKey;

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

    private bool IsPaused => _pointerInside || _keyboardFocused;

    /// <summary>暫時隱藏以讓位給巢狀對話框</summary>
    public void HideForNestedDialog()
    {
        _temporarilyHidden = true;
        Hide();
    }

    private void OnDialogPointerEntered(object sender, PointerRoutedEventArgs e) => SetPauseState(ref _pointerInside, true);

    private void OnDialogPointerExited(object sender, PointerRoutedEventArgs e) => SetPauseState(ref _pointerInside, false);

    private void SetPauseState(ref bool field, bool value)
    {
        field = value;
        UpdateCountdownUi();
    }

    private void OnPrimaryButtonClicked(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        _autoCloseTimer.StopTimer();
        _isClosing = true;
    }

    private void OnAutoCloseTimerTick()
    {
        if (IsPaused || _isClosing)
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

        ButtonText = IsPaused ? "確定（已暫停）" : $"確定（{ceilSeconds}s）";

        double percent = Math.Clamp(remaining / _totalSeconds * 100.0, 0, 100);
        CountdownProgress.Value = percent;
    }
}
