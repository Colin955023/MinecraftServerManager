using System.ComponentModel;
using System.Windows;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 匯入伺服器獨立進度視窗
/// </summary>
public partial class ServerImportProgressDialog : Window
{
    private static bool _completed;
    private readonly IProgress<ServerImportProgressReport> _progress;

    public ServerImportProgressDialog(string serverName)
    {
        InitializeComponent();
        _completed = false;
        TitleText.Text = $"正在匯入伺服器「{serverName}」";
        _progress = new Progress<ServerImportProgressReport>(Report);

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
    /// 供背景匯入流程回報進度使用（已封送至 UI 執行緒）。
    /// </summary>
    public IProgress<ServerImportProgressReport> Progress => _progress;

    /// <summary>
    /// 標記流程結束，解除關閉鎖定。
    /// </summary>
    public static void MarkCompleted() => _completed = true;

    private void Report(ServerImportProgressReport report)
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.InvokeAsync(() => Report(report));
            return;
        }

        int percent = Math.Clamp(report.Percentage, 0, 100);
        ProgressBarControl.Value = percent;
        PercentText.Text = $"{percent}%";
        PhaseText.Text = report.StageText;
    }

    private void OnDialogClosing(object? sender, CancelEventArgs e) =>
        e.Cancel = !_completed;
}
