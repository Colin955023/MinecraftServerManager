using System.Windows;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 刪除伺服器確認結果列舉
/// </summary>
public enum ServerDeleteDecision
{
    Cancel,
    DeleteServerOnly,
    DeleteServerAndBackups
}

/// <summary>
/// 刪除伺服器確認對話框
/// </summary>
public partial class ServerDeleteConfirmationDialog : Window
{
    public ServerDeleteDecision Decision { get; private set; } = ServerDeleteDecision.Cancel;

    public ServerDeleteConfirmationDialog(string serverName, int backupCount)
    {
        InitializeComponent();

        if (Icon == null)
        {
            try
            {
                Icon = System.Windows.Media.Imaging.BitmapFrame.Create(
                    new Uri("pack://application:,,,/MinecraftServerManager.App;component/assets/icon.ico", UriKind.RelativeOrAbsolute));
            }
            catch
            {
            }
        }

        if (backupCount > 0)
        {
            MessageText.Text = $"確定要刪除伺服器「{serverName}」嗎？\n\n⚠️ 這將永久刪除伺服器檔案，無法復原！\n\n偵測到此伺服器有 {backupCount} 個外部備份檔案，是否一併刪除？\n（是：連同備份一併刪除 / 否：只刪除伺服器）";
            WithBackupsButtons.Visibility = Visibility.Visible;
            NoBackupsButtons.Visibility = Visibility.Collapsed;
        }
        else
        {
            MessageText.Text = $"確定要刪除伺服器「{serverName}」嗎？\n\n⚠️ 這將永久刪除伺服器檔案，無法復原！";
            WithBackupsButtons.Visibility = Visibility.Collapsed;
            NoBackupsButtons.Visibility = Visibility.Visible;
        }
    }

    private void OnYesClicked(object sender, RoutedEventArgs e)
    {
        Decision = ServerDeleteDecision.DeleteServerAndBackups;
        DialogResult = true;
    }

    private void OnNoClicked(object sender, RoutedEventArgs e)
    {
        Decision = ServerDeleteDecision.DeleteServerOnly;
        DialogResult = true;
    }

    private void OnConfirmClicked(object sender, RoutedEventArgs e)
    {
        Decision = ServerDeleteDecision.DeleteServerOnly;
        DialogResult = true;
    }

    private void OnCancelClicked(object sender, RoutedEventArgs e)
    {
        Decision = ServerDeleteDecision.Cancel;
        DialogResult = false;
    }
}
