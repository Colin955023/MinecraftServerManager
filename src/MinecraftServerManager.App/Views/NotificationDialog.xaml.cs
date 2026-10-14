using System.Media;
using System.Windows;

namespace MinecraftServerManager.App.Views;

public enum NotificationLevel
{
    Info,
    Warning,
    Error,
}

public partial class NotificationDialog : Window
{
    private readonly System.Windows.Threading.DispatcherTimer? _autoCloseTimer;
    private int _remainingSeconds = 3;

    public NotificationDialog(string title, string message, NotificationLevel level = NotificationLevel.Info)
    {
        InitializeComponent();

        Title = title;
        TitleText.Text = title;
        MessageText.Text = message;

        switch (level)
        {
            case NotificationLevel.Error:
                IconText.Text = "❌";
                SystemSounds.Hand.Play();
                break;
            case NotificationLevel.Warning:
                IconText.Text = "⚠️";
                SystemSounds.Exclamation.Play();
                break;
            case NotificationLevel.Info:
            default:
                IconText.Text = "ℹ️";
                SystemSounds.Asterisk.Play();

                _remainingSeconds = 3;
                OkButton.Content = $"確定 ({_remainingSeconds}s)";
                _autoCloseTimer = new System.Windows.Threading.DispatcherTimer
                {
                    Interval = TimeSpan.FromSeconds(1)
                };
                _autoCloseTimer.Tick += (s, e) =>
                {
                    _remainingSeconds--;
                    if (_remainingSeconds <= 0)
                    {
                        _autoCloseTimer.Stop();
                        DialogResult = true;
                        Close();
                    }
                    else
                    {
                        OkButton.Content = $"確定 ({_remainingSeconds}s)";
                    }
                };
                _autoCloseTimer.Start();
                break;
        }
    }

    private static readonly object SyncLock = new();
    private static string? _lastMessage;
    private static DateTimeOffset _lastShownTime;

    public static void Show(Window? owner, string title, string message, NotificationLevel level = NotificationLevel.Info)
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
            Application.Current.Dispatcher.Invoke(Action);
        }
        else
        {
            Action();
        }
    }

    private void OkButton_Click(object sender, RoutedEventArgs e)
    {
        _autoCloseTimer?.Stop();
        DialogResult = true;
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
