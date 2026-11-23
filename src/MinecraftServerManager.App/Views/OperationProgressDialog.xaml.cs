using System.ComponentModel;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>通用非同步作業進度對話方塊</summary>
public sealed partial class OperationProgressDialog : ContentDialog, INotifyPropertyChanged, INestableContentDialog
{
    private static readonly PropertyChangedEventArgs PhaseMessageChangedArgs = new(nameof(PhaseMessage));
    private static readonly PropertyChangedEventArgs ProgressValueChangedArgs = new(nameof(ProgressValue));
    private static readonly PropertyChangedEventArgs PercentDisplayChangedArgs = new(nameof(PercentDisplay));

    private readonly IUiService _ui;
    // 進度可能由背景執行緒回報與完成：完成旗標用 volatile，去重狀態以鎖保護
    private readonly Lock _reportLock = new();
    private volatile bool _completed;
    private bool _allowNestedHide;
    private int _lastReportedPercent = -1;
    private string? _lastReportedMessage;

    public OperationProgressDialog(IUiService ui, string heading, string initialMessage)
    {
        ArgumentNullException.ThrowIfNull(ui);

        _ui = ui;
        DialogHeading = heading;
        PhaseMessage = initialMessage;

        InitializeComponent();

        // 作業在對話框顯示前就已完成時，開啟後立即關閉
        Opened += (_, _) =>
        {
            if (_completed)
            {
                Hide();
            }
        };
        Closed += (_, _) =>
        {
            if (_completed)
            {
                Bindings.StopTracking();
            }
        };
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public string DialogHeading { get; }

    public string PhaseMessage { get; private set; }

    public double ProgressValue { get; private set; }

    public string PercentDisplay { get; private set; } = "0%";

    public void MarkCompleted() => _completed = true;

    /// <summary>暫時隱藏以讓位給巢狀對話框（作業尚未完成時亦允許）</summary>
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

        // 高頻回報時略過與上次相同的內容，避免無謂的 UI 執行緒排程與整體屬性通知
        lock (_reportLock)
        {
            if (pct == _lastReportedPercent && string.Equals(message, _lastReportedMessage, StringComparison.Ordinal))
            {
                return;
            }

            _lastReportedPercent = pct;
            _lastReportedMessage = message;
        }

        _ui.RunOnUi(() =>
        {
            if (_completed)
            {
                return;
            }

            ProgressValue = pct;
            PercentDisplay = $"{pct}%";
            PropertyChanged?.Invoke(this, ProgressValueChangedArgs);
            PropertyChanged?.Invoke(this, PercentDisplayChangedArgs);
            if (!string.IsNullOrWhiteSpace(message))
            {
                PhaseMessage = message;
                PropertyChanged?.Invoke(this, PhaseMessageChangedArgs);
            }
        });
    }

    private void OnDialogClosing(ContentDialog sender, ContentDialogClosingEventArgs args)
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
}
