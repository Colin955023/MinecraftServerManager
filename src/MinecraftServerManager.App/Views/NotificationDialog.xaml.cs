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
                break;
        }
    }

    public static void Show(Window? owner, string title, string message, NotificationLevel level = NotificationLevel.Info)
    {
        void Action()
        {
            var dialog = new NotificationDialog(title, message, level);
            Window? effectiveOwner = owner ?? Application.Current?.MainWindow;
            if (effectiveOwner != null && effectiveOwner.IsVisible)
            {
                dialog.Owner = effectiveOwner;
                dialog.WindowStartupLocation = WindowStartupLocation.CenterOwner;
            }
            else
            {
                dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen;
            }

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
        DialogResult = true;
        Close();
    }
}
