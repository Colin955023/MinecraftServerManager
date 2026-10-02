using System.IO;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 匯入伺服器對話框 ViewModel
/// </summary>
public sealed partial class ImportServerViewModel(IServerManager serverManager) : ObservableObject
{
    private readonly IServerManager _serverManager = serverManager;

    [ObservableProperty]
    private string _sourcePath = string.Empty;

    [ObservableProperty]
    private string _serverName = string.Empty;

    [ObservableProperty]
    private string _statusMessage = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsNotBusy))]
    private bool _isBusy;

    public bool IsNotBusy => !IsBusy;

    public string? ImportedServerName { get; private set; }

    public event Action<bool>? RequestClose;

    [RelayCommand]
    public void BrowseZip()
    {
        var dialog = new OpenFileDialog
        {
            Title = "選取 Minecraft 伺服器 ZIP 壓縮檔",
            Filter = "ZIP 壓縮檔 (*.zip)|*.zip|所有檔案 (*.*)|*.*",
            Multiselect = false
        };

        if (dialog.ShowDialog() == true)
        {
            SourcePath = dialog.FileName;
            if (string.IsNullOrWhiteSpace(ServerName))
            {
                ServerName = Path.GetFileNameWithoutExtension(dialog.FileName);
            }
        }
    }

    [RelayCommand]
    public void BrowseFolder()
    {
        var dialog = new OpenFolderDialog
        {
            Title = "選取 Minecraft 伺服器目錄",
            Multiselect = false
        };

        if (dialog.ShowDialog() == true)
        {
            SourcePath = dialog.FolderName;
            if (string.IsNullOrWhiteSpace(ServerName))
            {
                ServerName = Path.GetFileName(dialog.FolderName);
            }
        }
    }

    [RelayCommand]
    public async Task ImportAsync()
    {
        if (string.IsNullOrWhiteSpace(SourcePath))
        {
            StatusMessage = "請先選取來源目錄或 ZIP 壓縮檔";
            return;
        }

        if (string.IsNullOrWhiteSpace(ServerName))
        {
            StatusMessage = "請輸入匯入後的伺服器名稱";
            return;
        }

        IsBusy = true;
        StatusMessage = string.Empty;

        string targetName = ServerName.Trim();
        string source = SourcePath.Trim();

        var progressDialog = new ServerImportProgressDialog(targetName);
        if (Application.Current?.MainWindow is not null)
        {
            progressDialog.Owner = Application.Current.MainWindow;
        }

        // 開啟獨立進度視窗並在背景非同步執行匯入
        progressDialog.Show();
        var progress = progressDialog.Progress;

        try
        {
            var result = await Task.Run(() => _serverManager.ImportServerAsync(
                source,
                targetName,
                ImportTransferMode.Copy,
                progress)).ConfigureAwait(true);

            ServerImportProgressDialog.MarkCompleted();
            progressDialog.Close();

            if (result.Completed)
            {
                ImportedServerName = targetName;
                RequestClose?.Invoke(true);
            }
            else
            {
                StatusMessage = $"匯入失敗：{result.Message}";
            }
        }
        catch (Exception ex)
        {
            ServerImportProgressDialog.MarkCompleted();
            progressDialog.Close();
            StatusMessage = $"匯入異常：{ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    public void Cancel() => RequestClose?.Invoke(false);
}
