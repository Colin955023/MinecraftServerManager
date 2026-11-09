using System.ComponentModel;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 通用非同步作業進度 WinUI 3 原生 ContentDialog
/// </summary>
public sealed partial class OperationProgressDialog : ContentDialog, INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    private readonly IUiService _ui;
    private bool _completed;
    private bool _allowNestedHide;

    public string DialogHeading { get; }
    public string PhaseMessage { get; private set; }
    public double ProgressValue { get; private set; }
    public string PercentDisplay { get; private set; } = "0%";

    public OperationProgressDialog(IUiService ui, string windowTitle, string heading, string initialMessage)
    {
        ArgumentNullException.ThrowIfNull(ui);
        InitializeComponent();

        _ui = ui;
        _ = windowTitle;
        DialogHeading = heading;
        PhaseMessage = initialMessage;

        // 作業在對話框真正顯示（或被巢狀對話框中斷後重新顯示）之前就已完成時，開啟後立即關閉，避免殘留卡住主視窗
        Opened += (_, _) =>
        {
            if (_completed)
            {
                Hide();
            }
        };
    }

    private void ContentDialog_Closing(ContentDialog sender, ContentDialogClosingEventArgs args)
    {
        if (_allowNestedHide)
        {
            // 讓位給巢狀對話框的暫時隱藏，待上層關閉後由協調器重新顯示
            _allowNestedHide = false;
            return;
        }

        if (!_completed)
        {
            args.Cancel = true;
        }
    }

    public void MarkCompleted() => _completed = true;

    /// <summary>
    /// 暫時隱藏以讓位給巢狀對話框（作業尚未完成時亦允許）
    /// </summary>
    public void HideForNestedDialog()
    {
        _allowNestedHide = true;
        Hide();
    }

    public void Close()
    {
        _completed = true;
        _ui.RunOnUi(Hide);
    }

    public void UpdateProgress(int percent, string message)
    {
        int pct = Math.Clamp(percent, 0, 100);
        _ui.RunOnUi(() =>
        {
            ProgressValue = pct;
            PercentDisplay = $"{pct}%";
            if (!string.IsNullOrWhiteSpace(message))
            {
                PhaseMessage = message;
            }
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ProgressValue)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(PercentDisplay)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(PhaseMessage)));
        });
    }

    public void UpdateProgress(int current, int total, string message)
    {
        int pct = total > 0 ? (int)Math.Clamp(current * 100.0 / total, 0, 100) : 0;
        _ui.RunOnUi(() =>
        {
            ProgressValue = pct;
            PercentDisplay = $"{pct}% ({current}/{total})";
            if (!string.IsNullOrWhiteSpace(message))
            {
                PhaseMessage = message;
            }
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ProgressValue)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(PercentDisplay)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(PhaseMessage)));
        });
    }
}
