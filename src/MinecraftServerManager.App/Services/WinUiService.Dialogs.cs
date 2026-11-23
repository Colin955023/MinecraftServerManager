using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.App.Services;

public sealed partial class WinUiService
{
    public Task<bool?> ShowManageJavaAsync(ManageJavaViewModel viewModel) =>
        ShowModalAsync(() => new ManageJavaWindow(viewModel));

    public Task<bool?> ShowJvmArgsAsync(JvmArgsViewModel viewModel) =>
        ShowContentBoolDialogAsync(() => new JvmArgsDialog(viewModel));

    public Task<bool?> ShowServerPropertiesAsync(ServerPropertiesViewModel viewModel) =>
        ShowModalAsync(() => new ServerPropertiesWindow(viewModel));

    public Task<bool?> ShowPlayerManagementAsync(PlayerManagementViewModel viewModel) =>
        ShowModalAsync(() => new PlayerManagementWindow(viewModel));

    public Task<bool?> ShowRestoreBackupAsync(RestoreBackupViewModel viewModel) =>
        ShowModalAsync(() => new RestoreBackupWindow(viewModel));

    public Task<bool?> ShowServerMemoryAsync(ServerMemoryViewModel viewModel) =>
        ShowContentBoolDialogAsync(() => new ServerMemoryDialog(viewModel));

    public Task<bool?> ShowImportServerAsync(ImportServerViewModel viewModel) =>
        ShowContentBoolDialogAsync(() => new ImportServerDialog(viewModel));

    public Task<bool?> ShowModVersionPickerAsync(ModVersionPickerViewModel viewModel) =>
        ShowModalAsync(() => new ModVersionPickerWindow(viewModel));

    public Task<bool?> ShowModInstallQueueAsync(ModInstallQueueReviewViewModel viewModel) =>
        ShowModalAsync(() => new ModInstallQueueWindow(viewModel));

    public Task<IReadOnlyList<ModUpdateCandidateItem>?> ShowModUpdatesAsync(ModUpdateSelectionViewModel viewModel) =>
        ShowModalAsync(() => new ModUpdatesWindow(viewModel), static d => ModalWindowHost.GetDialogResult(d) == true ? d.ViewModel.GetSelectedItems() : null);

    public Task<ServerDeleteDecision> ShowServerDeleteConfirmationAsync(string serverName, int backupCount)
    {
        AudioFeedback.PlayWarning();
        string message = backupCount > 0
            ? $"確定要刪除伺服器「{serverName}」嗎？\n\n這將永久刪除伺服器檔案，無法復原！\n\n偵測到此伺服器有 {backupCount} 個外部備份檔案，是否一併刪除？"
            : $"確定要刪除伺服器「{serverName}」嗎？\n\n這將永久刪除伺服器檔案，無法復原！";
        string primaryText = backupCount > 0 ? "連同備份一併刪除" : "確定刪除";
        string? secondaryText = backupCount > 0 ? "僅刪除伺服器" : null;

        return ShowContentDialogAsync(
            () => new CustomConfirmDialog(
                message,
                "刪除伺服器",
                UiMessageLevel.Warning,
                primaryButtonText: primaryText,
                secondaryButtonText: secondaryText,
                closeButtonText: "取消"),
            (dialog, result) => result switch
            {
                ContentDialogResult.Primary => backupCount > 0
                    ? ServerDeleteDecision.DeleteServerAndBackups
                    : ServerDeleteDecision.DeleteServerOnly,
                ContentDialogResult.Secondary => ServerDeleteDecision.DeleteServerOnly,
                _ => ServerDeleteDecision.Cancel,
            });
    }

    public Task<ModListExportFormat?> ShowExportModListAsync() =>
        ShowContentDialogAsync(
            static () => new ExportModListDialog(),
            static (dialog, result) => result == ContentDialogResult.Primary ? (ModListExportFormat?)dialog.SelectedFormat : null);

    public Task<bool> ShowServerInitializationAsync(ServerInitializationViewModel viewModel) =>
        ShowModalAsync(() => new ServerInitializationWindow(viewModel, this), static d =>
        {
            bool success = d.IsSuccess;
            d.Dispose();
            return success;
        });
}
