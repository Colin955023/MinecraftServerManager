using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.App.Services;

public sealed partial class WinUiService
{
    public IProgressSession<ServerBackupProgressReport> ShowServerBackupProgress(string serverName, bool isRestore = false)
    {
        string actionTitle = isRestore ? "還原" : "備份";
        string verb = isRestore ? "解壓縮" : "壓縮";
        string completedText = isRestore ? "還原完成！" : $"{actionTitle}壓縮完成！";
        return ShowProgressSession<ServerBackupProgressReport>(
            $"正在{actionTitle}伺服器「{serverName}」",
            isRestore ? "正在準備還原環境與解壓縮備份..." : "正在收集伺服器檔案...",
            report => (report.PercentCompleted, !string.IsNullOrWhiteSpace(report.CurrentFile)
                ? $"正在{verb}：{report.CurrentFile}"
                : (report.PercentCompleted >= 100 ? completedText : string.Empty)));
    }

    public IProgressSession<ServerImportProgressReport> ShowServerImportProgress(string serverName) =>
        ShowProgressSession<ServerImportProgressReport>(
            $"正在匯入伺服器「{serverName}」",
            "正在驗證伺服器目錄...",
            static report => (report.Percentage, report.StageText));

    public IProgressSession<ServerCreationProgressReport> ShowServerCreationProgress(string serverName) =>
        ShowProgressSession<ServerCreationProgressReport>(
            $"正在建立伺服器「{serverName}」",
            "正在驗證伺服器名稱與目錄...",
            static report => (report.PercentCompleted, $"[{report.Phase}] {report.Message}"));

    public IOperationProgress ShowOperationProgress(string title, string initialMessage)
    {
        var host = new ProgressDialogHost(this, title, initialMessage);
        return new OperationProgressHandle(host, new CoalescingProgress<(int Current, int Total, string Message)>(_dispatcherQueue, report =>
        {
            int percent = report.Total > 0 ? (int)Math.Round((double)report.Current / report.Total * 100) : 0;
            host.Update(percent, report.Message);
        }));
    }

    /// <summary>顯示進度對話框；失敗時記錄並標記完成，避免作業結束後殘留無法關閉的視窗</summary>
    private async Task ShowProgressDialogSafeAsync(OperationProgressDialog dialog)
    {
        try
        {
            await ShowCreatedDialogAsync(dialog);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "顯示進度對話框失敗");
            dialog.MarkCompleted();
        }
    }

    private ProgressSession<TReport> ShowProgressSession<TReport>(string heading, string initialMessage, Func<TReport, (int Percent, string Message)> map)
    {
        var host = new ProgressDialogHost(this, heading, initialMessage);
        var progress = new CoalescingProgress<TReport>(_dispatcherQueue, report =>
        {
            var (percent, message) = map(report);
            host.Update(percent, message);
        });
        return new ProgressSession<TReport>(progress, host);
    }

    /// <summary>進度對話框宿主：於 UI 執行緒建立與更新對話框，關閉早於建立時不再顯示</summary>
    private sealed class ProgressDialogHost
    {
        private readonly WinUiService _owner;
        private OperationProgressDialog? _dialog;
        private bool _closed;

        public ProgressDialogHost(WinUiService owner, string heading, string initialMessage)
        {
            _owner = owner;
            owner.RunOnUi(() =>
            {
                if (_closed)
                {
                    return;
                }

                _dialog = new OperationProgressDialog(owner, heading, initialMessage);
                _ = owner.ShowProgressDialogSafeAsync(_dialog);
            });
        }

        public void Update(int percent, string message) => _owner.RunOnUi(() =>
        {
            if (_closed)
            {
                return;
            }

            _dialog?.UpdateProgress(percent, message);
        });

        public void Close() => _owner.RunOnUi(() =>
        {
            _closed = true;
            _dialog?.Close();
        });
    }

    private sealed partial class ProgressSession<TReport>(IProgress<TReport> progress, ProgressDialogHost host) : IProgressSession<TReport>
    {
        public IProgress<TReport> Progress { get; } = progress;

        public void Dispose() => host.Close();
    }

    private sealed partial class OperationProgressHandle(ProgressDialogHost host, IProgress<(int Current, int Total, string Message)> progress) : IOperationProgress
    {
        public void UpdateProgress(int current, int total, string message) => progress.Report((current, total, message));

        public void Dispose() => host.Close();
    }
}
