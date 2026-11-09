using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 伺服器名單管理視窗（原生模態視窗，透過 ModalWindowHost 裝載）
/// </summary>
public sealed partial class PlayerManagementDialog : Window
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(PlayerManagementDialog));

    public PlayerManagementViewModel ViewModel { get; }
    public bool? DialogResult { get; private set; }

    public PlayerManagementDialog(PlayerManagementViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
        Title = "伺服器名單管理";

        WindowLayoutHelper.ResizeToDip(this, 1060, 740);

        if (Content is FrameworkElement fe)
        {
            fe.Loaded += async (_, _) =>
            {
                try
                {
                    await ViewModel.InitializeAsync().ConfigureAwait(true);
                }
                catch (Exception ex)
                {
                    Logger.Error(ex, "初始化名單管理失敗: {Message}", ex.Message);
                }
            };
        }

        ViewModel.RequestClose += success =>
        {
            DialogResult = success;
            // 延後至 async 命令完成後再關閉，避免命令結束時更新已關閉視窗的按鈕狀態造成原生閃退
            DispatcherQueue.TryEnqueue(Microsoft.UI.Dispatching.DispatcherQueuePriority.Low, Close);
        };

        AppWindow.Closing += async (sender, args) =>
        {
            try
            {
                if (DialogResult is null && ViewModel.HasUnsavedChanges)
                {
                    args.Cancel = true;
                    if (await ViewModel.ConfirmDiscardAsync().ConfigureAwait(true))
                    {
                        DialogResult = false;
                        Close();
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Warning(ex, "名單管理視窗關閉確認異常: {Message}", ex.Message);
            }
        };
    }

    private void RemoveWhitelist_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: ServerWhitelistEntry entry })
        {
            ViewModel.RemoveWhitelist(entry);
        }
    }

    private void RemoveBannedPlayer_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: ServerBannedPlayerEntry entry })
        {
            ViewModel.RemoveBannedPlayer(entry);
        }
    }

    private void RemoveBannedIp_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: ServerBannedIpEntry entry })
        {
            ViewModel.RemoveBannedIp(entry);
        }
    }

    private void OnOperatorSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.OperatorRows.SortBy(TableSortKeys.Operators, e);

    private void OnOperatorAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.OperatorRows, TableSortKeys.Operators);

    private void OnWhitelistSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.Whitelist.SortBy(TableSortKeys.Whitelist, e);

    private void OnWhitelistAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.Whitelist, TableSortKeys.Whitelist);

    private void OnBannedPlayerSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.BannedPlayers.SortBy(TableSortKeys.BannedPlayers, e);

    private void OnBannedPlayerAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.BannedPlayers, TableSortKeys.BannedPlayers);

    private void OnBannedIpSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.BannedIps.SortBy(TableSortKeys.BannedIps, e);

    private void OnBannedIpAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.BannedIps, TableSortKeys.BannedIps);
}
