using System.ComponentModel;
using System.Windows;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 備份伺服器獨立進度視窗
/// </summary>
public partial class ServerBackupProgressDialog : Window
{
    private static bool _completed;
    private readonly IProgress<ServerBackupProgressReport> _progress;

    public ServerBackupProgressDialog(string serverName)
    {
        InitializeComponent();
        _completed = false;
        TitleText.Text = $"正在備份伺服器「{serverName}」";
        _progress = new Progress<ServerBackupProgressReport>(Report);

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

        Closing += OnDialogClosing;
    }

    /// <summary>
    /// 供背景備份流程回報進度使用（已封送至 UI 執行緒）。
    /// </summary>
    public IProgress<ServerBackupProgressReport> Progress => _progress;

    /// <summary>
    /// 標記流程結束，解除關閉鎖定。
    /// </summary>
    public static void MarkCompleted() => _completed = true;

    private void Report(ServerBackupProgressReport report)
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.InvokeAsync(() => Report(report));
            return;
        }

        int percent = Math.Clamp(report.PercentCompleted, 0, 100);
        ProgressBarControl.Value = percent;
        PercentText.Text = $"{percent}%";

        if (!string.IsNullOrWhiteSpace(report.CurrentFile))
        {
            PhaseText.Text = $"正在壓縮: {report.CurrentFile}";
        }
        else if (percent >= 100)
        {
            PhaseText.Text = "備份壓縮完成！";
        }
    }

    private void OnDialogClosing(object? sender, CancelEventArgs e) =>
        e.Cancel = !_completed;
}
