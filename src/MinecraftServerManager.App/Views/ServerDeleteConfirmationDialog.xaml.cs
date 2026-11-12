using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>刪除伺服器確認 WinUI 3 原生 ContentDialog</summary>
public sealed partial class ServerDeleteConfirmationDialog : ContentDialog
{
    private readonly int _backupCount;

    public ServerDeleteDecision Decision { get; private set; } = ServerDeleteDecision.Cancel;
    public string Message { get; }
    public string PrimaryText { get; }
    public string SecondaryText { get; }

    public ServerDeleteConfirmationDialog(string serverName, int backupCount)
    {
        _backupCount = backupCount;
        InitializeComponent();

        if (backupCount > 0)
        {
            Message = $"確定要刪除伺服器「{serverName}」嗎？\n\n⚠️ 這將永久刪除伺服器檔案，無法復原！\n\n偵測到此伺服器有 {backupCount} 個外部備份檔案，是否一併刪除？";
            PrimaryText = "連同備份一併刪除";
            SecondaryText = "僅刪除伺服器";
        }
        else
        {
            Message = $"確定要刪除伺服器「{serverName}」嗎？\n\n⚠️ 這將永久刪除伺服器檔案，無法復原！";
            PrimaryText = "確定刪除";
            SecondaryText = string.Empty;
        }
    }

    private void Dialog_PrimaryButtonClick(ContentDialog sender, ContentDialogButtonClickEventArgs args) =>
        Decision = _backupCount > 0 ? ServerDeleteDecision.DeleteServerAndBackups : ServerDeleteDecision.DeleteServerOnly;

    private void Dialog_SecondaryButtonClick(ContentDialog sender, ContentDialogButtonClickEventArgs args) =>
        Decision = ServerDeleteDecision.DeleteServerOnly;
}
