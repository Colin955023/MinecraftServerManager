using System.Windows;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

public enum NotificationLevel
{
    Warning,
    Error,
}

/// <summary>
/// 具備自主平滑淡出與滑鼠懸停暫停功能的系統提示視窗
/// </summary>
public partial class NotificationDialog : Window
{
    private readonly NotificationLevel _level;
    private readonly DispatcherTimer? _autoCloseTimer;
    private readonly double _totalSeconds;
    private double _elapsedSeconds;
    private bool _isPaused;
    private bool _isClosing;

    public NotificationDialog(string title, string message, NotificationLevel level = NotificationLevel.Warning)
    {
        InitializeComponent();

        _level = level;
        Title = title;
        TitleText.Text = title;
        MessageText.Text = message;

        _totalSeconds = level switch
        {
            NotificationLevel.Error => 10.0,
            _ => 6.0
        };

        switch (level)
        {
            case NotificationLevel.Error:
                IconText.Text = "❌";
                CountdownProgress.SetResourceReference(ForegroundProperty, "DangerBrush");
                break;
            case NotificationLevel.Warning:
            default:
                IconText.Text = "⚠️";
                CountdownProgress.SetResourceReference(ForegroundProperty, "WarningBrush");
                break;
        }

        UpdateCountdownUi();

        _autoCloseTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMilliseconds(100)
        };
        _autoCloseTimer.Tick += AutoCloseTimer_Tick;
        _autoCloseTimer.Start();
    }

    private void AutoCloseTimer_Tick(object? sender, EventArgs e)
    {
        if (_isPaused || _isClosing)
        {
            return;
        }

        _elapsedSeconds += 0.1;
        if (_elapsedSeconds >= _totalSeconds)
        {
            _autoCloseTimer?.Stop();
            BeginFadeOutAndClose();
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

        if (_isPaused)
        {
            OkButton.Content = "確定 (已暫停)";
        }
        else
        {
            OkButton.Content = $"確定 ({ceilSeconds}s)";
        }

        double percent = Math.Clamp(remaining / _totalSeconds * 100.0, 0, 100);
        CountdownProgress.Value = percent;
    }

    private void Window_Loaded(object sender, RoutedEventArgs e)
    {
        switch (_level)
        {
            case NotificationLevel.Error:
                AudioFeedback.PlayError();
                break;
            case NotificationLevel.Warning:
            default:
                AudioFeedback.PlayWarning();
                break;
        }
    }

    private void Window_MouseEnter(object sender, System.Windows.Input.MouseEventArgs e)
    {
        _isPaused = true;
        UpdateCountdownUi();
    }

    private void Window_MouseLeave(object sender, System.Windows.Input.MouseEventArgs e)
    {
        _isPaused = false;
        UpdateCountdownUi();
    }

    private static readonly Lock SyncLock = new();
    private static string? _lastMessage;
    private static DateTimeOffset _lastShownTime;

    public static void Show(Window? owner, string title, string message, NotificationLevel level = NotificationLevel.Warning)
    {
        lock (SyncLock)
        {
            if (string.Equals(message, _lastMessage, StringComparison.Ordinal) &&
                DateTimeOffset.UtcNow - _lastShownTime < TimeSpan.FromSeconds(2))
            {
                return;
            }

            _lastMessage = message;
            _lastShownTime = DateTimeOffset.UtcNow;
        }

        void Action()
        {
            var dialog = new NotificationDialog(title, message, level);
            Window? effectiveOwner = owner ?? Application.Current?.MainWindow;
            if (effectiveOwner is { IsVisible: true })
            {
                dialog.Owner = effectiveOwner;
            }
            dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen;

            dialog.ShowDialog();
        }

        if (Application.Current?.Dispatcher.CheckAccess() == false)
        {
            Application.Current.Dispatcher.BeginInvoke(new Action(Action));
        }
        else
        {
            Action();
        }
    }

    private void OkButton_Click(object sender, RoutedEventArgs e)
    {
        _autoCloseTimer?.Stop();
        SafeClose();
    }

    private void BeginFadeOutAndClose()
    {
        if (_isClosing)
        {
            return;
        }

        _isClosing = true;
        _autoCloseTimer?.Stop();

        var anim = new DoubleAnimation(0.0, TimeSpan.FromMilliseconds(280))
        {
            EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseOut }
        };
        anim.Completed += (_, _) => SafeClose();
        BeginAnimation(OpacityProperty, anim);
    }

    private void SafeClose()
    {
        try
        {
            if (System.Windows.Interop.ComponentDispatcher.IsThreadModal)
            {
                DialogResult = true;
            }
        }
        catch (InvalidOperationException)
        {
        }

        Close();
    }

    protected override void OnClosed(EventArgs e)
    {
        _autoCloseTimer?.Stop();
        base.OnClosed(e);
        try
        {
            if (Owner is not null)
            {
                if (Owner.WindowState == WindowState.Minimized)
                {
                    Owner.WindowState = WindowState.Normal;
                }
                Owner.Activate();
                Owner.Focus();
            }
        }
        catch
        {
        }
    }
}
