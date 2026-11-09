using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

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

        AppWindow.Resize(new Windows.Graphics.SizeInt32(1060, 740));

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
                Logger.Error(ex, "名單管理視窗關閉確認異常: {Message}", ex.Message);
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

    private void OnOperatorSortRequested(object? sender, SortRequestedEventArgs e)
    {
        if (ViewModel.OperatorRows.Count <= 1)
        {
            return;
        }

        ViewModel.OperatorRows.SortBy(e);
    }

    private void OnOperatorAutoFitRequested(object? sender, string propertyName)
    {
        if (ViewModel.OperatorRows.Count == 0)
        {
            return;
        }

        var cols = OperatorListColumns.Current;
        switch (propertyName)
        {
            case "IsOp":
                cols.IsOpWidth = new(SortableTableHeader.CalculateAutoFitWidth(OperatorListColumns.DefaultIsOpWidth, [], "管理員"));
                break;
            case "Name":
                cols.NameWidth = new(SortableTableHeader.CalculateAutoFitWidth(OperatorListColumns.DefaultNameWidth, ViewModel.OperatorRows.Select(r => r.Name), "玩家名稱"));
                break;
            case "Level":
                cols.LevelWidth = new(SortableTableHeader.CalculateAutoFitWidth(OperatorListColumns.DefaultLevelWidth, [], "權限等級"));
                break;
            case "BypassesPlayerLimit":
                cols.BypassWidth = new(SortableTableHeader.CalculateAutoFitWidth(OperatorListColumns.DefaultBypassWidth, [], "略過人數限制"));
                break;
            case "Uuid":
                cols.UuidWidth = new(SortableTableHeader.CalculateAutoFitWidth(OperatorListColumns.DefaultUuidWidth, ViewModel.OperatorRows.Select(r => r.Uuid), "UUID"));
                break;
        }
    }

    private void OnWhitelistSortRequested(object? sender, SortRequestedEventArgs e)
    {
        if (ViewModel.Whitelist.Count <= 1)
        {
            return;
        }

        ViewModel.Whitelist.SortBy(e);
    }

    private void OnWhitelistAutoFitRequested(object? sender, string propertyName)
    {
        if (ViewModel.Whitelist.Count == 0)
        {
            return;
        }

        var cols = WhitelistListColumns.Current;
        switch (propertyName)
        {
            case "Name":
                cols.NameWidth = new(SortableTableHeader.CalculateAutoFitWidth(WhitelistListColumns.DefaultNameWidth, ViewModel.Whitelist.Select(w => w.Name), "玩家名稱"));
                break;
            case "Uuid":
                cols.UuidWidth = new(SortableTableHeader.CalculateAutoFitWidth(WhitelistListColumns.DefaultUuidWidth, ViewModel.Whitelist.Select(w => w.Uuid), "UUID"));
                break;
        }
    }

    private void OnBannedPlayerSortRequested(object? sender, SortRequestedEventArgs e)
    {
        if (ViewModel.BannedPlayers.Count <= 1)
        {
            return;
        }

        ViewModel.BannedPlayers.SortBy(e);
    }

    private void OnBannedPlayerAutoFitRequested(object? sender, string propertyName)
    {
        if (ViewModel.BannedPlayers.Count == 0)
        {
            return;
        }

        var cols = BannedPlayerListColumns.Current;
        switch (propertyName)
        {
            case "Name":
                cols.NameWidth = new(SortableTableHeader.CalculateAutoFitWidth(BannedPlayerListColumns.DefaultNameWidth, ViewModel.BannedPlayers.Select(b => b.Name), "玩家名稱"));
                break;
            case "Reason":
                cols.ReasonWidth = new(SortableTableHeader.CalculateAutoFitWidth(BannedPlayerListColumns.DefaultReasonWidth, ViewModel.BannedPlayers.Select(b => b.Reason), "封鎖原因"));
                break;
            case "FormattedCreated":
                cols.CreatedWidth = new(SortableTableHeader.CalculateAutoFitWidth(BannedPlayerListColumns.DefaultCreatedWidth, ViewModel.BannedPlayers.Select(b => b.FormattedCreated), "封鎖時間"));
                break;
            case "Uuid":
                cols.UuidWidth = new(SortableTableHeader.CalculateAutoFitWidth(BannedPlayerListColumns.DefaultUuidWidth, ViewModel.BannedPlayers.Select(b => b.Uuid), "UUID"));
                break;
        }
    }

    private void OnBannedIpSortRequested(object? sender, SortRequestedEventArgs e)
    {
        if (ViewModel.BannedIps.Count <= 1)
        {
            return;
        }

        ViewModel.BannedIps.SortBy(e);
    }

    private void OnBannedIpAutoFitRequested(object? sender, string propertyName)
    {
        if (ViewModel.BannedIps.Count == 0)
        {
            return;
        }

        var cols = BannedIpListColumns.Current;
        switch (propertyName)
        {
            case "Ip":
                cols.IpWidth = new(SortableTableHeader.CalculateAutoFitWidth(BannedIpListColumns.DefaultIpWidth, ViewModel.BannedIps.Select(b => b.Ip), "IP 位址"));
                break;
            case "Reason":
                cols.ReasonWidth = new(SortableTableHeader.CalculateAutoFitWidth(BannedIpListColumns.DefaultReasonWidth, ViewModel.BannedIps.Select(b => b.Reason), "封鎖原因"));
                break;
            case "FormattedCreated":
                cols.CreatedWidth = new(SortableTableHeader.CalculateAutoFitWidth(BannedIpListColumns.DefaultCreatedWidth, ViewModel.BannedIps.Select(b => b.FormattedCreated), "封鎖時間"));
                break;
        }
    }
}
